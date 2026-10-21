"""Bounded Streamlink -> FFmpeg -> latest PNG pipeline. No image files or credentials."""

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import re
import struct
import subprocess
import sys
import threading
import time

from PIL import Image

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_PNG_BYTES = 32 * 1024 * 1024
MAX_PIXELS = 4096 * 2160


class CaptureError(RuntimeError):
    """A safe reason code; raw subprocess logs may contain signed URLs."""


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            raise EOFError
        data.extend(chunk)
    return bytes(data)


def read_png(stream):
    """Read a framed PNG from image2pipe, without unbounded buffering."""
    signature = read_exact(stream, 8)
    if signature != PNG_SIGNATURE:
        raise CaptureError("invalid_decoder_output")
    result = bytearray(signature)
    while True:
        header = read_exact(stream, 8)
        length, name = struct.unpack(">I4s", header)
        if len(result) + 12 + length > MAX_PNG_BYTES:
            raise CaptureError("frame_exceeds_byte_limit")
        content = read_exact(stream, length + 4)
        if name == b"IHDR":
            if length != 13:
                raise CaptureError("invalid_png_header")
            width, height = struct.unpack(">II", content[:8])
            if width * height > MAX_PIXELS:
                raise CaptureError("frame_exceeds_pixel_limit")
        result.extend(header)
        result.extend(content)
        if name == b"IEND":
            return bytes(result)


@dataclass(frozen=True)
class Source:
    kind: str  # file, hls (authorized HTTP input), twitch (anonymous public playback)
    value: str
    quality: str = "best"

    def streamlink_command(self):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", self.quality):
            raise ValueError("Use a single named rendition, best or worst")
        if self.kind == "twitch":
            if not re.fullmatch(r"[A-Za-z0-9_]{1,25}", self.value):
                raise ValueError("Use a Twitch channel login, not a URL")
            url = "https://www.twitch.tv/" + self.value
        elif self.kind == "hls":
            if not self.value.startswith(("http://", "https://")):
                raise ValueError("HLS input must be an explicitly authorized HTTP(S) URL")
            url = "hls://" + self.value
        else:
            raise ValueError("Not a Streamlink source")
        return [sys.executable, "-m", "streamlink", "--no-config", "--no-plugin-cache",
                "--no-plugin-sideloading", "--webbrowser", "false", "--loglevel", "error",
                "--http-timeout", "10", "--stream-timeout", "15", "--stream-segment-timeout", "10",
                "--stream-segment-attempts", "2", "--stream-segment-threads", "1",
                "--ringbuffer-size", "4M", "--hls-live-edge", "2", "--stdout", url, self.quality]


def ffmpeg_command(executable, source, *, file_offset=0, keyframes_only=True):
    command = [executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-threads", "1"]
    if keyframes_only:
        command += ["-skip_frame", "nokey"]
    if source.kind == "file":
        if file_offset:
            command += ["-ss", f"{file_offset:.6f}"]
        command += ["-re", "-i", str(Path(source.value).resolve())]
    else:
        command += ["-probesize", "262144", "-analyzeduration", "1000000", "-i", "pipe:0"]
    # Decode keyframes by default; do not encode more than one preview/second.
    # This reduces CPU, NOT downloaded video bytes. The reader always drains output.
    command += ["-an", "-sn", "-dn", "-vf", "select=isnan(prev_selected_t)+gte(t-prev_selected_t\\,1)",
                "-fps_mode", "vfr", "-c:v", "png", "-threads", "1", "-f", "image2pipe", "pipe:1"]
    return command


@dataclass(frozen=True)
class Frame:
    png: bytes
    sequence: int
    arrived_monotonic: float
    received_at: str

    def image(self):
        with Image.open(BytesIO(self.png)) as image:
            return image.convert("RGB")


class VideoSession:
    """One connection and decoder, one latest frame, bounded stderr and byte counters."""

    def __init__(self, source, *, ffmpeg="ffmpeg", file_offset=0, keyframes_only=True):
        self.condition = threading.Condition()
        self.latest = None
        self.error = None
        self.stopping = False
        self.source_bytes = 0
        self.source = source
        self.logs = {"streamlink": bytearray(), "ffmpeg": bytearray()}
        self.threads = []
        self.producer = None
        self.decoder = None
        try:
            if source.kind != "file":
                self.producer = subprocess.Popen(source.streamlink_command(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self._thread(self._logs, self.producer.stderr, "streamlink")
            self.decoder = subprocess.Popen(ffmpeg_command(ffmpeg, source, file_offset=file_offset,
                                                           keyframes_only=keyframes_only),
                                            stdin=subprocess.PIPE if self.producer else subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self._thread(self._logs, self.decoder.stderr, "ffmpeg")
            if self.producer:
                self._thread(self._relay)
            self._thread(self._frames)
        except (OSError, ValueError):
            self.close()
            raise

    def _thread(self, function, *args):
        thread = threading.Thread(target=function, args=args, daemon=True)
        self.threads.append(thread)
        thread.start()

    def _logs(self, pipe, name):
        while chunk := pipe.read1(1024):
            self.logs[name].extend(chunk)
            del self.logs[name][:-16384]

    def _relay(self):
        try:
            while not self.stopping:
                # Forward available bytes; filling the buffer can stall a live source.
                chunk = self.producer.stdout.read1(16384)
                if not chunk:
                    break
                self.source_bytes += len(chunk)
                self.decoder.stdin.write(chunk)
                self.decoder.stdin.flush()
        except (OSError, ValueError):
            pass
        finally:
            try:
                self.decoder.stdin.close()
            except OSError:
                pass

    def _frames(self):
        try:
            while not self.stopping:
                png = read_png(self.decoder.stdout)
                with self.condition:
                    sequence = self.latest.sequence + 1 if self.latest else 1
                    self.latest = Frame(png, sequence, time.monotonic(), datetime.now(timezone.utc).isoformat())
                    self.condition.notify_all()
        except EOFError:
            self.error = "source_ended"
        except (OSError, CaptureError):
            self.error = "decoder_failed"
        finally:
            with self.condition:
                self.condition.notify_all()

    def reason(self):
        text = bytes(self.logs["streamlink"]).lower()
        if b"no playable streams" in text or b"no streams found" in text:
            return "offline_or_unavailable"
        if any(value in text for value in (b"name resolution", b"getaddrinfo", b"failed to resolve",
                                           b"winerror 10013", b"network is unreachable", b"connection refused")):
            return "network_unavailable"
        if b"403" in text or b"client-integrity" in text or b"access denied" in text:
            return "access_denied"
        return self.error or "frame_timeout"

    def frame(self, *, after_sequence=0, timeout=20, max_age=5):
        deadline = time.monotonic() + timeout
        with self.condition:
            while True:
                if self.latest and self.latest.sequence > after_sequence:
                    if time.monotonic() - self.latest.arrived_monotonic <= max_age:
                        return self.latest
                if self.error:
                    raise CaptureError(self.reason())
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CaptureError(self.reason())
                self.condition.wait(min(remaining, .2))

    def close(self):
        self.stopping = True
        for process in (self.producer, self.decoder):
            if process and process.poll() is None:
                process.terminate()
        for process in (self.producer, self.decoder):
            if process:
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        for thread in self.threads:
            thread.join(timeout=1)
        for process in (self.producer, self.decoder):
            if process:
                for pipe in (process.stdin, process.stdout, process.stderr):
                    if pipe and not pipe.closed:
                        pipe.close()
