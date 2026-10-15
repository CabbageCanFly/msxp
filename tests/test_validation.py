from datetime import datetime, timedelta, timezone

import pytest

from exp_tracker.models import Reading
from exp_tracker.validation import Observation, validate_transition

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def observation(exp=1000, percent=10, *, level=25, character="alice", seconds=0):
    return Observation(character, START + timedelta(seconds=seconds), Reading(level, exp, percent))


def test_first_reading_starts_baseline():
    assert validate_transition(None, observation()).status == "baseline"


def test_ordinary_gain_and_no_mutation():
    previous = observation()
    transition = validate_transition(previous, observation(1200, 12, seconds=60))
    assert (transition.status, transition.gained_exp) == ("accepted", 200)
    assert previous.reading.current_exp == 1000


@pytest.mark.parametrize("current,expected", [
    (observation(seconds=60), "accepted"),
    (observation(seconds=0), "rejected"),
    (observation(seconds=-1), "rejected"),
    (observation(1300, 13, seconds=300), "baseline"),
    (observation(0, 0, level=26, seconds=60), "ambiguous"),
    (observation(900, 9, seconds=60), "ambiguous"),
    (observation(1200, 9, seconds=60), "ambiguous"),
    (observation(1000, 11, seconds=60), "rejected"),
    (observation(100, 1, level=23, seconds=60), "ambiguous"),
    (observation(100, 1, character="bob", seconds=60), "baseline"),
    (observation(-1, 1, seconds=60), "rejected"),
])
def test_discontinuities(current, expected):
    transition = validate_transition(observation(), current)
    assert transition.status == expected
    if expected != "accepted":
        assert transition.gained_exp is None


def test_rate_limit_rejects_implausible_gain():
    assert validate_transition(observation(), observation(999999, 50, seconds=60),
                               max_exp_per_second=100).reason == "implausible_gain"


def test_naive_timestamp_is_rejected():
    naive = Observation("alice", START.replace(tzinfo=None), Reading(25, 1000, 10))
    assert validate_transition(None, naive).status == "rejected"
    assert validate_transition(naive, observation(seconds=60)).status == "rejected"


def test_invalid_previous_state_is_rejected():
    assert validate_transition(observation(-1), observation(seconds=60)).status == "rejected"


@pytest.mark.parametrize("options", [{"max_gap_seconds": 0}, {"max_exp_per_second": -1}])
def test_invalid_policy(options):
    with pytest.raises(ValueError):
        validate_transition(None, observation(), **options)
