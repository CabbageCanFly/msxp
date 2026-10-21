"""Shared experimental endpoint evidence. Never supplies trusted Store gains."""
from datetime import datetime
from decimal import Decimal
from fractions import Fraction

from .diagnostic_evidence import consistency,full_reading,supported_exp,CONTEXT_SECONDS
from .diagnostic_percentage import boundary,LARGE_CHANGE_BP
from .diagnostic_progress import percentage_point,rational,elapsed_seconds
from .exp_requirements import requirement
from .shadow_grammar import interpret_exp

POLICY='endpoint_pace_v3'
RECOVERY_POLICY='conditional_percent_v1'
TRACKED_POLICY='tracked_endpoint_exp_v5'
PUBLIC_POLICY='public_endpoint_window_v2'
# Longest live window plus causal warmup; age by replay time, never query time.
FRAME_HISTORY_SECONDS=24*60*60+5*60


def exp_interval(edge):
    """One nonnegative same-level EXP interval, independent of lookback length."""
    a,b=edge['before'],edge['after'];req=requirement(b['level']['value'])
    if req['to_next'] is None or a['level']['value']!=b['level']['value']:return None
    direct=all(supported_exp(p) for p in (a,b))
    gain=Fraction(int(b['exp'])-int(a['exp'])) if direct else Fraction((b['bp']-a['bp'])*req['to_next'],10000)
    if gain<0:return None
    return dict(start=a['timestamp'],end=b['timestamp'],first_event_id=a['event_id'],last_event_id=b['event_id'],
        level=b['level']['value'],value=rational(gain),requirement=req,identity=edge['identity'],
        basis='observed_exp_endpoints' if direct else 'displayed_percentage_endpoints',kind=edge['kind'],
        evidence_types=sorted({a['evidence'],b['evidence']}),
        missing_event_ids=edge['missing_event_ids'],unrecorded_attempts=edge['unrecorded_attempts'],
        policy=TRACKED_POLICY,trusted=False,**({'restart':edge['restart']} if edge.get('restart') else {}))


def tracked_window(intervals,*,start,end,level=None):
    """Whole eligible intervals only; never prorate a gain at a lookback boundary."""
    selected=[g for g in intervals if (level is None or g['level']==level)
        and start<=datetime.fromisoformat(g['start'])<datetime.fromisoformat(g['end'])<=end]
    amount=sum((Fraction(g['value']['numerator'],g['value']['denominator']) for g in selected),Fraction(0))
    coverage=sum((elapsed_seconds(datetime.fromisoformat(g['start']),datetime.fromisoformat(g['end'])) for g in selected),Fraction(0))
    result=dict(available=bool(selected),gain=rational(amount) if selected else None,policy=TRACKED_POLICY,
        window_start=start.isoformat(),window_end=end.isoformat(),trusted=False,
        scope='selected_character_independent_sessions_and_sources',intervals=len(selected))
    if not selected:return dict(result,observed=dict(available=False))
    ids={g[k] for g in selected for k in ('first_event_id','last_event_id')}
    interruptions=sum(a['last_event_id']!=b['first_event_id'] for a,b in zip(selected,selected[1:]))
    first,last=selected[0],selected[-1]
    return dict(result,observed=dict(available=True,start=first['start'],end=last['end'],readings=len(ids),
        coverage_seconds=rational(coverage),span_seconds=rational(elapsed_seconds(datetime.fromisoformat(first['start']),datetime.fromisoformat(last['end']))),
        interruptions=interruptions,unavailable_attempts=len({i for g in selected for i in g['missing_event_ids']}),
        missing_attempts=sum(g['unrecorded_attempts'] for g in selected),
        estimated_exp=dict(value=rational(amount),basis=TRACKED_POLICY,requirement=last['requirement']),
        difference_percentage_points=None,age_seconds=max(0,(end-datetime.fromisoformat(last['end'])).total_seconds()),
        historical=False,paused=False,policy=TRACKED_POLICY,trusted=False))


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


def endpoint_interval(before,after):
    """Net EXP in level/EXP coordinates; no capture-connection eligibility."""
    if before.get('manual_epoch') != after.get('manual_epoch'):
        return None,'manual_correction'
    if not same_character(before,after):
        return None,'character_or_session_changed'
    a,b=before['level']['value'],after['level']['value']
    if a is None or b is None:return None,'level_unavailable'
    if b<a:return None,'observed_level_decrease'
    required=[requirement(level) for level in range(a,b)]
    if any(r['to_next'] is None for r in required):return None,'level_transition_requirement_unavailable'
    values=[]
    for point in (before,after):
        total=requirement(point['level']['value'])['to_next']
        if point['exp'] is None and total is None:return None,'percentage_requirement_unavailable'
        # Match the whole-EXP estimate shown at each percentage-only graph point.
        values.append(Fraction(int(point['exp'])) if point['exp'] is not None else Fraction((point['bp']*total+5000)//10000))
    gain=values[1]-values[0]+sum(r['to_next'] for r in required)
    numeric=all(p['exp'] is not None for p in (before,after))
    basis='observed_exp_endpoints' if numeric else 'displayed_percentage_endpoints' if all(p['exp'] is None for p in (before,after)) else 'mixed_exp_and_percentage_endpoints'
    return dict(start=before['timestamp'],end=after['timestamp'],first_event_id=before['event_id'],last_event_id=after['event_id'],
        level=b,value=rational(gain),requirement=requirement(b),requirements=required,
        basis=basis,kind='endpoint_supported',transition_gain_included=b>a,
        evidence_types=sorted({before['evidence'],after['evidence']}),policy=PUBLIC_POLICY,trusted=False),None


def usable_endpoint(point):
    level=point['level']['value']
    return (level is not None and point.get('exp_validity',{}).get('level') in (None,level)
            and (point['exp'] is not None or requirement(level)['to_next'] is not None))


def same_character(before,after):
    # Scope was character:session in older persisted checkpoints; character IDs are Store-global.
    a=str(before.get('accounting_scope') or '').partition(':')[0]
    b=str(after.get('accounting_scope') or '').partition(':')[0]
    return a not in ('','None') and a==b


def window_endpoints(points,*,start,end,level=None):
    """Sum disjoint nonnegative intervals ending in the window and no longer than it."""
    ordered=sorted((p for p in points if usable_endpoint(p) and datetime.fromisoformat(p['timestamp'])<=end),
                   key=lambda p:datetime.fromisoformat(p['timestamp']))
    used=[];gains=[];coverage=Fraction(0);reason='two_distinct_observation_times_required'
    for before,after in zip(ordered,ordered[1:]):
        a,b=datetime.fromisoformat(before['timestamp']),datetime.fromisoformat(after['timestamp'])
        if not start<=b<=end or b<=a:continue
        if b-a>end-start:
            reason='gap_exceeds_window';continue
        if level is not None and (before['level']['value']!=level or after['level']['value']!=level):continue
        gain,why=endpoint_interval(before,after)
        if gain is None:
            reason=why;continue
        if gain['value']['numerator']<0:
            reason='observed_exp_decrease';continue
        if not used or used[-1]['event_id']!=before['event_id']:used.append(before)
        used.append(after);gains.append(gain);coverage+=elapsed_seconds(a,b)
    if not gains:
        available=[p for p in points if start<=datetime.fromisoformat(p['timestamp'])<=end]
        if len(available)>=2 and sum(usable_endpoint(p) for p in available)<2:
            reason='level_unavailable' if any(p['level']['value'] is None for p in available) else 'percentage_requirement_unavailable'
        return [],None,reason
    return used,dict(gains[-1],start=used[0]['timestamp'],first_event_id=used[0]['event_id'],
        value=rational(sum((Fraction(g['value']['numerator'],g['value']['denominator']) for g in gains),Fraction(0))),
        coverage_seconds=rational(coverage),intervals=gains,
        manual_boundaries=any(a['last_event_id']!=b['first_event_id'] for a,b in zip(gains,gains[1:])),
        requirements=[r for g in gains for r in g['requirements']],
        transition_gain_included=any(g['transition_gain_included'] for g in gains),
        basis=gains[0]['basis'] if len({g['basis'] for g in gains})==1 else 'mixed_exp_and_percentage_endpoints'),None


def collect_observed(snapshot, *, now, read, max_interval_seconds, state=None):
    """Already-public observations. Failures never clear an endpoint.

    The diagnostic collector supplies conditional-symbol readings and duplicate
    detection, never its capture-gap or interval-inclusion decisions.
    """
    if state is None:state={}
    diagnostic=collect(snapshot,now=now,read=read,max_interval_seconds=max_interval_seconds,state=state.setdefault('diagnostic',{}))
    recovered={r['event_id']:r['value'] for r in diagnostic['recoveries'] if r['status']=='eligible_experimental'}
    duplicates={r['event_id'] for r in diagnostic['excluded'] if r['reason']=='duplicate_capture'}
    previous=state.get('previous');holes=state.get('holes',[]);edges=[];points=[];excluded=[]
    character=(snapshot.get('selected_character') or {}).get('id')
    last_time=state.get('last_time') or (previous['timestamp'] if previous else None)
    for row in snapshot['observations']:
        value=recovered.get(row['event_id']) or read(row)
        if value and value['fresh_at_capture'] and not value['simulated'] and row['event_id'] not in duplicates and row.get('timestamp_ordered') is not False and not row.get('crop_suspect') and (character is None or row.get('character_id')==character):
            try:
                when=datetime.fromisoformat(value['timestamp'])
                if when.utcoffset() is None or when>now:raise ValueError
            except (TypeError,ValueError):continue
            if last_time and when<=datetime.fromisoformat(last_time):
                excluded.append(dict(event_id=row['event_id'],timestamp=value['timestamp'],reason='nonincreasing_timestamp'))
                continue
            last_time=value['timestamp']
            value=dict(value,source_kind=row.get('source_kind'),source_identity=row.get('source_identity'),run_id=row.get('run_id'),index=row.get('index'),
                accounting_scope=f"{row.get('character_id')}:{row.get('session_id')}")
            # A circular arithmetic level dip must not become a new subtraction baseline.
            if (previous and usable_endpoint(value) and same_character(previous,value)
                    and previous.get('manual_epoch')==value.get('manual_epoch')
                    and value['level'].get('status') in ('exp_derived','retained_level','provisional_level_up')
                    and value['level']['value']<previous['level']['value']):
                holes.append(row['event_id'])
                excluded.append(dict(event_id=row['event_id'],timestamp=value['timestamp'],reason='inferred_level_decrease'))
                continue
            points.append(value)
            if not usable_endpoint(value):continue
            if previous and previous.get('manual_epoch')==value.get('manual_epoch') and same_character(previous,value) and datetime.fromisoformat(previous['timestamp'])<when:
                edges.append(dict(before=previous,after=value,epoch=0,
                    identity=(row.get('assigned_channel') or row.get('channel'),row.get('channel'),row.get('source_kind'),row.get('source_identity'),row.get('character_id'),row.get('session_id')),
                    kind='endpoint_supported' if holes else 'direct',missing_event_ids=list(holes),
                    unrecorded_attempts=max(0,value['index']-previous['index']-1-len(holes)) if value['run_id']==previous.get('run_id') else 0))
            previous=value;holes=[]
        else:
            holes.append(row['event_id']);excluded.append(dict(event_id=row['event_id'],timestamp=row.get('received_at') or row.get('attempted_at'),reason='public_observation_unavailable'))
    state.update(previous=previous,holes=holes,last_time=last_time)
    return dict(points=points,intervals=edges,recoveries=diagnostic['recoveries'],excluded=excluded,epoch=0,
        latest=previous,pending_missing=len(holes),identity=edges[-1]['identity'] if edges else None)


def collect(snapshot, *, now, read, max_interval_seconds,state=None):
    """Keep disjoint intervals, clearing only the subtraction anchor at unsafe rows.

    ``read`` is the existing product reading decoder, not a new numerical parser.
    """
    edges=[];recoveries=[];excluded=[];previous=None;prior_attempt=None;support=[];holes=[]
    seen_events=set();seen_frames={};frame_time=None;epoch=0;identity=None;level=None;last_value=None;unrecorded=0;last_interval_end=None;numeric_gap=False
    if state:
        previous=state['previous'];prior_attempt=state['prior_attempt'];support=state['support'];holes=state['holes']
        seen_events=state['seen_events'];seen_frames=state['seen_frames'];epoch=state['epoch'];identity=state['identity']
        level=state['level'];last_value=state['last_value'];unrecorded=state['unrecorded']
        last_interval_end=state['last_interval_end']
        numeric_gap=state.get('numeric_gap',False)
        frame_time=state.get('frame_time')
    if isinstance(seen_frames,set):
        # Old checkpoints lack dates: conservatively grandfather once, without refreshing on restart.
        frame_time=min(datetime.fromisoformat(prior_attempt['timestamp']).timestamp(),now.timestamp()) if prior_attempt else now.timestamp()
        seen_frames=dict.fromkeys(sorted(seen_frames),frame_time)
    reviews={r['event_id']:r for r in snapshot['percentage_progress']['percentage_reviews']}
    for row in snapshot['observations']:
        evidence=row.get('experimental_level') or {};stamp=row.get('received_at') or row.get('attempted_at')
        context=dict(channel=row.get('assigned_channel') or row.get('channel'),source_channel=row.get('channel'),
            source_kind=row.get('source_kind'),source_identity=row.get('source_identity'),
            character_id=row.get('character_id'),session_id=row.get('session_id'),run_id=row.get('run_id'),
            index=row.get('index'),coordinator_instance=row.get('coordinator_instance'),timestamp=stamp,
            interval_seconds=row.get('interval_seconds',15),level=evidence.get('value'),manual_epoch=row.get('manual_epoch'),
            run_interrupted=row.get('run_interrupted') is True,
            operator_interrupted=row.get('status')=='capture_failed' and row.get('reasons')==['operator_interrupted'])
        key=tuple(context[k] for k in ('channel','source_channel','source_kind','source_identity','character_id','session_id'))
        hard=None;edge=None
        when=None
        try:
            when=datetime.fromisoformat(stamp)
            if when.utcoffset() is None or when>now or row.get('timestamp_ordered') is False:raise ValueError
            if prior_attempt:edge=boundary(prior_attempt,context,row)
        except (TypeError,ValueError,KeyError):hard='invalid_or_future_timestamp'
        if identity is not None and key!=identity:
            epoch+=1;previous=None;support=[];holes=[];level=None;numeric_gap=False
        identity=key
        if (prior_attempt and prior_attempt['run_id']==context['run_id']
                and type(context['index']) is int and type(prior_attempt['index']) is int):
            unrecorded+=max(0,context['index']-prior_attempt['index']-1)
        value=read(row);point,invalid=percentage_point(row)
        numeric_pair=bool(previous and value and all(supported_exp(p) for p in (previous,value)))
        restart=bool(hard is None and edge=='run_boundary' and numeric_pair and invalid is None
            and row.get('run_start_reason')=='process_start' and context['index']==1
            and prior_attempt['run_interrupted'] and prior_attempt['operator_interrupted']
            and context['source_kind']=='twitch' and context['source_identity'] and context['source_identity']==prior_attempt['source_identity']
            and all(context[k] is not None and context[k]==prior_attempt[k] for k in ('channel','source_channel','character_id','session_id'))
            and context['coordinator_instance'] and prior_attempt['coordinator_instance']
            and context['coordinator_instance']!=prior_attempt['coordinator_instance']
            and previous['level']['value']==value['level']['value']
            and when>datetime.fromisoformat(prior_attempt['timestamp'])
            and 0<(when-datetime.fromisoformat(previous['timestamp'])).total_seconds()<=max_interval_seconds)
        if restart:edge='interrupted_restart'
        if edge in ('manual_correction','source_changed','character_or_session_changed','run_boundary','nonincreasing_timestamp'):
            hard=edge
            if edge=='run_boundary':epoch+=1
        frame=row.get('frame_sha256')
        observed=when.timestamp() if when is not None and when.utcoffset() is not None and when<=now else frame_time
        if observed is not None:frame_time=observed if frame_time is None else max(frame_time,observed)
        if frame_time is None:frame_time=now.timestamp()
        while seen_frames:
            oldest=next(iter(seen_frames))
            if seen_frames[oldest]>=frame_time-FRAME_HISTORY_SECONDS:break
            del seen_frames[oldest]
        if row['event_id'] in seen_events or frame and frame in seen_frames:hard='duplicate_capture'
        seen_events.add(row['event_id'])
        if frame:
            seen_frames.pop(frame,None)
            seen_frames[frame]=frame_time
        localization_gap=bool(row.get('overlapping_hud_gap') is True and frame and row.get('capture_acquired') is True
            and row.get('received_at') and row.get('local_age_seconds') is not None and 0<=row['local_age_seconds']<=15)
        if (row.get('crop_suspect') or row.get('candidate_invalid') or row.get('percentage_only_invalid')
                or row.get('timing_mode')=='simulated' or (row.get('hud_count') or 0)>1 and not localization_gap
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
            previous=None;holes=[];unrecorded=0;numeric_gap=False
            if hard!='incompatible_full_exp':support=[]
        baseline_only=hard in ('manual_correction','run_boundary','source_changed','character_or_session_changed','level_changed',
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
        unreadable=(localization_gap or row.get('status')=='capture_failed' or
            row.get('status')=='unavailable' and row.get('hud_count')==0 and row.get('reasons')==['missing_hud']
            and row.get('local_age_seconds') is not None and row['local_age_seconds']<=15 or
            fresh and point is None and recovery is None and evidence.get('status') not in ('conflict','pending'))
        if usable and value:
            if previous:
                elapsed=(datetime.fromisoformat(value['timestamp'])-datetime.fromisoformat(previous['timestamp'])).total_seconds()
                ordered=((not numeric_gap or numeric_pair) and value['level']['value']==previous['level']['value'] and 0<elapsed<=max_interval_seconds
                    and (last_interval_end is None or previous['timestamp']>=last_interval_end)
                    and 0<=value['bp']-previous['bp']<LARGE_CHANGE_BP
                    and not (value['exp'] is not None and previous['exp'] is not None and int(value['exp'])<int(previous['exp'])))
                if ordered:
                    missing=[h['event_id'] for h in holes]
                    kind='endpoint_supported' if holes or unrecorded or edge in ('missing_attempt','sampling_gap','interrupted_restart') else 'direct'
                    edges.append(dict(before=previous,after=value,epoch=epoch,identity=key,kind=kind,
                        missing_event_ids=missing,unrecorded_attempts=unrecorded))
                    if restart:edges[-1]['restart']='interrupted_same_assignment'
                    last_interval_end=value['timestamp']
                else:
                    support=[]
                    excluded.append(dict(event_id=row['event_id'],reason='incompatible_endpoints_or_interval_limit'))
            previous=value;last_value=value;holes=[];unrecorded=0;numeric_gap=False
            if evidence.get('status') in ('agreement','provisional_neural') and value['evidence']!='conditional_symbol':
                support=(support+[dict(value,frame_sha256=frame)])[-2:]
        elif not hard and (unreadable or matching_pending):
            holes.append(dict(event_id=row['event_id']))
            numeric_gap |= localization_gap
        else:
            numerical_boundary=(hard=='incompatible_full_exp' or not hard and fresh and point
                and invalid is None and not decision['progress_eligible'] and evidence.get('value')==level)
            previous=None;holes=[];unrecorded=0;numeric_gap=False
            if not numerical_boundary:support=[]
            excluded.append(dict(event_id=row['event_id'],reason=hard or decision['reason'] or invalid))
        prior_attempt=context
    if state is not None:
        state.update(previous=previous,prior_attempt=prior_attempt,support=support,holes=holes,seen_events=seen_events,
            seen_frames=seen_frames,epoch=epoch,identity=identity,level=level,last_value=last_value,unrecorded=unrecorded)
        state.update(last_interval_end=last_interval_end,numeric_gap=numeric_gap,frame_time=frame_time)
    return dict(intervals=edges,recoveries=recoveries,excluded=excluded,epoch=epoch,
        latest=last_value,pending_missing=len(holes)+unrecorded,identity=identity)
