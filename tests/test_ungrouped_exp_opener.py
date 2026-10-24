"""Below 1,000 EXP a '1' opener needs arithmetic at an independently read level."""
import pytest
from exp_tracker.character_automation import level_evidence
from exp_tracker.product import reading
from exp_tracker.shadow_grammar import interpret_exp
from tests.test_autonomous_characters import record
from tests.test_endpoint_pace import point, snapshot


def unreadable(text, level=40, **changes):
    current = point(1, 0, 192, '0.07', level=level)
    current.update(raw_text=text, candidate=None, status='malformed_or_unavailable', **changes)
    return current


@pytest.mark.parametrize('text', ['19210.07%]', '19210.07%1', '19210.07%)'])
def test_short_exp_after_level_up_is_one_hypothesis(text):
    proposal, = interpret_exp(text)['full_exp']['proposals']
    assert proposal['reading'] == dict(kind='full_exp_pair', exp='192', percentage='0.07')
    assert 'ungrouped_exp_opener' in [e['category'] for e in proposal['edits']]


def test_two_possible_openers_still_abstain():
    assert interpret_exp('11110.07%]')['full_exp']['classification'] == 'ambiguous'


def test_independent_level_that_fits_the_arithmetic_accepts_the_pair():
    value = reading(snapshot([unreadable('19210.07%)')], 0)['observations'][0])
    assert (value['exp'], value['percentage'], value['evidence']) == ('192', '0.07', 'grammar_recovered')


@pytest.mark.parametrize('changes', [dict(level=10), dict(visual_level=None, neural_level=None)], ids=['contradicting_level', 'no_level'])
def test_without_fitting_independent_level_it_abstains_as_before(changes):
    level = changes.pop('level', 40)
    row = snapshot([unreadable('19210.07%]', level, **changes)], 0)['observations'][0]
    assert reading(row) is None and row['exp_opener_unverified']
    assert row['exp_validity']['status'] != 'invalid'  # Ambiguous text, not a contradiction.


def test_unverified_pair_cannot_vouch_for_the_neural_level_that_would_verify_it():
    current = record(1, level=40)
    current.update(candidate=None, status='malformed_or_unavailable', neural=dict(text='19210.07%]'), visual_level=None,
                   neural_level=dict(status='numeric_candidate', text='40', level=40, score=.99, preprocessing='neutral4'))
    assert level_evidence(current) is None
    current['visual_level'] = 40
    assert level_evidence(current)['level'] == 40
