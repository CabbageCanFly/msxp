"""Displayed-percentage diagnostics only. No Store writes or trusted gains."""

from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction

from .exp_requirements import requirement
from .shadow_grammar import interpret_exp

LABEL = 'EXPERIMENTAL / UNVERIFIED'


def rational(value):
    return dict(numerator=value.numerator, denominator=value.denominator, approximate=float(value))


def difference_bounds(first, last):
    """Outer bounds in basis points; formatting hypotheses, not OCR confidence."""
    result = {}
    for rule, offset, width in [('nearest_half_up', Fraction(1,2), Fraction(1,2)), ('truncation', 0, 1)]:
        low = max(0, last-offset)-min(10000, first+width)
        high = min(10000, last+width)-max(0, first-offset)
        result[rule] = (Fraction(low), Fraction(high), '[-0.5,+0.5)' if offset else '[0,1)')
    return result


def quantization_pace(first, last, elapsed):
    return {rule: dict(lower=rational(low*36/elapsed), upper=rational(high*36/elapsed), endpoint_error_bp=error)
            for rule,(low,high,error) in difference_bounds(first,last).items()}


def elapsed_seconds(a, b):
    delta = b-a
    return Fraction((delta.days*86400+delta.seconds)*1000000+delta.microseconds, 1000000)


def percentage_point(row, *, include_recovered=True):
    """One percentage per immutable attempt; don't trust supplied proposal objects."""
    if row.get('candidate_invalid') or row.get('percentage_only_invalid'):
        return None, 'candidate_contradiction'
    interpreted = interpret_exp(row.get('raw_text'))
    kind, reading = None, None
    if row.get('candidate'):
        if interpreted['strict_full'] and all(row['candidate'].get(k)==interpreted['strict_full'][k] for k in ('exp','percentage')):
            kind, reading = 'strict_full', interpreted['strict_full']
        else:
            return None, 'candidate_contradiction'
    elif row.get('percentage_only_candidate'):
        if interpreted['strict_percentage_only'] == row['percentage_only_candidate']:
            kind, reading = 'strict_percentage_only', interpreted['strict_percentage_only']
        else:
            return None, 'candidate_contradiction'
    elif include_recovered and interpreted['percentage']['classification']=='unique_proposal':
        kind, reading = 'grammar_recovered', interpreted['percentage']['proposals'][0]['reading']
    if reading is None:
        return None, 'invalid_or_ambiguous_percentage'
    point = dict(event_id=row.get('event_id'), index=row.get('index'), run_id=row.get('run_id'),
        channel=row.get('assigned_channel') or row.get('channel'), source_channel=row.get('channel'),
        source_kind=row.get('source_kind'), character_id=row.get('character_id'), session_id=row.get('session_id'),
        timestamp=row.get('received_at'), percentage=reading['percentage'], bp=int(Decimal(reading['percentage'])*100),
        fresh_at_capture=row.get('fresh_at_capture') is True,capture_acquired=row.get('capture_acquired') is True,
        evidence=kind, grammar_policy=interpreted['policy'] if kind=='grammar_recovered' else None,
        raw_text=row.get('raw_text'), visual_level=row.get('visual_level'), neural_level=(row.get('neural_level') or {}).get('level'),
        trusted=False, identity_verified=False, numerical_identity_verified=False)
    reason = None
    if not row.get('fresh_at_capture') or row.get('capture_acquired') is not True or row.get('status') not in ('diagnostic_pair','diagnostic_percentage_only','malformed_or_unavailable'):
        reason = 'failed_or_stale_capture'
    elif row.get('hud_count') != 1:
        reason = 'hud_not_unique'
    elif not point['channel'] or point['character_id'] is None or point['session_id'] is None or not point['event_id'] or not point['run_id']:
        reason = 'explicit_assignment_missing'
    elif row.get('visual_status') != 'available' or type(point['visual_level']) is not int or not 1<=point['visual_level']<=200:
        reason = 'visual_level_unavailable'
    elif type(point['index']) is not int or point['index']<1:
        reason = 'attempt_index_unavailable'
    elif point['neural_level'] is not None and point['neural_level'] != point['visual_level'] or row.get('relation')=='conflict':
        reason = 'level_evidence_conflict'
    try:
        when = datetime.fromisoformat(point['timestamp'])
        if when.utcoffset() is None or row.get('timestamp_ordered') is False:
            raise ValueError
    except (TypeError,ValueError):
        reason = reason or 'timestamp_unavailable_or_out_of_order'
    point['comparison_eligible'] = reason is None
    return point, reason


def progress(rows, *, now=None, stale_after_seconds=45, include_recovered=True, min_readings=3, min_span_seconds=30, current_run_id=None):
    if type(min_readings) is not int or min_readings<3 or not 30<=min_span_seconds<=86400:
        raise ValueError('Pace requires >=3 readings spanning >=30 seconds')
    now = now or datetime.now(timezone.utc)
    segments, comparisons = [], []
    previous, current, latest, latest_time = None, None, None, None
    seen = set()
    for row in rows:
        point, reason = percentage_point(row,include_recovered=include_recovered)
        when = None
        if point and point['timestamp']:
            try:
                when = datetime.fromisoformat(point['timestamp'])
                if when.utcoffset() is None: when=None
                elif when>now: reason=reason or 'future_timestamp';when=None
            except (TypeError,ValueError): pass
        if point and (latest_time is None or when is not None and when>latest_time):
            latest,latest_time = point,when
        edge = dict(event_id=row.get('event_id'), change='missing_comparison', reason=reason)
        if row.get('event_id') in seen:
            reason = 'duplicate_event'
        seen.add(row.get('event_id'))
        if not point or reason:
            if point: point['comparison_eligible']=False
            edge['reason'] = reason
            comparisons.append(edge)
            if current: current['end_reason'] = reason
            previous = current = None
            continue
        when = datetime.fromisoformat(point['timestamp'])
        if previous:
            elapsed = elapsed_seconds(datetime.fromisoformat(previous['timestamp']),when)
            cadence = Fraction(str(previous['interval_seconds']))
            reason = ('source_changed' if (point['channel'],point['source_channel'],point['source_kind']) != (previous['channel'],previous['source_channel'],previous['source_kind']) else
                'character_or_session_changed' if (point['character_id'],point['session_id']) != (previous['character_id'],previous['session_id']) else
                'run_boundary' if point['run_id'] != previous['run_id'] else
                'level_changed' if point['visual_level'] != previous['visual_level'] else
                'nonincreasing_timestamp' if elapsed<=0 else
                'missing_attempt' if point['index'] != previous['index']+1 else
                'sampling_gap' if elapsed>min(Fraction(120),cadence*Fraction(3,2)) else None)
            if reason is None:
                diff = point['bp']-previous['bp']
                edge.update(change='positive' if diff>0 else 'negative' if diff<0 else 'zero',
                    difference_bp=diff,difference_percentage_points=f'{Decimal(diff)/100:.2f}',elapsed_seconds=rational(elapsed))
                if diff<0: reason='percentage_decrease_no_levelup_inferred'
        if reason == 'nonincreasing_timestamp':
            if current: current['end_reason']=reason
            comparisons.append({**edge,'reason':reason})
            previous=current=None
            continue
        if reason or current is None:
            if current: current['end_reason'] = reason
            current = dict(channel=point['channel'],character_id=point['character_id'],session_id=point['session_id'],
                run_id=point['run_id'],level=point['visual_level'],level_provenance='available_visual_tesseract; no conflicting neural level',
                start_reason=reason or 'baseline',end_reason=None,points=[])
            segments.append(current)
        point['interval_seconds'] = row.get('interval_seconds',15)
        current['points'].append(point)
        previous = point
        edge['reason'] = reason or ('baseline' if len(current['points'])==1 else 'contiguous_diagnostic_endpoints')
        comparisons.append(edge)
    for segment in segments:
        points = segment.pop('points')
        if not points:
            segment.update(readings=0,pace=None)
            continue
        first,last = points[0],points[-1]
        elapsed = elapsed_seconds(datetime.fromisoformat(first['timestamp']),datetime.fromisoformat(last['timestamp']))
        diff = last['bp']-first['bp']
        counts = {kind:sum(p['evidence']==kind for p in points) for kind in ('strict_full','strict_percentage_only','grammar_recovered')}
        segment.update(first_event_id=first['event_id'],last_event_id=last['event_id'],readings=len(points),
            start=first['timestamp'],end=last['timestamp'],start_percentage=first['percentage'],end_percentage=last['percentage'],
            difference_bp=diff,difference_percentage_points=f'{Decimal(diff)/100:.2f}',span_seconds=rational(elapsed),
            evidence_counts=counts,missing_intermediate_attempts=0,rejected_intermediate_attempts=0,
            pace=None,estimated_exp=None,pace_reason='insufficient_readings' if len(points)<min_readings else 'insufficient_span',
            quantization_bounds={rule:dict(lower_percentage_points=rational(low/100),upper_percentage_points=rational(high/100))
                                 for rule,(low,high,_) in difference_bounds(first['bp'],last['bp']).items()},
            requirement=requirement(segment['level']))
        if len(points)>=2 and segment['requirement']['to_next'] is not None:
            total=segment['requirement']['to_next']
            segment['estimated_exp'] = dict(label=LABEL,requirement_status='community_provisional',
                bounds_kind='outer_display_quantization_bounds_not_actual_earned_EXP',
                hypotheses={rule:dict(lower=rational(low*total/10000),upper=rational(high*total/10000))
                            for rule,(low,high,_) in difference_bounds(first['bp'],last['bp']).items()})
        if len(points)>=min_readings and elapsed>=Fraction(str(min_span_seconds)):
            segment.update(pace_reason='eligible_experimental_endpoints',pace=dict(label=LABEL,units='percentage_points_per_hour',
                value=rational(Fraction(diff*36)/elapsed),**quantization_pace(first['bp'],last['bp'],elapsed),
                bounds_kind='outer_quantization_bounds_not_statistical_intervals'))
    reason = comparisons[-1]['reason'] if comparisons else 'no_observations'
    if current and current_run_id is not None and current['run_id'] != current_run_id:
        current['end_reason']='new_run_waiting_for_capture'
        current=None;reason='new_run_waiting_for_capture'
    if rows and rows[-1].get('run_interrupted'):
        if current: current['end_reason']='explicit_run_interruption'
        current=None;reason='explicit_run_interruption'
    age = None
    if latest and latest['timestamp']:
        try: age = (now-datetime.fromisoformat(latest['timestamp'])).total_seconds()
        except (TypeError,ValueError): pass
    stale = age is None or age<0 or age>stale_after_seconds or not latest['fresh_at_capture'] or not latest['capture_acquired']
    if stale: reason='stale_or_missing_timestamp'
    return dict(label=LABEL+' — based on displayed percentage observations and local capture timestamps',
        trusted=False,identity_verified=False,include_recovered=include_recovered,
        latest_percentage=latest,latest_movement=comparisons[-1] if comparisons else None,
        current_segment=current,current_pace=current.get('pace') if current and not stale else None,
        reason=reason,age_seconds=max(0,age) if age is not None else None,stale=stale,
        segments=segments,comparisons=comparisons,history_scope='bounded_selected_session_history',
        config=dict(min_readings=min_readings,min_span_seconds=min_span_seconds,max_gap_factor='1.5',max_gap_seconds=120))
