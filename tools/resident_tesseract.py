"""Opt-in resident libtesseract (C API via ctypes) in isolated, reused worker processes.

multi_alpha --resident-tesseract gives each capture attempt a TesseractPool, set as
exp_tracker.recognition.ocr_engine for that attempt only. The goal is to reproduce
pytesseract.image_to_data(..., output_type=DICT) exactly, for the configurations
exp_tracker.recognition._ocr builds, without starting a Tesseract process per call.

- The library, tessdata directory and version come from the SAME configured CLI
  (`--list-langs`, `--version`); a version mismatch refuses to start.
- Pixels are the 8-bit grayscale images pytesseract would have saved as PNG.
- TSV comes from TessBaseAPIGetTsvText and is parsed by pytesseract's own file_to_dict.
- Page segmentation mode and the whitelist are set on EVERY request (including an empty
  whitelist), and results plus adaptive-classifier state are cleared after each one.
- The worker (`--serve`) owns one engine. A timeout, crash or malformed reply kills it;
  the next request starts a fresh one, as ResidentNeural does. No engine runs in-process.
- Parity evidence, limits and operation: docs/performance-integration.md.
"""

import ctypes
import ctypes.util
import glob
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import struct
import subprocess
import sys
import threading
import time

if __name__ == '__main__':  # The worker runs as a script, possibly from a venv without this checkout.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from exp_tracker.video import CaptureError  # noqa: E402

HEADER = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
MAX_PIXELS = 20_000_000       # scan() caps at 1080p-equivalent x 3 per side = 18.7 MP.
MAX_REPLY = 8 * 1024 * 1024
REQUEST = struct.Struct('!IIII')  # psm, whitelist bytes, width, height; then whitelist, pixels.


def installation(command):
    """Library, tessdata directory, versions and model hash of the configured Tesseract CLI."""
    def run(*args):
        result = subprocess.run([command, *args], capture_output=True, text=True, timeout=30)
        return result.stdout + result.stderr
    found = re.search(r'List of available languages in "(.+?)"', run('--list-langs'))
    if not found:
        raise RuntimeError('Cannot read the CLI tessdata directory from --list-langs')
    datapath = str(Path(found.group(1)))
    cli = re.search(r'tesseract v?(\S+)', run('--version'))
    library = os.environ.get('MSXP_LIBTESSERACT')
    if not library and os.name == 'nt':
        matches = sorted(glob.glob(str(Path(command).resolve().parent / 'libtesseract*.dll')))
        library = matches[0] if matches else None
    library = library or ctypes.util.find_library('tesseract')
    if not library:
        raise RuntimeError('libtesseract not found; set MSXP_LIBTESSERACT to the installed library')
    model = Path(datapath) / 'eng.traineddata'
    return dict(library=library, datapath=datapath, cli_version=cli.group(1) if cli else None,
                model=str(model), model_sha256=hashlib.sha256(model.read_bytes()).hexdigest())


class NativeTesseract:
    """One TessBaseAPI handle. Not thread-safe: use one instance per thread or process."""

    def __init__(self, info, lang='eng'):
        if os.name == 'nt':
            os.add_dll_directory(str(Path(info['library']).parent))
        lib = self.lib = ctypes.CDLL(info['library'])
        handle, text = ctypes.c_void_p, ctypes.c_char_p
        for name, args, result in [
                ('TessVersion', [], text), ('TessBaseAPICreate', [], handle),
                ('TessBaseAPIInit3', [handle, text, text], ctypes.c_int),
                ('TessBaseAPISetPageSegMode', [handle, ctypes.c_int], None),
                ('TessBaseAPISetVariable', [handle, text, text], ctypes.c_int),
                ('TessBaseAPISetImage', [handle, text, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int], None),
                ('TessBaseAPIGetTsvText', [handle, ctypes.c_int], handle),
                ('TessDeleteText', [handle], None), ('TessBaseAPIClear', [handle], None),
                ('TessBaseAPIClearAdaptiveClassifier', [handle], None),
                ('TessBaseAPIEnd', [handle], None), ('TessBaseAPIDelete', [handle], None)]:
            function = getattr(lib, name)
            function.argtypes, function.restype = args, result
        self.version = lib.TessVersion().decode().removeprefix('v')  # Windows builds report 'v5.4.0...'.
        if info['cli_version'] != self.version:
            raise RuntimeError(f"libtesseract {self.version} differs from CLI {info['cli_version']}")
        started = time.perf_counter()
        self.api = lib.TessBaseAPICreate()
        if lib.TessBaseAPIInit3(self.api, info['datapath'].encode(), lang.encode()):
            lib.TessBaseAPIDelete(self.api)
            self.api = None
            raise RuntimeError('TessBaseAPIInit3 failed')
        self.init_seconds = time.perf_counter() - started

    def tsv(self, mode, size, pixels, psm, whitelist='', timeout=None):
        """TSV rows (no header) for 8-bit grayscale pixels, exactly as recognition passes them.

        timeout is accepted for interface parity but CANNOT be enforced in-process; only the
        worker process (ResidentTesseract) bounds a hung call.
        """
        width, height = size
        if mode != 'L' or len(pixels) != width * height or not 0 < width * height <= MAX_PIXELS:
            raise ValueError('Expected an 8-bit grayscale image within the pixel limit')
        lib, api = self.lib, self.api
        lib.TessBaseAPISetPageSegMode(api, psm)
        if not lib.TessBaseAPISetVariable(api, b'tessedit_char_whitelist', whitelist.encode()):
            raise RuntimeError('Cannot set the whitelist')
        lib.TessBaseAPISetImage(api, pixels, width, height, 1, width)  # Copied into a Leptonica Pix.
        pointer = lib.TessBaseAPIGetTsvText(api, 0)
        try:
            if not pointer:
                raise RuntimeError('Tesseract returned no TSV')
            return ctypes.string_at(pointer).decode('utf-8')
        finally:
            if pointer:
                lib.TessDeleteText(pointer)
            lib.TessBaseAPIClear(api)
            lib.TessBaseAPIClearAdaptiveClassifier(api)

    def close(self):
        if self.api:
            self.lib.TessBaseAPIEnd(self.api)
            self.lib.TessBaseAPIDelete(self.api)
            self.api = None


def as_data(tsv):
    from pytesseract.pytesseract import file_to_dict
    return file_to_dict(HEADER + tsv, '\t', -1)


def _frame(stream, limit):
    header = stream.read(4)
    if len(header) != 4:
        raise EOFError
    length = struct.unpack('!I', header)[0]
    if length > limit:
        raise ValueError('Frame exceeds limit')
    payload = stream.read(length)
    if len(payload) != length:
        raise EOFError
    return payload


def _send(stream, payload):
    stream.write(struct.pack('!I', len(payload)) + payload)
    stream.flush()


def serve(command):
    """Worker: identity (or startup error) frame, then one TSV frame per request. Any error exits non-zero."""
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    try:
        info = installation(command)
        engine = NativeTesseract(info)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        _send(stdout, json.dumps(dict(error=f'{type(error).__name__}: {error}')).encode())
        raise SystemExit(1) from None
    _send(stdout, json.dumps(dict(info, version=engine.version, init_seconds=engine.init_seconds,
                                  pid=os.getpid())).encode())
    while True:
        try:
            header = stdin.read(REQUEST.size)
        except OSError:
            return
        if not header:
            engine.close()
            return
        psm, length, width, height = REQUEST.unpack(header)
        if length > 256 or not 0 < width * height <= MAX_PIXELS:
            raise ValueError('Request exceeds limits')
        whitelist = stdin.read(length).decode('ascii')
        pixels = stdin.read(width * height)
        if len(pixels) != width * height:
            raise EOFError
        _send(stdout, engine.tsv('L', (width, height), pixels, psm, whitelist).encode('utf-8'))


class ResidentTesseract:
    """Client for ONE worker process; requests are serialized. TesseractPool holds several."""

    def __init__(self, command, *, timeout=10, start_timeout=30):
        self.command, self.timeout, self.start_timeout = command, timeout, start_timeout
        self.lock = threading.Lock()
        self.process = self.replies = self.identity = self.error = None
        self.starts = self.requests = self.failures = 0
        self.closed = False

    @staticmethod
    def _read(process, replies):
        try:
            while True:
                replies.put(_frame(process.stdout, MAX_REPLY))
        except (OSError, ValueError, EOFError):
            replies.put(None)

    @staticmethod
    def _write(process, data):
        try:
            process.stdin.write(data)
            process.stdin.flush()
        except (OSError, ValueError):
            pass  # A dead worker surfaces as EOF to the reader.

    def _reply(self, timeout, reason):
        try:
            reply = self.replies.get(timeout=timeout)
        except queue.Empty:
            self._stop()
            raise CaptureError(f'tesseract_worker_{reason}_timeout') from None
        if reply is None:
            self._stop()
            raise CaptureError('tesseract_worker_failed')
        return reply

    def _start(self):
        self._stop()
        # One OCR thread per worker, as multi_alpha sets for the CLI; the pool provides parallelism.
        self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
        # close() sets closed before reading self.process, so a close racing this start is seen
        # either here or by close() itself; never both missed.
        if self.closed:
            self._stop()
            raise CaptureError('tesseract_worker_closed')
        self.replies = queue.Queue()
        self.starts += 1
        threading.Thread(target=self._read, args=(self.process, self.replies), daemon=True).start()
        identity = json.loads(self._reply(self.start_timeout, 'start'))
        if 'error' in identity:
            self.error = identity['error']
            self._stop()
            raise CaptureError('tesseract_worker_unavailable')
        self.identity = identity

    def tsv(self, mode, size, pixels, psm, whitelist='', timeout=None):
        width, height = size
        if mode != 'L' or len(pixels) != width * height or not 0 < width * height <= MAX_PIXELS:
            raise ValueError('Expected an 8-bit grayscale image within the pixel limit')
        with self.lock:
            self.requests += 1
            try:
                if self.closed:
                    raise CaptureError('tesseract_worker_closed')  # Never restart after shutdown.
                if self.process is None or self.process.poll() is not None:
                    self._start()
                encoded = whitelist.encode('ascii')
                data = REQUEST.pack(psm, len(encoded), width, height) + encoded + pixels
                # Write off-thread: a hung worker with a full pipe must not outlive the timeout.
                threading.Thread(target=self._write, args=(self.process, data), daemon=True).start()
                return self._reply(timeout or self.timeout, 'request').decode('utf-8')
            except (OSError, RuntimeError, ValueError):
                self.failures += 1
                raise

    def _stop(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        for pipe in (process.stdin, process.stdout):
            try:
                pipe.close()
            except OSError:
                pass

    def close(self):
        self.closed = True
        self._stop()

    def snapshot(self):
        process = self.process
        return dict(pid=process.pid if process else None, starts=self.starts, requests=self.requests,
                    failures=self.failures)


class TesseractPool:
    """At most `size` isolated workers, one request each at a time; callers wait for a free one.

    Workers start on first use and LIFO reuse keeps warm ones busy, so more start only when
    calls actually overlap. Each call is a whole request and reply on one worker, so
    concurrent captures never share a reply or engine state.
    """

    def __init__(self, command, size, *, timeout=10, start_timeout=30):
        self.workers = [ResidentTesseract(command, timeout=timeout, start_timeout=start_timeout) for _ in range(size)]
        self.idle = queue.LifoQueue()
        for worker in reversed(self.workers):
            self.idle.put(worker)
        self.lock = threading.Lock()
        self.calls, self.wait_seconds, self.max_wait_seconds = 0, 0.0, 0.0

    def __call__(self, image, psm, whitelist='', *, metrics=None):
        """One recognition._ocr call: the image_to_data DICT pytesseract would return."""
        queued = time.monotonic()
        worker = self.idle.get()
        waited = time.monotonic() - queued
        with self.lock:
            self.calls += 1
            self.wait_seconds += waited
            self.max_wait_seconds = max(self.max_wait_seconds, waited)
        if metrics is not None:
            metrics['tesseract_calls'] = metrics.get('tesseract_calls', 0) + 1
            metrics['tesseract_queue_wait_seconds'] = metrics.get('tesseract_queue_wait_seconds', 0) + waited
        try:
            return as_data(worker.tsv(image.mode, image.size, image.tobytes(), psm, whitelist))
        finally:
            self.idle.put(worker)

    def check(self):
        """Start one worker now, so a missing library or version mismatch stops startup clearly."""
        worker = self.idle.get()
        try:
            worker.tsv('L', (1, 1), b'\xff', 7)
        except CaptureError as error:
            raise RuntimeError(f'Resident Tesseract unavailable ({error}): {worker.error or "no identity from worker"}. '
                               'Install the libtesseract matching the tesseract CLI or set MSXP_LIBTESSERACT; '
                               'nothing was installed or changed. Or run without --resident-tesseract') from None
        finally:
            self.idle.put(worker)
        return worker.identity

    def snapshot(self):
        with self.lock:
            return dict(size=len(self.workers), calls=self.calls, queue_wait_seconds=round(self.wait_seconds, 3),
                        max_queue_wait_seconds=round(self.max_wait_seconds, 3),
                        workers=[worker.snapshot() for worker in self.workers])

    def close(self):
        # Lock-free, as ResidentNeural: at shutdown an abandoned attempt may still hold a worker.
        for worker in self.workers:
            worker.close()


def worker_command():
    from exp_tracker.recognition import configure_tesseract
    import pytesseract
    configure_tesseract()
    return [sys.executable, str(Path(__file__).resolve()), '--serve', pytesseract.pytesseract.tesseract_cmd]


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--serve':
        serve(sys.argv[2])
    else:
        raise SystemExit('Usage: resident_tesseract.py --serve TESSERACT_CLI (started by ResidentTesseract)')
