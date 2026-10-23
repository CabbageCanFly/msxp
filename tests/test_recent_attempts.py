"""The recent-captures view shows whose each capture was and what a held capture read."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
from recent_attempts import lines
from tests.test_autonomous_characters import auto, sequence  # noqa: F401


def test_switch_shows_saved_character_and_the_name_a_held_capture_read(auto):
    sequence(auto, ['Alpha', 'Alpha', 'Beta', 'Beta'])
    newest_first = lines(auto[0], 'alpha', 10)
    assert len(newest_first) == 4
    # The first Beta capture is held under Alpha; its own reading still shows.
    assert 'saved as: Alpha read: Beta unavailable hold: identity floor: None tesseract: 30' in newest_first[1]
    assert 'saved as: Beta read: Beta diagnostic_pair hold: None floor: 30 tesseract: 30' in newest_first[0]
    assert 'saved as: Alpha read: Alpha diagnostic_pair hold: None floor: 30' in newest_first[2]
    assert 'saved as: Alpha read: Alpha unavailable hold: level_confirmation_pending floor: None' in newest_first[3]
    assert lines(auto[0], 'nobody') == []
