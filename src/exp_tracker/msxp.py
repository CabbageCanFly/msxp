"""msxp: one command for the MapleStory Classic EXP tracker. Start with `msxp help`.

Thin wrappers around the project's own tools. Each prints the full command it runs, and any
option msxp does not know passes through to that tool (e.g. `msxp tracker --check`).
Standard library only, so `msxp install` and `msxp doctor` work before anything is installed.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import tempfile
import time
import webbrowser

ROOT = Path(__file__).resolve().parents[2]
WINDOWS = os.name == 'nt'
BIN = 'Scripts/python.exe' if WINDOWS else 'bin/python'


def environment_root(root):
    """A linked git worktree has no .venv of its own (it isn't in Git), so it borrows the main checkout's.

    Tools still run this checkout's code: run() puts its src first on PYTHONPATH."""
    git = root / '.git'
    if (root / '.venv').exists() or not git.is_file():return root
    gitdir = git.read_text(encoding='utf-8').partition('gitdir:')[2].strip()  # <main>/.git/worktrees/<name>
    main = (root / gitdir).resolve().parents[2] if gitdir else root
    return main if (main / '.venv').exists() else root


ENVIRONMENTS = environment_root(ROOT)
VENV = ENVIRONMENTS / '.venv' / BIN
OCR = ENVIRONMENTS / 'private/rapidocr/.venv' / BIN
OCR_PACKAGES = ['rapidocr==3.10.0', 'onnxruntime==1.31.0', 'psutil==7.2.2', 'Pillow==12.3.0']  # As deploy/install-ubuntu.sh.
SETTINGS = {'MSXP_DATABASE': 'private/msxp/tracker.sqlite3', 'MSXP_PORT': '8765', 'MSXP_ADMIN_PORT': '8766',
            'MSXP_DEMO_PORT': '8890', 'MSXP_DASHBOARD_PORT': '8767', 'MSXP_WORKERS': '2',
            'MSXP_SERVER': '', 'MSXP_SERVER_DIR': '/opt/msxp/app', 'MSXP_SERVER_USER': 'msxp',
            'MSXP_PRELOAD_STREAMLINK': 'auto', 'MSXP_ALERT_WEBHOOK': '', 'MSXP_ALERT_MINUTES': '30',
            'MSXP_ALERT_STREAM_MINUTES': '', 'MSXP_FRONTEND_ORIGIN': ''}
TWITCH_KEYS = ('TWITCH_CLIENT_ID', 'TWITCH_CLIENT_SECRET')
ALERT_ENV = Path('/etc/msxp/alert.env')
SERVER_ENV = (Path('/etc/msxp/split.env'), Path('/etc/msxp/roster.env'), Path('/etc/msxp/msxp.env'), ALERT_ENV)
UNITS = {'tracker': 'msxp-tracker', 'api': 'msxp-api', 'cleanup': 'msxp-retention', 'alert': 'msxp-alert'}
PORTS = {'admin': 'MSXP_ADMIN_PORT', 'demo': 'MSXP_DEMO_PORT', 'dashboard': 'MSXP_DASHBOARD_PORT', 'api': 'MSXP_PORT', 'tracker': 'MSXP_PORT'}
PAGES = {'dashboard': 'dev/streams'}  # The page each command opens; default the homepage.
INSTALL = {  # Windows, macOS, Linux (Debian/Ubuntu)
    'Tesseract': ('winget install --id UB-Mannheim.TesseractOCR -e', 'brew install tesseract', 'sudo apt install tesseract-ocr'),
    'FFmpeg': ('winget install --id Gyan.FFmpeg -e', 'brew install ffmpeg', 'sudo apt install ffmpeg'),
}

HELP = """\
msxp: MapleStory Classic EXP tracker

  First time     msxp install     Python packages + OCR engine, then checks everything
                 msxp doctor      what is installed, missing or misconfigured (alias: diag)
  Just look      msxp demo        the website with fictional players; nothing to set up
  Your tracker   msxp setup       create your tracker database (once)
                 msxp admin       add streamers, start/pause tracking
                 msxp streamer add LOGIN      add with admin defaults and tracking enabled
                 msxp streamer disable LOGIN  pause tracking, preserve history
                 msxp streamer hide LOGIN     hide publicly, keep tracking setting
                 msxp streamer merge OLD --into NEW  preview a Twitch username change (see --help)
                 msxp tracker     capture the streams + your local website (normal decoding for faster first pictures)
  More           msxp api         website only, for an existing database
                 msxp dashboard   operator view: every capture's details per streamer (read-only)
                 msxp health      missed captures in the last hour, and why
                 msxp cleanup     keep only the last 24 h of raw readings (add --apply)
                 msxp alert       Discord message when a live stream is stuck (see Alerts below)
                 msxp test        run the test suite
                 msxp test-data   download only the private files needed by tests
                 msxp where       where your settings, database, logs and backups are
                 msxp logs        follow the log (on a server: tracker, api, cleanup or alert)
                 msxp sql         open your database in a read-only SQLite shell
  On a server    msxp server ...  run any command on your server over SSH, e.g. msxp server admin

Settings and secrets live in .env (msxp install copies .env.example; never commit .env):
  MSXP_DATABASE   your tracker database   (default private/msxp/tracker.sqlite3)
  MSXP_PORT / MSXP_ADMIN_PORT / MSXP_DASHBOARD_PORT / MSXP_DEMO_PORT   8765 / 8766 / 8767 / 8890
  MSXP_WORKERS    streams captured at once (default 2)
  MSXP_PRELOAD_STREAMLINK  auto (default): preload on Linux; 0 disables, 1 explicitly enables
  MSXP_SERVER     your server's SSH login for msxp server, e.g. root@203.0.113.7
  TWITCH_CLIENT_ID + TWITCH_CLIENT_SECRET   optional, shows who is live (docs/twitch-authentication.md)
  MSXP_ALERT_WEBHOOK / MSXP_ALERT_MINUTES   Discord webhook URL for alerts / minutes before stuck (30)
  MSXP_ALERT_STREAM_MINUTES   per-streamer increases, e.g. Streamer_A=90,Streamer_B=120
On a server, /etc/msxp/split.env, roster.env, msxp.env and alert.env are read too, in that order.

Alerts           msxp alert            check once now (--dry-run shows, sends nothing)
                 msxp server alert streamer Streamer_A min 90       set a longer wait
                 msxp server alert streamer Streamer_A min default  restore the default
                 msxp server alert streamer Streamer_A              show its wait
                 msxp alert test       send a test message to the webhook
                 msxp alert --watch    keep checking every 5 minutes (on a PC)
  On a server    msxp server alert on       install and start the 5-minute timer; asks for the webhook
                 msxp server alert status   timer, settings and open alerts
                 msxp server alert off      stop the timer, keep settings (remove: delete it all)

Browse logs      msxp logs tracker --browse
                 msxp logs tracker --since "14 hours ago" --until "10 hours ago" --search "Streamer_A" --browse
  --lines N      latest N entries (default 50; all for --browse or time filters)
  --lines all    all retained matching entries
  --no-follow    show entries and exit; default follows new entries
  --since/--until show history and exit unless --follow is requested
  --search TEXT  case-insensitive literal text; --browse opens the scroll/search viewer
  Viewer keys    /text + Enter to search, n next, g top, G bottom, q quit
  Remote         msxp server logs tracker --browse    msxp server sql
                 msxp server streamer add Streamer_A
  Streamer add   enables tracking; no browser or service restart needed
  SQL keys       .tables    .schema TABLE    SELECT ...;    .quit

Every command prints the tool it runs; unknown options pass through (msxp tracker --check).
Stop a running command with Ctrl+C. More: README.md, docs/README.md
"""


def read_env(env_file):
    found = {}
    try:lines = Path(env_file).read_text(encoding='utf-8-sig').splitlines()
    except OSError:return found  # Missing, or a server file this user may not read.
    for line in lines:
        key, sep, value = line.strip().removeprefix('export ').partition('=')
        if sep and key and not key.startswith('#'):
            found[key.strip()] = value.split(' #')[0].strip().strip('"\'')
    return found


def settings(env_file=None, environ=None, server_files=SERVER_ENV):
    """MSXP_* settings: environment, then .env, then a server's /etc/msxp files, then defaults.
    Twitch keys are only checked for presence."""
    environ = os.environ if environ is None else environ
    layers = [read_env(Path(env_file) if env_file else ROOT / '.env'), *map(read_env, server_files)]
    get = lambda key: environ.get(key) or next((layer[key] for layer in layers if layer.get(key)), '')
    value = {key: get(key) or default for key, default in SETTINGS.items()}
    value['twitch'] = all(get(key) and not get(key).startswith('your_') for key in TWITCH_KEYS)  # .env.example placeholders
    return value


def path(value):
    return Path(value) if Path(value).is_absolute() else ROOT / value


def tesseract():
    """The same lookup as recognition.configure_tesseract, without importing OCR packages."""
    candidate = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Tesseract-OCR/tesseract.exe'
    return os.environ.get('TESSERACT_CMD') or shutil.which('tesseract') or (str(candidate) if WINDOWS and candidate.is_file() else None)


BLANK_PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAHgAAAAQCAAAAAD4qOQ5AAAAF0lEQVR42mNgGAWjYBSMglEwCkbBQAMAB5AAAa8T4zAAAAAASUVORK5CYII=')


def ocr_works():
    """Runs the live tracker's RapidOCR worker once: a damaged environment can still have its python.exe."""
    if not OCR.is_file():return False
    try:
        output = subprocess.run([str(OCR), str(ROOT / 'tools/shadow_rapidocr.py')], input=BLANK_PNG, capture_output=True, timeout=120)
        return output.returncode == 0 and 'text' in json.loads(output.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):return False


def hint(tool):
    return INSTALL[tool][0 if WINDOWS else 1 if sys.platform == 'darwin' else 2]


def in_use(port):
    with socket.socket() as probe:
        probe.settimeout(.3)
        return probe.connect_ex(('127.0.0.1', int(port))) == 0


def build(name, args, s, extra=()):
    """(command, url to open) for a wrapper subcommand, without running it."""
    py, db = str(VENV), str(path(args.db or s['MSXP_DATABASE'])) if hasattr(args, 'db') else None
    twitch = ['--twitch-status'] if s['twitch'] else []
    port = str(getattr(args, 'port', None) or s[PORTS.get(name, 'MSXP_PORT')])
    url = f'http://127.0.0.1:{port}/{PAGES.get(name, "")}'
    command, opens = {
        'demo': ([py, 'tools/preview_pages.py', '--demo', '--live', '--port', port], True),
        'admin': ([py, '-m', 'exp_tracker.admin_server', '--db', db, '--port', port], True),
        'tracker': ([py, 'tools/multi_alpha.py', '--db-roster', db, '--port', port, '--continuous',
                     '--workers', str(getattr(args, 'workers', None) or s['MSXP_WORKERS']), '--ocr-python', str(OCR),
                     *({'1':['--preload-streamlink'],'0':['--no-preload-streamlink']}.get(s['MSXP_PRELOAD_STREAMLINK'],[])), *twitch], True),
        'api': ([py, '-m', 'exp_tracker.server', '--db', db, '--port', port, '--public-only', *twitch], True),
        # The same read-only server with the operator pages instead of --public-only; local connections only.
        'dashboard': ([py, '-m', 'exp_tracker.server', '--db', db, '--port', port, '--diagnostic-dashboard', *twitch], True),
        'health': ([py, 'tools/tracker_health.py', '--db', db, '--minutes', str(getattr(args, 'minutes', 60))], False),
        'cleanup': ([py, '-m', 'exp_tracker.retention', '--db', db,
                     *(['--apply', '--log-root', 'private/multi-alpha/runs'] if getattr(args, 'apply', False) else [])], False),
        'test': ([py, '-m', 'pytest'], False),
        'alert': ([py, '-m', 'exp_tracker.alerts', *(['--test'] if getattr(args, 'action', '') == 'test' else ['--db', db])], False),
        'test-data': ([py, 'tools/restore_test_data.py', '--download', *(['--check'] if getattr(args, 'check', False) else [])], False),
    }[name]
    return [*command, *extra], url if opens and not args.no_browser else None


def open_when_ready(url, seconds=90):
    """Opens the browser once the server answers HTTP (an SSH tunnel listens before it does); gives up quietly."""
    from urllib.error import HTTPError
    from urllib.request import urlopen
    def wait():
        for _ in range(int(seconds / .5)):
            try:
                with urlopen(url, timeout=1):pass
            except HTTPError:pass  # Any HTTP answer means the page is being served.
            except OSError:time.sleep(.5);continue
            webbrowser.open(url);return
    threading.Thread(target=wait, daemon=True).start()


def run(command, url=None, tool=True):
    """tool=False for pip: this checkout's src on PYTHONPATH makes pip report false dependency conflicts."""
    shown = ' '.join(str(Path(c).relative_to(ROOT)) if Path(c).is_absolute() and Path(c).is_relative_to(ROOT) else str(c) for c in command)
    print(f'> {shown}', flush=True)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [str(ROOT / 'src'), os.environ.get('PYTHONPATH')]))) if tool else None
    process = subprocess.Popen([str(c) for c in command], cwd=ROOT, env=env)
    if url:open_when_ready(url)
    try:return process.wait()
    except KeyboardInterrupt:  # The tool received Ctrl+C too and shuts down on its own.
        try:return process.wait(timeout=30)
        except KeyboardInterrupt:process.kill();return 130


def checks(s):
    """(what, ok, how to fix, kind): a missing 'need' is a problem, 'next' is the next step, 'optional' is optional."""
    db = path(s['MSXP_DATABASE'])
    yield 'Python 3.11 or newer', sys.version_info >= (3, 11), 'install Python 3.11+ from https://www.python.org/downloads/', 'need'
    yield 'Project environment (.venv)', VENV.is_file(), 'msxp install', 'need'
    yield 'OCR environment (RapidOCR worker runs)', ocr_works(), 'msxp install   (repairs a damaged environment too)', 'need'
    yield 'Tesseract OCR', bool(tesseract()), hint('Tesseract') + '   (or set TESSERACT_CMD)', 'need'
    yield 'FFmpeg', bool(shutil.which('ffmpeg')), hint('FFmpeg') + '   (then open a new terminal)', 'need'
    yield f'Tracker database: {db}', db.is_file(), 'msxp setup   (or point MSXP_DATABASE in .env at yours)', 'next'
    yield 'Twitch keys in .env: shows who is live', s['twitch'], 'optional, see .env', 'optional'


def doctor(s):
    problems = 0; steps = []; label = {'need': ('!!', 'fix'), 'next': ('..', 'next'), 'optional': ('--', 'tip')}
    for what, ok, fix, kind in checks(s):
        problems += not ok and kind == 'need'
        if not ok and kind == 'next':steps.append(fix.split('   ')[0])
        mark, word = ('ok', '') if ok else label[kind]
        print(f'  [{mark}] {what}' + ('' if ok else f'\n        {word}: {fix}'))
    if not problems and steps:print('Ready. Look around with: msxp demo   Start your own tracker with: ' + ', then '.join(steps))
    for name in ('MSXP_PORT', 'MSXP_ADMIN_PORT'):
        if in_use(s[name]):print(f'  [..] port {s[name]} ({name}) is in use: already running, or choose another in .env')
    print('All set.' if not problems else f'{problems} thing(s) to fix above.')
    return 1 if problems else 0


def install(args, s):
    if sys.version_info < (3, 11):
        print('Python 3.11 or newer is required: https://www.python.org/downloads/');return 1
    steps = []
    if not VENV.is_file():steps.append([sys.executable, '-m', 'venv', VENV.parents[1]])
    # ensurepip first: a damaged environment can lose pip itself; reinstalling then restores missing dependencies.
    pip, ensure = ['-m', 'pip', 'install', '--disable-pip-version-check'], ['-m', 'ensurepip', '--upgrade']
    steps += [[VENV, *ensure], [VENV, *pip, '--upgrade', 'pip'], [VENV, *pip, '-e', '.[capture,dev]']]
    if not args.no_ocr:
        if not OCR.is_file():steps.append([sys.executable, '-m', 'venv', OCR.parents[1]])
        steps += [[OCR, *ensure], [OCR, *pip, '--only-binary=:all:', *OCR_PACKAGES]]
    for step in steps:
        if run(step, tool=False):print('Install stopped; see the error above.');return 1
    if not (ROOT / '.env').exists():
        shutil.copyfile(ROOT / '.env.example', ROOT / '.env');print('Created .env from .env.example (your settings and secrets).')
    print('\nChecking your setup:');return doctor(settings())


def setup(args, s):
    db = path(args.db or s['MSXP_DATABASE'])
    from exp_tracker.streamer_roster import create
    try:create(db)
    except ValueError as error:print(f'Not created: {error}');return 1
    print(f'Created your tracker database: {db}\n\nNext:\n  1. msxp admin     add a streamer and enable tracking'
          '\n  2. msxp tracker   start capturing (keep it running)')
    if args.db:print(f'\nTo use it by default, add to .env:  MSXP_DATABASE={args.db}')
    return 0


def services():
    """This machine's installed msxp systemd units (a server set up by deploy/install-ubuntu.sh)."""
    return [unit for unit in UNITS.values() if Path(f'/etc/systemd/system/{unit}.service').exists()]


def where(s):
    rows = [('Project folder', ROOT), ('Your settings and secrets', ROOT / '.env'),
            *(('Server settings', p) for p in SERVER_ENV if p.exists()), ('Tracker database', path(s['MSXP_DATABASE'])),
            ('Capture logs', ROOT / 'private/multi-alpha/runs'), ('Backups', ROOT / 'private/backups'),
            ('Manual backups', ROOT / 'private/manual-backups'), ('Python environment', VENV.parents[1]),
            ('OCR environment', OCR.parents[1])]
    for what, location in rows:
        print(f'  {what:<26} {location}' + ('' if location.exists() else '   (not created yet)'))
    if services():print(f'  {"Services (systemd)":<26} {", ".join(services())}   logs: msxp logs')
    return 0


def logs(args):
    """A server's journal for the chosen services; locally, the newest capture log."""
    if services() and shutil.which('journalctl'):
        units = [UNITS[n] for n in args.which or UNITS]
        sudo = ['sudo'] if hasattr(os, 'geteuid') and os.geteuid() != 0 else []  # Service logs need root or the journal group.
        history = bool(args.browse or args.since or args.until)
        follow = args.follow if args.follow is not None else not history
        count = args.lines if args.lines is not None else ('all' if history else 50)
        command = [*sudo, 'journalctl', *(x for unit in units for x in ('-u', unit)),
                   '-o', 'short-iso', '--full', '-n', str(count)]
        for name in ('since', 'until'):
            if getattr(args, name):command.append(f'--{name}={getattr(args, name)}')
        if args.search is not None:command += ['--grep=' + re.escape(args.search), '--case-sensitive=no']
        if follow:command.append('-f')
        if not args.browse:command.append('--no-pager')
        return run(command, tool=False)
    if args.since or args.until or args.search is not None or args.browse:
        print('Time filters, text search and browsing need the server journal. Use: msxp server logs tracker ...')
        return 1
    newest = max((ROOT / 'private/multi-alpha/runs').glob('*/operator*.jsonl'), key=lambda p: p.stat().st_mtime, default=None)
    if not newest:print('No capture logs yet. A running msxp tracker prints its log in its own window.');return 0
    print(f'Newest capture log: {newest}\n(msxp tracker also prints a readable log in its own window)\n')
    lines = newest.read_text(encoding='utf-8', errors='replace').splitlines(keepends=True)
    count = args.lines if args.lines is not None else 50
    if count != 'all':lines = lines[-count:] if count else []
    print(''.join(lines), end='')
    return 0


def log_lines(value):
    if value == 'all':return value
    try:
        count = int(value)
        if count >= 0:return count
    except ValueError:pass
    raise argparse.ArgumentTypeError('use a nonnegative number of lines, or all')


def sql(args, s):
    db = path(args.db or s['MSXP_DATABASE']).resolve()
    if not db.is_file():
        print(f'No tracker database at {db}. Check msxp where or supply --db PATH.');return 1
    executable = shutil.which('sqlite3')
    if not executable:
        print('SQLite shell is missing. Install it: sudo apt install sqlite3 (Ubuntu), brew install sqlite (macOS), '
              'or winget install --id SQLite.SQLite -e (Windows).');return 1
    print(f'Read-only database: {db}\n.tables lists tables; .schema TABLE shows columns; end SQL with ; and exit with .quit.', flush=True)
    return run([executable, '-init', os.devnull, '-safe', '-readonly', '-header', '-column',
                '-cmd', '.timeout 5000', '--', str(db), *([args.query] if args.query is not None else [])], tool=False)


def streamer(args, s):
    """Use the admin portal's validated, audited roster edits without starting an HTTP server."""
    import sqlite3
    from . import streamer_roster as roster
    from .store import Store
    db = path(args.db or s['MSXP_DATABASE']).resolve()
    if not db.is_file():
        print(f'No tracker database at {db}. Check msxp where or supply --db PATH.');return 1
    if args.action=='merge':
        from . import streamer_merge
        import json
        try:
            if not args.into:raise ValueError('merge requires --into CURRENT_USERNAME')
            if args.reason:raise ValueError('merge uses its own audit receipt; --reason applies to roster edits')
            mapping={}
            for pair in args.map_character:
                if not re.fullmatch(r'[1-9][0-9]*:[1-9][0-9]*',pair):raise ValueError('use --map-character OLD_ID:NEW_ID')
                old,new=map(int,pair.split(':'))
                if old in mapping:raise ValueError('old character mapped more than once')
                mapping[old]=new
            if args.apply:
                if not args.backup:raise ValueError('--apply requires --backup NEW_FILE')
                result=streamer_merge.apply(db,args.login.lower(),args.into.lower(),mapping,path(args.backup))
            else:
                if args.backup:raise ValueError('--backup is used only with --apply')
                with Store(db,read_only=True) as store,store._transaction():
                    result=streamer_merge.preview(store,args.login.lower(),args.into.lower(),mapping)
            print(json.dumps(result,indent=2));return 0
        except (ValueError,OSError,sqlite3.Error) as error:
            print(f'Merge not completed: {error}');return 1
    if args.into or args.map_character or args.apply or args.backup or args.preview:
        print('Merge options require streamer merge.');return 1
    raw = dict(action='roster_add' if args.action == 'add' else 'roster_update', channel=args.login,
               reason=args.reason if args.reason is not None else f'msxp streamer {args.action}')
    if args.action == 'add':
        raw.update(tracking_enabled=True, public_visible=True,
                   automatic_characters=True, experimental_neural_level=True)
    else:raw['tracking_enabled' if args.action == 'disable' else 'public_visible'] = False
    try:
        with Store(db, read_only=True) as store, store._transaction():plan = roster.preview(store, raw)
        with Store(db, allow_migration=False) as store:result = roster.commit(store, plan)
    except (ValueError, OSError, sqlite3.Error) as error:
        print(f'Not saved: {error}');return 1
    row = result['configuration']
    print(f'Saved {row["channel"]} in {db}: tracking={row["tracking_enabled"]}, public={row["public_visible"]}.\n'
          'The running coordinator applies settings after any in-flight capture finishes.')
    return 0


ALERT_UNITS = ('msxp-alert.service', 'msxp-alert.timer')
ALERT_STATE = ROOT / 'private/alert-state.json'  # As exp_tracker.alerts.STATE.


def alert_streamer(args, s):
    """Persist one alert override without touching tracking or sending a message."""
    from .alerts import windows
    key = 'MSXP_ALERT_STREAM_MINUTES'
    if not args.login or not re.fullmatch(r'[A-Za-z0-9_]{1,25}', args.login):
        raise ValueError('Use a Twitch login, not a URL')
    default, overrides = windows(s)
    login = args.login.lower()
    if args.minutes is None:
        duration = overrides.get(login, default)
        print(f'{login}: {duration.total_seconds()/60:g} minutes ({"override" if login in overrides else "default"})');return 0
    if args.minutes == 'default':overrides.pop(login, None)
    else:
        _, replacement = windows(dict(s, MSXP_ALERT_STREAM_MINUTES=f'{login}={args.minutes}'))
        overrides.update(replacement)
    value = ','.join(f'{name}={duration.total_seconds()/60:g}' for name,duration in sorted(overrides.items()))
    server = bool(shutil.which('systemctl'))
    if os.environ.get(key) or server and read_env(ROOT / '.env').get(key):
        raise ValueError(f'Unset the overriding {key} in the process environment or project .env before saving file settings')
    if server and os.geteuid() != 0:os.execvp('sudo', ['sudo', sys.executable, *sys.argv])
    file = ALERT_ENV if server else ROOT / '.env'
    original = file.read_text(encoding='utf-8') if file.exists() else ''
    lines = [line for line in original.splitlines() if not re.match(r'^\s*(?:export\s+)?MSXP_ALERT_STREAM_MINUTES\s*=', line)]
    lines.append(f'{key}={value}')
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=file.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write('\n'.join(lines) + '\n')
        os.chmod(temporary, 0o640 if server else 0o600)
        if server:shutil.chown(temporary, 'root', s['MSXP_SERVER_USER'])
        os.replace(temporary, file)
    finally:
        if temporary:temporary.unlink(missing_ok=True)
    print(f'Saved {login}: {overrides.get(login, default).total_seconds()/60:g} minutes in {file}. Next check uses it; no restart needed.')
    return 0


def alert(args, s):
    """on/off/remove/status for the server's msxp-alert.timer; checks and tests run exp_tracker.alerts instead."""
    if not shutil.which('systemctl'):
        print('on, off, remove and status manage the alert timer on a Linux server.\n'
              'On this computer, keep  msxp alert --watch  running instead.');return 1
    timer = ALERT_UNITS[1]
    if args.action == 'status':
        state = {}
        try:state = json.loads(ALERT_STATE.read_text(encoding='utf-8'))
        except (OSError, ValueError):pass
        active = subprocess.run(['systemctl', 'is-active', timer], capture_output=True, text=True).stdout.strip()
        open_alerts = sorted(k for k, v in state.get('streams', {}).items() if v.get('open'))
        print(f'  Timer          {timer}: {active or "not installed"}\n'
              f'  Webhook        {"set" if s["MSXP_ALERT_WEBHOOK"] else "not set (alerts only reach the log)"}\n'
              f'  Stuck after    {s["MSXP_ALERT_MINUTES"]} minutes\n'
              f'  Per streamer   {s["MSXP_ALERT_STREAM_MINUTES"] or "none"}\n'
              f'  Last check     {state.get("checked_at", "never")}\n'
              f'  Open alerts    {", ".join(open_alerts) or "none"}\n'
              f'  Change         msxp alert on (webhook), MSXP_ALERT_MINUTES / MSXP_ALERT_STREAM_MINUTES in {ALERT_ENV}; logs: msxp logs alert')
        return 0
    if os.geteuid() != 0:os.execvp('sudo', ['sudo', sys.executable, *sys.argv])  # Installs units and edits /etc/msxp.
    if args.action in ('off', 'remove'):
        run(['systemctl', 'disable', '--now', timer], tool=False)
        if args.action == 'off':
            print(f'Alerts stopped. Settings kept in {ALERT_ENV}; start again with: msxp alert on');return 0
        for file in (*(Path('/etc/systemd/system') / u for u in ALERT_UNITS), ALERT_ENV, ALERT_STATE):
            file.unlink(missing_ok=True);print(f'removed {file}')
        return run(['systemctl', 'daemon-reload'], tool=False)
    for unit in ALERT_UNITS:shutil.copyfile(ROOT / 'deploy' / unit, Path('/etc/systemd/system') / unit)
    lines = (ALERT_ENV if ALERT_ENV.exists() else ROOT / 'deploy/msxp-alert.env.example').read_text(encoding='utf-8').splitlines()
    current = read_env(ALERT_ENV).get('MSXP_ALERT_WEBHOOK')
    try:url = input(f'Discord webhook URL ({"Enter keeps the current one" if current else "Enter for none: log only"}): ').strip()
    except EOFError:url = ''
    if url and not url.startswith('https://'):print('Not saved: a webhook URL starts with https://');return 1
    if url:lines = [f'MSXP_ALERT_WEBHOOK={url}' if l.startswith('MSXP_ALERT_WEBHOOK=') else l for l in lines]
    ALERT_ENV.parent.mkdir(exist_ok=True)
    ALERT_ENV.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    os.chmod(ALERT_ENV, 0o640);shutil.chown(ALERT_ENV, 'root', s['MSXP_SERVER_USER'])
    if run(['systemctl', 'daemon-reload'], tool=False) or run(['systemctl', 'enable', '--now', timer], tool=False):return 1
    print(f'Alerts on: a check every 5 minutes. Webhook {"set" if url or current else "not set"}.\n'
          'Try it: msxp alert test    See it: msxp alert status    Stop: msxp alert off')
    return 0


def remote(command, s, no_browser=False):
    """(ssh command, local url) running `msxp COMMAND` in the server's checkout; admin/api come through an SSH tunnel."""
    name = command[0] if command else 'doctor'
    port = s[PORTS[name]] if name in ('admin', 'api', 'dashboard') else None
    msxp = ' '.join(shlex.quote(c) for c in ['./msxp', *(command or ['doctor']), *(['--no-browser'] if port else [])])
    # As the service user, who owns the database and its WAL files; only reading the journal needs this login.
    owner_free = name == 'logs' or name == 'alert' and (command[1:2] in (['on'], ['off'], ['remove'])
        or command[1:2] == ['streamer'] and len(command) >= 5)  # Root work; showing an override uses msxp's read access.
    as_owner = '' if owner_free else f'sudo -u {shlex.quote(s["MSXP_SERVER_USER"])} '
    ssh = ['ssh', '-t', *(['-L', f'{port}:127.0.0.1:{port}'] if port else []), s['MSXP_SERVER'],
           f'cd {shlex.quote(s["MSXP_SERVER_DIR"])} && {as_owner}{msxp}']
    return ssh, (f'http://127.0.0.1:{port}/{PAGES.get(name, "")}' if port and not no_browser else None)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='msxp', add_help=False)
    commands = parser.add_subparsers(dest='command')
    for name, text in (('help', 'show the overview'), ('install', 'install Python packages and the OCR engine'),
                       ('doctor', 'check your setup'), ('demo', 'website with fictional players'),
                       ('setup', 'create your tracker database'), ('admin', 'add and manage streamers'),
                       ('streamer', 'add, disable tracking or hide a streamer without a browser'),
                       ('tracker', 'capture streams + local website'), ('api', 'website only'),
                       ('dashboard', 'operator view of every capture'),
                       ('health', 'missed captures and why'), ('cleanup', 'keep only the last 24 h'),
                       ('test', 'run the test suite'), ('test-data', 'download only required private test files'),
                       ('where', 'where files are'), ('logs', 'follow or browse the log'),
                       ('sql', 'open a read-only SQLite shell'),
                       ('alert', 'Discord message when a live stream is stuck'),
                       ('server', 'run a command on your server over SSH')):
        sub = commands.add_parser(name, help=text, aliases=['diag'] if name == 'doctor' else [])
        if name == 'logs':
            sub.add_argument('which', nargs='*', choices=list(UNITS), help='on a server: tracker, api, cleanup, alert (default all)')
            sub.add_argument('--lines', type=log_lines, help='latest N entries, or all (default 50; all with time filters/browse)')
            sub.add_argument('--since', help='start time, e.g. "14 hours ago" or "2026-10-23 08:00:00"')
            sub.add_argument('--until', help='end time, e.g. "10 hours ago"')
            sub.add_argument('--search', '--grep', help='case-insensitive literal substring')
            mode = sub.add_mutually_exclusive_group()
            mode.add_argument('--browse', action='store_true', help='scroll/search historical logs in the journal viewer')
            mode.add_argument('--follow', dest='follow', action='store_true', default=None, help='keep waiting for new entries')
            mode.add_argument('--no-follow', dest='follow', action='store_false', help='show entries and exit')
        if name == 'alert':
            sub.add_argument('action', nargs='?', default='check', choices=['check', 'test', 'on', 'off', 'remove', 'status', 'streamer'],
                             help='check once (default), send a test, or manage the server timer')
            sub.add_argument('login', nargs='?', help='streamer action: Twitch login')
            sub.add_argument('setting', nargs='?', choices=['min'], help='streamer action: set its waiting time')
            sub.add_argument('minutes', nargs='?', help='streamer action: minutes, or default to remove its override')
        if name == 'sql':sub.add_argument('query', nargs='?', help='optional SQL to execute instead of opening the shell')
        if name == 'streamer':
            sub.add_argument('action', choices=['add', 'disable', 'hide', 'merge'], help='add enables tracking; merge previews a username change')
            sub.add_argument('login', help='Twitch login, not a URL or character name')
            sub.add_argument('--reason', help='single-line audit reason (default: msxp streamer ACTION)')
            sub.add_argument('--into', help='merge: current Twitch username, already tracked')
            sub.add_argument('--map-character', action='append', default=[], metavar='OLD_ID:NEW_ID', help='merge: explicitly verified duplicate character (repeatable)')
            merge_mode=sub.add_mutually_exclusive_group()
            merge_mode.add_argument('--preview', action='store_true', help='merge: read-only review (default)')
            merge_mode.add_argument('--apply', action='store_true', help='merge: back up, drain only these lanes, merge and resume the destination')
            sub.add_argument('--backup', help='merge --apply: new backup SQLite file; never overwritten')
        if name == 'server':
            sub.add_argument('--no-browser', action='store_true')
            sub.add_argument('remote', nargs=argparse.REMAINDER, help='the msxp command to run there (default: doctor)')
        if name in ('setup', 'admin', 'streamer', 'tracker', 'api', 'dashboard', 'health', 'cleanup', 'sql', 'alert'):sub.add_argument('--db', help='database (default: MSXP_DATABASE)')
        if name in ('demo', 'admin', 'tracker', 'api', 'dashboard'):
            sub.add_argument('--port', type=int);sub.add_argument('--no-browser', action='store_true')
        if name == 'tracker':sub.add_argument('--workers', type=int, help='streams captured at once (default: MSXP_WORKERS)')
        if name == 'health':sub.add_argument('--minutes', type=int, default=60)
        if name == 'cleanup':sub.add_argument('--apply', action='store_true', help='actually delete; default is a dry run')
        if name == 'install':sub.add_argument('--no-ocr', action='store_true', help='skip the RapidOCR environment')
        if name == 'test-data':sub.add_argument('--check', action='store_true', help='verify installed files; downloads only the manifest')
    args, extra = parser.parse_known_args(argv)
    name = {'diag': 'doctor', None: 'help'}.get(args.command, args.command)
    if extra and name not in ('demo', 'admin', 'tracker', 'api', 'dashboard', 'health', 'cleanup', 'test', 'test-data', 'alert'):parser.error(f'unknown option {extra[0]}')
    s = settings()
    if name == 'alert':
        if args.action == 'streamer':
            if extra or bool(args.setting) != (args.minutes is not None):parser.error('Use alert streamer LOGIN [min MINUTES|default]')
            try:return alert_streamer(args, s)
            except (ValueError, OSError) as error:parser.error(str(error))
        if args.login or args.setting or args.minutes:parser.error('Only alert streamer accepts a login and minutes')
    if name == 'help':print(HELP, end='');return 0
    if name == 'doctor':return doctor(s)
    if name == 'install':return install(args, s)
    if name == 'where':return where(s)
    if name == 'logs':return logs(args)
    if name == 'sql':return sql(args, s)
    if name == 'streamer':return streamer(args, s)
    if name == 'alert' and args.action not in ('check', 'test'):return alert(args, s)
    if name == 'server':
        if not s['MSXP_SERVER']:
            print("Add your server's SSH login to .env first, e.g.  MSXP_SERVER=root@203.0.113.7\n"
                  '(the app is expected at MSXP_SERVER_DIR, default /opt/msxp/app)');return 1
        return run(*remote(args.remote, s, args.no_browser), tool=False)
    if not VENV.is_file():print('Not installed yet. Run: msxp install');return 1
    if name == 'setup':return setup(args, s)
    args.no_browser = getattr(args, 'no_browser', True)
    command, url = build(name, args, s, extra)
    if '--db' in command and not Path(command[command.index('--db') + 1]).is_file() or '--db-roster' in command and not (
            Path(command[command.index('--db-roster') + 1]).is_file()):
        print(f'No tracker database at {path(args.db or s["MSXP_DATABASE"])}.\nRun: msxp setup   (or set MSXP_DATABASE in .env)');return 1
    if name == 'tracker' and not OCR.is_file():print('The OCR environment is missing. Run: msxp install');return 1
    return run(command, url)


if __name__ == '__main__':
    raise SystemExit(main())
