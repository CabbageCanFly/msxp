from copy import deepcopy
from datetime import timedelta

import pytest

from exp_tracker.diagnostic_evidence import consistency,project
from exp_tracker.diagnostic_progress import progress
from exp_tracker.product import reading
from tests.test_diagnostic_progress import row,NOW


def neural(index, text='713,015[45.13%]', level=65, score=.96, visual=63, **changes):
    from exp_tracker.shadow_grammar import interpret_exp
    parsed=interpret_exp(text)
    full=parsed['strict_full']
    return row(index, raw_text=text, candidate={k:full[k] for k in ('exp','percentage')} if full else None,
        percentage_only_candidate=parsed['strict_percentage_only'],status='diagnostic_pair' if full else 'malformed_or_unavailable',
        visual_level=visual,visual_status='available' if visual else 'unavailable',
        neural_level=dict(status='numeric_candidate',text=str(level),level=level,score=score,preprocessing='neutral4'),**changes)


@pytest.mark.parametrize('exp,pct,status',[(2458,'45.09','invalid'),(2802,'45.12','invalid'),(713015,'45.13','consistent')])
def test_conditional_full_exp_veto_never_discards_percentage(exp,pct,status):
    raw=neural(1,f'{exp:,}[{pct}%]',visual=65)
    original=deepcopy(raw)
    projected=project([raw])[0]
    assert projected['exp_validity']['status']==status and raw==original
    value=reading(projected)
    assert value['exp']==(str(exp) if status=='consistent' else None)
    assert value['percentage']==pct
    assert projected['candidate']['exp']==str(exp)


def test_unknown_or_disputed_level_is_indeterminate_not_an_arbitrary_veto():
    for level in (None,99,100,200):
        result=consistency(dict(exp='2458',percentage='45.09'),level)
        assert result['status']=='indeterminate'
    value=reading(project([neural(1,'2,458[45.09%]',level=99,visual=99)])[0])
    assert value['exp']=='2458' and value['exp_validity']['status']=='indeterminate'


def test_neural_temporal_and_strict_arithmetic_can_overrule_tesseract_without_an_80_percent_cutoff():
    rows=[neural(1),neural(2,score=.74),neural(3,score=.71)]
    values=project(rows)
    assert values[0]['experimental_level']['value'] is None
    assert values[1]['experimental_level']['value']==65
    assert values[2]['experimental_level']['value']==65
    assert values[1]['experimental_level']['status']=='provisional_neural'
    assert progress(rows,now=NOW+timedelta(seconds=30))['current_segment']['readings']==2


def test_single_wrong_neural_number_breaks_context_even_at_high_confidence():
    rows=[neural(1),neural(2),neural(3,level=55,score=.999,visual=None),neural(4),neural(5)]
    values=project(rows)
    assert [r['experimental_level']['value'] for r in values]==[None,65,None,None,65]
    assert values[2]['experimental_level']['reason']=='new_neural_level_requires_confirmation'
    result=progress(rows,now=NOW+timedelta(seconds=60))
    assert result['current_segment']['readings']==1 and result['current_pace'] is None


def test_neural_only_percentage_fields_need_repeated_visual_evidence_not_an_exp_inferred_level():
    rows=[neural(i,'[50.00%]',level=51,visual=None) for i in range(1,4)]
    assert [r['experimental_level']['value'] for r in project(rows)]==[None,None,51]
    for row_ in rows:row_['neural_level']['score']=.79
    assert all(r['experimental_level']['value'] is None for r in project(rows))


def test_known_51_to_50_wrong_rgb_outputs_and_arithmetic_contradictions_do_not_seed_context():
    rows=[neural(i,'10,000[8.00%]',level=50,visual=51,score=.992) for i in range(1,5)]
    # Competing Tesseract plus incompatible arithmetic forbids confidence-only repetition.
    assert all(r['experimental_level']['value'] is None for r in project(rows))
    for r in rows:r['neural_level']['preprocessing']='rgb4'
    assert all(r['experimental_level']['value'] is None for r in project(rows))


def test_short_missing_level_reads_carry_confirmed_context_but_do_not_bridge_capture_failures():
    rows=[neural(1),neural(2)]
    rows.extend(row(i,'45.13',visual_level=None,visual_status='unavailable') for i in range(3,6))
    assert [r['experimental_level']['value'] for r in project(rows)]==[None,65,65,65,None]
    rows[2]['status']='capture_failed'
    assert all(r['experimental_level']['value'] is None for r in project(rows)[2:])


@pytest.mark.parametrize('changes',[
    dict(character_id=2),dict(session_id=2),dict(channel='other'),dict(assigned_channel='other'),
    dict(run_id='restart'),dict(source_identity='changed'),dict(index=7),dict(fresh_at_capture=False),
    dict(hud_count=2),dict(timestamp_ordered=False),dict(received_at=(NOW+timedelta(seconds=120)).isoformat()),
])
def test_context_cannot_cross_assignment_time_capture_or_run_boundaries(changes):
    missing=row(3,'45.13',visual_level=None,visual_status='unavailable');missing.update(changes)
    assert project([neural(1),neural(2),missing])[-1]['experimental_level']['value'] is None


def test_explicitly_incomplete_level_crop_cannot_supply_or_inherit_a_level():
    rows=[neural(1),neural(2),neural(3,visual=65)]
    rows[-1]['neural_level']['source_complete']=False
    assert project(rows)[-1]['experimental_level']['value'] is None


def test_arithmetic_still_cannot_verify_small_digit_errors_or_correlated_wrong_fields():
    for exp in (74050,74059):
        assert consistency(dict(exp=str(exp),percentage='25.17'),40)['status']=='consistent'
    assert consistency(dict(exp='2345',percentage='92.74'),6)['status']=='invalid'
    assert consistency(dict(exp='1241',percentage='99.82'),9)['status']=='invalid'
    # Both visual algorithms can share a wrong level; the policy is explicitly untrusted.
    result=project([neural(1,'[50.00%]',level=50,visual=50)])[0]['experimental_level']
    assert result['value']==50 and result['trusted'] is False


def test_zero_zero_cannot_supply_arithmetic_corroboration_of_a_neural_level():
    rows=[neural(i,'0[0.00%]',visual=None) for i in (1,2)]
    assert all(r['experimental_level']['value'] is None for r in project(rows))


def test_historical_single_frame_level_errors_are_not_silently_corrected():
    # Saved 599s: Tesseract 3 versus weak but correct neural 8 => abstain.
    a=neural(1,'010.00%]',level=8,score=.48416,visual=3)
    assert project([a])[0]['experimental_level']['value'] is None
    # Saved 1061.75s: Tesseract 8 versus nonnumeric neural; provisional reference 9.
    # The legacy Tesseract-only error survives: neither arithmetic nor this policy invents 9.
    b=neural(1,'1[0.08%]',visual=8)
    b['neural_level']=dict(status='nonnumeric',text='\u65e5',level=None,score=.52745,preprocessing='neutral4')
    projected=project([b])[0]
    assert projected['experimental_level']['value']==8 and projected['experimental_level']['trusted'] is False
    assert projected['exp_validity']['status']=='invalid'
