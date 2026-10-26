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


def test_capitalization_changes_are_one_identity_without_mismatch_holds():
    state = IdentityCapture('channel', confirmed='Alpha')
    for index, name in enumerate(['alpha', 'ALPHA', 'aLpHa']):
        result = inspect(state, index, name)
        assert result['identity_conflict'] is None
        assert not result['reading_hold_recommended']
        assert result['suggestion']['pending_switch'] is None
        assert result['suggestion']['confirmed_name'] == 'Alpha'


def test_discovery_and_real_switch_confirm_across_capitalization_changes():
    state = IdentitySuggestions('channel')
    state.observe(evidence(0, 'Alpha'))
    assert state.observe(evidence(1, 'alpha'))['proposed_name'] == 'alpha'
    state.observe(evidence(2, 'Beta'))
    pending = state.observe(evidence(3, 'BETA'))['pending_switch']
    assert pending['name'] == 'BETA' and len(pending['evidence']) == 2


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
    assert state.observe(evidence(203))['pending_switch']['name'] == 'Beta'  # One reference frame cannot clear it.


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


def test_bottom_edge_name_crop_still_requires_two_distinct_frames():
    state = IdentityCapture('channel')
    layouts = candidate(x=780, y=1054.5, step=100)
    first = inspect(state, 0, layouts=layouts)
    assert first['evidence']['status'] == 'candidate'
    assert first['evidence']['box'] == [652, 1064, 774, 1080]
    assert first['suggestion']['proposed_name'] is None
    duplicate = inspect(state, 1, layouts=layouts, image_frame=make_frame(1, color=(0, 10, 20)))
    assert duplicate['suggestion']['latest_status'] == 'duplicate_frame'
    assert duplicate['suggestion']['proposed_name'] is None
    second = inspect(state, 2, layouts=layouts)
    assert second['suggestion']['proposed_name'] == 'Alpha'
    assert second['suggestion']['confirming_frames'] == 2
    assert second['tracking_action'] == 'none'


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
    # Verification ran on the same frame and read the reference name: no ownership hold.
    assert value['verification_requested'] and not value['reading_hold_recommended']
    assert value['tracking_action'] == 'none'


@pytest.mark.parametrize('pair', [[5000, 50.0], [5100, 51.0]])
def test_switch_at_similar_exp_still_recommends_holding_before_confirmation(pair):
    state = IdentityCapture('channel')
    normal = dict(current=True, candidate=[5000, 50.0], visual_level=1)
    inspect(state, 0, numbers=normal)
    inspect(state, 1, numbers=normal)
    first = inspect(state, 2, 'Beta', numbers=dict(normal, candidate=pair))
    assert not first['numeric_check']['check_now']
    assert first['suggestion']['pending_switch'] is None
    assert first['reading_hold_recommended'] and first['hold_reasons'] == ['name_mismatch']
    second = inspect(state, 3, 'Beta', numbers=dict(normal, candidate=pair))
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


def test_standalone_name_mode_has_no_db_and_defaults_remain_opt_in(tmp_path):
    shadow = importlib.import_module('shadow_capture')
    ordinary = shadow.parser().parse_args(['--file', 'missing.mp4', '--output', str(tmp_path / 'x')])
    assert not ordinary.character_names and ordinary.name_interval == 0 and not ordinary.resident_neural
    for source in (['--channel', 'example', '--authorized','--db','unused.db'], ['--file', 'missing.mp4', '--db', 'unused.db']):
        args = shadow.parser().parse_args(source + ['--character-names', '--output', str(tmp_path / 'x')])
        with pytest.raises(ValueError, match='requires no --db'):
            shadow.prepare(args)


@pytest.mark.parametrize('value', ['nan', '-1', '3601'])
def test_name_interval_is_bounded_before_capture(tmp_path, value):
    shadow = importlib.import_module('shadow_capture')
    args = shadow.parser().parse_args(['--file', 'missing.mp4', '--character-names',
        '--name-interval', value, '--output', str(tmp_path / 'unused.jsonl')])
    with pytest.raises(ValueError, match='name_interval must be finite'):
        shadow.prepare(args)


def run(state, sequence, start=0, numbers=None):
    return [inspect(state, start + i, name, numbers=numbers) for i, name in enumerate(sequence)]


def holds(values):
    return [v['reading_hold_recommended'] for v in values]


def numbers(exp, percentage, level):
    return dict(current=True, candidate=[exp, percentage], visual_level=level)


def test_aabb_creates_pending_switch_without_selecting_it():
    values = run(IdentityCapture('channel'), ['Alpha', 'Alpha', 'Beta', 'Beta'])
    last = values[-1]
    assert holds(values) == [False, False, True, True]
    assert last['suggestion']['pending_switch']['state'] == 'pending'
    assert last['suggestion']['proposed_name'] == 'Alpha' and last['suggestion']['confirmed_name'] is None
    assert last['identity_conflict'] == dict(reference_name='Alpha', reference_source='ocr_proposed',
                                             observed_name='Beta', pending_name='Beta')
    assert last['hold_reasons'] == ['name_mismatch', 'pending_switch']


def test_aaba_false_alarm_recovers_without_suggestion():
    values = run(IdentityCapture('channel'), ['Alpha', 'Alpha', 'Beta', 'Alpha'])
    assert holds(values) == [False, False, True, False]
    assert values[2]['identity_conflict']['observed_name'] == 'Beta'
    last = values[-1]
    assert last['identity_conflict'] is None and last['suggestion']['pending_switch'] is None
    assert last['suggestion']['history'] == []


def test_abbaa_return_to_operator_confirmed_original_supersedes_pending():
    values = run(IdentityCapture('channel', confirmed='Alpha'), ['Alpha', 'Beta', 'Beta', 'Alpha', 'Alpha'])
    assert holds(values) == [False, True, True, True, False]  # One returning frame is not enough.
    last = values[-1]['suggestion']
    assert last['pending_switch'] is None and last['reference_source'] == 'operator_confirmed'
    assert [(h['name'], h['state'], h['resolved_by']) for h in last['history']] == [('Beta', 'superseded', 'Alpha')]
    assert len(last['history'][0]['evidence']) == 2  # Diagnostic evidence is preserved.


def test_abbaa_without_operator_identity_cannot_know_the_original():
    last = run(IdentityCapture('channel'), ['Alpha', 'Beta', 'Beta', 'Alpha', 'Alpha'])[-1]
    assert last['suggestion']['proposed_name'] == 'Beta'  # One Alpha frame was never evidence.
    assert last['suggestion']['pending_switch']['name'] == 'Alpha'


def test_third_name_supersedes_pending_switch():
    last = run(IdentityCapture('channel'), ['Alpha', 'Alpha', 'Beta', 'Beta', 'Gamma', 'Gamma'])[-1]['suggestion']
    assert last['pending_switch']['name'] == 'Gamma'
    assert [(h['name'], h['state'], h['resolved_by']) for h in last['history']] == [('Beta', 'superseded', 'Gamma')]


@pytest.mark.parametrize('name', ['Alpha', None])
def test_normal_level_up_requests_verification_but_never_an_identity_hold(name):
    state = IdentityCapture('channel')
    run(state, ['Alpha', 'Alpha'], numbers=numbers(9900, 99.0, 1))
    up = inspect(state, 2, name, numbers=numbers(100, .5, 2))
    assert up['numeric_check']['classification'] == 'possible_normal_level_up'
    assert up['verification_requested'] and not up['reading_hold_recommended']
    after = inspect(state, 3, name, numbers=numbers(300, 1.5, 2))
    assert after['numeric_check']['reason'] == 'same_level_gain'  # New level became the anchor.
    assert not after['verification_requested'] and not after['reading_hold_recommended']


def test_level_decrease_holds_until_the_reference_name_is_read():
    state = IdentityCapture('channel')
    run(state, ['Alpha', 'Alpha'], numbers=numbers(10000, 50.0, 2))
    for index in (2, 3):  # Unverified anomaly keeps requesting checks and holding.
        value = inspect(state, index, None, numbers=numbers(5000, 50.0, 1))
        assert value['numeric_check']['classification'] == 'level_decrease'
        assert value['verification_requested'] and value['hold_reasons'] == ['unverified_numeric_anomaly']
    value = inspect(state, 4, 'Beta', numbers=numbers(5000, 50.0, 1))
    assert value['hold_reasons'] == ['name_mismatch', 'unverified_numeric_anomaly']
    value = inspect(state, 5, 'Alpha', numbers=numbers(5000, 50.0, 1))
    assert value['verification_requested'] and not value['reading_hold_recommended']
    assert value['identity_conflict'] is None


@pytest.mark.parametrize('pair,level,seconds,hold', [
    ([4000, 40.0], 1, 2, True),      # Same-level loss could be another character.
    ([500, 40.0], 1, 2, False),      # Arithmetic contradiction is EXP validity, not ownership.
    ([100, .5], 2, 300, True),       # Progression across a gap could be another character.
])
def test_other_numeric_anomalies_separate_ownership_from_exp_validity(pair, level, seconds, hold):
    state = IdentityCapture('channel')
    run(state, ['Alpha', 'Alpha'], numbers=numbers(5000, 50.0, 1))
    value = inspect(state, 1 + seconds, None, numbers=numbers(pair[0], pair[1], level))
    assert value['verification_requested'] and value['reading_hold_recommended'] is hold


def test_missing_stale_and_duplicate_evidence_never_clear_a_pending_hold():
    state = IdentityCapture('channel')
    run(state, ['Alpha', 'Alpha', 'Beta', 'Beta'])
    for index in (10, 700, 2000):
        assert inspect(state, index, None)['hold_reasons'] == ['pending_switch']
    assert state.missing((NOW + timedelta(seconds=2001)).isoformat())['pending_switch']['state'] == 'pending'
    assert inspect(state, 2002, layouts=candidate() * 2)['hold_reasons'] == ['pending_switch']
    f = make_frame(2003)
    stale = state.inspect(dict(current=True), f, f.image(), candidate(), lambda crop: response(), {},
                          max_age=15, clock=lambda: 2200)
    assert stale['evidence']['status'] == 'stale_local_frame' and stale['reading_hold_recommended']
    inspect(state, 2004, 'Beta', image_frame=make_frame(2004, color='black'))
    duplicate = inspect(state, 2005, 'Beta', image_frame=make_frame(2005, color='black'))
    assert duplicate['suggestion']['latest_status'] == 'duplicate_frame'
    assert duplicate['suggestion']['pending_switch']['evidence'][0]['received_at'] == make_frame(2).received_at
    assert duplicate['hold_reasons'] == ['name_mismatch', 'pending_switch']


def test_pending_switch_expires_only_after_time_and_a_reference_sighting():
    state = IdentitySuggestions('channel')
    for i, name in enumerate(['Alpha', 'Alpha', 'Beta', 'Beta']):
        state.observe(evidence(i, name))
    state.observe(evidence(100))  # Single Alpha sighting, not a two-frame return.
    assert state.observe(evidence(602, None, 'unreadable_or_conflicting'))['pending_switch']['state'] == 'pending'
    value = state.observe(evidence(603, None, 'unreadable_or_conflicting'))
    assert value['pending_switch'] is None
    assert [(h['state'], h['resolved_by']) for h in value['history']] == [('expired', 'reference_seen_without_pending_name')]
    # A later Beta switch stays pending however long names are unavailable, until Alpha is seen again.
    for i in (700, 701, 1400):
        state.observe(evidence(i, 'Beta'))
    assert state.observe(evidence(5000, None, 'unreadable_or_conflicting'))['pending_switch']['state'] == 'pending'


def test_operator_dismissal_requires_new_evidence_and_keeps_mismatch_holds():
    state = IdentityCapture('channel')
    run(state, ['Alpha', 'Alpha', 'Beta', 'Beta'])
    state.suggestions.dismiss((NOW + timedelta(seconds=4)).isoformat())
    value = inspect(state, 5, 'Beta')
    assert value['suggestion']['pending_switch'] is None
    assert value['suggestion']['history'][0]['state'] == 'dismissed'
    assert value['hold_reasons'] == ['name_mismatch']  # Dismissal never authorizes Beta readings for Alpha.
    assert inspect(state, 6, 'Beta')['suggestion']['pending_switch']['created_at'] == make_frame(6).received_at


def test_ocr_agreement_never_confirms_and_operator_selection_starts_new_baseline():
    state = IdentityCapture('channel', confirmed='Alpha')
    run(state, ['Alpha', 'Beta', 'Beta', 'Beta'], numbers=numbers(5000, 50.0, 1))
    assert state.suggestions.confirmed == 'Alpha'
    state.select('Beta', (NOW + timedelta(seconds=4)).isoformat())
    value = inspect(state, 5, 'Beta', numbers=numbers(9000, 90.0, 1))
    assert value['suggestion']['history'][0]['state'] == 'confirmed'
    assert value['suggestion']['confirmed_name'] == 'Beta' and value['suggestion']['proposed_name'] is None
    assert value['numeric_check']['reason'] == 'first_observation'  # Never compared with Alpha's EXP.
    assert not value['reading_hold_recommended']


def test_multiple_channels_keep_independent_lifecycles():
    a, b = IdentityCapture('a'), IdentityCapture('b', confirmed='Beta')
    for i, (x, y) in enumerate([('Alpha', 'Beta'), ('Alpha', 'Beta'), ('Beta', 'Beta'), ('Beta', 'Alpha')]):
        va, vb = inspect(a, i, x), inspect(b, i, y)
    assert va['suggestion']['pending_switch']['name'] == 'Beta' and vb['suggestion']['pending_switch'] is None
    assert va['hold_reasons'] == ['name_mismatch', 'pending_switch'] and vb['hold_reasons'] == ['name_mismatch']
    a.suggestions.dismiss(NOW.isoformat())
    assert not b.suggestions.history and a.suggestions.history[0]['state'] == 'dismissed'


def test_live_identity_cleans_job_remnants_but_keeps_name_pixels_and_source_box(monkeypatch):
    identity=importlib.import_module('character_identity')
    monkeypatch.setattr(identity,'name_region',lambda *_:dict(box=[0,0,80,25]))
    state=IdentityCapture('channel',confirmed='Alpha');state.job=state.job_seen='Cleric'
    image=Image.new('RGB',(1920,1080),(40,50,60));image.putpixel((50,0),(230,230,230));image.putpixel((20,5),(210,210,210))
    data=BytesIO();image.save(data,'PNG');frame=Frame(data.getvalue(),0,100,NOW.isoformat());calls=[]
    def read(crop):
        calls.append(crop.size)
        assert crop.getpixel((50,0))==(40,50,60) and crop.getpixel((20,5))==(210,210,210)
        return response('Alpha')
    value=state.inspect(dict(current=True,candidate=None,visual_level=None),frame,image,candidate(),read,{},max_age=15,clock=lambda:101)
    assert calls==[(80,25)] and value['evidence']['box']==[0,0,80,25]
    assert value['evidence']['name']=='Alpha' and not value['reading_hold_recommended']
    assert image.getpixel((50,0))==(230,230,230)


def test_known_name_second_look_keeps_original_pixels_after_cleaned_first_read(monkeypatch):
    identity=importlib.import_module('character_identity')
    monkeypatch.setattr(identity,'name_region',lambda *_:dict(box=[0,0,80,25]))
    state=IdentityCapture('channel',confirmed='Alpha');state.job=state.job_seen='Cleric'
    image=Image.new('RGB',(1920,1080),(40,50,60));image.putpixel((50,0),(230,230,230))
    data=BytesIO();image.save(data,'PNG');frame=Frame(data.getvalue(),0,100,NOW.isoformat());calls=[]
    def read(crop):
        calls.append(crop.size)
        if len(calls)==1:
            assert crop.getpixel((50,0))==(40,50,60)
            return response('Alpna')
        assert crop.getpixel((56,6))==(230,230,230)
        return response('Alpha')
    value=state.inspect(dict(current=True,candidate=None,visual_level=None),frame,image,candidate(),read,{},max_age=15,clock=lambda:101)
    assert len(calls)==2 and value['evidence']['first_read']['text']=='Alpna'
    assert value['evidence']['name']=='Alpha' and not value['reading_hold_recommended']


@pytest.mark.parametrize('second,used', [('Kayvenmoor', True), ('Kaymenmoor', False)])
def test_second_look_may_only_confirm_the_current_character(second, used):
    """Live Streamer_J: touching "yv" read as "w"; a padded second look reads the confirmed name."""
    state = IdentityCapture('channel', confirmed='Kayvenmoor'); sizes = []
    state.job = state.job_seen = 'Cleric'  # Known job, level unknown: no job read on this frame.
    def read(crop):
        sizes.append(crop.size)
        return response('Kaywenmoor' if len(sizes) == 1 else second)
    f = make_frame(0)
    value = state.inspect(dict(current=True, candidate=None, visual_level=None), f, f.image(), candidate(), read,
                          {1: 10000, 2: 20000}, max_age=15, clock=lambda: 101)
    assert len(sizes) == 2 and sizes[1] == (sizes[0][0] + 9, sizes[0][1] + 12)
    assert value['evidence']['name'] == ('Kayvenmoor' if used else 'Kaywenmoor')
    assert value['evidence']['raw']['raw']['txts'] == [value['evidence']['name']]
    assert ('first_read' in value['evidence']) is used and value['hold_reasons'] == ([] if used else ['name_mismatch'])


def test_matching_reads_and_unconfirmed_channels_take_no_second_look():
    for state, name in ((IdentityCapture('channel', confirmed='Alpha'), 'Alpha'), (IdentityCapture('channel'), 'Beta')):
        calls = []; state.job = state.job_seen = 'Cleric'  # No job read either.
        f = make_frame(0)
        state.inspect(dict(current=True, candidate=None, visual_level=None), f, f.image(), candidate(),
                      lambda crop: calls.append(crop) or response(name), {1: 10000, 2: 20000}, max_age=15, clock=lambda: 101)
        assert len(calls) == 1


def test_job_line_sits_directly_above_the_name_line():
    from character_name_ocr import job_region
    layout = candidate(x=780, y=1054.5, step=100)[0]
    assert job_region(layout, (1920, 1080)) == [652, 1048, 774, 1064]  # Name: [652, 1064, 774, 1080].


def test_job_reads_are_rare_and_only_move_up_a_tier():
    state, image, layout = IdentityCapture('channel'), make_frame(0).image(), candidate()[0]
    def read(text):
        return state.read_job(image, layout, lambda crop: response(text), now)
    now = 0
    assert state.job_due(None, now) and read('Magiclan')['job'] == 'Magician' and state.job is None  # One read is not enough.
    assert not state.job_due(None, 59)
    now = 60; assert state.job_due(None, now); read('Magician'); assert state.job == 'Magician'
    assert not state.job_due(29, 10_000)  # Below the second-job level: never re-read.
    now = 10_000; assert state.job_due(30, now); assert read('Cleric')['tier'] == 2 and state.job == 'Magician'
    now = 10_060; assert state.job_due(30, now); read('Cleric'); assert state.job == 'Cleric'
    assert not state.job_due(99, 20_000)  # No further job is known yet.
    for now in (20_000, 20_060):read('Beginner')
    assert state.job == 'Cleric'  # A lower tier is a misread, never a demotion.
    assert read('Alpha') == dict(status='unrecognized', job=None, tier=None, text='Alpha', score=.99, box=job_region_box(layout))
    state.select('Other', NOW.isoformat()); assert state.job is None and state.job_due(None, 0)


def test_a_failed_job_read_keeps_the_name_read():
    state, reads = IdentityCapture('channel'), []
    def read(crop):
        reads.append(crop.size)
        if len(reads) == 2:raise RuntimeError('worker stopped')  # The second crop is the job line.
        return response('Alpha')
    f = make_frame(0)
    value = state.inspect(dict(current=True, candidate=None, visual_level=None), f, f.image(), candidate(), read,
                          {1: 10000, 2: 20000}, max_age=15, clock=lambda: 101)
    assert len(reads) == 2 and value['evidence']['status'] == 'candidate' and value['evidence']['name'] == 'Alpha'
    assert value['evidence']['job'] == dict(status='failed', error='RuntimeError')


def job_region_box(layout):
    from character_name_ocr import job_region
    return job_region(layout, (1920, 1080))
