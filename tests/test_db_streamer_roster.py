"""Database roster integration on disposable thirteen-channel trackers; never live Twitch."""
from datetime import datetime, timedelta, timezone
import importlib
import json
import sqlite3
import threading
import time

import pytest

from exp_tracker import streamer_roster as roster
from exp_tracker.admin_server import AdminServer
from exp_tracker.automatic_adoption import states
from exp_tracker.character_automation import original
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.store import Store
from tests.test_automatic_adoption import legacy, multi, dump_tables, adopt  # noqa: F401
from tests.test_autonomous_characters import record
from tests.test_identity_coordinator import SCHEDULE
from tests.test_identity_coordinator import coordinator  # noqa: F401
from tests.test_admin_server import request
from tests.test_character_profiles import get
from tests.test_server import request as public_request
from tests.test_store import profile  # noqa: F401

REASON='Reviewed explicit database roster migration'
NEW_TABLES=('streamer_runtime','streamer_roster_events','streamer_capture','streamer_roster_bootstrap')


def bootstrap(legacy, automatic=()):
    _,_,config,path,_=legacy
    plan=roster.bootstrap_preview(path,config['streams'],automatic,REASON)
    roster.bootstrap_apply(path,plan,confirm='bootstrap-roster:'+plan['fingerprint'][:16],backup=path.parent/'roster-backup.sqlite3')
    return plan


def change(path, channel, **settings):
    with Store(path) as store:
        action='roster_update' if roster.entry(store,channel.lower()) else 'roster_add'
        return roster.commit(store,roster.preview(store,dict(action=action,channel=channel,reason=REASON,**settings)))


@pytest.fixture
def managed(legacy):
    bootstrap(legacy)
    return legacy


@pytest.fixture
def legacy10(legacy):
    with sqlite3.connect(legacy[3]) as db:
        for table in NEW_TABLES:db.execute(f'DROP TABLE {table}')
        db.execute('PRAGMA user_version=10')
    return legacy


def assert_schema10(path):
    with Store(path,read_only=True) as store:
        assert store.schema_version==10
        tables={r[0] for r in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not tables.intersection(NEW_TABLES)
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall()


@pytest.mark.parametrize('options',[{},dict(allow_migration=True),dict(allow_migration=False)])
def test_ordinary_schema10_store_writes_never_install_roster_schema(legacy10,options):
    path=legacy10[3]
    preserved=['characters','sessions','diagnostic_attempts','observations','streamers']
    before=dump_tables(path,preserved)
    with Store(path,**options) as store:
        cid=store._channel('channel0')['selected_character_id']
        store.correct_manual('channel0','ordinary-write',cid,level=30,current_exp=125,now=True)
        assert store.schema_version==10
    assert_schema10(path)
    assert dump_tables(path,preserved)==before
    with Store(path,read_only=True) as store:
        assert store.manual_history('channel0')[-1]['event_id']=='ordinary-write'


def test_schema10_protected_admin_preview_and_save_do_not_install_roster(legacy10):
    path=legacy10[3]
    with Store(path,read_only=True) as store:before=roster.database_digest(store)
    with AdminServer(path,0) as admin:
        cid=legacy10[4][0]['character_id']
        data=dict(action='set',channel='channel0',character_id=str(cid),level='30',exp='125',use_now=True)
        code,_,preview=request(admin,'/api/preview','POST',data)
        assert code==200,preview
        assert_schema10(path)
        with Store(path,read_only=True) as store:assert roster.database_digest(store)==before
        code,_,saved=request(admin,'/api/save','POST',dict(preview_id=preview['preview_id']))
        assert code==200,saved
        assert not request(admin,'/api/streamers')[2]['managed']
    assert_schema10(path)
    with Store(path,read_only=True) as store:assert len(store.manual_history('channel0'))==2


@pytest.mark.parametrize('operation',['manual','tracking','retention'])
def test_unrelated_schema10_cli_writers_preserve_schema(legacy10,operation):
    path=legacy10[3]
    if operation=='manual':
        from exp_tracker.manual_admin import main
        argv=['--db',str(path),'--channel','channel0','set','--character','Main 0','--level','30','--exp','125','--now']
    elif operation=='tracking':
        from exp_tracker.tracking import main
        argv=['--db',str(path),'--channel','channel0','character','AnotherSaved']
    else:
        from exp_tracker.retention import main
        argv=['--db',str(path),'--apply']
    assert main(argv)==0
    assert_schema10(path)
    with Store(path,read_only=True) as store:
        assert store._channel('channel0')['selected_character_id']==legacy10[4][0]['character_id']


def test_schema10_legacy_json_coordinator_preserves_schema_and_assignments(legacy10):
    module,config,_,path,mappings=legacy10
    before=dump_tables(path,['characters','sessions','streamers','manual_corrections'])
    assert module.main(['--config',str(config),'--continuous','--max-attempts','2','--exit-after-capture'])==0
    assert_schema10(path)
    assert dump_tables(path,list(before))==before
    with Store(path,read_only=True) as store:
        assert all(store._channel(m['channel'])['selected_character_id']==m['character_id'] for m in mappings)
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]==39


def test_schema10_bootstrap_failure_rolls_back_and_explicit_cli_retry_succeeds(legacy10,monkeypatch):
    path=legacy10[3];cli=importlib.import_module('db_streamer_roster')
    planfile=path.parent/'schema10-review.json';backup=path.parent/'schema10-backup.sqlite3'
    assert cli.main(['--db',str(path),'preview','--config',str(legacy10[1]),'--reason',REASON,'--preview',str(planfile)])==0
    plan=json.loads(planfile.read_text())
    assert plan['schema']==10
    assert_schema10(path)
    actual=roster.bootstrap_change
    def fail(*args):actual(*args);raise OSError('interrupted schema11 bootstrap')
    monkeypatch.setattr(roster,'bootstrap_change',fail)
    confirm='bootstrap-roster:'+plan['fingerprint'][:16]
    argv=['--db',str(path),'apply','--preview',str(planfile),'--confirm',confirm,'--backup',str(backup)]
    assert cli.main(argv)==1
    assert_schema10(path);assert_schema10(backup)
    with Store(path,read_only=True) as store:assert roster.database_digest(store)==plan['state_sha256']
    monkeypatch.setattr(roster,'bootstrap_change',actual)
    assert cli.main([*argv[:-1],str(path.parent/'retry-backup.sqlite3')])==0
    with Store(path,read_only=True) as store:assert store.schema_version==11 and roster.ready(store)
    assert cli.main(argv)==0  # Exact successful preview remains idempotent.


@pytest.mark.parametrize('version',[9,10,11])
def test_bootstrap_is_explicit_atomic_preserves_thirteen_channels_and_history(legacy,version):
    _,_,config,path,mappings=legacy
    if version<11:
        with sqlite3.connect(path) as db:
            for table in NEW_TABLES:db.execute(f'DROP TABLE {table}')
            if version==9:
                db.execute('DROP TRIGGER character_level_no_regression');db.execute('DROP TABLE character_level_guard');db.execute('DROP TABLE automatic_character_events')
            db.execute(f'PRAGMA user_version={version}')
    tables=['characters','sessions','diagnostic_attempts','manual_corrections','tracking_state',
            'reading_events','reading_batches','daily_character_exp','retention_state','streamers']
    before=dump_tables(path,tables)
    with Store(path,read_only=True) as store:before_hash=roster.database_digest(store)
    plan=roster.bootstrap_preview(path,config['streams'],[],REASON)
    with Store(path,read_only=True) as store:assert roster.database_digest(store)==before_hash
    result=roster.bootstrap_apply(path,plan,confirm='bootstrap-roster:'+plan['fingerprint'][:16],backup=path.parent/'before.sqlite3')
    assert not result['duplicate'] and dump_tables(path,tables)==before
    assert dump_tables(path.parent/'before.sqlite3',tables)==before
    with Store(path,read_only=True) as store:
        assert store.schema_version==11 and len(roster.entries(store))==13
        assert all(r['interval']==20 and not r['automatic_characters'] for r in roster.entries(store))
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
    assert roster.bootstrap_apply(path,plan,confirm='bootstrap-roster:'+plan['fingerprint'][:16],backup=path.parent/'before.sqlite3')['duplicate']
    with pytest.raises(ValueError,match='once'):roster.bootstrap_preview(path,config['streams'],[],REASON)


def test_bootstrap_rejects_unreviewed_auto_stale_confirmation_and_rolls_back(legacy,monkeypatch):
    _,_,config,path,_=legacy
    with pytest.raises(ValueError,match='adoption'):roster.bootstrap_preview(path,config['streams'],['channel0'],REASON)
    plan=roster.bootstrap_preview(path,config['streams'],[],REASON)
    with pytest.raises(ValueError,match='confirmation'):roster.bootstrap_apply(path,plan,confirm='yes',backup=path.parent/'bad.sqlite3')
    unsupported=dict(plan,version=2)
    unsupported['fingerprint']=roster.digest({k:v for k,v in unsupported.items() if k!='fingerprint'})
    with pytest.raises(ValueError,match='preview'):
        roster.bootstrap_apply(path,unsupported,confirm='bootstrap-roster:'+unsupported['fingerprint'][:16],backup=path.parent/'bad.sqlite3')
    actual=roster.bootstrap_change
    def fail(*args):actual(*args);raise OSError('interrupted bootstrap')
    monkeypatch.setattr(roster,'bootstrap_change',fail)
    with pytest.raises(OSError):roster.bootstrap_apply(path,plan,confirm='bootstrap-roster:'+plan['fingerprint'][:16],backup=path.parent/'failed.sqlite3')
    with Store(path,read_only=True) as store:assert not roster.ready(store)
    monkeypatch.setattr(roster,'bootstrap_change',actual)
    with Store(path) as store:store.add_channel('otherhistory')
    with pytest.raises(ValueError,match='stale'):roster.bootstrap_apply(path,plan,confirm='bootstrap-roster:'+plan['fingerprint'][:16],backup=path.parent/'stale.sqlite3')


def test_bootstrap_preserves_legacy_default_interval(legacy):
    rows=legacy[2]['streams'];rows[0].pop('interval')
    plan=roster.bootstrap_preview(legacy[3],rows,[],REASON)
    assert plan['rows'][0]['interval']==15 and plan['rows'][1]['interval']==20


def test_unknown_add_is_previewed_no_character_required_and_requests_are_idempotent(managed):
    path=managed[3]
    with Store(path) as store:
        count=store.db.execute('SELECT COUNT(*) FROM characters').fetchone()[0]
        plan=roster.preview(store,dict(action='roster_add',channel='NewCaster',reason=REASON,authorized=True,tracking_enabled=True))
        assert not store.db.execute("SELECT 1 FROM streamers WHERE login='newcaster'").fetchone()
        first=roster.commit(store,plan);second=roster.commit(store,plan)
        assert not first['duplicate'] and second['duplicate']
        assert store._channel('newcaster')['selected_character_id'] is None
        assert store.db.execute('SELECT COUNT(*) FROM characters').fetchone()[0]==count
        assert roster.entry(store,'newcaster')['automatic_characters']
        with pytest.raises(ValueError,match='changed'):
            old=roster.preview(store,dict(action='roster_update',channel='newcaster',reason=REASON,interval=30))
            roster.commit(store,roster.preview(store,dict(action='roster_update',channel='newcaster',reason=REASON,interval=40)))
            roster.commit(store,old)


@pytest.mark.parametrize('settings',[dict(authorized=False,tracking_enabled=True),dict(interval=1),dict(interval=float('nan')),
    dict(automatic_characters=False,tracking_enabled=True,authorized=True),dict(unknown=True),dict(quality='https://bad.example'),dict(save_crops='true')])
def test_invalid_settings_do_not_change_database(managed,settings):
    path=managed[3]
    with Store(path) as store:
        before=roster.database_digest(store)
        with pytest.raises(ValueError):roster.preview(store,dict(action='roster_add',channel='newcaster',reason=REASON,**settings))
        assert roster.database_digest(store)==before


def test_admin_protected_preview_confirmation_and_public_visibility(managed):
    from exp_tracker.server import create_server
    path=managed[3]
    with AdminServer(path,0) as server:
        data=dict(action='roster_add',channel='NewCaster',authorized=True,tracking_enabled=True,reason=REASON)
        assert request(server,'/api/streamers',headers={'X-Admin-Token':None})[0]==403
        assert request(server,'/api/preview','POST',data,headers={'Origin':'https://bad.example'})[0]==403
        status,_,preview=request(server,'/api/preview','POST',data)
        assert status==200,preview
        with Store(path,read_only=True) as store:assert roster.entry(store,'newcaster') is None
        assert request(server,'/api/save','POST',dict(preview_id=preview['preview_id']))[0]==200
        assert request(server,'/api/save','POST',dict(preview_id=preview['preview_id']))[0]==200
        result=request(server,'/api/streamers')[2]
        assert len(result['streamers'])==14 and next(r for r in result['streamers'] if r['channel']=='newcaster')['character'] is None
    with create_server(path,port=0,public_only=True) as public:
        code,home=get(public,'/api/players')
        assert 'channel0' in {r['channel'] for r in home['players']}|set(home.get('warming',[]))
        change(path,'channel0',public_visible=False)
        code,hidden=get(public,'/api/players')
        assert 'channel0' not in {r['channel'] for r in hidden['players']}|set(hidden.get('warming',[]))
        assert public_request((public,None),'/stream/channel0')[0]==200
        assert public_request((public,None),'/live/overlay/channel0')[0]==200
        assert get(public,'/api/players/channel0')[0]==200
        assert public_request((public,None),'/api/streamers','POST')[0] in (404,405)


def test_existing_adoption_is_preserved_and_controls_auto_policy(legacy):
    adopt(legacy)
    before=dump_tables(legacy[3],['automatic_character_events','character_level_guard','characters','sessions'])
    bootstrap(legacy,['channel0'])
    assert dump_tables(legacy[3],list(before))==before
    with Store(legacy[3],read_only=True) as store:
        assert roster.entry(store,'channel0')['automatic_characters'] and not roster.entry(store,'channel1')['automatic_characters']
        assert len(states(store))==13


@pytest.fixture
def running_roster(managed,multi,monkeypatch):
    module,_,_,path,_=managed
    counters={}; seen=[];clock=multi[-1];active=set();guard=threading.Lock();max_active=[0]
    scripts={};base=datetime.now(timezone.utc)+timedelta(minutes=5)
    class Resident:
        def close(self):pass
    monkeypatch.setattr(module.shadow,'ResidentNeural',Resident)
    def capture(args,source,requirements,index,**options):
        login=source.value
        with guard:
            assert login not in active
            active.add(login);max_active[0]=max(max_active[0],len(active))
            n=counters.get(login,0);counters[login]=n+1
        try:
            time.sleep(.003)
            name=scripts.get(login,[None])[n%len(scripts.get(login,[None]))]
            reference=options['identity'].suggestions.reference if 'identity' in options else None
            value=record(index,name,selected=reference,at=base+timedelta(seconds=20*(n+1)),bp=4000+n*10)
            value['source']=dict(kind='twitch',channel=login)
            if not args.character_names:value.pop('character_name')
            seen.append((login,index,args.interval,args.automatic_characters,id(options.get('resident'))))
            return value
        finally:
            with guard:active.remove(login)
    monkeypatch.setattr(module.shadow,'capture_attempt',capture)
    driver={'tick':lambda running,now:None}
    def schedule(lanes,perform,emit,**kw):
        actual=kw['reconcile']
        def reconcile(running,now):
            driver['tick'](running,now)
            actual(running,now)
        kw['reconcile']=reconcile
        return SCHEDULE(lanes,perform,emit,clock=lambda:clock[0],sleep=lambda t:clock.__setitem__(0,clock[0]+t),**kw)
    monkeypatch.setattr(module,'schedule',schedule)
    return managed,counters,seen,scripts,driver,max_active


def run_db(runtime,*extra):
    legacy=runtime[0]
    return legacy[0].main(['--db-roster',str(legacy[3]),'--port','0','--continuous','--workers','3','--exit-after-capture',*extra])


def test_admin_add_starts_unknown_character_without_restart_and_returns_to_id(running_roster):
    legacy,counters,seen,scripts,driver,max_active=running_roster
    path=legacy[3]
    scripts['newcaster']=[None,'Alpha','Alpha','Beta','Beta','Alpha','Alpha','Alpha']
    created=[False]
    with AdminServer(path,0) as admin:
        def tick(running,now):
            if now>=3 and not created[0]:
                data=dict(action='roster_add',channel='NewCaster',authorized=True,tracking_enabled=True,reason=REASON)
                code,_,p=request(admin,'/api/preview','POST',data);assert code==200,p
                assert request(admin,'/api/save','POST',dict(preview_id=p['preview_id']))[0]==200
                created[0]=True
        driver['tick']=tick
        assert run_db(running_roster,'--stop-after-seconds','150')==0
        assert created[0] and counters['newcaster']>=7 and 1<max_active[0]<=3
        report=request(admin,'/api/streamers')[2]
        saved=next(row for row in report['streamers'] if row['channel']=='newcaster')
        assert saved['character']['label']=='Alpha' and saved['identity']['verified']
    with Store(path,read_only=True) as store:
        sid=store._channel('newcaster')['id']
        characters={r['label']:r['id'] for r in store.db.execute('SELECT * FROM characters WHERE streamer_id=?',(sid,))}
        assert set(characters)=={'PendingOCR','Alpha','Beta'}
        rows=[(r['character_id'],json.loads(r['payload_json'])) for r in store.db.execute('''
            SELECT r.character_id,a.payload_json FROM diagnostic_runs r JOIN diagnostic_attempts a ON a.run_id=r.run_id
            WHERE r.streamer_id=? ORDER BY a.id''',(sid,))]
        assert all(not payload['current'] for cid,payload in rows if cid==characters['PendingOCR'])
        switches=[original(payload)['automatic_selection'] for _,payload in rows if 'automatic_selection' in original(payload)]
        assert [r['name'] for r in switches]==['Alpha','Beta','Alpha']
        assert switches[0]['character_id']==switches[-1]['character_id']==characters['Alpha']
        assert not any(key.startswith('existing-adoption:') for key, in store.db.execute('SELECT event_id FROM automatic_character_events WHERE streamer_id=?',(sid,)))
        assert store.db.execute('SELECT COUNT(*) FROM sessions WHERE streamer_id=?',(sid,)).fetchone()[0]==4
        original_ids={m['channel']:m['character_id'] for m in legacy[4]}
        assert all(store._channel(c)['selected_character_id']==cid for c,cid in original_ids.items())
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
    assert len({worker for login,_,_,auto,worker in seen if auto})==1


def test_pause_resume_change_interval_visibility_and_restart(running_roster):
    legacy,counters,seen,scripts,driver,_=running_roster;path=legacy[3]
    change(path,'newcaster',authorized=True,tracking_enabled=True)
    scripts['newcaster']=['Alpha']
    actions=set();paused_counts=[]
    def tick(running,now):
        if now>=30 and 'pause' not in actions:
            change(path,'newcaster',tracking_enabled=False,public_visible=False);actions.add('pause')
        if 35<=now<55:paused_counts.append(counters.get('newcaster',0))
        if now>=60 and 'resume' not in actions:
            change(path,'newcaster',tracking_enabled=True,interval=10);actions.add('resume')
    driver['tick']=tick
    assert run_db(running_roster,'--stop-after-seconds','105')==0
    assert paused_counts and len(set(paused_counts))==1
    assert {interval for login,_,interval,_,_ in seen if login=='newcaster'}=={20,10}
    with Store(path,read_only=True) as store:
        selected=store._channel('newcaster')['selected_character_id']
        sessions=store.db.execute("SELECT COUNT(*) FROM sessions WHERE streamer_id=(SELECT id FROM streamers WHERE login='newcaster')").fetchone()[0]
        rows=store.db.execute("SELECT configuration_json,summary_json FROM diagnostic_runs WHERE streamer_id=(SELECT id FROM streamers WHERE login='newcaster') ORDER BY rowid").fetchall()
        assert len({json.loads(r['configuration_json'])['roster_revision'] for r in rows})>=2
        assert not roster.entry(store,'newcaster')['public_visible']
    driver['tick']=lambda running,now:None
    assert run_db(running_roster,'--max-attempts','2')==0
    with Store(path,read_only=True) as store:
        assert store._channel('newcaster')['selected_character_id']==selected
        assert store.db.execute("SELECT COUNT(*) FROM sessions WHERE streamer_id=(SELECT id FROM streamers WHERE login='newcaster')").fetchone()[0]==sessions


def test_database_mode_uses_real_frame_identity_pipeline_without_a_known_name(coordinator,monkeypatch):
    from exp_tracker.automatic_adoption import marker
    module,path,config,played,steps,scripts=coordinator
    db=path.parent/'shared.sqlite3'
    for row in config['streams']:
        row.update(source='twitch',authorized=True,interval=20,count=2)
        row.pop('file',None)
    with Store(db) as store:
        store.add_channel('alpha');cid=store.add_character('alpha','Alpha')
        store.select_character('alpha',cid);store.start_session('alpha')
    marker(db).write_text(json.dumps(dict(application=module.APP)))
    source_plan=roster.bootstrap_preview(db,[config['streams'][0]],[],REASON)
    roster.bootstrap_apply(db,source_plan,confirm='bootstrap-roster:'+source_plan['fingerprint'][:16],backup=db.parent/'before.sqlite3')
    scripts['alpha']=[('Alpha',30,4000),('Alpha',30,4010)]
    scripts['bravo']=[('Bravo',40,1000),('Bravo',40,1010)]
    now=[0];added=[False]
    def schedule(lanes,perform,emit,**kw):
        actual=kw['reconcile']
        def reconcile(running,tick):
            if tick>=1 and not added[0]:change(db,'bravo',authorized=True,tracking_enabled=True);added[0]=True
            actual(running,tick)
        kw['reconcile']=reconcile
        return SCHEDULE(lanes,perform,emit,clock=lambda:now[0],sleep=lambda t:now.__setitem__(0,now[0]+t),**kw)
    monkeypatch.setattr(module,'schedule',schedule)
    assert module.main(['--db-roster',str(db),'--port','0','--continuous','--max-attempts','2','--exit-after-capture'])==0
    with Store(db,read_only=True) as store:
        assert roster.status(store)[1]['character']['label']=='Bravo'
        rows=[json.loads(r[0]) for r in store.db.execute('''SELECT a.payload_json FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id
            JOIN streamers s ON s.id=r.streamer_id WHERE s.login='bravo' ORDER BY a.id''')]
        assert len(rows)==2 and not rows[0]['current'] and rows[1]['current']
        assert rows[1]['automatic_selection']['name']=='Bravo'


def test_reconcile_drains_inflight_settings_and_coalesces_pause_resume(managed):
    from types import SimpleNamespace
    from db_roster_runtime import Reconciler
    path=managed[3];lanes=[];opened=[];closed=[]
    def build(row):return dict(channel=row['channel'],args=SimpleNamespace(interval=row['interval']))
    def start(lane):lane['run_id']=f"{lane['channel']}:{lane['roster_revision']}";opened.append(lane['run_id'])
    def close(lane,why):closed.append((lane['run_id'],why))
    with Store(path) as store:
        activity={}
        sync=Reconciler(store,lanes,build,start,close,activity,set())
        sync(set(),0)
        original_lane=next(l for l in lanes if l['channel']=='channel0')
        change(path,'channel0',tracking_enabled=False)
        sync({'channel0'},1)
        assert original_lane['paused'] and not closed
        change(path,'channel0',tracking_enabled=True)
        sync({'channel0'},2)
        assert not original_lane['paused'] and len(opened)==13
        change(path,'channel0',interval=10)
        sync({'channel0'},3)
        assert original_lane['args'].interval==20 and original_lane['paused'] and not closed
        sync(set(),4)
        replacement=next(l for l in lanes if l['channel']=='channel0')
        assert replacement is not original_lane and replacement['args'].interval==10
        assert len([l for l in lanes if l['channel']=='channel0'])==1 and len(closed)==1
        change(path,'channel0',tracking_enabled=False)
        sync(set(),5)
        assert activity['channel0']['state']=='stopped'  # Public cards must not present a paused lane as delayed/running.


def test_inflight_capture_keeps_old_revision_and_other_channels_continue(running_roster,monkeypatch):
    legacy,_,_,_,_,_=running_roster;module=legacy[0];path=legacy[3]
    capture=module.shadow.capture_attempt;changed=[False]
    def updating(args,source,requirements,index,**opts):
        value=capture(args,source,requirements,index,**opts)
        value['capture_interval']=args.interval
        if source.value=='channel0' and not changed[0]:
            change(path,'channel0',interval=10);changed[0]=True
        return value
    monkeypatch.setattr(module.shadow,'capture_attempt',updating)
    assert run_db(running_roster,'--stop-after-seconds','50')==0
    with Store(path,read_only=True) as store:
        rows=store.db.execute('''SELECT r.configuration_json,a.payload_json FROM diagnostic_runs r
            JOIN diagnostic_attempts a ON a.run_id=r.run_id JOIN streamers s ON s.id=r.streamer_id
            WHERE s.login='channel0' AND json_extract(r.configuration_json,'$.database_roster')=1 ORDER BY a.id''').fetchall()
        assert len(rows)>=3
        assert {json.loads(r['configuration_json'])['roster_revision'] for r in rows}=={1,2}
        assert all(json.loads(r['configuration_json'])['interval']==original(json.loads(r['payload_json']))['capture_interval'] for r in rows)


def test_pending_identity_blocks_unsafe_disable_and_survives_retention(managed):
    from exp_tracker.character_automation import AutonomousCharacters
    from exp_tracker.retention import prune
    from tests.test_autonomous_characters import config as header
    path=managed[3];change(path,'newcaster',authorized=True,tracking_enabled=True)
    at=datetime.now(timezone.utc)+timedelta(minutes=5)
    with Store(path) as store:
        cid=store.add_character('newcaster','PendingOCR');store.select_character('newcaster',cid);store.start_session('newcaster')
        Diagnostics(store).begin('discover','newcaster',header('discover'))
        policy=AutonomousCharacters(store);run='discover'
        for n,name in enumerate(('Alpha','Alpha','Beta'),1):
            index=store.db.execute('SELECT COUNT(*)+1 FROM diagnostic_attempts WHERE run_id=?',(run,)).fetchone()[0]
            r=policy.append(run,record(index,name,selected='PendingOCR' if n<3 else 'Alpha',at=at+timedelta(seconds=n*20)),f'after{n}',header(f'after{n}'))
            run=r['run_id']
        assert roster.discovery_state(store,store._channel('newcaster')['id'])['risk']=='Beta'
        prune(store,now=at+timedelta(days=2),dry_run=False,active_runs=set())
    with pytest.raises(ValueError,match='unresolved'):change(path,'newcaster',automatic_characters=False)
    change(path,'newcaster',tracking_enabled=False,automatic_characters=False)
    with pytest.raises(ValueError,match='unresolved'):change(path,'newcaster',tracking_enabled=True)
    change(path,'newcaster',automatic_characters=True,tracking_enabled=True)


def test_database_check_is_read_only_and_legacy_json_cannot_override_it(managed):
    module,config_path,_,path,_=managed
    with Store(path,read_only=True) as store:before=roster.database_digest(store)
    assert module.main(['--db-roster',str(path),'--port','0','--continuous','--check'])==0
    assert module.main(['--config',str(config_path),'--check'])==1
    with Store(path,read_only=True) as store:assert roster.database_digest(store)==before


def test_management_failure_rolls_back_and_retry_is_safe(managed):
    path=managed[3]
    with Store(path) as store:
        plan=roster.preview(store,dict(action='roster_add',channel='newcaster',reason=REASON))
        store.db.execute("CREATE TRIGGER refuse_roster BEFORE INSERT ON streamer_roster_events BEGIN SELECT RAISE(ABORT,'test disk failure'); END")
        with pytest.raises(sqlite3.IntegrityError):roster.commit(store,plan)
        assert roster.entry(store,'newcaster') is None
        assert not store.db.execute("SELECT 1 FROM streamers WHERE login='newcaster'").fetchone()
        store.db.execute('DROP TRIGGER refuse_roster')
        assert not roster.commit(store,plan)['duplicate']
        assert roster.commit(store,plan)['duplicate']


def test_unknown_invalid_duplicate_and_multiple_hud_evidence_never_become_identity(managed):
    from exp_tracker.character_automation import AutonomousCharacters
    from tests.test_autonomous_characters import config as header
    path=managed[3];change(path,'newcaster',authorized=True,tracking_enabled=True)
    at=datetime.now(timezone.utc)+timedelta(minutes=5)
    with Store(path) as store:
        cid=store.add_character('newcaster','PendingOCR');store.select_character('newcaster',cid);store.start_session('newcaster')
        Diagnostics(store).begin('discover','newcaster',header('discover'));policy=AutonomousCharacters(store)
        for n in range(1,9):
            r=record(n,'Alpha' if n>1 else None,selected='PendingOCR',at=at+timedelta(seconds=n*20))
            if n in (2,3):r['character_name']['evidence']['score']=.4
            if n==4:r['localization']['count']=2
            if n==6:r['character_name']['suggestion']=dict(latest_status='duplicate_frame')
            saved=policy.append('discover',r,f'after{n}',header(f'after{n}'))
            assert saved['switched']==(n==8)
            if n<8:assert not saved['record']['current'] and store._channel('newcaster')['selected_character_id']==cid


def test_database_roster_rotation_and_retention_keep_identity_and_daily_history(running_roster):
    from exp_tracker.retention import prune
    legacy,_,_,scripts,_,_=running_roster;path=legacy[3]
    for m in legacy[4]:change(path,m['channel'],tracking_enabled=False)
    change(path,'newcaster',authorized=True,tracking_enabled=True);scripts['newcaster']=['Alpha']
    assert run_db(running_roster,'--retention-24h','--max-attempts','63')==0
    with Store(path) as store:
        s=store._channel('newcaster');cid=s['selected_character_id']
        runs=store.db.execute('SELECT * FROM diagnostic_runs WHERE character_id=? ORDER BY rowid',(cid,)).fetchall()
        assert len(runs)==2 and len({r['session_id'] for r in runs})==1
        assert json.loads(runs[0]['summary_json'])['completion_reason']=='scheduled_rotation'
        assert [store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts WHERE run_id=?',(r['run_id'],)).fetchone()[0] for r in runs]==[60,2]
        prune(store,now=datetime.now(timezone.utc)+timedelta(days=2),dry_run=False,active_runs=set())
        assert len(roster.entries(store))==14 and store._channel('newcaster')['selected_character_id']==cid
        assert roster.discovery_state(store,s['id'])['verified']
        assert store.db.execute('SELECT level FROM character_level_guard WHERE character_id=?',(cid,)).fetchone()[0]==30
        assert store.db.execute('SELECT COUNT(*) FROM daily_character_exp WHERE character_id=?',(cid,)).fetchone()[0]>0


def test_disable_approved_during_inflight_conflict_is_rechecked_before_manual_capture(running_roster,monkeypatch):
    legacy,counters,_,scripts,_,_=running_roster;module=legacy[0];path=legacy[3]
    change(path,'newcaster',authorized=True,tracking_enabled=True);scripts['newcaster']=['Alpha','Alpha','Beta','Beta']
    capture=module.shadow.capture_attempt;disabled=[False]
    def updating(args,source,requirements,index,**opts):
        value=capture(args,source,requirements,index,**opts)
        if source.value=='newcaster' and counters['newcaster']==3:
            # The admin sees the last committed A, before this in-flight B frame is attributed.
            change(path,'newcaster',automatic_characters=False);disabled[0]=True
        return value
    monkeypatch.setattr(module.shadow,'capture_attempt',updating)
    assert run_db(running_roster,'--stop-after-seconds','85')==0
    assert disabled[0] and counters['newcaster']==3 and counters['channel0']>=4
    with Store(path,read_only=True) as store:
        selected=store._channel('newcaster')['selected_character_id']
        assert store.db.execute('SELECT label FROM characters WHERE id=?',(selected,)).fetchone()[0]=='Alpha'
        runtime=next(r for r in roster.status(store) if r['channel']=='newcaster')
        assert runtime['runtime']['state']=='error' and 'unresolved' in runtime['runtime']['error']
        assert runtime['identity']['risk']=='Beta'


def test_admin_character_rename_reconciles_without_changing_its_id(running_roster):
    legacy,_,_,scripts,driver,_=running_roster;path=legacy[3]
    change(path,'newcaster',authorized=True,tracking_enabled=True);scripts['newcaster']=['Alpha']
    renamed=[]
    def tick(running,now):
        if now>=30 and not renamed:
            with Store(path) as store:
                cid=store._channel('newcaster')['selected_character_id']
                store.rename_character('newcaster',cid,'Gamma',reason='Operator reviewed the current name')
                renamed.append(cid)
            scripts['newcaster']=['Gamma']
    driver['tick']=tick
    assert run_db(running_roster,'--stop-after-seconds','75')==0
    with Store(path,read_only=True) as store:
        assert renamed and store._channel('newcaster')['selected_character_id']==renamed[0]
        assert store.db.execute("SELECT COUNT(*) FROM characters WHERE streamer_id=(SELECT id FROM streamers WHERE login='newcaster')").fetchone()[0]==2


def test_bounded_attempt_limit_survives_dynamic_lane_replacement(running_roster,monkeypatch):
    legacy,counters,_,_,_,_=running_roster;module=legacy[0];path=legacy[3]
    capture=module.shadow.capture_attempt;updated=[False]
    def updating(args,source,requirements,index,**opts):
        value=capture(args,source,requirements,index,**opts)
        if source.value=='channel0' and not updated[0]:change(path,'channel0',interval=10);updated[0]=True
        return value
    monkeypatch.setattr(module.shadow,'capture_attempt',updating)
    assert run_db(running_roster,'--max-attempts','2')==0
    assert updated[0] and counters['channel0']==2


def test_bootstrap_requires_both_writer_locks_and_a_consistent_backup(legacy):
    from exp_tracker.automatic_adoption import marker
    from exp_tracker.writer_lock import writer_lease
    path=legacy[3];plan=roster.bootstrap_preview(path,legacy[2]['streams'],[],REASON)
    confirm='bootstrap-roster:'+plan['fingerprint'][:16]
    with Store(path,read_only=True) as store:before=roster.database_digest(store)
    with writer_lease(marker(path)),pytest.raises(ValueError,match='coordinator'):
        roster.bootstrap_apply(path,plan,confirm=confirm,backup=path.parent/'unused.sqlite3')
    with sqlite3.connect(path,isolation_level=None) as writer:
        writer.execute('BEGIN IMMEDIATE')
        with pytest.raises(sqlite3.OperationalError,match='locked'):
            roster.bootstrap_apply(path,plan,confirm=confirm,backup=path.parent/'unused.sqlite3')
        writer.execute('ROLLBACK')
    with pytest.raises(OSError):roster.bootstrap_apply(path,plan,confirm=confirm,backup=path.parent/'missing'/'backup.sqlite3')
    with Store(path,read_only=True) as store:assert roster.database_digest(store)==before
    assert not (path.parent/'unused.sqlite3').exists()


def test_schema9_partial_bootstrap_migration_fully_rolls_back(legacy,monkeypatch):
    path=legacy[3]
    with sqlite3.connect(path) as db:
        for table in NEW_TABLES:db.execute(f'DROP TABLE {table}')
        db.execute('DROP TRIGGER character_level_no_regression');db.execute('DROP TABLE character_level_guard')
        db.execute('DROP TABLE automatic_character_events');db.execute('PRAGMA user_version=9')
    plan=roster.bootstrap_preview(path,legacy[2]['streams'],[],REASON)
    actual=roster.bootstrap_change
    def broken(*args):actual(*args);raise OSError('interrupted migration')
    monkeypatch.setattr(roster,'bootstrap_change',broken)
    with pytest.raises(OSError):roster.bootstrap_apply(path,plan,confirm='bootstrap-roster:'+plan['fingerprint'][:16],backup=path.parent/'failed-migration.sqlite3')
    with Store(path,read_only=True) as store:
        assert store.schema_version==9 and not roster.ready(store)
        assert not store.db.execute("SELECT 1 FROM sqlite_master WHERE name='streamer_capture'").fetchone()
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall()


def test_unmanaged_historical_streamer_is_hidden_without_losing_direct_urls(managed):
    from exp_tracker.server import create_server
    path=managed[3]
    with Store(path) as store:
        store.add_channel('unmanaged');cid=store.add_character('unmanaged','SavedMage')
        store.select_character('unmanaged',cid);store.start_session('unmanaged')
        assert roster.visible(store)['unmanaged'] is False
    with create_server(path,port=0,public_only=True) as server:
        _,body=get(server,'/api/players')
        assert 'unmanaged' not in {p['channel'] for p in body['players']}|set(body.get('warming',[]))
        assert public_request((server,None),'/stream/unmanaged')[0]==200
        assert get(server,'/api/players/unmanaged')[0]==200


def test_operator_cli_rehearses_separate_copy_without_editing_source(legacy,capsys):
    from exp_tracker.automatic_adoption import snapshot
    cli=importlib.import_module('db_streamer_roster')
    _,config,_,source,_=legacy
    copy=source.parent/'rehearsal.sqlite3';snapshot(source,copy)
    with Store(source,read_only=True) as store:before=roster.database_digest(store)
    planfile=source.parent/'roster-preview.json';backup=source.parent/'roster-before.sqlite3'
    assert cli.main(['--db',str(copy),'preview','--config',str(config),'--reason',REASON,'--preview',str(planfile)])==0
    result=json.loads(capsys.readouterr().out)
    assert len(result['preview']['identities'])==13
    assert cli.main(['--db',str(copy),'apply','--preview',str(planfile),
                     '--confirm',result['confirmation'],'--backup',str(backup)])==0
    capsys.readouterr()
    assert cli.main(['--db',str(copy),'inspect'])==0
    assert len(json.loads(capsys.readouterr().out)['channels'])==13
    with Store(source,read_only=True) as store:assert roster.database_digest(store)==before and not roster.ready(store)


def historical_channels(path,count=30):
    ids={}
    with Store(path) as store:
        for i in range(count):
            login=f'aaa{i:02}';store.add_channel(login)
            cid=store.add_character(login,f'Archived{i}');store.select_character(login,cid);store.start_session(login)
            ids[login]=cid
    return ids


def test_visible_managed_directory_precedes_more_than_25_historical_channels(managed,monkeypatch):
    from exp_tracker.server import create_server
    path=managed[3];ids=historical_channels(path)
    change(path,'channel0',public_visible=False)
    expected={m['channel'] for m in managed[4]}-{'channel0'}
    tables=['streamers','characters','sessions','diagnostic_attempts','manual_corrections','reading_events']
    before=dump_tables(path,tables)
    with Store(path,read_only=True) as store:
        assert len(Diagnostics(store).heads())==26
        assert {h['login'] for h in Diagnostics(store).heads(public_directory=True)}==expected
    with create_server(path,port=0,public_only=True) as server:
        checked=[]
        assert set(json.loads(server.publisher.homepage())['warming'])==expected
        def availability(channels,**kw):checked.append(set(channels));return {}
        monkeypatch.setattr(server.twitch_availability,'snapshot',availability)
        _,home=get(server,'/api/players')
        assert {r['channel'] for r in home['players']}==expected
        assert not home['truncated'] and not home.get('warming')
        _,characters=get(server,'/api/players?mode=characters')
        assert {r['channel'] for r in characters['characters']}==expected and not characters['truncated']
        for login,cid in [('channel0',managed[4][0]['character_id']),('aaa00',ids['aaa00']),('aaa29',ids['aaa29'])]:
            assert public_request((server,None),f'/stream/{login}')[0]==200
            code,body=get(server,f'/api/players/{login}?character={cid}')
            assert code==200 and body['view']['character_id']==cid
            assert body['player']['channel']==login
            assert get(server,f'/api/players/{login}/history')[0]==200
            assert public_request((server,None),f'/live/overlay/{login}')[0]==200
        assert all(channels<=expected for channels in checked)  # Browsing adds no status-network work.
        _,home=get(server,'/api/players')
        assert {r['channel'] for r in home['players']}==expected
    with Store(path,read_only=True) as store:
        assert all(store._channel(login)['selected_character_id']==cid for login,cid in ids.items())
    assert dump_tables(path,tables)==before


def test_historical_direct_channel_cache_is_bounded_evicts_and_expires(managed):
    from exp_tracker.server import create_server
    from exp_tracker.publisher import MAX_CHANNEL_VIEWS,VIEW_IDLE_SECONDS
    path=managed[3];ids=historical_channels(path)
    with Store(path) as store:other=store.add_character('aaa00','OtherSaved')
    with create_server(path,port=0,public_only=True) as server:
        p=server.publisher
        for login,cid in ids.items():
            code,body=get(server,f'/api/players/{login}')
            assert code==200 and body['view']['character_id']==cid
            assert len(p.channel_views)<=MAX_CHANNEL_VIEWS
            assert len(p.entries)<=13+MAX_CHANNEL_VIEWS
        assert 'aaa00' not in p.entries and get(server,'/api/players/aaa00')[0]==200
        # Unselected historical characters use the existing bounded character-view path.
        assert get(server,f'/api/players/aaa00?character={other}')[1]['view']==dict(character_id=other,current=False)
        with p.lock:p.channel_views={c:seen-VIEW_IDLE_SECONDS-1 for c,seen in p.channel_views.items()}
        p.step()
        assert not p.channel_views and set(p.entries)<={m['channel'] for m in managed[4]}
        assert not p.views and not p.viewed
        for login in ids:p.want(login)
        assert len(p.channel_views)==MAX_CHANNEL_VIEWS and len(p.wanted)<=MAX_CHANNEL_VIEWS
        with Store(path) as store:store.rename_character('channel1',managed[4][1]['character_id'],'ReviewedHero')
        p.step()  # Requested historical builds cannot get ahead of a changed directory entry.
        assert p.entry('channel1')['public']['player']['character']['label']=='ReviewedHero'
        assert 'aaa29' not in p.entries


def test_managed_membership_limit_counts_paused_channels_not_workers(managed):
    path=managed[3]
    for i in range(roster.MAX_MANAGED_STREAMERS-13):change(path,f'paused{i}',public_visible=False)
    with Store(path) as store:
        assert len(roster.entries(store))==roster.MAX_MANAGED_STREAMERS
        with pytest.raises(ValueError,match='managed channels'):
            roster.preview(store,dict(action='roster_add',channel='oneextra',reason=REASON))


def test_reserved_name_never_confirms_or_archives_pending_identity(managed):
    from exp_tracker.character_automation import AutonomousCharacters
    from exp_tracker.retention import prune
    from tests.test_autonomous_characters import config as header,AT
    path=managed[3];change(path,'newcaster',authorized=True,tracking_enabled=True)
    with Store(path) as store:
        cid=store.add_character('newcaster','PendingOCR');store.select_character('newcaster',cid,at=AT)
        store.start_session('newcaster',at=AT);d=Diagnostics(store);d.begin('pending','newcaster',header('pending'))
        policy=AutonomousCharacters(store)
        for i,name in enumerate([None,'PendingOCR','PendingOCR',None],1):
            saved=policy.append('pending',record(i,name,selected='PendingOCR',at=AT+timedelta(seconds=20*i)),f'after{i}',header(f'after{i}'))
            assert not saved['switched'] and not saved['record']['current']
        assert not roster.discovery_state(store,store._channel('newcaster')['id'])['verified']
        assert not store.db.execute('SELECT 1 FROM character_level_guard WHERE character_id=?',(cid,)).fetchone()
        d.append('pending',dict(type='summary',trusted=False,attempts=4,interrupted=False))
        prune(store,now=AT+timedelta(days=3),dry_run=False,active_runs=set())
        assert not store.db.execute('SELECT 1 FROM daily_character_exp WHERE character_id=?',(cid,)).fetchone()
        assert not store.db.execute('SELECT 1 FROM diagnostic_attempts WHERE run_id=?',('pending',)).fetchone()
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall()


def test_pending_character_rejects_nonautomatic_ingest_manual_assertions_and_renames(managed,profile):
    from exp_tracker.daily_snapshots import save as archive
    from exp_tracker.retention import prune
    from tests.test_autonomous_characters import config as header,AT
    from tests.test_store import reading
    path=managed[3];change(path,'newcaster')
    with Store(path) as store:
        cid=store.add_character('newcaster','PendingOCR');store.select_character('newcaster',cid,at=AT)
        sid=store.start_session('newcaster',at=AT);d=Diagnostics(store)
        h=header('nonauto');h.pop('automatic_characters');d.begin('nonauto','newcaster',h)
        for i in (1,2):
            r=record(i,None,at=AT+timedelta(seconds=20*i));r.pop('character_name')
            assert d.append('nonauto',r) and not d.append('nonauto',r)  # Stable held replay.
            stored=json.loads(store.db.execute('SELECT payload_json FROM diagnostic_attempts WHERE run_id=? AND attempt_index=?',('nonauto',i)).fetchone()[0])
            assert not stored['current'] and 'identity_hold' in stored
        trusted=store.ingest('newcaster','no-trusted',AT+timedelta(seconds=60),reading(),profile=profile,session_id=sid)
        assert trusted['outcome']=='rejected' and trusted['reason']=='character_discovery_pending'
        assert trusted['current_exp'] is None and trusted['gained_exp'] is None
        with pytest.raises(ValueError,match='PendingOCR'):
            store.correct_manual('newcaster','no-manual',cid,level=67,current_exp=1000,effective_at=AT)
        with pytest.raises(ValueError,match='reserved'):store.rename_character('newcaster',cid,'Alpha')
        real=store.add_character('newcaster','Legit')
        with pytest.raises(ValueError,match='reserved'):store.rename_character('newcaster',real,'PendingOCR')
        for source in ('diagnostic','manual_correction','trusted_ocr'):
            archive(store,cid,AT.isoformat(),67,1000,2000,source,'synthetic','synthetic','synthetic')
        d.append('nonauto',dict(type='summary',trusted=False,attempts=2,interrupted=False))
        prune(store,now=AT+timedelta(days=3),dry_run=False,active_runs=set())
    with Store(path) as store:
        assert store._channel('newcaster')['selected_character_id']==cid
        for table in ('character_level_guard','manual_corrections','daily_character_exp'):
            assert not store.db.execute(f'SELECT 1 FROM {table} WHERE character_id=?',(cid,)).fetchone()
        assert store.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    from exp_tracker.server import create_server
    with create_server(path,port=0,diagnostic_dashboard=True) as server:
        code,_,body=public_request((server,None),'/api/streams/newcaster/state')
        assert code==200 and b'PendingOCR' not in body
        assert json.loads(body)['selected_character']['label']=='\u2014'
