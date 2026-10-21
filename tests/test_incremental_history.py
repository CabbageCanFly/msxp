"""Resumed causal checkpoints must equal a full causal replay exactly."""
from datetime import datetime,timedelta
import json
from pathlib import Path

import pytest

from exp_tracker import rolling_history
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.product import player
from exp_tracker.store import Store
from tests.test_product import tracking,NOW
from tests.test_diagnostic_history import config,rotate
from tests.test_tracked_exp_totals import save
from tests.test_cross_level_product import SAVED


def same(d,channel,now,checkpoints):
    """Incremental and full replay: totals, buckets, windows, chart, receipts, rows and ETA inputs."""
    fast=d.rolling_history(channel,now=now,checkpoints=checkpoints);full=d.rolling_history(channel,now=now)
    assert fast==full
    # This scenario includes losses: net gains need not grow with the lookback.
    recent=d.recent_snapshot(channel,now=now,checkpoints=checkpoints);reference=d.recent_snapshot(channel,now=now)
    assert recent==reference
    snap=d.snapshot(channel,now=now,limit=640)
    assert player(snap,now=now,recent_snapshot=recent)==player(snap,now=now,recent_snapshot=reference)
    return fast


def scenario(store,d):
    """Rotation, a manual restart and a source change around ordinary and unsafe evidence."""
    d.begin('a','alpha',config('a',interval=20))
    for i in range(1,61):
        changes={}
        if i==10:changes['missing']=True
        if i==20:changes['frame_sha256']=f'{19*20:064x}'  # Repeated frame: duplicate capture.
        bp=3300+i*5-(150 if 30<=i<=31 else 0)  # Two-capture loss, then recovery.
        level=65 if i>=45 else 64
        yield 'a',i,(i-1)*20,(i-44)*7 if level==65 else bp,dict(level=level,**changes)
    yield 'rotate',None,None,None,None
    for i in range(1,31):yield 'b',i,(59+i)*20,200+i*7,dict(level=65)
    yield 'restart',None,None,None,None
    for i in range(1,21):yield 'c',i,(95+i)*20,500+i*7,dict(level=65,source=dict(kind='file',channel=None) if i>10 else dict(kind='twitch',channel='alpha'))


def build(store,d,checkpoints,*,compare=True):
    last=None
    for run,index,seconds,bp,changes in scenario(store,d):
        if run=='rotate':
            d.rotate('a','b','alpha',dict(type='summary',trusted=False,attempts=60,interrupted=False,
                completion_reason='scheduled_rotation',next_run_id='b'),config('b','a',interval=20));continue
        if run=='restart':
            d.append('b',dict(type='summary',trusted=False,attempts=30,interrupted=True));d.begin('c','alpha',config('c',interval=20));continue
        save(d,run,index,seconds,bp,**changes);last=NOW+timedelta(seconds=seconds)
        if compare:same(d,'alpha',last,checkpoints)
        else:d.rolling_history('alpha',now=last,checkpoints=checkpoints);d.recent_snapshot('alpha',now=last,checkpoints=checkpoints)
    return last


def test_every_append_matches_full_replay_across_rotation_restart_loss_level_and_source(tracking):
    _,store,d=tracking;checkpoints={}
    last=build(store,d,checkpoints)
    assert {k[0] for k in checkpoints}=={'tracked','recent'}
    # Window expiry, inactivity and the next day with no new capture; then a clock regression.
    for delta in (1,301,3601,3901,86401,90001):same(d,'alpha',last+timedelta(seconds=delta),checkpoints)
    same(d,'alpha',last,checkpoints)


def test_ordinary_capture_reprocesses_only_the_open_run(tracking,monkeypatch):
    _,store,d=tracking;checkpoints={}
    last=build(store,d,checkpoints,compare=False)
    seen=[];original=rolling_history.run_rows
    monkeypatch.setattr(rolling_history,'run_rows',lambda *a,**k:seen.append(a[2]['run_id']) or original(*a,**k))
    save(d,'c',21,(95+21)*20,500+21*7,level=65,source=dict(kind='file',channel=None));now=last+timedelta(seconds=20)
    d.rolling_history('alpha',now=now,checkpoints=checkpoints);d.recent_snapshot('alpha',now=now,checkpoints=checkpoints)
    assert seen==['c','c']
    seen.clear();d.rolling_history('alpha',now=now)
    assert seen==['a','b','c']


def test_late_appends_summaries_and_out_of_band_row_loss_rebuild(tracking,monkeypatch):
    path,store,d=tracking;checkpoints={}
    d.begin('one','alpha',config('one',interval=20))
    for i in range(1,6):save(d,'one',i,i*20,3300+i*5)
    # A newer run starts while 'one' stays unfinished; the model still allows appends to it.
    d.begin('two','alpha',config('two',interval=20))
    for i in range(1,4):save(d,'two',i,200+i*20,3400+i*5)
    now=NOW+timedelta(seconds=260);same(d,'alpha',now,checkpoints)
    save(d,'one',6,120,3330);same(d,'alpha',now,checkpoints)
    d.append('one',dict(type='summary',trusted=False,attempts=6,interrupted=True));same(d,'alpha',now,checkpoints)
    seen=[];original=rolling_history.run_rows
    monkeypatch.setattr(rolling_history,'run_rows',lambda *a,**k:seen.append(a[2]['run_id']) or original(*a,**k))
    with store._transaction():store.db.execute("DELETE FROM diagnostic_attempts WHERE run_id='one' AND attempt_index=6")
    same(d,'alpha',now,checkpoints)
    assert seen.count('one')==4  # Both incremental reads rebuilt from the first run, like the full ones.


def test_selected_character_change_and_work_limit_never_resume_old_state(tracking,monkeypatch):
    _,store,d=tracking;checkpoints={}
    d.begin('one','alpha',config('one',interval=20))
    for i in range(1,8):save(d,'one',i,i*20,3300+i*5)
    now=NOW+timedelta(seconds=160);same(d,'alpha',now,checkpoints)
    monkeypatch.setattr(rolling_history,'MAX_EVENTS',5)
    assert same(d,'alpha',now,checkpoints)['status']=='history_limit'
    monkeypatch.setattr(rolling_history,'MAX_EVENTS',65536)
    other=store.add_character('alpha','Another character');store.select_character('alpha',other)
    assert same(d,'alpha',now,checkpoints)['tracked_exp'] is None


def test_checkpoint_store_is_bounded(tracking,monkeypatch):
    _,_,d=tracking;d.begin('one','alpha',config('one',interval=20))
    for i in range(1,4):save(d,'one',i,i*20,3300+i*5)
    d.append('one',dict(type='summary',trusted=False,attempts=3,interrupted=False))
    monkeypatch.setattr(rolling_history,'MAX_CHECKPOINTS',2)
    checkpoints={('stale',n):{} for n in range(2)}
    d.rolling_history('alpha',now=NOW+timedelta(seconds=80),checkpoints=checkpoints)
    assert len(checkpoints)==2 and ('tracked','alpha',1,((),0)) in checkpoints


def test_100_idle_channels_reuse_checkpoints_and_historical_eta_cache(tracking,monkeypatch):
    _,store,d=tracking;checkpoints={};etas={};channels=[f'cache{i}' for i in range(100)]
    now=NOW+timedelta(hours=3)
    for channel in channels:
        store.add_channel(channel);cid=store.add_character(channel,'Synthetic character')
        store.select_character(channel,cid);store.start_session(channel,at=NOW)
        d.begin(channel,channel,config(channel,interval=20))
        for i in (1,2):save(d,channel,i,i*20,3300+i*5,source=dict(kind='twitch',channel=channel))
        d.append(channel,dict(type='summary',trusted=False,attempts=2,interrupted=False))
        d.rolling_history(channel,now=now,checkpoints=checkpoints)
        d.recent_snapshot(channel,now=now,checkpoints=checkpoints,eta_cache=etas)
    seen=[];original=rolling_history.run_rows
    monkeypatch.setattr(rolling_history,'run_rows',lambda *a,**k:seen.append(a[2]['run_id']) or original(*a,**k))
    for channel in channels:
        d.rolling_history(channel,now=now,checkpoints=checkpoints)
        d.recent_snapshot(channel,now=now,checkpoints=checkpoints,eta_cache=etas)
    assert not seen  # Neither the causal prefix nor the old ETA history was replayed.


def saved_logs(root,channel):
    """Each saved capture log read once, as records in run order. Live capture may still
    append: a trailing unfinished line and a header-only new log are not yet part of it."""
    logs=[]
    for path in Path(root).glob(f'*/{channel}/**/capture.jsonl'):
        text=path.read_text()
        records=[json.loads(s) for s in text[:text.rfind('\n')+1].splitlines()]
        if len(records)>1:logs.append(records)
    return sorted(logs,key=lambda records:records[1]['attempted_at'])


def test_saved_logs_are_read_once_in_run_order(tmp_path):
    def write(path,*records,tail=''):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(''.join(json.dumps(r)+'\n' for r in records)+tail)
    header=lambda run:dict(type='configuration',run_id=run)
    attempt=lambda second:dict(type='attempt',attempted_at=(NOW+timedelta(seconds=second)).isoformat())
    write(tmp_path/'b/alpha/capture.jsonl',header('late'),attempt(60),tail='{"type": "attempt", "attem')  # Being written.
    write(tmp_path/'a/alpha/run/capture.jsonl',header('early'),attempt(0),attempt(20),dict(type='summary'))
    write(tmp_path/'c/alpha/capture.jsonl',header('new'))  # Created, no attempt yet.
    logs=saved_logs(tmp_path,'alpha')
    assert [r[0]['run_id'] for r in logs]==['early','late'] and [len(r) for r in logs]==[4,2]
    write(tmp_path/'b/alpha/capture.jsonl',header('late'),attempt(60),attempt(80))  # Later appends do not reach this snapshot.
    assert [len(r) for r in logs]==[4,2] and logs[1][1]['attempted_at']==(NOW+timedelta(seconds=60)).isoformat()


@pytest.mark.parametrize('channel',['emmies','niru','telfer1'])
def test_saved_logs_match_full_replay_while_streamed(tmp_path,channel):
    """Real missing/malformed OCR, level-ups, rotation, restarts and long inactivity.

    Bounded for the suite: resume every 6 records, compare every 150 and at the end.
    private/incremental-work/sweep.py compares far more often (see docs).
    """
    logs=saved_logs(SAVED,channel)  # One consistent snapshot: rotations during the replay do not change it.
    if not logs:pytest.skip('private saved capture unavailable')
    checkpoints={};steps=0;now=None
    with Store(tmp_path/'saved.sqlite3') as store:
        store.add_channel(channel);cid=store.add_character(channel,'Saved review');store.select_character(channel,cid)
        store.start_session(channel,at=datetime.fromisoformat(logs[0][1]['attempted_at']))
        d=Diagnostics(store)
        for records in logs:
            rid=records[0]['run_id'];d.begin(rid,channel,records[0])
            for r in records[1:]:
                d.append(rid,r);steps+=1
                if r['type']=='attempt':now=datetime.fromisoformat(r.get('received_at') or r['attempted_at'])
                if steps%150==0:same(d,channel,now,checkpoints)
                elif steps%6==0:d.rolling_history(channel,now=now,checkpoints=checkpoints);d.recent_snapshot(channel,now=now,checkpoints=checkpoints)
        for delta in (0,3901,90001):same(d,channel,now+timedelta(seconds=delta),checkpoints)


def test_homepage_and_character_api_share_one_card_computation_per_revision(tracking,monkeypatch):
    import exp_tracker.diagnostics as diagnostics_module
    import exp_tracker.server as server_module
    from tests.test_server import request
    class Clock(datetime):
        at=NOW+timedelta(seconds=100)
        @classmethod
        def now(cls,tz=None):return cls.at
    monkeypatch.setattr(server_module,'datetime',Clock);monkeypatch.setattr(diagnostics_module,'datetime',Clock)
    path,_,d=tracking;d.begin('one','alpha',config('one',interval=20))
    for i in range(1,5):save(d,'one',i,i*20,3300+i*5)
    calls=[];original=diagnostics_module.player
    monkeypatch.setattr(diagnostics_module,'player',lambda *a,**k:calls.append(1) or original(*a,**k))
    with server_module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        for url in ('/api/players','/api/players/alpha','/api/players/alpha','/api/players'):
            assert request((server,None),url)[0]==200
        assert len(calls)==1
        save(d,'one',5,100,3330)
        home=json.loads(request((server,None),'/api/players')[2]);character=json.loads(request((server,None),'/api/players/alpha')[2])
        assert len(calls)==2 and character['history'][-1]['timestamp']==(NOW+timedelta(seconds=100)).isoformat()
        assert home['players'][0]['latest_attempt_at']==character['player']['latest_attempt_at']


def test_cold_restore_of_a_session_beyond_4096_rows_trims_instead_of_failing(tracking):
    """Saved Telfer1 reached this branch and every build raised NameError (shadowed module imports)."""
    path,store,d=tracking;run='r0';d.begin(run,'alpha',config(run))
    for n in range(4140):  # 69 rotated runs of 60, as the coordinator writes them.
        if n and n%60==0:rotate(d,run,f'r{n//60}');run=f'r{n//60}'
        save(d,run,n%60+1,n+1,3300+n//10)
    now=NOW+timedelta(seconds=4140+70*60)  # No attempt in the last 65 minutes: restore from the whole session.
    recent=d.recent_snapshot('alpha',now=now)
    assert recent==d.recent_snapshot('alpha',now=now,checkpoints={})
    assert recent['recent_history_status']=='ready'


def test_checkpoint_keeps_the_endpoint_before_the_window_for_the_boundary_pair(tracking):
    """Saved Telfer1 at a rotation: a checkpoint saved at the comparison time had dropped the
    last reading before the 24h start, so only the full replay saw the boundary-crossing pair."""
    path,store,d=tracking;d.begin('r0','alpha',config('r0'))
    for i in range(1,61):save(d,'r0',i,20*i,3300+i)  # 20..1200 s.
    rotate(d,'r0','r1')
    for i in range(1,61):save(d,'r1',i,85800+20*i,3400+i)  # The next day, 85820..87000 s.
    rotate(d,'r1','r2');save(d,'r2',1,87010,3470)
    now=NOW+timedelta(seconds=87010)  # 24h start at 610 s: between readings at 600 and 620 s.
    checkpoints={}
    d.rolling_history('alpha',now=now,checkpoints=checkpoints)  # r1 settles now: checkpoint saved at this clock.
    assert checkpoints[('tracked','alpha',1,((),0))]['now']==now
    full=d.rolling_history('alpha',now=now)
    assert full['boundary_intervals_excluded']==0
    assert d.rolling_history('alpha',now=now,checkpoints=checkpoints)==full
    later=now+timedelta(seconds=5)  # Later windows resume from it too.
    assert d.rolling_history('alpha',now=later,checkpoints=checkpoints)==d.rolling_history('alpha',now=later)


@pytest.mark.parametrize('cutoff_seconds',[10,30,60])
def test_checkpoint_preserves_exclusions_when_old_endpoint_pairs_are_pruned(tracking,cutoff_seconds):
    _,_,d=tracking
    d.begin('old','alpha',config('old'))
    save(d,'old',1,0,3300,level=65)
    save(d,'old',2,20,3310,level=64)
    save(d,'old',3,40,3320,level=64)
    d.append('old',dict(type='summary',trusted=False,attempts=3,interrupted=False))
    now=NOW+timedelta(days=1,seconds=cutoff_seconds);checkpoints={}
    for delta in (0,0,40,40):
        at=now+timedelta(seconds=delta)
        full=d.rolling_history('alpha',now=at)
        assert full['exclusion_counts']['observed_level_decrease']==1
        assert d.rolling_history('alpha',now=at,checkpoints=checkpoints)==full
