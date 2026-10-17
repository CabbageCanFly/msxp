"""Exact conditional EXP/display diagnostics; not a trusted OCR validator."""

from decimal import Decimal, InvalidOperation


MODES = ('nearest_half_up', 'truncate')


def assess(level, exp, percentage, requirements, mode):
    if mode not in MODES:
        raise ValueError('Unknown rounding hypothesis')
    result = dict(status='unavailable_numeric', trusted=False, authoritative=False)
    if type(exp) is not int or exp < 0 or percentage is None or isinstance(percentage, bool):
        return result
    try:
        percent = Decimal(str(percentage))
        if not percent.is_finite() or not 0 <= percent <= 100:
            return result
        bp = percent * 100
        if bp != bp.to_integral_value():
            return result  # No decimal reconstruction or extra rounding of OCR output.
        bp = int(bp)
    except (InvalidOperation, ValueError):
        return result
    if level is None:
        return {**result, 'status': 'unavailable_level'}
    if type(level) is not int or level < 1:
        return {**result, 'status': 'invalid_level'}
    total = requirements.get(level)
    if total is None:
        return {**result, 'status': 'unavailable_requirement'}
    if type(total) is not int or total <= 0:
        raise ValueError('EXP requirement must be a positive integer')
    numerator = 10000 * exp
    if mode == 'truncate':
        actual = numerator // total
        lower, upper, divisor = bp * total, (bp + 1) * total, 10000
    else:
        actual = (2 * numerator + total) // (2 * total)
        lower, upper, divisor = (2 * bp - 1) * total, (2 * bp + 1) * total, 20000
    minimum = max(0, -(-lower // divisor))
    maximum = min(total - 1, -(-upper // divisor) - 1)
    count = max(0, maximum - minimum + 1)
    consistent = exp < total and actual == bp
    return {**result, 'status': 'consistent' if consistent else 'inconsistent',
            'requirement': total, 'displayed_bp': bp, 'calculated_bp': actual,
            'exact_halfway': 2 * (numerator % total) == total,
            'exp_bin': dict(min=minimum, max=maximum, count=count),
            'reason': ('exp_outside_level_or_transition' if exp >= total else
                       None if consistent else 'percentage_disagrees')}

