from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import importlib
import json
import sqlite3

import pytest

from exp_tracker.diagnostics import Diagnostics, main
from exp_tracker.schema import MIGRATION_2, STATEMENTS, VERSION
from exp_tracker.store import Store

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
CONFIG = dict(type='configuration', trusted=False, interval=15, count=3)
SUMMARY = dict(type='summary', trusted=False, interrupted=False, attempts=3)


def attempt(index=1):
    return dict(type='attempt', index=index, trusted=False, current=True,
        attempted_at=(NOW + timedelta(seconds=index * 15)).isoformat(),
        received_at=None, source=dict(kind='twitch', channel='alpha'),
        candidate=[100 + index, 25.0], status='diagnostic_pair', neural=dict(text=f'{100+index}[25.00%]'),
        visual_level=51, visual_status='available',
        neural_level=dict(status='numeric_candidate', text='51', level=51, score=.99))


@pytest.fixture
def configured(tmp_path):
    path = tmp_path / 'alpha.sqlite3'
    with Store(path) as store:
        store.add_channel('alpha')
        char = store.add_character('alpha', 'Explicit character')
        store.select_character('alpha', char)
        store.start_session('alpha', at=NOW)
    return path


def write_log(tmp_path, monkeypatch, rows):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / 'private/trial.jsonl'
    path.parent.mkdir(exist_ok=True)
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows), encoding='utf-8')
    return path


def test_realistic_replay_restart_idempotence_and_trust_separation(configured, tmp_path, monkeypatch):
    failed = attempt(2)
    failed.update(status='capture_failed', current=False, candidate=None, neural=None)
    only = attempt(3)
    only.update(candidate=None, neural=dict(text='[70.51%]'), diagnostic_type='percentage_only',
                percentage_only_candidate=dict(percentage_bp=7051, percentage='70.51', trusted=False))
    # Use the parser's actual representation, not a competing percentage model.
    from exp_tracker.shadow_types import parse_percentage_only
    only['percentage_only_candidate'] = parse_percentage_only('[70.51%]')
    log = write_log(tmp_path, monkeypatch, [CONFIG, attempt(), failed, only, SUMMARY])
    original = log.read_bytes()
    with Store(configured) as store:
        before = store.state('alpha', as_of=NOW)
        receipt = Diagnostics(store).replay('alpha', log)
        assert receipt['inserted_records'] == 4
        assert store.state('alpha', as_of=NOW) == before
        assert store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0] == 0
    with Store(configured) as store:
        assert Diagnostics(store).replay('alpha', log)['inserted_records'] == 0
        snap = Diagnostics(store).snapshot('alpha', now=NOW+timedelta(seconds=50))
        assert [r['index'] for r in snap['observations']] == [1, 2, 3]
        assert snap['observations'][1]['candidate'] is None
        assert snap['latest_reading']['observation']['percentage_only_candidate']['percentage'] == '70.51'
        assert snap['latest_reading']['observation']['candidate'] is None
        assert snap['observations'][0]['neural_level']['level'] == 51
        assert snap['trusted_state']['last_trusted'] is None
        assert snap['session']['id'] == receipt['session_id']
        assert snap['selected_character']['id'] == receipt['character_id']
        assert len({r['event_id'] for r in snap['observations']}) == 3
    assert log.read_bytes() == original


def test_explicit_selection_session_and_source_are_required(configured):
    with Store(configured) as store:
        diagnostic = Diagnostics(store)
        diagnostic.begin('run', 'alpha', CONFIG)
        wrong = attempt()
        wrong['source']['channel'] = 'other'
        with pytest.raises(ValueError, match='source'):
            diagnostic.append('run', wrong)
        store.add_channel('empty')
        with pytest.raises(ValueError, match='select'):
            diagnostic.begin('empty', 'empty', CONFIG)
        store.end_session('alpha', at=NOW)
        with pytest.raises(ValueError, match='assignment changed'):
            diagnostic.append('run', attempt())


def test_switches_isolate_sessions_and_replay_cannot_reassign(configured, tmp_path, monkeypatch):
    log = write_log(tmp_path, monkeypatch, [CONFIG, attempt(), SUMMARY])
    with Store(configured) as store:
        diagnostic = Diagnostics(store)
        first = diagnostic.replay('alpha', log)
        second_char = store.add_character('alpha', 'Second')
        store.select_character('alpha', second_char, at=NOW+timedelta(seconds=30))
        store.start_session('alpha', at=NOW+timedelta(seconds=30))
        assert diagnostic.replay('alpha', log)['character_id'] == first['character_id']
        assert diagnostic.snapshot('alpha')['observations'] == []
        diagnostic.begin('second', 'alpha', CONFIG)
        diagnostic.append('second', attempt())
        assert len(diagnostic.snapshot('alpha')['observations']) == 1
        store.add_channel('other')
        with pytest.raises(ValueError, match='different source'):
            diagnostic.replay('other', log)


def test_atomic_replay_rollback_and_changed_event_rejection(configured, tmp_path, monkeypatch):
    bad = attempt(2)
    bad['index'] = 3
    log = write_log(tmp_path, monkeypatch, [CONFIG, attempt(), bad, SUMMARY])
    with Store(configured) as store:
        diagnostic = Diagnostics(store)
        with pytest.raises(ValueError, match='order'):
            diagnostic.replay('alpha', log)
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_runs').fetchone()[0] == 0
        diagnostic.begin('stable', 'alpha', CONFIG)
        diagnostic.append('stable', attempt())
        changed = attempt()
        changed['candidate'] = [99999, 25]
        with pytest.raises(ValueError, match='different contents'):
            diagnostic.append('stable', changed)
        assert len(diagnostic.snapshot('alpha')['observations']) == 1
        store.db.execute("""CREATE TRIGGER fail_diagnostic BEFORE INSERT ON diagnostic_attempts
            BEGIN SELECT RAISE(ABORT, 'injected'); END""")
        with pytest.raises(sqlite3.IntegrityError, match='injected'):
            diagnostic.append('stable', attempt(2))
        assert len(diagnostic.snapshot('alpha')['observations']) == 1


def test_failed_stale_out_of_order_and_malformed_attempts_preserve_evidence(configured):
    with Store(configured) as store:
        diagnostic = Diagnostics(store)
        diagnostic.begin('run', 'alpha', CONFIG)
        diagnostic.append('run', attempt())
        bad = attempt(2)
        bad.update(candidate=None, neural=dict(text='0.85%1'), status='malformed_or_unavailable')
        diagnostic.append('run', bad)
        old = attempt(3)
        old.update(attempted_at=NOW.isoformat(), status='stale_local_frame', current=False)
        diagnostic.append('run', old)
        snap = diagnostic.snapshot('alpha', now=NOW+timedelta(seconds=70))
        assert snap['stale'] and snap['observations'][2]['timestamp_ordered'] is False
        assert snap['latest_reading']['observation']['index'] == 1
        assert snap['latest_reading']['stale']
        assert snap['observations'][1]['raw_text'] == '0.85%1'
        assert snap['observations'][1]['percentage_only_candidate'] is None


def test_history_spans_runs_but_not_sessions_and_is_bounded(configured):
    with Store(configured) as store:
        diagnostic = Diagnostics(store)
        for run in range(3):
            diagnostic.begin(f'run{run}', 'alpha', CONFIG)
            for index in range(1, 61):
                row = attempt(index)
                row['attempted_at'] = (NOW+timedelta(seconds=(60*run+index)*15)).isoformat()
                diagnostic.append(f'run{run}', row)
        snap = diagnostic.snapshot('alpha')
        assert len(snap['observations']) == 120 and snap['truncated']
        assert len({r['event_id'] for r in snap['observations']}) == 120


@pytest.mark.parametrize('change', [dict(trusted=True), dict(index=0), dict(index=True),
    dict(attempted_at='2026-01-01'), dict(received_at='bad'), dict(source=None), dict(neural='x'*65536),
    dict(status=[]), dict(visual_status=[]), dict(neural_level=dict(status=[]))])
def test_invalid_boundaries_do_not_write(configured, change):
    with Store(configured) as store:
        diagnostic = Diagnostics(store)
        diagnostic.begin('run', 'alpha', CONFIG)
        row = attempt()
        row.update(change)
        with pytest.raises(ValueError):
            diagnostic.append('run', row)
        assert not diagnostic.snapshot('alpha')['observations']


def test_v2_migration_is_additive_and_reader_refuses_to_migrate(tmp_path):
    path = tmp_path / 'v2.sqlite3'
    with sqlite3.connect(path) as db:
        for statement in (*STATEMENTS, *MIGRATION_2):
            db.execute(statement)
        db.execute("INSERT INTO streamers(login) VALUES ('preserved')")
        db.execute('PRAGMA user_version=2')
    with pytest.raises(ValueError, match='schema version 2'):
        Store(path, read_only=True)
    with Store(path) as store:
        assert store.db.execute('PRAGMA user_version').fetchone()[0] == VERSION
        assert store.state('preserved')['channel'] == 'preserved'
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
    with Store(path, read_only=True) as store:
        assert store.state('preserved')['channel'] == 'preserved'


def test_snapshot_concurrent_with_writer_and_private_fields_are_not_exposed(configured):
    with Store(configured) as store:
        diagnostic = Diagnostics(store)
        diagnostic.begin('run', 'alpha', CONFIG)
    def write():
        with Store(configured) as store:
            for index in range(1, 31):
                row = attempt(index)
                row['secret_url'] = 'https://private/token=secret'
                Diagnostics(store).append('run', row)
    def read():
        for _ in range(20):
            with Store(configured, read_only=True) as store:
                snap = Diagnostics(store).snapshot('alpha')
                assert len({r['event_id'] for r in snap['observations']}) == len(snap['observations'])
                assert 'secret' not in json.dumps(snap)
    with ThreadPoolExecutor(2) as executor:
        for future in [executor.submit(write), executor.submit(read)]:
            future.result()


def test_capture_cli_persists_same_jsonl_and_refuses_reassignment(configured, tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(__import__('pathlib').Path('tools').resolve()))
    shadow = importlib.import_module('shadow_capture')
    monkeypatch.setattr(shadow, 'ROOT', tmp_path)
    monkeypatch.setattr(shadow.shutil, 'which', lambda _: 'ffmpeg')
    table = tmp_path / 'table.json'
    table.write_text(json.dumps({'to_next': {'1': 15}}))
    executable = tmp_path / 'python'
    executable.touch()
    output = tmp_path / 'private/live.jsonl'
    def run(args, source, requirements, emit):
        assert args.experimental_neural_level
        emit(attempt())
        return SUMMARY
    monkeypatch.setattr(shadow, 'run', run)
    args = ['--channel', 'alpha', '--authorized', '--db', str(configured), '--output', str(output),
            '--requirements', str(table), '--ocr-python', str(executable), '--experimental-neural-level']
    assert shadow.main(args) == 0
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    monkeypatch.chdir(tmp_path)
    with Store(configured) as store:
        snap = Diagnostics(store).snapshot('alpha')
        assert len(snap['observations']) == 1 and snap['observations'][0]['neural_level']['level'] == 51
        saved = store.db.execute('SELECT payload_json FROM diagnostic_attempts').fetchone()[0]
        assert json.loads(saved) == rows[1]
        assert Diagnostics(store).replay('alpha', output)['inserted_records'] == 0
        assert store.state('alpha')['last_trusted'] is None


def test_replay_cli_and_incomplete_input_do_not_modify_evidence(configured, tmp_path, monkeypatch):
    log = write_log(tmp_path, monkeypatch, [CONFIG, attempt(), SUMMARY])
    assert main(['--db', str(configured), '--channel', 'alpha', str(log)]) == 0
    with log.open('a') as handle:
        handle.write('{')
    assert main(['--db', str(configured), '--channel', 'alpha', str(log)]) == 1


def test_capture_binding_change_stops_persistence_but_keeps_jsonl_evidence(configured, tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(__import__('pathlib').Path('tools').resolve()))
    shadow = importlib.import_module('shadow_capture')
    monkeypatch.setattr(shadow, 'ROOT', tmp_path)
    monkeypatch.setattr(shadow.shutil, 'which', lambda _: 'ffmpeg')
    table = tmp_path / 'requirements.json'
    table.write_text(json.dumps({'to_next': {'1': 15}}))
    executable = tmp_path / 'python'
    executable.touch()
    output = tmp_path / 'private/interrupted.jsonl'
    def run(args, source, requirements, emit):
        emit(attempt())
        with Store(configured) as store:
            store.end_session('alpha')
        emit(attempt(2))
        pytest.fail('Runner continued after persistence failed')
    monkeypatch.setattr(shadow, 'run', run)
    assert shadow.main(['--channel', 'alpha', '--authorized', '--db', str(configured),
        '--requirements', str(table), '--ocr-python', str(executable), '--output', str(output)]) == 1
    assert len(output.read_text().splitlines()) == 3
    with Store(configured) as store:
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0] == 1
        assert store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0] == 0
