"""Synthetic diagnostics only; repaired strings never enter strict progress inputs."""
import copy
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'tools'))
    return importlib.import_module('grammar_recovery'), importlib.import_module('percentage_progress')


@pytest.mark.parametrize('raw,proposed,edits', [
    ('[70.63%1','[70.63%]',1), ('[70 57%]','[70.57%]',1),
    ('[7057%]','[70.57%]',1), ('170 57%1','[70.57%]',3),
    ('998,512170.32%1','998,512[70.32%]',2), ('[70.631]','[70.63%]',1),
    ('74,050[25.17%1','74,050[25.17%]',1),
    ('1,241199.82%]','1,241[99.82%]',1)])
def test_fixed_hypotheses_record_every_edit_but_not_trust(modules, raw, proposed, edits):
    grammar, _ = modules
    result = grammar.propose(raw)
    assert result['raw'] == raw and result['strict'] is None and not result['trusted']
    hypothesis = next(p for p in result['proposals'] if p['interpretation'] == proposed)
    assert len(hypothesis['edits']) == edits and not hypothesis['numerical_identity_verified']
    assert hypothesis['image_verification'] == 'required' and not hypothesis['trusted']


@pytest.mark.parametrize('raw', ['0.85%1','70.63%1','[70.6%1','[100.01%1',
    '[7O.63%1','689.,965[92.17%]','[7 0.63%1','[705%','[70.63%_'])
def test_unknown_or_missing_numbers_never_reconstructed(modules, raw):
    assert modules[0].propose(raw)['proposals'] == []


@pytest.mark.parametrize('raw', ['74,050[25.17%]','2345[92.74%]','4,059[25.17%]','[70.63%]'])
def test_valid_syntax_cannot_detect_wrong_digits(modules, raw):
    result=modules[0].propose(raw)
    assert result['classification']=='complete_raw_strict'
    assert not result['numerical_identity_verified'] and not result['proposals']


def test_wrong_suffix_and_clipped_digits_need_source_evidence(modules):
    grammar, _=modules
    # Actual numeral 1 or damaged EXP can have exactly this raw string.
    assert grammar.propose('74,050[25.17%1')['proposals']
    assert grammar.propose('4,059[25.17%1', source_complete=False)['proposals']==[]
    assert grammar.propose('[70.63%1', source_complete=False)['proposals']==[]


@pytest.mark.parametrize('raw', ['S1','S 1'])
def test_s_to_five_requires_numeric_tile_context_and_is_never_a_level_accept(modules, raw):
    grammar, _=modules
    assert not grammar.propose(raw, field='level')['proposals']
    proposal=grammar.propose(raw, field='level', numeric_level_context=True)['proposals'][0]
    assert proposal['reading']['level']==51 and not proposal['trusted']
    for other in ('s1','O1','I1','Sa.','Su'):
        assert not grammar.propose(other, field='level', numeric_level_context=True)['proposals']


def row(index, percentage='70.00', **extra):
    result=dict(type='attempt', index=index, candidate=None, neural={'text':f'[{percentage}%]'},
        source={'channel':'synthetic'}, current=True, status='diagnostic_percentage_only',
        visual_level=63, visual_status='available', localization={'count':1},
        received_at=(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(seconds=15*(index-1))).isoformat())
    result.update(extra)
    return result


def test_exact_differences_and_both_quantization_hypotheses(modules):
    rows=[row(1), row(2,'70.04'),row(3,'70.10')]
    frozen=copy.deepcopy(rows)
    result=modules[1].progress(rows)
    segment=result['segments'][0]
    assert segment['difference_bp']==10 and segment['difference_percentage_points']=='0.10'
    assert segment['pace']['value']['approximate']==12
    for rule in ('nearest_half_up','truncation'):
        assert segment['pace'][rule]['lower']['approximate']==10.8
        assert segment['pace'][rule]['upper']['approximate']==13.2
    assert result['comparisons'][1]['difference_bp']==4
    assert rows==frozen and not result['trusted'] and not result['identity_verified']


def test_zero_and_negative_changes_do_not_infer_levelups(modules):
    module=modules[1]
    zero=module.progress([row(1),row(2),row(3)])['segments'][0]
    assert zero['pace']['value']['approximate']==0
    assert zero['pace']['nearest_half_up']['lower']['approximate']==-1.2
    negative=module.progress([row(1),row(2,'69.99'),row(3,'70.00')])
    edge=negative['comparisons'][1]
    assert edge['change']=='negative' and edge['reason']=='percentage_decrease_no_levelup_inferred'
    assert len(negative['segments'])==2 and all(s['pace'] is None for s in negative['segments'])


def test_zero_endpoint_bounds_keep_hypotheses_separate(modules):
    pace=modules[1].progress([row(1,'0.00'),row(2,'0.00'),row(3,'0.00')])['segments'][0]['pace']
    assert pace['nearest_half_up']['upper']['approximate']==.6
    assert pace['truncation']['upper']['approximate']==1.2


@pytest.mark.parametrize('extra,reason', [
    ({'current':False},'not_fresh_success'), ({'status':'capture_failed'},'not_fresh_success'),
    ({'visual_level':None},'visual_level_unavailable'),
    ({'visual_status':'unavailable'},'visual_level_unavailable'),
    ({'localization':{'count':2}},'hud_not_unique'), ({'localization':None},'hud_not_unique'),
    ({'received_at':None},'timestamp_unavailable'), ({'received_at':'2026-01-01T00:00:15'},'timestamp_unavailable'),
    ({'source':{}},'recorded_channel_missing'), ({'reasons':['conflict']},'level_contradiction'),
    ({'candidate':[123,70]},'candidate_contradiction')])
def test_failed_intermediate_attempt_breaks_segments(modules, extra, reason):
    result=modules[1].progress([row(1),row(2,**extra),row(3),row(4)])
    assert result['comparisons'][1]['reason']==reason
    assert all(s['pace'] is None for s in result['segments'])


@pytest.mark.parametrize('middle,reason', [
    (row(2,source={'channel':'other'}),'source_changed'),
    (row(2,visual_level=64),'level_changed'),
    (row(3),'missing_attempt'),
    (row(2,received_at='2026-01-01T00:00:23+00:00'),'sampling_gap'),
    (row(2,received_at='2026-01-01T00:00:00+00:00'),'nonincreasing_timestamp')])
def test_source_level_timestamp_and_missing_index_breaks(modules, middle, reason):
    result=modules[1].progress([row(1),middle])
    assert result['comparisons'][1]['reason']==reason
    assert all(s['pace'] is None for s in result['segments'])


def test_repairs_partial_evidence_and_derived_levels_cannot_feed_pace(modules):
    grammar, pace=modules
    bad=row(2,neural={'text':'[70.63%1'}, candidate=None,
            percentage_only_candidate={'percentage':'70.63'},
            partial_percentage_evidence={'percentage':'70.63'})
    bad['grammar_proposals']=grammar.propose(bad['neural']['text'])['proposals']
    result=pace.progress([row(1),bad,row(3)])
    assert result['comparisons'][1]['reason']=='no_strict_observation'
    derived=row(2,visual_level=None,level_evidence={'hypotheses':{'nearest_half_up':{'levels':[63]}}})
    assert pace.strict_point(derived)[1]=='visual_level_unavailable'


def test_full_and_percentage_only_share_strict_endpoint_semantics(modules):
    full=row(1,neural={'text':'1,000[70.00%]'},candidate=[1000,70.0],status='diagnostic_pair')
    assert modules[1].progress([full,row(2),row(3)])['segments'][0]['pace'] is not None


def test_minimum_span_exact_timestamps_and_config(modules):
    pace=modules[1]
    short=[row(1),row(2),row(3,received_at='2026-01-01T00:00:29.161433+00:00')]
    assert pace.progress(short)['segments'][0]['reason']=='insufficient_span'
    assert pace.progress([row(1),row(2),row(3)],min_span_seconds=31)['segments'][0]['pace'] is None
    assert pace.progress([row(1),row(2),row(3)],min_readings=4)['segments'][0]['pace'] is None
    for kwargs in ({'min_readings':2},{'min_span_seconds':0},{'min_span_seconds':29},{'interval_seconds':0}):
        with pytest.raises(ValueError):
            pace.progress([],**kwargs)


def test_report_comparison_keeps_unknown_references_and_component_errors_separate(modules):
    compare=importlib.import_module('evaluate_shadow_grammar').compare
    assert compare({'kind':'full_exp_pair','exp':74050,'percentage':'25.17'},
                   {'exp':[74059],'percentage':[25.17]})=='disagreement'
    assert compare({'kind':'full_exp_pair','exp':74059,'percentage':'25.17'},
                   {'exp':[None],'percentage':[25.17]})=='unknown_reference'
    assert compare({'kind':'percentage_only','percentage':'70.63'},
                   {'exp':[None],'percentage':[70.63]})=='agreement'


def test_raw_outputs_and_proposals_are_not_mutated_or_promoted(modules):
    grammar, module=modules
    text='[70.63%1'
    proposed=grammar.propose(text)
    assert module.strict_point(row(1,neural={'text':text},grammar_proposals=proposed['proposals']))[0] is None
    assert grammar.propose(text)==proposed and proposed['raw']==text
    assert grammar.propose(None)['classification']=='unavailable'
    assert module.strict_point(row(1,neural={'text':'1[70.63%]'}))[1]=='candidate_contradiction'
