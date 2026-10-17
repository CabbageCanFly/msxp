"""One bounded sequential shadow coordinator, shared SQLite and localhost directory."""

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time
import uuid

import shadow_capture as shadow
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.metrics import ResourceMonitor
from exp_tracker.recognition import configure_tesseract
from exp_tracker.server import CHANNEL, create_server
from exp_tracker.store import Store, utc
from local_alpha import report_attempt

APP = 'multi_alpha_v1'


def private(path):
    return shadow.private_path(Path(path))


def load_config(path):
    path = private(path)
    if path.stat().st_size > 32768:
        raise ValueError('Configuration exceeds 32 KiB')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or set(value) - {'database', 'port', 'streams'}:
        raise ValueError('Expected database, port and streams configuration')
    streams = value.get('streams')
    if not isinstance(streams, list) or not 2 <= len(streams) <= 5:
        raise ValueError('Configure 2..5 explicit stream assignments')
    database = private(value.get('database', 'private/multi-alpha/tracking.sqlite3'))
    port = value.get('port', 8765)
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('port must be 0..65535')
    result, seen = [], set()
    for row in streams:
        allowed = {'channel', 'character', 'source', 'file', 'start', 'interval', 'count', 'authorized',
                   'experimental_neural_level', 'save_crops', 'timeout', 'max_age', 'ocr_timeout', 'quality'}
        if not isinstance(row, dict) or set(row) - allowed:
            raise ValueError('Unknown stream configuration field')
        channel, character = row.get('channel'), row.get('character')
        if not isinstance(channel, str) or not CHANNEL.fullmatch(channel) or channel.lower() in seen:
            raise ValueError('Each stream needs a distinct Twitch login / explicit local assignment')
        if not isinstance(character, str) or not character.strip() or len(character) > 100 or any(ord(c)<32 for c in character):
            raise ValueError('Character must contain 1..100 characters without control characters')
        seen.add(channel.lower())
        if row.get('source') not in ('file', 'twitch'):
            raise ValueError('Source must be file or twitch')
        for key in ('authorized', 'experimental_neural_level', 'save_crops'):
            if key in row and type(row[key]) is not bool:
                raise ValueError(f'{key} must be an explicit boolean')
        for key, default, low, high in [('count',3,1,60), ('interval',15,5,300), ('start',0,0,86400),
                ('timeout',20,1,30), ('max_age',15,1,30), ('ocr_timeout',10,1,30)]:
            n = row.get(key, default)
            if type(n) not in (int,float) or not math.isfinite(n) or not low <= n <= high or key=='count' and type(n) is not int:
                raise ValueError(f'{key} must be bounded to {low}..{high}')
        if row['source'] == 'file' and (not isinstance(row.get('file'), str) or not row['file']):
            raise ValueError('Local video needs an explicit file path')
        result.append({**row, 'channel': channel.lower()})
    return database, port, result


@contextmanager
def ownership(database):
    """A local provenance marker and OS-released lock; never adopt a single-stream DB."""
    marker = database.with_suffix(database.suffix+'.multi-alpha.json')
    if database.exists() and not marker.exists() or marker.exists() and not database.exists():
        raise ValueError('Database ownership mismatch; choose a NEW shared database, do not import a single-stream DB')
    database.parent.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        with marker.open('x', encoding='utf-8') as f:
            json.dump(dict(application=APP), f)
    with marker.open('r+b') as handle:
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
            raise ValueError('Another coordinator owns this shared database') from None
        try:
            info = json.load(handle)
            if not isinstance(info,dict) or info.get('application') != APP:
                raise ValueError('Not a multi-alpha database marker')
            yield
        finally:
            handle.seek(0)
            release()


def initialize(database, streams, say=print):
    # Inspect every existing selection before making any assignment changes.
    if database.exists():
        with Store(database, read_only=True) as store:
            for row in streams:
                found = store.db.execute('SELECT selected_character_id FROM streamers WHERE login=?', (row['channel'],)).fetchone()
                if found and found[0] is not None:
                    label = store.db.execute('SELECT label FROM characters WHERE id=?', (found[0],)).fetchone()[0]
                    if label != row['character']:
                        raise ValueError(f"Character mismatch for {row['channel']}: selected {label!r}; requested {row['character']!r}. Use explicit administration.")
    with Store(database) as store:
        for row in streams:
            store.add_channel(row['channel'])
            character = store.add_character(row['channel'], row['character'])
            store.select_character(row['channel'], character, only_if_unselected=True)
            session = store.start_session(row['channel'], expected_character_id=character)
            row.update(character_id=character, session_id=session)
            say(f"Selected {row['channel']} / {row['character']!r} / session {session}")


def options(row, database, output):
    argv = ['--output', str(output), '--db', str(database)]
    argv += ['--file', row['file'], '--tracking-channel', row['channel']] if row['source']=='file' else ['--channel', row['channel']]
    for key in ('count','interval','start','timeout','max_age','ocr_timeout','quality'):
        if key in row:
            argv += ['--'+key.replace('_','-'), str(row[key])]
    for key in ('authorized','experimental_neural_level','save_crops'):
        if row.get(key): argv.append('--'+key.replace('_','-'))
    return shadow.parser().parse_args(argv)


def schedule(lanes, perform, emit, *, clock=time.monotonic, sleep=time.sleep):
    """No queue: one due-time per lane, rotating ties, elapsed slots skipped."""
    started, wall = clock(), datetime.now(timezone.utc)
    for lane in lanes:
        lane.update(due=started, attempts=0, frames=0, commits=0, stopped=False, interrupted=False, skipped=0)
    turn = 0
    try:
        while True:
            pending = [i for i,lane in enumerate(lanes) if not lane['stopped'] and lane['attempts'] < lane['args'].count]
            if not pending: break
            index = min(pending, key=lambda i: (lanes[i]['due'], (i-turn)%len(lanes)))
            lane = lanes[index]
            sleep(max(0, lane['due']-clock()))
            while lane['due']+lane['args'].interval <= clock():
                lane['due'] += lane['args'].interval
                lane['skipped'] += 1
            requested = utc(wall+timedelta(seconds=lane['due']-started))
            delay = max(0, clock()-lane['due'])
            number = lane['attempts']+1
            seek = lane['args'].start+clock()-started if lane['source'].kind=='file' else None
            try:
                record = perform(lane, number, seek)
            except KeyboardInterrupt:
                record = dict(type='attempt', trusted=False, current=False, index=number,
                    attempted_at=utc(), status='capture_failed', reasons=['operator_interrupted'],
                    source=dict(kind=lane['source'].kind, channel=lane['channel'] if lane['source'].kind=='twitch' else None))
                lane['interrupted'] = True
            except (OSError, ValueError, RuntimeError):
                record = dict(type='attempt', trusted=False, current=False, index=number,
                    attempted_at=utc(), status='capture_failed', reasons=['capture_process_failed'],
                    source=dict(kind=lane['source'].kind, channel=lane['channel'] if lane['source'].kind=='twitch' else None))
            record.update(requested_at=requested, scheduler_delay_seconds=delay)
            lane['attempts'] = number
            lane['frames'] += record.get('received_at') is not None
            try:
                emit(lane, record)
            except (OSError, sqlite3.Error, ValueError):
                lane.update(stopped=True, interrupted=True, persistence_failed=True)
            if lane['interrupted'] and not lane.get('persistence_failed'):
                raise KeyboardInterrupt
            lane['due'] += lane['args'].interval
            while lane['due'] < clock():
                lane['due'] += lane['args'].interval
                lane['skipped'] += 1
            turn = (index+1)%len(lanes)
    except KeyboardInterrupt:
        for lane in lanes:
            if lane['attempts'] < lane['args'].count:
                lane['interrupted'] = True
        return True
    return False


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--config', type=Path, required=True)
    cli.add_argument('--check', action='store_true', help='Validate capture configuration without connecting or writing')
    cli.add_argument('--replay', action='append', default=[], metavar='CHANNEL=PRIVATE_LOG')
    cli.add_argument('--exit-after-capture', action='store_true')
    args = cli.parse_args(argv)
    httpd = thread = None
    try:
        database, port, streams = load_config(args.config)
        mappings = {}
        if args.replay:
            if args.check:
                raise ValueError('Choose either capture preflight or historical replay')
            mappings = dict(item.split('=',1) for item in args.replay)
            if set(mappings) != {row['channel'] for row in streams} or len(args.replay) != len(streams):
                raise ValueError('Replay needs exactly one CHANNEL=LOG for every configured channel')
            for path in mappings.values():
                if not private(path).is_file(): raise ValueError('Replay log not found')
        directory = private('private/multi-alpha/runs') / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
        lanes = []
        for row in streams:
            opts = options(row, database, directory/row['channel']/'capture.jsonl')
            if not args.replay:
                source, table_bytes, table, requirements = shadow.prepare(opts, allow_missing_video=True)
                lanes.append({**row, 'args': opts, 'source': source, 'requirements': requirements, 'table': table, 'table_bytes': table_bytes})
        if not args.replay:
            configure_tesseract()
            if any(row['source']=='twitch' for row in streams) and importlib.util.find_spec('streamlink') is None:
                raise ValueError('Existing capture extra (Streamlink) is missing')
            for lane in lanes:
                if lane['source'].kind=='file' and not Path(lane['source'].value).is_file():
                    print(f"{lane['channel']}: local video unavailable; bounded failed attempts will be retained, other channels continue",flush=True)
        if args.check:
            print('Preflight passed; no connections, database changes or capture started.')
            return 0
        print(f'Database: {database}',flush=True)
        if not args.replay: print(f'Private capture logs: {directory}',flush=True)
        with ownership(database):
            initialize(database, streams)
            httpd = create_server(database, port=port, diagnostic_dashboard=True)
            httpd.quiet = True
            httpd.active_run_ids = set()
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            print(f'Directory: http://127.0.0.1:{httpd.server_port}/streams', flush=True)
            if args.replay:
                with Store(database) as store:
                    for row in streams:
                        receipt = Diagnostics(store).replay(row['channel'], private(mappings[row['channel']]))
                        print(f"Replayed {row['channel']}: {receipt['inserted_records']} records; original timestamps unchanged", flush=True)
                interrupted = False
            else:
                os.environ['OMP_THREAD_LIMIT'] = '1'
                directory.mkdir(parents=True, exist_ok=False)
                with closing(ResourceMonitor(sample_interval=.05, scope='multi-alpha coordinator, HTTP and sequential capture/OCR children')) as monitor, Store(database) as store:
                    diagnostic = Diagnostics(store)
                    handles = []
                    try:
                        for lane, binding in zip(lanes, streams):
                            lane.update(character_id=binding['character_id'], session_id=binding['session_id'], run_id=uuid.uuid4().hex)
                            lane['args'].output.parent.mkdir(parents=True, exist_ok=False)
                            lane['log'] = lane['args'].output.open('x', encoding='utf-8'); handles.append(lane['log'])
                            header = shadow.configuration(lane['args'], lane['table_bytes'], lane['table'], lane['run_id'])
                            header.update(coordinator=APP, source_kind=lane['source'].kind)
                            lane['log'].write(json.dumps(header)+'\n'); lane['log'].flush()
                            binding = diagnostic.begin(lane['run_id'], lane['channel'], header)
                            if (binding['character_id'],binding['session_id']) != (lane['character_id'],lane['session_id']):
                                raise ValueError('Startup assignment changed; no capture started')
                            httpd.active_run_ids.add(lane['run_id'])
                        print('Capture RUNNING: one active job at a time, bounded per-channel attempts, no queued frames.',flush=True)
                        with (directory/'operator.jsonl').open('x',encoding='utf-8') as operator:
                            def emit(lane, record):
                                record['resources'] = monitor.snapshot()
                                lane['log'].write(json.dumps(record,allow_nan=False)+'\n'); lane['log'].flush()
                                committed = False
                                try:
                                    if record['type']=='summary' and lane.get('persistence_failed'):
                                        raise ValueError('Keep database run unfinished for explicit replay recovery')
                                    diagnostic.append(lane['run_id'], record)
                                    committed = True
                                    if record['type']=='attempt': lane['commits'] += 1
                                finally:
                                    operator.write(json.dumps(dict(channel=lane['channel'],index=record.get('index'),type=record['type'],sqlite_committed=committed))+'\n'); operator.flush()
                                    if record['type']=='attempt':
                                        print(report_attempt(record, committed, database=database, channel=lane['channel'],
                                            neural_enabled=lane['args'].experimental_neural_level).replace('#',lane['channel']+' #',1),flush=True)
                            interrupted = schedule(lanes, lambda lane,n,seek: shadow.capture_attempt(lane['args'],lane['source'],lane['requirements'],n,seek=seek),emit)
                            for lane in lanes:
                                try:
                                    emit(lane,dict(type='summary',trusted=False,attempts=lane['attempts'],interrupted=lane['interrupted'],skipped_deadlines=lane['skipped']))
                                except (OSError,ValueError,sqlite3.Error):
                                    print(f"{lane['channel']}: final SQLite summary NOT committed; inspect private logs",flush=True)
                                httpd.active_run_ids.discard(lane['run_id'])
                            print('Capture stopped. UNVERIFIED diagnostics only. Resources: '+json.dumps(monitor.snapshot()),flush=True)
                            for lane in lanes:
                                print(f"{lane['channel']}: {lane['frames']}/{lane['attempts']} frames, {lane['commits']} SQLite attempt commits; skipped deadlines={lane['skipped']}",flush=True)
                    finally:
                        httpd.active_run_ids.clear()
                        for handle in handles: handle.close()
            if not args.exit_after_capture and not interrupted:
                print('Capture is NOT running; localhost viewer remains open. Ctrl+C closes it.',flush=True)
                while thread.is_alive(): thread.join(.5)
            return 130 if interrupted else 1 if any(lane.get('persistence_failed') for lane in lanes) else 2 if lanes and not any(lane['frames'] for lane in lanes) else 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, sqlite3.Error) as error:
        print(f'Multi-alpha stopped: {error}',file=sys.stderr)
        return 1
    finally:
        if httpd:
            if thread and thread.is_alive():
                httpd.shutdown(); thread.join(timeout=2)
            httpd.server_close()


if __name__ == '__main__':
    raise SystemExit(main())
