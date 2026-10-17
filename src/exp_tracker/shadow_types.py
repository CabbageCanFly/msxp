"""Experimental diagnostic types only; no production Reading or trust semantics."""

from decimal import Decimal, InvalidOperation
import re
from typing import Literal, TypedDict


class PercentageOnly(TypedDict):
    kind: Literal['percentage_only']
    percentage: str
    percentage_bp: int
    trusted: Literal[False]


def parse_percentage_only(text: str | None) -> PercentageOnly | None:
    """A whole square-bracketed field, ASCII digits and an explicit two-decimal value."""
    if not isinstance(text, str) or len(text) > 160:
        return None
    match = re.fullmatch(r'\[([0-9]{1,2}|100)\.([0-9]{2})%\]', text.strip())
    if not match:
        return None
    bp = int(match[1])*100 + int(match[2])
    if bp > 10000:
        return None
    return dict(kind='percentage_only', percentage=f'{bp//100}.{bp%100:02d}',
                percentage_bp=bp, trusted=False)


def partial_percentage(value):
    """Format existing parser evidence; this function never extracts or fills digits."""
    if type(value) not in (int, float):
        return None
    try:
        bp = Decimal(str(value))*100
        if not bp.is_finite() or not 0 <= bp <= 10000 or bp != bp.to_integral_value():
            return None
        return dict(kind='partial_percentage', percentage=f'{value:.2f}',
                    trusted=False, complete_observation=False)
    except InvalidOperation:
        return None
