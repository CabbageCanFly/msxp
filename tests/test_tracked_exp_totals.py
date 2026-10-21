"""All public gain lookbacks sum the same nonnegative, causal EXP intervals."""
from datetime import datetime,timedelta
from fractions import Fraction
import json
import threading
from types import SimpleNamespace

import pytest

from exp_tracker.diagnostics import Diagnostics
from exp_tracker.exp_requirements import requirement
from exp_tracker.pace_intervals import collect,collect_observed,exp_interval,tracked_window
from exp_tracker.product import reading,fraction,player,tracked_statistics
from exp_tracker.store import Store
from tests.test_product import tracking,NOW
from tests.test_diagnostics import attempt
from tests.test_diagnostic_history import config,rotate
from tests.test_cross_level_product import replay,expected_net


def save(d,run,index,seconds,bp,*,level=64,full=True,missing=False,**changes):
    r=attempt(index);stamp=(NOW+timedelta(seconds=seconds)).isoformat();pct=f'{bp//100}.{bp%100:02}'
    exp=bp*(requirement(level)['to_next'] or 100000)//10000
    r.update(attempted_at=stamp,received_at=stamp,current=True,localization=dict(count=1),
        frame_sha256=f'{seconds:064x}',visual_level=level,neural_level=None,visual_status='available',
        source=dict(kind='twitch',channel='alpha'),neural=dict(text=f'{exp:,}[{pct}%]' if full else f'[{pct}%]'),
        candidate=[exp,float(pct)] if full else None,status='diagnostic_pair' if full else 'diagnostic_percentage_only')
    if missing:r.update(received_at=None,current=False,status='capture_failed',localization=dict(count=0),candidate=None,neural=None)
    r.update(changes);d.append(run,r)


def fill(d,count,step=20,**options):
    for n in range(count):
        rid=f'gain-{n//60}'
        if n==0:d.begin(rid,'alpha',config(rid,interval=step))
        elif n%60==0:
            previous=f'gain-{n//60-1}'
            d.rotate(previous,rid,'alpha',dict(type='summary',trusted=False,attempts=60,
                interrupted=False,completion_reason='scheduled_rotation',next_run_id=rid),config(rid,previous,interval=step))
        save(d,rid,n%60+1,n*step,1000+n,**options)
    return NOW+timedelta(seconds=(count-1)*step)


def nested(result):
    values=[fraction(result['windows'][m]['gain']) if result['windows'][m]['gain'] is not None else None
        for m in ('5','10','15','30','60')]+[fraction(result['tracked_exp']) if result['tracked_exp'] is not None else None]
    available=[v for v in values if v is not None]
    assert available==sorted(available)
    return values


@pytest.mark.parametrize('minutes',[35,120])
@pytest.mark.parametrize('full',[True,False])
def test_new_35_minute_and_two_hour_characters_have_nested_totals(tracking,minutes,full):
    _,store,d=tracking;now=fill(d,minutes*3+1,full=full)
    result=d.rolling_history('alpha',now=now);values=nested(result)
    if minutes==35:assert values[-1]==values[-2]
    else:assert values[-1]>values[-2]
    snap=d.snapshot('alpha',now=now,limit=640)
    edges=collect(snap,now=now,read=reading,max_interval_seconds=300)['intervals']
    gains=[exp_interval(e) for e in edges]
    for m in ('5','10','15','30','60'):
        assert fraction(result['windows'][m]['gain'])==expected_net(snap,now,int(m))
    assert result['intervals']==minutes*3
    assert not store.db.execute('select 1 from observations').fetchone()


@pytest.mark.parametrize('missing_count',[1,2,5,10])
def test_supported_missing_endpoints_count_net_gain_and_all_elapsed_once(tracking,missing_count):
    _,_,d=tracking;d.begin('gaps','alpha',config('gaps',interval=20))
    save(d,'gaps',1,0,3300,full=False);save(d,'gaps',2,20,3305,full=False)
    for n in range(missing_count):save(d,'gaps',n+3,(n+2)*20,3310,missing=True)
    end=(missing_count+2)*20;save(d,'gaps',missing_count+3,end,3350,full=False)
    result=d.rolling_history('alpha',now=NOW+timedelta(seconds=end))
    assert fraction(result['tracked_exp'])==Fraction((3350*1497832+5000)//10000-(3300*1497832+5000)//10000)
    assert result['coverage_seconds']['approximate']==end and result['intervals']==2
    assert result['chart_intervals'][-1]['kind']=='endpoint_supported'
    assert nested(result)[-1]==nested(result)[-2]


@pytest.mark.parametrize('kind',['restart','session','source','level','loss','anomaly','stale','duplicate','incompatible'])
def test_public_boundaries_and_missed_captures_match_causal_replay(tracking,kind):
    _,store,d=tracking;d.begin('first','alpha',config('first'))
    save(d,'first',1,0,3300);save(d,'first',2,20,3305)
    run='first';base=3;level=64;bp=3310;changes={}
    if kind in ('restart','session'):
        if kind=='session':
            store.end_session('alpha',at=NOW+timedelta(seconds=21));store.start_session('alpha',at=NOW+timedelta(seconds=22))
        run='restart';base=1;d.begin(run,'alpha',config(run))
    elif kind=='source':changes['source']=dict(kind='file',channel=None)
    elif kind=='level':level=65;bp=1
    elif kind=='loss':bp=3200
    elif kind=='anomaly':bp=2300
    elif kind=='stale':changes.update(current=False,status='stale_local_frame')
    elif kind=='duplicate':changes['frame_sha256']=f'{20:064x}'
    elif kind=='incompatible':changes.update(candidate=[2458,33.10],neural=dict(text='2,458[33.10%]'))
    save(d,run,base,40,bp,level=level,**changes)
    if kind!='source':changes={}
    for n in (1,2,3):save(d,run,base+n,40+n*20,bp+n*5 if kind not in ('anomaly','incompatible','stale','duplicate') else 3310+n*5,level=level,**changes)
    now=NOW+timedelta(seconds=100);result=d.rolling_history('alpha',now=now)
    nested(result)
    # Replay the entire causal history in one batch: run batching must not change decisions.
    rows=[]
    for rid, in store.db.execute('select run_id from diagnostic_runs order by rowid'):
        rows+=d._snapshot('alpha',now=now,session_id=store.db.execute('select session_id from diagnostic_runs where run_id=?',(rid,)).fetchone()[0],run_id=rid,limit=60,_rows_only=True)
    from exp_tracker.diagnostic_evidence import project
    from exp_tracker.diagnostic_percentage import review
    from exp_tracker.diagnostic_progress import percentage_point
    rows=project(rows);decisions=review(rows,[percentage_point(r) for r in rows],now=now)
    for r,decision in zip(rows,decisions):r['percentage_review']=decision
    edges=collect_observed(dict(observations=rows,percentage_progress=dict(percentage_reviews=decisions)),now=now,read=reading,max_interval_seconds=300)['intervals']
    reference=dict(observations=rows);expected=expected_net(reference,now)
    assert (fraction(result['tracked_exp']) if result['tracked_exp'] else None)==expected
    assert result['tracked_exp'] is None or result['tracked_exp']['approximate']>=0
    assert not store.db.execute('select 1 from observations').fetchone()


def test_window_edges_include_whole_duration_eligible_crossing_intervals(tracking):
    _,_,d=tracking;d.begin('edges','alpha',config('edges'))
    for i,sec in enumerate((0,20,40,60),1):save(d,'edges',i,sec,3300+i*5,full=False)
    now=NOW+timedelta(seconds=325);result=d.rolling_history('alpha',now=now)
    # 20->40 crosses the start at 25s; both it and 40->60 count without prorating.
    assert fraction(result['windows']['5']['gain'])==Fraction((3320*1497832+5000)//10000-(3310*1497832+5000)//10000)
    assert fraction(result['windows']['10']['gain'])==Fraction((3320*1497832+5000)//10000-(3305*1497832+5000)//10000)
    nested(result)
    assert d.rolling_history('alpha',now=NOW+timedelta(days=2))['tracked_exp'] is None


def test_collector_streaming_state_and_conditional_percent_match_single_batch():
    from tests.test_endpoint_pace import point,snapshot,missing
    rows=[point(1,0,657877,'37.43'),point(2,20,659373,'37.51'),missing(3,40),
        point(4,60,660978,'37.60'),point(5,80,662457,'37.69')]
    rows[4].update(raw_text='662.457137.69X1',candidate=None,status='malformed_or_unavailable')
    snap=snapshot(rows,80);now=NOW+timedelta(seconds=80)
    expected=collect(snap,now=now,read=reading,max_interval_seconds=300)
    for size in (1,2,3):
        state={};edges=[];recoveries=[]
        for n in range(0,len(rows),size):
            chunk=dict(observations=snap['observations'][n:n+size],percentage_progress=dict(percentage_reviews=snap['percentage_progress']['percentage_reviews'][n:n+size]))
            result=collect(chunk,now=now,read=reading,max_interval_seconds=300,state=state)
            edges+=result['intervals'];recoveries+=result['recoveries']
        assert edges==expected['intervals'] and recoveries==expected['recoveries']


def test_tracked_gain_does_not_depend_on_rate_warmup(tracking):
    _,_,d=tracking;d.begin('short','alpha',config('short'))
    save(d,'short',1,0,3300);save(d,'short',2,3,3301)
    now=NOW+timedelta(seconds=3);h=d.rolling_history('alpha',now=now)
    snap=d.snapshot('alpha',now=now);p=player(snap,now=now,recent_snapshot=d.recent_snapshot('alpha',now=now))
    assert p['responsive_pace']['coverage_seconds']['approximate']==3
    assert tracked_statistics(p,h,now=now)['recent_windows']['5']['gain']['approximate']>0
    nested(h)


@pytest.mark.parametrize('end,expected',[(300,5000),(300.000001,5000),(360,5000),(600,4000)])
def test_exact_five_minute_capture_gap_and_whole_interval_cutoff(tracking,end,expected):
    from tests.test_exp_level_product import attempt as append
    from tests.test_exp_level_inference import display
    _,store,d=tracking
    for i,exp in enumerate((10000,11000,None,None,None,15000),1):
        stamp=(NOW+timedelta(seconds=(i-1)*60)).isoformat()
        pct=display(exp or 0,requirement(64)['to_next'])
        changes=dict(attempted_at=stamp,received_at=stamp,visual_level=64,visual_status='available',
            neural_level=dict(status='numeric_candidate',text='64',level=64,score=.99))
        if exp is None:
            changes.update(received_at=None,current=False,status='capture_failed',localization=dict(count=0),neural=None)
        append(d,i,exp=exp,pct=pct,**changes)
    now=NOW+timedelta(seconds=end);rolling=d.rolling_history('alpha',now=now)
    p=tracked_statistics(player(d.snapshot('alpha',now=now),now=now),rolling,now=now)
    values=nested(rolling)
    assert values[0]==expected and values[1:]==[5000]*5
    assert all(p['recent_windows'][m]['gain']==rolling['windows'][m]['gain'] for m in rolling['windows'])
    assert [e['value']['approximate'] for e in rolling['chart_intervals']]==[1000,4000]
    assert rolling['coverage_seconds']['approximate']==300
    if end==300:
        pace=p['recent_windows']['5']['pace']
        assert pace['coverage_seconds']['approximate']==300
        assert pace['estimates']['exp_per_hour']['value']['approximate']==60000
    assert not store.db.execute('select 1 from observations').fetchone()


@pytest.mark.parametrize('seconds,expected',[(300,5000),(300.000001,None)])
def test_endpoint_gap_limit_includes_exactly_five_minutes(seconds,expected):
    from tests.test_endpoint_pace import point,snapshot,missing
    from tests.test_exp_level_inference import display
    total=requirement(67)['to_next']
    rows=[point(1,0,10000,display(10000,total)),missing(2,60),
        point(3,seconds,15000,display(15000,total))]
    now=NOW+timedelta(seconds=seconds)
    edges=collect(snapshot(rows,seconds),now=now,read=reading,max_interval_seconds=300)['intervals']
    result=tracked_window([exp_interval(e) for e in edges],start=NOW,end=now)
    assert (result['gain']['approximate'] if result['gain'] else None)==expected


def test_current_level_filter_uses_supported_level_even_when_its_percentage_is_unreadable(tracking):
    _,_,d=tracking;d.begin('levels','alpha',config('levels'))
    save(d,'levels',1,0,3300);save(d,'levels',2,20,3305)
    for i in (3,4):
        save(d,'levels',i,i*20,1,level=65,candidate=None,neural=dict(text='unreadable'),status='malformed_or_unavailable',
            neural_level=dict(status='numeric_candidate',level=65,text='65',score=.99,preprocessing='neutral4'))
    result=d.rolling_history('alpha',now=NOW+timedelta(seconds=80))
    assert result['current_level']==65
    assert result['windows']['60']['gain']['approximate']>0
    assert result['current_level_windows']['60']['gain'] is None


def test_http_totals_share_one_asof_packet_through_cache_and_clock_expiry(tracking,monkeypatch):
    import exp_tracker.server as module
    from tests.test_server import request
    class Clock(datetime):
        at=NOW+timedelta(minutes=35)
        @classmethod
        def now(cls,tz=None):return cls.at
    monkeypatch.setattr(module,'datetime',Clock)
    path,store,d=tracking;fill(d,106)
    before=[tuple(r) for r in store.db.execute('select * from diagnostic_attempts order by id')]
    with module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        for delta in (0,7,40):
            Clock.at=NOW+timedelta(minutes=35,seconds=delta)
            actual=json.loads(request((server,None),'/api/players/alpha')[2])
            packet=actual['tracked_history'];nested(packet)
            separate=json.loads(request((server,None),'/api/players/alpha/history')[2])
            assert separate['as_of']==packet['as_of']==actual['player']['tracked_as_of']
            assert separate['tracked_exp']==packet['tracked_exp']
            assert packet['windows']['60']['gain']==packet['tracked_exp']
            assert actual['player']['recent_windows']['60']['gain']==packet['tracked_exp']
            assert all(actual['player']['recent_windows'][m]['gain']==packet['windows'][m]['gain'] for m in packet['windows'])
            assert all(actual['player']['recent_windows'][m]['start']==packet['windows'][m]['window_start']
                and actual['player']['recent_windows'][m]['end']==packet['as_of'] for m in packet['windows'])
    assert [tuple(r) for r in store.db.execute('select * from diagnostic_attempts order by id')]==before
    assert not store.db.execute('select 1 from observations').fetchone()


def test_rebuilding_one_published_channel_keeps_the_other_channels_entry(tracking,monkeypatch):
    import exp_tracker.server as module
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return NOW+timedelta(seconds=60)
    monkeypatch.setattr(module,'datetime',Clock)
    path,store,d=tracking;save(d,'run',1,0,3300);save(d,'run',2,20,3305);store.add_channel('beta')
    with module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        server.publisher.settle();beta=server.publisher.entry('beta')
        save(d,'run',3,40,3310);server.publisher.settle()
        assert server.publisher.entry('beta') is beta and server.publisher.entry('alpha')['tracked']['intervals']==2


def test_saved_emmies_exact_discrepancy_is_fixed_and_nested_after_sqlite_restart(tmp_path):
    db=tmp_path/'emmies.sqlite3';as_of=datetime.fromisoformat('2026-10-19T01:03:54.273738+00:00')
    with Store(db) as store:
        d,_=replay(store,'emmies',['20261019T001842Z-5817cb05','20261019T001945Z-65cc75a7','20261019T003226Z-cbe9ba29'],as_of=as_of)
        before=[r[0] for r in store.db.execute('select payload_json from diagnostic_attempts order by id')]
        result=d.rolling_history('emmies',now=as_of)
        # Both same-assignment restarts count: +698, and 18,800 -> 19,577 (+777).
        # Whole intervals crossing the 5/10/15/30m starts add 455/307/427/528 EXP.
        assert [float(v) for v in nested(result)]==[4757+455,9994+307,14696+427,27764+528,42703,42703]
        snap=d.snapshot('emmies',now=as_of,limit=640)
        p=tracked_statistics(player(snap,now=as_of,recent_snapshot=d.recent_snapshot('emmies',now=as_of)),result,now=as_of)
        assert p['recent_windows']['60']['gain']==result['tracked_exp']
        assert [r[0] for r in store.db.execute('select payload_json from diagnostic_attempts order by id')]==before
        assert not store.db.execute('select 1 from observations').fetchone()
    with Store(db,read_only=True) as store:assert Diagnostics(store).rolling_history('emmies',now=as_of)==result
