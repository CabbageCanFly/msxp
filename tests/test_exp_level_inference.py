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
    return row(index, pct, **{**dict(visual_level=None, visual_status='unavailable', frame_sha256=f'{index:064x}'), **changes})


def gap(index, **changes):
    return row(index, raw_text=None, percentage_only_candidate=None, status='unavailable', reasons=['missing_hud'],
        hud_count=0, fresh_at_capture=False, visual_level=None, visual_status='not_run', **changes)


def neural(level, score=.96, preprocessing='neutral4'):
    return dict(status='numeric_candidate', text=str(level), level=level, score=score, preprocessing=preprocessing)


def evidence(rows, **kwargs):
    return [r['experimental_level'] for r in project(rows, **kwargs)]


def levels(rows, **kwargs):
    return [e['value'] for e in evidence(rows, **kwargs)]


def statuses(rows):
    return [e['status'] for e in evidence(rows)]


def climbing(start=1, count=3, exp=278125, step=400):
    return [pair(start+i, exp+i*step) for i in range(count)]


def near_top(start=1):
    """Level 42 confirmed near 99%, then percentage-only readings through a level-up."""
    rows = climbing(start, exp=352000)
    return rows+[only(start+3+i, pct) for i, pct in enumerate(('98.90', '99.40', '99.92'))]


AFTER_WRAP = ('0.18', '0.45', '0.81', '1.16')


def wrapped(start=1):
    rows = near_top(start)
    return rows+[only(start+6+i, pct) for i, pct in enumerate(AFTER_WRAP)]


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
    single = exp_derived(dict(exp='74050', percentage='25.17'))
    assert single['hypotheses'] == dict(nearest_half_up=[40], truncate=[]) and single['unique_level'] == 40
    assert levels([pair(i, 100, '0.02') for i in range(1, 5)]) == [None]*4


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
    mismatch = [pair(i, 278125+i*400, candidate=dict(exp='278125', percentage='77.92')) for i in range(1, 4)]
    repaired = [pair(i, 0, raw_text=f'{278125+i*400:,}[{display(278125+i*400).replace(".", ",")}%]', candidate=None)
                for i in range(1, 4)]
    for rows in (mismatch, repaired):
        projected = project(rows)
        assert [r['experimental_level']['value'] for r in projected] == [None]*3
        assert all('exp_derived' not in r['experimental_level'] for r in projected)
    assert levels([pair(i, 278125+i*400, candidate_invalid=True) for i in range(1, 4)]) == [None]*3


def test_obscured_level_needs_three_fresh_rising_pairs_and_stays_labeled():
    rows = climbing()
    projected = project(rows)
    assert [r['experimental_level']['value'] for r in projected] == [None, None, 42]
    pending, confirmed = projected[1]['experimental_level'], projected[2]['experimental_level']
    assert pending['status'] == 'unavailable' and pending['level_context']['reason'] == 'exp_derived_confirmation_pending'
    assert pending['level_context']['candidate_level'] == 42 and pending['level_context']['last_supported_level'] is None
    assert confirmed['status'] == 'exp_derived' and confirmed['reason'] == 'repeated_unique_exp_inference'
    assert confirmed['visual'] is None and confirmed['neural'] is None and not confirmed['trusted']
    assert confirmed['strict_window_eligible'] is False
    context = confirmed['level_context']
    assert context['sample_event_ids'] == ['run:1', 'run:2', 'run:3'] and context['source'] == 'exp_derived'
    assert context['last_supported_level'] == 42 and context['confirmed_at'] == rows[2]['received_at']
    assert not context['verified'] and not context['trusted']
    # Agreement with the pairs the level came from is circular, not verification.
    assert projected[2]['exp_validity']['status'] == 'indeterminate'
    assert projected[2]['exp_validity']['reason'] == 'level_derived_from_exp_pairs'
    point, reason = percentage_point(projected[2])
    assert reason is None and point['level'] == 42
    assert reading(projected[2])['exp'] == '278925' and reading(projected[2])['level']['status'] == 'exp_derived'
    assert level_events(projected) == []
    assert progress(rows, now=NOW+timedelta(seconds=30))['current_segment']['level'] == 42


@pytest.mark.parametrize('rows', [
    [pair(1, 278125)],
    [pair(1, 278125), pair(2, 278525)],
    [pair(i, 278125) for i in range(1, 5)],                                 # no EXP progression
    [pair(i, 278125+i*400, frame_sha256=None) for i in range(1, 5)],         # no frame evidence
    [only(i, f'78.1{i}') for i in range(1, 6)],                             # percentages never identify
])
def test_single_static_unhashed_or_percentage_only_readings_are_not_level_evidence(rows):
    assert all(value is None for value in levels(rows))


def test_level_is_retained_across_prolonged_percentage_only_tracking():
    rows = climbing()+[only(i, f'{78.15+(i-4)*0.01:.2f}') for i in range(4, 244)]  # one hour
    projected = project(rows)
    retained = [r['experimental_level'] for r in projected[3:]]
    assert {e['value'] for e in retained} == {42} and {e['status'] for e in retained} == {'retained_level'}
    last = retained[-1]
    assert last['reason'] == 'retained_last_supported_level' and last['strict_window_eligible'] is False
    context = last['level_context']
    assert context['last_supported_level'] == 42 and context['supported_at'] == rows[2]['received_at']
    assert context['unsupported_frames'] == 240 and context['support_age_seconds'] == 3600
    assert context['continuity'] == 'ordered' and not context['verified']
    segment = progress(rows, now=NOW+timedelta(seconds=3660))['current_segment']
    assert segment['level'] == 42 and segment['readings'] == 241
    # A fresh unique pair renews support without restarting confirmation.
    renewed = evidence(rows+[pair(244, 287500)])[-1]
    assert renewed['status'] == 'exp_derived' and renewed['level_context']['unsupported_frames'] == 0


def test_no_evidence_frames_hold_context_but_breaks_and_identity_changes_reset():
    held = climbing()+[only(4, '78.16', frame_sha256=f'{3:064x}'), gap(5), only(6, '78.17', fresh_at_capture=False),
                       only(7, '78.18', crop_suspect=True), only(8, '78.19')]
    assert levels(held) == [None, None, 42, None, None, None, None, 42]
    assert evidence(held)[-1]['status'] == 'retained_level'
    for change in (dict(run_id='restart', event_id='restart:5'), dict(character_id=2), dict(source_identity='b'*64),
                   dict(session_id=2), dict(hud_count=2), dict(timing_mode='simulated'),
                   dict(received_at=(NOW+timedelta(seconds=400)).isoformat()), dict(index=9)):
        rows = climbing()+[only(4, '78.16'), only(5, '78.17'), only(6, '78.18')]
        rows[4].update(change)
        # Later frames keep the changed identity, so only fresh evidence could rebuild context.
        rows[5].update({k: v for k, v in change.items() if k in ('run_id', 'character_id', 'source_identity', 'session_id')})
        if 'event_id' in change: rows[5]['event_id'] = 'restart:6'
        assert levels(rows)[4:] == [None, None], change
    # Fresh evidence is still needed within 120s, even across held gaps.
    stale = climbing()+[gap(i) for i in range(4, 14)]+[only(14, '78.16')]
    assert levels(stale)[-1] is None


def test_percentage_decrease_retains_level_but_unexplained_drop_does_not():
    loss = evidence(climbing()+[only(4, '78.15'), only(5, '72.00'), only(6, '72.05')])
    assert [e['value'] for e in loss[3:]] == [42, 42, 42]
    assert loss[4]['reason'] == 'retained_after_percentage_decrease'
    assert loss[5]['level_context']['continuity'] == 'percentage_decrease_observed'
    # Level-ups only follow a near-100% to near-0% display; other large drops are unknown.
    assert levels(climbing()+[only(4, '40.00'), only(5, '40.05')])[3:] == [None, None]
    assert levels(climbing()+[only(4, '0.50'), only(5, '0.51')])[3:] == [None, None]


def test_wrap_becomes_possible_then_provisional_level_up_without_rewriting_history():
    rows = wrapped()
    projected = project(rows)
    seen = [(r['experimental_level']['value'], r['experimental_level']['status']) for r in projected[3:]]
    assert seen == [(42, 'retained_level')]*3+[(None, 'possible_level_up'), (None, 'possible_level_up'),
                                              (None, 'possible_level_up'), (43, 'provisional_level_up')]
    possible = projected[6]['experimental_level']['level_context']
    assert possible['last_supported_level'] == 42
    assert {k: possible['transition'][k] for k in ('from_level', 'to_level', 'phase', 'before_bp', 'after_bp')} == dict(
        from_level=42, to_level=43, phase='possible', before_bp=9992, after_bp=18)
    provisional = projected[-1]['experimental_level']['level_context']
    assert provisional['last_supported_level'] == 42 and provisional['transition']['phase'] == 'provisional'
    assert [s['event_id'] for s in provisional['transition']['samples']] == ['run:8', 'run:9', 'run:10']
    assert [r['raw_text'] for r in projected] == [r['raw_text'] for r in rows]
    events = level_events(projected)
    assert [(e['kind'], e['level'], e['previous_level'], e['status']) for e in events] == [
        ('inferred_level_up', 43, 42, 'provisional')]
    # Possible-transition readings are not assigned to either level; nothing spans the boundary.
    assert all(percentage_point(r)[0]['level'] is None for r in projected[6:9])
    segments = progress(rows, now=NOW+timedelta(seconds=160))['segments']
    assert {s['level'] for s in segments} == {42, 43} and all(s['level'] == 42 or s['start_percentage'] == '1.16' for s in segments)


def test_unique_post_wrap_pair_or_reader_corroborates_the_new_level():
    total = requirement(43)['to_next']
    corroborated = evidence(wrapped()+[pair(11, 5000, display(5000, total))])
    final = corroborated[-1]
    assert (final['value'], final['status'], final['reason']) == (43, 'exp_derived', 'level_up_corroborated_by_exp_pair')
    last = final['level_context']['last_transition']
    assert last['phase'] == 'corroborated' and last['corroborated_by'] == 'unique_exp_pair' and last['from_level'] == 42
    assert final['level_context']['last_supported_level'] == 43
    events = level_events(project(wrapped()+[pair(11, 5000, display(5000, total))]))
    assert [(e['level'], e['status']) for e in events] == [(43, 'corroborated')]
    # A pair right at the wrap corroborates immediately; percentages alone never would.
    direct = evidence(near_top()+[pair(7, 700, display(700, total))])
    assert direct[-1]['value'] == 43 and direct[-1]['level_context']['last_transition']['phase'] == 'corroborated'
    # A reader matching the hypothesis resolves it; one matching the old level abandons it.
    reader = evidence(near_top()+[only(7, '0.18'), only(8, '0.45', visual_level=43, visual_status='available')])
    assert reader[-1]['status'] == 'single_reader' and reader[-1]['value'] == 43
    old = wrapped()[:8]+[only(9, '99.95', visual_level=42, visual_status='available'), only(10, '99.96')]
    resolved = evidence(old)
    assert resolved[-1]['value'] == 42 and resolved[-1]['level_context']['last_transition']['phase'] == 'abandoned'


def test_misread_wrap_or_contradicting_progress_abandons_the_hypothesis():
    misread = near_top()+[only(7, '0.18'), only(8, '99.95'), only(9, '99.97')]
    projected = project(misread)
    assert [r['experimental_level']['value'] for r in projected[6:]] == [None, 42, 42]
    last = projected[-1]['experimental_level']['level_context']['last_transition']
    assert last['phase'] == 'abandoned' and last['abandoned_reason'] == 'percentage_returned_to_previous_level'
    assert level_events(projected) == []
    for later in (only(8, '50.00'), only(8, '0.10'), pair(8, 278125)):
        assert levels(near_top()+[only(7, '0.18'), later])[-1] is None
    # A provisional level that is then contradicted leaves no inferred marker.
    abandoned = project(wrapped()+[only(11, '99.99'), only(12, '40.00')])
    assert abandoned[-1]['experimental_level']['value'] is None and level_events(abandoned) == []


def test_one_wrap_is_one_level_and_unsupported_next_levels_stay_possible():
    # Big jumps after the wrap are not forward progress, so no second level-up from noise.
    assert levels(wrapped()+[only(11, '96.00'), only(12, '0.20')])[-2:] == [None, None]
    # Level 89 itself is never arithmetic evidence: an unpublished level-90 total could fit.
    t89 = requirement(89)['to_next']
    assert exp_derived(dict(exp=str(t89//2), percentage=display(t89//2, t89)))['status'] == 'outside_supported_coverage'
    t88 = requirement(88)['to_next']
    top = [pair(i, t88-60000+i*1000, display(t88-60000+i*1000, t88)) for i in range(1, 4)]
    up = [only(4, '99.50'), only(5, '99.90')]+[only(6+i, pct) for i, pct in enumerate(AFTER_WRAP)]
    # A reader can corroborate 89; the next wrap stays only possible: 90's requirement is disputed.
    again = [only(10, '1.20', visual_level=89, visual_status='available'), only(11, '99.60'), only(12, '99.90')]
    again += [only(13+i, pct) for i, pct in enumerate(AFTER_WRAP+('1.50', '2.00'))]
    hidden = evidence(top+up+again)
    assert hidden[2]['value'] == 88 and hidden[8]['value'] == 89 and hidden[8]['status'] == 'provisional_level_up'
    assert hidden[9]['level_context']['last_transition']['corroborated_by'] == 'reader_single_reader'
    assert {e['status'] for e in hidden[12:]} == {'possible_level_up'} and all(e['value'] is None for e in hidden[12:])


def test_reader_levels_take_precedence_and_disagreement_is_preserved():
    rows = climbing()+[pair(4, 279325, visual_level=24, visual_status='available')]
    conflict = evidence(rows)[3]
    assert conflict['value'] is None and conflict['status'] == 'conflict'
    assert conflict['reason'] == 'reader_conflicts_exp_derived_level'
    assert conflict['exp_derived_disagreement']['level_context']['last_supported_level'] == 42
    assert conflict['exp_derived_disagreement']['reader_level'] == 24
    rows[3].update(neural_level=neural(24))
    agreed = evidence(rows)[3]
    assert agreed['value'] == 24 and agreed['status'] == 'agreement'
    assert agreed['exp_derived_disagreement']['resolution'] == 'readers_agree_on_other_level'
    rows[3].update(visual_level=42, neural_level=None)
    matched = evidence(rows+[only(5, '78.40')])
    assert matched[3]['status'] == 'single_reader'
    assert matched[4]['status'] == 'retained_level' and matched[4]['level_context']['source'] == 'reader_single_reader'
    seen = [pair(i, 278125+i*400, visual_level=42, visual_status='available') for i in range(1, 5)]
    assert all(e['status'] == 'single_reader' and 'level_context' not in e for e in evidence(seen))


def test_persistent_single_reader_conflict_is_preserved_until_evidence_resolves_it():
    rows = climbing()+[pair(i, 279325+i, visual_level=24, visual_status='available') for i in range(4, 8)]+[pair(8, 279800)]
    assert statuses(rows) == ['unavailable']*2+['exp_derived']+['conflict']*4+['exp_derived']


def test_bogus_obscured_hud_reader_claims_do_not_block_arithmetic_but_real_ones_conflict():
    # Unconfirmed or invalid neural numbers (e.g. read from an overlay) stay recorded only.
    for claim in (neural(7, score=.42), neural(7, preprocessing='rgb4'), dict(status='numeric_candidate', text='7?', level=7, score=.99)):
        rows = [pair(i, 278125+i*400, neural_level=claim) for i in range(1, 4)]
        projected = evidence(rows)
        assert projected[-1]['value'] == 42 and projected[-1]['status'] == 'exp_derived'
        assert projected[-1]['unselected_reader_claims'] == dict(neural=7)
    # A repeated, seeded neural level is a meaningful contradiction, not something to override.
    repeated = climbing()+[only(i, f'78.2{i}', neural_level=neural(24)) for i in range(4, 7)]
    assert statuses(repeated)[3:] == ['retained_level', 'retained_level', 'conflict']
    # ...unless arithmetic contradicts the neural number, which keeps it unconfirmed.
    arithmetic = climbing()+[pair(i, 279325+i, neural_level=neural(24)) for i in range(4, 7)]
    assert statuses(arithmetic)[3:] == ['exp_derived']*3


def test_competing_unique_level_conflicts_once_and_replaces_only_after_its_own_chain():
    total = requirement(7)['to_next']
    rows = climbing()+[pair(4, 300, display(300, total))]+climbing(5)
    assert exp_derived(dict(exp='300', percentage=display(300, total)))['unique_level'] == 7
    projected = evidence(rows)
    assert [e['value'] for e in projected] == [None, None, 42, None, 42, 42, 42]
    assert projected[3]['status'] == 'conflict' and projected[3]['reason'] == 'competing_exp_derived_level'
    replaced = evidence(climbing()+[pair(4+i, 300+i*10, display(300+i*10, total)) for i in range(3)])
    assert [e['value'] for e in replaced[3:]] == [None, None, 7]
    assert replaced[-1]['reason'] == 'exp_derived_level_replaced' and replaced[-1]['level_context']['replaced_level'] == 42


def test_contradicting_pair_withholds_its_integer_and_keeps_the_percentage():
    projected = project(climbing()+[pair(4, 2345, '78.20')])
    assert projected[3]['experimental_level']['value'] == 42
    assert projected[3]['exp_validity']['status'] == 'invalid'
    assert reading(projected[3])['exp'] is None and reading(projected[3])['percentage'] == '78.20'


def test_recent_reader_context_vetoes_a_different_derived_level():
    readers = [row(i, '45.13', raw_text='713,015[45.13%]', candidate=dict(exp='713015', percentage='45.13'),
                   status='diagnostic_pair', visual_level=65, neural_level=neural(65), frame_sha256=f'{i:064x}')
               for i in (1, 2)]
    projected = project(readers+[pair(i, 278125+i*400) for i in range(3, 8)])
    assert [r['experimental_level']['status'] for r in projected[2:4]] == ['recent_context']*2
    assert [r['experimental_level']['value'] for r in projected[4:]] == [None]*3
    assert projected[4]['experimental_level']['level_context']['reason'] == 'recent_reader_level_disagrees'
    assert all(r['exp_validity']['whole_pair_rejected'] for r in projected[2:])


def test_incremental_state_matches_one_pass():
    rows = wrapped()+[gap(11), only(12, '1.20')]
    for cut in (2, 6, 8, 11):
        state = {}
        split = project(rows[:cut], state=state)+project(rows[cut:], state=state)
        assert [r['experimental_level'] for r in split] == [r['experimental_level'] for r in project(rows)]
