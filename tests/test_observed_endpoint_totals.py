"""Public net progress is independent of acquisition success and process lifetime."""
from copy import deepcopy
from datetime import datetime,timedelta
from fractions import Fraction
import json

import pytest

from exp_tracker.pace_intervals import collect,collect_observed,exp_interval,tracked_window
from exp_tracker.product import reading,recent_windows,player,tracked_statistics,fraction,history
from tests.test_endpoint_pace import point,missing,snapshot,NOW
from tests.test_product import tracking
from tests.test_cross_level_product import replay


def numeric(index,seconds,exp):
    from tests.test_exp_level_inference import display
    from exp_tracker.exp_requirements import requirement
    return point(index,seconds,exp,display(exp,requirement(69)['to_next']),level=69,source_identity='a'*64)


def projected(rows,seconds):
    snap=snapshot(rows,seconds)
    return snap,collect_observed(snap,now=NOW+timedelta(seconds=seconds),read=reading,max_interval_seconds=300)


def inferred_dip():
    rows=[point(1,0,876,'0.04',level=71),point(2,20,2453,'0.11',level=71),missing(3,40),
          point(4,60,2632,'0.35',level=None),point(5,80,0,'0.35',level=None),missing(6,100),
          point(7,120,7684,'0.35',level=None)]
    for r in rows:
        r['neural_level']=None
        if r['visual_level'] is None:r['visual_status']='unavailable'
    for index in (2,5):rows[index].update(status='unavailable',hud_count=2,reasons=['multiple_huds'])
    # The bad pair seeds 51; a percentage-only frame can then retain that false level.
    rows[4].update(raw_text='[0.35%]',candidate=None,status='diagnostic_percentage_only',
                   percentage_only_candidate=dict(kind='percentage_only',percentage='0.35',percentage_bp=35,trusted=False))
    return rows


@pytest.mark.parametrize('batch_size',(1,3,7))
def test_inferred_level_dip_cannot_create_a_false_cross_level_gain(batch_size):
    from exp_tracker.pace_intervals import window_endpoints
    rows=inferred_dip()
    original=deepcopy(rows);snap=snapshot(rows,120)
    assert snap['observations'][3]['experimental_level']['value']==51
    assert snap['observations'][4]['experimental_level']['status']=='retained_level'
    state={};points=[];excluded=[]
    for start in range(0,len(rows),batch_size):
        result=collect_observed(dict(snap,observations=snap['observations'][start:start+batch_size]),
            now=NOW+timedelta(seconds=120),read=reading,max_interval_seconds=300,state=state)
        points+=result['points'];excluded+=result['excluded']
    _,gain,_=window_endpoints(points,start=NOW,end=NOW+timedelta(seconds=120))
    assert gain['value']['approximate']==7684-876
    assert [p['level']['value'] for p in points]==[71,71,71]
    assert {r['event_id'] for r in excluded if r['reason']=='inferred_level_decrease'}=={'run:4','run:5'}
    assert rows==original


@pytest.mark.parametrize('boundary',('character','manual','reader'))
def test_inferred_dip_guard_respects_explicit_boundaries_and_reader_evidence(boundary):
    rows=[point(1,0,876,'0.04',level=71),point(5,60,2632,'0.35',level=None)]
    for r in rows:r['neural_level']=None
    rows[1]['visual_status']='unavailable'
    if boundary=='character':rows[1]['character_id']=2
    elif boundary=='manual':rows[1]['manual_epoch']='explicit-adjustment'
    else:rows[1].update(visual_level=51,visual_status='available')
    _,result=projected(rows,60)
    assert [p['level']['value'] for p in result['points']]==[71,51]
    assert not any(r['reason']=='inferred_level_decrease' for r in result['excluded'])


def test_inferred_dip_is_excluded_from_rolling_bars_and_cold_rebuild(tracking):
    from exp_tracker.store import Store
    from exp_tracker.diagnostics import Diagnostics
    from tests.test_product import append
    path,store,d=tracking
    for r in inferred_dip():
        pair=r.get('candidate')
        append(d,r['index'],r['raw_text'],attempted_at=r['attempted_at'],received_at=r['received_at'],
            status=r['status'],visual_level=r['visual_level'],visual_status=r['visual_status'],neural_level=None,
            candidate=[int(pair['exp']),float(pair['percentage'])] if pair else None,
            frame_sha256=r.get('frame_sha256'),localization=dict(count=r['hud_count']))
    d.append('run',dict(type='summary',trusted=False,attempts=7,interrupted=False))
    raw=[r[0] for r in store.db.execute('SELECT payload_json FROM diagnostic_attempts ORDER BY id')]
    now=NOW+timedelta(seconds=120)
    checkpoints={};result=d.rolling_history('alpha',now=now,checkpoints=checkpoints)
    assert result['tracked_exp']['approximate']==7684-876
    assert sum(b['value']['approximate'] for b in result['buckets'] if b['value'])==7684-876
    assert result['exclusion_counts']['inferred_level_decrease']==2
    assert checkpoints and d.rolling_history('alpha',now=now,checkpoints=checkpoints)==result
    with Store(path,read_only=True) as restarted:
        assert Diagnostics(restarted).rolling_history('alpha',now=now)==result
    assert raw==[r[0] for r in store.db.execute('SELECT payload_json FROM diagnostic_attempts ORDER BY id')]


@pytest.mark.parametrize('failure',['missing','multiple_huds','stale','duplicate'])
def test_failed_acquisition_does_not_erase_numeric_progress(failure):
    rows=[numeric(1,0,10000),numeric(2,60,11000),missing(3,120,source_identity='a'*64),numeric(4,300,15000)]
    if failure=='multiple_huds':rows[2].update(status='unavailable',hud_count=2,capture_acquired=True)
    elif failure=='stale':rows[2].update(status='stale_local_frame',capture_acquired=True)
    elif failure=='duplicate':rows[2]=dict(numeric(3,120,11000),frame_sha256=rows[1]['frame_sha256'])
    original=deepcopy(rows);snap,collected=projected(rows,300)
    w=recent_windows(snap,None,now=NOW+timedelta(seconds=300),collected=collected)['5']
    assert w['gain']['approximate']==5000 and w['pace']['coverage_seconds']['approximate']==300
    assert w['pace']['estimates']['exp_per_hour']['value']['approximate']==60000
    assert rows==original


def test_restart_first_failed_capture_does_not_clear_bound_numeric_endpoint():
    rows=[numeric(1,0,10000),numeric(2,20,11000),missing(1,40,source_identity='a'*64,run_id='new',event_id='new:1'),
        dict(numeric(2,60,13000),run_id='new',event_id='new:2',frame_sha256='d'*64),
        dict(numeric(3,80,14000),run_id='new',event_id='new:3',frame_sha256='e'*64)]
    snap,result=projected(rows,80)
    assert sum(fraction(exp_interval(e)['value']) for e in result['intervals'])==4000
    assert sum(fraction(exp_interval(e)['value']) for e in collect(snap,now=NOW+timedelta(seconds=80),read=reading,max_interval_seconds=300)['intervals'])==2000
    state={};streamed=[]
    for r in snap['observations']:
        streamed+=collect_observed(dict(observations=[r],percentage_progress=dict(percentage_reviews=[r['percentage_review']])),
            now=NOW+timedelta(seconds=80),read=reading,max_interval_seconds=300,state=state)['intervals']
    assert streamed==result['intervals']


@pytest.mark.parametrize('boundary',['source','character','session','unbound_restart','file_restart','loss','incompatible','level'])
def test_connection_metadata_preserves_gains_within_character_and_session_scope(boundary):
    from exp_tracker.pace_intervals import window_endpoints
    rows=[numeric(1,0,10000),numeric(2,20,11000),numeric(3,40,13000),numeric(4,60,14000)]
    if boundary in ('source','character','session'):
        field={'source':'source_identity','character':'character_id','session':'session_id'}[boundary]
        for r in rows[2:]:r[field]='b'*64 if boundary=='source' else 2
    elif boundary in ('unbound_restart','file_restart'):
        for r in rows[2:]:r.update(run_id='restart',event_id=f'restart:{r["index"]}',source_identity=None,source_kind='file' if boundary=='file_restart' else 'twitch')
    elif boundary=='loss':rows[2]=numeric(3,40,10999)
    elif boundary=='incompatible':rows[2].update(raw_text='999,999[0.66%]',candidate=dict(exp='999999',percentage='0.66'))
    else:
        rows[2]['neural_level'].update(level=70,text='70')
    snap,result=projected(rows,60)
    _,gain,_=window_endpoints(result['points'],start=NOW,end=NOW+timedelta(seconds=60))
    assert gain['value']['approximate']==(2000 if boundary=='character' else 4001 if boundary=='loss' else 4000)


def test_longer_windows_use_actual_endpoints_and_remain_nested():
    rows=[numeric(1,0,10000),numeric(2,1800,15000),numeric(3,2100,17000)]
    _,result=projected(rows,2100);gains=[exp_interval(e) for e in result['intervals']]
    amounts=[]
    for m in (5,10,15,30,60):
        w=tracked_window(gains,start=NOW+timedelta(seconds=2100)-timedelta(minutes=m),end=NOW+timedelta(seconds=2100))
        amounts.append(fraction(w['gain']) if w['gain'] else None)
    assert amounts==[2000,2000,2000,2000,7000]
    assert gains[0]['start']==rows[0]['received_at'] and gains[0]['end']==rows[1]['received_at']


def test_out_of_order_attempts_cannot_move_the_clock_back_or_overlap_gains():
    rows=[numeric(1,0,10000),numeric(2,20,11000),numeric(3,10,10500),numeric(4,15,12000),numeric(5,40,13000),numeric(6,60,14000)]
    snap,_=projected(rows,60)
    w=recent_windows(snap,None,now=NOW+timedelta(seconds=60))['5']
    assert w['gain']['approximate']==4000 and w['observed']['coverage_seconds']['approximate']==60


@pytest.mark.parametrize('switch_character',[False,True])
def test_public_gain_and_pace_share_selected_character_segments(tracking,switch_character):
    from tests.test_tracked_exp_totals import save,config
    _,store,d=tracking
    save(d,'run',1,0,3300);save(d,'run',2,20,3305)
    store.end_session('alpha',at=NOW+timedelta(seconds=21))
    if switch_character:store.select_character('alpha',store.add_character('alpha','Other character'))
    store.start_session('alpha',at=NOW+timedelta(seconds=30))
    d.begin('second','alpha',config('second'));save(d,'second',1,40,4000);save(d,'second',2,60,4010)
    now=NOW+timedelta(seconds=60);rolling=d.rolling_history('alpha',now=now)
    p=tracked_statistics(player(d.snapshot('alpha',now=now),now=now,recent_snapshot=d.recent_snapshot('alpha',now=now)),rolling,now=now)
    w=p['recent_windows']['5'];gain=1498 if switch_character else 4010*1497832//10000-3300*1497832//10000;elapsed=20 if switch_character else 60
    assert w['gain']['approximate']==w['pace']['total_gain']['approximate']==gain
    assert w['observed']['coverage_seconds']['approximate']==w['pace']['coverage_seconds']['approximate']==elapsed
    assert w['pace']['estimates']['exp_per_hour']['value']['approximate']==gain*12
    assert any(g['start']==(NOW+timedelta(seconds=20)).isoformat() and g['end']==(NOW+timedelta(seconds=40)).isoformat() for g in rolling['chart_intervals']) is not switch_character


@pytest.mark.parametrize('as_of,folders,expected,strict_expected,first_exp,last_exp',[
    ('2026-10-19T11:28:56.524233+00:00',['20261019T103818Z-62816188','20261019T112644Z-9a0733f3','20261019T112802Z-be8257c7'],18252,10375,549538,567790),
    ('2026-10-19T10:40:56.881611+00:00',['20261019T095936Z-ef8a3750','20261019T103818Z-62816188'],18162,17175,370489,388651)])
def test_saved_windows_and_public_api_share_numeric_totals(tracking,monkeypatch,as_of,folders,expected,strict_expected,first_exp,last_exp):
    import exp_tracker.server as server_module
    from tests.test_server import request
    path,store,_=tracking;now=datetime.fromisoformat(as_of);d,_=replay(store,'streamer_a',folders,as_of=now)
    raw=[r[0] for r in store.db.execute('select payload_json from diagnostic_attempts order by id')]
    recent=d.recent_snapshot('streamer_a',now=now);rolling=d.rolling_history('streamer_a',now=now)
    p=tracked_statistics(player(d.snapshot('streamer_a',now=now),now=now,recent_snapshot=recent),rolling,now=now)
    cutoff=now-timedelta(minutes=5)
    strict=[exp_interval(e) for e in collect(recent,now=now,read=reading,max_interval_seconds=300)['intervals']]
    assert tracked_window(strict,start=cutoff,end=now)['gain']['approximate']==strict_expected
    w=p['recent_windows']['5'];pace=w['pace'];observed=w['observed']
    assert w['gain']['approximate']==last_exp-first_exp==expected
    assert pace['total_gain']==w['gain']
    assert fraction(pace['estimates']['exp_per_hour']['value'])==Fraction(expected)*12
    gains=[g for g in rolling['chart_intervals'] if cutoff<=datetime.fromisoformat(g['end'])<=now
        and datetime.fromisoformat(g['end'])-datetime.fromisoformat(g['start'])<=timedelta(minutes=5)]
    assert sum(fraction(g['value']) for g in gains)==expected
    assert observed['start']==gains[0]['start'] and observed['end']==gains[-1]['end']
    assert observed['coverage_seconds']['approximate']>300
    assert [rolling['windows'][str(m)]['gain']['approximate'] for m in (5,10,15,30,60)]==sorted(rolling['windows'][str(m)]['gain']['approximate'] for m in (5,10,15,30,60))
    assert any(not r['connect_previous'] for r in history(recent)[1:])
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return now
    monkeypatch.setattr(server_module,'datetime',Clock)
    with server_module.create_server(path,port=0,diagnostic_dashboard=True,background=True) as server:
        server.publisher.settle()
        card=json.loads(request((server,None),'/api/players/streamer_a')[2])['player']
        home=json.loads(request((server,None),'/api/players')[2])['players']
        chart=json.loads(request((server,None),'/api/players/streamer_a/history')[2])
        assert card['recent_windows']['5']['gain']['approximate']==expected
        assert next(p for p in home if p['channel']=='streamer_a')['recent_windows']['5']['gain']['approximate']==expected
        assert chart['windows']['5']['gain']['approximate']==expected
    assert raw==[r[0] for r in store.db.execute('select payload_json from diagnostic_attempts order by id')]
    assert not store.db.execute('select 1 from observations').fetchone()
