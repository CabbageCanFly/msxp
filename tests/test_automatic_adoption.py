"""Existing 13-channel trackers: disposable data only, never Twitch or live databases."""
from copy import deepcopy
from datetime import timedelta
import importlib
import json
import sqlite3
import threading
import time

import pytest

from exp_tracker import automatic_adoption as adoption
from exp_tracker.character_automation import AutonomousCharacters, original
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.store import Store
from exp_tracker.retention import prune
from exp_tracker.invalidations import Invalidations
from exp_tracker.writer_lock import writer_lease
from tests.test_autonomous_characters import record, config as header, AT
from tests.test_multi_alpha import multi  # noqa: F401
from tests.test_identity_coordinator import SCHEDULE

REASON = 'Reviewed saved footage and confirmed this historical character name'


@pytest.fixture
def legacy(multi,request):
    module, path, config, calls, now = multi
    db = path.parent/'shared.sqlite3'
    rows, mappings = [], []
    with Store(db) as store:
        for i in range(13):
            login, label, name = f'channel{i}', f'Main {i}', f'Hero{i}'
            correct_names = getattr(request,'param',None)=='correctly_named'
            if correct_names and i==0:login,label,name='telfer1','Telfer','Telfer'
            elif correct_names and i==1:label=name
            row = dict(channel=login, character=label, source='twitch', authorized=True, interval=20, count=7)
            rows.append(row)
            store.add_channel(login)
            if correct_names and i==0:
                store.add_character(login,'Archived')  # The selected ID is deliberately not 1.
                cid=store.add_character(login,'Main')
                store.rename_character(login,cid,label,reason='Previously reviewed through the admin portal')
            else:cid = store.add_character(login, label)
            store.select_character(login, cid, at=AT-timedelta(minutes=5))
            store.start_session(login, at=AT-timedelta(minutes=5))
            h = header(f'old{i}'); h.pop('automatic_characters')
            Diagnostics(store).begin(f'old{i}', login, h)
            value = record(1, None, at=AT-timedelta(minutes=4))
            Diagnostics(store).append(f'old{i}', value)
            store.correct_manual(login, f'manual{i}', cid, level=30, current_exp=100,
                effective_at=AT-timedelta(minutes=3), reason='Reviewed old manual baseline')
            if i==0:
                service=Invalidations(store)
                spec=dict(action='invalidate',kind='diagnostic',identity='old0:1',timestamp=value['received_at'])
                reviewed=service.preview(login,cid,spec)
                service.commit(login,cid,'legacy-invalidation',spec,reviewed['fingerprint'],'Reviewed erroneous historical endpoint')
            mappings.append(dict(channel=login, character_id=cid, character=label, name=name))
    adoption.marker(db).write_text(json.dumps(dict(application=module.APP)))
    config['streams'] = rows
    path.write_text(json.dumps(config))
    return module, path, config, db, mappings


def adopt(legacy, mappings=None):
    db = legacy[3]
    plan = adoption.preview(db, mappings or legacy[4], REASON)
    result = adoption.apply(db, plan, confirm=adoption.confirmation(plan), backup=db.parent/(plan['fingerprint']+'.backup.sqlite3'))
    return plan, result


def dump_tables(db, tables):
    with Store(db, read_only=True) as store:
        return {t: [tuple(r) for r in store.db.execute(f'SELECT * FROM {t}')] for t in tables}


@pytest.mark.parametrize('version', [9, 10, 11])
def test_atomic_adoption_preserves_thirteen_channel_history_and_ids(legacy, version):
    db, mappings = legacy[3:]
    if version < 11:
        with sqlite3.connect(db) as conn:
            for table in ('streamer_runtime','streamer_roster_events','streamer_capture','streamer_roster_bootstrap'):
                conn.execute(f'DROP TABLE {table}')
            if version==9:
                conn.execute('DROP TRIGGER character_level_no_regression')
                conn.execute('DROP TABLE character_level_guard')
                conn.execute('DROP TABLE automatic_character_events')
            conn.execute(f'PRAGMA user_version={version}')
    preserved = ['streamers','sessions','diagnostic_runs','diagnostic_attempts','observations',
                 'manual_corrections','tracking_state','retention_state','daily_character_exp',
                 'reading_batches','reading_events','reading_commits','reading_validity']
    before = dump_tables(db, preserved)
    marker_before = adoption.marker(db).read_bytes()
    plan = adoption.preview(db, mappings, REASON)
    assert dump_tables(db, preserved) == before
    with Store(db,read_only=True) as store:
        assert store.schema_version == version
    assert all(v['counts']['sessions']==1 for v in plan['preserved'])
    result = adoption.apply(db, plan, confirm=adoption.confirmation(plan), backup=db.parent/'before.sqlite3')
    assert not result['duplicate'] and dump_tables(db, preserved)==before
    assert dump_tables(db.parent/'before.sqlite3', preserved)==before
    assert adoption.marker(db).read_bytes()==marker_before
    with Store(db,read_only=True) as store:
        assert store.schema_version==max(10,version) and len(adoption.states(store))==13
        assert [r[0] for r in store.db.execute('SELECT label FROM characters ORDER BY id')]==[m['name'] for m in mappings]
        assert store.db.execute('SELECT COUNT(*) FROM character_renames').fetchone()[0]==13
        assert store.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
    # Exact retries do not rename twice or demand a second backup, even after restart.
    assert adoption.apply(db, plan, confirm=adoption.confirmation(plan), backup=db.parent/'before.sqlite3')['duplicate']


@pytest.mark.parametrize('legacy',['correctly_named'],indirect=True)
def test_inspected_correct_names_are_approved_without_rename_or_history_changes(legacy,capsys,monkeypatch):
    _,_,_,db,_=legacy
    cli=importlib.import_module('adopt_automatic')
    with Store(db,read_only=True) as store:before=adoption.database_digest(store)
    assert cli.main(['--db',str(db),'inspect'])==0
    inspected=json.loads(capsys.readouterr().out)
    selected=next(r for r in inspected['channels'] if r['channel']=='telfer1')
    assert selected['character']=='Telfer' and selected['character_id']!=1
    mappings=[dict(channel=r['channel'],character_id=r['character_id'],character=r['character'],name=r['character'])
              for r in inspected['channels'] if r['channel'] in ('telfer1','channel1')]
    preserved=['characters','character_renames','streamers','sessions','diagnostic_runs','diagnostic_attempts',
               'observations','manual_corrections','tracking_state','character_level_guard','reading_validity',
               'reading_batches','reading_events','reading_commits','retention_state','daily_character_exp']
    saved=dump_tables(db,preserved)
    def no_rename(*args,**kw):raise AssertionError('already correct labels must not be renamed')
    monkeypatch.setattr(Store,'rename_character',no_rename)
    plan=adoption.preview(db,mappings,REASON)
    with Store(db,read_only=True) as store:assert adoption.database_digest(store)==before
    result=adoption.apply(db,plan,confirm=adoption.confirmation(plan),backup=db.parent/'correct-name-backup.sqlite3')
    assert not result['duplicate'] and dump_tables(db,preserved)==saved
    assert dump_tables(db.parent/'correct-name-backup.sqlite3',preserved)==saved
    with Store(db,read_only=True) as store:
        assert set(adoption.states(store))=={'telfer1','channel1'}
        assert store._channel('telfer1')['selected_character_id']==selected['character_id']


def test_rejected_mappings_stale_confirmation_and_backup_fail_without_changes(legacy):
    db, mappings = legacy[3:]
    for mutate in (lambda m:m.update(character_id=999), lambda m:m.update(character='Wrong'),
                   lambda m:m.update(channel='unknown'), lambda m:m.update(name='bad name')):
        bad=deepcopy(mappings); mutate(bad[0])
        with pytest.raises(ValueError):adoption.preview(db,bad,REASON)
    with pytest.raises(ValueError):adoption.preview(db,mappings,'yes')
    plan=adoption.preview(db,mappings,REASON)
    with pytest.raises(ValueError,match='confirmation'):
        adoption.apply(db,plan,confirm='yes',backup=db.parent/'unused.sqlite3')
    with pytest.raises(OSError):
        adoption.apply(db,plan,confirm=adoption.confirmation(plan),backup=db.parent/'missing'/'backup.sqlite3')
    with Store(db) as store:
        store.rename_character('channel12',mappings[-1]['character_id'],'Changed')
    with pytest.raises(ValueError,match='stale'):
        adoption.apply(db,plan,confirm=adoption.confirmation(plan),backup=db.parent/'unused.sqlite3')
    assert not (db.parent/'unused.sqlite3').exists()


@pytest.mark.parametrize('schema',[9,10,11])
def test_interrupted_adoption_rolls_back_migration_renames_and_retry(legacy,monkeypatch,schema):
    db=legacy[3]
    if schema<11:
        with sqlite3.connect(db) as conn:
            for table in ('streamer_runtime','streamer_roster_events','streamer_capture','streamer_roster_bootstrap'):
                conn.execute(f'DROP TABLE {table}')
            if schema==9:
                conn.executescript('DROP TRIGGER character_level_no_regression; DROP TABLE character_level_guard; DROP TABLE automatic_character_events;')
            conn.execute(f'PRAGMA user_version={schema}')
    plan=adoption.preview(db,legacy[4],REASON)
    real=adoption.change
    def broken(*args):
        real(*args)
        raise OSError('interrupted after SQL changes')
    monkeypatch.setattr(adoption,'change',broken)
    with pytest.raises(OSError,match='interrupted'):
        adoption.apply(db,plan,confirm=adoption.confirmation(plan),backup=db.parent/'failed.sqlite3')
    with Store(db,read_only=True) as store:
        assert store.schema_version==schema and not adoption.states(store)
        assert store.db.execute('SELECT COUNT(*) FROM character_renames').fetchone()[0]==0
    monkeypatch.setattr(adoption,'change',real)
    assert not adoption.apply(db,plan,confirm=adoption.confirmation(plan),backup=db.parent/'retry.sqlite3')['duplicate']


def test_both_writer_locks_and_conflicting_name_are_refused(legacy):
    db=legacy[3]
    plan=adoption.preview(db,legacy[4],REASON)
    with writer_lease(adoption.marker(db)), pytest.raises(ValueError,match='coordinator'):
        adoption.apply(db,plan,confirm=adoption.confirmation(plan),backup=db.parent/'unused.sqlite3')
    with sqlite3.connect(db,isolation_level=None) as writer:
        writer.execute('BEGIN IMMEDIATE')
        with pytest.raises(sqlite3.OperationalError,match='locked'):
            adoption.apply(db,plan,confirm=adoption.confirmation(plan),backup=db.parent/'unused.sqlite3')
        writer.execute('ROLLBACK')
    assert not (db.parent/'unused.sqlite3').exists()
    with Store(db) as store:store.add_character('channel0','Hero0')
    with pytest.raises(ValueError,match='cannot be merged'):
        adoption.preview(db,legacy[4],REASON)


def test_snapshot_and_cli_are_read_only_on_source(legacy,capsys):
    db=legacy[3]
    with Store(db,read_only=True) as store:before=adoption.database_digest(store)
    cli=importlib.import_module('adopt_automatic')
    assert cli.main(['--db',str(db),'inspect'])==0
    report=json.loads(capsys.readouterr().out)
    assert len(report['channels'])==13
    copied=db.parent/'rehearsal.sqlite3'
    assert cli.main(['--db',str(db),'snapshot','--output',str(copied)])==0
    with Store(db,read_only=True) as store:assert adoption.database_digest(store)==before
    with Store(copied,read_only=True) as store:assert adoption.database_digest(store)==before
    assert adoption.marker(copied).read_bytes()==adoption.marker(db).read_bytes()
    mappings=db.parent/'mapping.json';mappings.write_text(json.dumps(legacy[4]))
    review=db.parent/'review.json'
    assert cli.main(['--db',str(copied),'preview','--mappings',str(mappings),'--reason',REASON,'--preview',str(review)])==0
    plan=json.loads(review.read_text())
    assert cli.main(['--db',str(copied),'apply','--preview',str(review),'--confirm',adoption.confirmation(plan),'--backup',str(db.parent/'copy-before.sqlite3')])==0
    with Store(db,read_only=True) as store:assert adoption.database_digest(store)==before


def test_initial_two_names_switch_back_and_unreadability_with_retention(legacy):
    _,_,_,db,mappings=legacy
    adopt(legacy)
    with Store(db) as store:
        policy=AutonomousCharacters(store)
        channel=mappings[0]['channel']; cid=mappings[0]['character_id']
        run='adopted-first'; Diagnostics(store).begin(run,channel,header(run))
        names=['Hero0','Hero0',None,'Other','Other','Hero0','Hero0']
        receipts=[]
        for i,name in enumerate(names,1):
            selected=store.db.execute('SELECT label FROM characters WHERE id=?',(store._channel(channel)['selected_character_id'],)).fetchone()[0]
            index=store.db.execute('SELECT COUNT(*)+1 FROM diagnostic_attempts WHERE run_id=?',(run,)).fetchone()[0]
            result=policy.append(run,record(index,name,selected=selected,at=AT+timedelta(seconds=i*20)),f'next{i}',header(f'next{i}'))
            receipts.append(result);run=result['run_id']
        assert 'adoption_name_confirmation_pending' in receipts[0]['record']['identity_hold']['hold_reasons']
        assert all(receipts[i]['record']['current'] for i in (1,2,4,6))
        assert [r['switched'] for r in receipts]==[False,False,False,False,True,False,True]
        assert store._channel(channel)['selected_character_id']==cid
        assert len({r['character_id'] for r in receipts})==2
        assert adoption.states(store)[channel]['verified']
        assert store.db.execute('SELECT level FROM character_level_guard WHERE character_id=?',(cid,)).fetchone()[0]==30
        # A later unresolved conflict must survive complete raw-history expiration.
        index=store.db.execute('SELECT COUNT(*)+1 FROM diagnostic_attempts WHERE run_id=?',(run,)).fetchone()[0]
        policy.append(run,record(index,'Noise',selected='Hero0',at=AT+timedelta(minutes=4)), 'unused', header('unused'))
        prune(store,now=AT+timedelta(days=2),dry_run=False,active_runs=set())
        assert adoption.states(store)[channel]['risk']=='Noise'
    # No silent fallback to nonautomatic writes while identity is unresolved.
    with pytest.raises(ValueError,match='unresolved'):
        legacy[0].existing_preflight(db,legacy[2]['streams'],[])
    with Store(db) as store:
        policy=AutonomousCharacters(store); Diagnostics(store).begin('restart',channel,header('restart'))
        r=record(1,None,at=AT+timedelta(days=2,minutes=1))
        result=policy.append('restart',r,'no-switch',header('no-switch'))
        assert 'identity_hold' in result['record'] and adoption.states(store)[channel]['risk']=='Noise'


@pytest.fixture
def existing_capture(legacy,monkeypatch,multi):
    module,path,config,db,mappings=legacy
    adopt(legacy)
    counters={m['channel']:0 for m in mappings}
    scripts={m['channel']:[m['name'],m['name'],None,'Other','Other',m['name'],m['name']] for m in mappings}
    clock=multi[-1]
    lock=threading.Lock(); active=set(); parallel=[0]; options_seen=[]
    monkeypatch.setattr(module,'schedule',lambda group,perform,emit,**kw:
        SCHEDULE(group,perform,emit,clock=lambda:clock[0],sleep=lambda t:clock.__setitem__(0,clock[0]+t),**kw))
    class Resident:
        def close(self):pass
    monkeypatch.setattr(module.shadow,'ResidentNeural',Resident)
    def capture(args,source,requirements,index,**options):
        login=source.value
        with lock:
            assert login not in active
            active.add(login);parallel[0]=max(parallel[0],len(active))
            n=counters[login];counters[login]+=1
        try:
            time.sleep(.001)  # Exercise worker overlap, not a throughput benchmark.
            options_seen.append((login,args.automatic_characters,args.character_names,id(options.get('resident'))))
            name=scripts[login][n%len(scripts[login])]
            reference=options['identity'].suggestions.reference if 'identity' in options else 'manual'
            r=record(index,name,selected=reference,at=AT+timedelta(minutes=10,seconds=(n+1)*20),bp=4000+n*10)
            r['source']=dict(kind='twitch',channel=login)
            if not args.character_names:r.pop('character_name')
            return r
        finally:
            with lock:active.remove(login)
    monkeypatch.setattr(module.shadow,'capture_attempt',capture)
    return legacy,scripts,counters,parallel,options_seen


def run_existing(legacy,channels,*extra):
    module,path,config,_,_=legacy
    path.write_text(json.dumps(config))
    argv=['--config',str(path),'--exit-after-capture']
    for channel in channels:argv+=['--automatic-existing-channel',channel]
    return module.main([*argv,*extra])


@pytest.mark.parametrize('legacy',['correctly_named'],indirect=True)
def test_actual_telfer1_login_activation_expansion_and_disable(existing_capture):
    legacy,scripts,counters,_,seen=existing_capture
    _,_,config,db,mappings=legacy
    saved=dump_tables(db,['characters','character_renames','sessions','manual_corrections'])
    for row in config['streams']:row['count']=2
    for m in mappings:scripts[m['channel']]=[m['name']]
    with Store(db,read_only=True) as store:before=adoption.database_digest(store)
    assert run_existing(legacy,['telfer'],'--existing-tracker','--check')==1
    assert not seen
    assert run_existing(legacy,['telfer1'],'--existing-tracker','--check')==0
    with Store(db,read_only=True) as store:assert adoption.database_digest(store)==before
    assert run_existing(legacy,['telfer1'],'--existing-tracker','--workers','3')==0
    assert all(a==b==(login=='telfer1') for login,a,b,_ in seen)
    assert dump_tables(db,list(saved))==saved
    seen.clear()
    assert run_existing(legacy,['telfer1','channel1'],'--existing-tracker','--workers','3')==0
    assert all(a==b==(login in ('telfer1','channel1')) for login,a,b,_ in seen)
    assert dump_tables(db,list(saved))==saved
    assert all(row['interval']==20 for row in config['streams'])
    # A later switch and disable must preserve the selected ID despite config's Telfer label.
    scripts['telfer1']=['Other']
    assert run_existing(legacy,['telfer1','channel1'],'--existing-tracker','--workers','3')==0
    with Store(db,read_only=True) as store:
        selected=store._channel('telfer1')['selected_character_id']
        assert store.db.execute('SELECT label FROM characters WHERE id=?',(selected,)).fetchone()[0]=='Other'
    seen.clear()
    assert run_existing(legacy,[],'--existing-tracker','--workers','3')==0
    assert all(not auto and not names for _,auto,names,_ in seen)
    with Store(db,read_only=True) as store:assert store._channel('telfer1')['selected_character_id']==selected


def test_thirteen_channels_mixed_workers_restart_expand_and_disable(existing_capture):
    legacy,scripts,counters,parallel,seen=existing_capture
    _,_,config,db,mappings=legacy
    enabled=[m['channel'] for m in mappings[:3]]
    with Store(db,read_only=True) as store:before={m['channel']:store._channel(m['channel'])['selected_character_id'] for m in mappings}
    assert run_existing(legacy,enabled,'--workers','3','--continuous','--max-attempts','7')==0
    assert parallel[0]>1 and len({r[3] for r in seen})==1
    assert all(a==b==(login in enabled) for login,a,b,_ in seen)
    with Store(db,read_only=True) as store:
        assert {login:store._channel(login)['selected_character_id'] for login in before}==before
        assert store.db.execute('SELECT COUNT(*) FROM characters').fetchone()[0]==16  # Three distinct channel-owned Others.
        assert sum(v['verified'] for v in adoption.states(store).values())==3
        for login in enabled:
            saved=store.db.execute('''SELECT e.character_id,e.receipt_json FROM automatic_character_events e
                JOIN streamers s ON s.id=e.streamer_id WHERE s.login=? AND e.event_id NOT LIKE 'existing-%' ''',(login,)).fetchall()
            assert len(saved)==2 and saved[0]['character_id']!=before[login] and saved[1]['character_id']==before[login]
        ids={login:store._channel(login)['selected_character_id'] for login in before}
    # Expand all 13 without replacing the database, then finish on another character.
    enabled=list(before)
    for row in config['streams']:row['count']=4
    for m in mappings:scripts[m['channel']]=[m['name']]*counters[m['channel']]+[m['name'],m['name'],'Other','Other']
    assert run_existing(legacy,enabled,'--workers','3')==0
    with Store(db,read_only=True) as store:
        selected={login:store._channel(login)['selected_character_id'] for login in before}
        assert all(selected[c]!=ids[c] for c in selected)
        assert len(set(selected.values()))==13 and all(v['verified'] for v in adoption.states(store).values())
    # Restart with stale legacy config labels: never restore Main or Hero implicitly.
    for row in config['streams']:row['count']=2
    for login in scripts:scripts[login]=['Other']
    assert run_existing(legacy,enabled,'--workers','3')==0
    assert run_existing(legacy,[],'--existing-tracker','--workers','3','--hud-cache-seconds','60')==0  # Disable without reverting selection; manual caching can resume.
    with Store(db,read_only=True) as store:
        assert {login:store._channel(login)['selected_character_id'] for login in before}==selected
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
        diagnostic=Diagnostics(store)
        for login,cid in selected.items():
            snapshot=diagnostic.snapshot(login)
            assert snapshot['selected_character']['id']==cid
            assert all(r['id']==cid for r in diagnostic.roster(login) if r['current'])


def test_thirteen_channel_rotation_preserves_sessions_and_attribution(existing_capture):
    legacy,scripts,_,_,_=existing_capture
    _,_,_,db,mappings=legacy
    for m in mappings:scripts[m['channel']]=[m['name']]
    enabled=[m['channel'] for m in mappings]
    assert run_existing(legacy,enabled,'--workers','3','--continuous','--max-attempts','61')==0
    with Store(db,read_only=True) as store:
        assert store.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==13
        for m in mappings:
            rows=store.db.execute('SELECT * FROM diagnostic_runs WHERE character_id=? ORDER BY rowid',(m['character_id'],)).fetchall()
            assert len(rows)==3 and len({r['session_id'] for r in rows})==1
            assert json.loads(rows[1]['summary_json'])['completion_reason']=='scheduled_rotation'
            assert all(r['character_id']==m['character_id'] for r in rows)
            assert [store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts WHERE run_id=?',(r['run_id'],)).fetchone()[0] for r in rows]==[1,60,1]


def test_existing_check_flags_and_pending_disable_are_read_only(existing_capture,monkeypatch):
    legacy,_,_,_,_=existing_capture
    module,_,_,db,mappings=legacy
    enabled=[mappings[0]['channel']]
    with Store(db,read_only=True) as store:before=adoption.database_digest(store)
    assert run_existing(legacy,enabled,'--check')==0
    assert run_existing(legacy,['notadopted'],'--check')==1
    assert run_existing(legacy,enabled,'--hud-cache-seconds','60','--check')==1
    assert run_existing(legacy,enabled,'--automatic-characters','--check')==1
    with Store(db,read_only=True) as store:assert adoption.database_digest(store)==before
    # Port collisions fail before initialization or capture.
    monkeypatch.setattr(module,'available_port',lambda _,**kw:(_ for _ in ()).throw(ValueError('port busy')))
    assert run_existing(legacy,enabled)==1
    with Store(db,read_only=True) as store:assert adoption.database_digest(store)==before


@pytest.mark.parametrize('interruption',['failed','unreadable','duplicate','multiple_huds','delayed'])
def test_initial_confirmation_needs_independent_uninterrupted_evidence(legacy,interruption):
    db=legacy[3];adopt(legacy,[legacy[4][0]])
    with Store(db) as store:
        policy=AutonomousCharacters(store);Diagnostics(store).begin('verify','channel0',header('verify'))
        first=record(1,'Hero0',selected='Hero0',at=AT)
        policy.append('verify',first,'unused1',header('unused1'))
        second=record(2,'Hero0',selected='Hero0',at=AT+timedelta(seconds=20))
        if interruption=='failed':
            second=dict(type='attempt',trusted=False,index=2,current=False,status='capture_failed',
                        attempted_at=second['attempted_at'],source=second['source'],reasons=['frame_timeout'])
        elif interruption=='unreadable':second=record(2,None,at=AT+timedelta(seconds=20))
        elif interruption=='duplicate':second['character_name']['suggestion']=dict(latest_status='duplicate_frame')
        elif interruption=='multiple_huds':second['localization']['count']=2
        elif interruption=='delayed':second['received_at']=second['attempted_at']=(AT+timedelta(minutes=3)).isoformat();second['character_name']['evidence']['received_at']=second['received_at']
        policy.append('verify',second,'unused2',header('unused2'))
        assert not adoption.states(store)['channel0']['verified']
        if interruption=='delayed':
            third=record(3,'Hero0',selected='Hero0',at=AT+timedelta(minutes=3,seconds=20))
            policy.append('verify',third,'unused3',header('unused3'))
            assert adoption.states(store)['channel0']['verified']
        else:
            for n in (3,4):
                policy.append('verify',record(n,'Hero0',selected='Hero0',at=AT+timedelta(seconds=n*20)),f'unused{n}',header(f'unused{n}'))
                assert adoption.states(store)['channel0']['verified']==(n==4)


def test_systematic_wrong_name_creates_separate_history_never_relabels_legacy(legacy):
    db=legacy[3];adopt(legacy,[legacy[4][0]])
    with Store(db) as store:
        original_id=legacy[4][0]['character_id']
        policy=AutonomousCharacters(store);Diagnostics(store).begin('verify','channel0',header('verify'))
        first=policy.append('verify',record(1,'Wrong',selected='Hero0',at=AT),'next1',header('next1'))
        second=policy.append('verify',record(2,'Wrong',selected='Hero0',at=AT+timedelta(seconds=20)),'next2',header('next2'))
        assert first['record']['current'] is False and second['switched']
        assert second['character_id']!=original_id
        assert store.db.execute('SELECT label FROM characters WHERE id=?',(original_id,)).fetchone()[0]=='Hero0'
        assert store.db.execute("SELECT character_id FROM diagnostic_runs WHERE run_id='old0'").fetchone()[0]==original_id


def test_adoption_preserves_compacted_checkpoints_and_daily_snapshots(legacy):
    db=legacy[3]
    with Store(db) as store:
        prune(store,now=AT+timedelta(days=2),dry_run=False,active_runs=set())
        assert store.db.execute('SELECT COUNT(*) FROM retention_state').fetchone()[0]==13
        assert store.db.execute('SELECT COUNT(*) FROM daily_character_exp').fetchone()[0]>0
    before=dump_tables(db,['retention_state','daily_character_exp','manual_corrections','sessions'])
    adopt(legacy)
    assert dump_tables(db,list(before))==before


def test_external_existing_config_resolves_its_own_database_without_relaxing_defaults(legacy,monkeypatch,tmp_path):
    module,path,_,db,_=legacy
    adopt(legacy)
    feature_root=tmp_path/'separate-feature'
    monkeypatch.setattr(module.shadow,'ROOT',feature_root)
    with pytest.raises(ValueError,match='ignored'):
        module.load_config(path)
    resolved,_,streams=module.load_config(path,existing_tracker=True)
    assert resolved==db and len(streams)==13
    module.existing_preflight(resolved,streams,[],required=True)
    assert not feature_root.exists()  # No accidental fresh database or placeholder.


def test_public_and_obs_selection_stays_channel_scoped_after_adoption(legacy):
    from exp_tracker.server import create_server
    from tests.test_server import request
    from tests.test_character_profiles import get
    _,_,_,db,mappings=legacy
    adopt(legacy)
    with Store(db) as store:
        policy=AutonomousCharacters(store); Diagnostics(store).begin('web','channel0',header('web'))
        policy.append('web',record(1,'Other',selected='Hero0',at=AT),'new1',header('new1'))
        r=policy.append('web',record(2,'Other',selected='Hero0',at=AT+timedelta(seconds=20)),'new2',header('new2'))
        selected=r['character_id']
    httpd=create_server(db,port=0,public_only=True)
    try:
        code,profile=get(httpd,'/api/players/channel0')
        assert code==200 and profile['player']['character']['id']==selected
        code,old=get(httpd,f"/api/players/channel0?character={mappings[0]['character_id']}")
        assert code==200 and old['player']['character']['id']==mappings[0]['character_id']
        assert request((httpd,None),'/live/overlay/channel0')[0]==200
        assert request((httpd,None),f"/api/players/channel1?character={selected}")[0]==404
        with Store(db,read_only=True) as store:assert store._channel('channel0')['selected_character_id']==selected
    finally:httpd.server_close()


def test_verified_state_and_level_floor_roll_back_if_capture_logging_fails(legacy):
    db=legacy[3];adopt(legacy,[legacy[4][0]])
    with Store(db) as store:
        policy=AutonomousCharacters(store); Diagnostics(store).begin('verify','channel0',header('verify'))
        policy.append('verify',record(1,'Hero0',selected='Hero0',at=AT),'next1',header('next1'))
        second=record(2,'Hero0',selected='Hero0',at=AT+timedelta(seconds=20))
        def fail(*args):raise OSError('private log unavailable')
        with pytest.raises(OSError):policy.append('verify',second,'next2',header('next2'),write=fail)
        assert not adoption.states(store)['channel0']['verified']
        assert store.db.execute("SELECT COUNT(*) FROM diagnostic_attempts WHERE run_id='verify'").fetchone()[0]==1
        assert policy.append('verify',second,'next2',header('next2'))['record']['current']
        low=policy.append('verify',record(3,'Hero0',level=29,selected='Hero0',at=AT+timedelta(seconds=40)),'next3',header('next3'))
        assert low['record']['level_hold']['reason']=='level_regression'
        assert store.db.execute('SELECT level FROM character_level_guard WHERE character_id=?',(legacy[4][0]['character_id'],)).fetchone()[0]==30
