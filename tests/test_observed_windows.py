"""Observed endpoint summaries never relax fixed windows or connected pace."""
from copy import deepcopy
from datetime import timedelta

import pytest

from tests.test_recent_windows import history,windows
from tests.test_product import tracking,append,get,NOW
from exp_tracker.product import refresh
from exp_tracker.shadow_types import parse_percentage_only


def observed(rows,minutes='5',now=None):
    return windows(rows,now=now)[minutes]['observed']


def test_interrupted_endpoints_are_a_summary_not_a_complete_window_or_rate():
    rows=history(21);rows[10].update(raw_text=None,percentage_only_candidate=None)
    before=deepcopy(rows);w=windows(rows)['5'];o=w['observed']
    assert not w['eligible'] and w['estimates']['exp_per_hour'] is None
    assert o['available'] and o['difference_percentage_points']=='0.20'
    assert o['span_seconds']['approximate']==300 and o['readings']==20
    assert o['interruptions']==1 and o['unavailable_attempts']==1 and o['pace'] is None
    assert not o['trusted'] and not o['identity_verified'] and rows==before
    # Different windows use their own actual endpoints, never boundary interpolation.
    short=observed(history(13),'30')
    assert short['span_seconds']['approximate']==180 and short['readings']==13


def test_two_missing_attempts_allowed_but_repeated_failures_and_long_gaps_break():
    rows=history(30)
    for i in (20,21):rows[i].update(raw_text=None,percentage_only_candidate=None,status='capture_failed',capture_acquired=False,fresh_at_capture=False)
    assert observed(rows)['available'] and observed(rows)['unavailable_attempts']==2
    rows[22].update(raw_text=None,percentage_only_candidate=None)
    o=observed(rows)
    assert o['start']==rows[23]['received_at'] and o['unavailable_attempts']==0
    rows=history(21);del rows[10]
    assert observed(rows)['missing_attempts']==1
    rows=history(21);rows[-1]['received_at']=(NOW+timedelta(seconds=500)).isoformat()
    assert not observed(rows)['available']


def test_missing_hud_is_disclosed_only_with_bounded_local_receipt_evidence():
    rows=history(21);rows[10].update(raw_text=None,percentage_only_candidate=None,hud_count=0,
        fresh_at_capture=False,status='unavailable',reasons=['missing_hud'],local_age_seconds=2)
    assert observed(rows)['interruptions']==1
    rows[10]['local_age_seconds']=20
    assert observed(rows)['start']==rows[11]['received_at']


@pytest.mark.parametrize('change',[
    dict(character_id=2),dict(session_id=2),dict(run_id='other'),dict(source_identity='other'),
    dict(hud_count=2),dict(fresh_at_capture=False),dict(visual_level=65),
    dict(neural_level=dict(level=54,status='numeric_candidate',score=.99)),
    dict(raw_text='[32.00%]',percentage_only_candidate=dict(percentage='32.00')),
    dict(raw_text='[80.00%]',percentage_only_candidate=dict(percentage='80.00')),
])
def test_unsafe_intermediate_observations_are_boundaries_never_holes(change):
    rows=history(21);rows[10].update(change)
    o=observed(rows)
    assert not o['available'] or o['start']>=rows[11]['received_at']


def test_stationary_progress_is_available_but_confirmed_loss_starts_new_summary():
    rows=history(21)
    for r in rows:r.update(raw_text='[33.00%]',percentage_only_candidate=parse_percentage_only('[33.00%]'),frame_sha256=f"{r['index']:064x}")
    assert observed(rows)['difference_percentage_points']=='0.00'
    for i in range(10,21):
        pct=f'32.{i:02}'
        rows[i].update(raw_text=f'[{pct}%]',percentage_only_candidate=parse_percentage_only(f'[{pct}%]'))
    assert observed(rows)['start']>=rows[11]['received_at']
    assert observed(rows)['difference_percentage_points']=='0.09'


def test_sqlite_read_time_summary_pauses_and_survives_restart_without_trusted_writes(tracking):
    path,store,d=tracking
    for i in range(1,22):append(d,i,f'[33.{i:02}%]')
    append(d,22,None,status='capture_failed',received_at=None,current=False)
    p=get(d,315);o=p['windows']['5']['observed']
    assert o['available'] and o['paused'] and o['age_seconds']==15
    old=refresh(p,now=NOW+timedelta(seconds=500))
    assert old['windows']['5']['observed']['available'] and old['windows']['5']['observed']['paused']
    assert old['windows']['5']['observed']['age_seconds']==200
    assert not old['windows']['5']['eligible'] and not store.db.execute('select 1 from observations').fetchone()
    assert not old['windows']['5']['eligibility_checks']['fresh']
    from exp_tracker.store import Store
    from exp_tracker.diagnostics import Diagnostics
    from exp_tracker.product import player
    with Store(path,read_only=True) as restarted:
        now=NOW+timedelta(seconds=315)
        assert player(Diagnostics(restarted).snapshot('alpha',now=now),now=now)['windows']==p['windows']


def test_short_or_near_simultaneous_readings_and_simulation_do_not_make_observed_windows():
    assert not observed(history(2))['available']
    assert not observed(history(3,cadence=5))['available']
    rows=history(21)
    for r in rows:r['timing_mode']='simulated'
    assert not observed(rows)['available']


def test_false_decrease_recovery_never_includes_the_excluded_interval(tracking):
    _,_,d=tracking
    for i,pct in enumerate(('33.00','33.05','32.00','33.10','33.15','33.20'),1):
        append(d,i,f'[{pct}%]',frame_sha256=f'{i:064x}')
    o=get(d,75)['windows']['5']['observed']
    assert o['available'] and o['start']==(NOW+timedelta(seconds=45)).isoformat()
    assert o['difference_percentage_points']=='0.10' and o['readings']==3


def test_sqlite_rotation_is_comparable_but_restart_is_a_new_baseline(tmp_path):
    from exp_tracker.store import Store
    from exp_tracker.diagnostics import Diagnostics
    from exp_tracker.product import player,PRODUCT_ROWS
    from tests.test_diagnostic_history import config,fill,rotate
    with Store(tmp_path/'rotations.sqlite3') as store:
        store.add_channel('alpha');cid=store.add_character('alpha','Main');store.select_character('alpha',cid);store.start_session('alpha')
        d=Diagnostics(store);d.begin('a','alpha',config('a'));fill(d,'a')
        rotate(d,'a','b');fill(d,'b',60,count=4)
        now=NOW+timedelta(seconds=64*15)
        o=player(d.snapshot('alpha',now=now,limit=PRODUCT_ROWS),now=now)['windows']['30']['observed']
        assert o['available'] and o['readings']==64 and o['interruptions']==0
        d.begin('restart','alpha',config('restart'));fill(d,'restart',64,count=1)
        assert not player(d.snapshot('alpha',now=now+timedelta(seconds=15)),now=now+timedelta(seconds=15))['windows']['30']['observed']['available']


def test_suspect_crop_cannot_become_a_new_endpoint_and_gap_limit_is_inclusive():
    rows=history(10);rows[5]['crop_suspect']=True
    o=observed(rows)
    assert o['available'] and o['first_event_id']==rows[6]['event_id']
    rows=history(10,cadence=20)
    for i in (4,5):rows[i].update(raw_text=None,percentage_only_candidate=None)
    assert observed(rows)['unavailable_attempts']==2  # 60s between actual endpoints.
    rows=history(10,cadence=30)
    for i in (4,5):rows[i].update(raw_text=None,percentage_only_candidate=None)
    o=observed(rows)
    assert o['first_event_id']==rows[6]['event_id'] and o['unavailable_attempts']==0
