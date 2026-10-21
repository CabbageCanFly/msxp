"""Causal level evidence and dated pace; missing frames never become observations."""
from copy import deepcopy
from datetime import timedelta

import pytest

from exp_tracker.diagnostic_evidence import project
from exp_tracker.diagnostic_progress import percentage_point,progress
from exp_tracker.product import refresh,window_comparisons
from exp_tracker.shadow_grammar import interpret_exp
from tests.test_diagnostic_evidence import neural
from tests.test_diagnostic_progress import NOW
from tests.test_hud_resilience import at,present
from tests.test_product import tracking


def example(index,text,visual=67,level=67,score=.99,**changes):
    changes.setdefault('frame_sha256',f'{index:064x}')
    return neural(index,text,visual=visual,level=level,score=score,
        **changes)


def supported():
    return [example(1,'397,820[22.63%]'),example(2,'398,923122.69%1')]


def test_telfer_defects_are_not_repaired_into_known_answers():
    rows=supported()+[example(3,'399.979122.25%1',level=57,score=.68772),
        example(4,'401.128122.82X1',visual=None,level=None,score=0),
        example(5,'402.319[22.89%]',visual=None,level=57,score=.71207)]
    rows[3]['neural_level']=dict(status='no_output',text='',level=None,score=0,preprocessing='neutral4')
    frozen=deepcopy(rows);out=project(rows)
    assert rows==frozen
    assert out[2]['experimental_level']['value']==67
    assert out[2]['experimental_level']['status']=='contextual'
    assert out[2]['experimental_level']['reader_evidence']['value'] is None
    assert out[2]['exp_validity']['status']=='invalid'
    data=progress(rows,now=NOW+timedelta(seconds=60))
    decisions=data['percentage_reviews']
    # The whole-pair arithmetic veto now precedes percentage-decrease review.
    assert decisions[2]['reason']=='arithmetic_pair_veto' and not decisions[2]['public_eligible']
    assert not decisions[3]['progress_eligible']
    assert percentage_point(out[3])[0] is None
    assert out[4]['experimental_level']['value']==67
    assert out[4]['exp_validity']['status']=='consistent'
    assert decisions[4]['progress_eligible']
    assert data['comparisons'][-1]['reason']=='baseline'  # No #10 -> #13 gain.
    old=project(rows,allow_context=False)
    assert old[2]['experimental_level']['value'] is None
    assert old[4]['experimental_level']['value']==67 and old[4]['experimental_level']['status']=='exp_derived'


@pytest.mark.parametrize('text',['401.128122.82X1','401,128[22.82X1'])
def test_x_percent_hypothesis_is_review_only(text):
    result=interpret_exp(text)
    assert result['full_exp']['classification']=='rejected'
    assert result['percentage']['classification']=='rejected'
    assert not result['strict_full'] and not result['strict_percentage_only']
    hypothesis,=result['symbol_hypotheses']
    assert hypothesis['interpretation']=='401,128[22.82%]'
    assert not hypothesis['usable_as_observation'] and not hypothesis['trusted']
    assert any(e['old']=='X' and e['new']=='%' for e in hypothesis['edits'])
    assert interpret_exp(text,source_complete=False)['symbol_hypotheses']==[]


@pytest.mark.parametrize('text',['22.82X1','0.85X1','401,128122.8X1','401,12812282X1',
    '401,128122.82x1','4X1,128[22.82%]','X[22.82%]','401,128[22.82X','401,128[22.82X1extra'])
def test_missing_digits_and_other_symbols_do_not_get_percent_hypotheses(text):
    assert interpret_exp(text)['symbol_hypotheses']==[]


@pytest.mark.parametrize('changes',[
    dict(level=57,score=.99,visual=None),dict(level=68,score=.99,visual=68),
    dict(visual=57,level=57,score=.7),dict(fresh_at_capture=False),dict(hud_count=2),
    dict(character_id=2),dict(session_id=2),dict(source_identity='other'),dict(run_id='restart'),
    dict(timestamp_ordered=False),dict(crop_suspect=True),dict(frame_sha256=f'{1:064x}'),
])
def test_context_does_not_override_hard_boundaries(changes):
    values=dict(visual=None,level=57,score=.7);values.update(changes)
    last=example(3,'402.319[22.89%]',**values)
    result=project(supported()+[last])[-1]
    assert not result['experimental_level'].get('contextual')


def test_unique_arithmetic_supplies_level_without_prior_reader_support():
    rows=[example(i,'402.319[22.89%]',visual=None,level=57,score=.7) for i in range(1,5)]
    assert all(r['experimental_level']['value']==67 and r['experimental_level']['status']=='exp_derived' for r in project(rows))
    # A clipped/reset integer cannot support carrying the old level without visual agreement.
    result=project(supported()+[example(3,'103[0.01%]',visual=None,level=57,score=.7)])[-1]
    assert result['experimental_level']['value'] is None


def test_context_expires_and_repeated_weak_conflicts_cannot_keep_it_alive():
    rows=supported()+[example(i,'402.319[22.89%]',visual=None,level=57,score=.7) for i in range(3,6)]
    assert [r['experimental_level'].get('contextual',False) for r in project(rows)[2:]]==[True,True,False]
    rows=supported()+[example(i,'402.319[22.89%]',visual=None,level=None,score=0) for i in range(3,13)]
    for r in rows[2:]:r['neural_level']=None
    values=project(rows)
    assert values[4]['experimental_level']['value']==67
    assert values[-1]['experimental_level']['value']==67
    assert values[-1]['experimental_level']['status']=='exp_derived'
    assert not values[-1]['experimental_level'].get('contextual')


def test_context_state_is_identical_across_streamed_pages():
    rows=supported()+[example(3,'402.319[22.89%]',visual=None,level=57,score=.7),
        example(4,'403,270[22.94%]')]
    state={};paged=project(rows[:2],state=state)+project(rows[2:],state=state)
    assert paged==project(rows)


def test_context_cannot_complete_a_strict_window_or_mask_a_level_up():
    from exp_tracker.product import level_events
    rows=supported()+[example(3,'402.319[22.89%]',visual=None,level=57,score=.7)]
    rows += [example(i,'403,270[22.94%]') for i in range(4,22)]
    rows=project(rows);now=NOW+timedelta(seconds=300)
    data=progress(rows,now=now)
    for r,v in zip(rows,data['percentage_reviews']):r['percentage_review']=v
    metrics=window_comparisons(dict(observations=rows,percentage_progress=data),now=now)
    assert data['current_segment']['span_seconds']['approximate']==300
    assert not metrics['5']['eligible']
    assert metrics['5']['eligibility_checks']['reader_supported_levels'] is False
    rows=supported()+[example(3,'1,757,300[99.97%]'),
        example(4,'103[0.01%]',visual=68,level=68),example(5,'435[0.02%]',visual=68,level=68),
        example(6,'800[0.04%]',visual=68,level=68)]
    projected=project(rows)
    assert projected[-3]['experimental_level']['value']==68
    assert projected[-3]['experimental_level']['status']=='agreement'
    assert projected[-2]['experimental_level']['value']==68
    assert not projected[-2]['experimental_level'].get('contextual')
    # The existing transition detector still requires two supported captures.
    for r in projected:r['percentage_review']=dict(public_eligible=True)
    assert level_events(projected)[-1]['level']==68


def test_percentage_progress_cannot_consume_an_x_hypothesis_even_with_both_levels():
    rows=supported()+[example(3,'401.128122.82X1')]
    data=progress(rows,now=NOW+timedelta(seconds=30))
    assert not data['percentage_reviews'][-1]['public_eligible']
    assert data['current_segment'] is None
    assert data['segments'][-1]['readings']==2


@pytest.mark.parametrize('missing',[1,2,5,10,16])
def test_missing_attempts_retain_dated_rate_without_fake_intervals(tracking,missing):
    _,store,d=tracking
    for i in range(1,12):at(d,i,(i-1)*20,f'[33.{(i-1)*2:02}%]')
    base=present(d,200)['responsive_pace']
    for i in range(12,12+missing):
        at(d,i,(i-1)*20,'?',status='malformed_or_unavailable',visual_level=None,neural_level=None)
    end=200+missing*20;value=present(d,end);p=value['responsive_pace']
    assert not p['active'] and p['age_seconds']==missing*20
    assert p['presentation']['estimates']['exp_per_hour'] is not None
    assert p['presentation']['estimates']['eta'] is None
    assert p['coverage_seconds']['approximate']<=200
    assert p['end']==base['end']
    # Aging the earliest point can change whole-EXP rounding by one EXP.
    assert p['estimates']['exp_per_hour']['value']['approximate']==pytest.approx(
        sum(e['gain']['approximate'] for e in p['intervals'])*12)
    assert not value['windows']['5']['eligible']
    expired=refresh(value,now=NOW+timedelta(seconds=200+1800),activity=dict(state='waiting'))
    assert expired['responsive_pace']['presentation']['state']=='paused'
    assert expired['responsive_pace']['presentation']['estimates']['exp_per_hour'] is None
    at(d,12+missing,end+20,'[34.00%]');at(d,13+missing,end+40,'[34.02%]')
    recovered=present(d,end+40)['responsive_pace']
    assert recovered['active'] and recovered['presentation']['state']=='observed'
    assert recovered['estimates']['exp_per_hour']['value']['approximate']==pytest.approx(
        sum(e['gain']['approximate'] for e in recovered['intervals'])*12)
    assert recovered['interval_counts']['endpoint_supported']==(1 if missing*20+20<=300 else 0)
    assert not store.db.execute('SELECT 1 FROM observations').fetchone()
