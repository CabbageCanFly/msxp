"""An overlay over the EXP field's end hides '%]' (or half of '%', read as a digit): arithmetic at an
independently read level must accept the pair, as for an ungrouped opener."""
import pytest
from exp_tracker.product import reading
from exp_tracker.shadow_grammar import interpret_exp
from tests.test_endpoint_pace import point, snapshot


def covered(text, level=40, **changes):
    current = point(1, 0, 150000, '50.98', level=level)  # 150,000 / 294,216 at level 40.
    current.update(raw_text=text, candidate=None, status='malformed_or_unavailable', **changes)
    return current


@pytest.mark.parametrize('text', ['150,000[50.982', '150,000[50.98', '150.000[50.982'])
def test_covered_percent_is_one_hypothesis_needing_level_arithmetic(text):
    proposal, = interpret_exp(text)['full_exp']['proposals']
    assert proposal['reading'] == dict(kind='full_exp_pair', exp='150000', percentage='50.98')
    assert 'covered_percent_symbol' in [e['category'] for e in proposal['edits']]


@pytest.mark.parametrize('text', ['150,000[50.9', '150,000[50.9822', '[50.982', '1,50,00[50.982'])
def test_missing_digits_or_broken_grouping_still_reject(text):
    assert interpret_exp(text)['full_exp']['classification'] == 'rejected'


def test_independent_level_that_fits_the_arithmetic_accepts_the_pair():
    value = reading(snapshot([covered('150,000[50.982')], 0)['observations'][0])
    assert (value['exp'], value['percentage'], value['evidence']) == ('150000', '50.98', 'grammar_recovered')


@pytest.mark.parametrize('text,changes', [('150,000[50.982', dict(level=10)),
    ('150,000[50.982', dict(visual_level=None, neural_level=None)), ('150,000[50.912', {})],
    ids=['contradicting_level', 'no_level', 'misread_digit'])
def test_without_fitting_independent_level_it_abstains(text, changes):
    level = changes.pop('level', 40)
    row = snapshot([covered(text, level, **changes)], 0)['observations'][0]
    assert reading(row) is None and row['exp_opener_unverified']
