from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import socket
import sqlite3
from urllib.parse import urlsplit

import pytest

from exp_tracker.diagnostics import Diagnostics
from exp_tracker.schema import STATEMENTS, MIGRATION_2
from exp_tracker.store import Store


@pytest.fixture
def alpha(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path('tools').resolve()))
    module = importlib.import_module('local_alpha')
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module.shadow_capture, 'ROOT', tmp_path)
    monkeypatch.setattr(module, 'configure_tesseract', lambda: None)
    monkeypatch.setattr(module.shadow_capture.shutil, 'which', lambda _: 'ffmpeg')
    video = tmp_path / 'video.mp4'
    video.touch()
    table = tmp_path / 'table.json'
    table.write_text(json.dumps({'to_next': {'1': 15}}))
    executable = tmp_path / 'python'
    executable.touch()
    args = ['--channel', 'alpha', '--character', 'Main', '--file', str(video),
            '--requirements', str(table), '--ocr-python', str(executable), '--port', '0', '--exit-after-capture']
    calls = []
    def run(options, source, requirements, emit, **kwargs):
        calls.append((options, source))
        emit(record())
        return dict(type='summary', trusted=False, attempts=1, interrupted=False)
    monkeypatch.setattr(module.shadow_capture, 'run', run)
    return module, args, tmp_path / 'private/local-alpha/live/alpha.sqlite3', calls


def record(**changes):
    return dict(type='attempt', trusted=False, current=True, index=1,
        source=dict(kind='file', channel=None), attempted_at=datetime.now(timezone.utc).isoformat(),
        received_at=datetime.now(timezone.utc).isoformat(), reasons=[], status='diagnostic_pair',
        localization=dict(count=1), candidate=[123, 45.67], neural=dict(text='123[45.67%]'),
        visual_level=None, visual_status='unavailable', **changes)


def test_initialize_restart_same_selection_history_and_shutdown(alpha, capsys):
    module, args, database, calls = alpha
    assert module.main(args) == 0
    with Store(database, read_only=True) as store:
        first = store.state('alpha')
        assert len(Diagnostics(store).snapshot('alpha')['observations']) == 1
        assert store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0] == 0
    assert module.main(args) == 0
    with Store(database, read_only=True) as store:
        state = store.state('alpha')
        assert state['session']['id'] == first['session']['id']
        assert store.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 1
        assert len(Diagnostics(store).snapshot('alpha')['observations']) == 2
        assert state['last_trusted'] is None and state['observed_session_exp'] == 0
    paths = list(database.parent.parent.glob('runs/*/capture.jsonl'))
    assert len(paths) == 2 and paths[0] != paths[1]
    text = capsys.readouterr().out
    assert 'reuse session 1' in text and 'SQLite=committed' in text
    assert 'frame=acquired; HUD=unique; EXP=123 [45.67%]' in text
    assert 'neural level=off' in text and 'UNVERIFIED' in text
    for line in text.splitlines():
        if line.startswith('Dashboard: '):
            port = urlsplit(line.removeprefix('Dashboard: ')).port
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', port))  # Launcher actually closed the listening socket.


@pytest.mark.parametrize('kind', ['channel', 'character'])
def test_mismatches_refuse_before_mutation_or_capture(alpha, kind, capsys):
    module, args, database, calls = alpha
    assert module.main(args) == 0
    original = database.read_bytes()
    calls.clear()
    changed = args.copy()
    if kind == 'character':
        changed[changed.index('--character') + 1] = 'Other'
    else:
        changed[changed.index('--channel') + 1] = 'other_channel'
        changed += ['--db', str(database)]
    assert module.main(changed) == 1
    assert not calls and database.read_bytes() == original
    assert 'mismatch' in capsys.readouterr().out


@pytest.mark.parametrize('reason', ['offline_or_unavailable', 'access_denied', 'network_unavailable', 'frame_timeout'])
def test_failed_capture_is_committed_but_not_tracking_success(alpha, monkeypatch, reason, capsys):
    module, args, database, calls = alpha
    def run(options, source, requirements, emit, **kwargs):
        row = record()
        row.update(status='capture_failed', current=False, received_at=None, candidate=None,
                   neural=None, localization=None, reasons=[reason])
        emit(row)
        return dict(type='summary', trusted=False, attempts=1, interrupted=False)
    monkeypatch.setattr(module.shadow_capture, 'run', run)
    assert module.main(args) == 2
    text = capsys.readouterr().out
    assert 'frame=FAILED' in text and 'SQLite=committed' in text
    assert '0 fresh strict diagnostic candidates' in text
    with Store(database, read_only=True) as store:
        snap = Diagnostics(store).snapshot('alpha')
        assert snap['observations'][0]['status'] == 'capture_failed'
        assert snap['trusted_state']['last_trusted'] is None


@pytest.mark.parametrize('mode', ['missing_hud', 'multiple_huds', 'malformed', 'stale'])
def test_recognition_failures_are_distinct_and_untrusted(alpha, monkeypatch, mode, capsys):
    module, args, database, calls = alpha
    def run(options, source, requirements, emit, **kwargs):
        row = record()
        if mode in ('missing_hud', 'multiple_huds'):
            row.update(candidate=None, neural=None, status='unavailable',
                       localization=dict(count=0 if mode == 'missing_hud' else 2), reasons=[mode])
        elif mode == 'malformed':
            row.update(candidate=None, neural=dict(text='[70.63%1'), status='malformed_or_unavailable',
                       reasons=['strict_pair_unavailable'])
        else:
            row.update(current=False, status='stale_local_frame', reasons=['local_receipt_age_exceeded'])
        emit(row)
        return dict(type='summary', trusted=False, attempts=1, interrupted=False)
    monkeypatch.setattr(module.shadow_capture, 'run', run)
    assert module.main(args) == 2
    output = capsys.readouterr().out
    assert 'frame=acquired' in output and 'SQLite=committed' in output
    if mode == 'stale':
        assert 'STALE' in output
    elif mode == 'malformed':
        assert 'EXP=unavailable/rejected' in output
    else:
        assert f'HUD={"missing" if mode == "missing_hud" else "ambiguous"}' in output


def test_live_requires_permission_before_setup(alpha, capsys):
    module, args, database, calls = alpha
    live = args.copy()
    i = live.index('--file')
    del live[i:i+2]
    assert module.main(live) == 1
    assert not database.exists() and not calls
    assert '--authorized' in capsys.readouterr().out


def test_port_failure_never_starts_capture(alpha):
    module, args, database, calls = alpha
    with socket.socket() as held:
        held.bind(('127.0.0.1', 0))
        held.listen()
        blocked = args.copy()
        blocked[blocked.index('--port')+1] = str(held.getsockname()[1])
        assert module.main(blocked) == 1
    assert not calls


def test_interruption_cleans_server_and_preserves_assignment(alpha, monkeypatch, capsys):
    module, args, database, calls = alpha
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(module.shadow_capture, 'run', interrupted)
    assert module.main(args) == 130
    with Store(database, read_only=True) as store:
        assert store.state('alpha')['session']['id'] == 1
        assert store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0] == 0
    assert 'Interrupted' in capsys.readouterr().out


def test_persistence_failure_is_not_reported_as_committed(alpha, monkeypatch, capsys):
    module, args, database, calls = alpha
    original = module.initialize
    def initialize(*args):
        state = original(*args)
        with Store(database) as store:
            store.db.execute("""CREATE TRIGGER fail BEFORE INSERT ON diagnostic_attempts
                BEGIN SELECT RAISE(ABORT, 'injected'); END""")
        return state
    monkeypatch.setattr(module, 'initialize', initialize)
    assert module.main(args) == 1
    output = capsys.readouterr().out
    assert 'SQLite=NOT COMMITTED' in output and '0 SQLite commits' in output
    with Store(database, read_only=True) as store:
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0] == 0


def test_guarded_setup_refuses_concurrent_selection_changes(alpha):
    module, args, database, calls = alpha
    module.initialize(database, 'alpha', 'Main', lambda _: None)
    with Store(database) as store:
        other = store.add_character('alpha', 'Other')
        with pytest.raises(ValueError, match='refusing automatic switch'):
            store.select_character('alpha', other, only_if_unselected=True)
        with pytest.raises(ValueError, match='refusing session reassignment'):
            store.start_session('alpha', expected_character_id=other)
        assert store.state('alpha')['selected_character_id'] != other


def test_schema_mismatch_does_not_migrate_saved_database(alpha):
    module, args, database, calls = alpha
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as db:
        for statement in (*STATEMENTS, *MIGRATION_2):
            db.execute(statement)
        db.execute("INSERT INTO streamers(login) VALUES ('alpha')")
        db.execute('PRAGMA user_version=2')
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    assert module.main(args) == 1
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert not calls


@pytest.mark.parametrize('extra', [['--count', '61'], ['--interval', 'nan'], ['--port', '-1']])
def test_invalid_bounds_fail_before_initializing(alpha, extra):
    module, args, database, calls = alpha
    assert module.main(args + extra) == 1
    assert not database.exists() and not calls


def test_config_binding_race_stops_before_first_frame(alpha, monkeypatch, capsys):
    module, args, database, calls = alpha
    create = module.create_server
    def changed(*args, **kwargs):
        with Store(database) as store:
            other = store.add_character('alpha', 'Other operator selection')
            store.select_character('alpha', other)
            store.start_session('alpha')
        return create(*args, **kwargs)
    monkeypatch.setattr(module, 'create_server', changed)
    assert module.main(args) == 1
    assert not calls
    assert 'Assignment changed during startup' in capsys.readouterr().out
    with Store(database, read_only=True) as store:
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0] == 0


@pytest.mark.parametrize('interrupted',[False,True])
def test_owned_runtime_is_visible_while_capturing_and_cleared_at_shutdown(alpha,monkeypatch,interrupted):
    from datetime import timedelta
    from tests.test_server import request
    module,args,database,_=alpha
    create=module.create_server;servers=[];final=[]
    def status():
        server=servers[0]
        from tests.test_publisher import wait_for
        wait_for(lambda:server.publisher.entry('alpha') is not None,seconds=5)
        board=json.loads(request((server,None),'/api/players')[2])['players'][0]['activity']
        detail=json.loads(request((server,None),'/api/players/alpha')[2])['player']['activity']
        assert board==detail
        return detail
    def server(*a,**kw):
        assert kw.get('background') is True
        http=create(*a,**kw);servers.append(http);shutdown=http.shutdown
        def stop():
            final.append(status());assert not http.active_run_ids;shutdown()
        http.shutdown=stop;return http
    monkeypatch.setattr(module,'create_server',server)
    def run(options,source,requirements,emit,*,on_activity):
        now=datetime.now(timezone.utc)
        on_activity(dict(state='running',updated_at=now.isoformat(),expected_completion_seconds=45))
        assert status()['state']=='running' and servers[0].active_run_ids
        emit(record())
        on_activity(dict(state='waiting',updated_at=now.isoformat(),next_due_at=(now+timedelta(seconds=15)).isoformat()))
        assert status()['state']=='waiting'
        on_activity(dict(state='capture_failing',updated_at=now.isoformat(),next_due_at=now.isoformat()))
        assert status()['state']=='capture_failing'  # Does not assert Twitch offline.
        return dict(type='summary',trusted=False,attempts=1,interrupted=interrupted)
    monkeypatch.setattr(module.shadow_capture,'run',run)
    assert module.main(args)==(130 if interrupted else 0)
    assert final[0]['state']=='stopped' and final[0]['completion']==('interrupted' if interrupted else 'completed')
