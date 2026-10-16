"""Synthetic timeline checks; no private images or benchmark answers."""

import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def audit(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'tools'))
    return importlib.import_module('audit_timeline')


def record(seconds, *, level=2, exp=10, percentage=5, status='correct'):
    return dict(id=f'synthetic/{seconds}', seconds=seconds,
                expected=dict(level=level, current_exp=exp, percentage=percentage),
                metrics={k: status for k in ('complete_exp', 'complete_tesseract', 'complete_pixel')})


def test_chronology_gaps_and_unavailable_are_distinct(audit):
    rows = [record(0), record(1, status='unavailable'), record(2, status='incorrect'), record(121)]
    result = audit.summary(rows, 'complete_exp')
    assert result['counts'] == dict(correct=2, incorrect=1, unavailable=1)
    assert result['correct_seconds'] == [0, 121]
    assert result['incorrect_seconds'] == [2]
    assert result['unavailable_seconds'] == [1]
    assert result['gaps'][0]['seconds'] == 121


def test_recoveries_grouped_but_losses_preserved(audit):
    old = [record(0), record(1, status='unavailable'), record(1.25, status='unavailable'),
           record(10, status='unavailable'), record(11, level=3, status='unavailable')]
    new = [record(0, status='unavailable'), record(1), record(1.25), record(10), record(11, level=3)]
    result = audit.compare(old, new, 'complete_exp')
    assert result['episodes_5s'] == [[1, 1.25], [10], [11]]
    assert result['lost'] == [0]
    assert result['recovered'][0]['previous'] == 0
    assert result['recovered'][0]['next'] is None


@pytest.mark.parametrize('end,level,exp,percentage,reason', [
    (120, 2, 1000000, 95, 'same_level_gain'),
    (120.25, 2, 20, 10, 'gap_requires_new_baseline'),
    (100, 3, 20, 10, 'level_change_requires_confirmation'),
    (100, 2, 9, 4, 'reset_loss_or_character_switch'),
    (100, 2, 10, 6, 'unchanged_exp_with_changed_percentage'),
])
def test_conditional_check_uses_existing_guard(audit, end, level, exp, percentage, reason):
    rows = [record(0), record(30, status='unavailable'),
            record(end, level=level, exp=exp, percentage=percentage)]
    result = audit.conditional_intervals(rows, 'complete_pixel')
    # A labeled decrease is deliberately flagged even when the endpoints are readable.
    expected = 'intervening_contrary_evidence' if exp < 10 else reason
    assert result[0]['reason'] == expected
    assert result[0]['missing_samples'] == 1
    with pytest.raises(ValueError, match='recognized level'):
        audit.conditional_intervals(rows, 'complete_exp')


@pytest.mark.parametrize('middle', [record(30, level=3, status='unavailable'),
                                  record(30, exp=1, percentage=1, status='unavailable'),
                                  record(30, status='incorrect')])
def test_contrary_evidence_prevents_endpoint_only_bridge_claim(audit, middle):
    result = audit.conditional_intervals([record(0), middle, record(60, exp=20, percentage=10)],
                                         'complete_pixel')
    assert result[0]['status'] == 'hard_break'
    assert result[0]['gained_exp'] is None


def test_transition_brackets_come_from_labels_not_correct_readings(audit):
    rows = [record(level * 10, level=level, status='correct' if level != 3 else 'unavailable')
            for level in range(1, 11)]
    result = audit.transitions(rows, 'complete_exp', {r['id']: r['expected'] | dict(seconds=r['seconds']) for r in rows})
    assert result[1]['label_bracket'] == [20, 30]
    assert result[1]['first_new_correct'] is None


def test_cached_outputs_require_frozen_inputs_and_matching_scores(audit, tmp_path):
    row = record(0)
    row['result'] = dict(status='candidate', exp=10, percentage=5)
    levels = {row['id']: dict(tesseract=2, pixel=2)}
    row['metrics'] = audit.score(row['result'], row['expected'], levels[row['id']])
    examples = {row['id']: row['expected'] | dict(seconds=0)}
    path = tmp_path / 'saved.json'
    data = dict(hashes=dict(manifest='labels', levels='levels'), records=[row])
    path.write_text(json.dumps(data))
    assert audit.load_records(path, examples, levels, 'labels', 'levels') == [row]
    with pytest.raises(ValueError, match='hash mismatch'):
        audit.load_records(path, examples, levels, 'changed', 'levels')
    data['records'][0]['metrics']['complete_pixel'] = 'unavailable'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='score mismatch'):
        audit.load_records(path, examples, levels, 'labels', 'levels')
    data['records'].append(row)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='duplicate or missing'):
        audit.load_records(path, examples, levels, 'labels', 'levels')
