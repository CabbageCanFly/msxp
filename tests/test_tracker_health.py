"""The health check counts missed capture slots from gaps between readings and says why readings failed."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
from tracker_health import behind, missed, outcome


def test_missed_slots_follow_gap_length():
    assert missed([0, 20, 40, 60], 20) == 0
    assert missed([0, 23, 40], 20) == 0  # A few seconds late is not a missed reading.
    assert missed([0, 40, 60], 20) == 1
    assert missed([0, 100], 20) == 4
    assert missed([], 20) == missed([5], 20) == 0


def test_behind_counts_scheduler_skips_and_survives_restart_resets():
    assert behind([0, 0, 1, 3, 3]) == 3
    assert behind([5, 6, 0, 2]) == 3  # Restart reset the counter to 0: no negative contribution.
    assert behind([]) == behind([4]) == 0


def test_outcome_separates_offline_no_frame_no_hud_and_reads():
    assert outcome('capture_failed', ['offline_or_unavailable']) == 'offline'
    assert outcome('capture_failed', ['frame_timeout']) == 'no frame'
    assert outcome('unavailable', ['missing_hud']) == outcome('unavailable', ['multiple_huds']) == 'no HUD'
    assert outcome('malformed_or_unavailable', ['strict_pair_unavailable']) == 'unclear'
    assert outcome('diagnostic_pair', ['visual_level_unavailable']) == 'read'
