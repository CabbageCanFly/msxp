"""Synthetic window histories; no saved OCR numbers or private imagery required."""
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from exp_tracker.diagnostic_progress import progress
from exp_tracker.product import window_comparisons, player, PRODUCT_ROWS
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.store import Store
from tests.test_diagnostic_progress import row, NOW
from tests.test_diagnostic_history import config, fill, rotate
from tests.test_diagnostics import configured


def history(count=121, cadence=15, offset=0):
    return [row(i+1, f'{(3300+i)//100}.{(3300+i)%100:02}', interval_seconds=cadence,
                received_at=(NOW+timedelta(seconds=offset+i*cadence)).isoformat()) for i in range(count)]


def windows(rows, now=None):
    now=now or max(datetime.fromisoformat(r['received_at']) for r in rows)
    snap=dict(observations=rows,percentage_progress=progress(rows,now=now))
    return window_comparisons(snap,now=now)


def test_all_windows_use_actual_endpoints_exact_rates_and_separate_quantization_bounds():
    rows=history();before=deepcopy(rows)
    values=windows(rows)
    for minutes in (5,10,15,30):
        value=values[str(minutes)]
        assert value['eligible'] and value['coverage_seconds']['approximate']==minutes*60
        assert value['readings']==minutes*4+1
        assert value['difference_percentage_points']==f'{minutes*4/100:.2f}'
        pace=value['estimates']['percentage_per_hour']
        assert pace['value']['approximate']==2.4
        assert pace['nearest_half_up']['lower']['approximate']<2.4<pace['truncation']['upper']['approximate']
        assert value['estimates']['exp_per_hour']['requirement']['to_next']==1497832
        assert not value['trusted']
    assert rows==before


def test_no_interpolation_from_endpoint_outside_boundary_and_short_history_is_not_a_window():
    rows=history(22,offset=4)
    # Latest capture at 319s; a point at 19s is on the boundary, never split an interval.
    result=windows(rows)['5']
    assert result['start']==rows[1]['received_at'] and result['readings']==21
    assert result['difference_percentage_points']=='0.20'
    assert not windows(history(13))['5']['eligible']  # Three minutes, not five.
    rows=history(21,cadence=16)
    result=windows(rows)['5']
    assert result['coverage_seconds']['approximate']==288 and result['eligible']
    assert result['start']==rows[2]['received_at']
    assert result['difference_percentage_points']=='0.18'  # Not a fabricated 300-second difference.


@pytest.mark.parametrize('change',[
    dict(status='capture_failed',fresh_at_capture=False),dict(hud_count=2),dict(visual_level=None),
    dict(neural_level=dict(level=54,status='numeric_candidate',score=.99)),
    dict(character_id=2),dict(session_id=2),dict(run_id='restart'),
    dict(raw_text='[32.00%]',percentage_only_candidate=dict(percentage='32.00')),
])
def test_breaks_inside_window_prevent_comparison(change):
    rows=history(21);rows[10].update(change)
    assert not windows(rows)['5']['eligible']


def test_missing_attempt_long_gap_stale_interruption_and_simulation_do_not_produce_windows():
    rows=history(22);del rows[8]
    assert not windows(rows)['5']['eligible']
    rows=history(21);rows[-1]['received_at']=(NOW+timedelta(seconds=500)).isoformat()
    assert not windows(rows)['5']['eligible']
    rows=history(21)
    assert windows(rows,now=NOW+timedelta(seconds=400))['5']['state']=='stale'
    rows[-1]['run_interrupted']=True
    assert windows(rows)['5']['reason']=='explicit_run_interruption'
    rows=history(21);rows[-1]['timing_mode']='simulated'
    assert not windows(rows)['5']['eligible']


@pytest.mark.parametrize('level',[99,100,200])
def test_unsupported_or_disputed_requirement_keeps_percentage_window_only(level):
    rows=history(21)
    for r in rows:r['visual_level']=level
    value=windows(rows)['5']
    assert value['eligible'] and value['estimates']['percentage_per_hour']
    assert value['estimates']['exp_per_hour'] is None


def test_zero_window_is_not_ranked_as_unavailable_but_has_no_eta():
    rows=[row(i+1) for i in range(21)]
    value=windows(rows)['5']
    assert value['eligible'] and value['difference_percentage_points']=='0.00'
    assert value['estimates']['exp_per_hour']['value']['approximate']==0
    assert value['estimates']['eta'] is None


def test_sqlite_product_history_spans_clean_rotations_but_advanced_pages_stay_bounded(configured,monkeypatch):
    with Store(configured) as store:
        d=Diagnostics(store);d.begin('a','alpha',config('a'));fill(d,'a')
        rotate(d,'a','b');fill(d,'b',60)
        rotate(d,'b','c');fill(d,'c',120,count=5)
        now=NOW+timedelta(seconds=125*15)
        before=[r[0] for r in store.db.execute('select payload_json from diagnostic_attempts')]
        assert len(d.snapshot('alpha',now=now)['observations'])==120
        snap=d.snapshot('alpha',now=now,limit=PRODUCT_ROWS)
        result=player(snap,now=now)
        assert len(snap['observations'])==125 and result['windows']['30']['eligible']
        assert result['windows']['30']['readings']==121
        assert snap['coverage']['history_limit']==PRODUCT_ROWS
        assert not store.db.execute('select 1 from observations').fetchone()
        # Both real HTTP paths consume the same bounded SQLite projection.
        import exp_tracker.server as http
        import exp_tracker.diagnostics as persistence
        from tests.test_server import request
        from exp_tracker.publisher import public
        import json
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return now
        monkeypatch.setattr(http,'datetime',Clock);monkeypatch.setattr(persistence,'datetime',Clock)
        with http.create_server(configured,port=0,diagnostic_dashboard=True) as server:
            board=json.loads(request((server,None),'/api/players')[2])['players'][0]
            detail=json.loads(request((server,None),'/api/players/alpha')[2])
            assert board['windows']==detail['player']['windows']==public(result['windows'])  # Public omits diagnostics only.
            assert len(detail['history'])==125
            assert request((server,None),'/dev/api/streams/alpha/diagnostics')[0]==200
        for limit in (0,641,True):
            with pytest.raises(ValueError):d.snapshot('alpha',limit=limit)
        # Restart is a hard run boundary even with the same explicit character/session.
        d.begin('restart','alpha',config('restart'))
        fill(d,'restart',125,count=1)
        assert not player(d.snapshot('alpha',now=now+timedelta(seconds=15),limit=PRODUCT_ROWS),now=now+timedelta(seconds=15))['windows']['5']['eligible']
        assert before==[r[0] for r in store.db.execute('select payload_json from diagnostic_attempts order by id limit 125')]
    with Store(configured,read_only=True) as store:
        assert not player(Diagnostics(store).snapshot('alpha',now=now+timedelta(seconds=15),limit=PRODUCT_ROWS),now=now+timedelta(seconds=15))['windows']['30']['eligible']
