from copy import deepcopy
from datetime import timedelta
import json

import pytest

from exp_tracker.diagnostic_evidence import full_reading
from exp_tracker.diagnostic_progress import percentage_point
from exp_tracker.product import reading
from exp_tracker.shadow_view import observation
from tests.test_product import NOW, append, get, tracking


@pytest.mark.parametrize('text,candidate', [
    ('123,456[25.00%]', [123456, 25.0]),
    ('[25.00%]', None),
    ('[25.00%)', None),
    ('123,456[25.00%1', None),
])
@pytest.mark.parametrize('score,eligible', [(.84999, False), (.85, True), (.99, True)])
def test_exp_score_gates_strict_and_recovered_readings_without_losing_evidence(text, candidate, score, eligible):
    raw = dict(neural=dict(text=text, raw=dict(txts=[text], scores=[score])), candidate=candidate,
               visual_level=64)
    original = deepcopy(raw)
    row = observation(raw)
    assert row['exp_ocr_eligible'] is eligible and row['exp_ocr_score'] == score
    assert row['raw_text'] == text and raw == original
    point, reason = percentage_point(row)
    assert (point is not None) is eligible
    if not eligible:
        assert reason == 'exp_ocr_score_below_threshold'
        assert full_reading(row) is None and reading(row) is None
    elif candidate or text.startswith('123'):
        assert full_reading(row) is not None


@pytest.mark.parametrize('scores', [[], [None], [True], [-.1], [1.1], [float('nan')], [.99, .99], None, '0.99'])
def test_invalid_supplied_exp_scores_cannot_bypass_gate(scores):
    row = observation(dict(neural=dict(text='[25.00%]', raw=dict(scores=scores))))
    assert row['exp_ocr_eligible'] is False
    assert percentage_point(row) == (None, 'exp_ocr_score_below_threshold')


def test_legacy_logs_without_exp_scores_keep_existing_readings():
    row = observation(dict(neural=dict(text='[25.00%]')))
    assert row['exp_ocr_score'] is None and row['exp_ocr_eligible'] is True
    assert percentage_point(row)[0]['percentage'] == '25.00'


def test_low_score_keeps_last_reading_and_cannot_seed_history_spike(tracking):
    _, store, diagnostic = tracking
    def scored(index, text, score):
        append(diagnostic, index, text, neural=dict(text=text, raw=dict(txts=[text], scores=[score])))
    scored(1, '[67.51%)', .84805)
    assert get(diagnostic, 0)['reading'] is None
    scored(2, '[87.56%]', .95)
    assert get(diagnostic, 15)['reading']['percentage'] == '87.56'
    scored(3, '[12.00%]', .84)
    assert get(diagnostic, 30)['reading']['percentage'] == '87.56'
    scored(4, '[87.68%]', .85)
    result = diagnostic.rolling_history('alpha', now=NOW+timedelta(seconds=45))
    assert get(diagnostic, 45)['reading']['percentage'] == '87.68'
    assert result['intervals'] == 1
    assert 0 < result['tracked_exp']['approximate'] < 10000
    saved = [json.loads(row[0]) for row in store.db.execute('SELECT payload_json FROM diagnostic_attempts ORDER BY id')]
    assert saved[0]['neural']['raw']['scores'] == [.84805]
    assert not store.db.execute('SELECT 1 FROM observations').fetchone()
