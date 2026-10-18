"""Manage private multi-alpha assignments. Changes apply on controlled restart."""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import tempfile

import multi_alpha as multi
from exp_tracker.store import Store


@contextmanager
def edit_lock(path):
    # OS-released lock serializes roster commands, including after an interrupted edit.
    with path.with_suffix(path.suffix + '.roster.lock').open('a+b') as handle:
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            acquire = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            release = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            acquire = lambda: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(handle, fcntl.LOCK_UN)
        try:
            acquire()
        except OSError:
            raise ValueError('Another roster edit is in progress') from None
        try:
            yield
        finally:
            handle.seek(0)
            release()


def read_config(path):
    if path.stat().st_size > 32768:
        raise ValueError('Configuration exceeds 32 KiB')
    original = path.read_bytes()
    return original, json.loads(original.decode('utf-8-sig'))


def save_config(path, value, original):
    content = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    if len(content) > 32768:
        raise ValueError('Configuration exceeds 32 KiB')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + '.', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if (path.read_bytes() if path.exists() else None) != original:
            raise ValueError('Configuration changed during edit; retry after reviewing it')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def inspect_roster(database, rows):
    """Read compact ownership/history facts without creating or migrating a database."""
    configured = {row['channel']: row for row in rows}
    saved = {}
    if database.exists():
        with Store(database, read_only=True) as store:
            for row in store.db.execute('''SELECT s.login,c.label,
                (SELECT COUNT(*) FROM diagnostic_runs WHERE streamer_id=s.id) AS runs,
                (SELECT COUNT(*) FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id
                 WHERE r.streamer_id=s.id) AS attempts,
                (SELECT summary_json FROM diagnostic_runs WHERE streamer_id=s.id ORDER BY rowid DESC LIMIT 1) AS summary
                FROM streamers s LEFT JOIN characters c ON c.id=s.selected_character_id ORDER BY s.login LIMIT 101'''):
                saved[row['login']] = dict(row)
    if len(saved) > 100:
        raise ValueError('Roster inspection is limited to 100 saved channels; use the historical dashboard')
    result = []
    for channel in sorted(configured.keys() | saved.keys()):
        assignment, history = configured.get(channel), saved.get(channel)
        summary = json.loads(history['summary']) if history and history['summary'] else None
        result.append(dict(channel=channel,
            roster='configured' if assignment and assignment.get('enabled', True) else 'disabled' if assignment else 'historical_only',
            character=assignment['character'] if assignment else history['label'],
            source=assignment['source'] if assignment else None,
            authorized=assignment.get('authorized', False) if assignment else None,
            runs=history['runs'] if history else 0, attempts=history['attempts'] if history else 0,
            last_run='none' if not history or not history['runs'] else
                'interrupted' if summary and summary.get('interrupted') else 'completed' if summary else 'unfinished_activity_unknown'))
    return result


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--config', type=Path, required=True)
    cli.add_argument('--offline-fast-test', action='store_true', help='Validate explicit local-video-only 3s settings')
    sub = cli.add_subparsers(dest='action', required=True)
    init = sub.add_parser('init', help='Create a NEW empty private roster; never overwrite')
    init.add_argument('--database', default='private/multi-alpha/tracking.sqlite3')
    init.add_argument('--port', type=int, default=8765)
    sub.add_parser('list', help='List configured, disabled and historical-only channels')
    inspect = sub.add_parser('inspect')
    inspect.add_argument('channel')
    for name in ('add', 'disable', 'enable', 'remove'):
        command = sub.add_parser(name)
        command.add_argument('channel')
        command.add_argument('--dry-run', action='store_true')
        if name in ('add', 'enable'):
            command.add_argument('--authorized', action='store_true', help='Explicit permission for Twitch capture')
        if name == 'add':
            command.add_argument('--character', required=True)
            command.add_argument('--source', choices=('file', 'twitch'), default='twitch')
            command.add_argument('--file')
            command.add_argument('--start', type=float, default=0)
            command.add_argument('--interval', type=float, default=15)
            command.add_argument('--count', type=int, default=3)
            command.add_argument('--disabled', action='store_true')
            command.add_argument('--experimental-neural-level', action='store_true')
            command.add_argument('--save-crops', action='store_true')
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        path = multi.private(args.config)
        if args.action == 'init':
            path.parent.mkdir(parents=True, exist_ok=True)
        with edit_lock(path):
            if args.action == 'init':
                if path.exists():
                    raise ValueError('Configuration already exists; refusing to overwrite')
                original, value = None, dict(database=args.database, port=args.port, streams=[])
            else:
                original, value = read_config(path)
            database, port, rows = multi.validate_config(value, offline_fast_test=args.offline_fast_test)
            multi.check_assignments(database, rows)
            if args.action in ('list', 'inspect'):
                listing = inspect_roster(database, rows)
                if args.action == 'inspect':
                    listing = [row for row in listing if row['channel'] == args.channel.lower()]
                    if not listing:
                        raise ValueError('Channel is neither configured nor saved in this database')
                report = dict(assignments=listing, capture_activity='Check /streams on the coordinator server; unfinished runs alone do not prove capture is running')
                if args.action == 'inspect':
                    report['settings'] = next((row for row in rows if row['channel'] == args.channel.lower()), None)
                print(json.dumps(report, indent=2))
                return 0
            if args.action != 'init':
                channel = args.channel.lower()
                if not multi.CHANNEL.fullmatch(channel):
                    raise ValueError('Use a channel login, not a URL')
                matches = [row for row in value['streams'] if row['channel'].lower() == channel]
                if args.action == 'add':
                    if matches:
                        raise ValueError('Channel already configured; use enable or inspect')
                    row = dict(channel=channel, character=args.character, source=args.source,
                        interval=args.interval, count=args.count,
                        enabled=not args.disabled and (args.source == 'file' or args.authorized),
                        authorized=args.authorized, experimental_neural_level=args.experimental_neural_level,
                        save_crops=args.save_crops)
                    if args.source == 'file':
                        row.update(file=args.file, start=args.start)
                    elif args.file or args.start:
                        raise ValueError('file/start apply only to local video sources')
                    value['streams'].append(row)
                else:
                    if not matches:
                        raise ValueError('Channel is not configured')
                    row = matches[0]
                    if args.action == 'remove':
                        value['streams'].remove(row)
                    else:
                        if args.action == 'enable' and args.authorized:
                            row['authorized'] = True
                        if args.action == 'enable' and row['source'] == 'twitch' and not row.get('authorized'):
                            raise ValueError('Enabling Twitch requires explicit --authorized permission')
                        row['enabled'] = args.action == 'enable'
            database, _, rows = multi.validate_config(value, offline_fast_test=args.offline_fast_test)
            multi.check_assignments(database, rows)
            listing = inspect_roster(database, rows)
            if getattr(args, 'dry_run', False):
                print('PREVIEW only; no configuration or SQLite changes.')
            else:
                save_config(path, value, original)
                print('Roster saved. SQLite history and character/session selections are unchanged.')
            print(json.dumps(dict(assignments=listing), indent=2))
            print('Changes apply after Ctrl+C and coordinator restart.')
            print(f'Viewer: http://127.0.0.1:{port}/streams' if port else 'Viewer port will be printed by the coordinator (port 0 selects an available port).')
            if not any(row.get('enabled', True) for row in rows):
                print('No enabled assignments. Capture will refuse to start; read-only historical viewing remains available.')
            return 0
    except (json.JSONDecodeError, UnicodeError):
        print('Roster operation failed: invalid JSON or UTF-8. No capture started.')
        return 1
    except ValueError as error:
        print(f'Roster operation failed: {error}. No capture started.')
        return 1
    except (OSError, TypeError, KeyError, sqlite3.Error):
        # Do not echo malformed configuration values or accidentally supplied credentials.
        print('Roster operation failed: invalid configuration, assignment mismatch, concurrent edit, or inaccessible file/database. No capture started.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
