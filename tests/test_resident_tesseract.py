"""Resident libtesseract workers: isolation, recovery, pool bounds and exact pytesseract parity."""

import json
import sys
import threading
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import pytest
import pytesseract

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import resident_tesseract as native  # noqa: E402
from exp_tracker import recognition  # noqa: E402
from exp_tracker.video import CaptureError  # noqa: E402

DICT = pytesseract.Output.DICT

FAKE = r'''
import json, os, struct, sys, time
def send(data):
    sys.stdout.buffer.write(struct.pack('!I', len(data)) + data); sys.stdout.buffer.flush()
if os.environ.get('FAKE_INIT_ERROR'):
    send(json.dumps(dict(error='RuntimeError: libtesseract not found')).encode()); sys.exit(1)
if os.environ.get('FAKE_SLOW_START'): time.sleep(30)
send(json.dumps(dict(pid=os.getpid(), init_seconds=0, threads=os.environ.get('OMP_THREAD_LIMIT'))).encode())
while header := sys.stdin.buffer.read(16):
    psm, length, width, height = struct.unpack('!IIII', header)
    whitelist = sys.stdin.buffer.read(length).decode(); pixels = sys.stdin.buffer.read(width * height)
    if psm == 99: time.sleep(30)
    if psm == 98: sys.exit(1)
    if psm == 97: sys.stdout.buffer.write(struct.pack('!I', 1 << 30)); sys.stdout.buffer.flush(); time.sleep(30)
    if psm == 96: time.sleep(.05)
    # One TSV word echoing the request, so a reply can be matched to the request it answers.
    send(f'5\t1\t1\t1\t1\t1\t{psm}\t{width}\t{height}\t{os.getpid()}\t96\t{whitelist or "none"}\n'.encode())
'''


@pytest.fixture
def fake(tmp_path):
    script = tmp_path / 'fake_worker.py'
    script.write_text(FAKE)
    return [sys.executable, str(script)]


@pytest.fixture
def worker(fake):
    client = native.ResidentTesseract(fake, timeout=10)
    yield client
    client.close()
    assert client.process is None


def test_worker_is_reused_and_replaced_after_timeout_crash_or_oversized_reply(worker):
    def ask(psm, timeout=None):
        return worker.tsv('L', (3, 2), bytes(6), psm, '012', timeout=timeout).split('\t')
    first, second = ask(7), ask(11)
    assert first[9] == second[9] and first[6:9] == ['7', '3', '2'] and worker.starts == 1
    assert worker.identity['threads'] == '1'           # One OCR thread per worker process.
    with pytest.raises(CaptureError, match='request_timeout'):
        ask(99, timeout=.5)
    assert worker.process is None                       # Killed, not left running.
    third = ask(7)
    assert third[9] != first[9] and worker.starts == 2
    with pytest.raises(CaptureError, match='worker_failed'):
        ask(98)
    with pytest.raises(CaptureError, match='worker_failed'):
        ask(97)                                         # Reply length beyond the bound.
    assert ask(7)[6] == '7' and worker.starts == 4
    assert worker.snapshot()['requests'] == 7 and worker.snapshot()['failures'] == 3


def test_worker_rejects_wrong_mode_or_size_before_sending(worker):
    for mode, size, pixels in (('RGB', (2, 2), bytes(12)), ('L', (2, 2), bytes(3)),
                               ('L', (native.MAX_PIXELS + 1, 1), b'')):
        with pytest.raises(ValueError):
            worker.tsv(mode, size, pixels, 7)
    assert worker.starts == 0


def test_pool_is_bounded_and_concurrent_callers_never_receive_another_reply(fake):
    pool = native.TesseractPool(fake, 2)
    results, errors = {}, []
    def call(n):
        try:
            data = pool(Image.new('L', (n + 1, 2)), 96, str(n))
            results[n] = (data['left'], data['top'], data['text'], data['height'])
        except Exception as error:  # noqa: BLE001  (reported below)
            errors.append(error)
    try:
        threads = [threading.Thread(target=call, args=(n,)) for n in range(8)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(30)
        assert not errors
        assert {n: r[:3] for n, r in results.items()} == {n: ([96], [n + 1], [str(n)]) for n in range(8)}
        snapshot = pool.snapshot()
        assert snapshot['size'] == 2 and snapshot['calls'] == 8 and snapshot['max_queue_wait_seconds'] > 0
        assert len({r[3][0] for r in results.values()}) <= 2   # At most two worker processes.
        assert sum(w['starts'] for w in snapshot['workers']) <= 2
    finally:
        pool.close()
    assert all(w.process is None for w in pool.workers)


def test_pool_recovers_after_a_failed_request_and_reports_per_attempt_metrics(fake):
    pool = native.TesseractPool(fake, 1)
    try:
        metrics = {}
        with pytest.raises(CaptureError, match='worker_failed'):
            pool(Image.new('L', (2, 2)), 98, metrics=metrics)
        assert pool(Image.new('L', (2, 2)), 7, metrics=metrics)['left'] == [7]
        assert metrics['tesseract_calls'] == 2 and metrics['tesseract_queue_wait_seconds'] >= 0
        assert pool.snapshot()['workers'][0] == dict(pid=pool.workers[0].process.pid, starts=2, requests=2, failures=1)
    finally:
        pool.close()


def test_close_during_a_hung_request_ends_it_promptly_and_leaves_no_worker(fake):
    pool = native.TesseractPool(fake, 1)
    pool(Image.new('L', (2, 2)), 7)
    process = pool.workers[0].process
    errors = []
    def hang():
        try:
            pool(Image.new('L', (2, 2)), 99)
        except CaptureError as error:
            errors.append(str(error))
    thread = threading.Thread(target=hang)
    thread.start()
    time.sleep(.3)
    begun = time.monotonic()
    pool.close()                                        # Shutdown while an abandoned attempt holds the worker.
    thread.join(5)
    assert not thread.is_alive() and time.monotonic() - begun < 5
    assert errors == ['tesseract_worker_failed'] and process.poll() is not None
    with pytest.raises(CaptureError, match='closed'):   # A late call from that attempt starts nothing.
        pool(Image.new('L', (2, 2)), 7)
    assert pool.workers[0].starts == 1 and pool.workers[0].process is None


def test_close_racing_worker_spawn_leaves_no_process(worker, monkeypatch):
    # close() lands after tsv() checked `closed` but before Popen returned: the deterministic race.
    spawned = []
    real = native.subprocess.Popen
    def popen(*args, **kwargs):
        worker.close()
        spawned.append(real(*args, **kwargs))
        return spawned[-1]
    monkeypatch.setattr(native.subprocess, 'Popen', popen)
    with pytest.raises(CaptureError, match='closed'):
        worker.tsv('L', (2, 2), bytes(4), 7)
    assert len(spawned) == 1 and spawned[0].poll() is not None and worker.process is None


def test_close_during_worker_startup_ends_it_promptly(fake, monkeypatch):
    monkeypatch.setenv('FAKE_SLOW_START', '1')          # Started, but no identity for 30 s.
    client = native.ResidentTesseract(fake, start_timeout=30)
    errors = []
    def start():
        try:
            client.tsv('L', (2, 2), bytes(4), 7)
        except CaptureError as error:
            errors.append(str(error))
    thread = threading.Thread(target=start)
    thread.start()
    deadline = time.monotonic() + 10
    while client.process is None and time.monotonic() < deadline:
        time.sleep(.01)
    process = client.process
    begun = time.monotonic()
    client.close()
    thread.join(5)
    assert not thread.is_alive() and time.monotonic() - begun < 5
    assert errors == ['tesseract_worker_failed'] and process.poll() is not None and client.process is None


def test_missing_native_library_fails_clearly_at_preflight(fake, monkeypatch):
    monkeypatch.setenv('FAKE_INIT_ERROR', '1')
    pool = native.TesseractPool(fake, 1)
    with pytest.raises(RuntimeError, match='Resident Tesseract unavailable.*libtesseract not found.*MSXP_LIBTESSERACT'):
        pool.check()
    pool.close()


def test_engine_is_scoped_to_one_capture_attempt_and_its_thread(monkeypatch):
    monkeypatch.syspath_prepend(str(Path('tools').resolve()))
    import shadow_capture as shadow
    from types import SimpleNamespace

    class Pool:
        def __init__(self, name): self.name, self.calls = name, []
        def __call__(self, image, psm, whitelist='', *, metrics=None):
            self.calls.append(threading.current_thread().name)
            metrics['tesseract_calls'] = metrics.get('tesseract_calls', 0) + 1
            time.sleep(.01)
            return dict(text=[self.name], conf=['90'], left=[0], top=[0], width=[1], height=[1], page_num=[1])

    class Session:
        source_bytes = 0
        def __init__(self, *args, **kwargs): pass
        def frame(self, **kwargs): return SimpleNamespace(received_at='x', png=b'png')
        def close(self): pass

    def analyze(frame, requirements, reader, **options):
        seen = [recognition._ocr(Image.new('L', (2, 2)), 7)[0]['text'] for _ in range(3)]
        return dict(timings={}, seen=seen)

    args = SimpleNamespace(timeout=1, max_age=1, ocr_python=None, ocr_timeout=1, save_crops=False, output=Path('x'))
    pools, records = {name: Pool(name) for name in ('a', 'b')}, {}
    def attempt(name):
        records[name] = shadow.capture_attempt(args, shadow.Source('file', 'unused'), {1: 15, 2: 34}, 1, session_factory=Session,
                                               analyze_frame=analyze, tesseract=pools[name])
    threads = [threading.Thread(target=attempt, args=(name,), name=name) for name in pools]
    for thread in threads: thread.start()
    for thread in threads: thread.join(10)
    for name, pool in pools.items():
        assert records[name]['seen'] == [name] * 3 and set(pool.calls) == {name}
        assert records[name]['timings']['tesseract_calls'] == 3
    assert recognition.ocr_engine.get() is None
    # Without a pool the attempt leaves the CLI path alone and records no pool metrics.
    monkeypatch.setattr(recognition.pytesseract, 'image_to_data', lambda *a, **kw: dict(
        text=['cli'], conf=['90'], left=[0], top=[0], width=[1], height=[1], page_num=[1]))
    plain = shadow.capture_attempt(args, shadow.Source('file', 'unused'), {1: 15, 2: 34}, 1, session_factory=Session, analyze_frame=analyze)
    assert plain['seen'] == ['cli'] * 3 and 'tesseract_calls' not in plain['timings']


def hud_frame(rows):
    """Synthetic HUD rows with an orange level tile, readable by real Tesseract."""
    image = Image.new('RGB', (960, 540), (20, 30, 60))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=14)
    for y in rows:
        draw.text((40, y), 'LV.', fill='white', font=font)
        draw.rectangle((88, y - 2, 128, y + 26), fill=(230, 140, 40))
        draw.text((94, y), '42', fill='white', font=ImageFont.load_default(size=18))
        for x, text in ((300, 'HP 120/120'), (450, 'MP 80/80'), (600, 'EXP 12,345[6.78%]')):
            draw.text((x, y), text, fill='white', font=font)
    return image


@pytest.fixture
def real():
    recognition.configure_tesseract()
    pool = native.TesseractPool(native.worker_command(), 2)
    try:
        identity = pool.check()
    except RuntimeError as error:
        pool.close()
        pytest.skip(str(error))
    yield pool, identity
    pool.close()


@pytest.mark.ocr
def test_worker_tsv_matches_pytesseract_and_settings_do_not_leak(real):
    pool, identity = real
    image = hud_frame([60]).convert('L').resize((2880, 1620), Image.Resampling.BICUBIC).point(lambda p: 0 if p > 160 else 255)
    digits = Image.new('L', (200, 60), 255)
    ImageDraw.Draw(digits).text((10, 10), '42', fill=0, font=ImageFont.load_default(size=36))
    calls = [(image, 11, ''), (digits, 7, '0123456789'), (image, 11, '')]  # The third must equal the first.
    expected = [pytesseract.image_to_data(i, lang='eng', output_type=DICT, timeout=10,
                                          config=f'--psm {p}' + (f' -c tessedit_char_whitelist={w}' if w else ''))
                for i, p, w in calls]
    assert any(t.strip() == 'HP' for t in expected[0]['text'])
    assert [pool(i, p, w) for i, p, w in calls] == expected
    assert len(identity['model_sha256']) == 64 and json.dumps(identity)


@pytest.mark.ocr
@pytest.mark.parametrize('rows', [[60], [60, 470]], ids=['one_hud', 'two_huds'])
def test_hud_localization_and_level_reading_are_identical_through_the_pool(real, rows, monkeypatch):
    monkeypatch.syspath_prepend(str(Path('tools').resolve()))
    import adaptive_hud as hud
    pool, _ = real
    image = hud_frame(rows)
    def read():
        found = hud.locate(image)
        levels = [hud.level_reading(image.crop(c['regions']['level'].pixels(*image.size)))
                  for c in found if c['regions']['level'] is not None]
        return hud.scan(image), found, levels
    cli = read()
    scope = recognition.ocr_engine.set(pool)
    try:
        resident = read()
    finally:
        recognition.ocr_engine.reset(scope)
    assert resident == cli
    # Not vacuous: every HUD is found (two are the ambiguous multi-HUD case) and its level read.
    assert len(cli[1]) == len(rows) and [level for level, _ in cli[2]] == [42] * len(rows)
    assert pool.snapshot()['calls'] == 2*2 + 3*len(rows)  # Two scans at two scales; three level variants per HUD.


def test_version_mismatch_is_refused():
    try:
        recognition.configure_tesseract()
        info = native.installation(pytesseract.pytesseract.tesseract_cmd)
        native.NativeTesseract(info).close()
    except (RuntimeError, OSError) as error:
        pytest.skip(f'libtesseract unavailable: {error}')
    with pytest.raises(RuntimeError, match='differs'):
        native.NativeTesseract({**info, 'cli_version': '0.0.0'})


from tests.test_multi_alpha import main as run_main, multi, record  # noqa: E402,F401  (fixture reuse)
from tests.test_automatic_adoption import legacy  # noqa: E402,F401
from tests.test_db_streamer_roster import change, managed, run_db, running_roster  # noqa: E402,F401
from exp_tracker.store import Store  # noqa: E402


class FakePool:
    def __init__(self, made, error=None):
        self.made, self.error = made, error
    def __call__(self, command, size, **options):
        pool = FakePool(self.made, self.error)
        pool.command, pool.size, pool.closed = command, size, False
        self.made.append(pool)
        return pool
    def check(self):
        if self.error: raise RuntimeError(self.error)
        return dict(version='5.4.0', model_sha256='a'*64)
    def snapshot(self): return dict(size=self.size, calls=0, workers=[])
    def close(self): self.closed = True


def fake_pools(monkeypatch, error=None):
    made = []
    monkeypatch.setattr(native, 'TesseractPool', FakePool(made, error))
    monkeypatch.setattr(native, 'worker_command', lambda: ['worker'])
    return made


def headers(path):
    with Store(path, read_only=True) as store:
        return [json.loads(r[0]) for r in store.db.execute('SELECT configuration_json FROM diagnostic_runs')]


@pytest.mark.parametrize('extra, size', [([], 1), (['--workers', '4'], 4), (['--workers', '6', '--resident-neural'], 4),
                                         (['--workers', '8', '--stagger-capture', '--resident-neural'], 4)])
def test_coordinator_flag_gives_every_attempt_one_bounded_pool_and_closes_it(multi, monkeypatch, extra, size):
    module = multi[0]
    made = fake_pools(monkeypatch)
    seen = []
    def capture(args, source, requirements, index, **kwargs):
        seen.append(kwargs)
        return record(index)
    monkeypatch.setattr(module.shadow, 'capture_attempt', capture)
    monkeypatch.setattr(module.shadow.ResidentNeural, 'close', lambda self: None)
    assert run_main(multi, '--resident-tesseract', *extra) == 0
    preflight, pool = made                              # Preflight worker, then the run's pool.
    assert (preflight.size, preflight.closed, pool.size, pool.closed) == (1, True, size, True)
    assert len(seen) == 4 and all(kw['tesseract'] is pool for kw in seen)
    assert all(('resident' in kw) == ('--resident-neural' in extra) for kw in seen)  # Separate from RapidOCR reuse.
    assert all('analyze_frame' not in kw for kw in seen)                               # No HUD cache.
    found = headers(multi[1].parent/'shared.sqlite3')
    assert len(found) == 2 and all(h['resident_tesseract'] == dict(version='5.4.0', model_sha256='a'*64, workers=size)
                                   for h in found)
    assert all(h.get('stagger_capture') is ('--stagger-capture' in extra or None) for h in found)


@pytest.mark.parametrize('check', [False, True])
def test_unavailable_native_library_stops_before_any_database_or_capture(multi, monkeypatch, capsys, check):
    module = multi[0]
    made = fake_pools(monkeypatch, 'Resident Tesseract unavailable (tesseract_worker_unavailable): libtesseract not found')
    monkeypatch.setattr(module.shadow, 'capture_attempt', lambda *a, **kw: pytest.fail('captured'))
    assert run_main(multi, '--resident-tesseract', *(['--check'] if check else [])) == 1
    assert 'libtesseract not found' in capsys.readouterr().err
    assert made[0].closed and not (multi[1].parent/'shared.sqlite3').exists()


def test_db_roster_attempts_share_the_pool_across_an_identity_switch(running_roster, monkeypatch):
    legacy, counters, _, scripts, _, _ = running_roster
    module, path = legacy[0], legacy[3]
    made = fake_pools(monkeypatch)
    change(path, 'newcaster', authorized=True, tracking_enabled=True)
    scripts['newcaster'] = ['Alpha']
    pools = []
    capture = module.shadow.capture_attempt
    def checked(args, source, requirements, index, **options):
        pools.append(options['tesseract'])
        return capture(args, source, requirements, index, **options)
    monkeypatch.setattr(module.shadow, 'capture_attempt', checked)
    assert run_db(running_roster, '--resident-tesseract', '--stagger-capture', '--max-attempts', '3') == 0
    assert set(map(id, pools)) == {id(made[1])} and made[1].size == 3 and made[1].closed
    assert counters['newcaster'] == 3
    with Store(path, read_only=True) as store:
        from exp_tracker import streamer_roster as roster
        newcaster = next(row for row in roster.status(store) if row['channel'] == 'newcaster')
        assert newcaster['character']['label'] == 'Alpha'
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
    roster_headers = [h for h in headers(path) if h.get('database_roster')]
    assert len(roster_headers) >= 15 and all(h['resident_tesseract']['workers'] == 3 for h in roster_headers)
