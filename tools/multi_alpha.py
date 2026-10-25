"""One bounded sequential shadow coordinator, shared SQLite and localhost directory."""

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import functools
import importlib.util
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import socket
import sqlite3
import sys
import threading
import time
import uuid

import shadow_capture as shadow
from exp_tracker.diagnostic_evidence import CONFIRM_GAP_SECONDS
from exp_tracker.diagnostics import Diagnostics, identity_held
from exp_tracker.metrics import ResourceMonitor
from exp_tracker.recognition import configure_tesseract
from exp_tracker.server import CHANNEL, create_server
from exp_tracker.store import Store, utc
from exp_tracker.retention_files import OperatorLog
from exp_tracker.writer_lock import writer_lease
from local_alpha import report_attempt

APP = 'multi_alpha_v1'
# Ceiling is half the two-frame gap so jittered consecutive frames confirm with margin.
LIVE_TRIAL_INTERVAL = (15, CONFIRM_GAP_SECONDS/2)


def private(path):
    return shadow.private_path(Path(path))


def load_config(path, *, offline_fast_test=False, existing_tracker=False):
    path = Path(path).resolve() if existing_tracker else private(path)
    root = None
    if existing_tracker:
        roots = [p.parent for p in path.parents if p.name in ('private','artifacts')]
        if not roots:raise ValueError('Existing tracker config must remain under its checkout private/ or artifacts/')
        root = roots[0]
    if path.stat().st_size > 32768:
        raise ValueError('Configuration exceeds 32 KiB')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    database, port, streams = validate_config(value, offline_fast_test=offline_fast_test,existing_root=root)
    active = [row for row in streams if row.get('enabled', True)]
    if not active:
        raise ValueError('No enabled assignments; enable a streamer or use the read-only server')
    return database, port, active


def validate_config(value, *, offline_fast_test=False, existing_root=None):
    """Validate all assignments, including disabled ones; never initialize SQLite."""
    if not isinstance(value, dict) or set(value) - {'database', 'port', 'streams'}:
        raise ValueError('Expected database, port and streams configuration')
    streams = value.get('streams')
    if not isinstance(streams, list):
        raise ValueError('Configure a list of explicit stream assignments')
    requested = Path(value.get('database', 'private/multi-alpha/tracking.sqlite3'))
    database = (existing_root/requested).resolve() if existing_root else private(requested)
    if existing_root and not any(database.is_relative_to(existing_root/name) for name in ('private','artifacts')):
        raise ValueError('Existing tracker database must remain under its config checkout private/ or artifacts/')
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


def owner_info(database, automatic, trial=None, existing=()):
    """Read-only ownership preflight; never adopt or migrate another writer's DB."""
    marker = database.with_suffix(database.suffix+'.multi-alpha.json')
    if database.exists() != marker.exists():
        raise ValueError('Database ownership mismatch; choose a NEW shared database, do not import a single-stream DB')
    if not marker.exists():return
    try:info = json.loads(marker.read_text(encoding='utf-8'))
    except PermissionError:raise ValueError('Cannot inspect ownership marker; another coordinator may own this database') from None
    if not isinstance(info,dict) or info.get('application') != APP:
        raise ValueError('Not a multi-alpha database marker')
    if existing:
        from exp_tracker.automatic_adoption import ownership as adopted_owner, states
        adopted_owner(database)
        with Store(database,read_only=True) as store:
            if store.schema_version not in (10,11) or not set(existing)<=states(store).keys():
                raise ValueError('Existing automatic channels require reviewed adoption first; use tools/adopt_automatic.py')
    if automatic and info.get('automatic_characters') is not True:
        raise ValueError('Automatic testing requires a NEW disposable database or its own prior automatic-test database')
    if trial is not None:
        if any(info.get(key)!=value for key,value in trial.items()) or info.get('automatic_characters',False)!=automatic:
            raise ValueError('Live trial requires a NEW disposable DB/marker or the exact prior live trial; do not adopt another database')
        from exp_tracker.schema import VERSION
        with Store(database,read_only=True) as store:
            if store.schema_version!=VERSION:
                raise ValueError('Live trial restart will not migrate an older database; use a NEW trial')
    elif info.get('live_twitch_trial'):
        raise ValueError('Restart this live trial with its explicit character-name/automatic flags and isolated settings')


def live_trial(args, database, port, streams):
    if getattr(args,'automatic_existing_channel',None):return None  # Separately adopted, never relax trial ownership.
    if not args.character_names or not any(row['source']=='twitch' for row in streams):return None
    root = private('private/character-live-trial')
    logs = private(args.log_root) if args.log_root else None
    if (not database.is_relative_to(root) or database.parent==root or
            private(args.config).parent!=database.parent or logs is None or logs==database.parent or
            not logs.is_relative_to(database.parent) or logs in (database,args.config.resolve())):
        raise ValueError('Live name trials require a NEW private/character-live-trial/TRIAL/ database, config beside it, and explicit --log-root inside that trial')
    if database.exists() and database.stat().st_nlink>1:
        raise ValueError('Hard-linked databases cannot isolate WAL and ownership markers')
    if port==8765:raise ValueError('Live trial cannot use the default main port 8765; choose a separate port (e.g. 8879)')
    if (len(streams)>2 or any(row['source']!='twitch' or not row.get('authorized') for row in streams)
            or args.workers!=1 or args.retention_24h or args.hud_cache_seconds):
        raise ValueError('Initial live name trial requires 1..2 authorized Twitch channels, one worker, no retention and no HUD cache')
    low, high = LIVE_TRIAL_INTERVAL
    if any(not low<=row.get('interval',15)<=high for row in streams):
        raise ValueError(f'Live name trial interval must be {low:g}..{high:g} seconds: two-frame confirmation '
                         f'needs consecutive name frames at most {CONFIRM_GAP_SECONDS:g} seconds apart')
    return dict(live_twitch_trial=True,database=str(database),channels=sorted(row['channel'] for row in streams))


def available_port(port, *, existing=False):
    # A preflight probe, not a reservation; the actual HTTP bind still precedes all capture.
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as probe:
        if os.name=='nt':probe.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        try:probe.bind(('127.0.0.1',port))
        except OSError:
            advice = 'an existing tracker may still own it; no capture started, wait for an operator-approved stop' if existing else 'leave the main tracker alone and choose another trial port'
            raise ValueError(f'Localhost port {port} is unavailable; {advice}') from None


@contextmanager
def ownership(database, *, automatic=False, trial=None, existing=(), adopted=False):
    """A local provenance marker and OS-released lock; never adopt a single-stream DB."""
    marker = database.with_suffix(database.suffix+'.multi-alpha.json')
    owner_info(database,automatic,trial,existing)
    database.parent.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        with marker.open('x', encoding='utf-8') as f:
            json.dump(dict(application=APP,**({'automatic_characters':True} if automatic else {}),**(trial or {})), f)
    with writer_lease(marker) as handle:
        info = json.load(handle)
        if not isinstance(info,dict) or info.get('application') != APP:
            raise ValueError('Not a multi-alpha database marker')
        if (adopted or existing) and (info.get('automatic_characters') or info.get('live_twitch_trial')):
            raise ValueError('Existing tracker mode cannot adopt a trial ownership marker')
        if automatic and info.get('automatic_characters') is not True:
            raise ValueError('Automatic testing requires a NEW disposable database or its own prior automatic-test database')
        if trial is not None and any(info.get(key)!=value for key,value in trial.items()):
            raise ValueError('Live trial ownership changed before acquiring the writer lease')
        yield


def check_assignments(database, streams):
    # Inspect every existing selection before making any assignment changes.
    if database.exists():
        with Store(database, read_only=True) as store:
            from exp_tracker.automatic_adoption import states
            adopted=states(store)
            for row in streams:
                found = store.db.execute('SELECT selected_character_id FROM streamers WHERE login=?', (row['channel'],)).fetchone()
                if found and found[0] is not None:
                    label = store.db.execute('SELECT label FROM characters WHERE id=?', (found[0],)).fetchone()[0]
                    if label != row['character'] and row['channel'] not in adopted:
                        raise ValueError(f"Character mismatch for {row['channel']}: selected {label!r}; requested {row['character']!r}. Review the coordinated rename workflow in docs/manual-exp-admin.md; do not create another character.")


def initialize(database, streams, say=print, *, automatic=False, allow_migration=True):
    if not automatic: check_assignments(database, streams)
    with Store(database,allow_migration=allow_migration) as store:
        from exp_tracker.automatic_adoption import states
        adopted=states(store)
        for row in streams:
            store.add_channel(row['channel'])
            selected=store._channel(row['channel'])['selected_character_id']
            character = selected if (automatic or row['channel'] in adopted) and selected is not None else store.add_character(row['channel'], row['character'])
            store.select_character(row['channel'], character, only_if_unselected=True)
            session = store.start_session(row['channel'], expected_character_id=character)
            row.update(character_id=character, session_id=session,
                       character=store.db.execute('SELECT label FROM characters WHERE id=?',(character,)).fetchone()[0])
            say(f"Selected {row['channel']} / {row['character']!r} / session {session}")
            unfinished = store.db.execute('SELECT COUNT(*) FROM diagnostic_runs WHERE session_id=? AND summary_json IS NULL',(session,)).fetchone()[0]
            if unfinished:
                say(f"{row['channel']}: preserved {unfinished} previous unfinished run(s); activity unknown. Starting a NEW run; existing identity/level guards and rolling-window endpoint rules still apply.")


def existing_preflight(database, streams, enabled, *, required=False):
    """No adoption at startup; persist selections even after automation is disabled."""
    from exp_tracker.automatic_adoption import states
    if not database.exists():
        if enabled or required:raise ValueError('Existing automatic mode requires an adopted existing database')
        return
    with Store(database,read_only=True) as store:
        adopted=states(store)
        if required and (store.schema_version not in (10,11) or not adopted):
            raise ValueError('Existing tracker mode requires reviewed adoption before startup')
        if not adopted and not enabled:return
        configured={row['channel']:row for row in streams}
        if not set(enabled)<=configured.keys() or not set(enabled)<=adopted.keys():
            raise ValueError('Explicit automatic channels must be enabled in config and individually adopted')
        for login,value in adopted.items():
            if login in configured and login not in enabled and value['started'] and (not value['verified'] or value['risk']):
                raise ValueError(f'{login}: unresolved adopted identity; resume automatic verification before disabling it')
        for login in enabled:
            row=configured[login]
            if row['source']=='twitch' and not row.get('authorized'):
                raise ValueError('Existing automatic Twitch channels require explicit capture authorization')
            if row.get('interval',15)>CONFIRM_GAP_SECONDS/2:
                raise ValueError('Automatic channel interval must allow two independent frames within 120 seconds (use <=60s)')
        check_assignments(database,streams)


def options(row, database, output):
    argv = ['--output', str(output), '--db', str(database)]
    argv += ['--file', row['file'], '--tracking-channel', row['channel']] if row['source']=='file' else ['--channel', row['channel']]
    for key in ('count','interval','start','timeout','max_age','ocr_timeout','quality'):
        if key in row:
            argv += ['--'+key.replace('_','-'), str(row[key])]
    for key in ('authorized','experimental_neural_level','save_crops'):
        if row.get(key): argv.append('--'+key.replace('_','-'))
    return shadow.parser().parse_args(argv)


def category_gate(lanes, availability=None, *, seconds=60, any_category=False):
    """Check broadcast/category once a minute in the background; unknown or expired status allows capture."""
    from exp_tracker.twitch_auth import AppTokens
    from exp_tracker.twitch_probe import StreamAvailability, capture_paused
    availability=availability or StreamAvailability(enabled=True,auth=AppTokens(maintain=True))
    statuses={}
    def refresh():
        while True:
            try:statuses.update(availability.snapshot(sorted({l['channel'] for l in list(lanes) if l['source'].kind=='twitch'})))
            except (OSError,ValueError):pass
            time.sleep(seconds)
    threading.Thread(target=refresh,name='twitch-category',daemon=True).start()
    return lambda lane:lane['source'].kind=='twitch' and capture_paused(statuses.get(lane['channel']),
        now=datetime.now(timezone.utc),any_category=any_category)


def schedule(lanes, perform, emit, *, clock=time.monotonic, sleep=time.sleep,
             continuous=False, max_attempts=None, stop_after_seconds=None, rotate=None,
             activity=None, active_runs=None, simulated=False, maintain=None, workers=1, reconcile=None, stagger=False, gate=None):
    """No queue: one due-time per lane, rotating ties, elapsed slots skipped.

    workers>1 runs that many lanes' attempts at once, never two for one lane. Rotation,
    emit (logs and the single SQLite writer), status and maintain (retention) stay on this thread.
    stagger=True only moves first due times: a batch started with no other active lane puts
    lane i at i/len(batch) of ITS OWN interval; a lane added beside active lanes (roster add,
    resume or change) takes the middle of the widest gap in their upcoming due times, so
    their cadence is untouched and new work does not cluster.
    gate(lane) True holds a lane (e.g. live outside MapleStory); it resumes on time, without counting held slots as skipped.
    """
    started, wall = clock(), datetime.now(timezone.utc)
    totals={}
    total_fields=('attempts','frames','commits','skipped','capture_failures','ocr_failures','last_started',
                  'elapsed_total','elapsed_count','duration_total','max_delay')
    def initialize_lane(lane, due):
        lane.update(due=due, attempts=0, run_attempts=0, frames=0, commits=0, stopped=False,_scheduled=True,
                    interrupted=False, skipped=0, capture_failures=0, ocr_failures=0, last_started=None,
                    elapsed_total=0,elapsed_count=0,duration_total=0,max_delay=0)
        if reconcile:lane.update(totals.get(lane['channel'],{}))
        if activity is not None:
            activity[lane['channel']]=dict(state='waiting',run_id=lane['run_id'],updated_at=utc(),
                next_due_at=utc(wall+timedelta(seconds=due-started)),requested_interval_seconds=lane['args'].interval)
    def widest_gap(now, interval, others):
        # Fold every other lane's slots over the longest interval onto the new lane's period,
        # so each of its future slots, not only the first, avoids them.
        horizon=now+max(interval,*(other['args'].interval for other in others))
        points=[]
        for other in others:
            step=other['args'].interval;due=other['due']
            due+=max(0,math.ceil((now-due)/step))*step  # Next slot on that lane's own grid.
            # That next slot always counts, even exactly on (or rounded past) the horizon.
            points.append((due-now)%interval);due+=step
            while due<horizon:points.append((due-now)%interval);due+=step
        points.sort()
        gaps=[(b-a,(a+b)/2%interval) for a,b in zip(points,points[1:]+[points[0]+interval])]
        return now+max(gaps,key=lambda gap:(gap[0],-gap[1]))[1]  # Widest; the soonest among equals.
    def place(new):
        now=clock()
        others=[lane for lane in lanes if lane.get('_scheduled') and not lane['stopped'] and not lane.get('paused')]
        for index,lane in enumerate(new):
            interval=lane['args'].interval
            if not stagger:due=now
            elif not others:due=now+index*interval/len(new)
            else:due=widest_gap(now,interval,others)
            initialize_lane(lane,due)
            if stagger and others:others.append(lane)
    place(lanes)
    turn = 0
    running = {}
    results = queue.Queue()

    def failure(lane, number, reason):
        return dict(type='attempt', trusted=False, current=False, index=number,
            attempted_at=utc(), status='capture_failed', reasons=[reason],
            source=dict(kind=lane['source'].kind, channel=lane['channel'] if lane['source'].kind=='twitch' else None))

    def begin(lane):
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
                return None
        number = lane['run_attempts']+1
        seek = lane['args'].start+clock()-started if lane['source'].kind=='file' else None
        if activity is not None:
            activity[lane['channel']]=dict(state='running',run_id=lane['run_id'],updated_at=utc(),
                expected_completion_seconds=lane['args'].timeout+lane['args'].ocr_timeout+15)
        return dict(lane=lane, number=number, seek=seek, requested=requested, delay=delay, start=clock())

    def attempt(job):
        lane, number = job['lane'], job['number']
        try:
            record, interrupted = perform(lane, number, job['seek']), False
        except KeyboardInterrupt:
            record, interrupted = failure(lane, number, 'operator_interrupted'), True
        except (OSError, ValueError, RuntimeError):
            record, interrupted = failure(lane, number, 'capture_process_failed'), False
        job['seconds'] = max(0, clock()-job['start'])
        return record, interrupted

    def worker(job):
        try:
            results.put((job, *attempt(job), None))
        except BaseException as error:  # Re-raised on the coordinator thread, as the serial path would.
            results.put((job, None, False, error))

    def finish(job, record, interrupted, error=None):
        lane, number, attempt_start = job['lane'], job['number'], job['start']
        running.pop(lane['channel'], None)
        if error is not None: raise error
        if interrupted: lane['interrupted'] = True
        elapsed=None if lane['last_started'] is None else attempt_start-lane['last_started']
        record.update(requested_at=None if simulated else job['requested'], scheduler_delay_seconds=job['delay'],
            timing_mode='simulated' if simulated else 'real',
            actual_interval_seconds=elapsed,skipped_deadlines=lane['skipped'],
            coordinator_attempt_seconds=job['seconds'])
        if simulated: record['simulated_scheduler_seconds']=attempt_start-started
        lane['last_started']=attempt_start
        if elapsed is not None:
            lane['elapsed_total']+=elapsed;lane['elapsed_count']+=1
        lane['duration_total']+=record['coordinator_attempt_seconds']
        lane['max_delay']=max(lane['max_delay'],job['delay'])
        lane['run_attempts']=number
        lane['attempts'] += 1
        lane['frames'] += record.get('received_at') is not None
        lane['last_attempt_at']=record.get('received_at') or record.get('attempted_at')
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
        if activity is not None:
            done=lane['stopped'] or (lane['attempts']>=max_attempts if continuous and max_attempts is not None else lane['attempts']>=lane['args'].count if not continuous else False)
            activity[lane['channel']]=dict(state='stopped' if done else 'capture_failing' if record.get('status')=='capture_failed' else 'waiting',
                run_id=lane['run_id'],updated_at=utc(),next_due_at=utc(wall+timedelta(seconds=lane['due']-started)),
                skipped_deadlines=lane['skipped'],requested_interval_seconds=lane['args'].interval,
                actual_interval_seconds=elapsed)
        if reconcile:totals[lane['channel']]={key:lane[key] for key in total_fields}

    def collect(timeout):
        # Short waits keep Ctrl+C responsive on Windows, where a blocked Queue.get ignores it.
        deadline = time.monotonic()+timeout
        while True:
            try:
                return finish(*results.get(timeout=max(0, min(.5, deadline-time.monotonic()))))
            except queue.Empty:
                if time.monotonic() >= deadline: return None

    stopping = False
    try:
        while True:
            if stop_after_seconds is not None and clock()-started>=stop_after_seconds:stopping=True
            if reconcile and not stopping:
                reconcile(set(running),clock())
                place([lane for lane in lanes if not lane.get('_scheduled')])
            if maintain:maintain()
            if gate:
                for lane in lanes:
                    held=gate(lane)
                    if lane.get('gated') and not held:lane['due']=max(lane['due'],clock())
                    lane['gated']=held
            pending = [] if stopping or len(running) >= workers else [
                i for i,lane in enumerate(lanes) if not lane['stopped'] and not lane.get('paused') and not lane.get('gated') and lane['channel'] not in running and
                (lane['attempts'] < (max_attempts if continuous else lane['args'].count)
                 if not continuous or max_attempts is not None else True)]
            if not pending:
                if not running:
                    if (reconcile or gate and any(l.get('gated') for l in lanes)) and not stopping and max_attempts is None:
                        sleep(1);continue
                    break
                collect(1 if reconcile else math.inf)
                continue
            index = min(pending, key=lambda i: (lanes[i]['due'], (i-turn)%len(lanes)))
            lane = lanes[index]
            if stop_after_seconds is not None and max(clock(),lane['due'])-started >= stop_after_seconds:
                stopping = True
                continue
            if lane['due'] > clock() and (running or reconcile):
                delay=min(1,lane['due']-clock()) if reconcile else lane['due']-clock()
                if running:collect(delay)
                else:sleep(delay)
                continue
            sleep(max(0, lane['due']-clock()))
            job = begin(lane)
            if job is None: continue
            turn = (index+1)%len(lanes)
            running[lane['channel']] = job
            if workers == 1:
                finish(job, *attempt(job))
            else:
                threading.Thread(target=worker, args=(job,), daemon=True).start()
    except KeyboardInterrupt:
        # Discard in-flight results, as a serial interrupt would; their children end with the process.
        for job in list(running.values()):
            job.setdefault('seconds', max(0, clock()-job['start']))
            try:
                finish(job, failure(job['lane'], job['number'], 'operator_interrupted'), True)
            except KeyboardInterrupt:
                pass
        for lane in lanes:
            if continuous or lane['attempts'] < lane['args'].count:
                lane['interrupted'] = True
        return True
    return False


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    source_config=cli.add_mutually_exclusive_group(required=True)
    source_config.add_argument('--config', type=Path)
    source_config.add_argument('--db-roster',type=Path,help='Use the explicitly bootstrapped database roster; no JSON or automatic-channel flags')
    cli.add_argument('--port',type=int,default=8766,help='Public localhost port for --db-roster; existing JSON mode uses its config port')
    cli.add_argument('--check', action='store_true', help='Validate capture configuration without connecting or writing')
    cli.add_argument('--capture-only',action='store_true',help='Database-roster coordinator without HTTP or publisher; retains the exclusive writer lease')
    cli.add_argument('--runtime-state',type=Path,help='Private heartbeat file for --capture-only and the separate read-only API')
    cli.add_argument('--publication-cache',type=Path,help='Separate disposable publisher cache for bundled HTTP mode')
    cli.add_argument('--replay', action='append', default=[], metavar='CHANNEL=PRIVATE_LOG')
    cli.add_argument('--exit-after-capture', action='store_true')
    cli.add_argument('--continuous',action='store_true',help='Continue until Ctrl+C, rotating each channel at 60 attempts')
    cli.add_argument('--retention-24h',action='store_true',help='Removed: retention runs separately (python -m exp_tracker.retention --apply)')
    cli.add_argument('--public-only',action='store_true',help='Serve only the public homepage, character pages and OBS overlay; developer routes return 404')
    cli.add_argument('--cors-origin',action='append',default=[],metavar='ORIGIN',help='Exact frontend origin allowed to read the API, e.g. https://msxp.pages.dev; repeatable')
    cli.add_argument('--twitch-status',action='store_true',help='Opt in to cached official live status; requires local Twitch API environment credentials')
    cli.add_argument('--any-category',action='store_true',help='Keep capturing Twitch streams live in any category; by default continuous capture pauses outside MapleStory')
    cli.add_argument('--max-attempts',type=int,help='Continuous-mode stop condition, per channel (not per run)')
    cli.add_argument('--stop-after-seconds',type=float,help='Stop scheduling new work after real monotonic elapsed time')
    cli.add_argument('--offline-fast-test',action='store_true',help='Explicit local-video-only interval floor of 3 seconds')
    cli.add_argument('--workers',type=int,default=1,help='Concurrent capture/OCR attempts, 1..8 (one per channel at a time); SQLite stays single-writer. Above 4 is not yet validated on the VPS')
    cli.add_argument('--stagger-capture',action='store_true',help='Spread first captures across each channel interval instead of starting all channels at once; roster additions take the widest free gap. Off by default')
    cli.add_argument('--hud-cache-seconds',type=float,default=0,help='Search near a unique full-frame HUD for up to this long before a full rescan; 0 disables. A new competing HUD goes unseen until then')
    cli.add_argument('--resident-neural',action='store_true',help='Reuse one neural worker process instead of starting one per attempt')
    cli.add_argument('--resident-tesseract',action='store_true',help='Reuse isolated native libtesseract worker processes (at most min(workers, 4)) instead of one tesseract CLI process per OCR call; off by default')
    cli.add_argument('--preload-streamlink',action='store_true',default=os.environ.get('MSXP_PRELOAD_STREAMLINK')=='1',
        help='Linux: preload Streamlink imports, keeping a fresh CLI process per capture; also MSXP_PRELOAD_STREAMLINK=1. Off by default')
    cli.add_argument('--ocr-python',type=Path,help='Reuse the existing isolated OCR Python, including at its original checkout path')
    cli.add_argument('--log-root',type=Path,help='Private root for new per-process capture directories; required for isolated live name trials')
    cli.add_argument('--character-names',action='store_true',help='Opt in to own-name evidence/holds; Twitch requires isolated live trial settings; implies --resident-neural')
    cli.add_argument('--automatic-characters',action='store_true',help='NEW disposable DB only: automatically switch after two strong independent full-frame name readings; local video or isolated authorized Twitch trial')
    cli.add_argument('--automatic-existing-channel',action='append',default=[],metavar='CHANNEL',
        help='Enable automation ONLY for this reviewed/adopted existing channel; repeat for more channels, omit to disable')
    cli.add_argument('--existing-tracker',action='store_true',
        help='Use a reviewed/adopted existing tracker config/database, including another checkout private path; required there even when automation is disabled')
    args = cli.parse_args(argv)
    httpd = thread = streamlink = None
    try:
        db_mode=args.db_roster is not None
        if args.capture_only:
            if not db_mode or not args.continuous or not args.runtime_state:
                raise ValueError('--capture-only requires --db-roster, --continuous and --runtime-state')
            if args.public_only or args.cors_origin or args.twitch_status or args.publication_cache:
                raise ValueError('HTTP, CORS, Twitch status and publication cache belong to the separate API in capture-only mode')
            args.exit_after_capture=True
        elif args.runtime_state:
            raise ValueError('--runtime-state requires --capture-only in the coordinator')
        existing=args.automatic_existing_channel
        existing_mode=args.existing_tracker or bool(existing)
        if (len(set(existing))!=len(existing) or any(not CHANNEL.fullmatch(c) or c!=c.lower() for c in existing)):
            raise ValueError('Existing automatic channels must be distinct lowercase Twitch logins')
        if existing_mode and (args.automatic_characters or args.character_names or args.replay or existing and args.hud_cache_seconds):
            raise ValueError('Existing automatic mode cannot combine with trial/name-only flags, replay or HUD cache')
        if args.automatic_characters:
            args.character_names=True
            if args.replay or args.hud_cache_seconds:
                raise ValueError('Automatic testing requires capture with full-frame HUD localization, not replay/cache')
        if db_mode and (not args.continuous or existing_mode or args.character_names or args.automatic_characters
                        or args.replay or args.offline_fast_test or args.hud_cache_seconds):
            raise ValueError('Database roster requires --continuous and fresh full-frame capture; no JSON/trial/automatic-channel/cache flags')
        if args.retention_24h:
            # Inline cleanup froze capture for 19-41 s per round (docs/retention-capture-interference.md).
            raise ValueError('--retention-24h no longer runs inside the coordinator; run '
                             'python -m exp_tracker.retention --db <database> --apply --log-root <log root> separately')
        if not 1<=args.workers<=8:
            raise ValueError('--workers must be 1..8')
        if not math.isfinite(args.hud_cache_seconds) or not 0<=args.hud_cache_seconds<=3600:
            raise ValueError('--hud-cache-seconds must be 0..3600')
        if args.max_attempts is not None and (not args.continuous or not 1<=args.max_attempts<=1000000):
            raise ValueError('--max-attempts requires continuous mode and 1..1000000 attempts')
        if args.stop_after_seconds is not None and (not args.continuous or not math.isfinite(args.stop_after_seconds) or args.stop_after_seconds<=0):
            raise ValueError('--stop-after-seconds requires continuous mode and positive finite seconds')
        if args.replay and (args.continuous or args.offline_fast_test):
            raise ValueError('Historical replay cannot use continuous/fast-test capture settings')
        if args.replay and args.preload_streamlink:
            raise ValueError('Preloaded Streamlink requires capture, not historical replay')
        if db_mode:
            from exp_tracker import streamer_roster as roster
            from exp_tracker.automatic_adoption import ownership as adopted_owner
            database=args.db_roster.resolve(strict=True);port=args.port
            if not 0<=port<=65535:raise ValueError('port must be 0..65535')
            adopted_owner(database)
            with Store(database,read_only=True) as reader:
                desired=roster.entries(reader)
                for row in desired:roster.validate_policy(reader,row)
            streams=[dict(row,source='twitch',character='PendingOCR',count=60) for row in desired if row['tracking_enabled']]
            trial=None
            with writer_lease(database.with_suffix(database.suffix+'.multi-alpha.json')):pass
            if not args.capture_only:available_port(port,existing=True)
            if args.runtime_state:
                from exp_tracker.capture_runtime import validate_path
                validate_path(args.runtime_state,database)
        else:
            database, port, streams = load_config(args.config,offline_fast_test=args.offline_fast_test,existing_tracker=existing_mode)
            trial = live_trial(args,database,port,streams)
            if database.exists():
                from exp_tracker.streamer_roster import ready
                with Store(database,read_only=True) as reader:
                    if ready(reader):raise ValueError('Database roster is active; use --db-roster instead of overriding desired settings with JSON')
        if existing_mode:
            from exp_tracker.automatic_adoption import ownership as adopted_owner
            adopted_owner(database)
            owner_info(database,False,existing=existing)
            with writer_lease(database.with_suffix(database.suffix+'.multi-alpha.json')):pass
            available_port(port,existing=True)
        if not db_mode:existing_preflight(database,streams,existing,required=existing_mode)
        if trial is not None:
            owner_info(database,args.automatic_characters,trial)
            if database.exists():
                with writer_lease(database.with_suffix(database.suffix+'.multi-alpha.json')):pass
            available_port(port)
        mappings = {}
        if args.replay:
            if args.check:
                raise ValueError('Choose either capture preflight or historical replay')
            mappings = dict(item.split('=',1) for item in args.replay)
            if set(mappings) != {row['channel'] for row in streams} or len(args.replay) != len(streams):
                raise ValueError('Replay needs exactly one CHANNEL=LOG for every configured channel')
            for path in mappings.values():
                if not private(path).is_file(): raise ValueError('Replay log not found')
        directory = private(args.log_root or 'private/multi-alpha/runs') / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
        lanes = []
        def make_lane(row):
            output=directory/row['channel']/uuid.uuid4().hex/'capture.jsonl' if db_mode else directory/row['channel']/'capture.jsonl'
            opts = options(row, database, output)
            if args.ocr_python:opts.ocr_python=args.ocr_python.absolute()  # Never follow a venv's interpreter symlink.
            if args.continuous: opts.count=60
            if not args.replay:
                source, table_bytes, table, requirements = shadow.prepare(opts, allow_missing_video=True,offline_fast_test=args.offline_fast_test)
                # After prepare: its standalone no-DB guard does not apply, holds are enforced at emit/append.
                opts.automatic_characters=args.automatic_characters or row['channel'] in existing or db_mode and row['automatic_characters']
                opts.character_names=args.character_names or opts.automatic_characters
                return {**row, 'args': opts, 'source': source, 'requirements': requirements, 'table': table, 'table_bytes': table_bytes}
        for row in streams:
            if not args.replay:lanes.append(make_lane(row))
        native=None
        if not args.replay:
            configure_tesseract()
            if args.preload_streamlink:
                from exp_tracker.preloaded_streamlink import PreloadedStreamlink
                streamlink=PreloadedStreamlink();streamlink.check()
                print('Preloaded Streamlink: fresh CLI children via Linux forkserver.',flush=True)
            if args.resident_tesseract:
                from resident_tesseract import TesseractPool, worker_command
                preflight=TesseractPool(worker_command(),1)
                try:engine=preflight.check()  # Fails clearly here; no system changes.
                finally:preflight.close()
                native=dict(version=engine['version'],model_sha256=engine['model_sha256'],workers=min(args.workers,4))
                print(f"Resident Tesseract: libtesseract {native['version']}, model {native['model_sha256'][:12]}, up to {native['workers']} worker(s)",flush=True)
            if any(row['source']=='twitch' for row in streams) and importlib.util.find_spec('streamlink') is None:
                raise ValueError('Existing capture extra (Streamlink) is missing')
            for lane in lanes:
                if lane['source'].kind=='file' and not Path(lane['source'].value).is_file():
                    print(f"{lane['channel']}: local video unavailable; bounded failed attempts will be retained, other channels continue",flush=True)
        if args.check:
            owner_info(database,args.automatic_characters,trial,existing)
            if existing_mode:print('Existing tracker automatic channels: '+(', '.join(existing) or 'none (persisted selections preserved)'))
            print('Preflight passed; no connections, database changes or capture started.')
            return 0
        print(f'Database: {database}',flush=True)
        if not args.replay: print(f'Private capture logs: {directory}',flush=True)
        with ownership(database,automatic=args.automatic_characters,trial=trial,existing=existing,adopted=existing_mode or db_mode):
            if not db_mode:
                existing_preflight(database,streams,existing,required=existing_mode)
                initialize(database, streams,automatic=args.automatic_characters,allow_migration=trial is None and not existing_mode)
            else:lanes=[]  # Reconciliation initializes only desired active lanes on the writer thread.
            if args.capture_only:
                from exp_tracker.capture_runtime import CaptureRuntime
                httpd=CaptureRuntime(args.runtime_state,database)
                print('Capture-only: no HTTP listener or publisher; exclusive writer lease held.',flush=True)
            else:
                httpd = create_server(database, port=port, diagnostic_dashboard=not args.public_only,public_only=args.public_only,cors_origins=args.cors_origin,twitch_status=args.twitch_status,background=True,
                    **({'publication_cache':args.publication_cache} if args.publication_cache else {}))
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
                from exp_tracker.retention_files import own
                own(directory,database)  # Lets a separate retention worker expire this directory's files later.
                with closing(ResourceMonitor(sample_interval=1, scope=f'multi-alpha coordinator, HTTP and {args.workers}-worker capture/OCR children')) as monitor, Store(database,allow_migration=trial is None and not existing_mode and not db_mode) as store:
                    diagnostic = Diagnostics(store)
                    if args.automatic_characters or existing or db_mode:
                        from exp_tracker.character_automation import AutonomousCharacters
                        automation=AutonomousCharacters(store)
                    handles = {}
                    resident = shadow.ResidentNeural() if args.resident_neural or args.character_names or existing or db_mode else None
                    tesseract = TesseractPool(worker_command(),native['workers']) if native else None
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
                                previous_run_id=previous,offline_fast_test=args.offline_fast_test,timing_mode='real',
                                **({'stagger_capture':True} if args.stagger_capture else {}),
                                **({'resident_tesseract':native} if native else {}),
                                **({'preloaded_streamlink':True} if streamlink else {}))
                            if db_mode:header.update(database_roster=True,roster_revision=lane['roster_revision'])
                            lane['log'].write(json.dumps(header)+'\n'); lane['log'].flush()
                            return header
                        for lane, binding in zip(lanes, streams):
                            lane.update(character_id=binding['character_id'], session_id=binding['session_id'],character=binding['character'])
                            header=open_run(lane,uuid.uuid4().hex)
                            binding = diagnostic.begin(lane['run_id'], lane['channel'], header)
                            if (binding['character_id'],binding['session_id']) != (lane['character_id'],lane['session_id']):
                                raise ValueError('Startup assignment changed; no capture started')
                            httpd.active_run_ids.add(lane['run_id'])
                        print(f'Capture RUNNING: at most {args.workers} active job(s), one per channel, bounded per-channel attempts, no queued frames'
                              +(', first captures staggered across each interval.' if args.stagger_capture else '.'),flush=True)
                        with OperatorLog(directory) as operator:
                            def emit(lane, record):
                                if lane['args'].automatic_characters and record['type']=='attempt':
                                    record['resources']=monitor.snapshot()
                                    following=uuid.uuid4().hex
                                    header=shadow.configuration(lane['args'],lane['table_bytes'],lane['table'],following)
                                    old_header=json.loads(store.db.execute('SELECT configuration_json FROM diagnostic_runs WHERE run_id=?', (lane['run_id'],)).fetchone()[0])
                                    header.update({k:old_header[k] for k in ('coordinator','coordinator_instance','source_identity','source_kind','offline_fast_test','timing_mode','database_roster','roster_revision','stagger_capture','resident_tesseract','preloaded_streamlink') if k in old_header})
                                    pending={}
                                    def write(receipt, payload):
                                        handle=lane['log']
                                        if receipt['switched']:
                                            path=directory/lane['channel']/following/'capture.jsonl'
                                            path.parent.mkdir(parents=True,exist_ok=False)
                                            handle=path.open('x',encoding='utf-8')
                                            pending.update(log=handle,path=path)
                                            lane['log'].write(json.dumps(receipt['summary'])+'\n');lane['log'].flush()
                                            handle.write(json.dumps(receipt['configuration'])+'\n')
                                        handle.write(json.dumps(payload,allow_nan=False)+'\n');handle.flush()
                                    try:
                                        receipt=automation.append(lane['run_id'],record,following,header,write=write)
                                    except BaseException:
                                        if pending: pending['log'].close()
                                        raise
                                    if receipt['switched']:
                                        previous,old=lane['run_id'],lane['log']
                                        lane.update(run_id=receipt['run_id'],character_id=receipt['character_id'],
                                            session_id=receipt['session_id'],character=receipt['name'],run_attempts=1,log=pending['log'])
                                        lane['args'].output=pending['path'];handles[lane['channel']]=lane['log']
                                        httpd.active_run_ids.discard(previous);httpd.active_run_ids.add(lane['run_id'])
                                        lane['options']['identity'].select(receipt['name'],record['received_at'],source='automatic_two_frame')
                                        old.close()
                                        print(f"{lane['channel']}: automatically selected {receipt['name']} / character {receipt['character_id']} / session {receipt['session_id']}",flush=True)
                                    lane['commits']+=1
                                    print(report_attempt(receipt['record'],True,database=database,channel=lane['channel'],
                                        neural_enabled=lane['args'].experimental_neural_level).replace('#',f"{lane['channel']} [{lane.get('character')}] #",1),flush=True)
                                    return
                                record = identity_held(record)  # Before the log too, so replay stores the same payload.
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
                                            neural_enabled=lane['args'].experimental_neural_level).replace('#',f"{lane['channel']} [{lane.get('character')}] #",1),flush=True)
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
                            # Current official status avoids offline/unrelated playback; uncertainty never blocks capture.
                            if args.continuous and (db_mode or any(row['source']=='twitch' for row in streams)):
                                scheduler_options['gate']=category_gate(lanes,any_category=args.any_category)
                                print('Twitch captures pause while offline'+(' or outside the MapleStory category.' if not args.any_category else '.'),flush=True)
                            def lane_options(lane):
                                lane['options']={'resident':resident} if resident else {}
                                if tesseract:lane['options']['tesseract']=tesseract  # Shared bounded pool; never shares a reply.
                                if streamlink:lane['options']['streamlink']=streamlink
                                if args.hud_cache_seconds:  # Per channel; survives rotation, not restarts.
                                    lane['options']['analyze_frame']=functools.partial(shadow.analyze,
                                        locator=shadow.CachedLocator(args.hud_cache_seconds))
                                if lane['args'].character_names:  # Per channel; survives rotation, not restarts.
                                    from character_identity import IdentityCapture
                                    lane['options']['identity']=IdentityCapture(lane['channel'],confirmed=lane['character'],
                                        **({'confirmation_source':'persisted_selection'} if lane['args'].automatic_characters else {}))
                            for lane in lanes:lane_options(lane)
                            if db_mode:
                                from db_roster_runtime import Reconciler
                                def start_dynamic(lane):
                                    with store._transaction():
                                        s=store._channel(lane['channel']);cid=s['selected_character_id']
                                        if cid is None:
                                            if lane['origin']!='discovered':raise ValueError('historical streamer has no selected identity')
                                            cid=store.add_character(lane['channel'],'PendingOCR')
                                            store.select_character(lane['channel'],cid,only_if_unselected=True)
                                        sid=store.start_session(lane['channel'],expected_character_id=cid)
                                        label=store.db.execute('SELECT label FROM characters WHERE id=?',(cid,)).fetchone()[0]
                                        lane.update(character_id=cid,session_id=sid,character=label)
                                        header=open_run(lane,uuid.uuid4().hex)
                                        diagnostic.begin(lane['run_id'],lane['channel'],header)
                                    lane_options(lane);httpd.active_run_ids.add(lane['run_id'])
                                def close_dynamic(lane,reason):
                                    try:
                                        if not lane.get('persistence_failed'):
                                            emit(lane,dict(type='summary',trusted=False,attempts=lane['run_attempts'],interrupted=False,completion_reason=reason))
                                    finally:
                                        httpd.active_run_ids.discard(lane['run_id']);lane['log'].close()
                                reconciler=Reconciler(store,lanes,lambda row:make_lane(dict(row,source='twitch',count=60)),
                                    start_dynamic,close_dynamic,httpd.coordinator_status,httpd.active_run_ids)
                                scheduler_options['reconcile']=reconciler
                            def perform(lane,n,seek):
                                return shadow.capture_attempt(lane['args'],lane['source'],lane['requirements'],n,seek=seek,**lane['options'])
                            interrupted = schedule(lanes,perform,emit,workers=args.workers,stagger=args.stagger_capture,
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
                            if db_mode:
                                with store._transaction():store.db.execute("UPDATE streamer_runtime SET state='stopped',heartbeat_at=? WHERE state NOT IN ('paused','error')",(utc(),))
                            print('Capture stopped. UNVERIFIED diagnostics only. Resources: '+json.dumps(monitor.snapshot()),flush=True)
                            for lane in lanes:
                                print(f"{lane['channel']}: {lane['frames']}/{lane['attempts']} frames, {lane['commits']} SQLite attempt commits; skipped deadlines={lane['skipped']}; capture failures={lane['capture_failures']}, OCR failures={lane['ocr_failures']}",flush=True)
                                if lane['elapsed_count']: print(f"{lane['channel']}: requested {lane['args'].interval:.3f}s / actual mean start-to-start {lane['elapsed_total']/lane['elapsed_count']:.3f}s; mean work {lane['duration_total']/lane['attempts']:.3f}s",flush=True)
                                if lane['skipped']: print(f"{lane['channel']}: requested {lane['args'].interval}s cadence NOT sustained; inspect actual_interval_seconds and stage durations",flush=True)
                    finally:
                        httpd.active_run_ids.clear()
                        httpd.coordinator_status.clear()
                        for handle in handles.values(): handle.close()
                        if resident: resident.close()
                        if tesseract:
                            tesseract.close()
                            print('Resident Tesseract: '+json.dumps(tesseract.snapshot()),flush=True)
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
        if streamlink:streamlink.close()
        if httpd:
            if thread and thread.is_alive():
                httpd.shutdown(); thread.join(timeout=2)
            httpd.server_close()


if __name__ == '__main__':
    raise SystemExit(main())
