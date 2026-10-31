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


def test_case_only_reads_keep_selected_id_even_when_a_duplicate_already_exists(auto):
    _,store,_=auto
    selected=store._channel('alpha')['selected_character_id']
    duplicate=store.add_character('alpha','alpha')
    rows=sequence(auto,['Alpha','alpha','ALPHA','aLpHa'])
    assert all(not r['switched'] and r['character_id']==selected for r in rows)
    assert duplicate!=selected
    assert store.db.execute('SELECT COUNT(*) FROM characters').fetchone()[0]==2


def test_case_insensitive_return_reuses_oldest_existing_id_and_preserves_label(auto):
    _,store,_=auto
    selected=store._channel('alpha')['selected_character_id']
    store.add_character('alpha','alpha')
    rows=sequence(auto,['Beta','BETA','alpha','ALPHA'])
    assert [r['switched'] for r in rows]==[False,True,False,True]
    assert rows[-1]['character_id']==selected and rows[-1]['name']=='Alpha'
    assert store.db.execute('SELECT COUNT(*) FROM characters').fetchone()[0]==3


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


@pytest.mark.parametrize('strict_pair',[True,False])
def test_lower_misread_contradicted_by_its_own_exp_pair_does_not_reset_a_level_up(auto,strict_pair):
    """Live Streamer_I: Tesseract read Lv. 19 as 13 twice right after a level-up, beside neural 19."""
    _,store,policy=auto;run='first';reasons=[]
    for i,level in enumerate([30,30,31,31],1):
        value=record(i,level=level,bp=9900 if level==30 else 300+i*100,at=AT+timedelta(seconds=i*15))
        if i==4:
            value.update(visual_level=13,neural_level=dict(status='numeric_candidate',text='31',level=31,score=.99,preprocessing='neutral4'))
            if not strict_pair:value.update(candidate=None,status='malformed_or_unavailable',neural=dict(text='unreadable'))
        r=policy.append(run,value,f'next{i}',config(f'next{i}'));run=r['run_id'];reasons.append((r['record'].get('level_hold') or {}).get('reason'))
    assert reasons[2]=='level_confirmation_pending'
    floor=store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]
    # Only the frame's own arithmetic can show the lower reading is a misread.
    assert (reasons[3],floor)==((None,31) if strict_pair else ('level_regression',30))


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


def stationary_levelup_record(index,exp=1437,interval=15):
    value=record(index,level=57,bp=14,at=AT+timedelta(seconds=index*interval))
    value.update(visual_level=None,visual_status='unavailable',candidate=[exp,.14],
        neural=dict(text=f'{exp:,}[0.14%]'),
        neural_level=dict(level=57,text='57',status='numeric_candidate',score=.99839,preprocessing='neutral4'))
    return value


def percentage_levelup_record(index,seconds,visual=None):
    value=record(index,level=58,at=AT+timedelta(seconds=seconds))
    value.update(status='diagnostic_percentage_only',candidate=None,neural=dict(text='[95.00%]'),
        visual_level=visual,visual_status='available' if visual else 'unavailable',
        neural_level=dict(level=58,text='58',status='numeric_candidate',score=.99,preprocessing='neutral4'))
    return value


@pytest.mark.parametrize('restart',[False,True])
@pytest.mark.parametrize('delay,duplicate,confirmed',[(109,False,True),(120,False,True),(121,False,False),(109,True,False)])
def test_percentage_levelup_preserves_agreement_across_incomplete_level_reads(auto,restart,delay,duplicate,confirmed):
    path,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[57,57])
    first=percentage_levelup_record(3,45,58)
    policy.append('first',first,'unused3',config())
    pending=store.db.execute('SELECT pending_json FROM character_level_guard').fetchone()[0]
    for index,seconds in ((4,70),(5,100)):
        held=policy.append('first',percentage_levelup_record(index,seconds),'unused',config())['record']
        assert held['level_hold']['reason']=='level_confirmation_pending'
        assert store.db.execute('SELECT level,pending_json FROM character_level_guard').fetchone()[:]==(57,pending)
    after=percentage_levelup_record(6,45+delay,58)
    if duplicate:
        after['frame_sha256']=first['frame_sha256']
        after['character_name']['evidence']['pixel_sha256']=first['character_name']['evidence']['pixel_sha256']
    def finish(writer):
        result=writer.append('first',after,'unused6',config())['record']
        assert result['current'] is confirmed
    if restart:
        with Store(path) as reopened:finish(AutonomousCharacters(reopened))
    else:finish(policy)
    level,proof=store.db.execute('SELECT level,proof_json FROM character_level_guard').fetchone()
    assert level==(58 if confirmed else 57)
    if confirmed:assert json.loads(proof)['support']['received_at']==first['received_at']


@pytest.mark.parametrize('changes',[
    dict(visual_level=59),
    dict(neural_level=dict(level=59,text='59',status='numeric_candidate',score=.99,preprocessing='neutral4')),
    dict(neural_level=dict(level=58,text='58',status='numeric_candidate',score=.89,preprocessing='neutral4')),
    dict(neural_level=dict(level=58,text='58',status='numeric_candidate',score=.99,preprocessing='rgb4')),
    dict(local_age_seconds=16),dict(localization=dict(count=2)),dict(automatic_identity_risk='conflict'),
    dict(character_name=dict(evidence=dict(status='unreadable_or_conflicting'))),
])
def test_percentage_levelup_unsafe_gap_clears_agreement(auto,changes):
    from exp_tracker.character_automation import guard_level
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[57,57])
    policy.append('first',percentage_levelup_record(3,45,58),'unused3',config())
    gap=percentage_levelup_record(4,70)
    gap.update(deepcopy(changes))
    guard_level(store,store._channel('alpha')['selected_character_id'],gap)
    assert store.db.execute('SELECT pending_json FROM character_level_guard').fetchone()[0] is None
    result=guard_level(store,store._channel('alpha')['selected_character_id'],percentage_levelup_record(5,100,58))
    assert result['level_hold']['reason']=='level_confirmation_pending'
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==57


def test_percentage_levelup_does_not_reuse_agreement_from_ended_session(auto):
    from exp_tracker.character_automation import guard_level
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[57,57])
    policy.append('first',percentage_levelup_record(3,45,58),'unused3',config())
    cid=store._channel('alpha')['selected_character_id']
    store.end_session('alpha',at=AT+timedelta(seconds=55))
    store.start_session('alpha',at=AT+timedelta(seconds=60))
    result=guard_level(store,cid,percentage_levelup_record(4,70,58))
    assert result['level_hold']['reason']=='level_confirmation_pending'
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==57


@pytest.mark.parametrize('restart',[False,True])
@pytest.mark.parametrize('interval',[5,20,55])
def test_named_neural_percentage_confirms_after_five_votes_and_thirty_seconds(auto,restart,interval):
    path,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[57,57])
    count=max(5,30//interval+1)
    for n in range(count):
        if n==2 and restart:
            with Store(path) as reopened:
                policy=AutonomousCharacters(reopened)
                result=policy.append('first',percentage_levelup_record(n+3,45+n*interval),'unused',config())['record']
            policy=AutonomousCharacters(store)
        else:result=policy.append('first',percentage_levelup_record(n+3,45+n*interval),'unused',config())['record']
        assert result['current'] is (n==count-1)
    floor,proof=store.db.execute('SELECT level,proof_json FROM character_level_guard').fetchone()
    assert floor==58
    proof=json.loads(proof)
    assert proof['basis']=='named_neural_percentage' and len(proof['votes'])==5
    assert proof['votes'][0]['received_at']==(AT+timedelta(seconds=45)).isoformat()
    later=percentage_levelup_record(count+3,45+count*interval)
    assert policy.append('first',later,'unused',config())['record']['current']
    snapshot=Diagnostics(store).snapshot('alpha',now=AT+timedelta(seconds=46+count*interval))
    assert snapshot['observations'][-1]['experimental_level']['value']==58
    assert snapshot['percentage_progress']['latest_percentage']['percentage']=='95.00'


@pytest.mark.parametrize('changes',[
    dict(visual_level=56),dict(visual_level=59),
    dict(neural_level=dict(level=58,text='58',status='numeric_candidate',score=.989,preprocessing='neutral4')),
    dict(neural_level=dict(level=58,text='58',status='numeric_candidate',score=.999,preprocessing='rgb4')),
    dict(neural_level=dict(level=58,text='58',status='numeric_candidate',score=.999,preprocessing='neutral4',source_complete=False)),
    dict(local_age_seconds=16),dict(localization=dict(count=2)),dict(automatic_identity_risk='mismatch'),
    dict(character_name=dict(evidence=dict(status='unreadable_or_conflicting'))),
    dict(neural=dict(text='[95.00%1'),percentage_only_candidate=None,status='malformed_or_unavailable'),
    dict(current=False,status='unavailable',reasons=['missing_hud'],localization=dict(count=0)),
])
def test_named_neural_percentage_unsafe_frame_resets_streak(auto,changes):
    from exp_tracker.character_automation import guard_level
    _,store,_=auto;sequence(auto,['Alpha','Alpha'],levels=[57,57])
    cid=store._channel('alpha')['selected_character_id']
    for i in range(4):guard_level(store,cid,percentage_levelup_record(i+3,45+i*20))
    bad=percentage_levelup_record(7,125);bad.update(deepcopy(changes))
    guard_level(store,cid,bad)
    assert store.db.execute('SELECT pending_json FROM character_level_guard').fetchone()[0] is None
    for i in range(4):
        assert not guard_level(store,cid,percentage_levelup_record(i+8,145+i*20))['current']
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==57


@pytest.mark.parametrize('case',['duplicate','out_of_order','gap','total_span','session','missing_name','jump','bootstrap','mixed_agreement'])
def test_named_neural_percentage_cannot_confirm_from_invalid_streak(auto,case):
    from exp_tracker.character_automation import guard_level
    _,store,_=auto
    if case!='bootstrap':sequence(auto,['Alpha','Alpha'],levels=[57,57])
    cid=store._channel('alpha')['selected_character_id']
    values=[percentage_levelup_record(i+3,45+i*20) for i in range(5)]
    if case=='duplicate':
        values[-1]['character_name']['evidence']['pixel_sha256']=values[0]['character_name']['evidence']['pixel_sha256']
        values[-1]['frame_sha256']=values[0]['frame_sha256']
    if case in ('gap','total_span','out_of_order'):
        seconds=[45,65,85,105,226] if case=='gap' else [45,135,225,315,405] if case=='total_span' else [45,65,85,105,100]
        values=[percentage_levelup_record(i+3,s) for i,s in enumerate(seconds)]
    if case=='missing_name':
        for value in values:value['character_name']=dict(evidence=dict(status='unreadable_or_conflicting'))
    if case=='jump':
        for value in values:value['neural_level'].update(level=59,text='59')
    if case=='mixed_agreement':values=values[:1]+[percentage_levelup_record(4,65,58)]
    for i,value in enumerate(values):
        if case=='session' and i==4:
            store.end_session('alpha',at=AT+timedelta(seconds=110));store.start_session('alpha',at=AT+timedelta(seconds=115))
        result=guard_level(store,cid,value)
        assert not result['current']
    floor=store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]
    assert floor==(None if case=='bootstrap' else 57)


@pytest.mark.parametrize('restart',[False,True])
@pytest.mark.parametrize('exp',[1437,1441])
@pytest.mark.parametrize('interval',[15,40])
def test_stationary_low_percentage_levelup_with_one_neural_reader_reaches_outer_confirmation(auto,restart,exp,interval):
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[56,56],bps=[9900,9985])
    for i in (3,4,5):
        if i==4 and restart:policy=AutonomousCharacters(store)
        value=stationary_levelup_record(i,exp,interval)
        result=policy.append('first',value,f'noop{i}',config(f'noop{i}'))
        if i==3:
            assert result['record']['level_hold']['reason']=='level_confirmation_pending'
        else:
            assert result['record']['current'] and 'level_hold' not in result['record']
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==57
    now=AT+timedelta(seconds=5*interval+1)
    projected=Diagnostics(store).snapshot('alpha',now=now)
    assert projected['percentage_progress']['latest_percentage']['percentage']=='0.14'
    assert projected['percentage_progress']['current_segment']['difference_bp']==0
    card=Diagnostics(store).directory({},now=now)['streams'][0]['player']
    assert card['display_level']['value']==57 and card['reading']['exp']==str(exp)
    assert card['reading']['timestamp']==(AT+timedelta(seconds=5*interval)).isoformat()
    assert store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==0


@pytest.mark.parametrize('changes',[
    dict(neural_level=dict(level=57,text='57',status='numeric_candidate',score=.89,preprocessing='neutral4')),
    dict(neural_level=dict(level=57,text='57',status='numeric_candidate',score=.99,preprocessing='rgb4')),
    dict(neural_level=dict(level=57,text='57',status='numeric_candidate',score=.99,preprocessing='neutral4',source_complete=False)),
    dict(visual_level=56,visual_status='available'),
    dict(candidate=[15000,.14],neural=dict(text='15,000[0.14%]')),
    dict(candidate=None,neural=dict(text='[0.14%]'),status='diagnostic_percentage_only'),
    dict(current=False),
    dict(localization=dict(count=2)),
])
def test_stationary_neural_levelup_still_rejects_unsafe_or_inconsistent_evidence(auto,changes):
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[56,56],bps=[9900,9985])
    for i in (3,4):
        value=stationary_levelup_record(i);value.update(deepcopy(changes))
        policy.append('first',value,f'noop{i}',config(f'noop{i}'))
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==56


@pytest.mark.parametrize('duplicate,delay',[(True,15),(False,601)])
def test_stationary_neural_levelup_requires_distinct_frames_within_confirmation_window(auto,duplicate,delay):
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[56,56],bps=[9900,9985])
    before=stationary_levelup_record(3)
    policy.append('first',before,'noop3',config('noop3'))
    after=stationary_levelup_record(4)
    after['received_at']=after['attempted_at']=(AT+timedelta(seconds=45+delay)).isoformat()
    after['character_name']['evidence']['received_at']=after['received_at']
    if duplicate:
        after['frame_sha256']=before['frame_sha256']
        after['character_name']['evidence']['pixel_sha256']=before['character_name']['evidence']['pixel_sha256']
    result=policy.append('first',after,'noop4',config('noop4'))
    assert result['record']['level_hold']['reason']=='level_confirmation_pending'
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==56


def missing_hud_record(index,at):
    value=record(index,at=at)
    value.update(current=False,status='unavailable',reasons=['missing_hud'],
        localization=dict(count=0,candidates=[]),local_age_seconds=13,
        candidate=None,visual_level=None,visual_status='not_run',neural=None,neural_status='not_run',
        character_name=dict(reading_hold_recommended=False,evidence=dict(status='ineligible_frame')))
    return value


@pytest.mark.parametrize('delay,duplicate,restart,confirmed',[
    (103,False,False,True),(103,False,True,True),(120,False,False,True),
    (121,False,False,True),(600,False,False,True),(601,False,False,False),(103,True,False,False),
])
def test_normal_levelup_survives_unreadable_huds_without_extending_confirmation(auto,delay,duplicate,restart,confirmed):
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[64,64],bps=[9900,9980])
    def new_level(index,seconds):
        value=record(index,level=65,at=AT+timedelta(seconds=seconds))
        value.update(status='malformed_or_unavailable',candidate=None,neural=dict(text='1.08710.07%]'),
            visual_level=None,visual_status='unavailable',
            neural_level=dict(level=65,text='65',status='numeric_candidate',score=.95321,preprocessing='neutral4'))
        return value
    first=new_level(3,45)
    policy.append('first',first,'unused3',config('unused3'))
    pending=store.db.execute('SELECT pending_json FROM character_level_guard').fetchone()[0]
    for index,seconds in ((4,85),(5,125)):
        gap=policy.append('first',missing_hud_record(index,AT+timedelta(seconds=seconds)),
                          f'unused{index}',config(f'unused{index}'))
        assert not gap['record']['current'] and gap['record']['candidate'] is None
        assert store.db.execute('SELECT level,pending_json FROM character_level_guard').fetchone()[:]==(64,pending)
    if restart:policy=AutonomousCharacters(store)
    after=new_level(6,45+delay)
    if duplicate:
        after['frame_sha256']=first['frame_sha256']
        after['character_name']['evidence']['pixel_sha256']=first['character_name']['evidence']['pixel_sha256']
    result=policy.append('first',after,'unused6',config('unused6'))
    assert result['record']['current'] is confirmed
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==(65 if confirmed else 64)
    if confirmed:
        proof=json.loads(store.db.execute('SELECT proof_json FROM character_level_guard').fetchone()[0])
        assert proof['support']['received_at']==first['received_at']
        snapshot=Diagnostics(store).snapshot('alpha',now=AT+timedelta(seconds=45+delay+1),run_id='first')
        assert all('validated_level_floor' not in row for row in snapshot['observations'][:-1])
        assert snapshot['observations'][-1]['experimental_level']['reason']=='persistent_level_guard'
        card=Diagnostics(store).directory({},now=AT+timedelta(seconds=45+delay+1))['streams'][0]['player']
        assert card['display_level']['value']==65
        assert card['reading']['exp']=='1087' and card['reading']['percentage']=='0.07'
    else:assert result['record']['level_hold']['reason']=='level_confirmation_pending'
    assert store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==0


@pytest.mark.parametrize('changes',[
    dict(status='capture_failed',reasons=['frame_timeout'],localization=None),
    dict(status='stale_local_frame',reasons=['local_receipt_age_exceeded'],local_age_seconds=16),
    dict(reasons=['localization_failed']),
    dict(reasons=['multiple_huds'],localization=dict(count=2)),
    dict(local_age_seconds=16),dict(local_age_seconds=None),dict(frame_sha256=None),
    dict(received_at=None),
    dict(received_at=(AT+timedelta(seconds=45)).isoformat()),
    dict(received_at=(AT+timedelta(seconds=646)).isoformat()),
    dict(neural=dict(text='1,437[0.14%]')),dict(candidate=[1437,.14]),
    dict(visual_level=57),dict(neural_level=dict(level=57)),
    dict(character_name=dict(reading_hold_recommended=False,evidence=dict(status='ineligible_frame',name='Beta'))),
    dict(character_name=dict(reading_hold_recommended=True,hold_reasons=['pending_switch'])),
])
def test_only_fresh_unreadable_huds_can_preserve_a_normal_levelup_vote(auto,changes):
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[56,56],bps=[9900,9985])
    policy.append('first',stationary_levelup_record(3),'unused3',config('unused3'))
    gap=missing_hud_record(4,AT+timedelta(seconds=60))
    gap.update(deepcopy(changes))
    policy.append('first',gap,'unused4',config('unused4'))
    assert store.db.execute('SELECT pending_json FROM character_level_guard').fetchone()[0] is None
    result=policy.append('first',stationary_levelup_record(5),'unused5',config('unused5'))
    assert result['record']['level_hold']['reason']=='level_confirmation_pending'
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==56


@pytest.mark.parametrize('seed_floor',[False,True])
def test_unreadable_hud_does_not_bridge_initial_or_multiple_level_confirmation(auto,seed_floor):
    _,store,policy=auto
    if seed_floor:sequence(auto,['Alpha','Alpha'],levels=[67,67])
    start=3 if seed_floor else 1
    policy.append('first',record(start,level=80),f'unused{start}',config(f'unused{start}'))
    gap=missing_hud_record(start+1,AT+timedelta(seconds=(start+1)*15))
    policy.append('first',gap,'gap',config('gap'))
    assert store.db.execute('SELECT pending_json FROM character_level_guard').fetchone()[0] is None
    result=policy.append('first',record(start+2,level=80),'next',config('next'))
    assert result['record']['level_hold']['reason']=='level_confirmation_pending'
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==(67 if seed_floor else None)


@pytest.mark.parametrize('changes',[
    dict(score=.89),dict(preprocessing='rgb4'),dict(source_complete=False),
    dict(text='66'),dict(status='failed'),
])
def test_persisted_level_context_never_upgrades_weak_invalid_or_clipped_current_evidence(auto,changes):
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[65,65])
    Diagnostics(store).append('first',dict(type='summary',trusted=False,attempts=2,interrupted=False))
    Diagnostics(store).begin('new','alpha',config('new'))
    value=record(1,level=65,at=AT+timedelta(seconds=60))
    value.update(visual_level=None,visual_status='unavailable',candidate=None,neural=dict(text='1.08710.07%]'),
        neural_level=dict(level=65,text='65',status='numeric_candidate',score=.99,preprocessing='neutral4'))
    value['neural_level'].update(changes)
    policy.append('new',value,'unused',config('unused'))
    row=Diagnostics(store).snapshot('alpha',now=AT+timedelta(seconds=61))['observations'][-1]
    assert row['experimental_level']['value'] is None
    assert row['experimental_level']['reason']!='persistent_level_guard'


def test_untrusted_payload_cannot_supply_its_own_validated_level_context(auto):
    from exp_tracker.shadow_view import observation
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[56,56],bps=[9900,9985])
    value=stationary_levelup_record(3)
    value['validated_level_floor']=57
    assert 'validated_level_floor' not in observation(value)
    result=policy.append('first',value,'unused',config('unused'))
    assert result['record']['level_hold']['reason']=='level_confirmation_pending'
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==56
    row=Diagnostics(store).snapshot('alpha',now=AT+timedelta(seconds=46))['observations'][-1]
    assert row['validated_level_floor']==56 and row['experimental_level']['value'] is None


def test_wider_crop_retry_does_not_count_as_a_second_levelup_frame(auto,monkeypatch):
    import importlib
    from pathlib import Path
    from types import SimpleNamespace
    from PIL import Image
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'tools'))
    protocol=importlib.import_module('shadow_neural')
    worker=importlib.import_module('shadow_rapidocr')
    crop=Image.new('RGB',(37,24),(80,80,80))
    crop.paste(Image.new('RGB',(23,13),(240,120,20)),(2,5))
    outputs=iter([('1,437[0.14%]',.99),('57',.84),('57',.99)])
    def engine(*args,**kwargs):
        text,score=next(outputs)
        return SimpleNamespace(txts=[text],scores=[score],boxes=None,elapse=.01,elapse_list=None)
    output=worker.recognize_fields(engine,crop,protocol.png_bytes(crop,protocol.LEVEL_SIZE),experimental=True)
    neural=protocol.checked_level(output['neural_level'])
    assert neural['score']==.99 and neural['tile_attempt']['score']==.84
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[56,56],bps=[9900,9985])
    first=stationary_levelup_record(3)
    for i in (3,4,5):
        value=stationary_levelup_record(i)
        value['neural_level']=neural
        if i==4:
            value['frame_sha256']=first['frame_sha256']
            value['character_name']['evidence']['pixel_sha256']=first['character_name']['evidence']['pixel_sha256']
        result=policy.append('first',value,f'noop{i}',config(f'noop{i}'))
        if i<5:
            assert result['record']['level_hold']['reason']=='level_confirmation_pending'
            assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==56
    assert result['record']['current']
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==57
    assert store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==0


def test_saved_level_policy_cannot_bypass_a_newer_floor(auto):
    _,store,_=auto
    rows=sequence(auto,['Alpha']*4,levels=[67,67,68,68])
    old=deepcopy(rows[1]['record'])
    Diagnostics(store).append('first',dict(type='summary',trusted=False,attempts=4,interrupted=False))
    Diagnostics(store).begin('replay','alpha',config('replay'))
    old.update(index=1,attempted_at=(AT+timedelta(minutes=2)).isoformat(),received_at=(AT+timedelta(minutes=2)).isoformat())
    Diagnostics(store).append('replay',old)
    saved=json.loads(store.db.execute("SELECT payload_json FROM diagnostic_attempts WHERE run_id='replay'").fetchone()[0])
    assert saved['level_hold']['reason']=='level_regression'
    assert Diagnostics(store).append('replay',saved) is False


@pytest.mark.parametrize('explicit_boundary',[False,True])
def test_verified_overnight_progress_keeps_identity_without_offline_gain(auto,explicit_boundary):
    _,store,policy=auto
    initial=sequence(auto,['Alpha','Alpha'],levels=[67,67],bps=[5000,5010])
    cid,sid=initial[-1]['character_id'],initial[-1]['session_id']
    Diagnostics(store).append('first',dict(type='summary',trusted=False,attempts=2,interrupted=False))
    morning=AT+timedelta(hours=8)
    if explicit_boundary:
        store.end_session('alpha',at=AT+timedelta(minutes=2))
        store.start_session('alpha',at=morning)
    Diagnostics(store).begin('morning','alpha',config('morning'))
    rows=[]
    for i in (1,2,3):
        rows.append(policy.append('morning',record(i,level=70,bp=1000+i*10,at=morning+timedelta(seconds=i*15)),
                                  f'no{i}',config(f'no{i}')))
    assert not any(r['switched'] for r in rows)
    assert all(r['character_id']==cid for r in rows)
    assert (rows[-1]['session_id']!=sid)==explicit_boundary
    assert rows[0]['record']['level_hold']['reason']=='level_confirmation_pending'
    assert rows[1]['record']['current'] and rows[2]['record']['current']
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==70
    card=Diagnostics(store).directory({},now=morning+timedelta(seconds=50))['streams'][0]['player']
    assert card['display_level']['value']==70
    assert int(card['reading']['exp'])==record(3,level=70,bp=1030)['candidate'][0]
    assert card['responsive_pace']['start']==rows[1]['record']['received_at']
    assert card['responsive_pace']['end']==rows[2]['record']['received_at']
    assert {r['level'] for r in card['responsive_pace']['intervals']}=={70}
    assert card['responsive_pace']['total_gain']['approximate']==record(3,level=70,bp=1030)['candidate'][0]-record(2,level=70,bp=1020)['candidate'][0]


def test_zero_exp_does_not_arithmetically_validate_a_single_level_reader(auto):
    _,store,policy=auto
    rows=sequence(auto,['Alpha','Alpha'],levels=[67,67],bps=[0,0])
    assert all(r['record']['level_hold']['reason']=='level_unvalidated' for r in rows)
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0] is None
    for i in (3,4):
        value=record(i,level=67,bp=0)
        value['neural_level']=dict(level=67,text='67',status='numeric_candidate',score=.99,preprocessing='neutral4')
        result=policy.append('first',value,f'no{i}',config(f'no{i}'))
    assert result['record']['current']
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==67


def named_low_exp_record(index,level,exp,bp,seconds):
    value=record(index,level=level,at=AT+timedelta(seconds=seconds))
    value.update(candidate=[exp,bp/100],neural=dict(text=f'{exp}[{bp/100:.2f}%]'),
        visual_level=None,visual_status='unavailable',
        neural_level=dict(level=level,text=str(level),status='numeric_candidate',score=.95,preprocessing='neutral4'))
    return value


@pytest.mark.parametrize('level,exp,bp',[(27,0,0),(51,14,0),(51,27,0),(57,1437,14),(65,1087,7),
    (51,requirement(51)['to_next']//10000,1),(51,requirement(51)['to_next']*2//10000,2),
    (51,requirement(51)['to_next']*13//10000,13),(89,0,0)])
def test_named_next_level_confirms_tiny_or_zero_exp_across_long_unreadable_gap(auto,level,exp,bp):
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[level-1]*2,bps=[9900,9980])
    first=named_low_exp_record(3,level,exp,bp,45)
    result=policy.append('first',first,'unused3',config('unused3'))
    assert result['record']['level_hold']['reason']=='level_confirmation_pending'
    original_pending=store.db.execute('SELECT pending_json FROM character_level_guard').fetchone()[0]
    missing=missing_hud_record(4,AT+timedelta(seconds=100))
    weak=named_low_exp_record(5,level,exp,bp,170)
    weak['neural_level'].update(status='nonnumeric',level=None,text=f'{level//10} {level%10}',score=.8)
    weak.update(candidate=None,neural=dict(text='unreadable'),status='malformed_or_unavailable')
    for gap in (missing,weak):
        result=policy.append('first',gap,f"unused{gap['index']}",config())
        assert not result['record']['current']
        assert store.db.execute('SELECT pending_json FROM character_level_guard').fetchone()[0]==original_pending
    policy=AutonomousCharacters(store)
    second=named_low_exp_record(6,level,exp,bp,300)
    result=policy.append('first',second,'unused6',config())
    assert result['record']['current'] and 'level_hold' not in result['record']
    proof=json.loads(store.db.execute('SELECT proof_json FROM character_level_guard').fetchone()[0])
    assert proof['level']==level and proof['support']['received_at']==first['received_at']
    now=AT+timedelta(seconds=301)
    card=Diagnostics(store).directory({},now=now)['streams'][0]['player']
    assert card['display_level']['value']==level
    assert card['reading']['exp']==str(exp) and card['reading']['percentage']==f'{bp/100:.2f}'
    assert card['reading']['timestamp']==second['received_at']
    assert not store.db.execute('SELECT 1 FROM observations').fetchone()


@pytest.mark.parametrize('changes',[
    dict(visual_level=50,visual_status='available'),
    dict(neural_level=dict(level=51,text='51',status='numeric_candidate',score=.89,preprocessing='neutral4')),
    dict(neural_level=dict(level=51,text='51',status='numeric_candidate',score=.99,preprocessing='rgb4')),
    dict(neural_level=dict(level=51,text='51',status='numeric_candidate',score=.99,preprocessing='neutral4',source_complete=False)),
    dict(candidate=None,neural=dict(text='[0.00%]'),status='diagnostic_percentage_only'),
    dict(candidate=[1000,0.0],neural=dict(text='1000[0.00%]')),
    dict(current=False),dict(localization=dict(count=2)),dict(local_age_seconds=16),
    dict(character_name=dict(evidence=dict(status='unreadable_or_conflicting'))),
])
def test_zero_percentage_never_confirms_without_named_strong_compatible_full_evidence(auto,changes):
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[50,50])
    for i in (3,4):
        value=named_low_exp_record(i,51,27,0,i*15)
        value.update(deepcopy(changes))
        policy.append('first',value,f'unused{i}',config())
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==50


@pytest.mark.parametrize('floor',[None,49])
def test_zero_percentage_named_votes_do_not_relax_initialization_or_large_jumps(auto,floor):
    _,store,policy=auto
    if floor:sequence(auto,['Alpha','Alpha'],levels=[floor,floor])
    for i in ((3,4) if floor else (1,2)):
        policy.append('first',named_low_exp_record(i,51,27,0,i*15),f'unused{i}',config())
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==floor


@pytest.mark.parametrize('kind',['level_conflict','name_conflict','session_boundary','expired'])
def test_named_vote_cannot_survive_conflicts_session_changes_or_expiry(auto,kind):
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[50,50])
    policy.append('first',named_low_exp_record(3,51,27,0,45),'unused3',config())
    run='first';index=4 if kind=='expired' else 5
    if kind=='session_boundary':
        store.end_session('alpha',at=AT+timedelta(seconds=60))
        store.start_session('alpha',at=AT+timedelta(seconds=90))
        Diagnostics(store).begin('new','alpha',config('new'))
        run='new';index=1
    elif kind!='expired':
        gap=record(4,level=50,at=AT+timedelta(seconds=100)) if kind=='level_conflict' else record(4,name='Beta',at=AT+timedelta(seconds=100))
        policy.append(run,gap,'unused4',config())
    after=named_low_exp_record(index,51,27,0,646 if kind=='expired' else 300)
    result=policy.append(run,after,'unused5',config())
    assert result['record']['level_hold']['reason']=='level_confirmation_pending'
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==50


@pytest.mark.parametrize('changes',[
    dict(local_age_seconds=16),dict(current=False,status='stale_local_frame'),
    dict(localization=dict(count=2)),dict(frame_sha256=None),
    dict(neural_level=dict(level=51,text='51',status='numeric_candidate',score=.8,preprocessing='neutral4',source_complete=False)),
    dict(candidate=[1000,0.0],neural=dict(text='1000[0.00%]')),
])
def test_unsafe_intermediate_frames_clear_named_vote(auto,changes):
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[50,50])
    policy.append('first',named_low_exp_record(3,51,27,0,45),'unused3',config())
    gap=named_low_exp_record(4,51,27,0,100)
    gap['neural_level']['score']=.8
    gap.update(deepcopy(changes))
    policy.append('first',gap,'unused4',config())
    assert store.db.execute('SELECT pending_json FROM character_level_guard').fetchone()[0] is None
    result=policy.append('first',named_low_exp_record(5,51,27,0,300),'unused5',config())
    assert result['record']['level_hold']['reason']=='level_confirmation_pending'
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==50


def test_percentage_only_hud_needs_both_level_readers_before_a_floor(auto):
    """No absolute EXP means no arithmetic check, so neural alone never validates a level."""
    _,store,policy=auto
    def compact(index,visual):
        value=record(index,level=71)
        value.update(status='diagnostic_percentage_only',candidate=None,neural=dict(text='[80.00%]'),
            percentage_only_candidate=dict(kind='percentage_only',percentage='80.00',percentage_bp=8000,trusted=False),
            visual_level=visual,visual_status='available' if visual else 'unavailable',
            neural_level=dict(level=71,text='71',status='numeric_candidate',score=.99,preprocessing='neutral4'))
        return policy.append('first',value,f'no{index}',config(f'no{index}'))['record']
    rows=[compact(1,None),compact(2,None),compact(3,71),compact(4,71)]
    assert [r.get('level_hold',{}).get('reason') for r in rows]==['level_unvalidated']*2+['level_confirmation_pending',None]
    assert rows[3]['current']
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==71


def test_commit_failure_rolls_back_switch_and_can_retry(auto):
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha','Beta'])
    store.db.execute('CREATE TABLE fail_commit (cid INTEGER REFERENCES characters(id) DEFERRABLE INITIALLY DEFERRED)')
    def fail_at_commit(*args):store.db.execute('INSERT INTO fail_commit VALUES(-1)')
    with pytest.raises(sqlite3.IntegrityError,match='FOREIGN KEY'):
        policy.append('first',record(4,'Beta'),'failed',config('failed'),write=fail_at_commit)
    assert not store.db.in_transaction
    assert store.db.execute('SELECT COUNT(*) FROM characters').fetchone()[0]==1
    assert store.db.execute('SELECT COUNT(*) FROM automatic_character_events').fetchone()[0]==0
    assert store.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==1
    assert store.db.execute('SELECT summary_json FROM diagnostic_runs').fetchone()[0] is None
    assert policy.append('first',record(4,'Beta'),'retry',config('retry'))['switched']


def test_inflight_rename_stops_stale_identity_reference_instead_of_recreating_old_name(auto):
    _,store,policy=auto
    rows=sequence(auto,['Alpha','Alpha'])
    store.rename_character('alpha',rows[-1]['character_id'],'Corrected',reason='Synthetic audit')
    value=record(3)
    value['character_name']['suggestion']=dict(reference_name='Alpha')
    with pytest.raises(ValueError,match='reference changed'):
        policy.append('first',value,'unused',config('unused'))
    assert store.db.execute('SELECT COUNT(*) FROM characters').fetchone()[0]==1
    assert store.db.execute('SELECT label FROM characters').fetchone()[0]=='Corrected'
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==30


def test_cached_name_votes_cannot_clear_conflict_or_establish_switch(auto):
    _,store,policy=auto
    sequence(auto,['Alpha','Alpha','Beta'])
    for i in (4,5):
        value=record(i,'Beta')
        value['character_name']['evidence']['provenance']['search']='cached_region'
        result=policy.append('first',value,f'no{i}',config(f'no{i}'))
        assert not result['switched'] and 'identity_hold' in result['record']
    # A cached vote cannot pair with the first fresh full scan either.
    assert not policy.append('first',record(6,'Beta'),'no6',config('no6'))['switched']
    assert policy.append('first',record(7,'Beta'),'yes7',config('yes7'))['switched']


def test_offline_audited_floor_repair_recipe_is_atomic_and_preserves_history(auto):
    from exp_tracker.invalidations import Invalidations
    path,store,policy=auto
    sequence(auto,['Alpha']*4,levels=[67,67,70,70])
    cid=store._channel('alpha')['selected_character_id']
    old=dict(store.db.execute('SELECT * FROM character_level_guard').fetchone())
    archive=json.dumps(old,sort_keys=True);digest=hashlib.sha256(archive.encode()).hexdigest()
    when=AT+timedelta(minutes=2)
    def repair(*,fail=False):
        with store._transaction():
            assert dict(store.db.execute('SELECT * FROM character_level_guard').fetchone())==old
            service=Invalidations(store)
            spec=dict(action='invalidate',kind='diagnostic',identity='first:4',timestamp=(AT+timedelta(seconds=60)).isoformat())
            preview=service.preview('alpha',cid,spec)
            batch=service.commit('alpha',cid,'repair-invalidation',spec,preview['fingerprint'],'Confirmed wrong level evidence')
            Diagnostics(store)._append('first',dict(type='summary',trusted=False,attempts=4,interrupted=False))
            store.end_session('alpha',at=when)
            session=store.start_session('alpha',at=when,expected_character_id=cid)
            # Deliberate operator-only replacement on an offline copy; never drop the monotone trigger.
            store.db.execute('DELETE FROM character_level_guard WHERE character_id=?',(cid,))
            baseline=store.correct_manual('alpha','repair-baseline',cid,level=67,current_exp=1000,effective_at=when,
                                         session_id=session,reason=f'Floor repair; old guard SHA256={digest}; invalidation={batch["id"]}')
            proof=dict(level=67,received_at=when.isoformat(),basis='manual_admin_repair',event_id=baseline['event_id'],
                       superseded_level=old['level'],superseded_guard_sha256=digest,invalidation_batch=batch['id'])
            store.db.execute('INSERT INTO character_level_guard VALUES(?,?,?,?,?)',(cid,67,json.dumps(proof),None,when.isoformat()))
            if fail:raise OSError('Synthetic repair failure')
    with pytest.raises(OSError):repair(fail=True)
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==70
    assert store.db.execute('SELECT COUNT(*) FROM manual_corrections').fetchone()[0]==0
    assert store.db.execute('SELECT COUNT(*) FROM reading_commits').fetchone()[0]==0
    repair()
    assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]==4
    assert store.db.execute('SELECT COUNT(*) FROM characters').fetchone()[0]==1
    assert store.db.execute('SELECT COUNT(*) FROM character_level_guard').fetchone()[0]==1
    Diagnostics(store).begin('repaired','alpha',config('repaired'))
    result=policy.append('repaired',record(1,level=67,at=when+timedelta(seconds=15)),'unused',config('unused'))
    assert result['record']['current']
    with Store(path,read_only=True) as reopened:
        saved=reopened.db.execute('SELECT * FROM character_level_guard').fetchone()
        assert saved['level']==67 and json.loads(saved['proof_json'])['superseded_guard_sha256']==digest


def test_large_level_jump_needs_repeated_selected_name_even_after_restart(auto):
    path,store,_=auto
    sequence(auto,['Alpha','Alpha'],levels=[67,67])
    Diagnostics(store).append('first',dict(type='summary',trusted=False,attempts=2,interrupted=False))
    with Store(path) as cold:
        Diagnostics(cold).begin('returned','alpha',config('returned'))
        policy=AutonomousCharacters(cold)
        for i,name in enumerate((None,None,'Alpha','Alpha'),1):
            value=record(i,name,level=70,bp=1000+i*10,at=AT+timedelta(hours=8,seconds=i*15))
            result=policy.append('returned',value,f'no{i}',config(f'no{i}'))
            if i<4:
                assert not result['record']['current']
                assert cold.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==67
        assert result['record']['current']
        assert cold.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==70


def test_brief_coordinator_restart_keeps_session_and_normal_unreadable_name_levelup(auto):
    path,store,_=auto
    before=sequence(auto,['Alpha','Alpha'],levels=[67,67],bps=[9950,9970])
    Diagnostics(store).append('first',dict(type='summary',trusted=False,attempts=2,interrupted=True))
    with Store(path) as cold:
        session=cold.start_session('alpha',at=AT+timedelta(seconds=35))
        assert session==before[-1]['session_id']
        header=config('restart');header['start_reason']='process_start'
        Diagnostics(cold).begin('restart','alpha',header)
        policy=AutonomousCharacters(cold)
        for i in (1,2,3):
            value=record(i,None,level=68,bp=i*10,at=AT+timedelta(seconds=30+i*15))
            result=policy.append('restart',value,f'no{i}',config(f'no{i}'))
        assert result['record']['current'] and result['session_id']==session
        assert cold.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==1
        assert cold.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==68


def with_job(value, text):
    value['character_name']['evidence']['job'] = dict(status='candidate', job=text, tier=None, text=text, score=.99, box=[1, 2, 50, 20])
    return value


@pytest.mark.parametrize('jobs,level,expected', [
    ([None, 'Cleric', None, 'Cleric'], 30, 'Cleric'),        # Two agreeing reads of different frames.
    ([None, 'Cleric', None, None], 30, None),                # One read is not enough.
    ([None, 'Cleric', None, 'Bishop'], 30, None),            # Not a job: never stored.
    ([None, 'Cleric', None, 'Priest'], 30, None),
    ([None, 'Hunter', None, 'Cleric'], 30, None),            # Disagreeing reads.
    ([None, 'Cleric', None, 'Cleric'], 20, None),            # A second job below level 30 is a misread.
    ([None, 'Magician', None, 'Magician'], 20, 'Magician'),
])
def test_two_agreeing_job_reads_record_the_job(auto, jobs, level, expected):
    _, store, policy = auto; run = 'first'
    for i, job in enumerate(jobs, 1):
        value = record(i, level=level, bp=4000 + i * 10, at=AT + timedelta(seconds=i * 15))
        if job: with_job(value, job)
        run = policy.append(run, value, f'next{i}', config(f'next{i}'))['run_id']
    cid = store._channel('alpha')['selected_character_id']
    assert (store.character_job(cid) or {}).get('job') == expected


def test_job_only_moves_up_a_tier_and_the_operator_can_set_it(auto):
    _, store, policy = auto; run = 'first'; cid = store._channel('alpha')['selected_character_id']
    def frames(start, jobs):
        nonlocal run
        for i, job in enumerate(jobs, start):
            value = record(i, level=35, bp=4000 + i * 10, at=AT + timedelta(seconds=i * 15))
            if job: with_job(value, job)
            run = policy.append(run, value, f'next{i}', config(f'next{i}'))['run_id']
    frames(1, [None, 'Magician', None, 'Magician']); assert store.character_job(cid)['job'] == 'Magician'
    frames(5, ['Cleric', 'Cleric']); assert store.character_job(cid)['job'] == 'Cleric'
    frames(7, ['Beginner', 'Beginner']); assert store.character_job(cid)['job'] == 'Cleric'
    store.set_character_job(cid, 'Cleric', source='manual_admin')
    assert store.character_job(cid)['source'] == 'manual_admin'
    store.set_character_job(cid, None, source='manual_admin'); assert store.character_job(cid) is None
    with pytest.raises(ValueError):store.set_character_job(cid, 'Bishop', source='manual_admin')


def test_a_job_read_on_a_frame_named_for_another_character_is_not_counted(auto):
    _, store, policy = auto; run = 'first'
    for i in (1, 2, 3, 4):
        value = with_job(record(i, 'Beta' if i == 4 else 'Alpha', level=30, bp=4000 + i * 10, at=AT + timedelta(seconds=i * 15)), 'Hunter')
        if i in (1, 3): value['character_name']['evidence'].pop('job')
        run = policy.append(run, value, f'next{i}', config(f'next{i}'))['run_id']
    assert store.character_job(store._channel('alpha')['selected_character_id']) is None


def test_a_failing_job_record_never_blocks_the_capture(auto, monkeypatch, capsys):
    import exp_tracker.character_automation as automation
    _, store, policy = auto; run = 'first'
    monkeypatch.setattr(automation, 'confirm_job', lambda *a: (_ for _ in ()).throw(RuntimeError('broken')))
    for i in (1, 2):
        run = policy.append(run, with_job(record(i, level=30, at=AT + timedelta(seconds=i * 15)), 'Cleric'), f'next{i}', config(f'next{i}'))['run_id']
    assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0] == 2
    assert 'job not recorded' in capsys.readouterr().err
