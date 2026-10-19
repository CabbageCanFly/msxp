"""Bounded, causal, read-only 24h projection. Never trusted EXP accounting."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from fractions import Fraction
import json
import threading

from .diagnostic_evidence import project
from .manual import revision,active
from .diagnostic_percentage import review
from .diagnostic_progress import percentage_point,rational,elapsed_seconds
from .product import reading,fraction,WINDOWS,PACE_TREND_SECONDS
from .pace_intervals import collect_observed as collect,endpoint_interval,window_endpoints,usable_endpoint,PUBLIC_POLICY as TRACKED_POLICY

MAX_RUNS=1024
MAX_EVENTS=65536
MAX_BYTES=128*1024*1024


class HistoryLimit(ValueError):
    pass


def select_runs(diagnostic,channel,*,start,now):
    """The full-replay run sequence: time-range runs plus verified rotation predecessors."""
    from .diagnostics import rotation_link
    store=diagnostic.store;db=diagnostic.db;streamer=store._channel(channel)
    character=streamer['selected_character_id']
    owner='a.session_id IN (SELECT id FROM sessions WHERE streamer_id=? AND character_id=?)' if store.schema_version>=4 else 'r.streamer_id=? AND r.character_id=?'
    runs=[dict(r) for r in db.execute('SELECT DISTINCT r.rowid,r.* FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id '
        'WHERE '+owner+' AND a.attempted_at>=? AND a.attempted_at<=? ORDER BY r.rowid LIMIT ?',
        (streamer['id'],character,start.isoformat(),now.isoformat(),MAX_RUNS+1))] if character else []
    selected={r['run_id']:r for r in runs}
    if len(selected)>MAX_RUNS:raise HistoryLimit('run_limit')
    for current in runs:
        while True:
            config=json.loads(current['configuration_json'])
            previous=db.execute('SELECT rowid,* FROM diagnostic_runs WHERE run_id=?',(config.get('previous_run_id'),)).fetchone() if config.get('start_reason')=='scheduled_rotation' else None
            if not rotation_link(previous,current) or previous['run_id'] in selected:break
            selected[previous['run_id']]=dict(previous);current=selected[previous['run_id']]
            if len(selected)>MAX_RUNS:raise HistoryLimit('run_limit')
    return sorted(selected.values(),key=lambda r:r['rowid'])


def run_rows(diagnostic,channel,run,*,now,receipt):
    """Bounded source read of one run using the existing sanitized decoder."""
    receipt['run_count']+=1
    lengths=diagnostic.db.execute('SELECT COUNT(*),COALESCE(SUM(LENGTH(CAST(payload_json AS BLOB))),0),MAX(id) FROM diagnostic_attempts WHERE run_id=?',(run['run_id'],)).fetchone()
    receipt['context_attempts']+=lengths[0];receipt['source_bytes']+=lengths[1]
    if lengths[0]>60 or receipt['context_attempts']>MAX_EVENTS or receipt['source_bytes']>MAX_BYTES:
        raise HistoryLimit('attempt_or_byte_limit')
    rows=diagnostic._snapshot(channel,now=now,session_id=run['session_id'],run_id=run['run_id'],limit=60,_rows_only=True)
    return (run['run_id'],run['configuration_json'],run['summary_json'],lengths[0],lengths[2]),[
        r for r in rows if datetime.fromisoformat(r.get('received_at') or r['attempted_at'])<=now]


RECEIPT=('run_count','context_attempts','source_bytes')


def replay(diagnostic,channel,*,start,now,receipt,state,step,checkpoints=None,key=None,keep=lambda state:state):
    """Full causal replay, resumed after the longest unchanged checkpointed run prefix.

    Attempts are INSERT-only and contiguous within an unfinished run, and a summary
    is written once, which closes the run. A checkpoint therefore stays exact while
    the clock has not regressed, the current full-replay run sequence begins with
    the covered runs, and each covered run keeps its configuration, summary, attempt
    count and last attempt ID. Anything else is a full replay from the first run.
    ``step`` mutates ``state`` for one run batch and returns its percentage reviews.
    """
    runs=select_runs(diagnostic,channel,start=start,now=now)
    with LOCK:saved=checkpoints.get(key) if checkpoints is not None else None
    covered=0
    if saved and now>=saved['now'] and len(saved['runs'])<=len(runs) and all(
            (r['run_id'],r['configuration_json'],r['summary_json'])==f[:3] for r,f in zip(runs,saved['runs'])):
        ids=[f[0] for f in saved['runs']]
        counts={row[0]:(row[1],row[2]) for row in diagnostic.db.execute('SELECT run_id,COUNT(*),MAX(id) FROM diagnostic_attempts WHERE run_id IN ('
            +','.join('?'*len(ids))+') GROUP BY run_id',ids)} if ids else {}
        if all(counts.get(f[0],(0,None))==f[3:] for f in saved['runs']):
            # In place: a later HistoryLimit leaves the caller with the progress made so far.
            state.clear();state.update(thaw(saved['state']));receipt.update({k:saved['receipt'][k] for k in RECEIPT});covered=len(ids)
    if not covered and checkpoints is not None:
        with LOCK:checkpoints.pop(key,None)
    fingerprints=list(saved['runs'][:covered]) if covered else []
    for i,run in enumerate(runs[covered:],covered):
        fingerprint,rows=run_rows(diagnostic,channel,run,now=now,receipt=receipt)
        decisions=step(state,run,rows)
        # Only a complete, closed (or superseded) run whose last quarantine deadline has
        # passed is final: review() re-labels an unexpired final row from the clock.
        settled=(len(rows)==fingerprint[3] and (i<len(runs)-1 or run['summary_json'] is not None)
            and (not decisions or not decisions[-1]['verification_deadline']
                or now>datetime.fromisoformat(decisions[-1]['verification_deadline'])))
        if checkpoints is not None and len(fingerprints)==i and settled:
            fingerprints.append(fingerprint)
            value=dict(now=now,runs=list(fingerprints),receipt={k:receipt[k] for k in RECEIPT},state=thaw(keep(state)))
            with LOCK:
                if key not in checkpoints and len(checkpoints)>=MAX_CHECKPOINTS:checkpoints.pop(next(iter(checkpoints)))
                checkpoints[key]=value
    return state


MAX_CHECKPOINTS=64  # Two per channel (24h, recent) for the 25-channel directory, plus headroom.
LOCK=threading.Lock()  # Directory and character threads share one checkpoint store.


def thaw(state):
    """Independent mutable copy; immutable interval/row records are shared, not copied."""
    memo={id(v):v for name in ('gains','rows','decisions') for v in state.get(name,())}
    return deepcopy(state,memo)


def stamp(row):
    return datetime.fromisoformat(row.get('received_at') or row['attempted_at'])


def recent_snapshot(diagnostic,channel,*,now,_historical=False,eta_cache=None,checkpoints=None):
    """One hour plus causal warmup, never a browser-sized raw history response."""
    from .diagnostics import rotation_link
    base=diagnostic._snapshot(channel,now=now,limit=1)
    receipt=dict(context_attempts=0,source_bytes=0,run_count=0)
    start=now-timedelta(minutes=65);session=(base['session'] or {}).get('id')
    owner='session_id=?' if diagnostic.store.schema_version>=4 else 'run_id IN (SELECT run_id FROM diagnostic_runs WHERE session_id=?)'
    if _historical:
        earliest=diagnostic.db.execute('SELECT MIN(attempted_at) FROM diagnostic_attempts WHERE '+owner,
            (session,)).fetchone()[0]
        if earliest:start=datetime.fromisoformat(earliest)
    def step(state,run,batch):
        # select_runs already limits every independently bounded session to the selected character.
        if not rotation_link(state['previous_run'],run):state['level_state']={};state['percentage_state']={}
        for row in batch:
            when=row.get('received_at') or row['attempted_at']
            row['timestamp_ordered']=state['previous_time'] is None or when>state['previous_time']
            state['previous_time']=max(state['previous_time'],when) if state['previous_time'] else when
        batch=project(batch,state=state['level_state'])
        reviewed=review(batch,[percentage_point(r) for r in batch],now=now,state=state['percentage_state'])
        # Retained rows passed an earlier, never later, cutoff; reapply this request's.
        kept=[(r,d) for r,d in zip(state['rows'],state['decisions']) if stamp(r)>=start]
        rows=state['rows']=[r for r,_ in kept];decisions=state['decisions']=[d for _,d in kept]
        for row,decision in zip(batch,reviewed):
            if stamp(row)<start:continue
            row['percentage_review']=decision;rows.append(row);decisions.append(decision)
        if _historical and len(rows)>4096:
            # A lone new endpoint cannot evict the last supported rate.
            evidence=dict(observations=rows,percentage_progress=dict(percentage_reviews=decisions))
            intervals=collect(evidence,now=now,read=reading,max_interval_seconds=PACE_TREND_SECONDS)['intervals']
            if intervals:
                cutoff=datetime.fromisoformat(intervals[-1]['after']['timestamp'])-timedelta(minutes=65)
                keep=next((i for i,r in enumerate(rows) if stamp(r)>=cutoff),len(rows))
                state['rows']=rows[keep:];state['decisions']=decisions[keep:]
        if len(state['rows'])>4096:raise HistoryLimit('recent_attempt_limit')
        state['previous_run']=run
        return reviewed
    state=dict(level_state={},percentage_state={},previous_run=None,previous_time=None,rows=[],decisions=[])
    # The 4,096-row historical restoration is too large to retain per channel.
    resume=None if _historical else checkpoints
    try:
        state=replay(diagnostic,channel,start=start,now=now,receipt=receipt,state=state,step=step,
            checkpoints=resume,key=('recent',channel,base['selected_character'] and base['selected_character']['id'],session,
                revision(base['manual_corrections'])))
    except HistoryLimit:
        return dict(base,observations=[],recent_history_status='history_limit',recent_history_receipt=receipt)
    kept=[(r,d) for r,d in zip(state['rows'],state['decisions']) if stamp(r)>=start]
    rows=[r for r,_ in kept];decisions=[d for _,d in kept]
    data=dict(percentage_reviews=decisions,reason=decisions[-1]['reason'] if decisions else 'no_observations')
    result=dict(base,observations=rows,percentage_progress=data,recent_history_status='ready',recent_history_receipt=receipt)
    if not _historical:
        from .product import recent_windows,PACE_TREND_SECONDS
        from .pace_intervals import collect_observed as collect
        if not collect(result,now=now,read=reading,max_interval_seconds=PACE_TREND_SECONDS)['intervals']:
            # Cold-server restoration is bounded like other history queries.
            # Cache only compact static estimates, invalidated by any new event.
            attempt_revision=diagnostic.db.execute('SELECT MAX(id) FROM diagnostic_attempts WHERE '+owner+' AND attempted_at<=?',
                ((base['session'] or {}).get('id'),now.isoformat())).fetchone()[0]
            key=(channel,(base['session'] or {}).get('id'),attempt_revision,base['run_id'],base['run_status'],revision(base['manual_corrections']))
            cached=eta_cache.get(channel) if eta_cache is not None else None
            if cached is None or cached[0]!=key:
                historical=recent_snapshot(diagnostic,channel,now=now,_historical=True)
                old=recent_windows(historical,None,now=now)
                saved={m:w['eta'] for m,w in old.items()}
                cached=(key,saved,historical['recent_history_status'],historical['recent_history_receipt'])
                if eta_cache is not None:
                    if channel not in eta_cache and len(eta_cache)>=25:eta_cache.pop(next(iter(eta_cache)))
                    eta_cache[channel]=cached
            result.update(historical_etas=cached[1],eta_history_status=cached[2],eta_history_receipt=cached[3])
    return result


def aggregate(diagnostic,channel,*,now,checkpoints=None):
    from .diagnostics import rotation_link
    if now.utcoffset() is None:raise ValueError('Aware history clock required')
    now=now.astimezone(timezone.utc);start=now-timedelta(hours=24)
    store=diagnostic.store;streamer=store._channel(channel)
    character=streamer['selected_character_id']
    manual_events=store.manual_history(channel,character_id=character,as_of=now) if character else []
    manual_revision=revision(manual_events)
    bins=[dict(start=(start+timedelta(minutes=30*i)).isoformat(),end=(start+timedelta(minutes=30*(i+1))).isoformat(),
               amount=None,coverage=Fraction(0),intervals=0,gap=False) for i in range(48)]
    result=dict(policy=TRACKED_POLICY,channel=channel,character_id=character,as_of=now.isoformat(),
        start=start.isoformat(),end=now.isoformat(),seconds=1800,range_seconds=86400,trusted=False,
        identity_verified=False,status='ready',tracked_exp=None,intervals=0,coverage_seconds=rational(Fraction(0)),
        unknown_seconds=rational(Fraction(86400)),context_attempts=0,source_bytes=0,run_count=0,
        boundary_intervals_excluded=0,basis_counts={},requirement_versions=[],buckets=[],windows={},current_level_windows={},
        chart_intervals=[],scope='selected_character_public_observation_endpoints',exclusion_counts={})
    limited=False
    def step(state,run,rows):
        if not rotation_link(state['previous_run'],run):
            state['level_state']={};state['percentage_state']={}
        for row in rows:
            when=stamp(row);last=state['last_time']
            row['timestamp_ordered']=last is None or when>last
            state['last_time']=max(last,when) if last else when
        rows=project(rows,state=state['level_state'])
        evidence=[percentage_point(r) for r in rows]
        decisions=review(rows,evidence,now=now,state=state['percentage_state'])
        for row,decision in zip(rows,decisions):
            row['percentage_review']=decision
            level_reading=row.get('experimental_level') or {}
            if (level_reading.get('value') is not None and row.get('timestamp_ordered') is not False
                    and row.get('fresh_at_capture') and row.get('capture_acquired') and row.get('hud_count')==1):
                state['level']=level_reading['value'];state['level_epoch']=row.get('manual_epoch')
                state['level_baseline_id']=row.get('manual_baseline_id',row.get('manual_epoch'))
                state['level_at']=row.get('received_at') or row['attempted_at']
        collected=collect(dict(observations=rows,percentage_progress=dict(percentage_reviews=decisions)),
            now=now,read=reading,max_interval_seconds=PACE_TREND_SECONDS,state=state['interval_state'])
        counts=state['exclusion_counts']
        for excluded in collected['excluded']:
            reason=excluded['reason'] or 'unavailable'
            counts[reason]=counts.get(reason,0)+1
        state['rows'].extend(collected['points'])
        state['last_row']=rows[-1] if rows else state['last_row']
        state['previous_run']=run
        return decisions
    state=dict(level_state={},percentage_state={},interval_state={},last_time=None,previous_run=None,level=None,level_epoch=None,
        level_baseline_id=None,level_at=None,
        rows=[],last_row=None,exclusion_counts={})
    try:
        state=replay(diagnostic,channel,start=start-timedelta(seconds=PACE_TREND_SECONDS),now=now,receipt=result,state=state,step=step,
            checkpoints=checkpoints,key=('tracked',channel,character,manual_revision),
            keep=lambda s:dict(s,rows=[r for r in s['rows'] if datetime.fromisoformat(r['timestamp'])>=start]))
    except HistoryLimit:
        limited=True
    result['exclusion_counts']=dict(state['exclusion_counts']);level=state['level']
    transition=(((state['last_row'] or {}).get('experimental_level') or {}).get('level_context') or {}).get('transition') or {}
    session=store._open_session(streamer['id'])
    manual=next((e for e in reversed(active(manual_events)) if e['kind']=='baseline' and e['session_id']==(session['id'] if session else None)),None)
    if manual and manual['action']=='set' and manual['level'] is not None:
        if state['level_baseline_id']!=manual['id']:level=manual['level']
        if (state['last_row'] or {}).get('manual_baseline_id')!=manual['id']:transition={}
    point=next((e for e in reversed(active(manual_events)) if e['kind']=='point' and e['session_id']==(session['id'] if session else None)),None)
    if point and (not state['level_at'] or datetime.fromisoformat(point['effective_at'])>=datetime.fromisoformat(state['level_at'])) and (
            manual is None or point['effective_at']>=manual['effective_at']):
        level=point['level'];transition={}
    if transition.get('phase')=='possible':level=transition['to_level']
    gains=[];coverage=Fraction(0);versions=set()
    points=sorted((r for r in state['rows'] if usable_endpoint(r)),key=lambda r:datetime.fromisoformat(r['timestamp']))
    for before,after in zip(points,points[1:]):
        if before['timestamp']==after['timestamp']:continue
        gain,reason=endpoint_interval(before,after)
        if gain is None:
            result['exclusion_counts'][reason]=result['exclusion_counts'].get(reason,0)+1
            continue
        a,b=datetime.fromisoformat(gain['start']),datetime.fromisoformat(gain['end'])
        if a<start<b:result['boundary_intervals_excluded']+=1
        if a>=start and b<=now:
            gains.append(gain)
            amount=fraction(gain['value']);duration=elapsed_seconds(a,b)
            coverage+=duration;result['intervals']+=1
            basis=gain['basis'];result['basis_counts'][basis]=result['basis_counts'].get(basis,0)+1
            versions.add(gain['requirement']['version'])
            # Recognized at the later endpoint; no invented distribution through gaps.
            bucket=bins[min(47,(b-start)//timedelta(minutes=30))]
            bucket['amount']=(bucket['amount'] or Fraction(0))+amount
            bucket['coverage']=min(Fraction(1800),bucket['coverage']+duration)
            bucket['intervals']+=1;bucket['gap']=True
    if limited:
        # Incomplete causal replay must not masquerade as a complete query or zero.
        result.update(status='history_limit',tracked_exp=None,basis_counts={});versions.clear()
        bins=[dict(b,amount=None,coverage=Fraction(0),intervals=0) for b in bins]
        coverage=Fraction(0);result['intervals']=0
    else:
        _,daily,_=window_endpoints(state['rows'],start=start,end=now)
        result['tracked_exp']=daily['value'] if daily else None
    if not limited:
        result['current_level']=level
        from .product import recent_windows
        last=state['last_row'];head=dict(observations=[last] if last else [],
            run_id=last['run_id'] if last else None,percentage_progress=dict(reason='public_endpoint_window'))
        collected=dict(points=state['rows'],latest=state['rows'][-1] if state['rows'] else None,
            excluded=[],recoveries=[])
        result['windows']=recent_windows(head,dict(value=level),now=now,collected=collected)
        result['current_level_windows']=recent_windows(head,dict(value=level),now=now,current_level_only=True,collected=collected)
        for metrics in (result['windows'],result['current_level_windows']):
            for key,metric in list(metrics.items()):
                pace=metric.get('pace')
                metrics[key]={k:metric[k] for k in ('available','gain','observed','reason') if k in metric}
                metrics[key].update(window_start=metric['start'],window_end=metric['end'],policy=TRACKED_POLICY,
                    rate=pace['estimates']['exp_per_hour']['value'] if pace else None,
                    level=pace['level'] if pace else None,levels=pace['levels'] if pace else [],trusted=False)
        # Copied: retained interval records must never be reachable from a response.
        result['chart_intervals']=deepcopy([{k:g[k] for k in ('start','end','level','value','basis','kind','policy','evidence_types')}
            for g in gains if datetime.fromisoformat(g['start'])>=now-timedelta(minutes=60)])
        current=[r for r in state['rows'] if r['level']['value']==level and datetime.fromisoformat(r['timestamp'])>=now-timedelta(minutes=60)]
        result['current_level_chart_intervals']=[{k:g[k] for k in ('start','end','level','value','basis','kind','policy','evidence_types')}
            for a,b in zip(current,current[1:]) if (g:=endpoint_interval(a,b)[0])]
        result['chart_status']='ready' if max(len(result['chart_intervals']),len(result['current_level_chart_intervals']))<=4096 else 'history_limit'
        if result['chart_status']=='history_limit':result['chart_intervals']=[];result['current_level_chart_intervals']=[]
    result.update(coverage_seconds=rational(coverage),unknown_seconds=rational(Fraction(86400)-coverage),requirement_versions=sorted(versions),
        buckets=[dict(start=b['start'],end=b['end'],value=rational(b['amount']) if b['amount'] is not None else None,
            covered=rational(b['coverage']),intervals=b['intervals'],
            state='missing' if b['amount'] is None else 'covered' if b['coverage']==1800 and not b['gap'] else 'partial') for b in bins])
    return result
