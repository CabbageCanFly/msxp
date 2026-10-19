"""One bounded sequential shadow coordinator, shared SQLite and localhost directory."""

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import importlib.util
import hashlib
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


def load_config(path, *, offline_fast_test=False):
    path = private(path)
    if path.stat().st_size > 32768:
        raise ValueError('Configuration exceeds 32 KiB')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    database, port, streams = validate_config(value, offline_fast_test=offline_fast_test)
    active = [row for row in streams if row.get('enabled', True)]
    if not active:
        raise ValueError('No enabled assignments; enable a streamer or use the read-only server')
    return database, port, active


def validate_config(value, *, offline_fast_test=False):
    """Validate all assignments, including disabled ones; never initialize SQLite."""
    if not isinstance(value, dict) or set(value) - {'database', 'port', 'streams'}:
        raise ValueError('Expected database, port and streams configuration')
    streams = value.get('streams')
    if not isinstance(streams, list) or not 0 <= len(streams) <= 25:
        raise ValueError('Configure at most 25 explicit stream assignments')
    database = private(value.get('database', 'private/multi-alpha/tracking.sqlite3'))
    port = value.get('port', 8765)
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('port must be 0..65535')
    result, seen = [], set()
    for row in streams:
        allowed = {'channel', 'character', 'source', 'file', 'start', 'interval', 'count', 'authorized', 'enabled',
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
        if offline_fast_test and row.get('enabled', True) and row['source'] != 'file':
            raise ValueError('Offline fast testing requires ALL sources to be local video')
        for key in ('authorized', 'experimental_neural_level', 'save_crops', 'enabled'):
            if key in row and type(row[key]) is not bool:
                raise ValueError(f'{key} must be an explicit boolean')
        for key, default, low, high in [('count',3,1,60), ('interval',15,3 if offline_fast_test else 5,300), ('start',0,0,86400),
                ('timeout',20,1,30), ('max_age',15,1,30), ('ocr_timeout',10,1,30)]:
            n = row.get(key, default)
            if type(n) not in (int,float) or not math.isfinite(n) or not low <= n <= high or key=='count' and type(n) is not int:
                raise ValueError(f'{key} must be bounded to {low}..{high}')
        if row['source'] == 'file' and (not isinstance(row.get('file'), str) or not row['file']):
            raise ValueError('Local video needs an explicit file path')
        if 'quality' in row:
            if not isinstance(row['quality'], str):
                raise ValueError('quality must be a named rendition')
            shadow.Source('twitch', channel, row['quality']).streamlink_command()
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


def check_assignments(database, streams):
    # Inspect every existing selection before making any assignment changes.
    if database.exists():
        with Store(database, read_only=True) as store:
            for row in streams:
                found = store.db.execute('SELECT selected_character_id FROM streamers WHERE login=?', (row['channel'],)).fetchone()
                if found and found[0] is not None:
                    label = store.db.execute('SELECT label FROM characters WHERE id=?', (found[0],)).fetchone()[0]
                    if label != row['character']:
                        raise ValueError(f"Character mismatch for {row['channel']}: selected {label!r}; requested {row['character']!r}. Review the coordinated rename workflow in docs/manual-exp-admin.md; do not create another character.")


def initialize(database, streams, say=print):
    check_assignments(database, streams)
    with Store(database) as store:
        for row in streams:
            store.add_channel(row['channel'])
            character = store.add_character(row['channel'], row['character'])
            store.select_character(row['channel'], character, only_if_unselected=True)
            session = store.start_session(row['channel'], expected_character_id=character)
            row.update(character_id=character, session_id=session)
            say(f"Selected {row['channel']} / {row['character']!r} / session {session}")
            unfinished = store.db.execute('SELECT COUNT(*) FROM diagnostic_runs WHERE session_id=? AND summary_json IS NULL',(session,)).fetchone()[0]
            if unfinished:
                say(f"{row['channel']}: preserved {unfinished} previous unfinished run(s); activity unknown. Starting a NEW run; progress will not bridge the restart.")


def options(row, database, output):
    argv = ['--output', str(output), '--db', str(database)]
    argv += ['--file', row['file'], '--tracking-channel', row['channel']] if row['source']=='file' else ['--channel', row['channel']]
    for key in ('count','interval','start','timeout','max_age','ocr_timeout','quality'):
        if key in row:
            argv += ['--'+key.replace('_','-'), str(row[key])]
    for key in ('authorized','experimental_neural_level','save_crops'):
        if row.get(key): argv.append('--'+key.replace('_','-'))
    return shadow.parser().parse_args(argv)


def schedule(lanes, perform, emit, *, clock=time.monotonic, sleep=time.sleep,
             continuous=False, max_attempts=None, stop_after_seconds=None, rotate=None,
             activity=None, active_runs=None, simulated=False):
    """No queue: one due-time per lane, rotating ties, elapsed slots skipped."""
    started, wall = clock(), datetime.now(timezone.utc)
    for lane in lanes:
        lane.update(due=started, attempts=0, run_attempts=0, frames=0, commits=0, stopped=False,
                    interrupted=False, skipped=0, capture_failures=0, ocr_failures=0, last_started=None,
                    elapsed_total=0,elapsed_count=0,duration_total=0,max_delay=0)
        if activity is not None:
            activity[lane['channel']]=dict(state='waiting',run_id=lane['run_id'],updated_at=utc(),
                next_due_at=utc(wall),requested_interval_seconds=lane['args'].interval)
    turn = 0
    try:
        while True:
            pending = [i for i,lane in enumerate(lanes) if not lane['stopped'] and
                (lane['attempts'] < (max_attempts if continuous else lane['args'].count)
                 if not continuous or max_attempts is not None else True)]
            if not pending: break
            index = min(pending, key=lambda i: (lanes[i]['due'], (i-turn)%len(lanes)))
            lane = lanes[index]
            if stop_after_seconds is not None and max(clock(),lane['due'])-started >= stop_after_seconds:
                break
            sleep(max(0, lane['due']-clock()))
            while lane['due']+lane['args'].interval <= clock():
                lane['due'] += lane['args'].interval
                lane['skipped'] += 1
            requested = utc(wall+timedelta(seconds=lane['due']-started))
            delay = max(0, clock()-lane['due'])
            if lane['run_attempts']==60:
                try:
                    if rotate is None: raise ValueError('Continuous scheduling requires a rotation operation')
                    rotate(lane)
                    lane['run_attempts']=0
                except (OSError,sqlite3.Error,ValueError):
                    lane.update(stopped=True,interrupted=True,persistence_failed=True)
                    if active_runs is not None: active_runs.discard(lane['run_id'])
                    if activity is not None:
                        activity[lane['channel']]=dict(state='stopped',run_id=lane['run_id'],
                            updated_at=utc(),reason='rotation_failed')
                    continue
            number = lane['run_attempts']+1
            seek = lane['args'].start+clock()-started if lane['source'].kind=='file' else None
            attempt_start=clock()
            if activity is not None:
                activity[lane['channel']]=dict(state='running',run_id=lane['run_id'],updated_at=utc(),
                    expected_completion_seconds=lane['args'].timeout+lane['args'].ocr_timeout+15)
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
            elapsed=None if lane['last_started'] is None else attempt_start-lane['last_started']
            record.update(requested_at=None if simulated else requested, scheduler_delay_seconds=delay,
                timing_mode='simulated' if simulated else 'real',
                actual_interval_seconds=elapsed,skipped_deadlines=lane['skipped'],
                coordinator_attempt_seconds=max(0,clock()-attempt_start))
            if simulated: record['simulated_scheduler_seconds']=attempt_start-started
            lane['last_started']=attempt_start
            if elapsed is not None:
                lane['elapsed_total']+=elapsed;lane['elapsed_count']+=1
            lane['duration_total']+=record['coordinator_attempt_seconds']
            lane['max_delay']=max(lane['max_delay'],delay)
            lane['run_attempts']=number
            lane['attempts'] += 1
            lane['frames'] += record.get('received_at') is not None
            lane['capture_failures'] += record.get('status')=='capture_failed'
            lane['ocr_failures'] += record.get('status') in ('recognition_failed','malformed_or_unavailable','unavailable')
            try:
                emit(lane, record)
            except (OSError, sqlite3.Error, ValueError):
                lane.update(stopped=True, interrupted=True, persistence_failed=True)
                if active_runs is not None: active_runs.discard(lane['run_id'])
            if lane['interrupted'] and not lane.get('persistence_failed'):
                raise KeyboardInterrupt
            lane['due'] += lane['args'].interval
            while lane['due'] < clock():
                lane['due'] += lane['args'].interval
                lane['skipped'] += 1
            turn = (index+1)%len(lanes)
            if activity is not None:
                done=lane['stopped'] or (lane['attempts']>=max_attempts if continuous and max_attempts is not None else lane['attempts']>=lane['args'].count if not continuous else False)
                activity[lane['channel']]=dict(state='stopped' if done else 'capture_failing' if record.get('status')=='capture_failed' else 'waiting',
                    run_id=lane['run_id'],updated_at=utc(),next_due_at=utc(wall+timedelta(seconds=lane['due']-started)),
                    skipped_deadlines=lane['skipped'],requested_interval_seconds=lane['args'].interval,
                    actual_interval_seconds=elapsed)
    except KeyboardInterrupt:
        for lane in lanes:
            if continuous or lane['attempts'] < lane['args'].count:
                lane['interrupted'] = True
        return True
    return False


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--config', type=Path, required=True)
    cli.add_argument('--check', action='store_true', help='Validate capture configuration without connecting or writing')
    cli.add_argument('--replay', action='append', default=[], metavar='CHANNEL=PRIVATE_LOG')
    cli.add_argument('--exit-after-capture', action='store_true')
    cli.add_argument('--continuous',action='store_true',help='Continue until Ctrl+C, rotating each channel at 60 attempts')
    cli.add_argument('--public-only',action='store_true',help='Serve only the public homepage, character pages and OBS overlay; developer routes return 404')
    cli.add_argument('--twitch-status',action='store_true',help='Opt in to cached official live status; requires local Twitch API environment credentials')
    cli.add_argument('--max-attempts',type=int,help='Continuous-mode stop condition, per channel (not per run)')
    cli.add_argument('--stop-after-seconds',type=float,help='Stop scheduling new work after real monotonic elapsed time')
    cli.add_argument('--offline-fast-test',action='store_true',help='Explicit local-video-only interval floor of 3 seconds')
    args = cli.parse_args(argv)
    httpd = thread = None
    try:
        if args.max_attempts is not None and (not args.continuous or not 1<=args.max_attempts<=1000000):
            raise ValueError('--max-attempts requires continuous mode and 1..1000000 attempts')
        if args.stop_after_seconds is not None and (not args.continuous or not math.isfinite(args.stop_after_seconds) or args.stop_after_seconds<=0):
            raise ValueError('--stop-after-seconds requires continuous mode and positive finite seconds')
        if args.replay and (args.continuous or args.offline_fast_test):
            raise ValueError('Historical replay cannot use continuous/fast-test capture settings')
        database, port, streams = load_config(args.config,offline_fast_test=args.offline_fast_test)
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
            if args.continuous: opts.count=60
            if not args.replay:
                source, table_bytes, table, requirements = shadow.prepare(opts, allow_missing_video=True,offline_fast_test=args.offline_fast_test)
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
            httpd = create_server(database, port=port, diagnostic_dashboard=not args.public_only,public_only=args.public_only,twitch_status=args.twitch_status,background=True)
            httpd.quiet = True
            httpd.active_run_ids = set()
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            print(f'Directory: http://127.0.0.1:{httpd.server_port}/streams', flush=True)
            if args.public_only: print('Public-only: developer diagnostics are disabled (404).', flush=True)
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
                    handles = {}
                    instance=uuid.uuid4().hex
                    try:
                        def open_run(lane, run_id, previous=None):
                            lane['run_id']=run_id
                            if previous:
                                lane['args'].output=directory/lane['channel']/run_id/'capture.jsonl'
                            lane['args'].output.parent.mkdir(parents=True, exist_ok=False)
                            lane['log'] = lane['args'].output.open('x', encoding='utf-8'); handles[lane['channel']]=lane['log']
                            header = shadow.configuration(lane['args'], lane['table_bytes'], lane['table'], lane['run_id'])
                            source=lane['source']
                            identity=(source.kind, str(Path(source.value).resolve()) if source.kind=='file' else source.value)
                            header.update(coordinator=APP,coordinator_instance=instance,
                                source_identity=hashlib.sha256(json.dumps(identity).encode()).hexdigest(),
                                source_kind=source.kind,start_reason='scheduled_rotation' if previous else 'process_start',
                                previous_run_id=previous,offline_fast_test=args.offline_fast_test,timing_mode='real')
                            lane['log'].write(json.dumps(header)+'\n'); lane['log'].flush()
                            return header
                        for lane, binding in zip(lanes, streams):
                            lane.update(character_id=binding['character_id'], session_id=binding['session_id'])
                            header=open_run(lane,uuid.uuid4().hex)
                            binding = diagnostic.begin(lane['run_id'], lane['channel'], header)
                            if (binding['character_id'],binding['session_id']) != (lane['character_id'],lane['session_id']):
                                raise ValueError('Startup assignment changed; no capture started')
                            httpd.active_run_ids.add(lane['run_id'])
                        print('Capture RUNNING: one active job at a time, bounded per-channel attempts, no queued frames.',flush=True)
                        with (directory/'operator.jsonl').open('x',encoding='utf-8') as operator:
                            def emit(lane, record):
                                if record['type']=='summary' and lane.get('rotation_failed'):
                                    raise ValueError('Rotation intent already logged; keep database run unfinished')
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
                                    operator.write(json.dumps(dict(channel=lane['channel'],run_id=lane['run_id'],
                                        index=record.get('index'),type=record['type'],sqlite_committed=committed,
                                        status=record.get('status'),reasons=record.get('reasons',[]),
                                        timings=record.get('timings',{})))+'\n'); operator.flush()
                                    if record['type']=='attempt':
                                        print(report_attempt(record, committed, database=database, channel=lane['channel'],
                                            neural_enabled=lane['args'].experimental_neural_level).replace('#',lane['channel']+' #',1),flush=True)
                            def rotate(lane):
                                previous=lane['run_id']; following=uuid.uuid4().hex
                                summary=dict(type='summary',trusted=False,attempts=60,interrupted=False,
                                    completion_reason='scheduled_rotation',next_run_id=following)
                                old,old_output=lane['log'],lane['args'].output
                                try:
                                    old.write(json.dumps(summary)+'\n');old.flush()
                                    header=open_run(lane,following,previous)
                                    diagnostic.rotate(previous,following,lane['channel'],summary,header)
                                except (OSError,sqlite3.Error,ValueError):
                                    lane['rotation_failed']=True
                                    if lane['log'] is not old: lane['log'].close()
                                    lane.update(run_id=previous,log=old)
                                    lane['args'].output=old_output
                                    handles[lane['channel']]=old
                                    operator.write(json.dumps(dict(type='lifecycle_failure',channel=lane['channel'],
                                        run_id=previous,proposed_run_id=following,state='stopped',
                                        reason='rotation_failed',sqlite_committed=False))+'\n');operator.flush()
                                    print(f"{lane['channel']}: rotation NOT committed; capture stopped for this channel; original run preserved, inspect private logs",flush=True)
                                    raise
                                else:
                                    old.close()
                                httpd.active_run_ids.discard(previous);httpd.active_run_ids.add(following)
                                print(f"{lane['channel']}: scheduled rotation after 60 committed attempts; session {lane['session_id']} retained",flush=True)
                            scheduler_options=dict(continuous=True,max_attempts=args.max_attempts,stop_after_seconds=args.stop_after_seconds,rotate=rotate) if args.continuous else {}
                            interrupted = schedule(lanes, lambda lane,n,seek: shadow.capture_attempt(lane['args'],lane['source'],lane['requirements'],n,seek=seek),emit,
                                activity=httpd.coordinator_status,active_runs=httpd.active_run_ids,**scheduler_options)
                            for lane in lanes:
                                try:
                                    emit(lane,dict(type='summary',trusted=False,attempts=lane['run_attempts'],interrupted=lane['interrupted'],skipped_deadlines=lane['skipped'],
                                        scheduling=dict(requested_interval_seconds=lane['args'].interval,
                                            actual_mean_interval_seconds=lane['elapsed_total']/lane['elapsed_count'] if lane['elapsed_count'] else None,
                                            mean_attempt_seconds=lane['duration_total']/lane['attempts'] if lane['attempts'] else None,
                                            max_delay_seconds=lane['max_delay'],total_attempts_this_process=lane['attempts'],
                                            capture_failures=lane['capture_failures'],ocr_failures=lane['ocr_failures'],committed_attempts=lane['commits']),
                                        completion_reason='operator_interrupted' if lane['interrupted'] else 'stop_condition' if args.continuous else 'bounded_complete'))
                                except (OSError,ValueError,sqlite3.Error):
                                    print(f"{lane['channel']}: final SQLite summary NOT committed; inspect private logs",flush=True)
                                httpd.active_run_ids.discard(lane['run_id'])
                                httpd.coordinator_status[lane['channel']]=dict(state='stopped',run_id=lane['run_id'],updated_at=utc())
                            print('Capture stopped. UNVERIFIED diagnostics only. Resources: '+json.dumps(monitor.snapshot()),flush=True)
                            for lane in lanes:
                                print(f"{lane['channel']}: {lane['frames']}/{lane['attempts']} frames, {lane['commits']} SQLite attempt commits; skipped deadlines={lane['skipped']}; capture failures={lane['capture_failures']}, OCR failures={lane['ocr_failures']}",flush=True)
                                if lane['elapsed_count']: print(f"{lane['channel']}: requested {lane['args'].interval:.3f}s / actual mean start-to-start {lane['elapsed_total']/lane['elapsed_count']:.3f}s; mean work {lane['duration_total']/lane['attempts']:.3f}s",flush=True)
                                if lane['skipped']: print(f"{lane['channel']}: requested {lane['args'].interval}s cadence NOT sustained; inspect actual_interval_seconds and stage durations",flush=True)
                    finally:
                        httpd.active_run_ids.clear()
                        httpd.coordinator_status.clear()
                        for handle in handles.values(): handle.close()
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
