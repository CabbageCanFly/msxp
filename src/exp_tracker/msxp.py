"""msxp: one command for the MapleStory Classic EXP tracker. Start with `msxp help`.

Thin wrappers around the project's own tools. Each prints the full command it runs, and any
option msxp does not know passes through to that tool (e.g. `msxp tracker --check`).
Standard library only, so `msxp install` and `msxp doctor` work before anything is installed.
"""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser

ROOT = Path(__file__).resolve().parents[2]
WINDOWS = os.name == 'nt'
BIN = 'Scripts/python.exe' if WINDOWS else 'bin/python'
VENV = ROOT / '.venv' / BIN
OCR = ROOT / 'private/rapidocr/.venv' / BIN
OCR_PACKAGES = ['rapidocr==3.10.0', 'onnxruntime==1.31.0', 'psutil==7.2.2', 'Pillow==12.3.0']  # As deploy/install-ubuntu.sh.
SETTINGS = {'MSXP_DATABASE': 'private/msxp/tracker.sqlite3', 'MSXP_PORT': '8765', 'MSXP_ADMIN_PORT': '8766',
            'MSXP_DEMO_PORT': '8890', 'MSXP_WORKERS': '2',
            'MSXP_SERVER': '', 'MSXP_SERVER_DIR': '/opt/msxp/app', 'MSXP_SERVER_USER': 'msxp'}
TWITCH_KEYS = ('TWITCH_CLIENT_ID', 'TWITCH_CLIENT_SECRET')
SERVER_ENV = (Path('/etc/msxp/roster.env'), Path('/etc/msxp/msxp.env'))  # Written by deploy/install-ubuntu.sh.
UNITS = {'tracker': 'msxp-tracker', 'api': 'msxp-api', 'cleanup': 'msxp-retention'}
WRITES = ('admin', 'setup', 'cleanup')  # On a server these run as the service user, who owns the database.
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
                 msxp admin       add streamers, confirm permission, start/pause tracking
                 msxp tracker     capture the streams + your local website
  More           msxp api         website only, for an existing database
                 msxp health      missed captures in the last hour, and why
                 msxp cleanup     keep only the last 24 h of raw readings (add --apply)
                 msxp test        run the test suite
                 msxp where       where your settings, database, logs and backups are
                 msxp logs        follow the log (on a server: tracker, api or cleanup)
  On a server    msxp server ...  run any command on your server over SSH, e.g. msxp server admin

Settings and secrets live in .env (msxp install copies .env.example; never commit .env):
  MSXP_DATABASE   your tracker database   (default private/msxp/tracker.sqlite3)
  MSXP_PORT / MSXP_ADMIN_PORT / MSXP_DEMO_PORT   website 8765, admin 8766, demo 8890
  MSXP_WORKERS    streams captured at once (default 2)
  MSXP_SERVER     your server's SSH login for msxp server, e.g. root@203.0.113.7
  TWITCH_CLIENT_ID + TWITCH_CLIENT_SECRET   optional, shows who is live (docs/twitch-authentication.md)
On a server, the installer's /etc/msxp/roster.env and msxp.env are read too.

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
    port = str(getattr(args, 'port', None) or s['MSXP_ADMIN_PORT' if name == 'admin' else 'MSXP_DEMO_PORT' if name == 'demo' else 'MSXP_PORT'])
    url = f'http://127.0.0.1:{port}/'
    command, opens = {
        'demo': ([py, 'tools/preview_pages.py', '--demo', '--live', '--port', port], True),
        'admin': ([py, '-m', 'exp_tracker.admin_server', '--db', db, '--port', port], True),
        'tracker': ([py, 'tools/multi_alpha.py', '--db-roster', db, '--port', port, '--continuous',
                     '--workers', str(getattr(args, 'workers', None) or s['MSXP_WORKERS']), '--ocr-python', str(OCR), *twitch], True),
        'api': ([py, '-m', 'exp_tracker.server', '--db', db, '--port', port, '--public-only', *twitch], True),
        'health': ([py, 'tools/tracker_health.py', '--db', db, '--minutes', str(getattr(args, 'minutes', 60))], False),
        'cleanup': ([py, '-m', 'exp_tracker.retention', '--db', db,
                     *(['--apply', '--log-root', 'private/multi-alpha/runs'] if getattr(args, 'apply', False) else [])], False),
        'test': ([py, '-m', 'pytest'], False),
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
    yield 'OCR environment (RapidOCR)', OCR.is_file(), 'msxp install', 'need'
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
    if not VENV.is_file():steps.append([sys.executable, '-m', 'venv', ROOT / '.venv'])
    pip = ['-m', 'pip', 'install', '--disable-pip-version-check']
    steps += [[VENV, *pip, '--upgrade', 'pip'], [VENV, *pip, '-e', '.[capture,dev]']]
    if not args.no_ocr:
        if not OCR.is_file():steps.append([sys.executable, '-m', 'venv', ROOT / 'private/rapidocr/.venv'])
        steps.append([OCR, *pip, '--only-binary=:all:', *OCR_PACKAGES])
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
    print(f'Created your tracker database: {db}\n\nNext:\n  1. msxp admin     add a streamer, confirm you have permission, enable tracking'
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
            ('Manual backups', ROOT / 'private/manual-backups'), ('Python environment', ROOT / '.venv'),
            ('OCR environment', ROOT / 'private/rapidocr/.venv')]
    for what, location in rows:
        print(f'  {what:<26} {location}' + ('' if location.exists() else '   (not created yet)'))
    if services():print(f'  {"Services (systemd)":<26} {", ".join(services())}   logs: msxp logs')
    return 0


def logs(args):
    """A server's journal for the chosen services; locally, the newest capture log."""
    if services() and shutil.which('journalctl'):
        units = [UNITS[n] for n in args.which or UNITS]
        return run(['journalctl', *(x for unit in units for x in ('-u', unit)), '-n', str(args.lines),
                    *([] if args.no_follow else ['-f'])], tool=False)
    newest = max((ROOT / 'private/multi-alpha/runs').glob('*/operator*.jsonl'), key=lambda p: p.stat().st_mtime, default=None)
    if not newest:print('No capture logs yet. A running msxp tracker prints its log in its own window.');return 0
    print(f'Newest capture log: {newest}\n(msxp tracker also prints a readable log in its own window)\n')
    print(''.join(newest.read_text(encoding='utf-8', errors='replace').splitlines(keepends=True)[-args.lines:]), end='')
    return 0


def remote(command, s, no_browser=False):
    """(ssh command, local url) running `msxp COMMAND` in the server's checkout; admin/api come through an SSH tunnel."""
    name = command[0] if command else 'doctor'
    port = {'admin': s['MSXP_ADMIN_PORT'], 'api': s['MSXP_PORT']}.get(name)
    msxp = ' '.join(shlex.quote(c) for c in ['./msxp', *(command or ['doctor']), *(['--no-browser'] if port else [])])
    as_owner = f'sudo -u {shlex.quote(s["MSXP_SERVER_USER"])} ' if name in WRITES else ''
    ssh = ['ssh', '-t', *(['-L', f'{port}:127.0.0.1:{port}'] if port else []), s['MSXP_SERVER'],
           f'cd {shlex.quote(s["MSXP_SERVER_DIR"])} && {as_owner}{msxp}']
    return ssh, (f'http://127.0.0.1:{port}/' if port and not no_browser else None)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='msxp', add_help=False)
    commands = parser.add_subparsers(dest='command')
    for name, text in (('help', 'show the overview'), ('install', 'install Python packages and the OCR engine'),
                       ('doctor', 'check your setup'), ('demo', 'website with fictional players'),
                       ('setup', 'create your tracker database'), ('admin', 'add and manage streamers'),
                       ('tracker', 'capture streams + local website'), ('api', 'website only'),
                       ('health', 'missed captures and why'), ('cleanup', 'keep only the last 24 h'),
                       ('test', 'run the test suite'), ('where', 'where files are'), ('logs', 'follow the log'),
                       ('server', 'run a command on your server over SSH')):
        sub = commands.add_parser(name, help=text, aliases=['diag'] if name == 'doctor' else [])
        if name == 'logs':
            sub.add_argument('which', nargs='*', choices=list(UNITS), help='on a server: tracker, api, cleanup (default all)')
            sub.add_argument('--lines', type=int, default=50);sub.add_argument('--no-follow', action='store_true')
        if name == 'server':
            sub.add_argument('--no-browser', action='store_true')
            sub.add_argument('remote', nargs=argparse.REMAINDER, help='the msxp command to run there (default: doctor)')
        if name in ('setup', 'admin', 'tracker', 'api', 'health', 'cleanup'):sub.add_argument('--db', help='database (default: MSXP_DATABASE)')
        if name in ('demo', 'admin', 'tracker', 'api'):
            sub.add_argument('--port', type=int);sub.add_argument('--no-browser', action='store_true')
        if name == 'tracker':sub.add_argument('--workers', type=int, help='streams captured at once (default: MSXP_WORKERS)')
        if name == 'health':sub.add_argument('--minutes', type=int, default=60)
        if name == 'cleanup':sub.add_argument('--apply', action='store_true', help='actually delete; default is a dry run')
        if name == 'install':sub.add_argument('--no-ocr', action='store_true', help='skip the RapidOCR environment')
    args, extra = parser.parse_known_args(argv)
    name = {'diag': 'doctor', None: 'help'}.get(args.command, args.command)
    if extra and name not in ('demo', 'admin', 'tracker', 'api', 'health', 'cleanup', 'test'):parser.error(f'unknown option {extra[0]}')
    s = settings()
    if name == 'help':print(HELP, end='');return 0
    if name == 'doctor':return doctor(s)
    if name == 'install':return install(args, s)
    if name == 'where':return where(s)
    if name == 'logs':return logs(args)
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
