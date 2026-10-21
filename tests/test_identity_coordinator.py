"""Coordinator ownership holds, end to end on generated frames and disposable SQLite only."""

from datetime import datetime, timedelta, timezone
import functools
import importlib
from io import BytesIO
import json
import re
import time

from PIL import Image
import pytest

from tests.test_character_identity import candidate  # Also puts tools/ on sys.path.
from tests.test_multi_alpha import multi  # noqa: F401  (fixture)
from exp_tracker.diagnostics import Diagnostics, HELD_ENVELOPE, identity_held
from exp_tracker.store import Store
from exp_tracker.video import CaptureError, Frame

SCHEDULE = importlib.import_module('multi_alpha').schedule
REAL_CAPTURE = importlib.import_module('shadow_capture').capture_attempt  # Before fixtures patch it.
# Scripted receipts follow the real attempted_at clock, as real receipts follow their attempt.
BASE = (datetime.now(timezone.utc) + timedelta(minutes=5)).replace(microsecond=0)
A, B = 'Alpha', 'Beta'

# (name, level, basis points) | 'FAIL' | ('STALE', name, level, bp) | ('DISMISS', name, level, bp)
SWITCH = [(A, 30, 4000), (A, 30, 4100),
          (B, 30, 4150), (B, 30, 4160),                      # Similar EXP: only the name differs.
          (A, 30, 4200), (A, 30, 4250),                      # Return supersedes the pending switch.
          'FAIL', (None, 30, 4300), ('CONFLICT', 30, 4350),
          (A, 30, 9960), (None, 31, 30), (None, 31, 100),    # Normal level-up, names unreadable.
          (B, 31, 90), (B, 31, 95), ('DISMISS', B, 31, 97),  # Dismissed switch still holds B's readings.
          (A, 31, 150), ('STALE', A, 31, 200),
          (None, 20, 5000), (A, 31, 250)]                    # Unverified level decrease, then A again.
HELD = [False, False, True, True, True] + [False] * 7 + [True, True, True, False, False, True, False]
STABLE = [('Bravo', 40, 1000 + 100 * i) for i in range(len(SWITCH))]


def reading(requirements, level, bp):
    need = requirements[level]
    exp = need * bp // 10000
    return exp, exp * 10000 // need / 100  # Truncated display, consistent with the shared arithmetic.


@pytest.fixture
def coordinator(multi, monkeypatch):  # noqa: F811
    module, path, config, calls, now = multi
    config['streams'] = [dict(channel=c, character=label, source='file', file=config['streams'][0]['file'],
                              interval=15, count=len(SWITCH), max_age=1) for c, label in (('alpha', A), ('bravo', 'Bravo'))]
    path.write_text(json.dumps(config))
    scripts, steps, played = dict(alpha=SWITCH, bravo=STABLE), {}, {}
    current = {}
    class CaptureClock(datetime):
        @classmethod
        def now(cls, tz=None):return current.get('stamp',BASE).astimezone(tz)
    monkeypatch.setattr(module.shadow,'datetime',CaptureClock)

    def sleep(seconds): now[0] += seconds
    monkeypatch.setattr(module, 'schedule', lambda lanes, perform, emit, **kw:
                        SCHEDULE(lanes, perform, emit, clock=lambda: now[0], sleep=sleep, **kw))

    class Resident:
        def __call__(self, command, payload, timeout, metrics=None):
            step = current['step']
            if metrics is None:  # EXP request; the name request is the one carrying metrics.
                exp, pct = step['reading']
                text = f'{exp}[{pct:.2f}%]'
                response=dict(text=text, raw=dict(txts=[text], scores=[.99]))
                if '--experimental-neural-level' in command:
                    from shadow_neural import level_result
                    response['neural_level']=level_result(dict(txts=[str(step['level'])],scores=[.99]),0,0)
                return json.dumps(response).encode()
            if step['stale']: time.sleep(1.05)
            names = [A, B] if step['name'] == 'CONFLICT' else [step['name']]
            return json.dumps(dict(text=None, raw=dict(txts=names, scores=[.99] * len(names)))).encode()
        def close(self): pass
    monkeypatch.setattr(module.shadow, 'ResidentNeural', Resident)

    real = REAL_CAPTURE
    def capture(args, source, requirements, index, *, seek=None, **options):
        options.setdefault('resident', Resident())  # Same worker path whether or not names are enabled.
        channel = args.channel or args.tracking_channel
        n = steps[channel] = steps.get(channel, 0) + 1
        step = scripts[channel][(n - 1) % len(scripts[channel])]
        interval = next(row['interval'] for row in config['streams'] if row['channel']==channel)
        received = (BASE + timedelta(seconds=interval * n)).isoformat()
        current['stamp']=datetime.fromisoformat(received)
        if step == 'FAIL':
            class Failed:
                source_bytes = 0
                def frame(self, **kw): raise CaptureError('frame_timeout')
                def close(self): pass
            return real(args, source, requirements, index, seek=seek, session_factory=lambda *a, **k: Failed(), **options)
        marked = step[0] in ('STALE', 'DISMISS', 'DUPLICATE', 'MULTI')
        if step[0] == 'DISMISS' and 'identity' in options:
            options['identity'].suggestions.dismiss(received)
        name, level, bp = step[1:] if marked else step
        current['step'] = dict(name=name, level=level, reading=reading(requirements, level, bp), stale=step[0] == 'STALE')
        played.setdefault(channel, []).append(dict(n=n, name=name, level=level, reading=current['step']['reading']))
        pixel = n-1 if step[0]=='DUPLICATE' else n
        image = Image.new('RGB', (1920, 1080), (pixel % 256, 10 + pixel // 256, 20))
        data = BytesIO(); image.save(data, format='PNG')
        class Session:
            source_bytes = len(data.getvalue())
            def frame(self, **kw): return Frame(data.getvalue(), n, time.monotonic(), received)
            def close(self): pass
        analyze = functools.partial(module.shadow.analyze, locator=lambda image: candidate() * (2 if step[0]=='MULTI' else 1),
                                    read_level=lambda crop: (level, []))
        return real(args, source, requirements, index, seek=seek, session_factory=lambda *a, **k: Session(),
                    analyze_frame=analyze, **options)
    monkeypatch.setattr(module.shadow, 'capture_attempt', capture)
    return module, path, config, played, steps, scripts


def run(coordinator, *extra):
    module, path = coordinator[:2]
    assert module.main(['--config', str(path), '--exit-after-capture', *extra]) == 0
    return path.parent / 'shared.sqlite3'


def payloads(db, channel):
    with Store(db, read_only=True) as store:
        return [json.loads(r[0]) for r in store.db.execute(
            'SELECT a.payload_json FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id '
            'JOIN streamers s ON s.id=r.streamer_id WHERE s.login=? ORDER BY a.id', (channel,))]


NOW = BASE + timedelta(seconds=15 * len(SWITCH) + 10)


def public(db, channel):
    """Every public projection, with per-process identifiers normalized."""
    with Store(db, read_only=True) as store:
        diagnostics = Diagnostics(store)
        with store._transaction():
            head = next(h for h in diagnostics.heads() if h['login'] == channel)
            entry = diagnostics.card({}, head, now=NOW)
        cards = diagnostics.directory({}, now=NOW)['streams']
        value = dict(card=entry[1], extras=entry[2], directory=next(c for c in cards if c['channel'] == channel),
                     rolling=diagnostics.rolling_history(channel, now=NOW))
    text = json.dumps(value, sort_keys=True, default=str)
    # Storage receipts count payload bytes; held/name payloads are legitimately larger.
    text = re.sub(r'("\w*_bytes": )\d+', r'\g<1>0', text)
    text = re.sub(r'"started_at": "[^"]*"', '"started_at": null', text)  # Wall-clock session creation per DB.
    return json.loads(re.sub(r'\b[0-9a-f]{32}\b', 'ID', text))


def differences(a, b, path=''):
    """Differing JSON paths; cheap, unlike a text diff of two large projections."""
    if isinstance(a, dict) and isinstance(b, dict):
        return [p for k in sorted(set(a) | set(b)) for p in differences(a.get(k), b.get(k), f'{path}.{k}')]
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [p for i, (x, y) in enumerate(zip(a, b)) for p in differences(x, y, f'{path}[{i}]')]
    return [] if a == b else [path]


def rebuild(db, source_db, channel, transform, limit=None):
    """A fresh disposable DB holding the same run (optionally its first attempts), each attempt transformed."""
    with Store(source_db, read_only=True) as source:
        run = dict(source.db.execute('SELECT r.* FROM diagnostic_runs r JOIN streamers s ON s.id=r.streamer_id '
                                     'WHERE s.login=? ORDER BY r.rowid DESC LIMIT 1', (channel,)).fetchone())
        label = source.db.execute('SELECT label FROM characters WHERE id=?', (run['character_id'],)).fetchone()[0]
    with Store(db) as store:
        store.add_channel(channel)
        store.select_character(channel, store.add_character(channel, label))
        store.start_session(channel)
        diagnostics = Diagnostics(store)
        diagnostics.begin(run['run_id'], channel, json.loads(run['configuration_json']))
        for record in payloads(source_db, channel)[:limit]:
            diagnostics.append(run['run_id'], transform(record))
        if run['summary_json'] and limit is None:
            diagnostics.append(run['run_id'], json.loads(run['summary_json']))
    return db


def test_holds_follow_identity_policy_and_preserve_private_evidence(coordinator):
    db = run(coordinator, '--character-names')
    stored = payloads(db, 'alpha')
    assert [r['index'] for r in stored] == list(range(1, len(SWITCH) + 1))  # Contiguous, nothing dropped.
    assert [r.get('identity_hold') is not None for r in stored] == HELD
    played = {p['n']: p for p in coordinator[3]['alpha']}
    for n, record in enumerate(stored, 1):
        if HELD[n - 1]:
            assert set(record) <= {*HELD_ENVELOPE, 'status', 'current', 'reasons', 'identity_hold'}
            assert (record['status'], record['current'], record['reasons']) == ('unavailable', False, ['identity_hold'])
            evidence = record['identity_hold']['evidence']
            assert evidence['candidate'] == list(played[n]['reading']) and evidence['visual_level'] == played[n]['level']
            assert evidence['character_name']['evidence']['name'] == played[n]['name']
            assert 'neural' not in record and 'frame_sha256' not in record
        else:
            assert record['character_name']['reading_hold_recommended'] is False
    reasons = {n: stored[n - 1]['identity_hold']['hold_reasons'] for n in range(1, len(SWITCH) + 1) if HELD[n - 1]}
    assert reasons == {3: ['name_mismatch'], 4: ['name_mismatch', 'pending_switch'], 5: ['pending_switch'],
                       13: ['name_mismatch', 'unverified_numeric_anomaly'],
                       14: ['name_mismatch', 'pending_switch', 'unverified_numeric_anomaly'],
                       15: ['name_mismatch', 'unverified_numeric_anomaly'], 18: ['unverified_numeric_anomaly']}
    assert stored[6]['status'] == 'capture_failed'
    assert stored[8]['character_name']['evidence']['status'] == 'unreadable_or_conflicting'
    assert stored[16]['character_name']['evidence']['status'] == 'stale_local_frame'
    level_up = stored[10]['character_name']
    assert level_up['verification_requested'] and level_up['numeric_check']['classification'] == 'possible_normal_level_up'
    assert all(r['index'] and 'identity_hold' not in r for r in payloads(db, 'bravo'))
    with Store(db, read_only=True) as store:
        assert {r[0] for r in store.db.execute('SELECT label FROM characters')} == {A, 'Bravo'}  # No OCR-created roster.
        assert store.state('alpha')['selected_character_id'] == store.db.execute(
            'SELECT id FROM characters WHERE label=?', (A,)).fetchone()[0]
        config = json.loads(store.db.execute('SELECT configuration_json FROM diagnostic_runs LIMIT 1').fetchone()[0])
        assert config['character_names'] and config['identity_policy'] == 'review_only_v2'
    # The private lane log holds exactly what SQLite holds, so replay cannot release anything.
    log = next((db.parent / 'multi-alpha/runs').glob('*/alpha/capture.jsonl'))
    lines = [json.loads(l) for l in log.read_text(encoding='utf-8').splitlines()]
    assert [l for l in lines if l['type'] == 'attempt'] == stored


def test_held_readings_never_reach_public_projections(coordinator, tmp_path):
    db = run(coordinator, '--character-names')
    # Control: the same run with each held attempt replaced by an evidence-free attempt.
    blank = lambda r: {k: r[k] for k in HELD_ENVELOPE if k in r} | dict(status='unavailable', current=False, reasons=[]) \
        if 'identity_hold' in r else r
    control = rebuild(tmp_path / 'private/control.sqlite3', db, 'alpha', blank)
    assert differences(public(db, 'alpha'), public(control, 'alpha')) == []
    # Sensitivity: releasing the held evidence (no hold) visibly changes the public result.
    release = lambda r: {k: v for k, v in {**r, **r['identity_hold']['evidence']}.items()
                         if k not in ('identity_hold', 'character_name')} if 'identity_hold' in r else r
    leaked = rebuild(tmp_path / 'private/leaked.sqlite3', db, 'alpha', release)
    assert differences(public(db, 'alpha'), public(leaked, 'alpha'))
    for limit in (5, 18):  # A held attempt is the latest one: last-known state must stay A's.
        same = rebuild(tmp_path / f'private/held-{limit}.sqlite3', db, 'alpha', lambda r: r, limit)
        blank_db = rebuild(tmp_path / f'private/control-{limit}.sqlite3', db, 'alpha', blank, limit)
        assert differences(public(same, 'alpha'), public(blank_db, 'alpha')) == []
        with Store(same, read_only=True) as store:
            card = Diagnostics(store).directory({}, now=NOW)['streams'][0]
        assert card['visual_level'] is None and card['full_exp']['event_id'].endswith(':2' if limit == 5 else ':17')
    with Store(db, read_only=True) as store:
        card = Diagnostics(store).directory({}, now=NOW)['streams'][0]
        observations = Diagnostics(store).snapshot('alpha', now=NOW)['observations']
    assert card['channel'] == 'alpha' and card['full_exp']['event_id'].endswith(':19')
    assert card['visual_level'] == 31  # Last attributable state is A's, not the held level-20 reading.
    assert [o['visual_level'] for o in observations if o['status'] == 'unavailable'] == [None] * HELD.count(True)
    assert 31 in [o['visual_level'] for o in observations]  # The valid level-up is ordinary progress.


def test_matching_names_leave_ordinary_results_unchanged(coordinator, tmp_path):
    enabled = run(coordinator, '--character-names')
    first = public(enabled, 'bravo')
    enabled.rename(tmp_path / 'private/enabled.sqlite3')
    enabled.with_suffix('.sqlite3.multi-alpha.json').rename(tmp_path / 'private/enabled.marker')
    coordinator[4].clear()
    disabled = run(coordinator)
    assert differences(public(disabled, 'bravo'), first) == []
    assert all('character_name' not in r for r in payloads(disabled, 'alpha'))
    with Store(disabled, read_only=True) as store:
        config = json.loads(store.db.execute('SELECT configuration_json FROM diagnostic_runs LIMIT 1').fetchone()[0])
        assert 'character_names' not in config and 'resident_neural' not in config


def test_replay_restart_and_untransformed_logs_stay_held(coordinator, tmp_path):
    module, path, config = coordinator[:3]
    db = run(coordinator, '--character-names')
    logs = {c: next((db.parent / 'multi-alpha/runs').glob(f'*/{c}/capture.jsonl')) for c in ('alpha', 'bravo')}
    # Replay into a fresh disposable database stores byte-identical payloads.
    config['database'] = 'private/replayed.sqlite3'
    path.write_text(json.dumps(config))
    replay = [f'--replay={c}={p.relative_to(tmp_path)}' for c, p in logs.items()]
    assert module.main(['--config', str(path), '--exit-after-capture', *replay]) == 0
    assert payloads(path.parent / 'replayed.sqlite3', 'alpha') == payloads(db, 'alpha')
    # An older log written before the coordinator hold is held by the persistence boundary itself.
    raw = [dict(r, **r['identity_hold']['evidence']) for r in payloads(db, 'alpha') if 'identity_hold' in r]
    raw = [{k: v for k, v in r.items() if k != 'identity_hold'} for r in raw]
    assert [identity_held(r) for r in raw] == [r for r in payloads(db, 'alpha') if 'identity_hold' in r]
    unheld = lambda r: {k: v for k, v in {**r, **r['identity_hold']['evidence']}.items() if k != 'identity_hold'} \
        if 'identity_hold' in r else r
    assert payloads(rebuild(tmp_path / 'private/old-writer.sqlite3', db, 'alpha', unheld), 'alpha') == payloads(db, 'alpha')
    assert identity_held(dict(type='attempt', candidate=[1, .1], character_name={}))['reasons'] == ['identity_hold']
    # Restart: a NEW process re-initializes from the operator selection, never from OCR.
    config['database'] = 'private/shared.sqlite3'
    path.write_text(json.dumps(config))
    coordinator[4]['alpha'] = len(SWITCH) + 2  # Next process starts (later) with Beta on screen.
    assert module.main(['--config', str(path), '--exit-after-capture', '--character-names']) == 0
    second = payloads(db, 'alpha')[len(SWITCH):]
    assert [r.get('identity_hold') is not None for r in second[:3]] == [True, True, True]
    with Store(db, read_only=True) as store:
        assert store.state('alpha')['selected_character_id'] == 1


def test_pending_switch_survives_rotation_and_attempts_stay_contiguous(coordinator):
    # The script cycles; attempts 60, 61, 62 are B, B, A, straddling the 60-attempt rotation.
    db = run(coordinator, '--character-names', '--continuous', '--max-attempts', '64')
    with Store(db, read_only=True) as store:
        runs = [r[0] for r in store.db.execute(
            "SELECT r.run_id FROM diagnostic_runs r JOIN streamers s ON s.id=r.streamer_id WHERE s.login='alpha' ORDER BY r.rowid")]
        counts = [store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts WHERE run_id=?', (r,)).fetchone()[0] for r in runs]
        indices = [[i for (i,) in store.db.execute('SELECT attempt_index FROM diagnostic_attempts WHERE run_id=? '
                                                   'ORDER BY attempt_index', (r,))] for r in runs]
    assert counts == [60, 4] and indices == [list(range(1, 61)), [1, 2, 3, 4]]
    held = [r.get('identity_hold') is not None for r in payloads(db, 'alpha')]
    assert held[59:62] == [True, True, True]  # Mismatch, then the pending switch created in the NEW run.
    assert payloads(db, 'alpha')[60]['identity_hold']['hold_reasons'] == ['name_mismatch', 'pending_switch']
    assert held == [HELD[i % len(SWITCH)] for i in range(64)]
