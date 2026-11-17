"""A shared window_endpoints memo must return exactly what independent calls return."""
from datetime import datetime,timedelta,timezone
import random

from exp_tracker.pace_intervals import window_endpoints
from tests.test_product import tracking  # noqa: F401

START=datetime(2026,1,1,tzinfo=timezone.utc)


def point(i,seconds,level,exp,bp=None):
    return dict(event_id=i,timestamp=(START+timedelta(seconds=seconds)).isoformat(),level=dict(value=level),
        exp=exp,bp=bp if bp is not None else 1000+i,accounting_scope='7:1',evidence='strict_full')


def test_shared_memo_matches_independent_calls():
    points=[point(i,20*i,64 if i<40 else 65,1000*i if i<40 else 500*i) for i in range(80)]
    points[10]=point(10,200,64,9000)  # EXP decrease
    points[20]=point(20,380,64,None)  # Percentage-only endpoint
    points[30]=point(30,600,None,30000)  # Level unavailable
    points.append(point(80,20*79,65,40000))  # Same timestamp as the last point
    points+= [point(81+i,20*79+900+20*i,65,50000+i) for i in range(5)]  # After a 15-minute gap
    random.Random(0).shuffle(points)
    memo={};seen=set()
    for minutes in (1,5,10,15,30,60,1440):
        for end in range(0,20*90+1000,70):
            for level in (None,64,65):
                kwargs=dict(start=START+timedelta(seconds=end-60*minutes),end=START+timedelta(seconds=end),level=level)
                result=window_endpoints(points,memo=memo,**kwargs);seen.add(result[2] or len(result[0])>2)
                assert result==window_endpoints(points,**kwargs)
    assert {True,'gap_exceeds_window','two_distinct_observation_times_required'}<=seen


def test_tracked_packet_matches_fresh_window_calculations_as_time_advances(tracking,monkeypatch):
    from exp_tracker import rolling_history,pace_intervals
    from tests.test_incremental_history import build
    _,store,diagnostic=tracking;checkpoints={}
    last=build(store,diagnostic,checkpoints,compare=False)
    def independent(*args,memo=None,**kwargs):return window_endpoints(*args,**kwargs)
    for delta in (0,11,301,3901,90001):
        now=last+timedelta(seconds=delta)
        actual=diagnostic.rolling_history('alpha',now=now,checkpoints=checkpoints)
        if actual['tracked_exp'] is not None:
            assert actual['tracked_exp'] is not actual['windows']['1440']['gain']
        with monkeypatch.context() as patch:
            patch.setattr(rolling_history,'window_endpoints',independent)
            patch.setattr(pace_intervals,'window_endpoints',independent)
            assert actual==diagnostic.rolling_history('alpha',now=now)


def test_remembered_intervals_match_fresh_ones_across_rebuilds(monkeypatch):
    from exp_tracker import pace_intervals
    monkeypatch.setattr(pace_intervals,'PAIR_SLOTS',pace_intervals.OrderedDict())
    computed=[];real=pace_intervals.endpoint_interval
    monkeypatch.setattr(pace_intervals,'endpoint_interval',lambda a,b:computed.append(1) or real(a,b))
    def readings(count,changed=None):
        points=[point(i,20*i,64,1000*i) for i in range(count)]
        if changed is not None:points[changed]=dict(points[changed],exp=1000*changed+7)  # Same reading, corrected EXP.
        return points
    def rebuild(points,now):
        """Fresh reference results, then the remembered ones; returns how many intervals the remembered path computed."""
        expected=[window_endpoints(points,start=now-timedelta(minutes=m),end=now) for m in (5,60,1440)]
        computed.clear();memo=pace_intervals.window_memo(('pairs','alpha',1),now)
        assert [window_endpoints(points,start=now-timedelta(minutes=m),end=now,memo=memo) for m in (5,60,1440)]==expected
        return len(computed)
    now=START+timedelta(seconds=20*60)
    assert rebuild(readings(60),now)==59
    assert rebuild(readings(61),now+timedelta(seconds=20))==1  # Only the new capture's pair.
    assert rebuild(readings(61,changed=30),now+timedelta(seconds=40))==2  # Only the two pairs touching the corrected reading.
    assert rebuild(readings(61,changed=30),now+timedelta(seconds=50))==0


def test_remembered_intervals_drop_unused_pairs_and_stay_within_budget(monkeypatch):
    from exp_tracker import pace_intervals
    monkeypatch.setattr(pace_intervals,'PAIR_SLOTS',pace_intervals.OrderedDict())
    def rebuild(slot,points,now):
        memo=pace_intervals.window_memo(slot,now)
        window_endpoints(points,start=now-timedelta(days=1),end=now,memo=memo)
    now=START+timedelta(hours=2)
    rebuild('a',[point(i,20*i,64,1000*i) for i in range(100)],now)
    rebuild('a',[point(i,20*i,64,1000*i) for i in range(50,100)],now+timedelta(seconds=10))  # The first half left the window.
    rebuild('a',[point(i,20*i,64,1000*i) for i in range(50,100)],now+timedelta(seconds=20))
    store=pace_intervals.PAIR_SLOTS['a']
    assert len(store['new'])==49 and not store['old']
    monkeypatch.setattr(pace_intervals,'PAIR_BUDGET_BYTES',60*pace_intervals.PAIR_BYTES)
    rebuild('b',[point(i,20*i,64,1000*i) for i in range(30)],now)
    rebuild('b',[point(i,20*i,64,1000*i) for i in range(30)],now+timedelta(seconds=10))  # The budget is checked as a slot opens.
    assert list(pace_intervals.PAIR_SLOTS)==['b']  # 'a' was least recently used; 49+29 intervals exceed 60.
