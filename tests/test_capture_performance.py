"""Cached HUD search region, bounded parallel scheduling and the resident neural worker."""

import importlib
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

from PIL import Image
import pytest

from exp_tracker.video import CaptureError, Source
from tests.test_adaptive_hud import anchors, hud


def fake_ocr(monkeypatch, tokens, size):
    """Return the same frame tokens as Tesseract would see them in whatever crop it is given."""
    calls = []
    def ocr(image, psm, whitelist=''):
        box = calls[-1]
        scale = image.width / (box[2]-box[0])
        return [{**t, 'x': (t['x']-box[0])*scale, 'y': (t['y']-box[1])*scale,
                 'width': t['width']*scale, 'height': t['height']*scale}
                for t in tokens if box[0] <= t['x'] < box[2] and box[1] <= t['y'] < box[3]]
    original = hud.locate
    def locate(image, box=None):
        calls.append(box or (0, 0, *image.size))
        calls.append(calls[-1])
        return original(image, box)
    monkeypatch.setattr(hud, '_ocr', ocr)
    monkeypatch.setattr(hud, 'configure_tesseract', lambda: None)
    return locate, calls


def test_search_box_translates_tokens_back_to_full_frame(monkeypatch):
    image = Image.new('RGB', (1920, 1080))
    locate, _ = fake_ocr(monkeypatch, anchors(780, 1000, 109), image.size)
    full = locate(image)
    assert len(full) == 1
    box = hud.search_box(full[0], image.size)
    assert box[2]-box[0] < 700 and box[3]-box[1] < 150  # A small fraction of the frame.
    cropped = locate(image, box)
    assert len(cropped) == 1
    for field in ('exp', 'level'):
        a, b = cropped[0]['regions'][field].pixels(*image.size), full[0]['regions'][field].pixels(*image.size)
        assert max(abs(x-y) for x, y in zip(a, b)) <= 1


def candidate(x=780, y=1000, step=109, level=True):
    tokens = [{**t, 'height': .1*step, 'width': .2*step} for t in anchors(x, y, step)]  # Valid even without LV.
    result = hud.layouts(tokens if level else tokens[:3], (1920, 1080))
    assert len(result) == 1 and (result[0]['regions']['level'] is None) != level
    return result


class Scans:
    def __init__(self):
        self.full, self.region, self.calls = [], [], []
    def __call__(self, image, box=None):
        self.calls.append('region' if box else 'full')
        return (self.region if box else self.full).pop(0)


def test_cached_region_is_seeded_only_by_unique_full_frame_and_expires():
    now = [0.0]; scans = Scans(); image = Image.new('RGB', (1920, 1080))
    locator = hud.CachedLocator(60, clock=lambda: now[0], scan=scans)
    scans.full = [candidate()+candidate(300, 300), candidate(), candidate()]
    assert len(locator(image)) == 2 and locator.seed is None      # Ambiguous never seeds.
    assert locator(image) == candidate() and scans.calls == ['full', 'full']
    scans.region = [candidate(781), candidate(782)]
    now[0] = 30
    reused = locator(image)
    assert reused[0]['search'] == 'cached_region' and reused[0]['full_frame_age_seconds'] == 30
    now[0] = 60
    assert locator(image)[0]['search'] == 'cached_region'
    now[0] = 60.5                                                   # Reuse never extends the seed.
    assert 'search' not in locator(image)[0]
    assert scans.calls == ['full', 'full', 'region', 'region', 'full']


@pytest.mark.parametrize('region', [[], candidate()+candidate(300, 300), candidate(step=130),
                                    candidate(level=False), candidate(800)])
def test_any_region_doubt_rescans_the_full_frame(region):
    scans = Scans(); image = Image.new('RGB', (1920, 1080))
    locator = hud.CachedLocator(60, clock=lambda: 0, scan=scans)
    scans.full = [candidate(), []]
    locator(image)
    scans.region = [region]
    assert locator(image) == [] and locator.seed is None            # Full-frame answer, which clears the seed.
    assert scans.calls == ['full', 'region', 'full']


def test_frame_size_change_rescans_without_region_search():
    scans = Scans()
    locator = hud.CachedLocator(60, clock=lambda: 0, scan=scans)
    scans.full = [candidate(), candidate()]
    locator(Image.new('RGB', (1920, 1080)))
    locator(Image.new('RGB', (1280, 720)))
    assert scans.calls == ['full', 'full']


@pytest.fixture
def schedule(monkeypatch):
    monkeypatch.syspath_prepend(str(Path('tools').resolve()))
    return importlib.import_module('multi_alpha').schedule


def lanes(*channels, count=3, interval=.25):
    return [dict(channel=c, run_id=c, args=SimpleNamespace(count=count, interval=interval, start=0, timeout=1, ocr_timeout=1),
                 source=Source('file', 'unused')) for c in channels]


def attempt(index, **changes):
    return dict(type='attempt', index=index, status='diagnostic_pair', received_at='x', **changes)


def test_parallel_workers_are_bounded_one_per_lane_and_emit_on_coordinator_thread(schedule):
    lock = threading.Lock(); active = set(); peak = [0]; emitted = []
    main = threading.get_ident()
    def perform(lane, index, seek):
        with lock:
            assert lane['channel'] not in active
            active.add(lane['channel']); peak[0] = max(peak[0], len(active))
        time.sleep(.1)
        with lock: active.discard(lane['channel'])
        return attempt(index)
    def emit(lane, record):
        assert threading.get_ident() == main
        emitted.append((lane['channel'], record['index']))
    group = lanes('a', 'b', 'c', 'd')
    assert schedule(group, perform, emit, workers=2) is False
    assert peak[0] == 2
    for c in 'abcd':
        assert [i for channel, i in emitted if channel == c] == [1, 2, 3]
    assert all(lane['commits'] == 0 and lane['attempts'] == 3 for lane in group)
    assert all(lane['duration_total'] >= .3 for lane in group)


def test_parallel_interrupt_records_in_flight_attempts_and_stops(schedule):
    release = threading.Event(); emitted = []
    def perform(lane, index, seek):
        if lane['channel'] == 'a':
            time.sleep(.05)
            raise KeyboardInterrupt
        release.wait(5)
        return attempt(index)
    group = lanes('a', 'b')
    assert schedule(group, perform, lambda lane, record: emitted.append((lane['channel'], record['reasons'])), workers=2) is True
    release.set()
    assert sorted(emitted) == [('a', ['operator_interrupted']), ('b', ['operator_interrupted'])]
    assert all(lane['interrupted'] for lane in group)


def test_parallel_unexpected_error_reaches_coordinator(schedule):
    def perform(lane, index, seek):
        raise TypeError('bug')
    with pytest.raises(TypeError):
        schedule(lanes('a', 'b'), perform, lambda *_: None, workers=2)


WORKER = r'''
import json, os, struct, sys, time
while header := sys.stdin.buffer.read(4):
    payload = sys.stdin.buffer.read(struct.unpack('!I', header)[0])
    if payload == b'hang': time.sleep(30)
    if payload == b'die': sys.exit(1)
    sys.stdout.write(json.dumps(dict(text=payload.decode(), pid=os.getpid())) + '\n'); sys.stdout.flush()
'''


def test_resident_worker_is_reused_and_replaced_after_timeout_or_crash(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path('tools').resolve()))
    shadow = importlib.import_module('shadow_capture')
    script = tmp_path/'worker.py'; script.write_text(WORKER)
    command = [sys.executable, str(script)]
    resident = shadow.ResidentNeural()
    try:
        first = shadow.json.loads(resident(command, b'one', 10))
        second = shadow.json.loads(resident(command, b'two', 10))
        assert (first['text'], second['text']) == ('one', 'two') and first['pid'] == second['pid']
        with pytest.raises(CaptureError, match='neural_timeout'):
            resident(command, b'hang', .5)
        third = shadow.json.loads(resident(command, b'three', 10))
        assert third['pid'] != first['pid']
        with pytest.raises(CaptureError, match='neural_worker_failed'):
            resident(command, b'die', 10)
        assert shadow.json.loads(resident(command, b'four', 10))['text'] == 'four'
    finally:
        resident.close()
    assert resident.processes == {}


from tests.test_multi_alpha import main as run_main, multi, record  # noqa: E402,F401  (fixture reuse)


def test_coordinator_flags_reach_each_attempt_and_are_bounded(multi, monkeypatch):
    module = multi[0]
    seen = []
    def capture(args, source, requirements, index, **kwargs):
        seen.append((args.tracking_channel, kwargs))
        return record(index)
    monkeypatch.setattr(module.shadow, 'capture_attempt', capture)
    closed = []
    monkeypatch.setattr(module.shadow.ResidentNeural, 'close', lambda self: closed.append(self))
    assert run_main(multi, '--workers', '2', '--hud-cache-seconds', '30', '--resident-neural') == 0
    assert sorted(channel for channel, _ in seen) == ['alpha', 'alpha', 'beta', 'beta']
    residents = {id(kw['resident']) for _, kw in seen}
    assert len(residents) == 1 and len(closed) == 1                 # One shared resident, closed at exit.
    locators = {c: {id(kw['analyze_frame'].keywords['locator']) for channel, kw in seen if channel == c} for c in ('alpha', 'beta')}
    assert all(len(ids) == 1 for ids in locators.values()) and locators['alpha'] != locators['beta']
    seen.clear()
    assert run_main(multi) == 0 and all(set(kw) == {'seek'} for _, kw in seen)  # Defaults keep the serial, per-attempt path.
    for bad in (['--workers', '5'], ['--hud-cache-seconds', '-1'], ['--hud-cache-seconds', 'nan']):
        assert run_main(multi, *bad) == 1


def test_run_summary_reports_stage_means_and_region_reuse(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path('tools').resolve()))
    summarize = importlib.import_module('summarize_capture_run').summarize
    rows = [dict(type='configuration'),
            dict(type='attempt', status='diagnostic_pair', received_at='x', coordinator_attempt_seconds=4,
                 actual_interval_seconds=None, timings=dict(localization_seconds=3, neural_bridge_seconds=1)),
            dict(type='attempt', status='capture_failed', coordinator_attempt_seconds=2, actual_interval_seconds=60,
                 localization=dict(candidates=[dict(search='cached_region')]), timings=dict(localization_seconds=1))]
    for lane in ('a', 'b'):
        (tmp_path/lane).mkdir()
        (tmp_path/lane/'capture.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
    result = summarize(tmp_path)
    assert result['attempts'] == 4 and result['frames'] == 2
    assert result['statuses'] == {'capture_failed': 2, 'diagnostic_pair': 2}
    assert (result['mean_work_seconds'], result['localization_seconds'], result['neural_seconds']) == (3, 2, 1)
    assert (result['cached_region_attempts'], result['cached_localization_seconds']) == (2, 1)
    assert result['mean_actual_interval_seconds'] == 60


def test_coordinator_ctrl_c_with_busy_workers_is_bounded_and_nothing_emits_later(schedule):
    import _thread
    release = threading.Event(); emitted = []
    def perform(lane, index, seek):
        release.wait(10)  # Stuck in a subprocess wait, as a hung capture would be.
        return attempt(index)
    group = lanes('a', 'b', 'c')
    timer = threading.Timer(.3, _thread.interrupt_main)  # Ctrl+C reaches only the coordinator thread.
    started = time.monotonic(); timer.start()
    try:
        assert schedule(group, perform, lambda lane, record: emitted.append((lane['channel'], record['reasons'])), workers=2) is True
    except KeyboardInterrupt:
        pytest.fail('interrupt escaped the scheduler')
    finally:
        timer.cancel()
    assert time.monotonic()-started < 3                       # Did not wait for the 10 s workers.
    assert sorted(emitted) == [('a', ['operator_interrupted']), ('b', ['operator_interrupted'])]
    release.set(); time.sleep(.3)
    assert len(emitted) == 2                                  # Late worker results are discarded.
    assert all(lane['interrupted'] for lane in group) and group[2]['attempts'] == 0


def test_parallel_interrupt_then_clean_restart_on_the_same_database(multi, monkeypatch):
    from exp_tracker.diagnostics import Diagnostics
    from exp_tracker.store import Store
    module, path = multi[0], multi[1]
    closed = []
    monkeypatch.setattr(module.shadow.ResidentNeural, 'close', lambda self: closed.append(self))
    count = [0]; lock = threading.Lock()
    def capture(args, source, requirements, index, **kwargs):
        with lock:
            count[0] += 1; current = count[0]
        if current == 2: raise KeyboardInterrupt
        return record(index)
    monkeypatch.setattr(module.shadow, 'capture_attempt', capture)
    assert run_main(multi, '--workers', '2', '--resident-neural') == 130
    assert len(closed) == 1                                   # Resident closed on interrupt, too.
    db = path.parent/'shared.sqlite3'
    with Store(db, read_only=True) as store:
        first = {c: Diagnostics(store).snapshot(c)['run_status'] for c in ('alpha', 'beta')}
        attempts = store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]
    assert first == {'alpha': 'interrupted', 'beta': 'interrupted'}
    monkeypatch.setattr(module.shadow, 'capture_attempt', lambda *a, **kw: record(a[3]))
    assert run_main(multi, '--workers', '2', '--resident-neural') == 0 and len(closed) == 2
    with Store(db, read_only=True) as store:
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_runs').fetchone()[0] == 4
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0] == attempts+4
        assert not store.db.execute('SELECT 1 FROM diagnostic_runs WHERE summary_json IS NULL').fetchone()
        assert all(Diagnostics(store).snapshot(c)['run_status'] == 'completed' for c in ('alpha', 'beta'))


DEAF = 'import time\ntime.sleep(30)\n'  # Never reads stdin: a large request fills the pipe.


def test_resident_worker_processes_are_killed_on_timeout_and_close(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path('tools').resolve()))
    shadow = importlib.import_module('shadow_capture')
    (tmp_path/'deaf.py').write_text(DEAF); (tmp_path/'worker.py').write_text(WORKER)
    deaf, live = [sys.executable, str(tmp_path/'deaf.py')], [sys.executable, str(tmp_path/'worker.py')]
    resident = shadow.ResidentNeural()
    try:
        started = time.monotonic()
        with pytest.raises(CaptureError, match='neural_timeout'):
            resident(deaf, b'x'*(4 << 20), .5)                # Larger than any pipe buffer.
        assert time.monotonic()-started < 5 and resident.processes == {}
        resident(live, b'one', 10)
        (process, _), = resident.processes.values()
        with pytest.raises(CaptureError, match='neural_timeout'):
            resident(live, b'hang', .5)
        assert process.wait(timeout=5) is not None            # The hung process is dead, not orphaned.
        resident(live, b'two', 10)
        (process, _), = resident.processes.values()
    finally:
        resident.close()
    assert process.wait(timeout=5) is not None and resident.processes == {}


def test_maintenance_runs_only_on_coordinator_thread_including_while_attempts_are_in_flight(schedule):
    main = threading.get_ident(); lock = threading.Lock(); flying = set(); calls = []; emitted = []
    def perform(lane, index, seek):
        with lock: flying.add(lane['channel'])
        time.sleep(.15)
        with lock: flying.discard(lane['channel'])
        return attempt(index)
    def maintain():
        with lock: calls.append((threading.get_ident(), frozenset(flying)))
    group = lanes('a', 'b', 'c')
    assert schedule(group, perform, lambda lane, record: emitted.append((lane['channel'], record['index'])),
                    workers=2, maintain=maintain) is False
    assert calls and all(ident == main for ident, _ in calls)
    assert calls[0][1] == frozenset()                          # First pass runs before any dispatch.
    assert any(busy for _, busy in calls)                      # ...and later passes overlap in-flight work.
    for c in 'abc':
        assert [i for channel, i in emitted if channel == c] == [1, 2, 3]


def test_interrupt_during_maintenance_records_in_flight_attempts(schedule):
    release = threading.Event(); emitted = []; both = threading.Barrier(3); passes = [0]
    def perform(lane, index, seek):
        both.wait(5); release.wait(10)
        return attempt(index)
    def maintain():
        passes[0] += 1
        if passes[0] == 3:                                      # Passes: before dispatch, after a, after b.
            both.wait(5)                                        # Both attempts are now running...
            raise KeyboardInterrupt                             # ...when Ctrl+C lands inside a prune.
    group = lanes('a', 'b')
    begun = time.monotonic()
    assert schedule(group, perform, lambda lane, record: emitted.append((lane['channel'], record['reasons'])),
                    workers=2, maintain=maintain, max_attempts=3, continuous=True) is True
    release.set()
    assert time.monotonic()-begun < 3
    assert sorted(emitted) == [('a', ['operator_interrupted']), ('b', ['operator_interrupted'])]


def test_retention_maintenance_overlaps_in_flight_worker_and_restarts_cleanly(multi, monkeypatch):
    from exp_tracker import retention
    from exp_tracker.diagnostics import Diagnostics
    from exp_tracker.store import Store
    module, path = multi[0], multi[1]
    real = time.monotonic; shift = [0.0]
    # Only collect() and maintain() read this clock: jumping it makes retention due mid-run.
    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: real()+shift[0], sleep=time.sleep))
    coordinator = threading.get_ident(); flying = set(); lock = threading.Lock()
    pruned = threading.Event(); seen = []; original = retention.prune
    def prune(store, **kwargs):
        with lock: seen.append((threading.get_ident(), set(kwargs['active_runs']), frozenset(flying)))
        result = original(store, **kwargs)
        pruned.set()
        return result
    monkeypatch.setattr(retention, 'prune', prune)
    def capture(args, source, requirements, index, **kwargs):
        channel = args.tracking_channel
        with lock: flying.add(channel)
        if channel == 'alpha' and index == 1:
            pruned.clear(); shift[0] += 7200                    # Maintenance falls due while alpha is in flight.
            assert pruned.wait(10)                              # Unblocked only by a prune on the coordinator.
        with lock: flying.discard(channel)
        return record(index)
    monkeypatch.setattr(module.shadow, 'capture_attempt', capture)
    flags = ('--continuous', '--retention-24h', '--max-attempts', '2', '--workers', '2', '--resident-neural')
    monkeypatch.setattr(module.shadow.ResidentNeural, 'close', lambda self: None)
    assert run_main(multi, *flags) == 0
    assert all(ident == coordinator for ident, _, _ in seen) and len(seen) >= 2
    overlapped = [(active, busy) for _, active, busy in seen if 'alpha' in busy]
    assert overlapped and all(len(active) == 2 for active, _ in overlapped)   # Both in-flight runs protected.
    db = path.parent/'shared.sqlite3'
    with Store(db, read_only=True) as store:
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0] == 4
        assert not store.db.execute('SELECT 1 FROM diagnostic_runs WHERE summary_json IS NULL').fetchone()
    seen.clear()
    assert run_main(multi, *flags) == 0                         # Restart: new runs, same DB, retention again.
    assert seen and all(ident == coordinator for ident, _, _ in seen)
    with Store(db, read_only=True) as store:
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_runs').fetchone()[0] == 4
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0] == 8
        assert not store.db.execute('SELECT 1 FROM diagnostic_runs WHERE summary_json IS NULL').fetchone()
        assert all(Diagnostics(store).snapshot(c)['run_status'] == 'completed' for c in ('alpha', 'beta'))
    assert list((path.parent/'multi-alpha/runs').glob('*/.retention-owner.json'))
