from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from exp_tracker.diagnostics import Diagnostics
from exp_tracker.exp_requirements import community_table
from exp_tracker.store import Store
from exp_tracker.video import Source


@pytest.fixture
def multi(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(Path('tools').resolve()))
    module=importlib.import_module('multi_alpha')
    monkeypatch.setattr(module.shadow,'ROOT',tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module,'configure_tesseract',lambda:None)
    monkeypatch.setattr(module.shadow.shutil,'which',lambda _: 'ffmpeg')
    real_find=module.importlib.util.find_spec
    monkeypatch.setattr(module.importlib.util,'find_spec',lambda name: object() if name=='streamlink' else real_find(name))
    executable=tmp_path/'private/rapidocr/.venv/Scripts/python.exe'
    executable.parent.mkdir(parents=True);executable.touch()
    table=tmp_path/'src/exp_tracker/data/community-exp-v2.json'
    table.parent.mkdir(parents=True);table.write_text(json.dumps(community_table()[0]))
    video=tmp_path/'synthetic.mp4';video.touch()
    config=dict(database='private/shared.sqlite3',port=0,streams=[dict(channel=c,character=f'{c} character',source='file',file=str(video),interval=15,count=2) for c in ('alpha','beta')])
    path=tmp_path/'private/config.json';path.write_text(json.dumps(config))
    now=[0.0];calls=[]
    original=module.schedule
    def sleep(seconds): now[0]+=seconds
    monkeypatch.setattr(module,'schedule',lambda lanes,perform,emit,**kw:original(lanes,perform,emit,clock=lambda:now[0],sleep=sleep,simulated=True,**kw))
    def capture(args,source,requirements,index,**kwargs):
        calls.append((args.tracking_channel,index,now[0]));now[0]+=1
        return record(index)
    monkeypatch.setattr(module.shadow,'capture_attempt',capture)
    return module,path,config,calls,now


def record(index,**changes):
    result=dict(type='attempt',index=index,trusted=False,current=True,status='diagnostic_percentage_only',
        attempted_at=datetime.now(timezone.utc).isoformat(),received_at=datetime.now(timezone.utc).isoformat(),
        source=dict(kind='file',channel=None),neural=dict(text='[33.05%]'),candidate=None,visual_level=64,
        visual_status='available',localization=dict(count=1))
    result.update(changes);return result


def main(multi,*extra):
    module,path,_,_,_=multi
    return module.main(['--config',str(path),'--exit-after-capture',*extra])


def test_shared_database_runs_restart_and_read_only_directory(multi):
    module,path,config,calls,_=multi
    assert main(multi)==0
    assert [r[:2] for r in calls]==[('alpha',1),('beta',1),('alpha',2),('beta',2)]
    db=path.parent/'shared.sqlite3'
    with Store(db,read_only=True) as store:
        ids={c:store.state(c)['session']['id'] for c in ('alpha','beta')}
        assert ids['alpha']!=ids['beta']
        runs=[r[0] for r in store.db.execute('SELECT run_id FROM diagnostic_runs')]
        assert len(set(runs))==2
        assert store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==0
        for c in ids:
            s=Diagnostics(store).snapshot(c)
            assert len(s['observations'])==2 and s['run_status']=='completed'
            assert all(r['assigned_channel']==c for r in s['observations'])
        cards=Diagnostics(store).directory({})['streams']
        assert [r['channel'] for r in cards]==['alpha','beta']
    assert main(multi)==0
    with Store(db,read_only=True) as store:
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]==8
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_runs').fetchone()[0]==4
        assert {c:store.state(c)['session']['id'] for c in ids}==ids


def test_capture_failures_do_not_starve_other_lane_and_no_overlap(multi,monkeypatch):
    module,path,_,_,_=multi
    active=[False];calls=[]
    def capture(args,source,requirements,index,**kwargs):
        assert not active[0];active[0]=True;calls.append(args.tracking_channel)
        active[0]=False
        if args.tracking_channel=='beta':raise OSError('secret playback URL must not escape')
        return record(index)
    monkeypatch.setattr(module.shadow,'capture_attempt',capture)
    assert main(multi)==0 and calls==['alpha','beta','alpha','beta']
    with Store(path.parent/'shared.sqlite3',read_only=True) as store:
        failed=Diagnostics(store).snapshot('beta')['observations']
        assert all(r['status']=='capture_failed' for r in failed)
        assert 'secret' not in json.dumps(failed)
        assert len(Diagnostics(store).snapshot('alpha')['observations'])==2


def test_due_time_skips_backlog_and_never_replays_old_frames(multi):
    module,_,_,_,_=multi
    original=importlib.import_module('multi_alpha').schedule
    # Fixture scheduler wraps the original with a virtual clock.
    lanes=[dict(channel=c,args=SimpleNamespace(count=2,interval=15,start=100),source=Source('file','unused')) for c in ('alpha','beta')]
    seeks=[]
    def perform(lane,index,seek):
        seeks.append((lane['channel'],seek));multi[4][0]+=40
        return record(index)
    assert original(lanes,perform,lambda *_:None) is False
    assert [r[0] for r in seeks]==['alpha','beta','alpha','beta']
    assert [r[1] for r in seeks]==[100,140,180,220]
    assert all(lane['skipped']>0 for lane in lanes)


def test_ownership_assignment_mismatch_and_lock_are_explicit(multi):
    module,path,config,_,_=multi
    db=path.parent/'shared.sqlite3'
    with Store(db):pass
    before=db.read_bytes()
    assert main(multi)==1 and db.read_bytes()==before
    db.unlink()  # Empty synthetic test database only.
    assert main(multi)==0
    with module.ownership(db):
        with pytest.raises(ValueError,match='coordinator'):
            with module.ownership(db):pass
    config['streams'][0]['character']='Wrong selection';path.write_text(json.dumps(config))
    assert main(multi)==1
    with Store(db,read_only=True) as store:
        assert store.state('alpha')['characters'][0]['label']=='alpha character'


def test_sqlite_failure_preserves_log_and_other_channel_and_allows_replay(multi,monkeypatch):
    module,path,_,_,_=multi
    original=module.shadow.capture_attempt
    injected=[False]
    def fail(args,*rest,**kwargs):
        if not injected[0]:
            with Store(args.db) as store:
                store.db.execute("""CREATE TRIGGER fail_alpha BEFORE INSERT ON diagnostic_attempts
                    WHEN (SELECT s.login FROM diagnostic_runs r JOIN streamers s ON s.id=r.streamer_id WHERE r.run_id=NEW.run_id)='alpha'
                    BEGIN SELECT RAISE(ABORT,'injected failure'); END""")
            injected[0]=True
        return original(args,*rest,**kwargs)
    monkeypatch.setattr(module.shadow,'capture_attempt',fail)
    assert main(multi)==1
    db=path.parent/'shared.sqlite3'
    with Store(db) as store:
        assert Diagnostics(store).snapshot('alpha')['run_status']=='unfinished'
        assert len(Diagnostics(store).snapshot('beta')['observations'])==2
        store.db.execute('DROP TRIGGER fail_alpha')
        log=next((path.parent/'multi-alpha/runs').glob('*/alpha/capture.jsonl'))
        assert Diagnostics(store).replay('alpha',log)['inserted_records']==2
        assert Diagnostics(store).replay('alpha',log)['inserted_records']==0


def test_interrupt_closes_coherent_runs_and_stops_further_jobs(multi,monkeypatch):
    module,path,_,_,_=multi
    count=[0]
    def interrupt(args,source,requirements,index,**kw):
        count[0]+=1
        if count[0]==2:raise KeyboardInterrupt
        return record(index)
    monkeypatch.setattr(module.shadow,'capture_attempt',interrupt)
    assert main(multi)==130 and count[0]==2
    with Store(path.parent/'shared.sqlite3',read_only=True) as store:
        for c in ('alpha','beta'):
            assert Diagnostics(store).snapshot(c)['run_status']=='interrupted'


@pytest.mark.parametrize('change',[
    {'streams':[]},{'port':-1},{'streams':[{}]*26},{'extra':'x'}])
def test_bad_configuration_never_creates_database(multi,change):
    _,path,config,_,_=multi
    config.update(change);path.write_text(json.dumps(config))
    assert main(multi)==1 and not (path.parent/'shared.sqlite3').exists()


def test_live_authorization_and_check_do_not_connect_or_write(multi,monkeypatch):
    module,path,config,calls,_=multi
    for row in config['streams']:
        row.update(source='twitch',authorized=False);row.pop('file')
    path.write_text(json.dumps(config))
    assert main(multi,'--check')==1
    for row in config['streams']:row['authorized']=True
    path.write_text(json.dumps(config))
    assert main(multi,'--check')==0
    assert not calls and not (path.parent/'shared.sqlite3').exists()


def test_mid_run_character_switch_stops_only_that_lane(multi,monkeypatch):
    module,path,_,_,_=multi
    original=module.shadow.capture_attempt
    changed=[False]
    def switch(args,*rest,**kwargs):
        if args.tracking_channel=='alpha' and not changed[0]:
            with Store(args.db) as store:
                char=store.add_character('alpha','Explicit administrator switch')
                store.select_character('alpha',char)
                store.start_session('alpha',expected_character_id=char)
            changed[0]=True
        return original(args,*rest,**kwargs)
    monkeypatch.setattr(module.shadow,'capture_attempt',switch)
    assert main(multi)==1
    with Store(path.parent/'shared.sqlite3',read_only=True) as store:
        assert Diagnostics(store).snapshot('alpha')['observations']==[]
        assert len(Diagnostics(store).snapshot('beta')['observations'])==2
        assert store.db.execute("SELECT COUNT(*) FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id JOIN streamers s ON s.id=r.streamer_id WHERE s.login='alpha'").fetchone()[0]==0


def test_continuous_multiple_rotations_persist_real_runs_without_real_waiting(multi):
    module,path,config,calls,_=multi
    config['streams'][1]['interval']=25
    path.write_text(json.dumps(config))
    assert main(multi,'--continuous','--max-attempts','125')==0
    assert len(calls)==250
    with Store(path.parent/'shared.sqlite3',read_only=True) as store:
        runs=list(store.db.execute('SELECT * FROM diagnostic_runs ORDER BY rowid'))
        assert len(runs)==6 and len({r['run_id'] for r in runs})==6
        assert sorted(store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts WHERE run_id=?',(r['run_id'],)).fetchone()[0] for r in runs)==[5,5,60,60,60,60]
        summaries=[json.loads(r['summary_json']) for r in runs]
        assert sum(s['completion_reason']=='scheduled_rotation' for s in summaries)==4
        for r in runs:
            rows=list(store.db.execute('SELECT attempt_index,payload_json FROM diagnostic_attempts WHERE run_id=? ORDER BY attempt_index',(r['run_id'],)))
            assert [row[0] for row in rows]==list(range(1,len(rows)+1))
            assert all(json.loads(row[1])['timing_mode']=='simulated' and json.loads(row[1])['requested_at'] is None for row in rows)
        ids={c:store.state(c)['session']['id'] for c in ('alpha','beta')}
        for c in ids:
            assert not Diagnostics(store).snapshot(c)['percentage_progress']['current_pace']
        assert store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==0
    assert main(multi,'--continuous','--max-attempts','1')==0
    with Store(path.parent/'shared.sqlite3',read_only=True) as store:
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]==252
        assert {c:store.state(c)['session']['id'] for c in ids}==ids
        configs=[json.loads(r[0]) for r in store.db.execute('SELECT configuration_json FROM diagnostic_runs ORDER BY rowid DESC LIMIT 2')]
        assert all(r['start_reason']=='process_start' and r['previous_run_id'] is None for r in configs)


def test_fast_test_is_explicit_and_never_allowed_for_twitch(multi):
    _,path,config,_,_=multi
    for row in config['streams']: row['interval']=3
    path.write_text(json.dumps(config))
    assert main(multi,'--check')==1
    assert main(multi,'--offline-fast-test','--check')==0
    assert main(multi,'--offline-fast-test')==0
    config['streams'][1].update(source='twitch',authorized=True)
    path.write_text(json.dumps(config))
    assert main(multi,'--offline-fast-test','--check')==1


def test_25_assignments_and_monotonic_stop_condition(multi):
    _,path,config,calls,_=multi
    template=config['streams'][0]
    config['streams']=[{**template,'channel':f'source_{i}','character':f'Character {i}'} for i in range(25)]
    path.write_text(json.dumps(config))
    assert main(multi,'--continuous','--stop-after-seconds','26')==0
    assert len(calls)==26 and len({c[0] for c in calls})==25
    with Store(path.parent/'shared.sqlite3',read_only=True) as store:
        assert store.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==25
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]==26


def test_continuous_interrupt_finalizes_and_does_not_run_more_jobs(multi,monkeypatch):
    module,path,_,calls,_=multi
    original=module.shadow.capture_attempt
    def capture(*args,**kw):
        if len(calls)==121: raise KeyboardInterrupt
        return original(*args,**kw)
    monkeypatch.setattr(module.shadow,'capture_attempt',capture)
    assert main(multi,'--continuous')==130
    with Store(path.parent/'shared.sqlite3',read_only=True) as store:
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]==122
        assert not store.db.execute('SELECT 1 FROM diagnostic_runs WHERE summary_json IS NULL').fetchone()


def test_continuous_overload_rotates_despite_isolated_failed_captures(multi,monkeypatch):
    module,path,config,calls,clock=multi
    original=module.shadow.capture_attempt
    config['streams'][1]['interval']=8;path.write_text(json.dumps(config))
    def capture(args,*rest,**kw):
        result=original(args,*rest,**kw);clock[0]+=20
        if args.tracking_channel=='beta' and result['index']%3==0:raise OSError('private path/URL not for HTTP')
        return result
    monkeypatch.setattr(module.shadow,'capture_attempt',capture)
    assert main(multi,'--continuous','--max-attempts','125')==0
    assert len(calls)==250 and {r[0] for r in calls}=={'alpha','beta'}
    with Store(path.parent/'shared.sqlite3',read_only=True) as store:
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_runs').fetchone()[0]==6
        for channel in ('alpha','beta'):
            rows=Diagnostics(store).snapshot(channel)['observations']
            assert any(r['skipped_deadlines']>0 for r in rows)
            assert all(r['actual_interval_seconds'] is None or r['actual_interval_seconds']>=20 for r in rows)
        assert any(r['status']=='capture_failed' for r in Diagnostics(store).snapshot('beta')['observations'])
