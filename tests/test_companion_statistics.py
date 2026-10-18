"""Read-only presentation estimates: no gaps become gains or elapsed coverage."""
from datetime import timedelta
from fractions import Fraction

import pytest

from exp_tracker.product import history,fraction,exp_change
from tests.test_product import tracking,append,get,NOW


def test_exp_conversion_is_exact_and_missing_requirement_abstains():
    change=exp_change(1000,1014,66)
    assert fraction(change['value'])==Fraction(14*change['requirement']['to_next'],10000)
    for bounds in change['hypotheses'].values():
        assert fraction(bounds['lower'])<=fraction(change['value'])<=fraction(bounds['upper'])
    assert not change['trusted'] and exp_change(100,101,100) is None


def test_history_gains_keep_zero_distinct_from_missing_and_never_bridge(tracking):
    _,store,d=tracking
    for i,text in enumerate(('[33.00%]','[33.00%]',None,'[33.10%]','[33.15%]'),1):
        append(d,i,text,**(dict(status='capture_failed',received_at=None,current=False) if text is None else {}))
    points=history(d.snapshot('alpha',now=NOW+timedelta(seconds=60)))
    assert points[0]['gain'] is None and points[1]['gain']['value']['approximate']==0
    assert points[2]['gain'] is None and points[3]['gain'] is None
    assert points[4]['gain']['first_event_id']==points[3]['event_id']
    assert points[4]['gain']['value']['approximate']==pytest.approx(748.916)
    assert not store.db.execute('select 1 from observations').fetchone()


def test_pooled_pace_uses_only_captured_seconds_and_quantization_components(tracking):
    _,_,d=tracking
    for i,pct in ((1,'33.00'),(2,'33.05'),(3,'33.10')):append(d,i,f'[{pct}%]')
    append(d,4,None,status='capture_failed',received_at=None,current=False)
    append(d,5,'[35.00%]');append(d,6,'[35.05%]')
    rate=get(d,75)['responsive_pace']
    assert rate['active'] and rate['readings']==5 and rate['interruptions']==1
    assert rate['coverage_seconds']['approximate']==45 and rate['span_seconds']['approximate']==75
    assert rate['estimates']['percentage_per_hour']['value']['approximate']==12
    # Two disconnected endpoint pairs contribute two display-precision bins.
    assert rate['estimates']['percentage_per_hour']['nearest_half_up']['lower']['approximate']==pytest.approx(10.4)
    assert not get(d,75)['windows']['5']['eligible']


@pytest.mark.parametrize('boundary', ['loss','anomaly','level','session','long_outage'])
def test_new_pace_and_bars_do_not_cross_hard_boundaries(tracking,boundary):
    _,store,d=tracking
    for i,pct in enumerate(('33.00','33.05','33.10'),1):append(d,i,f'[{pct}%]',frame_sha256=f'{i:064x}')
    if boundary=='session':
        store.end_session('alpha',at=NOW+timedelta(seconds=31));store.start_session('alpha',at=NOW+timedelta(seconds=32))
        assert get(d,40)['responsive_pace'] is None
        return
    if boundary=='long_outage':
        for i in (4,5,6):append(d,i,None,status='capture_failed',received_at=None,current=False)
        for i in (7,8):append(d,i,f'[34.{i:02}%]')
        result=get(d,105);assert result['responsive_pace']['readings']==2
        assert result['responsive_pace']['start']==(NOW+timedelta(seconds=90)).isoformat()
        return
    if boundary=='level':
        neural=dict(text='65',level=65,status='numeric_candidate',score=.99)
        for i,pct in ((4,'0.10'),(5,'0.15'),(6,'0.20')):append(d,i,f'[{pct}%]',visual_level=65,neural_level=neural)
    else:
        append(d,4,'[32.00%]',frame_sha256='4'*64)
        for i,pct in ((5,'32.05' if boundary=='loss' else '33.15'),(6,'32.10' if boundary=='loss' else '33.20')):
            append(d,i,f'[{pct}%]',frame_sha256=f'{i:064x}')
    result=get(d,75)
    assert result['responsive_pace']['readings']==2
    points=history(d.snapshot('alpha',now=NOW+timedelta(seconds=75)))
    assert points[3]['gain'] is None and points[-1]['gain']


def test_direct_strict_exp_interval_keeps_exact_integer_difference(tracking):
    _,_,d=tracking
    append(d,1,'494,285[33.00%]',candidate=[494285,33.0],status='diagnostic_pair')
    append(d,2,'495,034[33.05%]',candidate=[495034,33.05],status='diagnostic_pair')
    gain=history(d.snapshot('alpha',now=NOW+timedelta(seconds=15)))[1]['gain']
    assert gain['basis']=='observed_exp_endpoints' and fraction(gain['value'])==749


def test_stopped_progress_gives_zero_pace_and_no_eta(tracking):
    _,_,d=tracking
    for i in (1,2,3):append(d,i,'[33.00%]',frame_sha256=f'{i:064x}')
    p=get(d,30)
    assert p['responsive_pace']['estimates']['exp_per_hour']['value']['approximate']==0
    assert p['responsive_pace']['estimates']['eta'] is None


def test_small_integer_decrease_is_not_a_zero_gain_bar_or_a_smoothed_gain(tracking):
    _,_,d=tracking
    append(d,1,'494,285[33.00%]',candidate=[494285,33.0],status='diagnostic_pair')
    append(d,2,'494,280[33.00%]',candidate=[494280,33.0],status='diagnostic_pair')
    assert history(d.snapshot('alpha',now=NOW+timedelta(seconds=15)))[1]['gain'] is None
    assert not (get(d,15)['responsive_pace'] or {}).get('active')


def test_missing_capture_does_not_age_endpoints_out_of_the_held_rate(tracking):
    _,_,d=tracking
    for i in range(1,22):append(d,i,f'[33.{i if i<21 else 70:02}%]')
    before=get(d,300)['responsive_pace']
    append(d,22,None,status='capture_failed',received_at=None,current=False)
    held=get(d,315)['responsive_pace']
    assert not held['active'] and held['age_seconds']==15
    assert held['estimates']['exp_per_hour']==before['estimates']['exp_per_hour']
    assert held['coverage_seconds']==before['coverage_seconds'] and held['start']==before['start']
