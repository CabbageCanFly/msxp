import importlib
from pathlib import Path

import pytest

from exp_tracker.shadow_grammar import MAX_EDITS, propose_full_exp


@pytest.mark.parametrize('raw,expected,edits', [
    ('485,273132.40%1', '485,273[32.40%]', 2),
    ('485,977132.45%]', '485,977[32.45%]', 1),
    ('489.090[32.65%1', '489,090[32.65%]', 2),
    ('497,141133.19%1', '497,141[33.19%]', 2),
    ('487.317132.53%1', '487,317[32.53%]', 3),
    ('1.234,567[12.34%1', '1,234,567[12.34%]', 2),
    ('123[0.00%1', '123[0.00%]', 1),
])
def test_bounded_edits_preserve_original_positions_and_numeric_characters(raw, expected, edits):
    result = propose_full_exp(raw)
    assert result['classification'] == 'unique_proposal'
    assert result['raw'] == raw and not result['trusted'] and not result['numerical_identity_verified']
    proposal = result['proposals'][0]
    assert proposal['interpretation'] == expected
    assert len(proposal['edits']) == edits <= MAX_EDITS
    rebuilt = list(raw)
    for edit in proposal['edits']:
        assert raw[edit['index']] == edit['old']
        assert edit['category'] in ('opening_bracket', 'closing_bracket', 'exp_grouping')
        assert edit['old'] in '1.' and edit['new'] in ('[', ']', ',')
        rebuilt[edit['index']] = edit['new']
    assert ''.join(rebuilt) == expected
    assert not proposal['trusted'] and proposal['image_verification'] == 'required'


@pytest.mark.parametrize('raw', ['123113.45%1', '170 57%1', '0.85%1', '[70.63%1',
    '689.,965[92.17%1', '1,23[32.40%1', '12.34[32.40%1', '485,273[32,40%1',
    '485,273[3240%1', '485,273[32.4%1', '485,273[32.400%1', '485,273[32.40',
    '485,273[32.401]', '485,273[100.00%1', '0[1.00%1', '9999999999999999999999[32.40%1',
    '1.234.567.890132.40%1', '485,273[3O.40%1', '485,273|32.40%1',
    '485,273I32.40%1', '485,273l32.40%1', '485,273[32.40%11',
    '3,862[32,97%]', '5,031[33,05%]', 'extra 485,273[32.40%1'])
def test_no_decimal_digits_missing_fields_or_other_lookalikes_reconstructed(raw):
    result = propose_full_exp(raw)
    assert result['classification'] == 'rejected' and result['proposals'] == []


@pytest.mark.parametrize('raw', [None, 123, '', '1'*161])
def test_bounded_missing_inputs(raw):
    assert propose_full_exp(raw)['classification'] == 'unavailable'


def test_old_experiment_and_unchanged_strict_parser_are_separate(monkeypatch):
    monkeypatch.syspath_prepend(str(Path('tools').resolve()))
    grammar = importlib.import_module('grammar_recovery')
    complete_pair = importlib.import_module('analyze_temporal_ocr').complete_pair
    assert grammar.propose('170 57%1')['proposals']  # Historical decimal hypotheses are not enabled here.
    assert not grammar.propose_full_exp('170 57%1')['proposals']
    for raw in ('485,273[32.40%]', '494.098[32.99%]', 'EXP: 123 (12.34%)',
                '0[0.00%]', ' 4,059 [25.17%] ', '0[1.00%]', '123[100.00%]',
                '9223372036854775808[25.00%]'):
        before = complete_pair(raw)
        result = propose_full_exp(raw)
        if before:
            assert result['classification'] == 'raw_strict' and not result['proposals']
            assert result['strict']['exp'] == str(before[0])
            assert result['strict']['percentage'] == f'{before[1]:.2f}'
        else:
            assert not result['strict']
        assert complete_pair(raw) == before


def test_syntax_does_not_verify_numeric_identity_or_clipping():
    for raw, retained in (('74,050[25.17%1', ('74050','25.17')),
                          ('4,059[25.17%1', ('4059','25.17')),
                          ('1,241199.82%]', ('1241','99.82'))):
        # Wrong digits, clipped groups or wrong percentage survive perfectly valid repairs.
        result = propose_full_exp(raw)
        assert result['classification'] == 'unique_proposal'
        reading = result['proposals'][0]['reading']
        assert (reading['exp'],reading['percentage']) == retained
        assert not result['numerical_identity_verified'] and result['source_complete'] is None
        vetoed = propose_full_exp(raw, source_complete=False)
        assert vetoed['classification'] == 'incomplete_or_clipped_field' and not vetoed['proposals']
    result = propose_full_exp('2345[92.74%]')
    assert result['classification'] == 'raw_strict' and not result['numerical_identity_verified']
    assert propose_full_exp('4,059[25.17%]', source_complete=False)['strict'] is not None


def test_repaired_values_cannot_enter_strict_percentage_progress(monkeypatch):
    monkeypatch.syspath_prepend(str(Path('tools').resolve()))
    strict_point = importlib.import_module('percentage_progress').strict_point
    raw = '485,273132.40%1'
    result = propose_full_exp(raw)
    assert result['proposals'] and strict_point(dict(neural=dict(text=raw), grammar_recovery=result))[0] is None
