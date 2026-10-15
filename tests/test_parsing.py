import math

import pytest

from exp_tracker.models import Reading, Region, reading_errors
from exp_tracker.parsing import parse_exp, parse_level


@pytest.mark.parametrize("text,expected", [
    ("LV. 42", 42), ("1", 1), ("LV:200", 200), (" 83 ", 83),
    ("S6", None), ("LV 3?", None), ("", None), ("42 12", None),
])
def test_level_parser(text, expected):
    assert parse_level(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("EXP 12,345 [23.45%]", (12345, 23.45)),
    ("12.345(23.45%)", (12345, 23.45)),  # tiny comma rendered as a dot
    ("12345 [23.45%]", (12345, 23.45)),
    ("0(0.00%)", (0, 0)), ("25 [0.00%]", (25, 0)),
    ("12,34[23.45%]", None), ("12,345[2345%]", None),
    ("12,345[23.4S%]", None), ("12,345 23.45%", None),
    ("12.34[23.45%]", None), ("12,345[23.45%] garbage", None),
    ("12345123.45%)", None), ("-25(1.00%)", None), ("", None),
])
def test_exp_parser(text, expected):
    assert parse_exp(text) == expected


@pytest.mark.parametrize("reading", [
    Reading(0, 10, 0), Reading(201, 10, 0), Reading(True, 10, 0),
    Reading(25, -1, 0), Reading(25, 1.5, 0), Reading(25, 2**63, 0),
    Reading(25, 10, 100), Reading(25, 10, -1), Reading(25, 10, math.nan),
    Reading(25, 10, math.inf), Reading(25, 10, True), Reading(25, 0, 1),
])
def test_invalid_readings(reading):
    assert reading_errors(reading)


def test_zero_percent_may_hide_small_positive_exp():
    assert reading_errors(Reading(25, 10, 0)) == []


@pytest.mark.parametrize("coords", [(-.1, 0, 1, 1), (0, 0, 0, 1), (0, 0, 1, 2), (0, math.nan, 1, 1)])
def test_invalid_region(coords):
    with pytest.raises(ValueError):
        Region(*coords)


def test_normalized_region_covers_same_fraction_at_new_size():
    region = Region(.25, .5, .75, 1)
    assert region.pixels(800, 600) == (200, 300, 600, 600)
    assert region.pixels(1600, 1200) == (400, 600, 1200, 1200)
