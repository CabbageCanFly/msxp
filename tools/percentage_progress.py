"""Experimental percentage endpoints only; independent of grammar proposals and Store."""

from datetime import datetime
from decimal import Decimal
from fractions import Fraction
import re

from analyze_temporal_ocr import complete_pair
from exp_tracker.shadow_types import parse_percentage_only
from exp_tracker.diagnostic_progress import rational, quantization_pace


def strict_point(row):
    """Read original shadow text, not partial diagnostics, supplied repairs or arithmetic levels."""
    neural = row.get('neural')
    text = neural.get('text') if isinstance(neural, dict) else None
    pair = complete_pair(text) if isinstance(text, str) and len(text) <= 160 else None
    only = parse_percentage_only(text) if pair is None else None
    if pair is None and only is None:
        return None, 'no_strict_observation'
    if row.get('candidate') != pair:
        return None, 'candidate_contradiction'
    if row.get('percentage_only_candidate') is not None and row['percentage_only_candidate'] != only:
        return None, 'candidate_contradiction'
    if row.get('current') is not True or row.get('status') not in (
            'diagnostic_pair', 'diagnostic_percentage_only', 'malformed_or_unavailable'):
        return None, 'not_fresh_success'
    localization = row.get('localization')
    if not isinstance(localization, dict) or localization.get('count') != 1:
        return None, 'hud_not_unique'
    evidence = row.get('level_evidence')
    if 'conflict' in (row.get('reasons') or []) or isinstance(evidence, dict) and evidence.get('relation') == 'conflict':
        return None, 'level_contradiction'
    source = row.get('source')
    source = source.get('channel') if isinstance(source, dict) else None
    if not isinstance(source, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,25}', source):
        return None, 'recorded_channel_missing'
    level = row.get('visual_level')
    if type(level) is not int or not 1 <= level <= 200 or row.get('visual_status') != 'available':
        return None, 'visual_level_unavailable'
    try:
        time = datetime.fromisoformat(row.get('received_at', ''))
        if time.utcoffset() is None:
            raise ValueError('No timezone')
    except (TypeError, ValueError, OverflowError):
        return None, 'timestamp_unavailable'
    if type(row.get('index')) is not int or row['index'] < 1:
        return None, 'attempt_index_unavailable'
    bp = int(Decimal(str(pair[1]))*100) if pair else only['percentage_bp']
    return dict(index=row['index'], channel=source.lower(), level=level, time=time,
                timestamp=time.isoformat(), bp=bp), None


def progress(rows, *, interval_seconds=15, min_readings=3, min_span_seconds=30):
    if (type(min_readings) is not int or min_readings < 3
            or not 0 < interval_seconds <= 300 or not 30 <= min_span_seconds):
        raise ValueError('Use >=3 readings, >=30 seconds and a bounded nominal interval')
    interval = Fraction(str(interval_seconds))
    span = Fraction(str(min_span_seconds))
    segments, comparisons = [], []
    previous = None
    current = None
    for row in rows:
        point, reason = strict_point(row)
        edge = dict(index=row.get('index'), change='missing_comparison', reason=reason)
        if point is None:
            previous = current = None
            comparisons.append(edge)
            continue
        elapsed = None
        if previous is not None:
            delta = point['time']-previous['time']
            elapsed = Fraction((delta.days*86400+delta.seconds)*1000000+delta.microseconds, 1000000)
            reason = ('source_changed' if point['channel'] != previous['channel'] else
                      'level_changed' if point['level'] != previous['level'] else
                      'nonincreasing_timestamp' if elapsed <= 0 else
                      'missing_attempt' if point['index'] != previous['index']+1 else
                      'sampling_gap' if elapsed > interval*Fraction(3, 2) else None)
            if reason is None:
                diff = point['bp']-previous['bp']
                edge.update(change='positive' if diff > 0 else 'negative' if diff < 0 else 'zero',
                            difference_bp=diff, difference_percentage_points=f'{Decimal(diff)/100:.2f}',
                            elapsed_seconds=rational(elapsed))
                if diff < 0:
                    reason = 'percentage_decrease_no_levelup_inferred'
        edge['reason'] = reason or ('baseline' if previous is None else 'contiguous_strict_endpoints')
        if reason == 'nonincreasing_timestamp':
            comparisons.append(edge)
            previous = current = None
            continue
        if reason is not None or current is None:
            current = dict(channel=point['channel'], level=point['level'], points=[])
            segments.append(current)
        current['points'].append(point)
        comparisons.append(edge)
        previous = point
    for segment in segments:
        points = segment.pop('points')
        first, last = points[0], points[-1]
        delta = last['time']-first['time']
        elapsed = Fraction((delta.days*86400+delta.seconds)*1000000+delta.microseconds, 1000000)
        gain = last['bp']-first['bp']
        segment.update(first_index=first['index'], last_index=last['index'], readings=len(points),
            start=first['timestamp'], end=last['timestamp'], span_seconds=rational(elapsed),
            difference_bp=gain, difference_percentage_points=f'{Decimal(gain)/100:.2f}',
            pace=None, reason='insufficient_readings' if len(points)<min_readings else 'insufficient_span')
        if len(points) >= min_readings and elapsed >= span:
            bounds = quantization_pace(first['bp'], last['bp'], elapsed)
            segment.update(reason='eligible_experimental_endpoints', pace=dict(
                label='EXPERIMENTAL / UNVERIFIED', units='percentage_points_per_hour',
                value=rational(Fraction(gain*36, 1)/elapsed),
                **bounds,
                bounds_kind='outer_quantization_bounds_not_statistical_intervals'))
    return dict(trusted=False, identity_verified=False, label='EXPERIMENTAL / UNVERIFIED',
                config=dict(interval_seconds=interval_seconds, min_readings=min_readings,
                            min_span_seconds=min_span_seconds, max_gap_factor='1.5'),
                segments=segments, comparisons=comparisons)
