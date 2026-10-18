"""Bounded, causal, read-only 24h projection. Never trusted EXP accounting."""
from datetime import datetime,timedelta,timezone
from fractions import Fraction
import json

from .diagnostic_evidence import project
from .diagnostic_percentage import review,boundary
from .diagnostic_progress import percentage_point,rational,elapsed_seconds
from .product import reading,interval_gain,fraction

MAX_RUNS=1024
MAX_EVENTS=65536
MAX_BYTES=128*1024*1024


class HistoryLimit(ValueError):
    pass


def run_batches(diagnostic,channel,*,start,now,receipt):
    """Bounded source reads using the existing sanitized decoder; no partial totals."""
    from .diagnostics import rotation_link
    store=diagnostic.store;db=diagnostic.db;streamer=store._channel(channel)
    character=streamer['selected_character_id']
    owner='a.session_id IN (SELECT id FROM sessions WHERE streamer_id=? AND character_id=?)' if store.schema_version>=4 else 'r.streamer_id=? AND r.character_id=?'
    runs=list(db.execute('SELECT DISTINCT r.rowid,r.* FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id '
        'WHERE '+owner+' AND a.attempted_at>=? AND a.attempted_at<=? ORDER BY r.rowid LIMIT ?',
        (streamer['id'],character,start.isoformat(),now.isoformat(),MAX_RUNS+1))) if character else []
    selected={r['run_id']:r for r in runs}
    if len(selected)>MAX_RUNS:raise HistoryLimit('run_limit')
    for current in runs:
        while True:
            config=json.loads(current['configuration_json'])
            previous=db.execute('SELECT rowid,* FROM diagnostic_runs WHERE run_id=?',(config.get('previous_run_id'),)).fetchone() if config.get('start_reason')=='scheduled_rotation' else None
            if not rotation_link(previous,current) or previous['run_id'] in selected:break
            selected[previous['run_id']]=previous;current=previous
            if len(selected)>MAX_RUNS:raise HistoryLimit('run_limit')
    for run in sorted(selected.values(),key=lambda r:r['rowid']):
        receipt['run_count']+=1
        lengths=db.execute('SELECT COUNT(*),COALESCE(SUM(LENGTH(CAST(payload_json AS BLOB))),0) FROM diagnostic_attempts WHERE run_id=?',(run['run_id'],)).fetchone()
        receipt['context_attempts']+=lengths[0];receipt['source_bytes']+=lengths[1]
        if lengths[0]>60 or receipt['context_attempts']>MAX_EVENTS or receipt['source_bytes']>MAX_BYTES:
            raise HistoryLimit('attempt_or_byte_limit')
        rows=diagnostic._snapshot(channel,now=now,session_id=run['session_id'],run_id=run['run_id'],limit=60,_rows_only=True)
        yield run,[r for r in rows if datetime.fromisoformat(r.get('received_at') or r['attempted_at'])<=now]


def recent_snapshot(diagnostic,channel,*,now):
    """One hour plus causal warmup, never a browser-sized raw history response."""
    from .diagnostics import rotation_link
    base=diagnostic._snapshot(channel,now=now,limit=1)
    receipt=dict(context_attempts=0,source_bytes=0,run_count=0)
    rows=[];decisions=[];level_state={};percentage_state={};previous_run=None;previous_time=None
    start=now-timedelta(minutes=65)
    try:
        for run,batch in run_batches(diagnostic,channel,start=start,now=now,receipt=receipt):
            # A different session can supply its own historical total, never a
            # rate for the explicitly selected current session.
            if run['session_id']!=(base['session'] or {}).get('id'):continue
            if not rotation_link(previous_run,run):level_state={};percentage_state={}
            for row in batch:
                when=row.get('received_at') or row['attempted_at']
                row['timestamp_ordered']=previous_time is None or when>previous_time
                previous_time=max(previous_time,when) if previous_time else when
            batch=project(batch,state=level_state)
            reviewed=review(batch,[percentage_point(r) for r in batch],now=now,state=percentage_state)
            for row,decision in zip(batch,reviewed):
                if datetime.fromisoformat(row.get('received_at') or row['attempted_at'])<start:continue
                row['percentage_review']=decision;rows.append(row);decisions.append(decision)
            if len(rows)>4096:raise HistoryLimit('recent_attempt_limit')
            previous_run=run
    except HistoryLimit:
        return dict(base,observations=[],recent_history_status='history_limit',recent_history_receipt=receipt)
    data=dict(percentage_reviews=decisions,reason=decisions[-1]['reason'] if decisions else 'no_observations')
    return dict(base,observations=rows,percentage_progress=data,recent_history_status='ready',recent_history_receipt=receipt)


def aggregate(diagnostic,channel,*,now):
    from .diagnostics import rotation_link
    if now.utcoffset() is None:raise ValueError('Aware history clock required')
    now=now.astimezone(timezone.utc);start=now-timedelta(hours=24)
    store=diagnostic.store;db=diagnostic.db;streamer=store._channel(channel)
    character=streamer['selected_character_id']
    bins=[dict(start=(start+timedelta(minutes=30*i)).isoformat(),end=(start+timedelta(minutes=30*(i+1))).isoformat(),
               amount=None,coverage=Fraction(0),intervals=0) for i in range(48)]
    result=dict(policy='tracked_exp_24h_v1',channel=channel,character_id=character,as_of=now.isoformat(),
        start=start.isoformat(),end=now.isoformat(),seconds=1800,range_seconds=86400,trusted=False,
        identity_verified=False,status='ready',tracked_exp=None,intervals=0,coverage_seconds=rational(Fraction(0)),
        unknown_seconds=rational(Fraction(86400)),context_attempts=0,source_bytes=0,run_count=0,
        boundary_intervals_excluded=0,basis_counts={},requirement_versions=[],buckets=[])
    limited=False
    level_state={};percentage_state={};previous=None;previous_row=None;last_time=None;last_interval_end=None
    previous_run=None;total=Fraction(0);coverage=Fraction(0);versions=set()
    batches=run_batches(diagnostic,channel,start=start-timedelta(seconds=120),now=now,receipt=result)
    try:
      for run,rows in batches:
        if not rotation_link(previous_run,run):
            level_state={};percentage_state={};previous=previous_row=None
        for row in rows:
            when=datetime.fromisoformat(row.get('received_at') or row['attempted_at'])
            row['timestamp_ordered']=last_time is None or when>last_time
            last_time=max(last_time,when) if last_time else when
        rows=project(rows,state=level_state,allow_context=False)
        evidence=[percentage_point(r) for r in rows]
        decisions=review(rows,evidence,now=now,state=percentage_state)
        for row,(point,invalid),decision in zip(rows,evidence,decisions):
            row['percentage_review']=decision
            value=reading(row)
            eligible=point is not None and invalid is None and decision['progress_eligible']
            if point:point['interval_seconds']=row['interval_seconds']
            connected=bool(eligible and previous and not decision['break_before'] and boundary(previous,point,row) is None)
            gain=interval_gain(reading(previous_row),row,value,connected) if previous_row and not previous_row.get('crop_suspect') else None
            if gain:
                a,b=datetime.fromisoformat(gain['start']),datetime.fromisoformat(gain['end'])
                if a<start<b:result['boundary_intervals_excluded']+=1
                if a>=start and b<=now and b>a and (last_interval_end is None or a>=last_interval_end):
                    amount=fraction(gain['value']);duration=elapsed_seconds(a,b)
                    total+=amount;coverage+=duration;last_interval_end=b;result['intervals']+=1
                    basis=gain['basis'];result['basis_counts'][basis]=result['basis_counts'].get(basis,0)+1
                    versions.add(gain['requirement']['version'])
                    for bucket in bins:
                        left=max(a,datetime.fromisoformat(bucket['start']));right=min(b,datetime.fromisoformat(bucket['end']))
                        if right<=left:continue
                        overlap=elapsed_seconds(left,right)
                        bucket['amount']=(bucket['amount'] or Fraction(0))+amount*overlap/duration
                        bucket['coverage']+=overlap;bucket['intervals']+=1
            previous=point if eligible else None;previous_row=row if eligible else None
        previous_run=run
    except HistoryLimit:
        limited=True
    if limited:
        # Incomplete causal replay must not masquerade as a complete query or zero.
        result.update(status='history_limit',tracked_exp=None,basis_counts={});versions.clear()
        bins=[dict(b,amount=None,coverage=Fraction(0),intervals=0) for b in bins]
        coverage=Fraction(0);result['intervals']=0
    elif result['intervals']:result['tracked_exp']=rational(total)
    result.update(coverage_seconds=rational(coverage),unknown_seconds=rational(Fraction(86400)-coverage),requirement_versions=sorted(versions),
        buckets=[dict(start=b['start'],end=b['end'],value=rational(b['amount']) if b['amount'] is not None else None,
            covered=rational(b['coverage']),intervals=b['intervals'],
            state='missing' if b['amount'] is None else 'covered' if b['coverage']==1800 else 'partial') for b in bins])
    return result
