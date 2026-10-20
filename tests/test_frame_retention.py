"""Synthetic fingerprint history only; never opens production data."""
from datetime import timedelta

from exp_tracker.diagnostics import Diagnostics
from exp_tracker.pace_intervals import collect,FRAME_HISTORY_SECONDS
from exp_tracker.retention import checkpoint,dumps,loads,prune
from exp_tracker.store import Store
from tests.test_endpoint_pace import missing
from tests.test_product import tracking,NOW
from tests.test_retention import chain,metrics
from tests.test_diagnostic_history import config
from tests.test_tracked_exp_totals import save


def fingerprints(state,seconds,frame,index=1,*,now=None):
    row=missing(index,seconds,frame_sha256=frame)
    return collect(dict(observations=[row],percentage_progress=dict(percentage_reviews=[
        dict(event_id=row['event_id'],progress_eligible=False,reason='synthetic_missing')])),
        now=now or NOW+timedelta(seconds=seconds),read=lambda row:None,max_interval_seconds=300,state=state)


def test_five_days_at_twenty_seconds_bound_serialized_state_through_restarts():
    state={};sizes=[]
    for index,seconds in enumerate(range(0,5*86400,20),1):
        fingerprints(state,seconds,f'{index:064x}',index)
        if index%180==0:
            # Same non-fingerprint compaction as retention, followed by a cold reload.
            state['seen_events'].clear();state['holes']=[]
            encoded=dumps(state);sizes.append(len(encoded));state=loads(encoded)
            assert len(state['seen_frames'])<=FRAME_HISTORY_SECONDS//20+1
            assert len(encoded)<400_000
    assert max(sizes[-24:])-min(sizes[-24:])<1000
    assert f'{1:064x}' not in state['seen_frames']


def test_duplicates_refresh_expiry_and_use_replay_clock_not_query_clock():
    state={};frame='a'*64;late=NOW+timedelta(days=10)
    fingerprints(state,0,frame,now=late)
    for index,seconds in enumerate((FRAME_HISTORY_SECONDS-20,FRAME_HISTORY_SECONDS+20),2):
        result=fingerprints(state,seconds,frame,index,now=late)
        assert result['excluded'][0]['reason']=='duplicate_capture'
        state=loads(dumps(state))
    fingerprints(state,2*FRAME_HISTORY_SECONDS+21,'b'*64,4,now=late)
    assert frame not in state['seen_frames']


def test_duplicate_horizon_includes_exact_boundary_only():
    for age,duplicate in ((FRAME_HISTORY_SECONDS,True),(FRAME_HISTORY_SECONDS+1,False)):
        state={};frame='a'*64
        fingerprints(state,0,frame)
        result=fingerprints(state,age,frame,2)
        assert any(item['reason']=='duplicate_capture' for item in result['excluded']) is duplicate


def test_legacy_set_grace_expires_once_without_restart_renewal():
    state={};old='a'*64
    fingerprints(state,0,'b'*64)
    state['seen_frames']={old,'b'*64};state.pop('frame_time')
    state=loads(dumps(state))
    result=fingerprints(state,20,old,2)
    assert result['excluded'][0]['reason']=='duplicate_capture'
    assert state['seen_frames']['b'*64]==NOW.timestamp()
    state=loads(dumps(state))
    fingerprints(state,FRAME_HISTORY_SECONDS+1,'c'*64,3)
    assert 'b'*64 not in state['seen_frames'] and old in state['seen_frames']
    state=loads(dumps(state))
    fingerprints(state,FRAME_HISTORY_SECONDS+21,'d'*64,4)
    assert old not in state['seen_frames']


def test_future_timestamp_cannot_expire_duplicate_protection():
    state={};frame='a'*64
    fingerprints(state,0,frame)
    fingerprints(state,10*86400,'b'*64,2,now=NOW+timedelta(seconds=20))
    result=fingerprints(state,20,frame,3)
    assert result['excluded'][0]['reason']=='duplicate_capture'
    assert state['frame_time']==(NOW+timedelta(seconds=20)).timestamp()


def test_multi_day_pruning_bounds_real_checkpoint_and_preserves_all_windows(tracking,tmp_path):
    path,store,d=tracking;now=chain(d);sizes=[]
    with Store(tmp_path/'reference.sqlite3') as reference:
        store.db.backup(reference.db);golden=Diagnostics(reference)
        prune(store,now=now,dry_run=False)
        assert metrics(Diagnostics(store),now)==metrics(golden,now)
        for first in (8,13,18,23,28):
            with Store(path) as cold:
                current=Diagnostics(cold)
                for number in range(first,first+5):
                    rid=f'chain{number}';previous=f'chain{number-1}'
                    for target in (current,golden):
                        target.rotate(previous,rid,'alpha',dict(type='summary',trusted=False,attempts=60,
                            interrupted=False,completion_reason='scheduled_rotation',next_run_id=rid),
                            config(rid,previous,interval=300))
                        for i in range(1,61):
                            index=number*60+i-1
                            save(target,rid,i,index*300,1000+index,level=65,missing=index%17==0,
                                neural_level=dict(level=65,text='65',status='numeric_candidate',score=.99))
                now=NOW+timedelta(seconds=((first+5)*60-1)*300)
                expected=metrics(golden,now)
                prune(cold,now=now,dry_run=False)
                saved=checkpoint(cold,1);state=saved['tracked']['interval_state']['diagnostic']
                assert len(state['seen_frames'])<=FRAME_HISTORY_SECONDS//300+1
                assert not state['seen_events'] and not state['holes']
                assert not saved['tracked']['percentage_state']['seen']
                assert not saved['recent']['percentage_state']['seen']
                sizes.append(len(dumps(saved)))
                assert sizes[-1]<150_000
                with Store(path,read_only=True) as restarted:
                    assert metrics(Diagnostics(restarted),now)==expected
                assert not cold.db.execute('PRAGMA foreign_key_check').fetchall()
    assert max(sizes)-min(sizes)<2000


def test_duplicate_conditional_frame_survives_rotation_pruning_and_restart(tracking,monkeypatch):
    import exp_tracker.pace_intervals as intervals
    path,store,d=tracking
    d.append('run',dict(type='summary',trusted=False,attempts=0,interrupted=True))
    duplicate=f'{580:064x}'
    for number in range(2):
        rid=f'duplicate{number}'
        if not number:d.begin(rid,'alpha',config(rid,interval=20))
        else:d.rotate('duplicate0',rid,'alpha',dict(type='summary',trusted=False,attempts=60,
            interrupted=False,completion_reason='scheduled_rotation',next_run_id=rid),config(rid,'duplicate0',interval=20))
        for i in range(1,61):
            index=number*60+i-1;changes={}
            if index==75:
                changes=dict(neural=dict(text='401.128122.82X1'),candidate=None,
                    status='malformed_or_unavailable',visual_level=None,frame_sha256=duplicate)
            save(d,rid,i,index*20,2200+index+(7 if index>=75 else 0),level=67,**changes)
    now=NOW+timedelta(hours=24,minutes=5,seconds=1190)
    results=[];original=intervals.collect
    def record(*args,**kwargs):
        result=original(*args,**kwargs);results.append(result);return result
    monkeypatch.setattr(intervals,'collect',record)
    expected=metrics(d,now)
    assert expected['tracked_exp'] is not None
    prune(store,now=now,dry_run=False)
    assert duplicate in checkpoint(store,1)['tracked']['interval_state']['diagnostic']['seen_frames']
    assert not store.db.execute("SELECT 1 FROM diagnostic_attempts WHERE run_id='duplicate0'").fetchone()
    results.clear()
    with Store(path,read_only=True) as cold:
        assert metrics(Diagnostics(cold),now)==expected
    excluded=[item for result in results for item in result['excluded']]
    assert any(item['event_id']=='duplicate1:16' and item['reason']=='duplicate_capture' for item in excluded)
    recovery=[item for result in results for item in result['recoveries'] if item['event_id']=='duplicate1:16']
    assert recovery and all(item['status']=='rejected' and item['reason']=='duplicate_capture' for item in recovery)
