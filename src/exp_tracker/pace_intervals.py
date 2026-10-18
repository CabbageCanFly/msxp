"""Consumer endpoint evidence only. Never supplies chart, window or Store gains."""
from datetime import datetime
from decimal import Decimal

from .diagnostic_evidence import consistency,full_reading,CONTEXT_SECONDS
from .diagnostic_percentage import boundary,LARGE_CHANGE_BP
from .diagnostic_progress import percentage_point
from .shadow_grammar import interpret_exp

POLICY='endpoint_pace_v1'
RECOVERY_POLICY='conditional_percent_v1'


def conditional_percent(row, support, previous):
    """A unique punctuation hypothesis needs independent prior reader context."""
    hypotheses=interpret_exp(row.get('raw_text'))['symbol_hypotheses']
    if not hypotheses:return None
    result=dict(policy=RECOVERY_POLICY,event_id=row['event_id'],raw_text=row.get('raw_text'),
        status='rejected',reason='ambiguous_symbol_interpretation',trusted=False,
        numerical_identity_verified=False,proposals=hypotheses)
    if len(hypotheses)!=1:return result
    proposal=hypotheses[0];full=proposal['reading']
    result.update(reading=full,interpretation=proposal['interpretation'],edits=proposal['edits'])
    if len(support)<2 or previous is None:
        result['reason']='two_prior_supported_readings_and_temporal_reference_required';return result
    hashes=[p.get('frame_sha256') for p in support]+[row.get('frame_sha256')]
    if not all(hashes) or len(set(hashes))!=3:
        result['reason']='distinct_source_frames_required';return result
    level=support[-1]['level']['value'];evidence=row.get('experimental_level') or {}
    result.update(level=level,support_event_ids=[p['event_id'] for p in support])
    ages=[(datetime.fromisoformat(row['received_at'])-datetime.fromisoformat(p['timestamp'])).total_seconds() for p in support]
    if not all(0<age<=CONTEXT_SECONDS for age in ages) or any(p['level']['value']!=level for p in support):
        result['reason']='recent_matching_level_support_required';return result
    if (evidence.get('value') not in (None,level) or evidence.get('visual') not in (None,level)
            or evidence.get('neural') not in (None,level)):
        result['reason']='competing_current_level';return result
    checked=consistency(full,level);result['exp_validity']=checked
    if checked['status']!='consistent':
        result['reason']='full_pair_not_arithmetically_supported';return result
    bp=int(Decimal(full['percentage'])*100)
    if (not 0<=bp-previous['bp']<LARGE_CHANGE_BP
            or previous['exp'] is not None and int(full['exp'])<int(previous['exp'])):
        result['reason']='temporal_numeric_contradiction';return result
    result.update(status='eligible_experimental',reason='unique_syntax_recent_level_arithmetic_and_temporal_support',
        value=dict(event_id=row['event_id'],timestamp=row['received_at'],percentage=full['percentage'],bp=bp,
            exp=full['exp'],estimated_exp=None,exp_validity=checked,evidence='conditional_symbol',
            grammar_policy=RECOVERY_POLICY,fresh_at_capture=True,simulated=False,trusted=False,
            level=dict(value=level,status='conditional_context',reason='prior_reader_supported_level',
                policy=RECOVERY_POLICY,support_event_ids=result['support_event_ids'],trusted=False)))
    return result


def collect(snapshot, *, now, read, max_interval_seconds):
    """Keep disjoint intervals, clearing only the subtraction anchor at unsafe rows.

    ``read`` is the existing product reading decoder, not a new numerical parser.
    """
    edges=[];recoveries=[];excluded=[];previous=None;prior_attempt=None;support=[];holes=[]
    seen_events=set();seen_frames=set();epoch=0;identity=None;level=None;last_value=None;unrecorded=0
    reviews={r['event_id']:r for r in snapshot['percentage_progress']['percentage_reviews']}
    for row in snapshot['observations']:
        evidence=row.get('experimental_level') or {};stamp=row.get('received_at') or row.get('attempted_at')
        context=dict(channel=row.get('assigned_channel') or row.get('channel'),source_channel=row.get('channel'),
            source_kind=row.get('source_kind'),source_identity=row.get('source_identity'),
            character_id=row.get('character_id'),session_id=row.get('session_id'),run_id=row.get('run_id'),
            index=row.get('index'),coordinator_instance=row.get('coordinator_instance'),timestamp=stamp,
            interval_seconds=row.get('interval_seconds',15),level=evidence.get('value'))
        key=tuple(context[k] for k in ('channel','source_channel','source_kind','source_identity','character_id','session_id'))
        hard=None;edge=None
        try:
            when=datetime.fromisoformat(stamp)
            if when.utcoffset() is None or when>now or row.get('timestamp_ordered') is False:raise ValueError
            if prior_attempt:edge=boundary(prior_attempt,context,row)
        except (TypeError,ValueError,KeyError):hard='invalid_or_future_timestamp'
        if identity is not None and key!=identity:
            epoch+=1;previous=None;support=[];holes=[];level=None
        identity=key
        if (prior_attempt and prior_attempt['run_id']==context['run_id']
                and type(context['index']) is int and type(prior_attempt['index']) is int):
            unrecorded+=max(0,context['index']-prior_attempt['index']-1)
        if edge in ('source_changed','character_or_session_changed','run_boundary','nonincreasing_timestamp'):
            hard=edge
            if edge=='run_boundary':epoch+=1
        frame=row.get('frame_sha256')
        if row['event_id'] in seen_events or frame and frame in seen_frames:hard='duplicate_capture'
        seen_events.add(row['event_id'])
        if frame:seen_frames.add(frame)
        if (row.get('crop_suspect') or row.get('candidate_invalid') or row.get('percentage_only_invalid')
                or row.get('timing_mode')=='simulated' or (row.get('hud_count') or 0)>1
                or (row.get('neural_level') or {}).get('source_complete') is False
                or row.get('status')=='stale_local_frame'):
            hard='unsafe_source_or_numerical_evidence'
        if evidence.get('status')=='conflict':hard='unresolved_level_conflict'
        fresh=row.get('fresh_at_capture') is True and row.get('capture_acquired') is True and row.get('hud_count')==1
        if not hard and row.get('exp_validity',{}).get('status')=='invalid':hard='incompatible_full_exp'
        if hard=='incompatible_full_exp' and evidence.get('value') not in (None,level):hard='unresolved_level_conflict'
        if not hard and fresh and evidence.get('value') is not None:
            if level is not None and evidence['value']!=level:
                epoch+=1;hard='level_changed'
            level=evidence['value']
        decision=reviews[row['event_id']]
        if decision.get('break_before') and not hard:
            hard=decision['break_before']
        if hard:
            previous=None;holes=[];unrecorded=0
            if hard!='incompatible_full_exp':support=[]
        value=read(row);point,invalid=percentage_point(row)
        baseline_only=hard in ('run_boundary','source_changed','character_or_session_changed','level_changed',
            'confirmed_change_new_baseline','excluded_suspected_ocr_interval')
        usable=bool((not hard or baseline_only) and fresh and point and invalid is None and decision['progress_eligible'])
        recovery=None
        if fresh and not hard:
            recovery=conditional_percent(row,support,previous or last_value)
            if recovery:
                recoveries.append(recovery)
                if recovery['status']=='eligible_experimental':
                    recovery['starts_new_baseline']=previous is None
                    value=recovery['value'];usable=True
        elif interpret_exp(row.get('raw_text'))['symbol_hypotheses']:
            recoveries.append(dict(policy=RECOVERY_POLICY,event_id=row['event_id'],status='rejected',
                raw_text=row.get('raw_text'),reason=hard or 'fresh_unique_source_required',trusted=False))
        # A pending matching-level reacquisition is not an endpoint, but neither
        # is it affirmative evidence of a different level.
        matching_pending=bool(previous and fresh and invalid=='visual_level_unavailable'
            and evidence.get('status')=='pending' and evidence.get('neural')==previous['level']['value']
            and evidence.get('visual') in (None,previous['level']['value']) and decision['public_eligible']
            and consistency(full_reading(row),previous['level']['value'])['status']!='invalid')
        unreadable=(row.get('status')=='capture_failed' or
            row.get('status')=='unavailable' and row.get('hud_count')==0 and row.get('reasons')==['missing_hud']
            and row.get('local_age_seconds') is not None and row['local_age_seconds']<=15 or
            fresh and point is None and recovery is None and evidence.get('status') not in ('conflict','pending'))
        if usable and value:
            if previous:
                elapsed=(datetime.fromisoformat(value['timestamp'])-datetime.fromisoformat(previous['timestamp'])).total_seconds()
                ordered=(value['level']['value']==previous['level']['value'] and 0<elapsed<=max_interval_seconds
                    and 0<=value['bp']-previous['bp']<LARGE_CHANGE_BP
                    and not (value['exp'] is not None and previous['exp'] is not None and int(value['exp'])<int(previous['exp'])))
                if ordered:
                    missing=[h['event_id'] for h in holes]
                    kind='endpoint_supported' if holes or unrecorded or edge in ('missing_attempt','sampling_gap') else 'direct'
                    edges.append(dict(before=previous,after=value,epoch=epoch,identity=key,kind=kind,
                        missing_event_ids=missing,unrecorded_attempts=unrecorded))
                else:
                    support=[]
                    excluded.append(dict(event_id=row['event_id'],reason='incompatible_endpoints_or_interval_limit'))
            previous=value;last_value=value;holes=[];unrecorded=0
            if evidence.get('status') in ('agreement','provisional_neural') and value['evidence']!='conditional_symbol':
                support=(support+[dict(value,frame_sha256=frame)])[-2:]
        elif not hard and (unreadable or matching_pending):
            holes.append(dict(event_id=row['event_id']))
        else:
            numerical_boundary=(hard=='incompatible_full_exp' or not hard and fresh and point
                and invalid is None and not decision['progress_eligible'] and evidence.get('value')==level)
            previous=None;holes=[];unrecorded=0
            if not numerical_boundary:support=[]
            excluded.append(dict(event_id=row['event_id'],reason=hard or decision['reason'] or invalid))
        prior_attempt=context
    return dict(intervals=edges,recoveries=recoveries,excluded=excluded,epoch=epoch,
        latest=last_value,pending_missing=len(holes)+unrecorded,identity=identity)
