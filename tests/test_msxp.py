"""msxp: settings precedence, the exact tool commands it runs, setup and its friendly refusals."""
from argparse import Namespace

import pytest

from exp_tracker import msxp, streamer_roster
from exp_tracker.store import Store


def test_settings_come_from_environment_then_env_file_then_defaults(tmp_path):
    env = tmp_path / '.env'
    env.write_text('# comment\nMSXP_PORT=9000   # trailing note\nexport MSXP_WORKERS="3"\n'
                   'MSXP_DATABASE=C:/My Folder/tracker.sqlite3\nTWITCH_CLIENT_ID=your_client_id\nTWITCH_CLIENT_SECRET=s\n', encoding='utf-8')
    s = msxp.settings(env, {'MSXP_PORT': '9100'}, ())
    assert (s['MSXP_PORT'], s['MSXP_WORKERS'], s['MSXP_ADMIN_PORT']) == ('9100', '3', '8766')
    assert s['MSXP_DATABASE'] == 'C:/My Folder/tracker.sqlite3'  # Paths may contain spaces.
    assert s['twitch'] is False  # The .env.example placeholder is not a key.
    assert msxp.settings(env, {'TWITCH_CLIENT_ID': 'real'}, ())['twitch'] is True
    assert msxp.settings(tmp_path / 'missing', {}, ())['MSXP_DATABASE'] == 'private/msxp/tracker.sqlite3'


def build(name, s=None, **args):
    return msxp.build(name, Namespace(**dict(db=None, port=None, workers=None, no_browser=False) | args), s or msxp.settings('missing', {}, ()))


def test_each_command_runs_the_documented_tool():
    db = str(msxp.ROOT / 'private/msxp/tracker.sqlite3')
    command, url = build('tracker')
    assert command[1:] == ['tools/multi_alpha.py', '--db-roster', db, '--port', '8765', '--continuous', '--workers', '2', '--ocr-python', str(msxp.OCR)]
    assert url == 'http://127.0.0.1:8765/'
    assert build('admin')[0][1:] == ['-m', 'exp_tracker.admin_server', '--db', db, '--port', '8766']
    assert build('demo')[0][1:] == ['tools/preview_pages.py', '--demo', '--live', '--port', '8890']
    assert build('api', port=9000, no_browser=True) == ([str(msxp.VENV), '-m', 'exp_tracker.server', '--db', db, '--port', '9000', '--public-only'], None)
    assert build('cleanup', apply=False)[0][-2:] == ['--db', db]
    assert build('cleanup', apply=True)[0][-3:] == ['--apply', '--log-root', 'private/multi-alpha/runs']
    twitch = dict(msxp.settings('missing', {'TWITCH_CLIENT_ID': 'a', 'TWITCH_CLIENT_SECRET': 'b'}, ()))
    assert build('tracker', twitch)[0][-1] == '--twitch-status' and build('api', twitch)[0][-1] == '--twitch-status'


def test_unknown_options_pass_through_and_workers_override():
    command, url = msxp.build('tracker', Namespace(db='other.sqlite3', port=None, workers=4, no_browser=True), msxp.settings('missing', {}, ()), ['--check'])
    assert command[command.index('--workers') + 1] == '4' and command[-1] == '--check' and url is None
    assert command[command.index('--db-roster') + 1] == str(msxp.ROOT / 'other.sqlite3')


def test_setup_creates_an_empty_ready_roster_and_never_overwrites(tmp_path, capsys):
    db = tmp_path / 'mine' / 'tracker.sqlite3'
    assert msxp.setup(Namespace(db=str(db)), {}) == 0
    with Store(db, read_only=True) as store:assert streamer_roster.ready(store) and streamer_roster.entries(store) == []
    assert 'msxp admin' in capsys.readouterr().out
    assert msxp.setup(Namespace(db=str(db)), {}) == 1 and 'already exists' in capsys.readouterr().out
    with Store(db) as store:  # The admin portal's add-streamer path works on it.
        plan = streamer_roster.preview(store, dict(action='roster_add', channel='Example_Streamer', reason='first streamer'))
        assert streamer_roster.commit(store, plan)['configuration']['automatic_characters'] is True


def test_friendly_refusals_never_start_a_tool(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(msxp, 'run', lambda *a, **k: pytest.fail('must not run'))
    monkeypatch.setattr(msxp, 'VENV', tmp_path / 'python')
    assert msxp.main(['tracker']) == 1 and 'msxp install' in capsys.readouterr().out
    monkeypatch.setattr(msxp, 'VENV', tmp_path / 'python'); (tmp_path / 'python').write_text('')
    assert msxp.main(['admin', '--db', str(tmp_path / 'none.sqlite3')]) == 1 and 'msxp setup' in capsys.readouterr().out
    with pytest.raises(SystemExit):msxp.main(['doctor', '--bogus'])


def test_doctor_fails_only_for_missing_requirements(monkeypatch, capsys):
    monkeypatch.setattr(msxp, 'in_use', lambda port: False)
    found = [('Tesseract OCR', True, 'x', 'need'), ('Tracker database', False, 'msxp setup', 'next'), ('Twitch keys', False, 'see .env', 'optional')]
    monkeypatch.setattr(msxp, 'checks', lambda s: iter(found))
    assert msxp.doctor({'MSXP_PORT': 1, 'MSXP_ADMIN_PORT': 2}) == 0  # A fresh install only lacks its next step.
    out = capsys.readouterr().out
    assert '[..] Tracker database\n        next: msxp setup' in out and 'Start your own tracker with: msxp setup' in out
    found[0] = ('Tesseract OCR', False, 'winget install ...', 'need')
    assert msxp.doctor({'MSXP_PORT': 1, 'MSXP_ADMIN_PORT': 2}) == 1 and 'fix: winget install' in capsys.readouterr().out


def test_help_lists_every_command(capsys):
    assert msxp.main([]) == 0
    text = capsys.readouterr().out
    for name in ('install', 'doctor', 'demo', 'setup', 'admin', 'tracker', 'api', 'health', 'cleanup', 'test', '.env'):
        assert f'msxp {name}' in text or name in text


def test_server_settings_files_fill_in_after_the_project_env(tmp_path):
    roster, secrets = tmp_path / 'roster.env', tmp_path / 'msxp.env'
    roster.write_text('MSXP_DATABASE=/opt/msxp/app/private/production/tracker.sqlite3\n', encoding='utf-8')
    secrets.write_text('TWITCH_CLIENT_ID=id\nTWITCH_CLIENT_SECRET=secret\n', encoding='utf-8')
    s = msxp.settings(tmp_path / 'missing', {}, (roster, secrets, tmp_path / 'unreadable.env'))
    assert s['MSXP_DATABASE'] == '/opt/msxp/app/private/production/tracker.sqlite3' and s['twitch'] is True
    local = tmp_path / '.env';local.write_text('MSXP_DATABASE=mine.sqlite3\n', encoding='utf-8')
    assert msxp.settings(local, {}, (roster,))['MSXP_DATABASE'] == 'mine.sqlite3'  # The project's .env wins.


def test_server_commands_run_over_ssh_with_a_tunnel_and_the_service_user():
    s = dict(msxp.settings('missing', {}, ()), MSXP_SERVER='root@203.0.113.7')
    ssh, url = msxp.remote(['admin'], s)
    assert ssh == ['ssh', '-t', '-L', '8766:127.0.0.1:8766', 'root@203.0.113.7',
                   'cd /opt/msxp/app && sudo -u msxp ./msxp admin --no-browser'] and url == 'http://127.0.0.1:8766/'
    assert msxp.remote(['logs', 'api'], s) == (['ssh', '-t', 'root@203.0.113.7', 'cd /opt/msxp/app && ./msxp logs api'], None)
    assert msxp.remote([], s)[0][-1] == 'cd /opt/msxp/app && ./msxp doctor'
    assert msxp.remote(['cleanup', '--apply'], s)[0][-1] == 'cd /opt/msxp/app && sudo -u msxp ./msxp cleanup --apply'
    assert msxp.remote(['health', '--minutes', '10; rm -rf /'], s)[0][-1].endswith("./msxp health --minutes '10; rm -rf /'")


def test_server_without_a_configured_login_explains_what_to_set(monkeypatch, capsys):
    monkeypatch.setattr(msxp, 'settings', lambda: msxp.SETTINGS | {'twitch': False})
    monkeypatch.setattr(msxp, 'run', lambda *a, **k: pytest.fail('must not run'))
    assert msxp.main(['server', 'admin']) == 1 and 'MSXP_SERVER=' in capsys.readouterr().out
