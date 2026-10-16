"""Synthetic temporal diagnostics do not establish OCR correctness or change state."""

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def diagnostic(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'tools'))
    return importlib.import_module('analyze_temporal_ocr')


def row(i, text='10[20.00%]', *, seconds=None, level=2, missing=False):
    return dict(id=str(i), seconds=i if seconds is None else seconds, text=text,
                level=level, missing_crop=missing)


def test_repeats_are_one_correlated_episode(diagnostic):
    result = diagnostic.describe([row(i) for i in range(3)], 1)
    assert result['edge_counts'] == {'agreement':2}
    assert len(result['repeat_episodes']) == 1
    assert result['repeat_episodes'][0]['frames'] == 3


def test_missing_frame_is_not_filled_or_skipped_for_agreement(diagnostic):
    result = diagnostic.describe([row(0), row(1,None,missing=True), row(2)], 1)
    assert result['complete'] == 2 and result['unavailable'] == 1
    assert result['edge_counts'] == {'unavailable':2}
    assert result['repeat_episodes'] == []
    assert result['unavailable_with_complete_neighbor'] == ['1']


def test_malformed_punctuation_stays_unavailable(diagnostic):
    result = diagnostic.describe([row(0,'10[20.00%1'), row(1,'10[20.00%')], 1)
    assert result['complete'] == 0 and result['malformed'] == 2
    assert diagnostic.complete_pair('0[0.00%]') == [0,0]


def test_changes_are_differences_not_automatically_errors(diagnostic):
    result = diagnostic.describe([row(0),row(1,'9000000[90.00%]')], 1)
    assert result['edge_counts'] == {'different':1}
    assert result['edges'][0]['level_relation'] == 'same'


def test_level_change_splits_identical_numeric_episodes(diagnostic):
    result = diagnostic.describe([row(0,'0[0.00%]',level=2),row(1,'0[0.00%]',level=3)], 1)
    assert len(result['episodes']) == 2 and not result['repeat_episodes']
    assert result['edges'][0]['level_relation'] == 'changed'


def test_timestamp_gap_does_not_establish_adjacency(diagnostic):
    result = diagnostic.describe([row(0),row(1,seconds=3)], 1)
    assert result['edges'] == [] and not result['repeat_episodes']


def test_repeated_wrong_number_cannot_be_detected_by_agreement(diagnostic):
    # Synthetic source intent is 1059; neither temporal nor crop agreement knows it.
    result = diagnostic.describe([row(0,'1050[25.00%]'),row(1,'1050[25.00%]')], 1)
    assert result['edge_counts'] == {'agreement':1}
    assert result['repeat_episodes'][0]['pair'] == [1050,25]


def test_unknown_level_is_retained_as_unknown(diagnostic):
    result = diagnostic.describe([row(0,level=None),row(1)], 1)
    assert result['edges'][0]['level_relation'] == 'unknown'


def inputs():
    items = [dict(id='0',seconds=0,window='a'),dict(id='1',seconds=1,window='b')]
    locations = [dict(id=e['id'],seconds=e['seconds'],level=None) for e in items]
    def variants(padding):
        return dict(records=[dict(id=e['id'],seconds=e['seconds'],text='10[20.00%]',
            missing_crop=False,mode='line_recognize',scale=2,padding_pixels=padding) for e in items])
    return dict(examples=items),dict(records=locations),variants(0),variants(2)


def test_windows_are_not_joined_and_conflicts_have_no_winner(diagnostic):
    manifest,location,zero,padded = inputs()
    padded['records'][0]['text'] = '11[20.00%]'
    result = diagnostic.analyze(manifest,location,zero,padded)
    assert result['trusted'] is False
    assert result['windows']['a']['crop_comparison_counts'] == {'contradiction':1}
    for w in result['windows'].values():
        assert w['padding']['2']['edges'] == []


@pytest.mark.parametrize('fault',['duplicate','missing','time','variant'])
def test_mismatched_evidence_fails_explicitly(diagnostic, fault):
    manifest,location,zero,padded = inputs()
    if fault == 'duplicate': padded['records'].append(padded['records'][0])
    elif fault == 'missing': padded['records'].pop()
    elif fault == 'time': padded['records'][0]['seconds'] = 4
    else: padded['records'][0]['padding_pixels'] = 4
    with pytest.raises(ValueError):
        diagnostic.analyze(manifest,location,zero,padded)
