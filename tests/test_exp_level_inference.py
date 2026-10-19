from datetime import timedelta

import pytest

from exp_tracker.diagnostic_evidence import exp_derived, project
from exp_tracker.diagnostic_progress import percentage_point, progress
from exp_tracker.exp_requirements import community_table, requirement
from exp_tracker.product import level_events, reading
from exp_tracker.shadow_grammar import interpret_exp
from tests.test_diagnostic_progress import row, NOW

L42 = 356916


def display(exp, total=L42):
    bp = (20000*exp+total)//(2*total)
    return f'{bp//100}.{bp%100:02}'


def pair(index, exp, pct=None, **changes):
    """A strict full HUD pair with the level HUD obscured (no reader level)."""
    text = f'{exp:,}[{pct or display(exp)}%]'
    full = interpret_exp(text)['strict_full']
    value = dict(raw_text=text, candidate=dict(exp=full['exp'], percentage=full['percentage']),
        percentage_only_candidate=None, status='diagnostic_pair', visual_level=None,
        visual_status='unavailable', frame_sha256=f'{index:064x}')
    return row(index, **{**value, **changes})


def only(index, pct, **changes):
    return row(index, pct, visual_level=None, visual_status='unavailable', frame_sha256=f'{index:064x}', **changes)


def levels(rows, **kwargs):
    return [r['experimental_level']['value'] for r in project(rows, **kwargs)]


def climbing(start=1, count=3, exp=278125, step=400):
    return [pair(start+i, exp+i*step) for i in range(count)]


def test_worked_example_is_uniquely_level_42_under_both_hypotheses():
    result = exp_derived(dict(exp='278125', percentage='77.92'))
    assert result['status'] == 'unique' and result['unique_level'] == 42
    assert result['hypotheses'] == dict(nearest_half_up=[42], truncate=[42])
    data, sha = community_table()
    assert result['table_version'] == data['version'] and result['table_sha256'] == sha
    assert result['supported_levels'] == [1, 89]
    assert not result['trusted'] and not result['authoritative'] and not result['visual']


def test_ambiguous_and_hypothesis_split_pairs_never_yield_a_level():
    result = exp_derived(dict(exp='100', percentage='0.02'))
    assert result['status'] == 'ambiguous' and result['unique_level'] is None
    assert result['hypotheses'] == dict(nearest_half_up=[44, 45, 46, 47, 48, 49], truncate=[42, 43, 44, 45])
    # Each rule alone is unique, but they disagree: no rule is chosen after the fact.
    split = exp_derived(dict(exp='2', percentage='0.04'))
    assert split['hypotheses'] == dict(nearest_half_up=[14], truncate=[13])
    assert split['status'] == 'ambiguous' and split['levels'] == [13, 14]
    # One matching rule is still a unique table level.
    single = exp_derived(dict(exp='74050', percentage='25.17'))
    assert single['hypotheses'] == dict(nearest_half_up=[40], truncate=[]) and single['unique_level'] == 40
    rows = [pair(i, 100, '0.02') for i in range(1, 5)]
    assert levels(rows) == [None]*4


@pytest.mark.parametrize('exp,pct', [(0, '0.00'), (1, '0.00'), (1000, '0.01'),
    (3914759, '50.00'),   # quest's disputed level-95 requirement 7,829,518 at 50%
    (5684000, '99.99')])  # could equal the level-89 floor or an unpublished 90+ total
def test_zero_and_pairs_that_could_need_unsupported_requirements_abstain(exp, pct):
    result = exp_derived(dict(exp=str(exp), percentage=pct))
    assert result['status'] == 'outside_supported_coverage' and result['unique_level'] is None
    assert requirement(95)['status'] == 'source_disagreement' and requirement(150)['status'] == 'missing_requirement'
    assert levels([pair(i, exp, pct) for i in range(1, 5)]) == [None]*4


def test_bad_contradictory_or_repaired_ocr_is_never_inferred():
    assert exp_derived(dict(exp='2345', percentage='92.74'))['status'] == 'incompatible'
    assert exp_derived(dict(exp='1241', percentage='99.82'))['status'] == 'incompatible'
    # Candidate disagreeing with its raw text and grammar-only repairs supply no pair.
    mismatch = [pair(i, 278125+i*400, candidate=dict(exp='278125', percentage='77.92')) for i in range(1, 4)]
    repaired = [pair(i, 0, raw_text=f'{278125+i*400:,}[{display(278125+i*400).replace(".", ",")}%]', candidate=None)
                for i in range(1, 4)]
    for rows in (mismatch, repaired):
        projected = project(rows)
        assert [r['experimental_level']['value'] for r in projected] == [None]*3
        assert all('exp_derived' not in r['experimental_level'] for r in projected)
    flagged = [pair(i, 278125+i*400, candidate_invalid=True) for i in range(1, 4)]
    assert levels(flagged) == [None]*3


def test_obscured_level_needs_three_fresh_rising_pairs_and_stays_labeled():
    rows = climbing()
    projected = project(rows)
    assert [r['experimental_level']['value'] for r in projected] == [None, None, 42]
    pending, confirmed = projected[1]['experimental_level'], projected[2]['experimental_level']
    assert pending['status'] == 'unavailable' and pending['exp_derived_context']['reason'] == 'exp_derived_confirmation_pending'
    assert pending['exp_derived']['unique_level'] == 42
    assert confirmed['status'] == 'exp_derived' and confirmed['reason'] == 'repeated_unique_exp_inference'
    assert confirmed['visual'] is None and confirmed['neural'] is None and not confirmed['trusted']
    assert confirmed['strict_window_eligible'] is False
    assert confirmed['exp_derived_context']['sample_event_ids'] == ['run:1', 'run:2', 'run:3']
    # Agreement with the pairs the level came from is circular, not verification.
    assert projected[2]['exp_validity']['status'] == 'indeterminate'
    assert projected[2]['exp_validity']['reason'] == 'level_derived_from_exp_pairs'
    point, reason = percentage_point(projected[2])
    assert reason is None and point['level'] == 42
    assert reading(projected[2])['exp'] == '278925' and reading(projected[2])['level']['status'] == 'exp_derived'
    # No reader-level event or public level-up is derived from arithmetic.
    assert level_events(projected) == []
    assert progress(rows, now=NOW+timedelta(seconds=30))['current_segment']['level'] == 42


@pytest.mark.parametrize('rows', [
    [pair(1, 278125)],
    [pair(1, 278125), pair(2, 278525)],
    [pair(i, 278125) for i in range(1, 5)],                                 # no EXP progression
    [pair(i, 278125+i*400, frame_sha256=None) for i in range(1, 5)],         # no frame evidence
])
def test_single_static_or_unhashed_unique_pairs_are_not_level_evidence(rows):
    assert all(value is None for value in levels(rows))


def test_reader_levels_take_precedence_and_disagreement_is_preserved():
    rows = climbing()+[pair(4, 279325, visual_level=24, visual_status='available')]
    projected = project(rows)
    conflict = projected[3]['experimental_level']
    assert conflict['value'] is None and conflict['status'] == 'conflict'
    assert conflict['reason'] == 'reader_conflicts_exp_derived_level'
    assert conflict['exp_derived_disagreement']['exp_derived_level'] == 42
    assert conflict['exp_derived_disagreement']['reader_level'] == 24
    # Two agreeing visual readers win, with the disagreement still recorded.
    neural = dict(status='numeric_candidate', text='24', level=24, score=.96, preprocessing='neutral4')
    rows[3].update(neural_level=neural)
    agreed = project(rows)[3]['experimental_level']
    assert agreed['value'] == 24 and agreed['status'] == 'agreement'
    assert agreed['exp_derived_disagreement']['exp_derived_level'] == 42
    # Matching reader levels end the arithmetic fallback without conflict.
    rows[3].update(visual_level=42, neural_level=None)
    assert project(rows)[3]['experimental_level']['status'] == 'single_reader'
    # Visible reader levels never accrue arithmetic samples.
    seen = [pair(i, 278125+i*400, visual_level=42, visual_status='available') for i in range(1, 5)]
    assert all(r['experimental_level']['status'] == 'single_reader' for r in project(seen))


def test_persistent_single_reader_conflict_is_bounded_then_readers_resume():
    rows = climbing()+[pair(i, 279325, visual_level=24, visual_status='available') for i in range(4, 7)]
    statuses = [r['experimental_level']['status'] for r in project(rows)]
    assert statuses == ['unavailable', 'unavailable', 'exp_derived', 'conflict', 'conflict', 'single_reader']


def test_percentage_only_frames_briefly_continue_but_cannot_start_or_change_level():
    rows = climbing()+[only(4, '78.15'), only(5, '78.16'), only(6, '78.17'), pair(7, 279325)]
    assert levels(rows) == [None, None, 42, 42, 42, None, 42]
    assert project(rows)[3]['experimental_level']['reason'] == 'short_exp_derived_context'
    assert levels([only(i, f'78.1{i}') for i in range(1, 6)]) == [None]*5
    # A percentage wrap is not a level-up; numeric pairs must re-establish a level.
    wrapped = climbing()+[only(4, '0.50'), only(5, '0.51')]
    assert levels(wrapped) == [None, None, 42, None, None]
    assert project(wrapped)[3]['experimental_level']['exp_derived_context']['reason'] == 'exp_derived_progression_contradiction'


def test_genuine_level_up_needs_fresh_confirmation_at_the_new_level():
    total = requirement(43)['to_next']
    after = [pair(i, 9000+(i-4)*500, display(9000+(i-4)*500, total)) for i in range(4, 7)]
    assert all(exp_derived(dict(exp=r['candidate']['exp'], percentage=r['candidate']['percentage']))['unique_level'] == 43
               for r in after)
    rows = climbing()+after
    assert levels(rows) == [None, None, 42, None, None, 43]
    assert level_events(project(rows)) == []


def test_one_surprising_self_consistent_pair_resets_instead_of_switching():
    # 74,059 -> 74,050 style digit errors stay undetectable within one level, but a
    # corrupted pair implying another unique level abstains and needs reconfirmation.
    total = requirement(7)['to_next']
    rows = climbing()+[pair(4, 300, display(300, total))]+climbing(5)
    assert exp_derived(dict(exp='300', percentage=display(300, total)))['unique_level'] == 7
    assert levels(rows) == [None, None, 42, None, None, None, 42]


@pytest.mark.parametrize('change', [
    dict(fresh_at_capture=False), dict(frame_sha256=f'{1:064x}'), dict(run_id='restart', event_id='restart:3'),
    dict(character_id=2), dict(source_identity='b'*64), dict(session_id=2), dict(crop_suspect=True),
    dict(received_at=(NOW+timedelta(seconds=400)).isoformat()), dict(hud_count=2)])
def test_stale_duplicate_restart_identity_or_gap_resets_the_chain(change):
    rows = climbing(count=4)
    rows[2].update(change)
    assert levels(rows)[2:] == [None, None]


def test_recent_reader_context_vetoes_a_different_derived_level():
    neural = dict(status='numeric_candidate', text='65', level=65, score=.96, preprocessing='neutral4')
    readers = [row(i, '45.13', raw_text='713,015[45.13%]', candidate=dict(exp='713015', percentage='45.13'),
                   status='diagnostic_pair', visual_level=65, neural_level=neural, frame_sha256=f'{i:064x}')
               for i in (1, 2)]
    rows = readers+[pair(i, 278125+i*400) for i in range(3, 8)]
    projected = project(rows)
    # Existing short reader carry first, then the reader-supported anchor keeps vetoing.
    assert [r['experimental_level']['status'] for r in projected[2:4]] == ['recent_context']*2
    assert [r['experimental_level']['value'] for r in projected[4:]] == [None]*3
    assert projected[4]['experimental_level']['exp_derived_context']['reason'] == 'recent_reader_level_disagrees'
    assert all(r['exp_validity']['whole_pair_rejected'] for r in projected[2:])


def test_incremental_state_matches_one_pass():
    rows = climbing()+[only(4, '78.15'), pair(5, 279325)]
    state = {}
    split = project(rows[:2], state=state)+project(rows[2:], state=state)
    assert [r['experimental_level'] for r in split] == [r['experimental_level'] for r in project(rows)]
