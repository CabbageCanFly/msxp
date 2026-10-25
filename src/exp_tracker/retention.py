"""Transactional 24-hour evidence retention, run separately from capture. CLI defaults to read-only reporting."""
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import argparse
import json
from pathlib import Path
import sqlite3
import time

from .store import Store, utc

# The worker's runs per batch. Replay reads a snapshot, so batch size bounds CPU per call, not the write lock:
# measured 115-132 ms at 5, 10 or 25 runs (docs/retention-capture-interference.md); 10 leaves CPU to OCR.
BATCH_RUNS = 10
PRUNE_RUNS = 200  # Direct prune() callers keep the original per-call limit.


def pack(value):
    if value is None or type(value) in (str,int,float,bool):return value
    if isinstance(value, datetime):return {'$datetime':value.isoformat()}
    if isinstance(value, Fraction):return {'$fraction':[value.numerator,value.denominator]}
    if isinstance(value, deque):return {'$deque':[pack(list(value)),value.maxlen]}
    if isinstance(value, set):return {'$set':[pack(v) for v in sorted(value,key=str)]}
    if isinstance(value, tuple):return {'$tuple':[pack(v) for v in value]}
    if isinstance(value, dict):return {k:pack(v) for k,v in value.items()}
    if isinstance(value, list):return [pack(v) for v in value]
    return value


def unpack(value):
    if isinstance(value,list):return [unpack(v) for v in value]
    if not isinstance(value,dict):return value
    if '$datetime' in value:return datetime.fromisoformat(value['$datetime'])
    if '$fraction' in value:return Fraction(*value['$fraction'])
    if '$deque' in value:return deque(unpack(value['$deque'][0]),maxlen=value['$deque'][1])
    if '$set' in value:return set(unpack(value['$set']))
    if '$tuple' in value:return tuple(unpack(value['$tuple']))
    result={k:unpack(v) for k,v in value.items()}
    # Also compact copies in old endpoints/display/provenance, including inactive characters.
    if {'wrap_event_id','from_level','phase','samples'}<=result.keys():
        from .diagnostic_evidence import compact_transition
        return compact_transition(result)
    return result


def dumps(value):return json.dumps(pack(value),separators=(',',':'),allow_nan=False)
def loads(value):return unpack(json.loads(value))


def checkpoint(store, character):
    if store.schema_version<8 or character is None:return {}
    row=store.db.execute('SELECT checkpoint_json FROM retention_state WHERE character_id=?',(character,)).fetchone()
    return loads(row[0]) if row else {}


def expired(store, character, when):
    if store.schema_version<8:return False
    row=store.db.execute('SELECT cutoff FROM retention_state WHERE character_id=?',(character,)).fetchone()
    return bool(row and datetime.fromisoformat(when)<=datetime.fromisoformat(row[0]))


def guard(store, character, when):
    if expired(store,character,when):
        raise ValueError('reading history has expired under 24-hour retention; use a new current baseline')


def next_id(store, table, column):
    """Audit source identities must never be recycled after the highest row expires."""
    return store.db.execute(f'SELECT MAX(COALESCE((SELECT MAX(rowid) FROM {table}),0),{column})+1 FROM retention_meta WHERE id=1').fetchone()[0]


def live_runs(store):
    """Unfinished runs that may still be capturing: each streamer's newest run, while it has no summary.

    A coordinator runs one lane per streamer and its active run is that streamer's newest, so an older
    unfinished run was superseded (e.g. left by a killed process) and is not being written. This needs no
    heartbeat; while capture is stopped it protects at most one extra run per streamer."""
    return {r[0] for r in store.db.execute('''SELECT run_id FROM diagnostic_runs r WHERE summary_json IS NULL
        AND rowid=(SELECT MAX(rowid) FROM diagnostic_runs WHERE streamer_id=r.streamer_id)''')}


@contextmanager
def _snapshot(store):
    """One read snapshot holding no write lock (WAL); query_only makes any accidental write fail loudly."""
    store.db.execute('PRAGMA query_only=ON')
    try:
        if store.db.in_transaction or store.read_only:
            with store._transaction():yield
        else:
            store.db.execute('BEGIN')
            try:yield
            finally:store.db.execute('ROLLBACK')
    finally:
        store.db.execute('PRAGMA query_only=OFF')


@contextmanager
def _as_selected(store, login, character):
    """Replay a character as if selected, in this connection's memory only; nothing is written."""
    channel=store._channel
    store._channel=lambda name:(dict(row,selected_character_id=character) if (row:=channel(name))['login']==login else row)
    try:yield
    finally:store._channel=channel


def _fingerprint(store, cid, streamer, runs):
    """Everything a prefix checkpoint is computed from. Compared again under the write lock before applying."""
    audit=''.join(f',(SELECT MAX(id) FROM {t})' for t,v in (('manual_corrections',5),('character_renames',6),('reading_commits',7))
        if store.schema_version>=v)
    head=store.db.execute(f'''SELECT (SELECT revision FROM retention_meta WHERE id=1),
        (SELECT checkpoint_json FROM retention_state WHERE character_id=?),
        (SELECT id FROM sessions WHERE streamer_id=? AND ended_at IS NULL),(SELECT MAX(id) FROM observations){audit}''',
        (cid,streamer)).fetchone()
    state=store.db.execute('SELECT * FROM tracking_state WHERE character_id=?',(cid,)).fetchone()
    rows=[tuple(store.db.execute('''SELECT r.rowid,r.summary_json,COUNT(a.id),MAX(a.id) FROM diagnostic_runs r
        LEFT JOIN diagnostic_attempts a ON a.run_id=r.run_id WHERE r.run_id=?''',(run['run_id'],)).fetchone()) for run in runs]
    return tuple(head),tuple(state) if state else None,rows


def plan(store, now, active_runs=None, limit=None):
    cutoff=now-timedelta(hours=24,minutes=5)
    groups={}
    for row in store.db.execute('''SELECT r.rowid,r.*,MAX(a.attempted_at) AS attempted,
            MAX(COALESCE(a.received_at,a.attempted_at)) AS received,COUNT(a.id) AS attempts
            FROM diagnostic_runs r LEFT JOIN diagnostic_attempts a ON a.run_id=r.run_id
            GROUP BY r.rowid ORDER BY r.rowid'''):
        groups.setdefault(row['character_id'],[]).append(dict(row))
    prefixes={};remaining=PRUNE_RUNS if limit is None else limit
    for cid,runs in groups.items():
        if not remaining:break
        floor=checkpoint(store,cid).get('through_run',0);chosen=[]
        for run in runs:
            if run['rowid']<=floor:continue
            stamp=max(run['attempted'] or run['created_at'],run['received'] or run['created_at'])
            protected=run['run_id'] in active_runs if active_runs is not None else run['summary_json'] is None
            if protected or run['attempts'] and datetime.fromisoformat(stamp)>=cutoff:break
            chosen.append(run)
            remaining-=1
            if not remaining:break
        if chosen:prefixes[cid]=chosen
    return prefixes


def _checkpoint_value(store, cid, character, runs, now, cutoff):
    """Replay a character's prefix runs into the checkpoint that replaces them, plus the daily snapshots the
    replay would have saved. Reads only; _apply writes both."""
    store.deferred_daily=[]
    try:return _replay_prefix(store,cid,character,runs,now,cutoff),store.deferred_daily
    finally:del store.deferred_daily


def _replay_prefix(store, cid, character, runs, now, cutoff):
    from .diagnostics import Diagnostics
    from .product import player,reading,responsive_pace
    from .rolling_history import usable_endpoint
    diagnostic=Diagnostics(store);diagnostic._retention_prefix={r['run_id'] for r in runs};diagnostic._retention_states={}
    diagnostic.rolling_history(character['login'],now=now)
    from .rolling_history import recent_snapshot
    recent=recent_snapshot(diagnostic,character['login'],now=now,_historical=True)
    states=diagnostic._retention_states
    if set(states)!={'tracked','recent'} or recent.get('recent_history_status')!='ready':
        raise ValueError('cannot checkpoint incomplete retention replay')
    previous=checkpoint(store,cid)
    prefix_pace=responsive_pace(recent,None,now=now)
    from .diagnostic_progress import progress
    from .diagnostic_evidence import Projected
    recent['observations']=Projected(diagnostic._retention_display_rows if hasattr(diagnostic,'_retention_display_rows') else [])
    recent['percentage_progress']=progress(recent['observations'],now=now)
    shown=player(recent,now=now)
    display={k:shown[k] for k in ('reading','display_level','level_context','latest_attempt_at','latest_attempt_status','responsive_pace')}
    display['responsive_pace']=prefix_pace
    full=next((reading(r) for r in reversed(recent['observations']) if reading(r) and reading(r)['exp'] is not None),None)
    display['full_exp']=dict(exp=full['exp'],percentage=full['percentage'],evidence=full['evidence'],event_id=full['event_id'],
        timestamp=full['timestamp']) if full else previous.get('display',{}).get('full_exp')
    for key in ('reading','display_level','responsive_pace'):
        if display[key] is None:display[key]=previous.get('display',{}).get(key)
    if display['responsive_pace']:
        display['responsive_pace']={k:v for k,v in display['responsive_pace'].items()
            if k not in ('intervals','conditional_recoveries','excluded','latest_endpoint')}
    etas=recent['historical_etas']
    etas={str(m):etas.get(str(m)) for m in (5,10,15,30,60)}
    etas={m:v or previous.get('etas',{}).get(m) for m,v in etas.items()}
    tracked=states['tracked']
    tracked['rows']=[p for p in tracked['rows'] if usable_endpoint(p)][-1:]
    states['recent']['rows']=[];states['recent']['decisions']=[]
    # Event IDs are immutable and prefix runs cannot be appended/replayed.
    for value in (tracked,states['recent']):
        value['percentage_state'].get('seen',set()).clear()
    diagnostic_state=tracked['interval_state'].get('diagnostic',{})
    diagnostic_state.get('seen_events',set()).clear()
    # These IDs describe intervals wholly before every future rolling window.
    tracked['interval_state']['holes']=[]
    if diagnostic_state:diagnostic_state['holes']=[]
    paces=dict(previous.get('paces',{}),**states['recent'].get('retained_paces',{}))
    value=dict(states,through_run=runs[-1]['rowid'],display=display,etas=etas,paces=paces)
    return value


def _apply(store, cid, runs, cutoff, value, daily):
    """The only writes for a prefix: its daily snapshots, id high-water marks and checkpoint, then its deletions."""
    from .daily_snapshots import save
    for snapshot in daily:save(store,*snapshot)
    store.db.execute('''UPDATE retention_meta SET
        attempt_id=MAX(attempt_id,COALESCE((SELECT MAX(id) FROM diagnostic_attempts),0)),
        observation_id=MAX(observation_id,COALESCE((SELECT MAX(id) FROM observations),0)),
        run_id=MAX(run_id,COALESCE((SELECT MAX(rowid) FROM diagnostic_runs),0)) WHERE id=1''')
    store.db.execute('INSERT OR REPLACE INTO retention_state VALUES(?,?,?)',(cid,utc(cutoff),dumps(value)))
    for run in runs:
        store.db.execute('DELETE FROM diagnostic_attempts WHERE run_id=?',(run['run_id'],))
    # Keep one predecessor for rotation validation, plus the latest run per session.
    store.db.execute('''DELETE FROM diagnostic_runs WHERE character_id=? AND rowid<?
        AND rowid NOT IN (SELECT MAX(rowid) FROM diagnostic_runs GROUP BY session_id)''',(cid,runs[-1]['rowid']))


def prune(store, *, now=None, dry_run=True, active_runs=None, batch_runs=None, bump=True):
    """Fold a chronological prefix of old runs into checkpoints and delete their raw attempts.

    Planning, replay and the integrity check read a snapshot without the write lock. Each character's prefix
    is then written in its own short transaction that first re-reads the fingerprint it was computed from;
    if anything changed nothing is written, and the prefix is recomputed on the next call.
    active_runs: unfinished runs to protect; None protects every unfinished run, a callable (e.g. live_runs)
    is evaluated in each snapshot. bump=False leaves the retention revision to the caller, so readers that
    rebuild on it do so once per maintenance pass rather than once per prefix.
    """
    now=datetime.fromisoformat(utc(now));cutoff=now-timedelta(hours=24,minutes=5)
    limit=PRUNE_RUNS if batch_runs is None else batch_runs
    report=dict(dry_run=dry_run,cutoff=utc(cutoff),runs=0,attempts=0,observation_candidates=0,batch_limit_reached=False,
        stale_snapshots=0,changed=False,compute_seconds=0.0,lock_seconds=0.0,max_lock_seconds=0.0)
    def held(tick):
        seconds=time.perf_counter()-tick
        report['lock_seconds']+=seconds;report['max_lock_seconds']=max(report['max_lock_seconds'],seconds)
    tick=time.perf_counter()
    with _snapshot(store):
        prefixes=plan(store,now,active_runs(store) if callable(active_runs) else active_runs,limit)
        report.update(runs=sum(map(len,prefixes.values())),attempts=sum(r['attempts'] for runs in prefixes.values() for r in runs),
            observation_candidates=store.db.execute('SELECT COUNT(*) FROM observations WHERE observed_at<?',(utc(cutoff),)).fetchone()[0])
        report['batch_limit_reached']=report['runs']==limit
        if dry_run:return report
        if store.schema_version<9:raise ValueError('writer migration to schema 9 required')
        # Immediate FK enforcement covers the writes below; this finds pre-existing damage before any of them.
        if store.db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('retention foreign key check failed')
    report['compute_seconds']+=time.perf_counter()-tick
    report.update(runs=0,attempts=0);remaining=limit
    while remaining>0:
        tick=time.perf_counter()
        with _snapshot(store):
            prefix=next(iter(plan(store,now,active_runs(store) if callable(active_runs) else active_runs,remaining).items()),None)
            if prefix is None:break
            cid,runs=prefix
            character=store.db.execute('''SELECT c.*,s.login,s.selected_character_id FROM characters c
                JOIN streamers s ON s.id=c.streamer_id WHERE c.id=?''',(cid,)).fetchone()
            seen=_fingerprint(store,cid,character['streamer_id'],runs)
            with _as_selected(store,character['login'],cid):value,daily=_checkpoint_value(store,cid,character,runs,now,cutoff)
        report['compute_seconds']+=time.perf_counter()-tick
        tick=time.perf_counter()
        with store._transaction():
            fresh=_fingerprint(store,cid,character['streamer_id'],runs)==seen
            if fresh:_apply(store,cid,runs,cutoff,value,daily)
        held(tick)
        if not fresh:
            report['stale_snapshots']+=1;break
        report['runs']+=len(runs);report['attempts']+=sum(r['attempts'] for r in runs);report['changed']=True
        remaining-=len(runs)
    tick=time.perf_counter()
    with store._transaction():
        before=store.db.total_changes
        _trusted(store,cutoff)
        report['changed']|=store.db.total_changes!=before
        if bump and report['changed']:store.db.execute('UPDATE retention_meta SET revision=revision+1 WHERE id=1')
    held(tick)
    # More may remain when this call filled its batch or found its snapshot outdated.
    report['batch_limit_reached']=report['runs']>=limit or report['stale_snapshots']>0
    return report


def _trusted(store,cutoff):
    from .trusted_replay import replay
    for session,through in store.db.execute('SELECT session_id,MAX(id) FROM observations WHERE session_id IS NOT NULL AND observed_at<? GROUP BY session_id',(utc(cutoff),)).fetchall():
        # Only a chronological prefix can be folded into an anchor.
        earlier=store.db.execute('SELECT MIN(id) FROM observations WHERE session_id=? AND observed_at>=?',(session,utc(cutoff))).fetchone()[0]
        if earlier is not None:through=min(through,earlier-1)
        old=store.db.execute('SELECT * FROM trusted_checkpoints WHERE session_id=?',(session,)).fetchone()
        if old and through<=old['through_id']:continue
        value=replay(store,session,_force=True,_until_id=through)
        if value['unavailable']:raise ValueError('cannot checkpoint incomplete trusted replay')
        from .daily_snapshots import trusted as archive_daily
        archive_daily(store,session,through,old['through_id'] if old else 0,value['rows'])
        keep={r[0] for r in store.db.execute('SELECT last_trusted_observation_id FROM tracking_state WHERE last_trusted_observation_id IS NOT NULL')}
        keep.update(r[0] for r in store.db.execute('SELECT interval_start_observation_id FROM observations WHERE id>? AND interval_start_observation_id IS NOT NULL',(through,)))
        if value['last']:keep.add(value['last']['id'])
        candidates=[r[0] for r in store.db.execute('SELECT id FROM observations WHERE session_id=? AND id<=?',(session,through)) if r[0] not in keep]
        gain=old['original_gain'] if old else 0;bridged=old['original_bridged'] if old else 0
        for identity in candidates:
            row=store.db.execute('SELECT gained_exp,missing_observations FROM observations WHERE id=?',(identity,)).fetchone()
            gain+=row['gained_exp'] or 0
            if row['missing_observations']:bridged+=row['gained_exp'] or 0
        bridged+=store.db.execute('SELECT COALESCE(SUM(gained_exp),0) FROM observations WHERE session_id=? AND id<=? AND missing_observations>0'+
            (' AND id NOT IN ('+','.join('?'*len(candidates))+')' if candidates else ''),(session,through,*candidates)).fetchone()[0]
        # Expired anchors retain scalar evidence, not an entire foreign-key-linked chain.
        store.db.execute('UPDATE observations SET interval_start_observation_id=NULL,missing_observations=0 WHERE session_id=? AND id<=?',(session,through))
        for identity in candidates:store.db.execute('DELETE FROM observations WHERE id=?',(identity,))
        value['rows']=[]
        store.db.execute('INSERT OR REPLACE INTO trusted_checkpoints VALUES(?,?,?,?,?)',(session,through,dumps(value),gain,bridged))
        cid=store.db.execute('SELECT character_id FROM sessions WHERE id=?',(session,)).fetchone()[0]
        frozen=checkpoint(store,cid)
        store.db.execute('INSERT OR REPLACE INTO retention_state VALUES(?,?,?)',(cid,utc(cutoff),dumps(frozen)))
    store.db.execute('DELETE FROM observations WHERE session_id IS NULL AND observed_at<?',(utc(cutoff),))


def status(store, database, now=None):
    """Plain numbers an operator can compare between passes; read-only."""
    now=datetime.fromisoformat(utc(now))
    oldest=store.db.execute('SELECT MIN(attempted_at) FROM diagnostic_attempts').fetchone()[0]
    unfinished=store.db.execute('SELECT COUNT(*) FROM diagnostic_runs WHERE summary_json IS NULL').fetchone()[0]
    size=lambda path:round(path.stat().st_size/1e6,1) if path.exists() else 0.0
    return dict(oldest_attempt_hours=round((now-datetime.fromisoformat(oldest)).total_seconds()/3600,1) if oldest else None,
        attempts_kept=store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0],
        unfinished_runs=unfinished,protected_runs=len(live_runs(store)),
        db_mb=size(Path(database)),wal_mb=size(Path(str(database)+'-wal')))


BUSY=('database is locked','database is busy')


def maintenance_pass(database, *, log_root=None, batch_runs=BATCH_RUNS, max_seconds=600, pause_seconds=1.0, emit=lambda line:print(line,flush=True)):
    """One bounded pass beside a running coordinator: prune until no backlog or max_seconds, then files.

    Returns the summary; 'complete' is False when backlog remains for the next pass. Never migrates."""
    from .retention_files import cleanup,current_operator_log,register
    began=time.perf_counter()
    summary=dict(event='summary',chunks=0,runs=0,attempts=0,stale_snapshots=0,busy_errors=0,compute_s=0.0,
        lock_total_s=0.0,max_lock_ms=0.0,complete=False,revision_bumped=False,files=0,bytes=0,file_errors=0)
    with Store(database,allow_migration=False) as store:
        if log_root:register(log_root,database,store)  # Adopt legacy directories while their runs are still known.
        changed=False
        while time.perf_counter()-began<max_seconds:
            try:report=prune(store,dry_run=False,active_runs=live_runs,batch_runs=batch_runs,bump=False)
            except sqlite3.OperationalError as error:
                if not any(text in str(error) for text in BUSY) or summary['busy_errors']>=4:raise
                summary['busy_errors']+=1;time.sleep(pause_seconds*4);continue
            summary['chunks']+=1;changed|=report['changed']
            for key,value in (('runs','runs'),('attempts','attempts'),('stale_snapshots','stale_snapshots'),
                    ('compute_s','compute_seconds'),('lock_total_s','lock_seconds')):summary[key]+=report[value]
            summary['max_lock_ms']=max(summary['max_lock_ms'],1000*report['max_lock_seconds'])
            emit(json.dumps(dict(event='chunk',chunk=summary['chunks'],runs=report['runs'],attempts=report['attempts'],
                compute_s=round(report['compute_seconds'],2),lock_ms=round(1000*report['lock_seconds'],1),
                stale=report['stale_snapshots'])))
            if not report['batch_limit_reached']:
                summary['complete']=True;break
            time.sleep(pause_seconds)  # Leaves CPU to capture/OCR between batches.
        if changed:
            # Once per pass: the publisher rebuilds every page (keeping old ones on show) when this changes.
            with store._transaction():store.db.execute('UPDATE retention_meta SET revision=revision+1 WHERE id=1')
            summary['revision_bumped']=True
        if log_root:
            files=cleanup(log_root,database,store,dry_run=False,active_logs=current_operator_log(log_root,database),
                protected_runs=live_runs(store))
            summary.update(files=files['files'],bytes=files['bytes'],file_errors=files['errors'])
        store.db.execute('PRAGMA wal_checkpoint(PASSIVE)')
        summary.update(status(store,database))
    summary.update(elapsed_s=round(time.perf_counter()-began,1),compute_s=round(summary['compute_s'],1),
        lock_total_s=round(summary['lock_total_s'],2),max_lock_ms=round(summary['max_lock_ms'],1))
    emit(json.dumps(summary))
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--apply',action='store_true',help='Prune this explicitly selected database; default reports only')
    parser.add_argument('--log-root',type=Path,help="The coordinator's capture-log root (default for --db-roster: private/multi-alpha/runs); omitted: SQLite only")
    parser.add_argument('--batch-runs',type=int,default=BATCH_RUNS,help=f'Runs folded per batch (1..200, default {BATCH_RUNS})')
    parser.add_argument('--max-seconds',type=float,default=600,help='Stop a pass after this long; the rest waits for the next pass')
    parser.add_argument('--pause-seconds',type=float,default=1.0,help='Pause between batches')
    parser.add_argument('--every-minutes',type=float,help='Repeat passes (e.g. on Windows); systemd uses a timer instead')
    args=parser.parse_args(argv)
    if not args.db.is_file():parser.error('database must already exist')
    if not 1<=args.batch_runs<=200 or not 0<args.max_seconds<=86400 or not 0<=args.pause_seconds<=60:
        parser.error('--batch-runs 1..200, --max-seconds up to 86400, --pause-seconds 0..60')
    if args.every_minutes is not None and not 1<=args.every_minutes<=1440:parser.error('--every-minutes must be 1..1440')
    if (args.every_minutes is not None or args.log_root) and not args.apply:parser.error('--every-minutes and --log-root need --apply')
    try:
        if not args.apply:
            with Store(args.db,read_only=True) as store:
                report=prune(store,dry_run=True,active_runs=live_runs);report.update(status(store,args.db))
            print(json.dumps(report,indent=2))
            return 0
        from .writer_lock import writer_lease
        lock=args.db.with_suffix(args.db.suffix+'.retention.lock');lock.touch(exist_ok=True)
        with writer_lease(lock,message='Another retention worker is running for this database'):
            while True:
                summary=maintenance_pass(args.db,log_root=args.log_root,batch_runs=args.batch_runs,
                    max_seconds=args.max_seconds,pause_seconds=args.pause_seconds)
                if args.every_minutes is None:return 0  # Busy beyond its retries raises: exit 75 below.
                time.sleep(args.every_minutes*60)
    except KeyboardInterrupt:
        return 130  # Between statements: SQLite rolled back any open batch.
    except (ValueError,OSError,sqlite3.Error) as error:
        parser.exit(75 if any(text in str(error) for text in BUSY+('Another retention worker',)) else 1,f'Retention failed: {error}\n')


if __name__=='__main__':raise SystemExit(main())
