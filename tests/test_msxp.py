"""msxp: settings precedence, the exact tool commands it runs, setup and its friendly refusals."""
from argparse import Namespace
import shutil
import sqlite3
import subprocess

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


def test_a_git_worktree_borrows_the_main_checkouts_environments(tmp_path):
    main, worktree = tmp_path / 'main', tmp_path / 'feature'
    (main / '.git/worktrees/feature').mkdir(parents=True); (main / '.venv').mkdir(); worktree.mkdir()
    (worktree / '.git').write_text(f'gitdir: {main / ".git/worktrees/feature"}\n', encoding='utf-8')
    assert msxp.environment_root(worktree) == main.resolve()
    (worktree / '.venv').mkdir()  # Its own environment wins.
    assert msxp.environment_root(worktree) == worktree
    assert msxp.environment_root(main) == main  # A normal checkout has a .git folder, not a file.


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
    assert build('test-data') == ([str(msxp.VENV), 'tools/restore_test_data.py', '--download'], None)
    assert build('test-data', check=True)[0][-1] == '--check'
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
    for name in ('install', 'doctor', 'demo', 'setup', 'admin', 'tracker', 'api', 'health', 'cleanup', 'test', 'sql', '.env'):
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
    # Only the journal needs the login itself; everything else runs as the database's owner.
    assert msxp.remote(['logs', 'api'], s) == (['ssh', '-t', 'root@203.0.113.7', 'cd /opt/msxp/app && ./msxp logs api'], None)
    assert msxp.remote([], s)[0][-1] == 'cd /opt/msxp/app && sudo -u msxp ./msxp doctor'
    assert msxp.remote(['cleanup', '--apply'], s)[0][-1] == 'cd /opt/msxp/app && sudo -u msxp ./msxp cleanup --apply'
    assert msxp.remote(['health', '--minutes', '10; rm -rf /'], s)[0][-1].endswith("./msxp health --minutes '10; rm -rf /'")
    assert msxp.remote(['dashboard'], s) == (['ssh', '-t', '-L', '8767:127.0.0.1:8767', 'root@203.0.113.7',
        'cd /opt/msxp/app && sudo -u msxp ./msxp dashboard --no-browser'], 'http://127.0.0.1:8767/dev/streams')


def test_dashboard_is_the_read_only_server_with_operator_pages():
    command, url = build('dashboard')
    assert command[1:] == ['-m', 'exp_tracker.server', '--db', str(msxp.ROOT / 'private/msxp/tracker.sqlite3'),
                           '--port', '8767', '--diagnostic-dashboard'] and url == 'http://127.0.0.1:8767/dev/streams'
    assert '--public-only' not in command and build('api')[0][-1] == '--public-only'


def test_server_without_a_configured_login_explains_what_to_set(monkeypatch, capsys):
    monkeypatch.setattr(msxp, 'settings', lambda: msxp.SETTINGS | {'twitch': False})
    monkeypatch.setattr(msxp, 'run', lambda *a, **k: pytest.fail('must not run'))
    assert msxp.main(['server', 'admin']) == 1 and 'MSXP_SERVER=' in capsys.readouterr().out


def test_split_settings_precede_roster_but_not_explicit_settings(tmp_path):
    split, roster = tmp_path / 'split.env', tmp_path / 'roster.env'
    split.write_text('MSXP_DATABASE=production.sqlite3\n')
    roster.write_text('MSXP_DATABASE=older.sqlite3\n')
    local = tmp_path / '.env'
    assert msxp.settings(local, {}, (split, roster))['MSXP_DATABASE'] == 'production.sqlite3'
    local.write_text('MSXP_DATABASE=local.sqlite3\n')
    assert msxp.settings(local, {}, (split, roster))['MSXP_DATABASE'] == 'local.sqlite3'
    assert msxp.settings(local, {'MSXP_DATABASE': 'explicit.sqlite3'}, (split, roster))['MSXP_DATABASE'] == 'explicit.sqlite3'
    assert [p.name for p in msxp.SERVER_ENV] == ['split.env', 'roster.env', 'msxp.env']


@pytest.mark.parametrize('options,lines,follow,pager', [
    ([], '50', True, False),
    (['--no-follow', '--lines', '500'], '500', False, False),
    (['--browse'], 'all', False, True),
    (['--since', '14 hours ago', '--until', '10 hours ago'], 'all', False, False),
    (['--since', 'yesterday', '--follow', '--lines', '100'], '100', True, False),
    (['--lines', 'all', '--no-follow'], 'all', False, False),
])
def test_log_modes(monkeypatch, options, lines, follow, pager):
    commands = []
    monkeypatch.setattr(msxp, 'services', lambda: ['msxp-tracker'])
    monkeypatch.setattr(msxp.shutil, 'which', lambda name: name)
    monkeypatch.setattr(msxp, 'run', lambda command, **kwargs: commands.append(command) or 0)
    assert msxp.main(['logs', 'tracker', *options]) == 0
    command = commands[0]
    assert command[command.index('-n') + 1] == lines
    assert ('-f' in command) == follow
    assert ('--no-pager' not in command) == pager
    assert command[command.index('-u') + 1] == 'msxp-tracker'
    if '--since' in options:assert '--since=' + options[options.index('--since') + 1] in command
    if '--until' in options:assert '--until=' + options[options.index('--until') + 1] in command


@pytest.mark.parametrize('flag', ['--search', '--grep'])
def test_log_search_treats_punctuation_as_literal_text(monkeypatch, flag):
    commands = []
    monkeypatch.setattr(msxp, 'services', lambda: ['msxp-tracker'])
    monkeypatch.setattr(msxp.shutil, 'which', lambda name: name)
    monkeypatch.setattr(msxp, 'run', lambda command, **kwargs: commands.append(command) or 0)
    assert msxp.main(['logs', 'tracker', flag, 'Some.Name[1]', '--browse']) == 0
    assert '--grep=Some\\.Name\\[1\\]' in commands[0] and '--case-sensitive=no' in commands[0]


@pytest.mark.parametrize('options', [['--lines', '-1'], ['--lines', 'oops'], ['--browse', '--follow']])
def test_log_options_reject_invalid_values(options):
    with pytest.raises(SystemExit):msxp.main(['logs', 'tracker', *options])


def test_local_logs_preserve_tail_and_refuse_unavailable_filters(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(msxp, 'services', lambda: [])
    monkeypatch.setattr(msxp, 'ROOT', tmp_path)
    log = tmp_path / 'private/multi-alpha/runs/example/operator.jsonl'
    log.parent.mkdir(parents=True)
    log.write_text('first\nsecond\nthird\n', encoding='utf-8')
    assert msxp.main(['logs', '--lines', '1']) == 0
    assert capsys.readouterr().out.endswith('\nthird\n')
    assert msxp.main(['logs', '--lines', '0']) == 0
    assert 'third' not in capsys.readouterr().out
    assert msxp.main(['logs', '--lines', 'all']) == 0
    assert capsys.readouterr().out.endswith('first\nsecond\nthird\n')
    for options in (['--search', 'first'], ['--since', 'yesterday'], ['--until', 'now'], ['--browse']):
        assert msxp.main(['logs', *options]) == 1
        assert 'need the server journal' in capsys.readouterr().out


def test_remote_sql_and_log_filters_preserve_arguments():
    import shlex
    s = msxp.SETTINGS | {'MSXP_SERVER': 'root@203.0.113.7'}
    for args in (['sql'], ['sql', "SELECT 'a; $(whoami)';", '--db', '/a path/file.sqlite3'],
                 ['logs', 'tracker', '--since', '14 hours ago', '--until', '10 hours ago', '--search', 'some.text', '--browse']):
        command, url = msxp.remote(args, s)
        assert command[:2] == ['ssh', '-t'] and url is None
        expected = (['sudo', '-u', 'msxp'] if args[0] == 'sql' else []) + ['./msxp', *args]
        assert shlex.split(command[-1].split(' && ', 1)[1]) == expected


def test_sql_missing_database_or_shell_never_runs(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(msxp, 'run', lambda *a, **k: pytest.fail('must not run'))
    missing = tmp_path / 'missing.sqlite3'
    assert msxp.main(['sql', '--db', str(missing)]) == 1
    assert 'No tracker database' in capsys.readouterr().out and not missing.exists()
    db = tmp_path / 'existing.sqlite3'
    with sqlite3.connect(db):pass
    monkeypatch.setattr(msxp.shutil, 'which', lambda name: None)
    assert msxp.main(['sql', '--db', str(db)]) == 1
    assert 'SQLite shell is missing' in capsys.readouterr().out


def test_sql_reads_live_wal_and_blocks_writes_and_file_commands(monkeypatch, tmp_path, capsys):
    if not shutil.which('sqlite3'):pytest.skip('SQLite CLI is not installed')
    db = tmp_path / 'a space # unicode-é.sqlite3'
    outputs = []
    def execute(command, **kwargs):
        result = subprocess.run(command, input='', capture_output=True, text=True)
        outputs.append(result)
        return result.returncode
    monkeypatch.setattr(msxp, 'run', execute)
    monkeypatch.setattr(msxp, 'settings', lambda: msxp.SETTINGS | {'MSXP_DATABASE': str(db)})
    with sqlite3.connect(db) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('CREATE TABLE example (value TEXT)')
        writer.execute("INSERT INTO example VALUES ('original')")
        writer.commit()
        assert msxp.main(['sql', 'SELECT * FROM example;']) == 0
        assert 'original' in outputs[-1].stdout
        assert str(db) in capsys.readouterr().out
        assert msxp.main(['sql', '--', '-- SQL comment\nSELECT * FROM example;']) == 0
        assert 'original' in outputs[-1].stdout
        for query in ("UPDATE example SET value='changed';", 'DELETE FROM example;', 'DROP TABLE example;',
                      "ATTACH 'forbidden.sqlite3' AS other;", '.open forbidden.sqlite3', '.shell echo forbidden'):
            assert msxp.main(['sql', query]) != 0, query
            assert outputs[-1].stderr
            assert writer.execute('SELECT * FROM example').fetchall() == [('original',)]
        assert msxp.main(['sql', '--db', str(db)]) == 0
