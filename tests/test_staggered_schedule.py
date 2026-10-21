"""Opt-in staggered first deadlines in the real multi_alpha.schedule() and coordinator."""

import json
import threading
import time

import pytest

from exp_tracker.store import Store
from tests.test_capture_performance import attempt, lanes, schedule  # noqa: F401  (fixture reuse)
from tests.test_multi_alpha import main as run_main, multi, record  # noqa: F401  (fixture reuse)


def fake_clock():
    now = [0.0]
    def sleep(seconds): now[0] += max(0, seconds)
    return now, (lambda: now[0]), sleep


def serial(schedule, group, *, stagger, work=1.0, **options):
    """workers=1 never waits on real time, so the fake clock makes the run exact."""
    now, clock, sleep = fake_clock()
    starts = []
    def perform(lane, index, seek):
        starts.append((lane['channel'], index, now[0], lane['due'], seek))
        now[0] += work
        return attempt(index)
    result = schedule(group, perform, lambda lane, record: None, clock=clock, sleep=sleep, stagger=stagger, **options)
    return result, starts


def test_default_keeps_one_shared_first_deadline(schedule):
    _, starts = serial(schedule, lanes('a', 'b', 'c', count=2, interval=9), stagger=False)
    assert [(c, i, t, due) for c, i, t, due, _ in starts] == [
        ('a', 1, 0, 0), ('b', 1, 1, 0), ('c', 1, 2, 0), ('a', 2, 9, 9), ('b', 2, 10, 9), ('c', 2, 11, 9)]


def test_stagger_spreads_first_deadlines_and_never_starts_early(schedule):
    group = lanes('a', 'b', 'c', count=2, interval=9)
    _, starts = serial(schedule, group, stagger=True)
    assert [(c, i, t, due) for c, i, t, due, _ in starts] == [
        ('a', 1, 0, 0), ('b', 1, 3, 3), ('c', 1, 6, 6), ('a', 2, 9, 9), ('b', 2, 12, 12), ('c', 2, 15, 15)]
    assert all(t >= due for _, _, t, due, _ in starts)
    # Only timing moves: local-video seek is still the actual elapsed time, so no older frame is requested.
    assert all(seek == t for _, _, t, _, seek in starts)
    assert all(lane['skipped'] == 0 for lane in group)


def test_mixed_intervals_each_start_inside_their_own_first_period(schedule):
    group = lanes('a', 'b', 'c', count=1)
    for lane, interval in zip(group, (10, 20, 30)):
        lane['args'].interval = interval
    _, starts = serial(schedule, group, stagger=True, work=0)
    assert [(c, t) for c, _, t, _, _ in starts] == [('a', 0), ('b', pytest.approx(20/3)), ('c', 20)]
    assert all(t < lane['args'].interval for (_, _, t, _, _), lane in zip(starts, group))


def test_stagger_skips_whole_slots_on_each_lane_grid(schedule):
    group = lanes('a', 'b', count=3, interval=10)
    _, starts = serial(schedule, group, stagger=True, work=25)  # Work exceeds the interval.
    offsets = {'a': 0, 'b': 5}
    for lane in group:
        offset = offsets[lane['channel']]
        dues = [due for c, _, _, due, _ in starts if c == lane['channel']]
        assert all((due-offset) % 10 == 0 for due in dues)  # Phase kept; slots skipped, not shifted.
        assert lane['due'] == offset + 10*(lane['attempts']+lane['skipped'])
        assert lane['skipped'] > 0 and lane['attempts'] == 3


def test_stagger_stop_after_seconds_never_starts_a_later_phase(schedule):
    group = lanes('a', 'b', 'c', interval=9)
    _, starts = serial(schedule, group, stagger=True, work=0, continuous=True, stop_after_seconds=5,
                       rotate=lambda lane: None)
    assert [c for c, *_ in starts] == ['a', 'b']


@pytest.mark.parametrize('workers', [6, 8])
def test_stagger_keeps_workers_bounded_order_rotation_and_coordinator_writes(schedule, workers):
    lock = threading.Lock(); active = set(); peak = [0]; main = threading.get_ident(); rotated = []; early = []
    def perform(lane, index, seek):
        if time.monotonic() < lane['due']:
            early.append(lane['channel'])
        with lock:
            assert lane['channel'] not in active
            active.add(lane['channel']); peak[0] = max(peak[0], len(active))
        time.sleep(.003)
        with lock: active.discard(lane['channel'])
        return attempt(index)
    def rotate(lane):
        assert threading.get_ident() == main and lane['channel'] not in active
        rotated.append(lane['channel'])
    emitted = {}
    def emit(lane, record):
        assert threading.get_ident() == main
        emitted.setdefault(lane['channel'], []).append(record['index'])
    group = lanes(*map(str, range(workers+2)), interval=.002)
    assert schedule(group, perform, emit, workers=workers, continuous=True, max_attempts=62, rotate=rotate,
                    stagger=True) is False
    assert 1 < peak[0] <= workers and not early
    assert sorted(rotated) == sorted(lane['channel'] for lane in group)
    assert all(emitted[lane['channel']] == [*range(1, 61), 1, 2] for lane in group)


def test_stagger_failures_and_interrupts_keep_existing_records(schedule):
    emitted = []
    def perform(lane, index, seek):
        if lane['channel'] == '0':
            raise OSError('capture child failed')
        raise KeyboardInterrupt
    group = lanes('0', '1', '2', '3', interval=.4)  # First deadlines 0, .1, .2, .3 s.
    assert schedule(group, perform, lambda lane, record: emitted.append((lane['channel'], record['reasons'])),
                    workers=2, stagger=True) is True
    assert emitted == [('0', ['capture_process_failed']), ('1', ['operator_interrupted'])]
    assert all(lane['interrupted'] for lane in group)
    assert [lane['attempts'] for lane in group] == [1, 1, 0, 0]  # Later phases never started.


def configure(multi, *, disabled=False):
    path = multi[1]
    config = json.loads(path.read_text())
    if disabled:
        config['streams'].insert(1, {**config['streams'][0], 'channel': 'gamma', 'enabled': False})
    path.write_text(json.dumps(config))
    return path.parent/'shared.sqlite3'


@pytest.mark.parametrize('disabled', [False, True])
def test_coordinator_flag_only_moves_first_deadlines_of_enabled_lanes(multi, monkeypatch, disabled):
    module, _, _, calls, _ = multi
    database = configure(multi, disabled=disabled)
    seen = []
    real = module.schedule
    monkeypatch.setattr(module, 'schedule', lambda *a, **kw: (seen.append(kw), real(*a, **kw))[1])
    assert run_main(multi, '--stagger-capture') == 0
    # Two enabled lanes at 15 s: beta starts half an interval later; a disabled lane takes no phase.
    assert calls == [('alpha', 1, 0), ('beta', 1, 7.5), ('alpha', 2, 15), ('beta', 2, 22.5)]
    assert seen[0]['stagger'] is True and seen[0]['workers'] == 1
    with Store(database, read_only=True) as store:
        headers = [json.loads(r[0]) for r in store.db.execute('SELECT configuration_json FROM diagnostic_runs')]
        assert len(headers) == 2 and all(h.get('stagger_capture') is True for h in headers)
        assert all('hud_cache_seconds' not in h and 'resident_neural' not in h for h in headers)
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0] == 4


def test_coordinator_default_is_unchanged_and_unrecorded(multi, monkeypatch):
    module, _, _, calls, _ = multi
    database = configure(multi)
    seen = []
    def capture(args, source, requirements, index, **kwargs):
        seen.append(kwargs)
        return record(index)
    monkeypatch.setattr(module.shadow, 'capture_attempt', capture)
    assert run_main(multi) == 0
    assert all(set(kw) == {'seek'} for kw in seen) and len(seen) == 4
    with Store(database, read_only=True) as store:
        headers = [json.loads(r[0]) for r in store.db.execute('SELECT configuration_json FROM diagnostic_runs')]
        assert headers and all('stagger_capture' not in h for h in headers)
    seen.clear()
    assert run_main(multi, '--stagger-capture') == 0
    assert all(set(kw) == {'seek'} for kw in seen) and len(seen) == 4  # No cache, resident or extra options.


def roster_run(schedule, stagger, change):
    """Lanes a, b at 12 s; at t=13 the roster callback changes the lane list, as Reconciler does."""
    now, clock, sleep = fake_clock()
    group = lanes('a', 'b', interval=12)
    starts = []
    def perform(lane, index, seek):
        starts.append((lane['channel'], now[0]))
        return attempt(index)
    def reconcile(running, t):
        if t >= 13 and not group[-1].get('changed'):
            change(group, running)
            group[-1]['changed'] = True
    schedule(group, perform, lambda lane, record: None, clock=clock, sleep=sleep, continuous=True, max_attempts=4,
             rotate=lambda lane: None, reconcile=reconcile, stagger=stagger)
    return {c: [t for channel, t in starts if channel == c] for c, _ in starts}


@pytest.mark.parametrize('stagger', [False, True])
def test_roster_addition_takes_the_widest_gap_and_never_moves_active_lanes(schedule, stagger):
    times = roster_run(schedule, stagger, lambda group, running: group.extend(lanes('c', interval=12)))
    assert times['a'] == [0, 12, 24, 36]
    assert times['b'] == ([6, 18, 30, 42] if stagger else [0, 12, 24, 36])
    # Unstaggered, an added lane starts at once; staggered, in the soonest widest gap (a 12, b 18).
    assert times['c'] == ([15, 27, 39, 51] if stagger else [13, 25, 37, 49])


def test_reconfigured_lane_returns_to_its_vacated_phase(schedule):
    def replace(group, running):
        assert 'b' not in running                   # Reconciler only replaces an idle lane.
        group.remove(group[1])
        group.extend(lanes('b', interval=12))
    times = roster_run(schedule, True, replace)
    assert times['a'] == [0, 12, 24, 36]
    assert times['b'] == [6, 18, 30, 42]            # Restarted lane totals continue on the old phase.


def test_widest_gap_folds_slower_lanes_onto_a_faster_resumed_lane(schedule):
    now, clock, sleep = fake_clock()
    group = lanes('a', 'b', 'c', 'd', interval=20)  # Phases 0, 5, 10, 15.
    fast = lanes('e', interval=10)[0]
    starts = []
    def perform(lane, index, seek):
        starts.append((lane['channel'], now[0]))
        return attempt(index)
    def reconcile(running, t):
        if t >= 21 and fast not in group:
            group.append(fast)
    schedule(group, perform, lambda lane, record: None, clock=clock, sleep=sleep, continuous=True, max_attempts=3,
             rotate=lambda lane: None, reconcile=reconcile, stagger=True)
    e = [t for c, t in starts if c == 'e']
    # Folded mod 10 the others sit at 0 and 5, so every e slot is 2.5 s from them, not just the first.
    assert e == [22.5, 32.5, 42.5] and all(t % 5 == 2.5 for t in e)
    assert all((t - 5*'abcd'.index(c)) % 20 == 0 for c, t in starts if c != 'e')


from tests.test_automatic_adoption import legacy  # noqa: E402,F401  (fixture reuse)
from exp_tracker import streamer_roster as roster  # noqa: E402
from tests.test_db_streamer_roster import change, managed, run_db, running_roster  # noqa: E402,F401


@pytest.mark.parametrize('stagger', [False, True])
def test_db_roster_spreads_startup_and_a_resumed_channel_avoids_active_slots(running_roster, multi, monkeypatch, stagger):
    legacy, counters, _, scripts, driver, _ = running_roster
    module, path, clock = legacy[0], legacy[3], multi[-1]
    change(path, 'newcaster', authorized=True, tracking_enabled=True)  # 14 lanes at 20 s.
    scripts['newcaster'] = ['Alpha']               # Two strong frames switch PendingOCR to Alpha.
    starts = []
    capture = module.shadow.capture_attempt
    def timed(args, source, requirements, index, **options):
        starts.append((source.value, clock[0]))
        return capture(args, source, requirements, index, **options)
    monkeypatch.setattr(module.shadow, 'capture_attempt', timed)
    actions = set()
    def tick(running, now):
        if now >= 30 and 'pause' not in actions:
            change(path, 'newcaster', tracking_enabled=False); actions.add('pause')
        if now >= 60 and 'resume' not in actions:
            change(path, 'newcaster', tracking_enabled=True, interval=10); actions.add('resume')
    driver['tick'] = tick
    assert run_db(running_roster, '--stop-after-seconds', '105', *(['--stagger-capture'] if stagger else [])) == 0
    first = {}
    for login, t in starts:
        first.setdefault(login, t)
    resumed = [t for login, t in starts if login == 'newcaster' and t >= 60]
    assert resumed and counters['newcaster'] > len(resumed)
    with Store(path, read_only=True) as store:
        headers = [json.loads(r[0]) for r in store.db.execute('SELECT configuration_json FROM diagnostic_runs')]
        newcaster = next(row for row in roster.status(store) if row['channel'] == 'newcaster')
        assert newcaster['character']['label'] == 'Alpha'  # The switched run carries the flag too.
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
    roster_headers = [h for h in headers if h.get('database_roster')]
    if not stagger:
        assert set(first.values()) == {0} and all('stagger_capture' not in h for h in roster_headers)
        return
    assert sorted(first.values()) == pytest.approx([i*20/14 for i in range(14)])
    assert all(h.get('stagger_capture') is True for h in roster_headers) and len(roster_headers) >= 15
    others = {login: t for login, t in first.items() if login != 'newcaster'}
    for login, t in starts:                         # Other lanes never leave their own 20 s grid.
        if login != 'newcaster':
            assert (t - others[login]) % 20 == pytest.approx(0, abs=1e-6) or (t - others[login]) % 20 == pytest.approx(20)
    # Folded onto the resumed 10 s period, the 13 phases sit 10/7 s apart; each resumed slot is midway.
    for t in resumed:
        assert min(min((t-p) % 10, 10-(t-p) % 10) for p in others.values()) >= .7


def test_lane_added_when_the_only_other_slot_is_exactly_on_the_horizon(schedule):
    # A lane that just ran on time has its next slot exactly one interval (the horizon) away.
    now, clock, sleep = fake_clock()
    group = lanes('a', interval=12)
    starts = []
    def perform(lane, index, seek):
        starts.append((lane['channel'], now[0]))
        return attempt(index)
    def reconcile(running, t):
        if len(starts) == 2 and len(group) == 1:
            assert group[0]['due'] == t + 12
            group.extend(lanes('c', interval=12))
    schedule(group, perform, lambda lane, record: None, clock=clock, sleep=sleep, continuous=True, max_attempts=3,
             rotate=lambda lane: None, reconcile=reconcile, stagger=True)
    times = {c: [t for channel, t in starts if channel == c] for c in 'ac'}
    assert times == {'a': [0, 12, 24], 'c': [18, 30, 42]}  # Half an interval from a, which never moves.
