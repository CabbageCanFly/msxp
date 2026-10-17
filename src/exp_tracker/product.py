"""Read-only player presentation of existing experimental evidence, never accounting."""

from copy import deepcopy
from datetime import datetime,timedelta,timezone
from fractions import Fraction

from .diagnostic_progress import percentage_point,rational,quantization_pace,elapsed_seconds
from .diagnostic_evidence import project

WINDOWS=(5,10,15,30)
PRODUCT_ROWS=640  # 30 minutes at the explicit offline 3s floor, plus level-context/boundary evidence.


def fraction(value):
    return Fraction(value['numerator'],value['denominator'])


def level_evidence(row):
    return row['experimental_level'] if 'experimental_level' in row else project([row])[0]['experimental_level']


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
    if 'experimental_level' not in row: row=project([row])[0]
    point,_=percentage_point(row)
    if not point: return None
    full=row.get('candidate') if point['evidence']=='strict_full' else None
    if point['evidence']=='grammar_recovered':
        proposed=(row.get('interpretations') or {}).get('full_exp',{})
        if proposed.get('classification')=='unique_proposal':
            candidate=proposed['proposals'][0]['reading']
            if candidate['percentage']==point['percentage']: full=candidate
    return dict(event_id=point['event_id'],timestamp=point['timestamp'],percentage=point['percentage'],
        bp=point['bp'],exp=full['exp'] if full and row['exp_validity']['status']!='invalid' else None,
        exp_validity=row['exp_validity'],evidence=point['evidence'],grammar_policy=point['grammar_policy'],
        fresh_at_capture=point['fresh_at_capture'] and point['capture_acquired'],level=level_evidence(row),
        simulated=row.get('timing_mode')=='simulated',trusted=False)


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
    result={}
    for minutes in WINDOWS:
        cutoff=end-timedelta(minutes=minutes)
        points=[(r,p) for r,p in sequence if p and cutoff<=datetime.fromisoformat(p['timestamp'])<=end]
        metric=dict(minutes=minutes,reference_at=reference,requested_start=cutoff.isoformat(),eligible=False,
            state='building_history',reason='insufficient_contiguous_coverage',readings=len(points),
            coverage_seconds=rational(Fraction(0)),coverage_fraction=rational(Fraction(0)),
            difference_percentage_points=None,estimates=estimates(None,None,0),trusted=False)
        if points:
            first,last=points[0][1],points[-1][1]
            a,b=datetime.fromisoformat(first['timestamp']),datetime.fromisoformat(last['timestamp'])
            elapsed=elapsed_seconds(a,b)
            metric.update(start=first['timestamp'],end=last['timestamp'],coverage_seconds=rational(elapsed),
                coverage_fraction=rational(elapsed/(minutes*60)),
                evidence_counts={kind:sum(p['evidence']==kind for _,p in points) for kind in ('strict_full','strict_percentage_only','grammar_recovered')})
            boundary=elapsed_seconds(cutoff,a)
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
    progress=snapshot['percentage_progress'];segment=progress['current_segment']
    usable=bool(latest and segment and segment['last_event_id']==latest['event_id'] and rows and rows[-1]['event_id']==latest['event_id'])
    movement=progress.get('latest_movement') if usable else None
    movement=movement if movement and movement.get('change') in ('positive','zero') else None
    result=dict(channel=snapshot['channel'],character=snapshot['selected_character'],session_id=(snapshot['session'] or {}).get('id'),
        source_kind=snapshot.get('source_kind'),reading=latest,latest_attempt_at=(rows[-1].get('received_at') or rows[-1].get('attempted_at')) if rows else None,
        latest_attempt_status=rows[-1]['status'] if rows else 'waiting',
        stale_after_seconds=snapshot['stale_after_seconds'],movement=movement,
        segment=dict(start=segment['start'],end=segment['end'],readings=segment['readings'],span_seconds=segment['span_seconds'],
            difference_percentage_points=segment['difference_percentage_points'],evidence_counts=segment['evidence_counts']) if usable else None,
        estimates=estimates(segment,progress['current_pace'],latest['bp']) if usable else estimates(None,None,0),
        windows=window_comparisons(snapshot,now=now),trusted=False,experimental=True)
    return refresh(result,now=now)


def refresh(value,*,now=None,activity=None):
    now=now or datetime.now(timezone.utc);value=deepcopy(value)
    latest=value['reading'];age=(now-datetime.fromisoformat(latest['timestamp'])).total_seconds() if latest else None
    value['age_seconds']=max(0,age) if age is not None else None
    value['stale']=age is None or age<0 or age>value['stale_after_seconds'] or not latest['fresh_at_capture']
    value['activity']=activity or dict(state='coordinator_stopped')
    if value['stale'] or latest and latest['simulated']:
        value['estimates']=estimates(None,None,0)
        for metric in value.get('windows',{}).values():
            metric.update(eligible=False,state='stale',reason='stale_or_simulated_reading',estimates=estimates(None,None,0))
    return value


def history(snapshot):
    points=[]
    for row in snapshot['observations']:
        value=reading(row)
        points.append(dict(event_id=row['event_id'],timestamp=row['received_at'] or row['attempted_at'],
            reading=value,status=row['status'],fresh_at_capture=row['fresh_at_capture'],
            interval_seconds=row['interval_seconds'],level=level_evidence(row),
            break_reason=next((c['reason'] for c in snapshot['percentage_progress']['comparisons'] if c['event_id']==row['event_id']),None)))
    return points
