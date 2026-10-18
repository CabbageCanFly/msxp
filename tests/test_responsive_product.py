"""Consumer estimates use guarded segments, never supply trusted/window accounting."""
from datetime import timedelta

import pytest

from exp_tracker.product import history,player,refresh
from tests.test_product import NOW,append,get,tracking


def test_two_reading_rate_is_tentative_and_separate_from_fixed_windows(tracking):
    _,store,d=tracking
    append(d,1,'[33.00%]');append(d,2,'[33.05%]')
    p=get(d,15);pace=p['responsive_pace']
    assert pace['active'] and pace['tentative'] and pace['readings']==2
    assert pace['span_seconds']['approximate']==15
    assert pace['estimates']['exp_per_hour']['value']['approximate']==pytest.approx(179739.84)
    assert pace['estimates']['eta'] is None
    assert not p['windows']['5']['eligible'] and p['estimates']['exp_per_hour'] is None
    assert not store.db.execute('SELECT 1 FROM observations').fetchone()


def test_two_readings_need_real_separation_and_rate_uses_actual_exp_when_consistent(tracking):
    _,_,d=tracking
    append(d,1,'494,285[33.00%]',candidate=[494285,33.0],status='diagnostic_pair')
    stamp=(NOW+timedelta(seconds=4)).isoformat()
    append(d,2,'495,034[33.05%]',candidate=[495034,33.05],status='diagnostic_pair',received_at=stamp,attempted_at=stamp)
    assert get(d,4)['responsive_pace'] is None
    stamp=(NOW+timedelta(seconds=22)).isoformat()
    append(d,3,'495,783[33.10%]',candidate=[495783,33.10],status='diagnostic_pair',received_at=stamp,attempted_at=stamp)
    p=get(d,22)['responsive_pace']
    assert p['basis']=='observed_exp_endpoints' and p['tentative']
    assert p['estimates']['exp_per_hour']['value']['approximate']==pytest.approx(1498*3600/22)


def test_missing_sample_retains_history_and_next_valid_endpoint_includes_gap_time(tracking):
    _,_,d=tracking
    append(d,1,'[33.00%]');append(d,2,'[33.05%]')
    before=get(d,15)['responsive_pace']
    append(d,3,None,status='capture_failed',received_at=None,current=False)
    p=get(d,30)
    assert not p['responsive_pace']['active'] and p['responsive_pace']['end']==before['end']
    append(d,4,'[34.00%]');assert get(d,45)['responsive_pace']['active']
    append(d,5,'[34.05%]');p=get(d,60)
    assert p['responsive_pace']['active'] and p['responsive_pace']['readings']==4
    assert p['responsive_pace']['coverage_seconds']['approximate']==60
    assert p['responsive_pace']['span_seconds']['approximate']==60
    assert p['responsive_pace']['interruptions']==0
    assert p['responsive_pace']['interval_counts']==dict(direct=2,endpoint_supported=1)
    # Net endpoint difference includes the full elapsed gap, with no invented sample.
    assert p['responsive_pace']['estimates']['percentage_per_hour']['value']['approximate']==63
    old=refresh(p,now=NOW+timedelta(seconds=200))
    assert not old['responsive_pace']['active'] and old['responsive_pace']['estimates']['exp_per_hour']
    assert old['responsive_pace']['age_seconds']==140


def test_quarantine_and_confirmed_loss_do_not_contribute_to_responsive_pace(tracking):
    _,_,d=tracking
    for i,pct in enumerate(('33.00','33.05','32.00','32.05','32.10'),1):
        append(d,i,f'[{pct}%]',frame_sha256=f'{i:064x}')
        p=get(d,(i-1)*15)
        if i==3:assert not p['responsive_pace']['active']
        if i==4:assert not p['responsive_pace']['active']
    assert p['responsive_pace']['readings']==4 and p['responsive_pace']['interruptions']==1
    assert p['responsive_pace']['intervals'][-1]['start']==(NOW+timedelta(seconds=45)).isoformat()
    assert all(e['first_event_id']!='run:3' and e['last_event_id']!='run:3' for e in p['responsive_pace']['intervals'])


def test_corroborated_level_event_and_new_pace_never_connect_cross_level(tracking):
    _,_,d=tracking
    append(d,1,'[99.90%]');append(d,2,'[99.97%]')
    neural=dict(text='65',level=65,status='numeric_candidate',score=.99,preprocessing='neutral4')
    append(d,3,'[0.01%]',visual_level=65,neural_level=neural)
    assert get(d)['level_events']==[]
    for i,pct in ((4,'0.03'),(5,'0.08'),(6,'0.12')):append(d,i,f'[{pct}%]',visual_level=65,neural_level=neural,frame_sha256=f'{i:064x}')
    p=get(d,75)
    assert len(p['level_events'])==1 and p['level_events'][0]['level']==65
    assert p['responsive_pace']['level']==65 and p['responsive_pace']['start']>=(NOW+timedelta(seconds=45)).isoformat()
    points=history(d.snapshot('alpha',now=NOW+timedelta(seconds=75)))
    assert not points[3]['connect_previous'] and points[4]['connect_previous']
    assert p['windows']['5']['eligible'] is False


@pytest.mark.parametrize('changes',[dict(localization=dict(count=0)),dict(localization=dict(count=2)),dict(current=False),dict(neural_level=dict(text='55',level=55,status='numeric_candidate',score=.99))])
def test_ambiguous_or_stale_intermediate_frames_cannot_seed_or_bridge_rate(tracking,changes):
    _,_,d=tracking
    append(d,1,'[33.00%]');append(d,2,'[33.05%]',**changes)
    assert not (get(d,15)['responsive_pace'] or {}).get('active')


def test_missing_requirement_allows_percentage_pace_without_numerical_exp(tracking):
    _,_,d=tracking
    for i,pct in ((1,'33.00'),(2,'33.05')):
        append(d,i,f'[{pct}%]',visual_level=100,neural_level=dict(text='100',level=100,status='numeric_candidate',score=.99))
    pace=get(d,15)['responsive_pace']
    assert pace['active'] and pace['estimates']['exp_per_hour'] is None
    assert pace['estimates']['percentage_per_hour']


def test_level_event_needs_distinct_new_frames_and_never_crosses_session_or_restart(tracking):
    _,store,d=tracking
    append(d,1,'[99.90%]')
    neural=dict(text='65',level=65,status='numeric_candidate',score=.99)
    for i in (2,3,4):append(d,i,'[0.01%]',visual_level=65,neural_level=neural,frame_sha256='a'*64)
    assert get(d,45)['level_events']==[]
    append(d,5,'[0.02%]',visual_level=65,neural_level=neural,frame_sha256='b'*64)
    assert len(get(d,60)['level_events'])==1
    store.end_session('alpha',at=NOW+timedelta(seconds=61));store.start_session('alpha',at=NOW+timedelta(seconds=62))
    assert get(d,63)['responsive_pace'] is None and get(d,63)['level_events']==[]


def test_trend_retains_only_observed_intervals_in_last_five_minutes(tracking):
    _,_,d=tracking
    for i in range(1,30):append(d,i,f'[{33+i//100}.{i%100:02}%]')
    pace=get(d,420)['responsive_pace']
    assert pace['span_seconds']['approximate']==300 and pace['readings']==21
    assert not pace['tentative'] and pace['start']==(NOW+timedelta(seconds=120)).isoformat()
