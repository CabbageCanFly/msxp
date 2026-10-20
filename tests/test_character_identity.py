"""Suggestion state never selects a character; all frames here are generated."""

from datetime import datetime, timedelta, timezone
import importlib
from io import BytesIO
from pathlib import Path
import sys

from PIL import Image, PngImagePlugin
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
from character_identity import IdentityCapture, IdentitySuggestions
from exp_tracker.video import Frame
from tests.test_capture_performance import candidate

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


def evidence(index, name='Alpha', status='candidate', digest=None):
    return dict(status=status, name=name, score=.99, pixel_sha256=digest or str(index),
                received_at=(NOW + timedelta(seconds=index)).isoformat(), box=[1, 2, 50, 15])


def test_stable_identity_and_repeated_switch_never_replace_initial_proposal():
    state = IdentitySuggestions('channel')
    assert state.observe(evidence(0))['proposed_name'] is None
    assert state.observe(evidence(1))['proposed_name'] == 'Alpha'
    assert state.observe(evidence(2, 'Beta'))['pending_switch'] is None
    result = state.observe(evidence(3, 'Beta'))
    assert result['proposed_name'] == 'Alpha'
    assert result['pending_switch']['name'] == 'Beta'
    assert len(result['pending_switch']['evidence']) == 2
    assert result['trusted'] is False


def test_missing_conflicting_and_old_frames_cannot_complete_a_switch():
    state = IdentitySuggestions('channel')
    for i in range(2): state.observe(evidence(i))
    state.observe(evidence(2, 'Beta'))
    state.observe(evidence(3, None, 'unreadable_or_conflicting'))
    assert state.observe(evidence(4, 'Beta'))['pending_switch'] is None
    state.observe(evidence(5, None, 'multiple_huds'))
    assert state.observe(evidence(6, 'Beta'))['pending_switch'] is None
    assert state.observe(evidence(7, 'Beta', digest='6'))['latest_status'] == 'duplicate_frame'
    assert state.observe(evidence(4, 'Beta'))['latest_status'] == 'out_of_order'
    assert state.observe(evidence(200, 'Beta'))['pending_switch'] is None
    assert state.observe(evidence(201, 'Beta'))['pending_switch']['name'] == 'Beta'
    state.observe(evidence(202, None, 'capture_failed'))
    assert state.observe(evidence(203))['pending_switch']['name'] == 'Beta'  # Latched for review.


def make_frame(index, color=None, metadata=False):
    image = Image.new('RGB', (1920, 1080), color or (index, 10, 20))
    data = BytesIO()
    info = PngImagePlugin.PngInfo()
    if metadata: info.add_text('private-test', str(index))
    image.save(data, format='PNG', pnginfo=info)
    return Frame(data.getvalue(), index, 100 + index, (NOW + timedelta(seconds=index)).isoformat())


def response(name='Alpha'):
    return dict(text=name, raw=dict(txts=[name], scores=[.99]), inference_seconds=.02)


def inspect(state, index, name='Alpha', *, numbers=None, layouts=None, image_frame=None, **kwargs):
    f = image_frame or make_frame(index)
    return state.inspect(numbers or dict(current=True, candidate=None, visual_level=None), f, f.image(),
        candidate() if layouts is None else layouts, lambda crop: response(name), {1: 10000, 2: 20000},
        max_age=15, clock=lambda: 101 + index, **kwargs)


def test_canonical_pixels_not_png_encoding_establish_distinctness():
    state = IdentityCapture('channel')
    inspect(state, 0, image_frame=make_frame(0, color='black'))
    value = inspect(state, 1, image_frame=make_frame(1, color='black', metadata=True))
    assert value['suggestion']['proposed_name'] is None
    assert value['suggestion']['latest_status'] == 'duplicate_frame'


def test_periodic_cadence_is_bypassed_by_existing_validator_events():
    state = IdentityCapture('channel', interval=300)
    normal = dict(current=True, candidate=[5000, 50.0], visual_level=1)
    inspect(state, 0, numbers=normal)
    inspect(state, 1, numbers=normal)  # Baseline confirmation bypasses cadence.
    assert inspect(state, 2, numbers=normal)['evidence']['status'] == 'not_due'
    drop = dict(current=True, candidate=[4000, 40.0], visual_level=1)
    value = inspect(state, 3, numbers=drop)
    assert value['evidence']['verification_reason'] == 'numeric_event'
    assert value['numeric_check']['reason'] == 'reset_loss_or_character_switch'
    assert value['suggestion']['pending_switch'] is None
    assert value['suspect_reading_hold_recommended'] and value['tracking_action'] == 'none'


def test_switch_at_identical_exp_still_recommends_holding_before_confirmation():
    state = IdentityCapture('channel')
    normal = dict(current=True, candidate=[5000, 50.0], visual_level=1)
    inspect(state, 0, numbers=normal)
    inspect(state, 1, numbers=normal)
    first = inspect(state, 2, 'Beta', numbers=normal)
    assert not first['numeric_check']['check_now']
    assert first['suggestion']['pending_switch'] is None
    assert first['suspect_reading_hold_recommended']
    second = inspect(state, 3, 'Beta', numbers=normal)
    assert second['suggestion']['proposed_name'] == 'Alpha'
    assert second['suggestion']['pending_switch']['name'] == 'Beta'


@pytest.mark.parametrize('pair,level,seconds,classification', [
    ([4000, 40.0], 1, 10, 'reset_loss_or_character_switch'),
    ([100, .5], 2, 10, 'possible_normal_level_up'),
    ([100, .5], 2, 300, 'possible_offstream_progression'),
    ([500, 40.0], 1, 10, 'possible_bad_ocr'),
])
def test_numeric_events_do_not_establish_identity(pair, level, seconds, classification):
    state = IdentityCapture('channel')
    state.numeric_check(dict(current=True, candidate=[9900, 99.0], visual_level=1), NOW.isoformat(),
                        {1: 10000, 2: 20000})
    result = state.numeric_check(dict(current=True, candidate=pair, visual_level=level),
                                (NOW + timedelta(seconds=seconds)).isoformat(), {1: 10000, 2: 20000})
    assert result['check_now'] and result['classification'] == classification
    assert state.suggestions.proposed is None and state.suggestions.pending_switch is None


def test_capture_failure_resets_confirmation_but_not_prior_suggestion():
    state = IdentityCapture('channel')
    inspect(state, 0)
    inspect(state, 1)
    inspect(state, 2, 'Beta')
    assert state.missing((NOW + timedelta(seconds=3)).isoformat())['proposed_name'] == 'Alpha'
    assert inspect(state, 4, 'Beta')['suggestion']['pending_switch'] is None
    # Incomplete numeric fields cannot suppress verification once identity is proposed.
    assert state.numeric_check(dict(current=True), NOW.isoformat(), {})['check_now']


def test_level_decrease_and_large_jump_use_shared_transition_reason():
    state = IdentityCapture('channel')
    state.numeric_check(dict(current=True, candidate=[10000, 50.0], visual_level=2), NOW.isoformat(),
                        {1: 10000, 2: 20000, 10: 30000})
    for level, exp, classification in [(1, 5000, 'level_decrease'), (10, 15000, 'level_change_requires_confirmation')]:
        value = state.numeric_check(dict(current=True, candidate=[exp, 50.0], visual_level=level),
                                    (NOW + timedelta(seconds=10)).isoformat(), {1: 10000, 2: 20000, 10: 30000})
        assert value['reason'] == 'level_change_requires_confirmation'
        assert value['classification'] == classification


def test_channel_state_is_isolated_and_conflicting_raw_lines_do_not_vote():
    a, b = IdentityCapture('a'), IdentityCapture('b')
    for i in range(2):
        inspect(a, i, 'Alpha')
        inspect(b, i, 'Beta')
    assert a.suggestions.proposed == 'Alpha' and b.suggestions.proposed == 'Beta'
    f = make_frame(3)
    value = a.inspect(dict(current=True), f, f.image(), candidate(),
                      lambda crop: dict(raw=dict(txts=['Alpha', 'Beta'], scores=[.99, .99])), {},
                      max_age=15, clock=lambda: 104)
    assert value['evidence']['status'] == 'unreadable_or_conflicting'
    assert value['suggestion']['confirming_frames'] == 0


def test_analyze_reuses_layout_preserves_exp_and_never_localizes_again():
    shadow = importlib.import_module('shadow_capture')
    f = make_frame(0)
    calls = []
    def locator(image):
        calls.append('locate')
        return candidate()
    kwargs = dict(locator=locator, read_level=lambda crop: (1, []), clock=lambda: 101)
    ordinary = shadow.analyze(f, {1: 10000}, lambda crop: response('5000[50.00%]'), **kwargs)
    state = IdentityCapture('channel')
    named = shadow.analyze(f, {1: 10000}, lambda crop: response('5000[50.00%]'),
                           identity=state, read_name=lambda crop: response(), **kwargs)
    assert calls == ['locate', 'locate']
    assert named['character_name']['evidence']['box'] == [640, 1011, 773, 1029]
    named.pop('character_name'); named['timings'].pop('character_name_seconds')
    assert named == ordinary
    for count in (0, 2):
        value = shadow.analyze(f, {1: 10000}, lambda crop: pytest.fail('EXP on ambiguous HUD'),
            locator=lambda image: candidate() * count, clock=lambda: 101,
            identity=state, read_name=lambda crop: pytest.fail('Name on ambiguous HUD'))
        assert value['character_name']['evidence']['status'] in ('multiple_huds', 'ineligible_frame')


def test_stale_or_failed_name_preserves_exp_result():
    shadow = importlib.import_module('shadow_capture')
    f = make_frame(0)
    now = [101]
    def slow(crop):
        now[0] = 130
        return response()
    result = shadow.analyze(f, {1: 10000}, lambda crop: response('5000[50.00%]'),
        locator=lambda image: candidate(), read_level=lambda crop: (1, []), clock=lambda: now[0],
        identity=IdentityCapture('channel'), read_name=slow)
    assert result['current'] and result['candidate'] == [5000, 50.0]
    assert result['character_name']['evidence']['status'] == 'stale_local_frame'
    assert result['character_name']['suggestion']['proposed_name'] is None
    def failed(crop):
        raise RuntimeError('OCR unavailable')
    result = shadow.analyze(f, {1: 10000}, lambda crop: response('5000[50.00%]'),
        locator=lambda image: candidate(), read_level=lambda crop: (1, []), clock=lambda: 101,
        identity=IdentityCapture('channel'), read_name=failed)
    assert result['current'] and result['candidate'] == [5000, 50.0]
    assert result['character_name']['evidence']['status'] == 'failed'


def test_name_mode_is_local_and_no_db_and_defaults_remain_opt_in(tmp_path):
    shadow = importlib.import_module('shadow_capture')
    ordinary = shadow.parser().parse_args(['--file', 'missing.mp4', '--output', str(tmp_path / 'x')])
    assert not ordinary.character_names and ordinary.name_interval == 0 and not ordinary.resident_neural
    for source in (['--channel', 'example', '--authorized'], ['--file', 'missing.mp4', '--db', 'unused.db']):
        args = shadow.parser().parse_args(source + ['--character-names', '--output', str(tmp_path / 'x')])
        with pytest.raises(ValueError, match='local --file without --db'):
            shadow.prepare(args)


@pytest.mark.parametrize('value', ['nan', '-1', '3601'])
def test_name_interval_is_bounded_before_capture(tmp_path, value):
    shadow = importlib.import_module('shadow_capture')
    args = shadow.parser().parse_args(['--file', 'missing.mp4', '--character-names',
        '--name-interval', value, '--output', str(tmp_path / 'unused.jsonl')])
    with pytest.raises(ValueError, match='name_interval must be finite'):
        shadow.prepare(args)
