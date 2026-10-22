"""The health check counts missed capture slots from gaps between readings."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
from tracker_health import missed


def test_missed_slots_follow_gap_length():
    assert missed([0, 20, 40, 60], 20) == 0
    assert missed([0, 23, 40], 20) == 0  # A few seconds late is not a missed reading.
    assert missed([0, 40, 60], 20) == 1
    assert missed([0, 100], 20) == 4
    assert missed([], 20) == missed([5], 20) == 0
