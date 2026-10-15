"""Conservative observation transitions; this is not a full session tracker."""

from dataclasses import dataclass
from datetime import datetime
import math

from .models import Reading, reading_errors


@dataclass(frozen=True)
class Observation:
    character_id: str
    captured_at: datetime
    reading: Reading


@dataclass(frozen=True)
class Transition:
    status: str
    reason: str
    gained_exp: int | None = None


def validate_transition(previous: Observation | None, current: Observation,
                        *, max_gap_seconds: float = 120,
                        max_exp_per_second: float | None = None) -> Transition:
    """Never attribute cross-character/reset/gap differences as ordinary gains.

    A level increase is ambiguous without identity confirmation AND a verified EXP
    table. A rate bound is optional and must be chosen for the selected game rules.
    """
    if not math.isfinite(max_gap_seconds) or max_gap_seconds <= 0:
        raise ValueError("max_gap_seconds must be positive and finite")
    if max_exp_per_second is not None and (not math.isfinite(max_exp_per_second) or max_exp_per_second <= 0):
        raise ValueError("max_exp_per_second must be positive and finite")
    errors = reading_errors(current.reading)
    if errors:
        return Transition("rejected", ",".join(errors))
    if current.captured_at.tzinfo is None or current.captured_at.utcoffset() is None:
        return Transition("rejected", "timestamp_must_be_timezone_aware")
    if previous is None:
        return Transition("baseline", "first_observation")
    if previous.captured_at.tzinfo is None or previous.captured_at.utcoffset() is None:
        return Transition("rejected", "previous_timestamp_must_be_timezone_aware")
    if reading_errors(previous.reading):
        return Transition("rejected", "invalid_previous_observation")
    seconds = (current.captured_at - previous.captured_at).total_seconds()
    if seconds <= 0:
        return Transition("rejected", "non_increasing_timestamp")
    if current.character_id != previous.character_id:
        return Transition("baseline", "explicit_character_switch")
    a, b = previous.reading, current.reading
    if a.level != b.level:
        return Transition("ambiguous", "level_change_requires_confirmation")
    delta = b.current_exp - a.current_exp
    if delta < 0 or b.percentage < a.percentage:
        return Transition("ambiguous", "reset_loss_or_character_switch")
    if delta == 0 and b.percentage != a.percentage:
        return Transition("rejected", "unchanged_exp_with_changed_percentage")
    if max_exp_per_second is not None and delta > max_exp_per_second * seconds:
        return Transition("rejected", "implausible_gain")
    if seconds > max_gap_seconds:
        return Transition("baseline", "gap_requires_new_baseline")
    return Transition("accepted", "unchanged" if delta == 0 else "same_level_gain", delta)

