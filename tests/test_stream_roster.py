import importlib
import json

import pytest

from exp_tracker.diagnostics import Diagnostics
from exp_tracker.store import Store
from tests.test_multi_alpha import multi, main as capture


@pytest.fixture
def roster(multi):
    return importlib.import_module('stream_roster'), multi


def command(roster, *args):
    tool, (_, path, *_rest) = roster
    return tool.main(['--config', str(path), *args])


def test_init_add_preview_preserves_settings_and_authorization(roster, capsys):
    tool, (module, path, config, *_rest) = roster
    before = path.read_bytes()
    assert command(roster, 'add', 'Gamma', '--character', 'Main', '--dry-run') == 0
    assert path.read_bytes() == before
    assert not (path.parent / 'shared.sqlite3').exists()
    assert command(roster, 'add', 'Gamma', '--character', 'Main') == 0
    result = json.loads(path.read_text())
    assert result['streams'][:2] == config['streams']
    assert result['port'] == config['port'] and result['database'] == config['database']
    assert result['streams'][2]['enabled'] is False
    assert result['streams'][2]['authorized'] is False
    assert command(roster, 'enable', 'gamma') == 1
    assert 'explicit --authorized' in capsys.readouterr().out
    assert command(roster, 'enable', 'gamma', '--authorized') == 0
    assert len(module.load_config(path)[2]) == 3
    new = path.parent / 'new.json'
    assert tool.main(['--config', str(new), 'init', '--database', 'private/new.sqlite3']) == 0
    assert not (path.parent / 'new.sqlite3').exists()
    initial = new.read_bytes()
    assert tool.main(['--config', str(new), 'init']) == 1
    assert new.read_bytes() == initial


def test_disable_enable_remove_restart_history_and_session_preservation(roster, capsys):
    tool, fixture = roster
    module, path, _, calls, _ = fixture
    assert capture(fixture) == 0
    db = path.parent / 'shared.sqlite3'
    with Store(db, read_only=True) as store:
        sessions = {c: store.state(c)['session']['id'] for c in ('alpha', 'beta')}
        original = list(store.db.execute('SELECT id,payload_json FROM diagnostic_attempts ORDER BY id'))
        snapshot = Diagnostics(store).snapshot('alpha')
    assert command(roster, 'disable', 'alpha') == 0
    with Store(db, read_only=True) as store:
        assert [tuple(r) for r in store.db.execute('SELECT id,payload_json FROM diagnostic_attempts ORDER BY id')] == [tuple(r) for r in original]
        assert Diagnostics(store).snapshot('alpha')['observations'] == snapshot['observations']
    calls.clear()
    assert capture(fixture) == 0
    assert [c[0] for c in calls] == ['beta', 'beta']  # One active lane is safe.
    assert command(roster, 'enable', 'alpha') == 0
    calls.clear()
    assert capture(fixture) == 0
    with Store(db, read_only=True) as store:
        assert {c: store.state(c)['session']['id'] for c in sessions} == sessions
        assert len(Diagnostics(store).snapshot('alpha')['observations']) == 4
        assert len(Diagnostics(store).snapshot('beta')['observations']) == 6
        runs = list(store.db.execute('SELECT run_id,configuration_json FROM diagnostic_runs'))
        assert len({r['run_id'] for r in runs}) == 5
        assert all(json.loads(r['configuration_json'])['start_reason'] == 'process_start' for r in runs)
        assert not store.db.execute('SELECT 1 FROM observations').fetchone()
    assert command(roster, 'remove', 'alpha') == 0
    assert command(roster, 'inspect', 'alpha') == 0
    assert 'historical_only' in capsys.readouterr().out
    assert command(roster, 'add', 'alpha', '--character', 'Wrong', '--source', 'file', '--file', 'synthetic.mp4') == 1
    assert command(roster, 'add', 'alpha', '--character', 'alpha character', '--source', 'file', '--file', 'synthetic.mp4') == 0
    with Store(db, read_only=True) as store:
        assert store.state('alpha')['session']['id'] == sessions['alpha']


def test_all_disabled_keeps_history_but_no_capture(roster):
    _, fixture = roster
    _, path, _, calls, _ = fixture
    assert capture(fixture) == 0
    assert command(roster, 'disable', 'alpha') == 0
    assert command(roster, 'disable', 'beta') == 0
    calls.clear()
    assert capture(fixture) == 1 and not calls
    assert command(roster, 'list') == 0
    assert command(roster, 'remove', 'alpha') == 0
    assert command(roster, 'remove', 'beta') == 0
    assert command(roster, 'list') == 0
    with Store(path.parent / 'shared.sqlite3', read_only=True) as store:
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0] == 4


@pytest.mark.parametrize('edit', [
    lambda c: c['streams'].append(dict(c['streams'][0], channel='ALPHA')),
    lambda c: c['streams'][0].update(character=''),
    lambda c: c['streams'][0].update(enabled='false'),
    lambda c: c['streams'][0].update(enabled=False, count=-1),
    lambda c: c.update(TWITCH_CLIENT_SECRET='MUST_NOT_PRINT'),
    lambda c: c['streams'][0].update(access_token='MUST_NOT_PRINT'),
    lambda c: c['streams'][0].update(quality='Bearer MUST_NOT_PRINT'),
])
def test_invalid_existing_config_is_not_rewritten(roster, edit, capsys):
    _, (_, path, config, *_rest) = roster
    edit(config)
    path.write_text(json.dumps(config))
    original = path.read_bytes()
    assert command(roster, 'disable', 'beta') == 1
    assert path.read_bytes() == original
    assert 'MUST_NOT_PRINT' not in capsys.readouterr().out


def test_duplicates_missing_bad_names_and_malformed_json(roster):
    _, (_, path, *_rest) = roster
    original = path.read_bytes()
    for args in [('add', 'ALPHA', '--character', 'Other'), ('disable', 'absent'),
                 ('add', 'https://twitch.tv/channel', '--character', 'Main'),
                 ('add', 'gamma', '--character', 'Main', '--source', 'file')]:
        assert command(roster, *args) == 1
        assert path.read_bytes() == original
    path.write_text('{ invalid')
    assert command(roster, 'list') == 1
    assert path.read_text() == '{ invalid'


def test_atomic_write_failure_concurrent_edit_and_lock_release(roster, monkeypatch):
    tool, (_, path, *_rest) = roster
    original = path.read_bytes()
    replace = tool.os.replace
    def fail(*args):
        raise OSError('synthetic disk failure')
    monkeypatch.setattr(tool.os, 'replace', fail)
    assert command(roster, 'disable', 'alpha') == 1
    assert path.read_bytes() == original
    assert not list(path.parent.glob('*.tmp'))
    monkeypatch.setattr(tool.os, 'replace', replace)
    with tool.edit_lock(path):
        assert command(roster, 'disable', 'alpha') == 1
    assert command(roster, 'disable', 'alpha') == 0
    with pytest.raises(ValueError, match='changed during edit'):
        tool.save_config(path, {}, original)
    assert not list(path.parent.glob('*.tmp'))


def test_roster_mismatch_fails_without_changing_config_or_database(roster, capsys):
    _, fixture = roster
    _, path, config, *_rest = fixture
    assert capture(fixture) == 0
    config['streams'][0]['character'] = 'Wrong'
    path.write_text(json.dumps(config))
    original = path.read_bytes()
    assert command(roster, 'disable', 'alpha') == 1
    assert 'Character mismatch for alpha' in capsys.readouterr().out
    assert path.read_bytes() == original
    with Store(path.parent / 'shared.sqlite3', read_only=True) as store:
        assert store.state('alpha')['characters'][0]['label'] == 'alpha character'


def test_active_coordinator_config_edit_does_not_mutate_running_lanes(roster, monkeypatch):
    _, fixture = roster
    module, path, _, calls, _ = fixture
    original = module.shadow.capture_attempt
    edited = []
    def capture_and_edit(*args, **kwargs):
        if not edited:
            edited.append(command(roster, 'disable', 'beta'))
        return original(*args, **kwargs)
    monkeypatch.setattr(module.shadow, 'capture_attempt', capture_and_edit)
    assert capture(fixture) == 0
    assert edited == [0]
    assert [c[0] for c in calls] == ['alpha', 'beta', 'alpha', 'beta']
    calls.clear()
    assert capture(fixture) == 0
    assert [c[0] for c in calls] == ['alpha', 'alpha']


def test_empty_and_disabled_configs_bounded_and_fast_video_settings(roster):
    _, (module, path, config, *_rest) = roster
    config['streams'][0].update(interval=3)
    config['streams'][1].update(source='twitch', enabled=False)
    path.write_text(json.dumps(config))
    assert module.load_config(path, offline_fast_test=True)[2][0]['interval'] == 3
    with pytest.raises(ValueError): module.load_config(path)
    assert roster[0].main(['--config', str(path), '--offline-fast-test', 'disable', 'alpha']) == 0
    with pytest.raises(ValueError, match='No enabled'): module.load_config(path, offline_fast_test=True)
    config['streams'] *= 13
    with pytest.raises(ValueError, match='at most 25'): module.validate_config(config)
