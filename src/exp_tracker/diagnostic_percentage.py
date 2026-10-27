"""Causal experimental percentage quarantine. Never changes capture evidence or Store state."""
from datetime import datetime,timedelta
from fractions import Fraction
import re

from .diagnostic_evidence import consistency,full_reading

POLICY='percentage_continuity_v2'
CONFIRM_SECONDS=60
LARGE_CHANGE_BP=1000  # 10 percentage points: evidence gate, not an EXP gain/rate cap.
PERCENTAGE_CONTEXT_SECONDS=180  # Saved supports span 156.765s over four attempt steps.
PERCENTAGE_CONTEXT_STEPS=4  # Two strict supports, at most two intervening unreadable captures.
CONTEXT_KEYS=('channel','source_channel','source_kind','source_identity','character_id','session_id','run_id','manual_epoch')


def _context_capture(row):
    capture={k:row.get(k) for k in (*CONTEXT_KEYS,'index')}
    capture.update(channel=row.get('assigned_channel') or row.get('channel'),source_channel=row.get('channel'),
        timestamp=row.get('received_at') or row.get('attempted_at'),level=(row.get('experimental_level') or {}).get('value'))
    return capture


def boundary(before,point,row):
    elapsed=(datetime.fromisoformat(point['timestamp'])-datetime.fromisoformat(before['timestamp'])).total_seconds()
    rotated=(point['run_id']!=before['run_id'] and row.get('rotation_from')==before['run_id']
        and before['index']==60 and point['index']==1
        and point['source_identity'] is not None and point['source_identity']==before['source_identity']
        and point['coordinator_instance'] is not None and point['coordinator_instance']==before['coordinator_instance'])
    return ('manual_correction' if point.get('manual_epoch')!=before.get('manual_epoch') else
        'source_changed' if any(point[k]!=before[k] for k in ('channel','source_channel','source_kind','source_identity')) else
        'character_or_session_changed' if any(point[k]!=before[k] for k in ('character_id','session_id')) else
        'run_boundary' if point['run_id']!=before['run_id'] and not rotated else
        'level_changed' if point['level']!=before['level'] else
        'nonincreasing_timestamp' if elapsed<=0 else
        'missing_attempt' if not rotated and point['index']!=before['index']+1 else
        'sampling_gap' if elapsed>min(120,Fraction(str(before['interval_seconds']))*Fraction(3,2)) else None)


def review(rows,evidence,*,now,confirmation_seconds=CONFIRM_SECONDS,state=None):
    """Separate eligible captures corroborate a baseline, not statistical independence or cause."""
    if type(confirmation_seconds) is not int or not 1<=confirmation_seconds<=60:raise ValueError('Confirmation span must be 1..60 seconds')
    anchor=pending=previous=None
    seen=set();result=[];quarantined_at=None;strict_percentage_context=[];context_previous=None;context_frames=[]
    if state:
        anchor=state['anchor'];pending=state['pending'];previous=state['previous']
        seen=state['seen'];quarantined_at=state['quarantined_at']
        strict_percentage_context=state.get('strict_percentage_context',[])
        context_previous=state.get('percentage_context_previous')
        context_frames=state.get('percentage_context_frames',[])
    def record(value):
        nonlocal quarantined_at,strict_percentage_context,context_previous,context_frames
        if value['public_eligible']:quarantined_at=None
        elif value['pending_since'] and quarantined_at is None:quarantined_at=datetime.fromisoformat(value['pending_since'])
        value['verification_deadline']=(quarantined_at+timedelta(seconds=confirmation_seconds)).isoformat() if quarantined_at else None
        if value['break_before'] or edge not in (None,'sampling_gap'):strict_percentage_context=[]
        if (point and value['progress_eligible'] and point['evidence']=='strict_percentage_only' and safe_capture):
            strict_percentage_context=(strict_percentage_context+[dict(point=point,frame=row['frame_sha256'])])[-2:]
        elif not (unreadable or safe_capture and point and value['progress_eligible'] and (
                value.get('percentage_only_context',{}).get('supported')
                or point['evidence']=='grammar_recovered' and
                    re.fullmatch(r'\[[0-9]{1,2}\.[0-9]{2}%[1|)]',point['raw_text'] or ''))):
            strict_percentage_context=[]
        context_previous=capture
        context_frames=(context_frames+[row['frame_sha256']])[-5:] if strict_percentage_context else []
        result.append(value)
    for row,(point,invalid) in zip(rows,evidence):
        if point:point['interval_seconds']=row.get('interval_seconds',15)
        value=dict(policy=POLICY,event_id=row.get('event_id'),status='accepted_observation',reason=invalid,
            public_eligible=False,progress_eligible=False,break_before=None,resolves_event_id=None,
            pending_since=None,confirmation_deadline=None,eligibility_reason=invalid,
            candidate_percentage=point['percentage'] if point else None)
        if row.get('event_id') in seen:invalid='duplicate_event'
        seen.add(row.get('event_id'))
        when=datetime.fromisoformat(point['timestamp']) if point and point.get('timestamp') and invalid not in ('timestamp_unavailable_or_out_of_order',) else None
        if when and when>now:invalid='future_timestamp'
        edge=boundary(previous,point,row) if previous and point and invalid is None else None
        capture=_context_capture(row)
        try:
            captured_at=datetime.fromisoformat(capture['timestamp'])
            ordered=captured_at.utcoffset() is not None and captured_at<=now and row.get('timestamp_ordered') is not False
            linked=(context_previous is not None and ordered and type(capture['index']) is int
                and capture['index']==context_previous['index']+1
                and captured_at>datetime.fromisoformat(context_previous['timestamp'])
                and all(capture[k]==context_previous[k] for k in CONTEXT_KEYS))
        except (TypeError,ValueError):ordered=linked=False
        safe_capture=(ordered and row.get('frame_sha256') and row['frame_sha256'] not in context_frames
            and not row.get('crop_suspect') and row.get('timing_mode')!='simulated'
            and not row.get('reading_invalidated') and not row.get('manual_point')
            and not row.get('candidate_invalid') and not row.get('percentage_only_invalid')
            and (row.get('neural_level') or {}).get('source_complete') is not False
            and row.get('exp_validity',{}).get('status')!='invalid'
            and (row.get('local_age_seconds') is None or row['local_age_seconds']<=15))
        unreadable=(safe_capture and point is None and invalid=='invalid_or_ambiguous_percentage'
            and not row.get('candidate') and not row.get('percentage_only_candidate')
            and (row.get('fresh_at_capture') is True and row.get('capture_acquired') is True
                and row.get('status')=='malformed_or_unavailable' and row.get('hud_count')==1
                or row.get('status') in ('unavailable','missing_hud') and row.get('reasons')==['missing_hud']
                and row.get('hud_count') in (None,0) and not row.get('raw_text')
                and row.get('visual_level') is None and (row.get('neural_level') or {}).get('level') is None))
        if strict_percentage_context:
            support=strict_percentage_context[-1]['point']
            claims=(capture['level'],row.get('visual_level'),(row.get('neural_level') or {}).get('level'))
            if (not linked or not safe_capture or any(level not in (None,support['level']) for level in claims)):
                strict_percentage_context=[];context_frames=[]
            else:
                strict_percentage_context=[c for c in strict_percentage_context if
                    0<(captured_at-datetime.fromisoformat(c['point']['timestamp'])).total_seconds()<=PERCENTAGE_CONTEXT_SECONDS
                    and 0<capture['index']-c['point']['index']<=PERCENTAGE_CONTEXT_STEPS]
        if point and point.get('requires_percentage_only_context'):
            frames=[c['frame'] for c in strict_percentage_context]+[row.get('frame_sha256')]
            keys=(*CONTEXT_KEYS,'level')
            supported=(invalid is None and edge in (None,'sampling_gap') and pending is None
                and len(strict_percentage_context)==2 and all(frames) and len(set(frames))==3
                and all(all(c['point'][k]==point[k] for k in keys) and
                    0<(when-datetime.fromisoformat(c['point']['timestamp'])).total_seconds()<=PERCENTAGE_CONTEXT_SECONDS
                    for c in strict_percentage_context))
            value['percentage_only_context']=dict(policy='leading_one_percentage_v3',supported=supported,
                support_event_ids=[c['point']['event_id'] for c in strict_percentage_context],
                max_age_seconds=PERCENTAGE_CONTEXT_SECONDS,max_attempt_steps=PERCENTAGE_CONTEXT_STEPS)
            if supported:point['comparison_eligible']=True
            else:invalid='percentage_bracket_context_required';value['eligibility_reason']=invalid
        if anchor and point:
            if point.get('manual_epoch')!=anchor['point'].get('manual_epoch'):
                anchor=pending=None;strict_percentage_context=[]
        if anchor and point:
            changed=any(point[k]!=anchor['point'][k] for k in ('channel','source_channel','source_kind','source_identity','character_id','session_id'))
            if (changed or invalid is None and point['level'] is not None and point['level']!=anchor['level']
                    or point['run_id']!=anchor['point']['run_id'] and (previous is None or edge=='run_boundary')):anchor=pending=None
        prior_pending=pending
        if invalid or edge:pending=None
        value.update(reference_event_id=anchor['point']['event_id'] if anchor else None,
            reference_percentage=anchor['point']['percentage'] if anchor else None)
        if invalid:
            value.update(reason=invalid,status='unresolved_numerical_continuity')
            # Preserve legacy unknown-level display, without using it as a gain baseline.
            value['public_eligible']=bool(point and invalid in ('visual_level_unavailable','level_evidence_conflict')
                and (anchor is None or 0<=point['bp']-anchor['point']['bp']<LARGE_CHANGE_BP))
            if value['public_eligible']:
                value['status']='accepted_observation'
                if prior_pending:value.update(resolves_event_id=prior_pending['point']['event_id'],resolution='suspected_ocr_anomaly',break_before='excluded_suspected_ocr_interval')
                anchor=dict(point=point,row=row,level=anchor['level'] if anchor else None)
            elif point and anchor and invalid in ('visual_level_unavailable','level_evidence_conflict'):
                pending=dict(point=point,row=row,since=when,direction='down' if point['bp']<anchor['point']['bp'] else 'up',
                    large=anchor['point']['bp']-point['bp']>=LARGE_CHANGE_BP)
                value.update(pending_since=when.isoformat(),confirmation_deadline=(when+timedelta(seconds=confirmation_seconds)).isoformat(),
                    reason='decrease_with_unresolved_level' if pending['direction']=='down' else 'large_increase_with_unresolved_level')
            previous=None;record(value);continue
        if edge=='nonincreasing_timestamp':
            value.update(reason=edge,status='unresolved_numerical_continuity');previous=None;record(value);continue
        value.update(public_eligible=True,progress_eligible=True,reason=edge or 'eligible_observation')
        if anchor:
            difference=point['bp']-anchor['point']['bp']
            if pending:
                first=pending['point'];expired=(when-pending['since']).total_seconds()>confirmation_seconds
                lower=point['bp']<anchor['point']['bp']
                returned=(not lower if pending['direction']=='down' else point['bp']<first['bp'])
                independent=(row.get('frame_sha256') is not None and pending['row'].get('frame_sha256') is not None
                    and row['frame_sha256']!=pending['row']['frame_sha256'])
                clean=all(p['comparison_eligible'] and r.get('crop_suspect') is not True
                    and (p['evidence']!='grammar_recovered' or consistency(full_reading(r),p['level'])['status']=='consistent')
                    for p,r in ((point,row),(first,pending['row'])))
                if returned:
                    value.update(resolves_event_id=first['event_id'],resolution='suspected_ocr_anomaly')
                    if 0<=difference<LARGE_CHANGE_BP:value['break_before']='excluded_suspected_ocr_interval'
                    pending=None
                elif (not expired and not (pending['direction']=='down' and (pending['large'] or anchor['point']['bp']-point['bp']>=LARGE_CHANGE_BP))
                        and independent and clean and point['bp']>=first['bp']):
                    value.update(status='corroborated_lower_baseline' if lower else 'accepted_observation',
                        reason='two_distinct_eligible_captures_cause_unverified',resolves_event_id=first['event_id'],
                        break_before='confirmed_change_new_baseline')
                    pending=None
                else:
                    value.update(public_eligible=False,progress_eligible=False,status='unresolved_numerical_continuity',
                        reason='confirmation_expired' if expired else 'large_decrease_requires_independent_evidence' if lower and -difference>=LARGE_CHANGE_BP else 'insufficient_independent_confirmation')
                    if expired:pending=None
                    else:pending.update(point=point,row=row,large=pending['large'] or -difference>=LARGE_CHANGE_BP)
            if pending is None and value['public_eligible'] and value['break_before'] is None and (difference<0 or difference>=LARGE_CHANGE_BP):
                pending=dict(point=point,row=row,since=when,direction='down' if difference<0 else 'up',large=-difference>=LARGE_CHANGE_BP)
                value.update(public_eligible=False,progress_eligible=False,
                    status='unresolved_numerical_continuity' if difference<=-LARGE_CHANGE_BP else 'pending_exp_decrease' if difference<0 else 'pending_large_increase',
                    reason='large_decrease_requires_independent_evidence' if difference<=-LARGE_CHANGE_BP else 'second_capture_required')
            elif pending is None and not value['public_eligible']:
                # Expiry never turns a single still-lower observation into a new public baseline.
                pending=dict(point=point,row=row,since=when,direction='down' if difference<0 else 'up',large=-difference>=LARGE_CHANGE_BP)
        if value['public_eligible']:anchor=dict(point=point,row=row,level=point['level'])
        if pending:
            value.update(pending_since=pending['since'].isoformat(),
                confirmation_deadline=(pending['since']+timedelta(seconds=confirmation_seconds)).isoformat())
        previous=point;record(value)
    if state is not None:state.update(anchor=anchor,pending=pending,previous=previous,seen=seen,quarantined_at=quarantined_at,
        strict_percentage_context=strict_percentage_context,percentage_context_previous=context_previous,
        percentage_context_frames=context_frames)
    if result and result[-1]['verification_deadline'] and now>datetime.fromisoformat(result[-1]['verification_deadline']):
        result[-1].update(status='unresolved_numerical_continuity',reason='confirmation_expired')
    return result
