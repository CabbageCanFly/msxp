from datetime import datetime, timezone
import importlib
import json
import os
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
    monkeypatch.setenv('MSXP_PRELOAD_STREAMLINK','0')  # Scheduler tests use fake capture, never a real launcher.
    monkeypatch.syspath_prepend(str(Path('tools').resolve()))
    module=importlib.import_module('multi_alpha')
    monkeypatch.setattr(module.shadow,'ROOT',tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module,'configure_tesseract',lambda:None)
    monkeypatch.setattr(module.shadow.shutil,'which',lambda _: 'ffmpeg')
    real_find=module.importlib.util.find_spec
    monkeypatch.setattr(module.importlib.util,'find_spec',lambda name: object() if name=='streamlink' else real_find(name))
    executable=tmp_path/'private/rapidocr/.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')  # As shadow_capture expects.
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


def test_each_capture_line_names_the_lane_character(multi,capsys):
    assert main(multi)==0
    out=capsys.readouterr().out
    for channel in ('alpha','beta'):
        for index in (1,2):
            assert f'{channel} [{channel} character] #{index:02d} frame=acquired' in out


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
    servers=[]
    create_server=module.create_server
    def server(*args,**kw):
        assert kw.get('background') is True
        result=create_server(*args,**kw);servers.append(result);return result
    monkeypatch.setattr(module,'create_server',server)
    injected=[False]
    def fail(args,*rest,**kwargs):
        if not injected[0]:
            with Store(args.db) as store:
                store.db.execute("""CREATE TRIGGER fail_alpha BEFORE INSERT ON diagnostic_attempts
                    WHEN (SELECT s.login FROM diagnostic_runs r JOIN streamers s ON s.id=r.streamer_id WHERE r.run_id=NEW.run_id)='alpha'
                    BEGIN SELECT RAISE(ABORT,'injected failure'); END""")
            injected[0]=True
        elif args.tracking_channel=='beta':
            with Store(args.db,read_only=True) as store:
                snap=Diagnostics(store).snapshot('alpha',active_runs=servers[0].active_run_ids.copy())
            assert snap['run_status']=='unfinished'  # A stopped lane is no longer a live worker.
            assert servers[0].coordinator_status['alpha']['state']=='stopped'
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


def test_coordinator_never_prunes_but_owns_its_logs_for_the_separate_worker(multi,monkeypatch):
    from exp_tracker import retention
    module,path,_,calls,_=multi
    monkeypatch.setattr(retention,'prune',lambda *a,**k:pytest.fail('capture must not run retention inline'))
    assert main(multi,'--continuous','--retention-24h','--max-attempts','2')==1  # Refused before any capture.
    assert not calls and not (path.parent/'shared.sqlite3').exists()
    assert main(multi,'--continuous','--max-attempts','2')==0 and len(calls)==4
    assert list((path.parent/'multi-alpha/runs').glob('*/.retention-owner.json'))


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


@pytest.mark.parametrize('count',[25,40])
def test_many_assignments_and_monotonic_stop_condition(multi,count):
    _,path,config,calls,_=multi
    template=config['streams'][0]
    config['streams']=[{**template,'channel':f'source_{i}','character':f'Character {i}'} for i in range(count)]
    path.write_text(json.dumps(config))
    assert main(multi,'--continuous','--stop-after-seconds',str(count+1))==0
    assert len(calls)==count+1 and len({c[0] for c in calls})==count
    with Store(path.parent/'shared.sqlite3',read_only=True) as store:
        assert store.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==count
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]==count+1


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


def test_rotation_transaction_failure_keeps_old_run_identity_and_reports_stopped(multi,monkeypatch):
    module,path,_,calls,_=multi
    original=Diagnostics.rotate
    failed=[]
    servers=[]
    create_server=module.create_server
    def server(*args,**kw):
        result=create_server(*args,**kw);servers.append(result);return result
    monkeypatch.setattr(module,'create_server',server)
    capture=module.shadow.capture_attempt
    def check_stopped(*args,**kw):
        if failed:
            assert servers[0].coordinator_status['beta']['state']=='stopped'
            assert failed[0] not in servers[0].active_run_ids
        return capture(*args,**kw)
    monkeypatch.setattr(module.shadow,'capture_attempt',check_stopped)
    def rotate(self,previous,following,channel,summary,configuration):
        if channel=='beta':
            failed.append(previous)
            self.db.execute(f"""CREATE TRIGGER fail_rotation BEFORE INSERT ON diagnostic_runs
                WHEN NEW.run_id='{following}' BEGIN SELECT RAISE(ABORT,'injected rotation failure: secret URL'); END""")
        return original(self,previous,following,channel,summary,configuration)
    monkeypatch.setattr(Diagnostics,'rotate',rotate)
    assert main(multi,'--continuous','--max-attempts','62')==1
    assert len([r for r in calls if r[0]=='alpha'])==62
    assert len([r for r in calls if r[0]=='beta'])==60
    operator=next((path.parent/'multi-alpha/runs').glob('*/operator.jsonl'))
    events=[json.loads(line) for line in operator.read_text().splitlines()]
    errors=[r for r in events if r.get('reason')=='rotation_failed']
    assert len(errors)==1 and errors[0]['run_id']==failed[0]
    assert errors[0]['state']=='stopped' and not errors[0]['sqlite_committed']
    assert 'secret' not in operator.read_text()
    log=operator.parent/'beta/capture.jsonl'
    summaries=[r for line in log.read_text().splitlines() if (r:=json.loads(line))['type']=='summary']
    assert len(summaries)==1  # No contradictory shutdown summary appended after failed rotation.
    with Store(path.parent/'shared.sqlite3',read_only=True) as store:
        run=store.db.execute('SELECT * FROM diagnostic_runs WHERE run_id=?',(failed[0],)).fetchone()
        assert run['summary_json'] is None  # Atomic DB rotation did not commit.
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts WHERE run_id=?',(failed[0],)).fetchone()[0]==60


@pytest.mark.parametrize('interval',[15,30])
def test_consecutive_outage_crosses_rotation_then_recovers_without_starving_healthy_lane(multi,monkeypatch,interval):
    module,path,config,calls,clock=multi
    for stream in config['streams']:stream['interval']=interval
    path.write_text(json.dumps(config))
    original=module.shadow.capture_attempt
    totals=dict(alpha=0,beta=0)
    def capture(args,*rest,**kw):
        channel=args.tracking_channel;totals[channel]+=1
        result=original(args,*rest,**kw)
        if channel=='beta' and 58<=totals[channel]<=64:
            clock[0]+=19  # A bounded 20-second acquisition timeout, not an instant failure.
            return record(result['index'],status='capture_failed',current=False,received_at=None,
                neural=None,visual_level=None,visual_status='not_run',localization=None,
                reasons=['frame_timeout'])
        return result
    monkeypatch.setattr(module.shadow,'capture_attempt',capture)
    assert main(multi,'--continuous','--max-attempts','67')==0
    assert totals==dict(alpha=67,beta=67)
    assert all(a[0]!=b[0] for a,b in zip(calls,calls[1:]))
    with Store(path.parent/'shared.sqlite3',read_only=True) as store:
        for channel in totals:
            runs=list(store.db.execute('''SELECT r.* FROM diagnostic_runs r JOIN streamers s ON s.id=r.streamer_id
                WHERE s.login=? ORDER BY r.rowid''',(channel,)))
            assert len(runs)==2 and len({r['session_id'] for r in runs})==1
            assert len({r['character_id'] for r in runs})==1
            rows=[json.loads(r[0]) for run in runs for r in store.db.execute(
                'SELECT payload_json FROM diagnostic_attempts WHERE run_id=? ORDER BY attempt_index',(run['run_id'],))]
            assert len(rows)==67 and [r['index'] for r in rows]==list(range(1,61))+list(range(1,8))
            failed=[i+1 for i,r in enumerate(rows) if r['status']=='capture_failed']
            assert failed==(list(range(58,65)) if channel=='beta' else [])
            assert all(rows[i-1]['received_at'] is None for i in failed)
            assert rows[64]['current'] and rows[64]['status']=='diagnostic_percentage_only'
            assert all(r['summary_json'] is not None for r in runs)
            assert not Diagnostics(store).snapshot(channel)['percentage_progress']['current_pace']
        assert not store.db.execute('SELECT 1 FROM observations').fetchone()
    events=[json.loads(line) for line in next((path.parent/'multi-alpha/runs').glob('*/operator.jsonl')).read_text().splitlines()]
    failures=[e for e in events if e.get('status')=='capture_failed']
    assert len(failures)==7 and all(e['sqlite_committed'] and e['reasons']==['frame_timeout'] for e in failures)


def test_public_only_coordinator_serves_public_routes_and_refuses_developer_routes(multi,monkeypatch,capsys):
    from tests.test_server import request
    module=multi[0];servers=[];seen=[]
    create_server=module.create_server
    def server(*args,**kw):
        assert (kw['public_only'],kw['diagnostic_dashboard'],kw['background'],kw['cors_origins'])==(True,False,True,['https://msxp.pages.dev'])
        result=create_server(*args,**kw);servers.append(result);return result
    monkeypatch.setattr(module,'create_server',server)
    capture=module.shadow.capture_attempt
    def check(*args,**kw):
        seen.append([request((servers[0],None),p)[0] for p in ('/api/players','/stream/alpha','/live/overlay/alpha','/dev/api/streams','/dashboard/alpha')])
        assert request((servers[0],None),'/api/players',origin='https://msxp.pages.dev')[1]['Access-Control-Allow-Origin']=='https://msxp.pages.dev'
        return capture(*args,**kw)
    monkeypatch.setattr(module.shadow,'capture_attempt',check)
    assert main(multi,'--public-only','--cors-origin','https://msxp.pages.dev')==0
    assert seen and all(s==[200,200,200,404,404] for s in seen)
    assert 'Public-only: developer diagnostics are disabled' in capsys.readouterr().out
