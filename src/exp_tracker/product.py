"""Read-only player presentation of existing experimental evidence, never accounting."""

from copy import deepcopy
from datetime import datetime,timedelta,timezone
from fractions import Fraction

from .diagnostic_progress import percentage_point,rational,quantization_pace,elapsed_seconds,difference_bounds
from .diagnostic_evidence import project
from .diagnostic_percentage import boundary
from .exp_requirements import requirement
from .exp_consistency import MODES, assess

WINDOWS=(5,10,15,30)
PRODUCT_ROWS=640  # 30 minutes at the explicit offline 3s floor, plus level-context/boundary evidence.
PACE_MIN_SECONDS=5
PACE_TREND_SECONDS=300
OBSERVED_MAX_GAP_SECONDS=60
OBSERVED_MAX_MISSING=2


def _last_connected_pace(snapshot, display_level):
    """Consumer estimate from an existing safe segment, never window/ranking evidence."""
    rows=snapshot['observations'];data=snapshot['percentage_progress']
    positions={r['event_id']:i for i,r in enumerate(rows)}
    for segment in reversed(data['segments']):
        if display_level and segment['level']!=display_level['value']:continue
        points=[reading(r) for r in rows[positions[segment['first_event_id']]:positions[segment['last_event_id']]+1]]
        points=[p for p in points if p]
        if len(points)<2:continue
        end=datetime.fromisoformat(points[-1]['timestamp'])
        points=[p for p in points if (end-datetime.fromisoformat(p['timestamp'])).total_seconds()<=PACE_TREND_SECONDS]
        if len(points)<2:continue
        first,last=points[0],points[-1]
        elapsed=elapsed_seconds(datetime.fromisoformat(first['timestamp']),end)
        if elapsed<PACE_MIN_SECONDS:continue
        diff=last['bp']-first['bp']
        if diff<0:continue
        pace=dict(value=rational(Fraction(diff*36)/elapsed),**quantization_pace(first['bp'],last['bp'],elapsed))
        calculated=estimates(segment,pace,last['bp'])
        basis='displayed_percentage_endpoints'
        if (calculated['exp_per_hour'] and all(p['evidence']=='strict_full' and p['exp'] is not None
                and p['exp_validity']['status']=='consistent' for p in (first,last)) and int(last['exp'])>=int(first['exp'])):
            calculated['exp_per_hour']['value']=rational(Fraction((int(last['exp'])-int(first['exp']))*3600)/elapsed)
            basis='observed_exp_endpoints'
        # Two samples can seed a rate, but cannot seed an ETA.
        tentative=len(points)<3 or elapsed<30
        if tentative:calculated['eta']=None
        current=data['current_segment']
        return dict(active=bool(current and current['last_event_id']==last['event_id'] and rows[-1]['event_id']==last['event_id']),
            tentative=tentative,level=segment['level'],start=first['timestamp'],end=last['timestamp'],
            readings=len(points),span_seconds=rational(elapsed),coverage_seconds=rational(elapsed),interruptions=0,
            estimates=calculated,basis=basis,history_basis='last_connected_segment',
            evidence_counts={kind:sum(p['evidence']==kind for p in points) for kind in ('strict_full','strict_percentage_only','grammar_recovered')},
            policy='responsive_pace_v2',minimum_seconds=PACE_MIN_SECONDS,trend_seconds=PACE_TREND_SECONDS,
            trusted=False,reason=data['reason'])
    return None


def responsive_pace(snapshot, display_level):
    """Pool captured intervals inside recent safe context; holes supply no gain/time."""
    rows=snapshot['observations'];data=snapshot['percentage_progress']
    reference=next((r.get('received_at') or r.get('attempted_at') for r in reversed(rows)),None)
    if not reference:return None
    # Review decisions already carry the causal as-of clock from snapshot().
    points,_,_,_=observed_sequence(snapshot,now=datetime.fromisoformat(reference))
    allowed={p['event_id'] for p in points}
    edges=[];comp={c['event_id']:c for c in data['comparisons']}
    for before,after in zip(rows,rows[1:]):
        if not {before['event_id'],after['event_id']}<=allowed:continue
        if comp[after['event_id']]['reason']!='contiguous_diagnostic_endpoints':continue
        a,b=reading(before),reading(after)
        if not a or not b:continue
        if display_level and b['level']['value']!=display_level['value']:continue
        if before.get('crop_suspect') or after.get('crop_suspect'):continue
        if all(p['exp'] is not None and p['evidence']=='strict_full' for p in (a,b)) and int(b['exp'])<int(a['exp']):
            edges.clear();continue  # A visible integer decrease cannot be smoothed into gains.
        edges.append((a,b))
    if edges:
        # Failed attempts must not advance the rate's sample or change a held value.
        cutoff=datetime.fromisoformat(edges[-1][1]['timestamp'])-timedelta(seconds=PACE_TREND_SECONDS)
        edges=[(a,b) for a,b in edges if datetime.fromisoformat(a['timestamp'])>=cutoff]
    elapsed=sum((elapsed_seconds(datetime.fromisoformat(a['timestamp']),datetime.fromisoformat(b['timestamp'])) for a,b in edges),Fraction(0))
    if elapsed<PACE_MIN_SECONDS:
        old=_last_connected_pace(snapshot,display_level)
        if old:old['active']=False
        return old
    groups=[]
    for a,b in edges:
        if groups and groups[-1][1]['event_id']==a['event_id']:groups[-1]=(groups[-1][0],b)
        else:groups.append((a,b))
    diff=sum(b['bp']-a['bp'] for a,b in groups)
    pace=dict(value=rational(Fraction(diff*36)/elapsed))
    for rule in ('nearest_half_up','truncation'):
        bins=[difference_bounds(a['bp'],b['bp'])[rule] for a,b in groups]
        pace[rule]=dict(lower=rational(sum((v[0] for v in bins),Fraction(0))*36/elapsed),
            upper=rational(sum((v[1] for v in bins),Fraction(0))*36/elapsed))
    first,last=edges[0][0],edges[-1][1]
    calculated=estimates(dict(requirement=requirement(last['level']['value'])),pace,last['bp'])
    basis='captured_percentage_intervals'
    if calculated['exp_per_hour'] and all(p['evidence']=='strict_full' and p['exp'] is not None
            and p['exp_validity']['status']=='consistent' for pair in edges for p in pair):
        gain=sum(int(b['exp'])-int(a['exp']) for a,b in edges)
        if gain>=0:
            calculated['exp_per_hour']['value']=rational(Fraction(gain*3600)/elapsed)
            basis='observed_exp_endpoints'
    ids={p['event_id'] for pair in edges for p in pair}
    tentative=len(ids)<3 or elapsed<30
    active=bool(rows[-1]['event_id']==last['event_id'] and not rows[-1].get('run_interrupted')
        and snapshot.get('run_id',rows[-1]['run_id'])==rows[-1]['run_id'])
    if tentative or not active:calculated['eta']=None
    return dict(active=active,tentative=tentative,level=last['level']['value'],start=first['timestamp'],end=last['timestamp'],
        readings=len(ids),span_seconds=rational(elapsed_seconds(datetime.fromisoformat(first['timestamp']),datetime.fromisoformat(last['timestamp']))),
        coverage_seconds=rational(elapsed),interruptions=len(groups)-1,estimates=calculated,basis=basis,
        evidence_counts={kind:sum(reading(r)['evidence']==kind for r in rows if r['event_id'] in ids) for kind in ('strict_full','strict_percentage_only','grammar_recovered')},
        policy='responsive_pace_v2',minimum_seconds=PACE_MIN_SECONDS,trend_seconds=PACE_TREND_SECONDS,
        trusted=False,reason=data['reason'])


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
    return events


def fraction(value):
    return Fraction(value['numerator'],value['denominator'])


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
    if row.get('percentage_review',{}).get('public_eligible') is False:return None
    if 'experimental_level' not in row: row=project([row])[0]
    point,_=percentage_point(row)
    if not point: return None
    full=row.get('candidate') if point['evidence']=='strict_full' else None
    if point['evidence']=='grammar_recovered':
        proposed=(row.get('interpretations') or {}).get('full_exp',{})
        if proposed.get('classification')=='unique_proposal':
            candidate=proposed['proposals'][0]['reading']
            if candidate['percentage']==point['percentage']: full=candidate
    exp=full['exp'] if full and row['exp_validity']['status']!='invalid' else None
    level=level_evidence(row)
    return dict(event_id=point['event_id'],timestamp=point['timestamp'],percentage=point['percentage'],
        bp=point['bp'],exp=exp,estimated_exp=percentage_exp(point['bp'],level) if exp is None else None,
        exp_validity=row['exp_validity'],evidence=point['evidence'],grammar_policy=point['grammar_policy'],
        fresh_at_capture=point['fresh_at_capture'] and point['capture_acquired'],level=level,
        simulated=row.get('timing_mode')=='simulated',trusted=False)


def observed_sequence(snapshot, *, now):
    """Endpoint comparisons across short disclosed holes, never connected pace/gains."""
    points=[];holes=[];previous=None;pending=[];last=None;break_reason='baseline'
    reviews={r['event_id']:r for r in snapshot['percentage_progress']['percentage_reviews']}
    for row in project(snapshot['observations']):
        point,invalid=percentage_point(row);decision=reviews[row['event_id']]
        stamp=row.get('received_at') or row.get('attempted_at')
        # Context placeholders test ownership/order only; never supply a numeric endpoint.
        context=dict(channel=row.get('assigned_channel') or row.get('channel'),source_channel=row.get('channel'),
            source_kind=row.get('source_kind'),source_identity=row.get('source_identity'),
            character_id=row.get('character_id'),session_id=row.get('session_id'),run_id=row.get('run_id'),
            index=row.get('index'),coordinator_instance=row.get('coordinator_instance'),timestamp=stamp,
            interval_seconds=row.get('interval_seconds',15),level=(row.get('experimental_level') or {}).get('value'))
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
                elif edge=='sampling_gap' and (when-datetime.fromisoformat(previous['timestamp'])).total_seconds()>OBSERVED_MAX_GAP_SECONDS:hard='gap_exceeds_limit'
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
        if not usable and not allowed_missing:hard=hard or decision['reason'] or invalid or 'unusable_observation'
        if usable and last and hard is None:
            elapsed=(when-datetime.fromisoformat(last['timestamp'])).total_seconds()
            absent=(context['index']-previous['index']-1) if previous and context['run_id']==previous['run_id'] else 0
            absent=max(0,absent)+sum(h['missing_indices'] for h in pending)
            if len(pending)+absent>OBSERVED_MAX_MISSING or elapsed>OBSERVED_MAX_GAP_SECONDS:hard='gap_exceeds_limit'
            if point['bp']<last['bp'] or point['bp']-last['bp']>=1000:
                hard='unresolved_numerical_continuity';usable=False
            if row.get('frame_sha256') and row['frame_sha256']==last.get('frame_sha256'):
                hard='duplicate_source_frame';usable=False
        if hard:
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
            if len(pending)+sum(h['missing_indices'] for h in pending)>OBSERVED_MAX_MISSING or (when-datetime.fromisoformat(last['timestamp'])).total_seconds()>OBSERVED_MAX_GAP_SECONDS:
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
    observed=observed_sequence(snapshot,now=now)
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
            complete=(len(points)>=3 and elapsed>=30 and elapsed>=Fraction(minutes*60*9,10)
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
        if metric['observed']['available']:
            metric['observed']['paused'] |= bool(rows and (rows[-1].get('run_interrupted')
                or snapshot.get('run_id',rows[-1]['run_id'])!=rows[-1]['run_id']))
        result[str(minutes)]=metric
    return result


def player(snapshot,*,now=None):
    now=now or datetime.now(timezone.utc)
    rows=snapshot['observations'];latest=None
    for row in rows:
        value=reading(row)
        if value and row.get('timestamp_ordered') is not False and value['timestamp']:
            when=datetime.fromisoformat(value['timestamp'])
            if when<=now and (latest is None or when>datetime.fromisoformat(latest['timestamp'])): latest=value
    # Display context never enters reading(), numerical checks or progress inputs.
    display_level=None
    for row in rows:
        level=level_evidence(row);stamp=row.get('received_at')
        if (stamp and datetime.fromisoformat(stamp)<=now and row.get('timestamp_ordered') is not False
                and row.get('fresh_at_capture') and row.get('capture_acquired') and row.get('hud_count')==1
                and level['value'] is not None and level['status'] in ('agreement','provisional_neural')):
            display_level=dict(value=level['value'],timestamp=stamp,event_id=row['event_id'],
                evidence=level,display_only=True,trusted=False)
    progress=snapshot['percentage_progress'];segment=progress['current_segment']
    usable=bool(latest and segment and segment['last_event_id']==latest['event_id'] and rows and rows[-1]['event_id']==latest['event_id'])
    movement=progress.get('latest_movement') if usable else None
    movement=movement if movement and movement.get('change') in ('positive','zero') else None
    decision=progress.get('percentage_state')
    result=dict(channel=snapshot['channel'],character=snapshot['selected_character'],session_id=(snapshot['session'] or {}).get('id'),
        percentage_state=decision,display_level=display_level,level_events=level_events(rows),
        source_kind=snapshot.get('source_kind'),reading=latest,latest_attempt_at=(rows[-1].get('received_at') or rows[-1].get('attempted_at')) if rows else None,
        latest_attempt_status=rows[-1]['status'] if rows else 'waiting',
        stale_after_seconds=snapshot['stale_after_seconds'],movement=movement,
        segment=dict(start=segment['start'],end=segment['end'],readings=segment['readings'],span_seconds=segment['span_seconds'],
            difference_percentage_points=segment['difference_percentage_points'],evidence_counts=segment['evidence_counts']) if usable else None,
        estimates=estimates(segment,progress['current_pace'],latest['bp']) if usable else estimates(None,None,0),
        windows=window_comparisons(snapshot,now=now),trusted=False,experimental=True)
    historical=next((s for s in reversed(progress['segments']) if s['pace']),None)
    result['early_pace']=dict(active=bool(usable and progress['current_pace']),reason=progress['reason'],
        segment=historical,estimates=estimates(historical,historical['pace'],int(Fraction(historical['end_percentage'])*100)) if historical else estimates(None,None,0),
        label='EXPERIMENTAL / UNVERIFIED; early segment estimate, not a completed window')
    result['responsive_pace']=responsive_pace(snapshot,display_level)
    return refresh(result,now=now)


def refresh(value,*,now=None,activity=None):
    now=now or datetime.now(timezone.utc);value=deepcopy(value)
    latest=value['reading'];age=(now-datetime.fromisoformat(latest['timestamp'])).total_seconds() if latest else None
    value['age_seconds']=max(0,age) if age is not None else None
    value['stale']=age is None or age<0 or age>value['stale_after_seconds'] or not latest['fresh_at_capture']
    value['activity']=activity or dict(state='coordinator_stopped')
    pace=value.get('responsive_pace')
    if pace:
        pace['age_seconds']=max(0,(now-datetime.fromisoformat(pace['end'])).total_seconds())
        if value['stale'] or latest and latest['simulated']:pace['active']=False
    level=value.get('display_level')
    if level:
        level['age_seconds']=max(0,(now-datetime.fromisoformat(level['timestamp'])).total_seconds())
        level['last_known']=(level['timestamp']!=value['latest_attempt_at'] or level['age_seconds']>value['stale_after_seconds'])
    decision=value.get('percentage_state')
    deadline=(decision.get('verification_deadline') or decision.get('confirmation_deadline')) if decision else None
    if decision and not decision['public_eligible'] and deadline and now>datetime.fromisoformat(deadline):
        decision.update(status='unresolved_numerical_continuity',reason='confirmation_expired')
        value['stale']=True
        if pace:pace['active']=False
    if value['stale'] or latest and latest['simulated']:
        value['estimates']=estimates(None,None,0)
        for metric in value.get('windows',{}).values():
            metric.update(eligible=False,state='stale',reason='stale_or_simulated_reading',estimates=estimates(None,None,0))
    if value.get('early_pace') and (value['stale'] or latest and latest['simulated']):
        value['early_pace'].update(active=False,reason='stale_or_simulated_reading')
    for metric in value.get('windows',{}).values():
        if 'eligibility_checks' in metric:
            metric['eligibility_checks']['fresh']=not value['stale'] and not (latest and latest['simulated'])
        observed=metric.get('observed')
        if observed and observed['available']:
            observed['age_seconds']=max(0,(now-datetime.fromisoformat(observed['end'])).total_seconds())
            observed['paused'] |= value['stale'] or bool(value.get('percentage_state') and not value['percentage_state']['public_eligible'])
    return value


def interval_gain(previous,row,value,connected):
    """Shared public interval interpretation; history and rolling aggregation agree."""
    if not connected or not previous or not value or row.get('crop_suspect') or value['bp']<previous['bp']:return None
    gain=exp_change(previous['bp'],value['bp'],value['level']['value'])
    if gain:
        if all(p['evidence']=='strict_full' and p['exp'] is not None and p['exp_validity']['status']=='consistent' for p in (previous,value)):
            if int(value['exp'])<int(previous['exp']):return None
            gain['value']=rational(Fraction(int(value['exp'])-int(previous['exp'])))
            gain['basis']='observed_exp_endpoints'
        gain.update(start=previous['timestamp'],end=value['timestamp'],
            first_event_id=previous['event_id'],last_event_id=value['event_id'],level=value['level']['value'])
        if all(p['exp'] is not None and p['evidence']=='strict_full' for p in (previous,value)) and int(value['exp'])<int(previous['exp']):return None
    return gain


def history(snapshot):
    points=[]
    comparisons={c['event_id']:c for c in snapshot['percentage_progress']['comparisons']}
    previous=None;previous_row=None
    for row in snapshot['observations']:
        value=reading(row)
        comparison=comparisons.get(row['event_id'])
        connected=bool(comparison and comparison['reason']=='contiguous_diagnostic_endpoints' and comparison['change'] in ('positive','zero'))
        gain=interval_gain(previous,row,value,connected) if previous_row and not previous_row.get('crop_suspect') else None
        points.append(dict(event_id=row['event_id'],timestamp=row['received_at'] or row['attempted_at'],percentage_review=row.get('percentage_review'),
            connect_previous=connected,gain=gain,
            reading=value,status=row['status'],fresh_at_capture=row['fresh_at_capture'],
            interval_seconds=row['interval_seconds'],level=level_evidence(row),
            break_reason=comparison['reason'] if comparison else None))
        previous=value;previous_row=row
    return points
