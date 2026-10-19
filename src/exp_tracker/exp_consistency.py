"""Exact conditional EXP/display diagnostics; not a trusted OCR validator."""

from bisect import bisect_left, bisect_right
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import re


MODES = ('nearest_half_up', 'truncate')


def displayed_bp(percentage):
    """Displayed basis points of an exact 0-100 percentage, else None; never rounded."""
    try:
        percent = Decimal(str(percentage))
        if not percent.is_finite() or not 0 <= percent <= 100:
            return None
        bp = percent * 100
        if bp != bp.to_integral_value():
            return None  # No decimal reconstruction or extra rounding of OCR output.
        return int(bp)
    except (InvalidOperation, ValueError):
        return None


def assess(level, exp, percentage, requirements, mode):
    if mode not in MODES:
        raise ValueError('Unknown rounding hypothesis')
    result = dict(status='unavailable_numeric', trusted=False, authoritative=False)
    if type(exp) is not int or exp < 0 or percentage is None or isinstance(percentage, bool):
        return result
    bp = displayed_bp(percentage)
    if bp is None:
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



def infer_levels(exp, percentage, requirements, mode='nearest_half_up'):
    """Enumerate every compatible supplied level, without an OCR level or tolerance."""
    if mode not in MODES:
        raise ValueError('Unknown rounding hypothesis')
    return infer_indexed(exp, percentage, requirement_index(requirements), mode)


def requirement_index(requirements):
    """Validated, immutable index of one table, for callers that reuse a fixed table."""
    if not requirements or any(type(level) is not int or level<1 or type(total) is not int or total<=0
                               for level,total in requirements.items()):
        raise ValueError('A nonempty positive integer level/requirement table is required')
    return _by_requirement(tuple(sorted(requirements.items())))


def infer_indexed(exp, percentage, index, mode):
    """infer_levels() on a requirement_index(); identical output by construction."""
    if mode not in MODES:
        raise ValueError('Unknown rounding hypothesis')
    result=dict(levels=[],unique_level=None,rounding=mode,trusted=False,authoritative=False,
                exhaustive_only_within_supplied_table=True)
    if exp is None or percentage is None:
        return {**result,'status':'unavailable'}
    if (type(exp) is not int or exp<0 or exp>2**63-1 or isinstance(percentage,bool)
        or not isinstance(percentage,(int,float,str,Decimal))
        or isinstance(percentage,str) and re.fullmatch(r'[0-9]{1,3}\.[0-9]{2}',percentage) is None):
        return {**result,'status':'invalid_input'}
    bp=displayed_bp(percentage)
    if bp is None:
        return {**result,'status':'invalid_input'}
    # assess() is consistent exactly when exp < T and its integer rounding equals bp.
    # Solved for the requirement T with n = 10000*exp:
    #   truncate:        bp*T <= n < (bp+1)*T
    #   nearest_half_up: (2bp-1)*T <= 2n < (2bp+1)*T
    n=10000*exp
    if mode=='truncate':lower,upper=n//(bp+1)+1,n//bp if bp else None
    else:lower,upper=2*n//(2*bp+1)+1,2*n//(2*bp-1) if bp else None
    totals,ordered=index
    # Requirements need not increase with level: select by value, then report by level.
    selected=ordered[bisect_left(totals,max(lower,exp+1)):len(totals) if upper is None else bisect_right(totals,upper)]
    levels=sorted(selected)
    return {**result,'status':'unique' if len(levels)==1 else 'ambiguous' if levels else 'incompatible',
            'levels':levels,'unique_level':levels[0] if len(levels)==1 else None}


@lru_cache(maxsize=16)  # One entry per distinct requirement table.
def _by_requirement(items):
    pairs=sorted((total,level) for level,total in items)
    return tuple(total for total,_ in pairs),tuple(level for _,level in pairs)
