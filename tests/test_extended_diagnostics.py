"""Synthetic text diagnostics only: proposals are deliberately never trusted."""

import pytest

from exp_tracker.exp_requirements import community_table, requirement
from exp_tracker.models import Reading, reading_errors
from exp_tracker.shadow_grammar import interpret_exp, propose_full_exp
from exp_tracker.shadow_types import parse_percentage_only


@pytest.mark.parametrize('raw,full,percentage', [
    ('123,456|12.34%|', '123456', '12.34'),
    ('123.456|12.34%1', '123456', '12.34'),
    ('123,456112.34%1', '123456', '12.34'),
    ('3,862[32,97%]', None, '32.97'),
    ('5,031[33,05%]', None, '33.05'),
    ('12,,345[12.34%1', None, '12.34'),
    ('[70.63%1', None, '70.63'),
    ('|70.63%|', None, '70.63'),
])
def test_bounded_independent_percentage_recovery(raw, full, percentage):
    result = interpret_exp(raw)
    proposal = result['full_exp']['proposals']
    assert (proposal[0]['reading']['exp'] if proposal else None) == full
    only = result['percentage']['proposals'][0]
    assert result['percentage']['classification'] == 'unique_proposal'
    assert only['reading']['percentage'] == percentage
    assert parse_percentage_only(only['interpretation']) == only['reading']
    for field in ('full_exp', 'percentage'):
        for candidate in result[field]['proposals']:
            assert not candidate['trusted'] and not candidate['numerical_identity_verified']
            assert len(candidate['edits']) <= 4
            for edit in candidate['edits']:
                assert raw[edit['index']] == edit['old']
                assert edit['category'] in ('opening_bracket', 'closing_bracket', 'exp_grouping', 'percentage_decimal')


@pytest.mark.parametrize('raw', ['0.85%1', '170 57%1', '[12.3%1', '[12.345%1',
    '[12,3,4%1', '[101.00%1', '123I12.34%1', '12,345|12.34%|text',
    'text[12.34%1', '[12.34%[', '1.23[4.56%1[7.89%1', '[12.34]1', None, '', '1'*161])
def test_no_missing_digits_boundary_reconstruction_or_unsupported_lookalikes(raw):
    result = interpret_exp(raw)
    assert not result['full_exp']['proposals'] and not result['percentage']['proposals']


def test_clipped_exp_veto_does_not_discard_complete_percentage():
    result = interpret_exp('4,059[25.17%1', source_complete=False)
    assert result['full_exp']['classification'] == 'incomplete_or_clipped_field'
    assert result['percentage']['proposals'][0]['reading']['percentage'] == '25.17'
    # Text cannot detect this source clipping when review evidence is absent.
    assert interpret_exp('4,059[25.17%1')['full_exp']['classification'] == 'unique_proposal'


@pytest.mark.parametrize('raw', ['123,456[12.34%]', '123.456[12.34%]', '[70.51%]', '0[0.00%]'])
def test_strict_baseline_and_legacy_policy_are_unchanged(raw):
    result = interpret_exp(raw, source_complete=False)
    if raw.startswith('['):
        assert result['strict_percentage_only'] == parse_percentage_only(raw)
    else:
        assert result['strict_full'] == propose_full_exp(raw)['strict']
    assert result['full_exp']['classification'] == 'raw_strict'
    assert not result['full_exp']['proposals'] and not result['percentage']['proposals']
    assert propose_full_exp('123,456|12.34%|')['classification'] == 'rejected'


def test_grammar_cannot_detect_known_wrong_numbers_or_choose_ambiguous_pixels():
    for raw, exp, percentage in [('74,050[25.17%1', '74050', '25.17'),
                                  ('1,241199.82%]', '1241', '99.82'),
                                  ('496,738|33.18%1', '496738', '33.18')]:
        p = interpret_exp(raw)['full_exp']['proposals'][0]
        assert p['reading']['exp'] == exp and p['reading']['percentage'] == percentage
        assert p['numerical_identity_verified'] is False
    assert interpret_exp('2345[92.74%]')['strict_full']['exp'] == '2345'


@pytest.mark.parametrize('level,value,status', [(49,655200,'community_provisional'),
    (50,709716,'community_provisional'), (64,1497832,'community_provisional'),
    (99,None,'source_disagreement'), (100,None,'missing_requirement'), (200,None,'missing_requirement')])
def test_recognition_range_is_independent_of_table(level, value, status):
    lookup = requirement(level)
    assert lookup['status'] == status and lookup['to_next'] == value
    assert not lookup['authoritative'] and not lookup['trusted']
    assert not reading_errors(Reading(level, 100, 25.0))


def test_table_preserves_all_published_conflicts_and_explicit_missing_entries():
    data, sha = community_table()
    assert len(sha) == 64
    assert data['historical']['sha256'] == 'efd379d8010c99afe4a21d6a73b6873746865dfea7c60065cc562557cb72cb0a'
    assert data['disputed_to_next']['99'] == dict(meowdb=9482161548, quest=9692044)
    assert requirement(99)['to_next'] is None
    assert len(data['to_next']) == 89
    assert not data['build_applicability_verified']
    assert requirement(True)['status'] == requirement(201)['status'] == 'invalid_or_unavailable_level'


def test_new_shadow_default_is_portable_public_data_not_a_recognition_cap(monkeypatch):
    import importlib
    import json
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'tools'))
    shadow = importlib.import_module('shadow_capture')
    args = shadow.parser().parse_args(['--file', 'synthetic.mp4', '--output', 'private/new.jsonl'])
    assert args.requirements.is_file() and 'private' not in args.requirements.parts
    data = json.loads(args.requirements.read_text())
    levels = {int(k): v for k, v in data['to_next'].items()}
    result = shadow.level_evidence([485273, 32.40], 64, levels)
    assert result['hypotheses']['nearest_half_up']['levels'] == [64]
    assert result['relation'] == 'agreement_not_verification' and result['trusted'] is False
    assert shadow.level_evidence([100, 1.0], 200, levels)['relation'] == 'unsupported_visual_level'
    # This archived relation concerns table availability; visual level 200 remains valid.
    from exp_tracker.shadow_view import observation
    assert observation(dict(visual_level=200))['visual_level'] == 200
