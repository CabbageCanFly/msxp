"""A shared window_endpoints memo must return exactly what independent calls return."""
from datetime import datetime,timedelta,timezone
import random

from exp_tracker.pace_intervals import window_endpoints

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
