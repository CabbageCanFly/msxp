"""Revised presentation/accounting from retained, originally trusted OCR inputs."""
from datetime import datetime
import json

from .models import Reading
from .validation import Observation,Transition,validate_transition

# shortcut: replay at most 65,536 trusted rows per session; checkpoint this if larger recordings are needed.
MAX_ROWS=65536


def replay(store, session_id):
    if store.schema_version<7 or session_id is None:return None
    if not store.db.execute("SELECT 1 FROM reading_validity WHERE kind='observation' AND session_id=? LIMIT 1",(session_id,)).fetchone():return None
    rows=store.db.execute('SELECT * FROM observations WHERE session_id=? ORDER BY id LIMIT ?',(session_id,MAX_ROWS+1)).fetchall()
    if len(rows)>MAX_ROWS:return dict(unavailable=True,rows=[],last=None,last_event_at=None,broken=True,pending=0,gain=None,bridged=None)
    invalid={r[0] for r in store.db.execute("SELECT source_id FROM reading_validity WHERE kind='observation' AND action='invalidate' AND session_id=?",(session_id,))}
    session=store.db.execute('SELECT * FROM sessions WHERE id=?',(session_id,)).fetchone()
    login=store.db.execute('SELECT login FROM streamers WHERE id=?',(session['streamer_id'],)).fetchone()[0]
    boundaries=[e['effective_at'] for e in store.manual_history(login,character_id=session['character_id'],active_only=True) if e['session_id']==session_id]
    result=[];last=None;event_at=None;broken=True;pending=0;gain=0;bridged=0
    for source in rows:
        row=dict(source);raw=json.loads(row['diagnostic_json']);status=raw.get('status')
        if row['id'] in invalid:
            # Removing OCR cannot remove an explicit capture pause or an uncalibrated source boundary.
            if status in ('offline','paused') or row['reason']=='glyph_profile_required':broken=True;pending=0
            else:pending+=1
            continue
        ordered=event_at is None or row['observed_at']>event_at
        if not ordered:continue
        event_at=row['observed_at']
        if row['outcome'] not in ('accepted','baseline'):
            soft=bool(row['profile_hash'] and status in ('unreadable','missing_hud','low_confidence','invalid','ambiguous'))
            if soft:pending+=1
            else:broken=True;pending=0
            continue
        prior=last
        if prior and any(prior['observed_at']<=b<row['observed_at'] for b in boundaries):prior=None
        before=Observation(str(row['character_id']),datetime.fromisoformat(prior['observed_at']),
            Reading(prior['level'],prior['current_exp'],prior['percentage_bp']/100)) if prior else None
        current=Observation(str(row['character_id']),datetime.fromisoformat(row['observed_at']),
            Reading(row['level'],row['current_exp'],row['percentage_bp']/100))
        transition=validate_transition(before,current)
        if transition.status=='accepted' and (broken or row['outcome']=='baseline'):
            transition=Transition('baseline','retained_original_boundary')
        row.update(outcome=transition.status,reason=transition.reason,gained_exp=transition.gained_exp,
            interval_start_observation_id=prior['id'] if transition.status=='accepted' else None,
            missing_observations=pending if transition.status=='accepted' else 0)
        result.append(row)
        if transition.status in ('accepted','baseline'):
            last=row;broken=False;pending=0
            gain+=row['gained_exp'] or 0
            if row['missing_observations']:bridged+=row['gained_exp'] or 0
        else:broken=True;pending=0
    return dict(unavailable=False,rows=result,last=last,last_event_at=event_at,broken=broken,pending=pending,gain=gain,bridged=bridged)


def present(store, snapshot, now):
    from .statistics import tracking_statistics
    session=snapshot['session'];old=snapshot['last_trusted']
    value=replay(store,session['id'] if session else old['session_id'] if old else None)
    previous_session=False
    if value is None and session and old and old['session_id']!=session['id']:
        value=replay(store,old['session_id'])
        previous_session=value is not None
    if value is None:return snapshot
    snapshot['original_accounting']={k:snapshot[k] for k in ('last_trusted','observed_session_exp','bridged_session_exp','statistics','status','reason','last_event_at')}
    snapshot['accounting_source']='retained_trusted_ocr_replay'
    snapshot['accounting_status']='history_limit' if value['unavailable'] else 'revised'
    last=value['last']
    snapshot.update(last_trusted={k:last[k] for k in ('id','session_id','observed_at','level','current_exp','percentage_bp')} if last else None,
        observed_session_exp=value['gain'] if session and not previous_session else 0,
        bridged_session_exp=value['bridged'] if session and not previous_session else 0)
    if not previous_session:
        snapshot.update(continuity_broken=value['broken'],pending_missing_observations=value['pending'],last_event_at=value['last_event_at'])
    age=max(0,(now-datetime.fromisoformat(last['observed_at'])).total_seconds()) if last else None
    snapshot.update(age_seconds=age,stale=age is None or age>120,
        status=('tracking' if last and not value['broken'] and age<=120 else 'paused') if session and not previous_session else snapshot['status'],
        reason='reading_history_limit' if value['unavailable'] else 'reading_invalidation_replay')
    snapshot['statistics']=tracking_statistics(store.db,snapshot,now,revised_rows=[] if previous_session else value['rows'])
    return snapshot
