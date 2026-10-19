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
from tests.test_diagnostic_history import config
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
    assert len(checkpoints)==2 and ('tracked','alpha',1,()) in checkpoints


@pytest.mark.parametrize('channel',['emmies','niru','telfer1'])
def test_saved_logs_match_full_replay_while_streamed(tmp_path,channel):
    """Real missing/malformed OCR, level-ups, rotation, restarts and long inactivity.

    Bounded for the suite: resume every 6 records, compare every 150 and at the end.
    private/incremental-work/sweep.py compares far more often (see docs).
    """
    paths=sorted(Path(SAVED).glob(f'*/{channel}/**/capture.jsonl'),key=lambda p:json.loads(p.read_text().splitlines()[1])['attempted_at'])
    if not paths:pytest.skip('private saved capture unavailable')
    checkpoints={};steps=0;now=None
    with Store(tmp_path/'saved.sqlite3') as store:
        store.add_channel(channel);cid=store.add_character(channel,'Saved review');store.select_character(channel,cid)
        store.start_session(channel,at=datetime.fromisoformat(json.loads(paths[0].read_text().splitlines()[1])['attempted_at']))
        d=Diagnostics(store)
        for path in paths:
            records=[json.loads(s) for s in path.read_text().splitlines()];rid=records[0]['run_id'];d.begin(rid,channel,records[0])
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
