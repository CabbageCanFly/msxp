"""Offline automation, atomicity and non-regression on disposable SQLite only."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import time
import sqlite3

import pytest

from exp_tracker.character_automation import AutonomousCharacters
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.exp_requirements import requirement
from exp_tracker.retention import prune
from exp_tracker.store import Store
from tests.test_identity_coordinator import coordinator  # noqa: F401
from tests.test_multi_alpha import multi  # noqa: F401
from tests.test_identity_coordinator import SCHEDULE
from tests.test_store import profile, reading  # noqa: F401

AT = datetime.now(timezone.utc) - timedelta(hours=1)


def config(run='first'):
    return dict(type='configuration',trusted=False,run_id=run,interval=15,automatic_characters=True,
                source_kind='file',timing_mode='real',character_names=True)


def record(index, name='Alpha', level=30, bp=4000, *, selected='Alpha', score=.99, at=None):
    exp=requirement(level)['to_next'] * bp // 10000
    pct=exp*10000//requirement(level)['to_next']/100
    stamp=(at or AT+timedelta(seconds=index*15)).isoformat()
    digest=hashlib.sha256(f'{stamp}:{name}:{bp}'.encode()).hexdigest()
    text=f'{exp}[{pct:.2f}%]'
    return dict(type='attempt',trusted=False,index=index,current=True,status='diagnostic_pair',
        attempted_at=stamp,received_at=stamp,frame_sha256=digest,local_age_seconds=0,
        source=dict(kind='file',channel=None),visual_level=level,visual_status='available',
        neural_status='single_line',candidate=[exp,pct],neural=dict(text=text),localization=dict(count=1),
        character_name=dict(reading_hold_recommended=bool(name and name!=selected),
            hold_reasons=['name_mismatch'] if name and name!=selected else [],identity_conflict=None,
            evidence=dict(status='candidate' if name else 'unreadable_or_conflicting',name=name,score=score,
                received_at=stamp,pixel_sha256=digest,box=[1,2,50,20],provenance=dict(layout_count=1,search='full_frame'),
                raw=dict(raw=dict(txts=[name],scores=[score])))))


@pytest.fixture
def auto(tmp_path):
    path=tmp_path/'disposable.sqlite3'
    with Store(path) as store:
        store.add_channel('alpha')
        cid=store.add_character('alpha','Alpha')
        store.select_character('alpha',cid,at=AT)
        store.start_session('alpha',at=AT)
        Diagnostics(store).begin('first','alpha',config())
        yield path,store,AutonomousCharacters(store)


def sequence(auto, names, *, levels=None, bps=None):
    _,store,policy=auto; run='first'; receipts=[]
    for i,name in enumerate(names,1):
        selected=store.db.execute('SELECT label FROM characters WHERE id=?',(store._channel('alpha')['selected_character_id'],)).fetchone()[0]
        index=store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts WHERE run_id=?',(run,)).fetchone()[0]+1
        value=record(index,name,level=levels[i-1] if levels else 30,bp=bps[i-1] if bps else 4000+i*10,
                     selected=selected,at=AT+timedelta(seconds=i*15))
        r=policy.append(run,value,f'next{i}',config(f'next{i}'))
        run=r['run_id'];receipts.append(r)
    return receipts


def test_aabbb_switches_on_fourth_and_keeps_first_b_held(auto):
    _,store,_=auto
    rows=sequence(auto,['Alpha','Alpha','Beta','Beta','Beta'])
    assert [r['switched'] for r in rows]==[False,False,False,True,False]
    assert 'identity_hold' in rows[2]['record']
    assert rows[3]['record']['index']==1 and rows[3]['name']=='Beta'
    # A viewed guest feed receives the same scoped, auditable association; OCR cannot prove ownership.
    assert rows[3]['record']['automatic_selection']['visible_feed_association'] is True
    assert rows[3]['record']['candidate']==record(4,'Beta',bp=4040)['candidate']
    assert rows[4]['session_id']==rows[3]['session_id']!=rows[1]['session_id']
    assert store.db.execute('SELECT COUNT(*) FROM characters').fetchone()[0]==2
    ids=[r[0] for r in store.db.execute('SELECT character_id FROM diagnostic_runs ORDER BY rowid')]
    assert ids==[rows[0]['character_id'],rows[3]['character_id']]
    assert store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==0
    d=Diagnostics(store)
    card=d.directory({},now=AT+timedelta(minutes=2))['streams'][0]
    assert card['character']['label']=='Beta'
    assert int(card['player']['reading']['exp'])==record(5,'Beta',bp=4050)['candidate'][0]
    # The entire public packet can only contain B's run as its current session.
    snapshot=d.snapshot('alpha',now=AT+timedelta(minutes=2))
    assert len(snapshot['observations'])==2
    assert {p['character_id'] for p in snapshot['observations']}=={rows[3]['character_id']}


def test_abbAA_returns_to_existing_id_without_joining_sessions(auto):
    rows=sequence(auto,['Alpha','Beta','Beta','Alpha','Alpha'])
    assert rows[2]['switched'] and rows[4]['switched']
    assert rows[4]['character_id']==rows[0]['character_id']
    assert len({r['session_id'] for r in rows})==3
    assert auto[1].db.execute('SELECT COUNT(*) FROM characters').fetchone()[0]==2
    assert len(Diagnostics(auto[1]).snapshot('alpha')['observations'])==1


def test_noise_and_unreadable_names_preserve_available_progress(auto):
    rows=sequence(auto,['Alpha','Alpha','Noise','Alpha',None,None])
    assert not any(r['switched'] for r in rows)
    assert 'identity_hold' in rows[2]['record']
    assert all(rows[i]['record']['current'] for i in (1,3,4,5))
    assert auto[1].db.execute('SELECT COUNT(*) FROM characters').fetchone()[0]==1


def test_known_mismatch_remains_held_through_unreadability(auto):
    rows=sequence(auto,['Alpha','Alpha','Beta',None,None,'Alpha'])
    assert all('identity_hold' in rows[i]['record'] for i in (2,3,4))
    assert rows[5]['record']['current']


def test_single_high_ocr_does_not_poison_floor_and_old_clip_cannot_regress(auto):
    rows=sequence(auto,['Alpha']*7,levels=[67,67,80,67,53,67,67])
    assert rows[2]['record']['level_hold']['reason']=='level_confirmation_pending'
    assert rows[4]['record']['level_hold']['reason']=='level_regression'
    assert rows[3]['record']['current'] and rows[5]['record']['current']
    assert auto[1].db.execute('SELECT level FROM character_level_guard').fetchone()[0]==67
    snapshot=Diagnostics(auto[1]).snapshot('alpha',now=AT+timedelta(minutes=4))
    assert 53 not in [r['visual_level'] for r in snapshot['observations']]
    assert 80 not in [r['visual_level'] for r in snapshot['observations']]


def test_level_up_unreadability_and_same_level_death_loss(auto):
    rows=sequence(auto,['Alpha','Alpha',None,None,None,'Alpha'],
                  levels=[30,30,31,31,31,31],bps=[9900,9950,100,200,150,250])
    assert rows[2]['record']['level_hold']['reason']=='level_confirmation_pending'
    assert all(rows[i]['record']['current'] for i in (3,4,5))
    assert auto[1].db.execute('SELECT level FROM character_level_guard').fetchone()[0]==31


def test_rollback_and_idempotent_switch_receipt(auto):
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha','Beta'])
    b=record(4,'Beta',bp=4040)
    def fail(*args):raise OSError('disk failed')
    with pytest.raises(OSError):policy.append('first',b,'failed',config('failed'),write=fail)
    assert store.db.execute('SELECT COUNT(*) FROM characters').fetchone()[0]==1
    assert store.db.execute('SELECT summary_json FROM diagnostic_runs').fetchone()[0] is None
    receipt=policy.append('first',b,'succeeded',config('succeeded'))
    assert receipt['switched']
    again=policy.append('first',b,'unused',config('unused'))
    assert again['duplicate'] and again['run_id']=='succeeded'
    assert store.db.execute('SELECT COUNT(*) FROM automatic_character_events').fetchone()[0]==1
    changed=deepcopy(b);changed['candidate'][0]+=1
    with pytest.raises(ValueError,match='different input'):policy.append('first',changed,'unused',config('unused'))


def test_multiple_huds_and_creation_cap_keep_the_mismatch_held(auto):
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha'])
    for i in (3,4):
        value=record(i,'Beta');value['localization']['count']=2
        assert not policy.append('first',value,f'no{i}',config(f'no{i}'))['switched']
    for i in range(15):store.add_character('alpha',f'Existing{i}')
    for i in (5,6):
        result=policy.append('first',record(i,'Beta'),f'no{i}',config(f'no{i}'))
        assert 'identity_hold' in result['record'] and not result['switched']
    assert store.db.execute('SELECT COUNT(*) FROM characters').fetchone()[0]==16
    # The cap limits creation, never selection of an already existing character.
    for i in (7,8):
        result=policy.append('first',record(i,'Existing0'),f'yes{i}',config(f'yes{i}'))
    assert result['switched'] and result['name']=='Existing0'


def test_low_quality_or_duplicate_names_never_create_characters(auto):
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha'])
    for i in (3,4):policy.append('first',record(i,'Beta',score=.6),f'no{i}',config(f'no{i}'))
    b=record(5,'Beta');policy.append('first',b,'no5',config('no5'))
    clone=deepcopy(b);clone.update(index=6,received_at=(AT+timedelta(seconds=90)).isoformat())
    clone['character_name']['evidence']['received_at']=clone['received_at']
    assert not policy.append('first',clone,'no6',config('no6'))['switched']
    assert store.db.execute('SELECT COUNT(*) FROM characters').fetchone()[0]==1


def test_floor_survives_restart_retention_and_new_session(auto):
    path,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[67,67])
    Diagnostics(store).append('first',dict(type='summary',trusted=False,attempts=2,interrupted=False))
    prune(store,now=AT+timedelta(days=2),dry_run=False)
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==67
    # A checkpoint can predate the latest validated level and must not lower its display.
    saved=store.db.execute('SELECT checkpoint_json FROM retention_state').fetchone()
    checkpoint=json.loads(saved[0]);checkpoint['display']['display_level']['value']=53
    store.db.execute('UPDATE retention_state SET checkpoint_json=?',(json.dumps(checkpoint),))
    with Store(path) as cold:
        cold.end_session('alpha',at=AT+timedelta(days=2))
        cold.start_session('alpha',at=AT+timedelta(days=2))
        Diagnostics(cold).begin('cold','alpha',config('cold'))
        r=AutonomousCharacters(cold).append('cold',record(1,level=53,at=AT+timedelta(days=2,seconds=15)),
                                          'unused',config('unused'))
        assert r['record']['level_hold']['reason']=='level_regression'
        card=Diagnostics(cold).directory({},now=AT+timedelta(days=2,seconds=20))['streams'][0]
        assert card['player']['display_level']['value']==67


def test_existing_session_cannot_be_rebound_by_a_late_capture(auto):
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha','Beta'])
    other=store.add_character('alpha','Operator')
    store.select_character('alpha',other,at=AT+timedelta(minutes=2))
    store.start_session('alpha',at=AT+timedelta(minutes=2))
    with pytest.raises(ValueError,match='assignment changed'):
        policy.append('first',record(4,'Beta'),'late',config('late'))
    assert store._channel('alpha')['selected_character_id']==other


def test_nested_store_calls_roll_back_as_a_unit(auto):
    _,store,_=auto
    with pytest.raises(ValueError):
        with store._transaction():
            char=store.add_character('alpha','RolledBack')
            store.select_character('alpha',char,at=AT+timedelta(minutes=1))
            raise ValueError('injected')
    assert store.db.execute('SELECT COUNT(*) FROM characters').fetchone()[0]==1
    assert store._open_session(store._channel('alpha')['id'])['ended_at'] is None


def test_automatic_coordinator_uses_existing_real_capture_path(coordinator):
    # The existing fixture drives two channels through real analyze/identity/persistence.
    module,path,config_value=coordinator[:3]
    assert module.main(['--config',str(path),'--automatic-characters','--exit-after-capture'])==0
    db=path.parent/'shared.sqlite3'
    with Store(db,read_only=True) as store:
        names={r[0] for r in store.db.execute('SELECT label FROM characters')}
        assert {'Alpha','Beta','Bravo'}<=names
        assert store.db.execute('SELECT COUNT(*) FROM automatic_character_events').fetchone()[0]>=2
        assert store.db.execute('PRAGMA foreign_key_check').fetchone() is None


@pytest.fixture
def lanes(multi,monkeypatch):  # noqa: F811
    module,path,settings,_,clock=multi
    settings['streams']=[dict(channel=channel,character='Alpha',source='file',file=settings['streams'][0]['file'],
                             count=5,interval=15) for channel in ('alpha','beta')]
    path.write_text(json.dumps(settings))
    scripts={c:['Alpha','Alpha','Beta','Beta','Beta'] for c in ('alpha','beta')}
    counters=dict(alpha=0,beta=0)
    start=datetime.now(timezone.utc)+timedelta(minutes=5)
    def sleep(seconds):clock[0]+=seconds
    monkeypatch.setattr(module,'schedule',lambda group,perform,emit,**kw:
                        SCHEDULE(group,perform,emit,clock=lambda:clock[0],sleep=sleep,**kw))
    def capture(args,source,requirements,index,**options):
        channel=args.tracking_channel
        n=counters[channel];counters[channel]+=1
        names=scripts[channel];name=names[n%len(names)]
        reference=options['identity'].suggestions.reference
        time.sleep(.005)  # Exercise actual overlapping scheduler workers, without shared OCR globals.
        return record(index,name,selected=reference,at=start+timedelta(seconds=15*(n+1)))
    monkeypatch.setattr(module.shadow,'capture_attempt',capture)
    return module,path,settings,scripts,counters


def test_parallel_channels_switch_independently_and_restart_reuses_selection(lanes):
    module,path,settings,scripts,counters=lanes
    assert module.main(['--config',str(path),'--automatic-characters','--workers','3','--exit-after-capture'])==0
    db=path.parent/'shared.sqlite3'
    with Store(db,read_only=True) as store:
        selected={c:store._channel(c)['selected_character_id'] for c in scripts}
        assert selected['alpha']!=selected['beta']
        assert store.db.execute('SELECT COUNT(*) FROM characters').fetchone()[0]==4
        sessions=store.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
    # The configured label is still Alpha; autonomous restart must keep the selected Beta.
    for c in scripts:scripts[c]=['Beta']
    assert module.main(['--config',str(path),'--automatic-characters','--workers','2','--exit-after-capture'])==0
    with Store(db,read_only=True) as store:
        assert {c:store._channel(c)['selected_character_id'] for c in scripts}==selected
        assert store.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==sessions
        assert store.db.execute('SELECT COUNT(*) FROM automatic_character_events').fetchone()[0]==2


def test_switch_crosses_rotation_and_returns_without_history_leak(lanes):
    module,path,_,scripts,_=lanes
    for c in scripts:scripts[c]=['Alpha']*59+['Beta','Beta','Beta','Alpha','Alpha']
    assert module.main(['--config',str(path),'--automatic-characters','--continuous',
                        '--max-attempts','64','--workers','2','--exit-after-capture'])==0
    with Store(path.parent/'shared.sqlite3',read_only=True) as store:
        for c in scripts:
            cid=store._channel(c)['selected_character_id']
            assert store.db.execute('SELECT label FROM characters WHERE id=?',(cid,)).fetchone()[0]=='Alpha'
            runs=store.db.execute('SELECT * FROM diagnostic_runs WHERE streamer_id=? ORDER BY rowid', (store._channel(c)['id'],)).fetchall()
            assert len(runs)==4
            counts=[store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts WHERE run_id=?',(r['run_id'],)).fetchone()[0] for r in runs]
            assert counts==[60,0,3,1]
            for run,count in zip(runs,counts):
                assert [r[0] for r in store.db.execute('SELECT attempt_index FROM diagnostic_attempts WHERE run_id=? ORDER BY attempt_index',(run['run_id'],))]==list(range(1,count+1))
            packet=Diagnostics(store).rolling_history(c,now=datetime.now(timezone.utc)+timedelta(hours=1))
            assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
            assert packet['channel']==c


def test_log_failure_rolls_back_switch_and_other_channel_continues(lanes,monkeypatch):
    module,path,_,scripts,_=lanes
    real=AutonomousCharacters.append
    def injected(self,run_id,value,following,configuration,*,write=None):
        def broken(receipt,payload):
            write(receipt,payload)
            if receipt['switched'] and self.store._channel('alpha')['id']==self.db.execute(
                    'SELECT streamer_id FROM diagnostic_runs WHERE run_id=?',(run_id,)).fetchone()[0]:
                raise OSError('injected after log flush')
        return real(self,run_id,value,following,configuration,write=broken)
    monkeypatch.setattr(AutonomousCharacters,'append',injected)
    assert module.main(['--config',str(path),'--automatic-characters','--workers','2','--exit-after-capture'])==1
    with Store(path.parent/'shared.sqlite3',read_only=True) as store:
        assert store.db.execute('SELECT COUNT(*) FROM automatic_character_events').fetchone()[0]==1
        state=store._channel('alpha')
        assert store.db.execute('SELECT label FROM characters WHERE id=?',(state['selected_character_id'],)).fetchone()[0]=='Alpha'
    monkeypatch.setattr(AutonomousCharacters,'append',real)
    for c in scripts:scripts[c]=['Beta']
    assert module.main(['--config',str(path),'--automatic-characters','--workers','2','--exit-after-capture'])==0
    with Store(path.parent/'shared.sqlite3',read_only=True) as store:
        assert store.db.execute('SELECT COUNT(*) FROM automatic_character_events').fetchone()[0]==2


def test_existing_nonautomatic_database_is_refused(lanes):
    module,path,_,_,_=lanes
    db=path.parent/'shared.sqlite3'
    # Construct a non-automatic ownership marker without ever connecting to production.
    with Store(db):pass
    db.with_suffix(db.suffix+'.multi-alpha.json').write_text(json.dumps(dict(application=module.APP)))
    before=db.read_bytes()
    assert module.main(['--config',str(path),'--automatic-characters','--exit-after-capture'])==1
    assert db.read_bytes()==before


def test_manual_correction_cannot_lower_current_floor_but_history_remains_editable(auto):
    _,store,_=auto
    sequence(auto,['Alpha','Alpha'],levels=[67,67])
    cid=store._channel('alpha')['selected_character_id']
    proof=json.loads(store.db.execute('SELECT proof_json FROM character_level_guard').fetchone()[0])
    proof['received_at']=datetime.fromisoformat(proof['received_at']).astimezone(timezone(timedelta(hours=-4))).isoformat()
    store.db.execute('UPDATE character_level_guard SET proof_json=?',(json.dumps(proof),))
    with pytest.raises(ValueError,match='cannot regress'):
        store.correct_manual('alpha','regress',cid,level=53,current_exp=10,effective_at=AT+timedelta(minutes=1))
    value=store.correct_manual('alpha','historical',cid,level=53,current_exp=10,
        kind='point',target_kind='diagnostic',target_event_id='first:1',effective_at=AT+timedelta(seconds=15))
    assert value['level']==53
    assert Diagnostics(store).directory({},now=AT+timedelta(minutes=2))['streams'][0]['player']['display_level']['value']==67
    store.correct_manual('alpha','higher',cid,level=68,current_exp=10,effective_at=AT+timedelta(minutes=3))
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==68


def test_persisted_floor_also_guards_nonautomatic_writers(auto,profile):
    _,store,_=auto
    rows=sequence(auto,['Alpha','Alpha'],levels=[67,67])
    d=Diagnostics(store)
    d.append('first',dict(type='summary',trusted=False,attempts=2,interrupted=False))
    plain=config('plain');plain.pop('automatic_characters')
    d.begin('plain','alpha',plain)
    d.append('plain',record(1,level=53,at=AT+timedelta(minutes=1)))
    payload=json.loads(store.db.execute("SELECT payload_json FROM diagnostic_attempts WHERE run_id='plain'").fetchone()[0])
    assert payload['level_hold']['reason']=='level_regression'
    for level,reason in ((53,'validated_character_level_regression'),(80,'validated_character_level_confirmation_required')):
        outcome=store.ingest('alpha',f'trusted-{level}',AT+timedelta(minutes=level),reading(level=level),
                             profile=profile,session_id=rows[-1]['session_id'])
        assert outcome['reason']==reason
    with pytest.raises(sqlite3.IntegrityError,match='cannot regress'):
        store.db.execute('UPDATE character_level_guard SET level=53')


def test_missing_frame_cannot_join_two_anomalously_high_level_reads(auto):
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[67,67])
    policy.append('first',record(3,level=80),'unused3',config('unused3'))
    failed=dict(type='attempt',trusted=False,index=4,status='capture_failed',current=False,
                attempted_at=(AT+timedelta(seconds=60)).isoformat(),source=dict(kind='file'))
    policy.append('first',failed,'unused4',config('unused4'))
    r=policy.append('first',record(5,level=80),'unused5',config('unused5'))
    assert r['record']['level_hold']['reason']=='level_confirmation_pending'
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==67


def test_missing_exp_requirement_needs_two_frames_with_two_agreeing_level_readers(auto):
    _,store,policy=auto
    for i in (1,2):
        value=record(i)
        value.update(visual_level=100,neural_level=dict(level=100,text='100',status='numeric_candidate',
                                                     score=.99,preprocessing='neutral4'))
        result=policy.append('first',value,f'unused{i}',config(f'unused{i}'))
    assert result['record']['current']
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==100


def test_schema9_stays_readable_and_writer_migrates_atomically(tmp_path):
    from exp_tracker import schema
    path=tmp_path/'legacy9.sqlite3'
    with sqlite3.connect(path) as db:
        for statement in (*schema.STATEMENTS,*schema.MIGRATION_2,*schema.MIGRATION_3,*schema.MIGRATION_4,
                *schema.MIGRATION_5,*schema.MIGRATION_6,*schema.MIGRATION_7,*schema.MIGRATION_8,*schema.MIGRATION_9):db.execute(statement)
        db.execute('PRAGMA user_version=9')
    before=path.read_bytes()
    with Store(path,read_only=True) as store:assert store.schema_version==9
    assert path.read_bytes()==before
    with Store(path) as store:
        assert store.schema_version==10
        assert store.db.execute('SELECT COUNT(*) FROM character_level_guard').fetchone()[0]==0
        assert store.db.execute('PRAGMA foreign_key_check').fetchone() is None


def test_percentage_only_levelup_can_use_two_independent_agreeing_readers(auto):
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[67,67])
    for i in (3,4):
        value=record(i,level=68)
        value.update(candidate=None,neural=dict(text='[10.00%]'),
                     neural_level=dict(level=68,text='68',status='numeric_candidate',score=.99,preprocessing='neutral4'))
        result=policy.append('first',value,f'noop{i}',config(f'noop{i}'))
    assert result['record']['current']
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==68
