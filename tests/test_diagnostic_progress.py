from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from exp_tracker.diagnostic_progress import progress
from exp_tracker.shadow_types import parse_percentage_only

NOW = datetime(2026,1,1,tzinfo=timezone.utc)


def row(index, percentage='33.00', **changes):
    value = dict(index=index,event_id=f'run:{index}',run_id='run',assigned_channel='alpha',channel='alpha',
        source_kind='twitch',character_id=1,session_id=1,
        received_at=(NOW+timedelta(seconds=15*(index-1))).isoformat(),
        raw_text=f'[{percentage}%]',candidate=None,percentage_only_candidate=parse_percentage_only(f'[{percentage}%]'),
        fresh_at_capture=True,capture_acquired=True,status='diagnostic_percentage_only',hud_count=1,
        visual_level=64,visual_status='available',neural_level=None,interval_seconds=15)
    value.update(changes)
    return value


def test_only_explicit_clean_rotation_can_extend_one_segment():
    a=row(59,source_identity='a'*64,coordinator_instance='b'*32)
    b=row(60,'33.01',source_identity='a'*64,coordinator_instance='b'*32)
    c=row(1,'33.02',received_at=(NOW+timedelta(seconds=900)).isoformat(),
        run_id='next',event_id='next:1',rotation_from='run',source_identity='a'*64,coordinator_instance='b'*32)
    result=progress([a,b,c],now=NOW+timedelta(seconds=900),current_run_id='next')
    assert len(result['segments'])==1 and result['current_pace']
    assert result['current_segment']['run_ids']==['run','next']
    for change in ({'rotation_from':None},{'coordinator_instance':'c'*32},{'source_identity':'d'*64},{'index':2}):
        other={**c,**change}
        assert len(progress([a,b,other],now=NOW+timedelta(seconds=900))['segments'])==2
    c['timing_mode']='simulated'
    assert progress([a,b,c],now=NOW+timedelta(seconds=900))['comparisons'][-1]['reason']=='simulated_timing_not_real_progress'


def run(rows, **kwargs):
    return progress(rows,now=NOW+timedelta(seconds=120),stale_after_seconds=200,**kwargs)


def test_mixed_strict_and_recovered_points_count_once_and_preserve_inputs():
    a=row(1,raw_text='100[33.00%]',candidate=dict(exp='100',percentage='33.00'),percentage_only_candidate=None,status='diagnostic_pair')
    b=row(2,raw_text='5,031[33,05%]',percentage_only_candidate=None,status='malformed_or_unavailable')
    c=row(3,'33.10')
    rows=[a,b,c];before=deepcopy(rows)
    result=run(rows)
    segment=result['segments'][0]
    assert segment['readings']==3 and segment['difference_bp']==10
    assert segment['difference_percentage_points']=='0.10'
    assert segment['evidence_counts']==dict(strict_full=1,strict_percentage_only=1,grammar_recovered=1)
    assert segment['pace']['value']['approximate']==12
    assert segment['pace']['nearest_half_up']['lower']['approximate']==10.8
    assert segment['pace']['truncation']['upper']['approximate']==13.2
    assert result['latest_percentage']['percentage']=='33.10'
    assert result['current_pace'] and not result['trusted'] and rows==before
    assert run(rows,include_recovered=False)['current_pace'] is None
    # This full-EXP proposal also has a percentage interpretation, still one point.
    b.update(raw_text='123,456|33.05%|')
    assert run(rows)['segments'][0]['readings']==3


def test_percentage_to_full_and_estimated_exp_is_an_outer_range_not_a_total():
    result=run([row(1,'33.05'),row(2,raw_text='200[33.10%]',candidate=dict(exp='200',percentage='33.10'),percentage_only_candidate=None,status='diagnostic_pair')])
    s=result['segments'][0]
    assert s['pace'] is None and s['requirement']['to_next']==1497832
    assert s['estimated_exp']['hypotheses']['nearest_half_up']['lower']['approximate']==pytest.approx(599.1328)
    assert s['estimated_exp']['hypotheses']['truncation']['upper']['approximate']==pytest.approx(898.6992)
    assert s['estimated_exp']['requirement_status']=='community_provisional'


def test_zero_and_negative_display_changes_do_not_establish_zero_gain_or_levelups():
    result=run([row(1),row(2),row(3)])
    assert result['current_pace']['value']['approximate']==0
    assert result['current_pace']['nearest_half_up']['lower']['approximate']==-1.2
    negative=run([row(1),row(2,'32.99'),row(3,'33.01')])
    assert negative['comparisons'][1]['change']=='missing_comparison'  # Unconfirmed loss is no longer a negative gain endpoint.
    assert negative['percentage_reviews'][1]['status']=='pending_exp_decrease'
    assert negative['percentage_reviews'][2]['resolution']=='suspected_ocr_anomaly'
    assert len(negative['segments'])==2 and negative['current_pace'] is None


@pytest.mark.parametrize('change,reason',[
    ({'fresh_at_capture':False},'failed_or_stale_capture'),
    ({'status':'capture_failed'},'failed_or_stale_capture'),
    ({'capture_acquired':False},'failed_or_stale_capture'),
    ({'hud_count':2},'hud_not_unique'),
    ({'visual_level':None},'visual_level_unavailable'),
    ({'neural_level':{'level':54}},'level_evidence_conflict'),
    ({'character_id':None},'explicit_assignment_missing'),
    ({'received_at':None},'timestamp_unavailable_or_out_of_order'),
    ({'timestamp_ordered':False},'timestamp_unavailable_or_out_of_order'),
    ({'candidate_invalid':True},'candidate_contradiction'),
    ({'percentage_only_invalid':True},'candidate_contradiction'),
    ({'raw_text':'0.85%1','percentage_only_candidate':None},'invalid_or_ambiguous_percentage'),
])
def test_invalid_intermediate_attempts_break_not_bridge(change,reason):
    result=run([row(1),row(2,**change),row(3),row(4)])
    assert result['comparisons'][1]['reason']==reason
    assert result['current_pace'] is None


@pytest.mark.parametrize('changes,reason',[
    ({'channel':'other'},'source_changed'),({'assigned_channel':'other'},'source_changed'),
    ({'character_id':2},'character_or_session_changed'),({'session_id':2},'character_or_session_changed'),
    ({'run_id':'other'},'run_boundary'),({'visual_level':65},'level_changed'),
    ({'index':3},'missing_attempt'),({'received_at':NOW.isoformat()},'nonincreasing_timestamp'),
    ({'received_at':(NOW+timedelta(seconds=25)).isoformat()},'sampling_gap'),
    ({'event_id':'run:1'},'duplicate_event')])
def test_boundaries_are_explicit(changes,reason):
    middle=row(2); middle.update(changes)
    result=run([row(1),middle])
    assert result['comparisons'][1]['reason']==reason
    assert result['current_pace'] is None


@pytest.mark.parametrize('level,status',[(99,'source_disagreement'),(100,'missing_requirement'),(200,'missing_requirement')])
def test_percentage_progress_does_not_require_an_exp_table(level,status):
    result=run([row(1,visual_level=level),row(2,'33.05',visual_level=level),row(3,'33.10',visual_level=level)])
    assert result['current_pace']
    assert result['current_segment']['estimated_exp'] is None
    assert result['current_segment']['requirement']['status']==status


def test_unknown_levels_preserve_evidence_without_comparable_progress():
    result=run([row(1,visual_level=None),row(2,'33.05',visual_level=None)])
    assert result['latest_percentage']['percentage']=='33.05'
    assert not result['segments'] and result['current_pace'] is None


def test_staleness_and_explicit_interruption_keep_old_values_but_disable_current_pace():
    rows=[row(1),row(2,'33.05'),row(3,'33.10')]
    stale=progress(rows,now=NOW+timedelta(seconds=500))
    assert stale['stale'] and stale['current_pace'] is None
    assert stale['segments'][0]['pace'] and stale['latest_percentage']['percentage']=='33.10'
    rows[-1]['run_interrupted']=True
    stopped=run(rows)
    assert stopped['reason']=='explicit_run_interruption' and stopped['current_segment'] is None
    assert stopped['current_pace'] is None
    waiting=run(rows,current_run_id='new_run')
    assert waiting['current_segment'] is None and waiting['latest_percentage']['percentage']=='33.10'


def test_quantization_boundary_and_insufficient_span():
    result=run([row(1,'0.00'),row(2,'0.00'),row(3,'0.00')])
    assert result['current_pace']['nearest_half_up']['upper']['approximate']==.6
    assert result['current_pace']['truncation']['upper']['approximate']==1.2
    assert run([row(1),row(2),row(3)],min_span_seconds=31)['current_pace'] is None
    assert run([row(1),row(2),row(3)],min_readings=4)['current_pace'] is None


def test_out_of_order_or_future_evidence_never_replaces_a_newer_reading():
    rows=[row(1,'33.05'),row(2,'33.10'),row(3,'99.00',received_at=NOW.isoformat(),timestamp_ordered=False)]
    result=run(rows)
    assert result['latest_percentage']['percentage']=='33.10' and result['current_segment'] is None
    rows[-1].update(received_at=(NOW+timedelta(seconds=500)).isoformat(),timestamp_ordered=True)
    result=run(rows)
    assert result['latest_percentage']['percentage']=='33.10'
    assert result['comparisons'][-1]['reason']=='future_timestamp'
    stale=run([row(1,fresh_at_capture=False)])
    assert stale['stale'] and stale['latest_percentage'] is None  # Raw stale candidate remains in input/evidence, never a public baseline.
