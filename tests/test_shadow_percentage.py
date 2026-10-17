"""Percentage-only diagnostics never become production EXP Reading values."""
import importlib
from pathlib import Path

import pytest

from exp_tracker.parsing import parse_exp
from exp_tracker.shadow_types import parse_percentage_only, partial_percentage
from exp_tracker.shadow_view import observation


@pytest.mark.parametrize('text,bp', [('[70.51%]',7051),('[0.00%]',0),('[99.99%]',9999),
                                  ('[100.00%]',10000),('  [70.51%]\n',7051)])
def test_whole_percentage_only_field(text,bp):
    result=parse_percentage_only(text)
    assert result['kind']=='percentage_only' and result['percentage_bp']==bp
    assert not result['trusted'] and 'exp' not in result
    assert parse_exp(text) is None


@pytest.mark.parametrize('text', ['0.85%1','[70.63%1','170 57%1','70.51%','[70.51%',
    '70.51%]','1[70.51%]','[7 0.51%]','[70.5%]','[70.510%]','[100.01%]','[-1.00%]',
    '[７０.５１%]','[70.51%]1','[70.51%][70.52%]','EXP[70.51%]','(70.51%)',None,51])
def test_unknown_digits_and_boundaries_never_repaired(text):
    assert parse_percentage_only(text) is None


def test_existing_full_parser_stays_separate_and_unchanged():
    assert parse_exp('1,234[70.51%]') == (1234,70.51)
    assert parse_percentage_only('1,234[70.51%]') is None
    assert partial_percentage(70.51)['complete_observation'] is False
    for value in (float('nan'),float('inf'),True,'70.51',70.511):
        assert partial_percentage(value) is None


def test_legacy_viewer_parses_only_whole_percentage_and_keeps_exp_missing():
    row=observation(dict(status='malformed_or_unavailable',candidate=None,neural={'text':'[70.51%]'},
                         parsed_diagnostic={'percentage':70.51}))
    assert row['candidate'] is None and row['diagnostic_type']=='percentage_only'
    assert row['percentage_only_candidate']['percentage']=='70.51'
    assert row['percentage_only_origin']=='legacy_raw_parse'
    assert row['partial_percentage_evidence'] is None


def test_contradictory_percentage_candidate_is_not_repaired_or_trusted():
    row=observation(dict(candidate=None,neural={'text':'[70.51%]'},
        percentage_only_candidate=parse_percentage_only('[71.51%]')))
    assert row['percentage_only_candidate'] is None and row['percentage_only_invalid']
    assert row['candidate'] is None and not row['trusted']


def test_malformed_full_field_partial_evidence_never_becomes_observation():
    row=observation(dict(candidate=None,neural={'text':'689.,965[92.17%]'},
                         parsed_diagnostic={'percentage':92.17}))
    assert row['percentage_only_candidate'] is None and row['candidate'] is None
    assert row['partial_percentage_evidence']['percentage']=='92.17'
    assert row['partial_percentage_evidence']['complete_observation'] is False


def test_shadow_capture_distinct_type_and_no_absolute_arithmetic(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'tools'))
    shadow=importlib.import_module('shadow_capture')
    from exp_tracker.models import Region
    from exp_tracker.video import Frame
    from io import BytesIO
    from PIL import Image
    payload=BytesIO(); Image.new('RGB',(100,100),'black').save(payload,format='PNG')
    frame=Frame(payload.getvalue(),1,100,'2026-01-01T00:00:00Z')
    regions=dict(regions={'exp':Region(.1,.1,.8,.4),'level':Region(.1,.5,.4,.8)})
    result=shadow.analyze(frame,{1:15},lambda image:{'text':'[70.51%]'},clock=lambda:101,
        locator=lambda image:[regions],read_level=lambda image:(63,[]))
    assert result['status']=='diagnostic_percentage_only' and result['diagnostic_type']=='percentage_only'
    assert result['candidate'] is None and result['percentage_only_candidate']['percentage_bp']==7051
    assert result['level_evidence']['hypotheses']['nearest_half_up']['status']=='unavailable'
    assert not result['trusted'] and result['current']
