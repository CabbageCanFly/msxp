"""One explicitly assigned local alpha: existing capture, SQLite diagnostics and HTTP."""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from exp_tracker.diagnostics import Diagnostics
from exp_tracker.recognition import configure_tesseract
from exp_tracker.server import CHANNEL, create_server
from exp_tracker.shadow_view import observation
from exp_tracker.store import Store, utc
import shadow_capture


def initialize(database, channel, character, say):
    """Inspect before mutation; reuse the Store's explicit administration methods."""
    state = None
    if database.exists():
        with Store(database, read_only=True) as store:
            channels = [r[0] for r in store.db.execute('SELECT login FROM streamers ORDER BY login')]
            if channel not in channels and channels:
                raise ValueError(f'Database mismatch: {channel!r} is absent; configured channels: {", ".join(channels)}. Choose the correct --db or a fresh path. No selection changed.')
            state = store.state(channel) if channel in channels else None
        if state:
            selected = next((c for c in state['characters'] if c['id'] == state['selected_character_id']), None)
            say(f'Existing selection: {selected["label"]!r}' if selected else 'Existing selection: none')
            if selected and selected['label'] != character:
                raise ValueError(f'Character mismatch: selected {selected["label"]!r}, requested {character!r}. Use that name or explicitly switch with the tracking CLI; nothing reassigned.')
            if state['session'] and state['session']['character_id'] != state['selected_character_id']:
                raise ValueError('Session/selection mismatch; repair explicit assignment before capturing')
    say(f'Plan: channel={channel}; character={character!r}; '
        f'{"reuse session " + str(state["session"]["id"]) if state and state["session"] else "start session"}; '
        f'{"reuse database" if database.exists() else "initialize new database"}')
    database.parent.mkdir(parents=True, exist_ok=True)
    with Store(database) as store:
        store.add_channel(channel)
        char = store.add_character(channel, character)
        store.select_character(channel, char, only_if_unselected=True)
        store.start_session(channel, expected_character_id=char)
        return store.state(channel)


def latest_status(latest):
    return (f"{latest['age_seconds']:.1f}s old / {'STALE' if latest['stale'] else 'local age only'}"
            if latest else 'no complete candidate yet')


def report_attempt(record, committed, *, database, channel, neural_enabled):
    row = observation(record)
    reasons = row['reasons']
    explanations = {
        'offline_or_unavailable': 'stream offline or not playable (not confirmed offline)',
        'access_denied': 'Twitch denied access; no bypass attempted',
        'network_unavailable': 'network/DNS/firewall connection failed',
        'frame_timeout': 'no frame within capture timeout',
        'decoder_failed': 'FFmpeg could not decode a frame',
        'source_ended': 'source ended before a usable frame',
        'capture_process_failed': 'capture process could not start',
        'missing_hud': 'HUD not found', 'multiple_huds': 'competing HUDs; no region selected',
        'strict_pair_unavailable': 'no strict full EXP pair (percentage-only may still exist)',
        'neural_worker_failed': 'RapidOCR worker failed; check its existing environment/models',
        'neural_timeout': 'RapidOCR exceeded its timeout',
        'local_receipt_age_exceeded': 'local frame expired during processing',
    }
    captured = row['received_at'] is not None
    localization = record.get('localization') or {}
    count = localization.get('count')
    hud = 'unique' if count == 1 else 'missing' if count == 0 else 'ambiguous' if count else 'not run'
    pair = row['candidate']
    only = row['percentage_only_candidate']
    value = f"{int(pair['exp']):,} [{pair['percentage']}%]" if pair else (
        f"[{only['percentage']}%] (percentage-only; EXP unavailable)" if only else 'unavailable/rejected')
    neural = row['neural_level']
    level = str(neural['level']) if neural and neural['level'] is not None else 'unavailable' if neural_enabled else 'off'
    freshness = 'unknown'
    if committed:
        with Store(database, read_only=True) as store:
            latest = Diagnostics(store).snapshot(channel)['latest_reading']
        freshness = latest_status(latest)
    return (f"#{row['index']:02d} frame={'acquired' if captured else 'FAILED'}; HUD={hud}; EXP={value}; "
        f"Tesseract={row['visual_level'] if row['visual_level'] is not None else 'unavailable'}; "
        f"neural level={level}; SQLite={'committed' if committed else 'NOT COMMITTED'}; latest={freshness}. "
        + '; '.join(explanations.get(reason, reason.replace('_', ' ')) for reason in reasons))


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--channel', required=True, help='Explicit Twitch login / local-video DB assignment')
    cli.add_argument('--character', required=True, help='Exact selected character label; never switches an existing selection')
    cli.add_argument('--authorized', action='store_true', help='Confirm streamer permission for this live trial')
    cli.add_argument('--db', type=Path, help='Default: private/local-alpha/live/CHANNEL.sqlite3')
    cli.add_argument('--file', type=Path, help='Offline local video instead of Twitch; no network capture')
    cli.add_argument('--port', type=int, default=8765)
    cli.add_argument('--twitch-status',action='store_true',help='Opt in to cached Helix live status with server environment credentials')
    cli.add_argument('--exit-after-capture', action='store_true', help='Close HTTP after the bounded trial (useful for offline checks)')
    defaults = shadow_capture.parser()
    for name, kind in [('count', int), ('interval', float), ('start', float), ('timeout', float),
                       ('max-age', float), ('ocr-timeout', float), ('quality', str),
                       ('ocr-python', Path), ('requirements', Path)]:
        cli.add_argument('--' + name, type=kind, default=defaults.get_default(name.replace('-', '_')))
    cli.add_argument('--experimental-neural-level', action='store_true')
    cli.add_argument('--save-crops', action='store_true')
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    httpd = thread = operator = None
    def say(message):
        print(message, flush=True)
        if operator:
            operator.write(json.dumps(dict(at=utc(), message=message)) + '\n')
            operator.flush()
    try:
        if not CHANNEL.fullmatch(args.channel):
            raise ValueError('Use a Twitch login, not a URL or path')
        args.channel = args.channel.lower()
        if not args.character.strip() or len(args.character) > 100 or any(ord(c) < 32 for c in args.character):
            raise ValueError('Character must contain 1..100 characters without control characters')
        if not 0 <= args.port <= 65535:
            raise ValueError('port must be 0..65535')
        database = (args.db or ROOT / 'private/local-alpha/live' / f'{args.channel}.sqlite3').resolve()
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        directory = ROOT / 'private/local-alpha/runs' / f'{args.channel}-{stamp}-{uuid.uuid4().hex[:8]}'
        capture = ['--db', str(database), '--output', str(directory / 'capture.jsonl')]
        capture += ['--file', str(args.file), '--tracking-channel', args.channel] if args.file else ['--channel', args.channel]
        for name in ('count', 'interval', 'start', 'timeout', 'max_age', 'ocr_timeout', 'quality', 'ocr_python', 'requirements'):
            capture += ['--' + name.replace('_', '-'), str(getattr(args, name))]
        for name in ('authorized', 'experimental_neural_level', 'save_crops'):
            if getattr(args, name):
                capture.append('--' + name.replace('_', '-'))
        try:
            shadow_capture.prepare(shadow_capture.parser().parse_args(capture))
        except (KeyError, TypeError, AttributeError):
            raise ValueError('Invalid EXP requirements file; expected the existing to_next table') from None
        configure_tesseract()
        if not args.file and importlib.util.find_spec('streamlink') is None:
            raise ValueError('Streamlink is missing from this Python environment; install the existing capture extra')
        directory.mkdir(parents=True, exist_ok=False)
        operator = (directory / 'operator.jsonl').open('x', encoding='utf-8')
        say(f'Database: {database}')
        say(f'Private logs: {directory}')
        state = initialize(database, args.channel, args.character, say)
        say(f'Selected: ttv/{args.channel} / {args.character!r} / session {state["session"]["id"]}')
        with Store(database, read_only=True) as store:
            saved = Diagnostics(store).snapshot(args.channel)
        say(f'Saved history: {len(saved["observations"])} recent attempts; latest={latest_status(saved["latest_reading"])}')
        httpd = create_server(database, port=args.port, diagnostic_dashboard=True,twitch_status=args.twitch_status,background=True)
        httpd.quiet = True
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        say(f'Dashboard: http://127.0.0.1:{httpd.server_port}/dashboard/{args.channel}')
        say(f'EXP Tracker: http://127.0.0.1:{httpd.server_port}/stream/{args.channel}')
        say('UNVERIFIED diagnostics only. HTTP is ready; no frame acquired yet. Ctrl+C stops capture and HTTP.')
        counts = dict(attempts=0, frames=0, candidates=0, committed=0)
        active_run_id=None
        def progress(record, committed):
            nonlocal active_run_id
            if record['type'] == 'configuration':
                if committed:
                    with Store(database, read_only=True) as store:
                        binding = store.db.execute('SELECT character_id,session_id FROM diagnostic_runs WHERE run_id=?',
                                                   (record['run_id'],)).fetchone()
                    if tuple(binding) != (state['selected_character_id'], state['session']['id']):
                        say('Assignment changed during startup; capture has NOT started. Restart with the explicit current selection.')
                        raise ValueError('Diagnostic startup assignment changed')
                    active_run_id=record['run_id']
                    httpd.active_run_ids.add(active_run_id)
                say(f'Capture runner starting: {args.count} attempts at {args.interval:g}s; source={"local video" if args.file else "authorized Twitch"}. Awaiting first frame.'
                    if committed else 'Configuration NOT committed; capture has NOT started.')
            if record['type'] == 'attempt':
                counts['attempts'] += 1
                counts['frames'] += record.get('received_at') is not None
                counts['committed'] += committed
                counts['candidates'] += bool(committed and record.get('current') and
                    (record.get('candidate') is not None or record.get('percentage_only_candidate') is not None))
                say(report_attempt(record, committed, database=database, channel=args.channel,
                                   neural_enabled=args.experimental_neural_level))
        def activity(value):
            if active_run_id:httpd.coordinator_status[args.channel]={**value,'run_id':active_run_id}
        code=1
        try:
            code = shadow_capture.main(capture, on_record=progress,on_activity=activity)
        finally:
            httpd.active_run_ids.clear()
            httpd.coordinator_status[args.channel]=dict(state='stopped',updated_at=utc(),
                completion='completed' if code==0 else 'interrupted' if code==130 or sys.exc_info()[0] is KeyboardInterrupt else 'failed')
        say(f'Capture STOPPED: {counts["frames"]}/{counts["attempts"]} frames; {counts["candidates"]} fresh strict diagnostic candidates; {counts["committed"]} SQLite commits. None are trusted EXP.')
        if code == 130:
            return 130
        if code:
            say('Capture/persistence failed; inspect capture.jsonl and the explicit character/session assignment.')
            return 1
        outcome = 0 if counts['candidates'] else 2
        if not args.exit_after_capture:
            say('Dashboard remains read-only; capture is NOT running. Ages continue to increase. Ctrl+C closes HTTP.')
            try:
                while thread.is_alive():
                    thread.join(.5)
            except KeyboardInterrupt:
                pass
        return outcome
    except KeyboardInterrupt:
        say('Interrupted; capture and HTTP are stopping.')
        return 130
    except SystemExit as error:
        say('Capture startup rejected its configuration; no successful tracking is implied.')
        return int(error.code or 0)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        say(f'FAILED: {error}. Capture is not continuing.')
        return 1
    finally:
        if httpd:
            if thread and thread.is_alive():
                httpd.shutdown()
                thread.join(timeout=2)
            httpd.server_close()
        if operator:
            operator.close()


if __name__ == '__main__':
    raise SystemExit(main())
