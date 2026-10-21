"""Whole endpoint intervals, window-duration rates, and disposable retention checks."""
from copy import deepcopy
from datetime import timedelta

import pytest

from exp_tracker.diagnostics import Diagnostics
from exp_tracker.exp_requirements import requirement
from exp_tracker.pace_intervals import window_endpoints
from exp_tracker.product import fraction,player,recent_windows,tracked_statistics
from exp_tracker.retention import prune
from exp_tracker.store import Store
from tests.test_product import tracking,NOW
from tests.test_tracked_exp_totals import save


def coordinate(minutes,exp,*,level=64,scope='1:1',epoch=None):
    return dict(timestamp=(NOW+timedelta(minutes=minutes)).isoformat(),exp=str(exp),bp=exp,
        level=dict(value=level),accounting_scope=scope,manual_epoch=epoch,event_id=f'{scope}:{minutes}',
        evidence='strict_full',source_kind='file',source_identity='local')


def gain(points,minutes,clock=60):
    _,value,_=window_endpoints(points,start=NOW+timedelta(minutes=clock-minutes),end=NOW+timedelta(minutes=clock))
    return fraction(value['value']) if value else None


def test_requested_30_40_42_example_and_window_normalized_rates():
    points=[coordinate(20,3000),coordinate(50,4000),coordinate(60,4200)]
    frozen=deepcopy(points)
    windows=recent_windows(dict(observations=[],percentage_progress=dict(reason='synthetic')),None,
        now=NOW+timedelta(minutes=60),collected=dict(points=points,excluded=[],recoveries=[]))
    assert [windows[str(m)]['gain']['approximate'] if windows[str(m)]['gain'] else None
            for m in (5,10,15,30,60,1440)]==[None,200,200,1200,1200,1200]
    for m in (10,15,30,60,1440):
        w=windows[str(m)]
        assert fraction(w['pace']['estimates']['exp_per_hour']['value'])==fraction(w['gain'])*60/m
    assert points==frozen


@pytest.mark.parametrize('minutes',(5,10,15,30,60,1440))
@pytest.mark.parametrize('over',(0,0.000001))
def test_gap_duration_boundary_even_when_older_endpoint_precedes_window(minutes,over):
    # The later endpoint is halfway through the window; its predecessor lies before it.
    points=[coordinate(-minutes/2-over,100),coordinate(minutes/2,200)]
    assert gain(points,minutes,clock=minutes)==(100 if over==0 else None)


def test_later_endpoint_boundaries_future_duplicate_and_stationary():
    points=[coordinate(0,100),coordinate(5,200),coordinate(10,300),coordinate(11,400)]
    assert gain(points,5,clock=10)==200  # Endpoints exactly at both inclusive boundaries.
    assert gain(points,5,clock=10.000001)==100
    assert gain([points[1],points[1],points[2],points[2]],5,clock=10)==100
    assert gain([coordinate(0,100),coordinate(5,100)],5,clock=5)==0


@pytest.mark.parametrize('scope,epoch,expected', [('1:99',None,100),('2:1',None,None),(None,None,None),('1:1','manual',None)])
def test_character_identity_and_manual_boundaries(scope,epoch,expected):
    assert gain([coordinate(0,100),coordinate(5,200,scope=scope,epoch=epoch)],5,clock=5)==expected


def test_loss_is_not_earned_exp_and_nested_windows_stay_monotone():
    points=[coordinate(0,100),coordinate(20,200),coordinate(40,150),coordinate(60,175)]
    assert [gain(points,m) for m in (5,10,15,30,60,1440)]==[None,None,None,25,125,125]


def test_level_ups_use_known_requirements_and_unknown_transitions_abstain():
    total=requirement(67)['to_next']
    points=[coordinate(0,total-100,level=67),coordinate(5,200,level=68)]
    assert gain(points,5,clock=5)==300
    assert gain([coordinate(0,100,level=90),coordinate(5,200,level=91)],5,clock=5) is None
    assert gain([coordinate(0,100,level=68),coordinate(5,200,level=67)],5,clock=5) is None


def finish(d,run,count):
    d.append(run,dict(type='summary',trusted=False,attempts=count,interrupted=False))


def test_saved_sessions_and_restarts_share_character_but_never_other_character(tracking):
    path,store,d=tracking
    save(d,'run',1,20*60,3000);finish(d,'run',1)
    store.end_session('alpha',at=NOW+timedelta(minutes=21));store.start_session('alpha',at=NOW+timedelta(minutes=49))
    d.begin('next','alpha',dict(type='configuration',trusted=False,interval=300,source_kind='file'))
    save(d,'next',1,50*60,4000);save(d,'next',2,60*60,4200)
    now=NOW+timedelta(minutes=60)
    before=d.rolling_history('alpha',now=now)
    req=requirement(64)['to_next'];difference=lambda a,b:b*req//10000-a*req//10000
    assert before['windows']['15']['gain']['approximate']==difference(4000,4200)
    assert before['windows']['30']['gain']['approximate']==difference(3000,4200)
    shown=tracked_statistics(player(d.snapshot('alpha',now=now),now=now,recent_snapshot=d.recent_snapshot('alpha',now=now)),before,now=now)
    assert shown['recent_windows']['30']['pace']['estimates']['exp_per_hour']['value']['approximate']==difference(3000,4200)*2
    with Store(path,read_only=True) as cold:
        assert Diagnostics(cold).rolling_history('alpha',now=now)==before
    other=store.add_character('alpha','Other')
    store.select_character('alpha',other,at=now);store.start_session('alpha',at=now)
    assert d.rolling_history('alpha',now=now)['tracked_exp'] is None


@pytest.mark.parametrize('gap_hours',(24,24.000001,40))
def test_24h_return_and_retention_keep_only_eligible_gain_and_latest_state(tracking,gap_hours):
    path,store,d=tracking
    save(d,'run',1,0,3000);finish(d,'run',1)
    now=NOW+timedelta(hours=gap_hours)
    # Prune the old closed run on the long-gap case; a bounded endpoint checkpoint survives.
    if gap_hours>25:prune(store,now=now,dry_run=False)
    d.begin('return','alpha',dict(type='configuration',trusted=False,interval=300,source_kind='file'))
    save(d,'return',1,int(gap_hours*3600),4000,attempted_at=now.isoformat(),received_at=now.isoformat())
    result=d.rolling_history('alpha',now=now)
    assert bool(result['tracked_exp'])==(gap_hours==24)
    assert result['windows']['1440']['gain']==result['tracked_exp']
    assert player(d.snapshot('alpha',now=now),now=now)['reading']['percentage']=='40.00'
    assert result['unknown_seconds']['approximate']>=0
    with Store(path,read_only=True) as cold:
        assert Diagnostics(cold).rolling_history('alpha',now=now)==result


def test_24h_boundary_crossing_interval_survives_pruning_its_old_endpoint(tracking):
    _,store,d=tracking
    save(d,'run',1,0,3000);finish(d,'run',1)
    d.begin('later','alpha',dict(type='configuration',trusted=False,interval=300,source_kind='file'))
    save(d,'later',1,23*3600,4000);finish(d,'later',1)
    now=NOW+timedelta(hours=30)
    before=d.rolling_history('alpha',now=now)
    assert before['tracked_exp']['approximate']>0
    assert prune(store,now=now,dry_run=False)['attempts']>0
    after=d.rolling_history('alpha',now=now)
    assert after['tracked_exp']==before['tracked_exp']
    assert after['windows']==before['windows']


def test_boundary_crossing_gain_does_not_force_continuous_card_rebuilds():
    from exp_tracker.diagnostics import due
    built=NOW+timedelta(minutes=60)
    pace=dict(start=(NOW+timedelta(minutes=20)).isoformat(),end=built.isoformat(),trend_seconds=1800)
    packet=dict(responsive_pace=pace,recent_windows={'30':dict(pace=pace,available=True)})
    assert not due(packet,built.isoformat(),built+timedelta(seconds=1))
    assert due(packet,built.isoformat(),built+timedelta(seconds=10))


def test_duplicate_old_frame_and_invalid_evidence_cannot_create_extra_gain():
    from tests.test_endpoint_pace import snapshot,missing
    from tests.test_observed_endpoint_totals import numeric
    from exp_tracker.pace_intervals import collect_observed
    from exp_tracker.product import reading
    rows=[numeric(1,0,10000),numeric(2,60,11000),dict(numeric(3,120,10000),frame_sha256=f'{1:064x}'),
          missing(4,180),numeric(5,240,12000)]
    now=NOW+timedelta(seconds=240);snap=snapshot(rows,240)
    collected=collect_observed(snap,now=now,read=reading,max_interval_seconds=300)
    assert len(collected['points'])==3
    assert window_endpoints(collected['points'],start=NOW,end=now)[1]['value']['approximate']==2000


def test_sparse_and_loss_sequences_preserve_nested_totals():
    from random import Random
    rng=Random(42)
    for _ in range(100):
        points=[];minute=0
        for _ in range(20):
            minute+=rng.choice((1,5,10,30,60,180,1500))
            points.append(coordinate(minute,rng.randrange(10000)))
        clock=minute+rng.randrange(30)
        totals=[gain(points,m,clock) or 0 for m in (5,10,15,30,60,1440)]
        assert totals==sorted(totals)
