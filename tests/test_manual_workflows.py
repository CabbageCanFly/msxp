"""Revised operator contract and audited historical presentation, using synthetic SQLite only."""
from datetime import datetime,timedelta,timezone
import json
import sqlite3

import pytest

from exp_tracker.diagnostics import Diagnostics
from exp_tracker.exp_requirements import requirement
from exp_tracker.manual_admin import main,timestamp
from exp_tracker.product import player,history
from exp_tracker.schema import STATEMENTS,MIGRATION_2,MIGRATION_3,MIGRATION_4,MIGRATION_5,VERSION
from exp_tracker.server import create_server
from exp_tracker.store import Store
from tests.test_product import tracking,NOW
from tests.test_tracked_exp_totals import save
from tests.test_server import request
from tests.test_exp_level_product import attempt,T43
from tests.test_store import profile,reading
from tests.test_publisher import clock


@pytest.fixture(autouse=True)
def preview_temp(tmp_path,monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile,'tempdir',str(tmp_path))


def at(seconds):return NOW+timedelta(seconds=seconds)


def edit(store,seconds=25,**changes):
    args=dict(level=64,percentage_bp=5000,effective_at=at(seconds))
    args.update(changes)
    cid=args.pop('character_id',store.state('alpha')['selected_character_id'])
    return store.correct_manual('alpha',args.pop('event_id',f'edit-{seconds}'),cid,**args)


def get(d,seconds=60,session=None):
    return player(d.snapshot('alpha',now=at(seconds),session_id=session),now=at(seconds))


@pytest.mark.parametrize('fields',[
    {'level':None},{'level':0},{'level':201},{'level':True},{'current_exp':None,'percentage_bp':None},
    {'current_exp':-1},{'percentage_bp':10000},{'effective_at':None},
    {'effective_at':at(20),'now':True},{'effective_at':datetime(2026,1,1)},
    {'effective_at':datetime.now(timezone.utc)+timedelta(days=1)},
])
def test_required_backend_contract(tracking,fields):
    _,store,_=tracking
    with pytest.raises(ValueError):edit(store,**fields)
    assert store.manual_history('alpha')==[]


@pytest.mark.parametrize('stamp',['2026-01-01','2026-01-01T12:30Z','2026-01-01T12:30:00',
    '2026-02-30T12:30:00Z','2026-01-01T24:00:00Z'])
def test_timestamp_must_include_seconds_and_timezone(stamp):
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):timestamp(stamp)


def test_now_is_explicit_and_retries_are_idempotent(tracking):
    _,store,d=tracking;cid=store.state('alpha')['selected_character_id']
    event=store.correct_manual('alpha','now',cid,level=200,current_exp=0,now=True)
    assert store.correct_manual('alpha','now',cid,level=200,current_exp=0,now=True)['duplicate']
    assert event['effective_at']==event['recorded_at']
    with pytest.raises(ValueError):store.correct_manual('alpha','now',cid,level=199,current_exp=0,now=True)


@pytest.mark.parametrize('level',[64,95,150,200])
def test_derived_values_and_arithmetic_provenance(tracking,level):
    _,store,d=tracking
    event=edit(store,level=level,current_exp=1000,percentage_bp=None)
    value=get(d)['reading']
    assert value['exp']=='1000' and event['percentage_bp'] is None
    if requirement(level)['to_next'] is not None:
        assert value['percentage'] and value['estimated_percentage']['source']=='manual_exp_and_community_requirement'
    else:
        assert value['percentage'] is None and value['estimated_percentage'] is None
    newer=edit(store,30,level=level,current_exp=None,percentage_bp=5000)
    value=get(d)['reading']
    assert value['exp'] is None and newer['current_exp'] is None
    assert bool(value['estimated_exp'])==(requirement(level)['to_next'] is not None)
    both=edit(store,35,level=level,current_exp=1,percentage_bp=5000)
    value=get(d)['reading']
    assert (value['exp'],value['percentage'])==('1','50.00')
    assert value['exp_validity']['supplied_values_preserved']
    assert value['exp_validity']['status']==('invalid' if requirement(level)['to_next'] else 'indeterminate')


def test_legacy_partial_events_remain_readable_without_becoming_new_api_allowances(tmp_path):
    path=tmp_path/'legacy.sqlite3'
    with sqlite3.connect(path) as db:
        for sql in (*STATEMENTS,*MIGRATION_2,*MIGRATION_3,*MIGRATION_4,*MIGRATION_5):db.execute(sql)
        db.execute('PRAGMA user_version=5')
        db.execute("INSERT INTO streamers(id,login,selected_character_id) VALUES(1,'alpha',1)")
        db.execute("INSERT INTO characters VALUES(1,1,'Legacy')")
        db.execute('INSERT INTO tracking_state(character_id) VALUES(1)')
        db.execute("INSERT INTO manual_corrections(event_id,streamer_id,character_id,effective_at,recorded_at,action,level) VALUES('legacy',1,1,?,?,'set',42)",
                   (at(0).isoformat(),at(0).isoformat()))
    with Store(path,read_only=True) as store:
        assert store.manual_history('alpha')[0]['level']==42
        assert get(Diagnostics(store))['display_level']['value']==42
    with Store(path) as store:
        assert store.schema_version==VERSION
        assert get(Diagnostics(store))['reading']['exp'] is None
        assert get(Diagnostics(store))['display_level']['value']==42
        with pytest.raises(ValueError):store.correct_manual('alpha','partial',1,level=49,effective_at=at(10))
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall()


def test_point_correction_replaces_historical_presentation_and_never_current_newer_ocr(tracking):
    _,store,d=tracking
    for index,seconds,bp in ((1,0,3300),(2,20,3310),(3,40,3320),(4,60,3330)):
        save(d,'run',index,seconds,bp)
    raw=[tuple(r) for r in store.db.execute('SELECT id,payload_json FROM diagnostic_attempts')]
    before=get(d)['reading']
    event=edit(store,20,level=49,current_exp=1000,percentage_bp=1,kind='point',target_kind='diagnostic',target_event_id='run:2')
    snap=d.snapshot('alpha',now=at(60));points=history(snap)
    assert points[1]['reading']['level']['value']==49
    assert points[1]['reading']['exp']=='1000' and points[1]['reading']['provenance']['id']==event['id']
    assert points[1]['gain'] is None and points[2]['gain'] is None
    assert get(d)['reading']['event_id']==before['event_id'] and get(d)['reading']['exp']==before['exp']
    assert raw==[tuple(r) for r in store.db.execute('SELECT id,payload_json FROM diagnostic_attempts')]
    result=d.rolling_history('alpha',now=at(60))
    assert len(result['chart_intervals'])==1 and result['chart_intervals'][0]['start']==at(40).isoformat()
    for window in result['windows'].values():assert window['gain']==result['tracked_exp']


def test_correcting_latest_point_changes_page_level_and_numbers(tracking):
    _,store,d=tracking
    save(d,'run',1,0,3300);save(d,'run',2,20,3310)
    edit(store,20,level=49,current_exp=1000,kind='point',target_kind='diagnostic',target_event_id='run:2')
    value=get(d)
    assert value['display_level']['value']==49 and value['reading']['exp']=='1000'
    assert value['reading']['event_id']=='run:2' and value['reading']['evidence']=='manual_admin'


def test_baselines_support_unordered_history_and_reject_ambiguous_or_foreign_targets(tracking):
    _,store,d=tracking;cid=store.state('alpha')['selected_character_id']
    later=edit(store,50,level=65);earlier=edit(store,10,level=49)
    assert get(d)['display_level']['value']==65
    assert [e['id'] for e in store.manual_history('alpha')]==[earlier['id'],later['id']]
    store.end_session('alpha',at=at(80));store.start_session('alpha',at=at(80))
    with pytest.raises(ValueError,match='ambiguous session'):edit(store,80,level=66)
    explicit=edit(store,80,level=66,session_id=2)
    assert explicit['session_id']==2
    other=store.add_character('alpha','Other')
    with pytest.raises(ValueError,match='scope'):edit(store,11,character_id=other,session_id=1)
    store.add_channel('beta');foreign=store.add_character('beta','Foreign')
    with pytest.raises(ValueError,match='belong'):edit(store,15,character_id=foreign)


def test_historical_character_session_and_amendments_do_not_leak_into_live_scope(tracking):
    _,store,d=tracking;old=store.state('alpha')['selected_character_id'];sid=store.state('alpha')['session']['id']
    save(d,'run',1,0,3300);save(d,'run',2,20,3310)
    other=store.add_character('alpha','Other');store.select_character('alpha',other,at=at(70));store.start_session('alpha',at=at(70))
    event=edit(store,20,character_id=old,level=49,session_id=sid,kind='point',target_kind='diagnostic',target_event_id='run:2')
    assert get(d,100)['reading'] is None
    assert get(d,100,session=sid)['reading']['level']['value']==49
    amended=edit(store,20,character_id=old,level=48,session_id=sid,kind='point',target_kind='diagnostic',target_event_id='run:2',
                 event_id='fix-old',replaces_id=event['id'],reason='Wrong level')
    assert get(d,100,session=sid)['reading']['level']['value']==48
    store.retract_manual('alpha','undo-old',amended['id'],reason='Restore original OCR')
    assert get(d,100,session=sid)['reading']['evidence']=='strict_full'
    assert get(d,100)['reading'] is None


def test_amend_older_revision_with_newer_event_and_move_wrong_character_or_time(tracking):
    _,store,d=tracking;cid=store.state('alpha')['selected_character_id']
    first=edit(store,10,level=49);later=edit(store,50,level=65)
    amended=edit(store,15,level=48,replaces_id=first['id'],reason='Fix historical level and time')
    assert get(d)['display_level']['value']==65
    assert get(d,30)['display_level']['value']==48
    other=store.add_character('alpha','Other')
    moved=edit(store,15,character_id=other,level=47,event_id='move',replaces_id=amended['id'],reason='Wrong character')
    assert get(d,30)['reading'] is None
    assert get(d)['display_level']['value']==65
    old_history=store.manual_history('alpha',character_id=cid,active_only=True)
    assert [e['id'] for e in old_history]==[later['id']]
    audit=store.manual_history('alpha')
    assert next(e for e in audit if e['id']==first['id'])['superseded_by']==amended['id']
    assert next(e for e in audit if e['id']==amended['id'])['superseded_by']==moved['id']
    with pytest.raises(ValueError,match='inactive'):edit(store,16,replaces_id=first['id'],reason='Stale target')


def test_undo_restores_ocr_and_removes_boundary_with_checkpoint_invalidation(tracking):
    _,store,d=tracking
    for i in range(1,5):save(d,'run',i,(i-1)*20,3300+i*10)
    before=d.rolling_history('alpha',now=at(60));checkpoints={}
    event=edit(store,20,level=49,kind='point',target_kind='diagnostic',target_event_id='run:2')
    corrected=d.rolling_history('alpha',now=at(60),checkpoints=checkpoints)
    assert corrected['tracked_exp']!=before['tracked_exp']
    undone=store.retract_manual('alpha','undo',event['id'],reason='Operator typo')
    assert undone['replaces_id']==event['id'] and undone['operation']=='retract'
    assert store.retract_manual('alpha','undo',event['id'],reason='Operator typo')['duplicate']
    assert d.rolling_history('alpha',now=at(60),checkpoints=checkpoints)==before
    assert not store.manual_history('alpha',active_only=True)


def test_duplicate_and_timestamp_scoped_point_resolution(tracking):
    _,store,d=tracking;save(d,'run',1,20,3300)
    event=edit(store,20,kind='point')
    assert event['target_event_id']=='run:1'
    assert edit(store,20,kind='point')['duplicate']
    with pytest.raises(ValueError,match='already corrected'):edit(store,20,kind='point',event_id='different-id')
    with pytest.raises(ValueError,match='no reading'):edit(store,21,kind='point')
    with pytest.raises(ValueError,match='exact effective'):edit(store,22,kind='point',target_kind='diagnostic',target_event_id='run:1')


def test_trusted_observation_point_is_presented_without_mutating_trusted_evidence(tracking,profile):
    _,store,d=tracking;cid=store.state('alpha')['selected_character_id'];sid=store.state('alpha')['session']['id']
    row=store.ingest('alpha','trusted',at(10),reading(),profile=profile,session_id=sid)
    original=tuple(store.db.execute('SELECT * FROM observations').fetchone())
    event=edit(store,10,level=49,current_exp=1000,kind='point',target_kind='observation',target_event_id=row['id'])
    assert get(d)['display_level']['value']==49 and get(d)['reading']['exp']=='1000'
    assert history(d.snapshot('alpha',now=at(60)))[0]['reading']['provenance']['id']==event['id']
    assert tuple(store.db.execute('SELECT * FROM observations').fetchone())==original
    assert store.state('alpha')['last_trusted']['level']==row['level']


def test_manual_seed_permits_existing_corroborated_obscured_hud_level_up(tracking):
    _,store,d=tracking
    attempt(d,1,pct='98.62',current=False,status='capture_failed',received_at=None,neural=None,localization=dict(count=0))
    edit(store,0,level=42,current_exp=352000,percentage_bp=9862)
    for i,pct in enumerate(('99.40','99.92','0.18','0.45','0.81','1.16'),2):
        attempt(d,i,pct=pct)
    intermediate=get(d,30)
    assert intermediate['display_level']['value']==42
    for i,exp in enumerate((5000,5400,5800),8):attempt(d,i,exp=exp,total=T43)
    value=get(d,150)
    assert value['display_level']['value']==43
    assert value['manual_correction']['level']==42 and value['level_context']['last_transition']['phase']=='corroborated'
    totals=d.rolling_history('alpha',now=at(150))
    assert totals['current_level']==43 and not store.db.execute('SELECT 1 FROM observations').fetchone()
    total42=requirement(42)['to_next']
    assert totals['tracked_exp']['approximate']==total42-(9940*total42+5000)//10000+5800
    assert all(g['start']!=at(0).isoformat() for g in totals['chart_intervals'])


def test_weak_or_competing_arithmetic_does_not_replace_manual_seed(tracking):
    _,store,d=tracking
    attempt(d,1,pct='77.92',current=False,status='capture_failed',received_at=None,neural=None,localization=dict(count=0))
    edit(store,0,level=42,current_exp=278125,percentage_bp=7792)
    attempt(d,2,exp=5000,total=T43)
    assert get(d,15)['display_level']['value']==42


def test_rename_keeps_ids_and_invalidates_publisher_and_is_audited(tracking):
    path,store,d=tracking;event=edit(store,level=64);cid=event['character_id']
    save(d,'run',1,0,3300)
    originals={table:[tuple(r) for r in store.db.execute('SELECT * FROM '+table)]
               for table in ('sessions','observations','diagnostic_attempts','manual_corrections')}
    with create_server(path,port=0,diagnostic_dashboard=True) as server:
        before=tuple(d.heads()[0]);request((server,None),'/api/players')
        rename=store.rename_character('alpha',cid,'Tricia',reason='Replace placeholder')
        assert tuple(d.heads()[0])!=before
        value=json.loads(request((server,None),'/api/players/alpha')[2])['player']
        assert value['character']==dict(id=cid,label='Tricia')
        assert json.loads(request((server,None),'/api/players')[2])['players'][0]['character']==value['character']
        assert rename['previous_label']=='Test character'
    for table,rows in originals.items():assert [tuple(r) for r in store.db.execute('SELECT * FROM '+table)]==rows
    for label in ('',' Bad ','x\ny','x'*101,'Tricia'):
        with pytest.raises(ValueError):store.rename_character('alpha',cid,label)
    store.add_character('alpha','Other')
    with pytest.raises(ValueError,match='already exists'):store.rename_character('alpha',cid,'Other')


def test_cli_required_input_preview_history_amend_undo_and_rename(tracking,capsys):
    path,store,d=tracking;base=['--db',str(path),'--channel','alpha'];scope=['--character','Test character']
    for fields in ([],['--level','64'],['--level','64','--exp','0'],['--level','64','--exp','0','--now','--effective-at',at(20).isoformat()]):
        with pytest.raises(SystemExit):main(base+['set']+scope+fields)
    fields=['--level','64','--exp','0','--effective-at',at(20).isoformat()]
    assert main(base+['set']+scope+fields+['--dry-run'])==0
    assert json.loads(capsys.readouterr().out)['preview']
    assert store.manual_history('alpha')==[]
    assert main(base+['set']+scope+fields)==0
    event=json.loads(capsys.readouterr().out);assert not event['preview']
    assert main(base+['amend']+scope+['--correction-id',str(event['id']),'--level','49','--percentage','0.00','--effective-at',at(10).isoformat(),'--reason','Wrong level/time'])==0
    amended=json.loads(capsys.readouterr().out)
    assert main(base+['undo','--correction-id',str(amended['id']),'--reason','Restore OCR'])==0;capsys.readouterr()
    assert main(base+['rename','--character-id',str(event['character_id']),'--new-name','Tricia','--dry-run'])==0;capsys.readouterr()
    assert store.state('alpha')['characters'][0]['label']=='Test character'
    assert main(base+['rename','--character-id',str(event['character_id']),'--new-name','Tricia'])==0;capsys.readouterr()
    assert main(base+['history'])==0
    audit=json.loads(capsys.readouterr().out)
    assert len(audit['corrections'])==3 and len(audit['renames'])==1


def test_every_historical_revision_invalidates_publication_without_another_attempt(tracking,clock):
    path,store,d=tracking
    for i in range(1,5):save(d,'run',i,(i-1)*20,3300+i*10)
    clock.at=at(60)
    checkpoints={};cache={}
    with create_server(path,port=0,diagnostic_dashboard=True) as server:
        def public():return json.loads(request((server,None),'/api/players/alpha')[2])
        initial=public();d.directory(cache,now=at(60),checkpoints=checkpoints)
        point=edit(store,60,level=49,kind='point',target_kind='diagnostic',target_event_id='run:4')
        fixed=public()
        assert fixed['player']['display_level']['value']==49
        moved=edit(store,20,level=48,kind='point',target_kind='diagnostic',target_event_id='run:2',
            event_id='move-point',replaces_id=point['id'],reason='Wrong historical time')
        updated=public()
        assert updated['player']['reading']['event_id']=='run:4' and updated['player']['reading']['evidence']=='strict_full'
        assert next(p for p in updated['history'] if p['event_id']=='run:2')['level']['value']==48
        assert d.directory(cache,now=at(60),checkpoints=checkpoints)['streams'][0]['player']['reading']['evidence']=='strict_full'
        store.retract_manual('alpha','undo-point',moved['id'],reason='Restore original capture history')
        restored=public()
        assert restored['player']['reading']==initial['player']['reading']
        assert restored['tracked_history']['tracked_exp']==initial['tracked_history']['tracked_exp']
        assert restored['history']==initial['history']
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]==4


def test_same_character_session_boundaries_preserve_valid_progress(tracking):
    _,store,d=tracking
    save(d,'run',1,0,3300);save(d,'run',2,20,3310)
    store.end_session('alpha',at=at(25));store.start_session('alpha',at=at(30))
    from tests.test_diagnostic_history import config
    d.begin('new-session','alpha',config('new-session'))
    save(d,'new-session',1,40,6000);save(d,'new-session',2,60,6010)
    result=d.rolling_history('alpha',now=at(60))
    assert result['intervals']==3 and result['coverage_seconds']['approximate']==60
    assert result['tracked_exp']['approximate']==sum(g['value']['approximate'] for g in result['chart_intervals'])
    assert any(g['start']==at(20).isoformat() and g['end']==at(40).isoformat() for g in result['chart_intervals'])


def test_explicit_unbound_baseline_between_sessions_does_not_leak_into_a_new_session(tracking):
    _,store,d=tracking
    store.end_session('alpha',at=at(20))
    with pytest.raises(ValueError,match='scope'):edit(store,30,level=49)
    event=edit(store,30,level=49,no_session=True)
    assert event['session_id'] is None and get(d,40)['display_level']['value']==49
    store.start_session('alpha',at=at(50))
    assert get(d,60)['reading'] is None
    with pytest.raises(ValueError,match='exclusively'):edit(store,55,session_id=2,no_session=True)


def test_a_newer_point_correction_survives_an_older_baseline_clear(tracking):
    _,store,d=tracking
    save(d,'run',1,0,3300);save(d,'run',2,60,3310)
    edit(store,20,clear=True,level=None,percentage_bp=None)
    point=edit(store,60,kind='point',target_kind='diagnostic',target_event_id='run:2',level=49)
    value=get(d,60)
    assert value['reading']['provenance']['id']==point['id'] and value['display_level']['value']==49
