"""Read-only player presentation of existing experimental evidence, never accounting."""

from copy import deepcopy
from datetime import datetime,timedelta,timezone
from fractions import Fraction

from .diagnostic_progress import percentage_point,rational,quantization_pace,elapsed_seconds,difference_bounds
from .diagnostic_evidence import project,full_reading,consistency,supported_exp,Projected
from .diagnostic_percentage import boundary
from .exp_requirements import requirement
from .exp_consistency import MODES, assess

WINDOWS=(5,10,15,30,60,1440)
# Public level provenance: readers first, then labeled EXP-derived/retained/provisional context.
DISPLAY_LEVEL_STATUSES=('agreement','provisional_neural','exp_derived','retained_level','provisional_level_up','manual_admin')
PRODUCT_ROWS=640  # 30 minutes at the explicit offline 3s floor, plus level-context/boundary evidence.
PACE_MIN_SECONDS=5
PACE_TREND_SECONDS=300
PACE_HISTORY_SECONDS=1800
OBSERVED_MAX_GAP_SECONDS=60
OBSERVED_MAX_MISSING=2


def responsive_pace(snapshot, display_level, *, now=None,minutes=5,pool_history=False,retain_history=True,collected=None,current_level_only=False):
    """Eligible whole-interval gains, normalized over the selected lookback duration."""
    from .pace_intervals import collect_observed,window_endpoints,PUBLIC_POLICY
    rows=snapshot['observations'];reference=next((r.get('received_at') or r.get('attempted_at') for r in reversed(rows)),None)
    if now is None and reference is None:return None
    now=now or datetime.fromisoformat(reference)
    collected=collected or collect_observed(snapshot,now=now,read=reading,max_interval_seconds=PACE_TREND_SECONDS)
    points=collected['points'];current=(display_level or {}).get('value')
    if current is None and points:current=points[-1]['level']['value']
    if current_level_only and current is None:return None
    selected,gain,reason=window_endpoints(points,start=now-timedelta(minutes=minutes),end=now,level=current if current_level_only else None)
    retained=False
    if gain is None and retain_history:
        eligible=[p for p in points if not current_level_only or p['level']['value']==current]
        for a,b in reversed(list(zip(eligible,eligible[1:]))):
            reference=datetime.fromisoformat(b['timestamp'])
            if reference-datetime.fromisoformat(a['timestamp'])>timedelta(minutes=minutes):continue
            selected,gain,reason=window_endpoints(points,start=reference-timedelta(minutes=minutes),end=reference,level=current if current_level_only else None)
            if gain:retained=True;break
    if gain is None:return None
    first,last=selected[0],selected[-1];elapsed=elapsed_seconds(datetime.fromisoformat(first['timestamp']),datetime.fromisoformat(last['timestamp']))
    span=elapsed
    if gain.get('coverage_seconds'):elapsed=fraction(gain['coverage_seconds'])
    denominator=Fraction(minutes*60)
    amount=fraction(gain['value']);rate=amount*3600/denominator;req=requirement(last['level']['value'])
    percentage=None
    if first['level']['value']==last['level']['value'] and not gain.get('manual_boundaries'):
        percentage=dict(value=rational(Fraction(last['bp']-first['bp'])*36/denominator),**quantization_pace(first['bp'],last['bp'],denominator))
    calculated=estimates(dict(requirement=req),percentage,last['bp']) if percentage else estimates(None,None,0)
    hypotheses=(calculated['exp_per_hour'] or {}).get('hypotheses')
    eta_hypotheses=(calculated['eta'] or {}).get('hypotheses')
    calculated['exp_per_hour']=dict(value=rational(rate),hypotheses=hypotheses,requirement=req,requirements=gain['requirements'],basis=gain['basis'],
        transition_gain_included=gain['transition_gain_included'])
    rest=Fraction(req['to_next'])-(Fraction(int(last['exp'])) if last['exp'] is not None else Fraction(last['bp']*req['to_next'],10000)) if req['to_next'] is not None else None
    calculated['eta']=dict(seconds=rational(rest*3600/rate),hypotheses=eta_hypotheses,basis='public_endpoint_rate',trusted=False) if rest is not None and rest>0 and rate>0 else None
    if any(p['evidence']=='conditional_symbol' for p in selected):calculated['eta']=None
    saved_eta=deepcopy(calculated['eta'])
    active=bool(not retained and rows and rows[-1]['event_id']==last['event_id'] and not rows[-1].get('run_interrupted')
        and snapshot.get('run_status') not in ('completed','interrupted') and snapshot.get('run_id',rows[-1].get('run_id'))==rows[-1].get('run_id'))
    if not active:calculated['eta']=None
    details=[];metadata={(e['before']['event_id'],e['after']['event_id']):e for e in collected.get('intervals',[])}
    for interval in gain['intervals']:
        detail=metadata.get((interval['first_event_id'],interval['last_event_id']),{})
        details.append(dict(first_event_id=interval['first_event_id'],last_event_id=interval['last_event_id'],start=interval['start'],end=interval['end'],
            kind=detail.get('kind','endpoint_supported'),basis=interval['basis'],level=interval['level'],requirement=interval['requirement'],gain=interval['value'],
            elapsed_seconds=rational(elapsed_seconds(datetime.fromisoformat(interval['start']),datetime.fromisoformat(interval['end']))),
            missing_event_ids=detail.get('missing_event_ids',[]),unrecorded_attempts=detail.get('unrecorded_attempts',0)))
    return dict(active=active,tentative=len(selected)<3 or elapsed<30,level=last['level']['value'],levels=sorted({p['level']['value'] for p in selected}),
        eta_at=last['timestamp'],start=first['timestamp'],end=last['timestamp'],source_kind=last.get('source_kind'),source_identity=last.get('source_identity'),
        readings=len(selected),last_observed_eta=saved_eta,span_seconds=rational(span),coverage_seconds=rational(elapsed),interruptions=int(bool(gain.get('manual_boundaries'))),
        estimates=calculated,basis=gain['basis'],interval_counts={kind:sum(d['kind']==kind for d in details) for kind in ('direct','endpoint_supported')},intervals=details,total_gain=gain['value'],
        basis_counts={gain['basis']:1},missing_attempts=len(collected['excluded'])+sum(d['unrecorded_attempts'] for d in details),
        evidence_counts={kind:sum(p['evidence']==kind for p in selected) for kind in ('strict_full','strict_percentage_only','grammar_recovered','conditional_symbol')},
        conditional_recoveries=collected['recoveries'],excluded=collected['excluded'],latest_endpoint=collected.get('latest'),
        policy=PUBLIC_POLICY,minimum_seconds=0,trend_seconds=minutes*60,trusted=False,retained_history=retained,recent_pool_expired=retained,
        aging_allowed=False,reason=snapshot['percentage_progress']['reason'],identity_verified=False,denominator='selected_window_duration')


def recent_windows(snapshot,display_level,*,now,current_level_only=False,collected=None):
    """Whole eligible intervals and window-normalized rates for each lookback."""
    from .pace_intervals import collect_observed as collect,window_endpoints
    collected=collected or collect(snapshot,now=now,read=reading,max_interval_seconds=PACE_TREND_SECONDS)
    result={}
    for minutes in WINDOWS:
        pace=responsive_pace(snapshot,display_level,now=now,minutes=minutes,pool_history=True,
            retain_history=False,collected=collected,current_level_only=current_level_only)
        observed=dict(available=False)
        if pace:
            percentage=pace['estimates']['percentage_per_hour']
            change=fraction(percentage['value'])*minutes*60/36 if percentage else None
            observed=dict(available=True,start=pace['start'],end=pace['end'],span_seconds=pace['span_seconds'],
                coverage_seconds=pace['coverage_seconds'],readings=pace['readings'],interruptions=pace['interruptions'],
                unavailable_attempts=pace['missing_attempts'],missing_attempts=0,paused=not pace['active'],
                age_seconds=max(0,(now-datetime.fromisoformat(pace['end'])).total_seconds()),historical=not pace['active'],
                difference_percentage_points=f'{int(change)//100}.{int(change)%100:02}' if change is not None else None,
                estimated_exp=dict(value=pace['total_gain'],basis=pace['basis'],
                    requirement=pace['estimates']['exp_per_hour']['requirement']) if pace['total_gain'] is not None else None,
                policy=pace['policy'],trusted=False)
        result[str(minutes)]=dict(minutes=minutes,start=(now-timedelta(minutes=minutes)).isoformat(),end=now.isoformat(),
            status=snapshot.get('recent_history_status','ready'),available=pace is not None,
            gain=pace['total_gain'] if pace else None,pace=({k:v for k,v in pace.items()
                if k not in ('intervals','conditional_recoveries','excluded','latest_endpoint')} if pace else None),
            observed=observed,scope='current_level_only' if current_level_only else 'selected_character_independent_sessions_and_sources',trusted=False,complete_window=False)
        if pace is None:
            level=(display_level or {}).get('value')
            if level is None and collected['points']:level=collected['points'][-1]['level']['value']
            _,_,reason=window_endpoints(collected['points'],start=now-timedelta(minutes=minutes),end=now,level=level if current_level_only else None)
            result[str(minutes)]['reason']=reason
        if pace is None:
            previous=responsive_pace(snapshot,display_level,now=now,minutes=minutes,pool_history=True,collected=collected,current_level_only=current_level_only)
            result[str(minutes)]['last_observed_pace']=({k:v for k,v in previous.items()
                if k not in ('intervals','conditional_recoveries','excluded','latest_endpoint')} if previous else None)
            if previous is None:
                saved=deepcopy(snapshot.get('historical_paces',{}).get(str(minutes)))
                if saved and (not current_level_only or saved['levels']==[(display_level or {}).get('value')]):
                    saved.update(active=False,retained_history=True,recent_pool_expired=True)
                    result[str(minutes)]['last_observed_pace']=saved
        current_basis=pace or result[str(minutes)].get('last_observed_pace')
        # Date the estimate at an observation, not at a poll that merely removes
        # old intervals. The gain/rate cards keep their actual current windows.
        basis=responsive_pace(snapshot,display_level,now=datetime.fromisoformat(current_basis.get('eta_at',current_basis['end'])),
            minutes=minutes,pool_history=True,collected=collected,current_level_only=current_level_only) if current_basis else None
        eta=basis and basis['last_observed_eta']
        # An old duration survives missing OCR, never an affirmative new level or
        # confirmed reset. No subtraction or countdown crosses the boundary.
        blocked=bool(basis and any(
            r.get('received_at') and r['received_at']>basis.get('eta_at',basis['end']) and (
                (r.get('experimental_level') or {}).get('value') not in (None,basis['level']) or
                (r.get('experimental_level') or {}).get('status')=='conflict' or
                (r.get('percentage_review') or {}).get('break_before')=='confirmed_change_new_baseline')
            for r in snapshot['observations']))
        result[str(minutes)]['eta']=dict(estimate=deepcopy(eta),estimated_at=basis.get('eta_at',basis['end']),
            window_minutes=minutes,start=basis['start'],level=basis['level'],readings=basis['readings'],
            source_identity=basis['source_identity'],source_kind=basis['source_kind'],
            coverage_seconds=basis['coverage_seconds'],tentative=basis['tentative'],
            levels=basis['levels'],
            rate_observed_at=basis['end'],rate_age_seconds=max(0,(now-datetime.fromisoformat(basis['end'])).total_seconds()),
            rate=basis['estimates']['exp_per_hour']['value'],
            historical=not current_basis['active'],age_seconds=max(0,(now-datetime.fromisoformat(basis.get('eta_at',basis['end']))).total_seconds()),
            static_duration=True,trusted=False) if eta and not blocked else None
        if not basis and not blocked:
            result[str(minutes)]['eta']=deepcopy(snapshot.get('historical_etas',{}).get(str(minutes)))
            saved=result[str(minutes)]['eta']
            if current_level_only and saved and saved.get('levels')!=[saved['level']]:result[str(minutes)]['eta']=None
        saved=result[str(minutes)]['eta']
        if saved and any(k in snapshot and snapshot[k]!=saved[k] for k in ('source_kind','source_identity')):
            result[str(minutes)]['eta']=None
    return result


def inferred_level_events(rows):
    """Percentage-wrap level-ups, labeled provisional until EXP or a reader corroborates them."""
    events={}
    for row in rows:
        context=(row.get('experimental_level') or {}).get('level_context') or {}
        for transition in (context.get('last_transition'),context.get('transition')):
            if not transition or transition['phase']=='possible':continue
            key=transition['wrap_event_id']
            # An abandoned hypothesis leaves no marker; raw OCR history is unchanged.
            if transition['phase']=='abandoned':events.pop(key,None);continue
            events[key]=dict(kind='inferred_level_up',level=transition['to_level'],previous_level=transition['from_level'],
                status=transition['phase'],timestamp=transition.get('corroborated_at') or transition.get('provisional_at'),
                first_observed_at=transition['detected_at'],event_id=key,inferred=True,
                evidence=transition.get('corroborated_by') or 'percentage_wrap_and_forward_progress',trusted=False)
    return list(events.values())


def level_events(rows):
    """Two adjacent supported new-level readings; no gains or identity inference."""
    events=[];established=None;previous=None;pending=None
    for row in rows:
        point,reason=percentage_point(row);level=level_evidence(row)
        if point:point.update(interval_seconds=row.get('interval_seconds',15),frame_sha256=row.get('frame_sha256'))
        supported=reason is None and level['status'] in ('agreement','provisional_neural') and row.get('percentage_review',{}).get('public_eligible') is not False
        if supported:
            if established and (any(point[k]!=established[k] for k in ('channel','source_channel','source_kind','character_id','session_id','source_identity','run_id'))
                    or not 0<(datetime.fromisoformat(point['timestamp'])-datetime.fromisoformat(established['timestamp'])).total_seconds()<=120):
                established=pending=None
            if established and point['level']==established['level']+1 and point['bp']<established['bp']:
                if (pending and previous and boundary(previous,point,row) is None
                        and point['frame_sha256'] and pending['frame_sha256'] and point['frame_sha256']!=pending['frame_sha256']):
                    events.append(dict(kind='level_up',level=point['level'],previous_level=established['level'],
                        timestamp=point['timestamp'],first_observed_at=pending['timestamp'],event_id=point['event_id'],
                        evidence='two_adjacent_supported_level_readings',trusted=False))
                    established=point;pending=None
                else:pending=point
            else:
                established=point;pending=None
        else:pending=None
        previous=point if supported else None
    return sorted(events+inferred_level_events(rows),key=lambda e:e['timestamp'])


def fraction(value):
    return Fraction(value['numerator'],value['denominator'])


def tracked_statistics(value,data,*,now,pace_as_of=None):
    """One saved-character/as-of packet supplies every public tracked-EXP total."""
    value['tracked_as_of']=data['as_of'];value['tracked_status']=data['status']
    as_of=datetime.fromisoformat(data['as_of'])
    value['tracked_windows']=deepcopy(data['windows'])
    value['tracked_current_level_windows']=deepcopy(data['current_level_windows'])
    for windows,rate_windows in ((value['tracked_windows'],value['recent_windows']),
                                (value['tracked_current_level_windows'],value['current_level_windows'])):
        for metric in windows.values():
            observed=metric.get('observed',{})
            if not observed.get('available'):continue
            observed['age_seconds']=max(0,(now-datetime.fromisoformat(observed['end'])).total_seconds())
            observed['historical']=observed['paused']=bool(value['stale'] or value.get('activity',{}).get('state') not in ('running','waiting','capture_delayed','capture_failing'))
        for minutes,metric in rate_windows.items():
            tracked=windows.get(minutes,{})
            metric.update(gain=tracked.get('gain'),observed=tracked.get('observed',dict(available=False)),
                reason=tracked.get('reason'),
                available=tracked.get('available',False),tracked_status=data['status'],tracked_as_of=data['as_of'],
                tracked_scope=data['scope'],start=(as_of-timedelta(minutes=int(minutes))).isoformat(),end=data['as_of'],
                pace_as_of=(pace_as_of or now).isoformat())
            if not tracked.get('available'):metric['pace']=None
            elif metric.get('pace'):
                pace=metric['pace'];observed=tracked['observed']
                pace.update(total_gain=tracked['gain'],start=observed['start'],end=observed['end'],
                    coverage_seconds=observed['coverage_seconds'],span_seconds=observed['span_seconds'],
                    readings=observed['readings'],level=tracked['level'],levels=tracked['levels'])
                pace['estimates']['exp_per_hour']['value']=tracked['rate']
    return value


def level_evidence(row):
    return row['experimental_level'] if 'experimental_level' in row else project([row])[0]['experimental_level']


def percentage_exp(bp, level):
    """Presentation estimate only; never supplies an OCR integer or chooses a level."""
    req=requirement(level.get('value'))
    if req['to_next'] is None:return None
    percentage=f'{bp//100}.{bp%100:02}'
    # The bin depends only on the display; the dummy EXP does not select a hypothesis.
    bins={mode:assess(level['value'],0,percentage,{level['value']:req['to_next']},mode)['exp_bin'] for mode in MODES}
    if not any(b['count'] for b in bins.values()):return None
    return dict(value=rational(Fraction(bp*req['to_next'],10000)),hypotheses=bins,
        requirement=req,level_evidence=level,source='displayed_percentage_and_provisional_requirement',
        label='EXPERIMENTAL / UNVERIFIED',trusted=False)


def estimates(segment,pace,bp):
    """Exact conversion and outer display-precision bounds; neither rule selected."""
    result=dict(percentage_per_hour=None,exp_per_hour=None,eta=None)
    if not segment or not pace: return result
    result['percentage_per_hour']=pace
    requirement=segment['requirement'];total=requirement['to_next']
    if total is not None:
        result['exp_per_hour']=dict(value=rational(fraction(pace['value'])*total/100),requirement=requirement,
            hypotheses={rule:dict(lower=rational(fraction(pace[rule]['lower'])*total/100),
                upper=rational(fraction(pace[rule]['upper'])*total/100)) for rule in ('nearest_half_up','truncation')})
    if fraction(pace['value'])<=0 or bp>=10000: return result
    bounds={}
    for rule,lo,hi in [('nearest_half_up',Fraction(-1,2),Fraction(1,2)),('truncation',Fraction(0),Fraction(1))]:
        low,high=fraction(pace[rule]['lower']),fraction(pace[rule]['upper'])
        if low<=0 or high<=0: return result
        remaining_low=Fraction(10000-min(10000,bp+hi),100)
        remaining_high=Fraction(10000-max(0,bp+lo),100)
        bounds[rule]=dict(lower_seconds=rational(remaining_low/high*3600),upper_seconds=rational(remaining_high/low*3600))
    result['eta']=dict(seconds=rational(Fraction(10000-bp,100)/fraction(pace['value'])*3600),
        hypotheses=bounds,basis='same_level_displayed_percentage_pace_not_a_countdown')
    return result


def reading(row):
    if row.get('reading_invalidated'):return None
    if row.get('manual_point'):
        from .manual import corrected_reading
        return corrected_reading(row['manual_point'],event_id=row['event_id'],
            timestamp=row.get('received_at') or row['attempted_at'],epoch=row['manual_epoch'])
    if row.get('percentage_review',{}).get('public_eligible') is False:return None
    if 'experimental_level' not in row: row=project([row])[0]
    point,_=percentage_point(row)
    if not point: return None
    if point.get('requires_percentage_only_context') and not row.get('percentage_review',{}).get('percentage_only_context',{}).get('supported'):
        return None
    full=full_reading(row)
    if full and full['percentage']!=point['percentage']:full=None
    exp=full['exp'] if full and row['exp_validity']['status']!='invalid' else None
    level=level_evidence(row)
    return dict(event_id=point['event_id'],timestamp=point['timestamp'],percentage=point['percentage'],
        bp=point['bp'],exp=exp,estimated_exp=percentage_exp(point['bp'],level) if exp is None else None,
        exp_validity=row['exp_validity'],evidence=point['evidence'],grammar_policy=point['grammar_policy'],
        fresh_at_capture=point['fresh_at_capture'] and point['capture_acquired'] and row.get('manual_resume_eligible',True),level=level,
        simulated=row.get('timing_mode')=='simulated',trusted=False,manual_epoch=row.get('manual_epoch'),
        manual_baseline_id=row.get('manual_baseline_id',row.get('manual_epoch')),
        accounting_scope=f"{row.get('character_id')}:{row.get('session_id')}")


def observed_sequence(snapshot, *, now,completed=None,max_gap_seconds=OBSERVED_MAX_GAP_SECONDS,max_missing=OBSERVED_MAX_MISSING,
                      pace_reacquisition=False):
    """Endpoint comparisons across short disclosed holes, never connected pace/gains."""
    points=[];holes=[];previous=None;pending=[];last=None;break_reason='baseline';seen_frames=set()
    reviews={r['event_id']:r for r in snapshot['percentage_progress']['percentage_reviews']}
    rows=snapshot['observations']
    for row in rows if type(rows) is Projected else project(rows):
        point,invalid=percentage_point(row);decision=reviews[row['event_id']]
        stamp=row.get('received_at') or row.get('attempted_at')
        # Context placeholders test ownership/order only; never supply a numeric endpoint.
        context=dict(channel=row.get('assigned_channel') or row.get('channel'),source_channel=row.get('channel'),
            source_kind=row.get('source_kind'),source_identity=row.get('source_identity'),
            character_id=row.get('character_id'),session_id=row.get('session_id'),run_id=row.get('run_id'),
            index=row.get('index'),coordinator_instance=row.get('coordinator_instance'),timestamp=stamp,
            interval_seconds=row.get('interval_seconds',15),level=(row.get('experimental_level') or {}).get('value'),
            manual_epoch=row.get('manual_epoch'))
        hard=None;valid_time=False
        try:
            when=datetime.fromisoformat(stamp)
            if when.utcoffset() is None or when>now:hard='timestamp_unavailable_or_future'
            else:valid_time=True
            if valid_time and previous:
                edge=boundary(previous,context,row)
                # Missing indices and sampling delays are disclosed, bounded holes.
                if edge not in (None,'sampling_gap','missing_attempt','level_changed'):hard=edge
                elif context['level'] is not None and last and context['level']!=last['level']:hard='level_changed'
                elif edge=='sampling_gap' and (when-datetime.fromisoformat(previous['timestamp'])).total_seconds()>max_gap_seconds:hard='gap_exceeds_limit'
        except (TypeError,ValueError,KeyError):hard='timestamp_unavailable_or_out_of_order'
        level=level_evidence(row)
        unsafe=(not valid_time or row.get('timestamp_ordered') is False or row.get('timing_mode')=='simulated'
                or row.get('status')=='stale_local_frame' or row.get('crop_suspect') is True
                or row.get('candidate_invalid') or row.get('percentage_only_invalid')
                or level['status']=='conflict' or (row.get('hud_count') or 0)>1)
        if unsafe:hard='ambiguous_or_unsafe_evidence'
        if decision.get('break_before'):hard=decision['break_before']
        usable=bool(not unsafe and point and invalid is None and decision['progress_eligible'])
        # Only absent numeric evidence may be skipped; a readable but quarantined
        # number or an unresolved level is a hard boundary, never a hole to bridge.
        missing=not point and not row.get('candidate') and not row.get('percentage_only_candidate')
        allowed_missing=not unsafe and missing and (row.get('status')=='capture_failed' or
            row.get('fresh_at_capture') and row.get('hud_count')==1 or
            row.get('status')=='unavailable' and row.get('hud_count')==0 and row.get('reasons')==['missing_hud']
            and row.get('local_age_seconds') is not None and row['local_age_seconds']<=15)
        # Pace may retain earlier intervals while the SAME neural level reacquires
        # confirmation. This frame is still excluded, and windows keep their policy.
        if (pace_reacquisition and last and not unsafe and point and invalid=='visual_level_unavailable'
                and level['status']=='pending' and level['reason']=='neural_confirmation_pending'
                and level.get('neural')==last['level'] and level.get('visual') in (None,last['level'])
                and decision['public_eligible'] and not decision.get('break_before')
                and 0<=point['bp']-last['bp']<1000
                and consistency(full_reading(row),last['level'])['status']!='invalid'):
            allowed_missing=True
        if (pace_reacquisition and last and level['status']=='pending'
                and any(level.get(k) not in (None,last['level']) for k in ('visual','neural'))):
            hard='level_reacquisition_conflict';allowed_missing=False
        frame=row.get('frame_sha256')
        if pace_reacquisition and frame and frame in seen_frames:
            hard='duplicate_source_frame';usable=False;allowed_missing=False
        if frame:seen_frames.add(frame)
        if not usable and not allowed_missing:hard=hard or decision['reason'] or invalid or 'unusable_observation'
        if usable and last and hard is None:
            elapsed=(when-datetime.fromisoformat(last['timestamp'])).total_seconds()
            absent=(context['index']-previous['index']-1) if previous and context['run_id']==previous['run_id'] else 0
            absent=max(0,absent)+sum(h['missing_indices'] for h in pending)
            if len(pending)+absent>max_missing or elapsed>max_gap_seconds:hard='gap_exceeds_limit'
            if point['bp']<last['bp'] or point['bp']-last['bp']>=1000:
                hard='unresolved_numerical_continuity';usable=False
            if row.get('frame_sha256') and row['frame_sha256']==last.get('frame_sha256'):
                hard='duplicate_source_frame';usable=False
        if hard:
            if completed is not None and points:completed.append((points,holes,pending,break_reason))
            points=[];holes=[];pending=[];last=None;break_reason=hard
        if usable:
            if last:
                missing_indices=max(0,context['index']-previous['index']-1) if previous and context['run_id']==previous['run_id'] else 0
                if pending or missing_indices or boundary(last,point|{'interval_seconds':context['interval_seconds']},row)=='sampling_gap':
                    holes.append(dict(start=last['timestamp'],end=point['timestamp'],
                        event_ids=[h['event_id'] for h in pending],missing_attempts=missing_indices+sum(h['missing_indices'] for h in pending),
                        unavailable_attempts=len(pending),elapsed_seconds=elapsed))
            point.update(interval_seconds=context['interval_seconds'],frame_sha256=row.get('frame_sha256'))
            points.append(point);last=point;pending=[]
        elif allowed_missing and last:
            pending.append(dict(event_id=row['event_id'],missing_indices=max(0,context['index']-previous['index']-1)
                if previous and context['run_id']==previous['run_id'] else 0))
            if len(pending)+sum(h['missing_indices'] for h in pending)>max_missing or (when-datetime.fromisoformat(last['timestamp'])).total_seconds()>max_gap_seconds:
                if completed is not None and points:completed.append((points,holes,pending,break_reason))
                points=[];holes=[];pending=[];last=None;break_reason='gap_exceeds_limit'
        previous=context
    return points,holes,pending,break_reason


def observed_window(sequence, *, cutoff, end):
    points,holes,pending,reason=sequence
    points=[p for p in points if cutoff<=datetime.fromisoformat(p['timestamp'])<=end]
    result=dict(available=False,state='building_history',reason=reason,policy='observed_window_v1',
        trusted=False,identity_verified=False,interpolated=False,pace=None,
        max_gap_seconds=OBSERVED_MAX_GAP_SECONDS,max_missing_attempts=OBSERVED_MAX_MISSING)
    if len(points)<3:return result
    first,last=points[0],points[-1]
    elapsed=elapsed_seconds(datetime.fromisoformat(first['timestamp']),datetime.fromisoformat(last['timestamp']))
    if elapsed<30:return result
    holes=[h for h in holes if datetime.fromisoformat(h['start'])>=datetime.fromisoformat(first['timestamp'])
           and datetime.fromisoformat(h['end'])<=datetime.fromisoformat(last['timestamp'])]
    diff=last['bp']-first['bp']
    return dict(result,available=True,state='observed_endpoints',reason='partial_observation_not_complete_window',
        level=last['level'],start=first['timestamp'],end=last['timestamp'],span_seconds=rational(elapsed),
        first_event_id=first['event_id'],last_event_id=last['event_id'],
        start_percentage=first['percentage'],end_percentage=last['percentage'],readings=len(points),
        difference_percentage_points=f'{diff//100}.{diff%100:02}',estimated_exp=exp_change(first['bp'],last['bp'],last['level']),
        interruptions=len(holes),holes=holes,
        unavailable_attempts=sum(h['unavailable_attempts'] for h in holes),
        missing_attempts=sum(h['missing_attempts'] for h in holes),pending_attempts=len(pending),
        paused=bool(pending),age_seconds=0,
        evidence_counts={kind:sum(p['evidence']==kind for p in points) for kind in ('strict_full','strict_percentage_only','grammar_recovered')})


def exp_change(first_bp,last_bp,level):
    """Net display conversion, never an exact earned-EXP total."""
    req=requirement(level)
    if req['to_next'] is None:return None
    return dict(value=rational(Fraction((last_bp-first_bp)*req['to_next'],10000)),requirement=req,
        hypotheses={rule:dict(lower=rational(low*req['to_next']/10000),upper=rational(high*req['to_next']/10000))
            for rule,(low,high,_) in difference_bounds(first_bp,last_bp).items()},
        basis='displayed_percentage_endpoint_difference',trusted=False)


def window_comparisons(snapshot, *, now):
    """Observed endpoints inside a fixed window; never split an interval at its boundary."""
    rows=snapshot['observations'];data=snapshot['percentage_progress'];segment=data['current_segment']
    reference=(rows[-1]['received_at'] or rows[-1]['attempted_at']) if rows else None
    end=datetime.fromisoformat(reference) if reference else now
    sequence=[]
    if segment:
        inside=False
        for row in rows:
            if row['event_id']==segment['first_event_id']:inside=True
            if inside:sequence.append((row,percentage_point(row)[0]))
            if row['event_id']==segment['last_event_id']:break
    completed=[]
    observed=observed_sequence(snapshot,now=now,completed=completed)
    result={}
    for minutes in WINDOWS:
        cutoff=end-timedelta(minutes=minutes)
        points=[(r,p) for r,p in sequence if p and cutoff<=datetime.fromisoformat(p['timestamp'])<=end]
        metric=dict(minutes=minutes,reference_at=reference,requested_start=cutoff.isoformat(),eligible=False,
            state='building_history',reason='insufficient_contiguous_coverage',readings=len(points),
            coverage_seconds=rational(Fraction(0)),coverage_fraction=rational(Fraction(0)),
            difference_percentage_points=None,estimates=estimates(None,None,0),trusted=False)
        metric['eligibility_checks']=dict(active_connected_segment=segment is not None,
            minimum_readings=len(points)>=3,minimum_span=False,ninety_percent_span=False,
            left_endpoint_within_interval=False,latest_attempt_is_endpoint=False,
            fresh=not data['stale'],reference_not_future=end<=now)
        context_free=not any(r.get('experimental_level',{}).get('contextual') or
            r.get('experimental_level',{}).get('strict_window_eligible') is False for r,_ in points)
        metric['eligibility_checks']['reader_supported_levels']=context_free
        if points:
            first,last=points[0][1],points[-1][1]
            a,b=datetime.fromisoformat(first['timestamp']),datetime.fromisoformat(last['timestamp'])
            elapsed=elapsed_seconds(a,b)
            metric.update(start=first['timestamp'],end=last['timestamp'],coverage_seconds=rational(elapsed),
                coverage_fraction=rational(elapsed/(minutes*60)),
                evidence_counts={kind:sum(p['evidence']==kind for _,p in points) for kind in ('strict_full','strict_percentage_only','grammar_recovered')})
            boundary=elapsed_seconds(cutoff,a)
            metric['eligibility_checks'].update(minimum_span=elapsed>=30,
                ninety_percent_span=elapsed>=Fraction(minutes*60*9,10),
                left_endpoint_within_interval=boundary<=Fraction(str(points[0][0]['interval_seconds'])),
                latest_attempt_is_endpoint=rows[-1]['event_id']==last['event_id'])
            complete=(context_free and len(points)>=3 and elapsed>=30 and elapsed>=Fraction(minutes*60*9,10)
                and boundary<=Fraction(str(points[0][0]['interval_seconds']))
                and rows[-1]['event_id']==last['event_id'])
            if complete:
                diff=last['bp']-first['bp']
                pace=dict(label='EXPERIMENTAL / UNVERIFIED',units='percentage_points_per_hour',
                    value=rational(Fraction(diff*36)/elapsed),**quantization_pace(first['bp'],last['bp'],elapsed),
                    bounds_kind='outer_quantization_bounds_not_statistical_intervals')
                metric.update(eligible=True,state='eligible',reason='observed_endpoints_cover_window',
                    difference_percentage_points=f'{diff//100}.{diff%100:02}',
                    estimates=estimates(segment,pace,last['bp']))
        if reference is None or end>now or data['stale'] or segment is None:
            metric.update(eligible=False,state='stale' if data['stale'] else 'unavailable',
                reason='future_timestamp' if end>now else data['reason'],estimates=estimates(None,None,0))
        metric['observed']=observed_window(observed,cutoff=cutoff,end=end)
        if not metric['observed']['available'] and snapshot.get('run_status') in ('completed','interrupted'):
            chain={snapshot.get('run_id',rows[-1]['run_id'])} if rows else set()
            for row in reversed(rows):
                if row['run_id'] in chain and row.get('rotation_from'):chain.add(row['rotation_from'])
            supported=next((r['experimental_level']['value'] for r in reversed(rows) if r.get('experimental_level',{}).get('value') is not None),None)
            for prior in reversed(completed):
                if prior[0][-1]['run_id'] not in chain or prior[0][-1]['level']!=supported:continue
                if any(prior[0][-1].get(k)!=rows[-1].get(k) for k in ('source_kind','source_identity','character_id','session_id')) or prior[0][-1]['source_channel']!=rows[-1].get('channel'):continue
                saved=observed_window(prior,cutoff=cutoff,end=end)
                if saved['available']:
                    metric['observed']=dict(saved,paused=True,historical=True,
                        ended_before_latest=True,reason='retained_comparable_history')
                    break
        if metric['observed']['available']:
            metric['observed']['paused'] |= bool(rows and (rows[-1].get('run_interrupted')
                or snapshot.get('run_id',rows[-1]['run_id'])!=rows[-1]['run_id']))
        result[str(minutes)]=metric
    return result


def observed_display(snapshot, *, now):
    """Compact dated display only; never a replacement for accounting observations."""
    rows=snapshot['observations'];latest=None;full=None
    for row in rows:
        value=reading(row)
        if value and row.get('timestamp_ordered') is not False and value['timestamp']:
            when=datetime.fromisoformat(value['timestamp'])
            if when<=now:
                if latest is None or when>datetime.fromisoformat(latest['timestamp']):latest=value
                if value['exp'] is not None and (full is None or when>datetime.fromisoformat(full['timestamp'])):full=value
    for point in snapshot.get('manual_observations',[]):
        if datetime.fromisoformat(point['timestamp'])<=now and (latest is None or point['timestamp']>=latest['timestamp']):latest=point
    # Display context never enters reading(), numerical checks or progress inputs.
    display_level=None
    for row in rows:
        level=level_evidence(row);stamp=row.get('received_at')
        if (not row.get('manual_point') and stamp and datetime.fromisoformat(stamp)<=now and row.get('timestamp_ordered') is not False
                and row.get('fresh_at_capture') and row.get('capture_acquired') and row.get('hud_count')==1
                and level['value'] is not None and level['status'] in DISPLAY_LEVEL_STATUSES):
            display_level=dict(value=level['value'],timestamp=stamp,event_id=row['event_id'],
                evidence=level,display_only=True,trusted=False,manual_epoch=row.get('manual_epoch'),
                manual_baseline_id=row.get('manual_baseline_id',row.get('manual_epoch')))
    if latest and latest['evidence']=='manual_admin' and (not display_level or latest['timestamp']>=display_level['timestamp']):
        display_level=dict(value=latest['level']['value'],timestamp=latest['timestamp'],event_id=latest['event_id'],
            evidence=latest['level'],display_only=True,trusted=False,manual_epoch=latest['manual_epoch'],
            manual_baseline_id=latest.get('manual_baseline_id'))
    full={k:full[k] for k in ('exp','percentage','evidence','event_id','timestamp')} if full else None
    return dict(reading=latest,display_level=display_level,full_exp=full)


def player(snapshot,*,now=None,recent_snapshot=None):
    now=now or datetime.now(timezone.utc)
    rows=snapshot['observations'];display=observed_display(snapshot,now=now)
    latest=display['reading'];display_level=display['display_level']
    progress=snapshot['percentage_progress'];segment=progress['current_segment']
    usable=bool(latest and segment and segment['last_event_id']==latest['event_id'] and rows and rows[-1]['event_id']==latest['event_id'])
    movement=progress.get('latest_movement') if usable else None
    movement=movement if movement and movement.get('change') in ('positive','zero') else None
    decision=progress.get('percentage_state')
    result=dict(channel=snapshot['channel'],character=snapshot['selected_character'],session_id=(snapshot['session'] or {}).get('id'),
        percentage_state=decision,display_level=display_level,level_events=None if recent_snapshot is not None else level_events(rows),
        level_context=level_evidence(rows[-1]).get('level_context') if rows else None,
        source_kind=snapshot.get('source_kind'),reading=latest,latest_attempt_at=(rows[-1].get('received_at') or rows[-1].get('attempted_at')) if rows else None,
        latest_attempt_status=rows[-1]['status'] if rows else 'waiting',
        capture_lifecycle=snapshot.get('run_status','waiting'),
        stale_after_seconds=snapshot['stale_after_seconds'],movement=movement,
        segment=dict(start=segment['start'],end=segment['end'],readings=segment['readings'],span_seconds=segment['span_seconds'],
            difference_percentage_points=segment['difference_percentage_points'],evidence_counts=segment['evidence_counts']) if usable else None,
        estimates=estimates(segment,progress['current_pace'],latest['bp']) if usable else estimates(None,None,0),
        windows=window_comparisons(snapshot,now=now),trusted=False,experimental=True)
    # A compact dated display is never fed back into OCR validation or window gains.
    saved=dict(snapshot.get('retention_display',{}))
    fallbacks=[(recent_snapshot or {}).get('historical_display',{})]
    if recent_snapshot is not None and latest is None:fallbacks.append(observed_display(recent_snapshot,now=now))
    for fallback in fallbacks:
        for key,value in fallback.items():
            if value and (not saved.get(key) or value['timestamp']>saved[key]['timestamp']):saved[key]=value
    for key in ('reading','display_level','latest_attempt_at'):
        if result.get(key) is None:result[key]=deepcopy(saved.get(key))
    full=display['full_exp']
    if saved.get('full_exp') and (full is None or saved['full_exp']['timestamp']>full['timestamp']):full=saved['full_exp']
    if not rows and saved:
        result['latest_attempt_status']=saved.get('latest_attempt_status',result['latest_attempt_status']);result['level_context']=deepcopy(saved.get('level_context'))
    from .manual import present
    present(result,snapshot)
    display_level=result['display_level']
    historical=next((s for s in reversed(progress['segments']) if s['pace']),None)
    result['early_pace']=dict(active=bool(usable and progress['current_pace']),reason=progress['reason'],
        segment=historical,estimates=estimates(historical,historical['pace'],int(Fraction(historical['end_percentage'])*100)) if historical else estimates(None,None,0),
        label='EXPERIMENTAL / UNVERIFIED; early segment estimate, not a completed window')
    result['responsive_pace']=responsive_pace(snapshot,display_level,now=now)
    if result['responsive_pace'] is None:result['responsive_pace']=deepcopy(saved.get('responsive_pace'))
    from .pace_intervals import collect_observed as collect
    # Both scopes use the same public observations, clock and limit.
    collected=collect(recent_snapshot or snapshot,now=now,read=reading,max_interval_seconds=PACE_TREND_SECONDS)
    result['recent_windows']=recent_windows(recent_snapshot or snapshot,display_level,now=now,collected=collected)
    transition=(result.get('level_context') or {}).get('transition') or {}
    filter_level=dict(value=transition['to_level']) if transition.get('phase')=='possible' and not transition.get('evidence_exhausted') else display_level
    result['current_level_windows']=recent_windows(recent_snapshot or snapshot,filter_level,now=now,current_level_only=True,collected=collected)
    if recent_snapshot is not None:result['level_events']=level_events(recent_snapshot['observations'])
    result['recent_history']=dict(status=(recent_snapshot or snapshot).get('recent_history_status','ready'),
        source='sqlite_time_range' if recent_snapshot is not None else 'provided_snapshot',
        receipt=(recent_snapshot or snapshot).get('recent_history_receipt'),
        eta_status=(recent_snapshot or snapshot).get('eta_history_status','ready'),
        eta_receipt=(recent_snapshot or snapshot).get('eta_history_receipt'))
    endpoint=(result['responsive_pace'] or {}).get('latest_endpoint')
    if endpoint and endpoint['evidence']=='conditional_symbol' and (not latest or endpoint['timestamp']>latest['timestamp']):
        result.update(reading=endpoint,original_percentage_state=decision,
            percentage_state=dict(policy='conditional_percent_v1',status='accepted_experimental_recovery',
                public_eligible=True,progress_eligible=False,reason='responsive_endpoint_only',trusted=False))
    result=present(result,snapshot)
    last=result['reading'];level=result['display_level']
    if last or level:
        result['last_seen']=dict(timestamp=(last or level)['timestamp'],reading=deepcopy(last),
            full_exp=deepcopy(full),display_level=deepcopy(level))
    return refresh(result,now=now)


def refresh(value,*,now=None,activity=None):
    now=now or datetime.now(timezone.utc);value=deepcopy(value)
    latest=value['reading'];age=(now-datetime.fromisoformat(latest['timestamp'])).total_seconds() if latest else None
    value['age_seconds']=max(0,age) if age is not None else None
    value['latest_attempt_age_seconds']=(now-datetime.fromisoformat(value['latest_attempt_at'])).total_seconds() if value.get('latest_attempt_at') else None
    if value.get('last_seen',{}).get('timestamp'):
        value['last_seen']['age_seconds']=max(0,(now-datetime.fromisoformat(value['last_seen']['timestamp'])).total_seconds())
    value['stale']=age is None or age<0 or age>value['stale_after_seconds'] or not latest['fresh_at_capture']
    value['activity']=activity or dict(state='coordinator_stopped')
    window_metrics=list(value.get('recent_windows',{}).values())+list(value.get('current_level_windows',{}).values())
    paces=[value.get('responsive_pace')]+[w.get(k) for w in window_metrics for k in ('pace','last_observed_pace')]
    for pace in paces:
        if not pace:continue
        pace['age_seconds']=max(0,(now-datetime.fromisoformat(pace['end'])).total_seconds())
        if value['stale'] or latest and latest['simulated'] or value.get('capture_lifecycle') in ('completed','interrupted'):pace['active']=False
        running=value['activity']['state'] in ('running','waiting','capture_delayed','capture_failing')
        offline=value.get('twitch',{}).get('status')=='offline'
        expired=running and not offline and pace['age_seconds']>=PACE_HISTORY_SECONDS
        shown=deepcopy(pace['estimates'])
        if expired:shown=estimates(None,None,0)
        elif not pace['active'] or not running or offline:shown['eta']=None
        pace['presentation']=dict(state='paused' if expired else 'observed' if pace['active'] and running and not offline else 'historical',
            can_age=False,pause_after_seconds=PACE_HISTORY_SECONDS,
            history_after_seconds=PACE_TREND_SECONDS,expire_after_seconds=PACE_HISTORY_SECONDS,
            running=running and not offline,
            factor=rational(Fraction(1)),estimates=shown,assumption=None,
            contributes_to_progress=False)
    level=value.get('display_level')
    if level:
        level['age_seconds']=max(0,(now-datetime.fromisoformat(level['timestamp'])).total_seconds())
        level['last_known']=(level['timestamp']!=value['latest_attempt_at'] or level['age_seconds']>value['stale_after_seconds'])
    decision=value.get('percentage_state')
    deadline=(decision.get('verification_deadline') or decision.get('confirmation_deadline')) if decision else None
    if decision and not decision['public_eligible'] and deadline and now>datetime.fromisoformat(deadline):
        decision.update(status='unresolved_numerical_continuity',reason='confirmation_expired')
        value['stale']=True
        for pace in paces:
            if pace:
                pace['active']=False;pace['presentation']['estimates']['eta']=None
    if value['stale'] or latest and latest['simulated']:
        value['estimates']=estimates(None,None,0)
        for metric in value.get('windows',{}).values():
            metric.update(eligible=False,state='stale',reason='stale_or_simulated_reading',estimates=estimates(None,None,0))
    if value.get('early_pace') and (value['stale'] or latest and latest['simulated']):
        value['early_pace'].update(active=False,reason='stale_or_simulated_reading')
    for metric in list(value.get('windows',{}).values())+window_metrics:
        eta=metric.get('eta')
        if eta:
            eta['age_seconds']=max(0,(now-datetime.fromisoformat(eta['estimated_at'])).total_seconds())
            if eta.get('rate_observed_at'):eta['rate_age_seconds']=max(0,(now-datetime.fromisoformat(eta['rate_observed_at'])).total_seconds())
            eta['historical'] = (value['stale'] or not (metric.get('pace') or {}).get('active')
                or (metric.get('pace') or {}).get('presentation',{}).get('state')!='observed')
        if 'eligibility_checks' in metric:
            metric['eligibility_checks']['fresh']=not value['stale'] and not (latest and latest['simulated'])
        observed=metric.get('observed')
        if observed and observed['available']:
            observed['age_seconds']=max(0,(now-datetime.fromisoformat(observed['end'])).total_seconds())
            observed['paused'] |= value['stale'] or bool(value.get('percentage_state') and not value['percentage_state']['public_eligible'])
    return value


def interval_gain(previous,row,value,connected):
    """Original diagnostic graph intervals; public totals use window endpoints."""
    if not connected or not previous or not value or row.get('crop_suspect') or value['bp']<previous['bp']:return None
    gain=exp_change(previous['bp'],value['bp'],value['level']['value'])
    if gain:
        if all(supported_exp(p) for p in (previous,value)):
            if int(value['exp'])<int(previous['exp']):return None
            gain['value']=rational(Fraction(int(value['exp'])-int(previous['exp'])))
            gain['basis']='observed_exp_endpoints'
        gain.update(start=previous['timestamp'],end=value['timestamp'],
            first_event_id=previous['event_id'],last_event_id=value['event_id'],level=value['level']['value'])
        if all(p['exp'] is not None for p in (previous,value)) and int(value['exp'])<int(previous['exp']):return None
    return gain


def history(snapshot):
    points=[]
    comparisons={c['event_id']:c for c in snapshot['percentage_progress'].get('comparisons',[])}
    previous=None;previous_row=None;previous_point=None
    for row in snapshot['observations']:
        if row.get('reading_invalidated'):
            previous=None;previous_row=None;previous_point=None
            continue
        value=reading(row)
        comparison=comparisons.get(row['event_id'])
        connected=bool(comparison and comparison['reason']=='contiguous_diagnostic_endpoints' and comparison['change'] in ('positive','zero'))
        point,invalid=percentage_point(row)
        eligible=bool(point and invalid is None and row.get('percentage_review',{}).get('progress_eligible'))
        if 'comparisons' not in snapshot['percentage_progress']:
            if point:point['interval_seconds']=row['interval_seconds']
            connected=bool(eligible and previous_point and not row['percentage_review'].get('break_before')
                and boundary(previous_point,point,row) is None and point['bp']>=previous_point['bp'])
        gain=interval_gain(previous,row,value,connected) if previous_row and not previous_row.get('crop_suspect') else None
        points.append(dict(event_id=row['event_id'],timestamp=row['received_at'] or row['attempted_at'],percentage_review=row.get('percentage_review'),
            connect_previous=connected,gain=gain,
            reading=value,status=row['status'],fresh_at_capture=row['fresh_at_capture'],
            interval_seconds=row['interval_seconds'],level=level_evidence(row),
            break_reason=comparison['reason'] if comparison else None))
        previous=value;previous_row=row;previous_point=point if eligible else None
    for reading_value in snapshot.get('manual_observations',[]):
        points.append(dict(event_id=reading_value['event_id'],timestamp=reading_value['timestamp'],percentage_review=None,
            connect_previous=False,gain=None,reading=reading_value,status='manual_correction',fresh_at_capture=False,
            interval_seconds=snapshot.get('interval_seconds') or 15,level=reading_value['level'],break_reason='manual_historical_correction'))
    return sorted(points,key=lambda p:p['timestamp'])
