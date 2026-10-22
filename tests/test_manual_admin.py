"""Manual values are public baselines, never fabricated OCR or earned EXP."""
from datetime import datetime,timedelta,timezone
import json
import sqlite3
import time

import pytest

from exp_tracker.diagnostics import Diagnostics
from exp_tracker.manual_admin import main
from exp_tracker.product import player
from exp_tracker.schema import STATEMENTS,MIGRATION_2,MIGRATION_3,MIGRATION_4,VERSION
from exp_tracker.server import create_server
from exp_tracker.store import Store
from tests.test_product import tracking,NOW
from tests.test_diagnostic_history import config
from tests.test_tracked_exp_totals import save
from tests.test_server import request
from tests.test_store import profile,reading


def at(seconds):return NOW+timedelta(seconds=seconds)


def correct(store,seconds=25,**values):
    return store.correct_manual('alpha',f'correction-{seconds}',store.state('alpha')['selected_character_id'],
                                effective_at=at(seconds),**values)


def current(d,seconds=30):
    return player(d.snapshot('alpha',now=at(seconds)),now=at(seconds))


@pytest.mark.parametrize('version',[0,3,4])
def test_additive_migration_and_restart(tmp_path,version):
    path=tmp_path/'migration.sqlite3'
    if version:
        with sqlite3.connect(path) as db:
            for sql in (*STATEMENTS,*MIGRATION_2,*MIGRATION_3,*(MIGRATION_4 if version==4 else ())):db.execute(sql)
            db.execute(f'PRAGMA user_version={version}')
            db.execute("INSERT INTO streamers(id,login) VALUES(1,'alpha')")
            db.execute("INSERT INTO characters VALUES(1,1,'Main')")
            db.execute('UPDATE streamers SET selected_character_id=1')
            db.execute('INSERT INTO tracking_state(character_id) VALUES(1)')
        before=path.read_bytes()
        with Store(path,read_only=True) as store:
            assert store.schema_version==version and store.manual_history('alpha')==[]
        assert path.read_bytes()==before
    with Store(path) as store:
        assert store.schema_version==(10 if version else VERSION)
        store.add_channel('alpha');cid=store.add_character('alpha','Main');store.select_character('alpha',cid,at=NOW)
        result=correct(store,level=64,current_exp=0,percentage_bp=0,reason='baseline')
    with Store(path,read_only=True) as store:
        assert store.manual_history('alpha')[0]['id']==result['id']
        p=current(Diagnostics(store))
        assert p['reading']['exp']=='0' and p['reading']['percentage']=='0.00'
        assert p['display_level']['value']==64
        assert p['reading']['evidence']=='manual_admin' and not p['reading']['trusted']
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
    with Store(path) as store:
        for sql in ('UPDATE manual_corrections SET level=65','DELETE FROM manual_corrections'):
            with pytest.raises(sqlite3.IntegrityError,match='append-only'):store.db.execute(sql)


def test_persistence_supplied_fields_and_no_ocr_changes(tracking):
    path,store,d=tracking;save(d,'run',1,0,3300)
    raw=list(store.db.execute('SELECT payload_json FROM diagnostic_attempts'))
    state=store.state('alpha',as_of=NOW)
    event=correct(store,level=65,percentage_bp=0,reason='Selected HUD level and percentage')
    assert event['provenance']=='manual_admin' and event['current_exp'] is None and event['percentage_bp']==0
    assert datetime.fromisoformat(event['recorded_at']).utcoffset()==timedelta(0)
    assert store.state('alpha',as_of=NOW)==state
    assert list(store.db.execute('SELECT payload_json FROM diagnostic_attempts'))==raw
    assert not store.db.execute('SELECT 1 FROM observations').fetchone()
    with Store(path,read_only=True) as reopened:
        assert reopened.manual_history('alpha')==store.manual_history('alpha')
        p=current(Diagnostics(reopened))
        assert p['reading']['exp'] is None and p['reading']['percentage']=='0.00'
        assert p['display_level']['value']==65


@pytest.mark.parametrize('values,exp,pct',[
    ({'level':200,'current_exp':0},'0',None),({'level':64,'current_exp':0},'0','0.00'),
    ({'level':64,'percentage_bp':9999},None,'99.99'),
    ({'level':64,'percentage_bp':5000},None,'50.00'),({'level':64,'current_exp':123},'123','0.00'),
])
def test_one_exp_coordinate_keeps_supplied_and_estimated_fields_separate(tracking,values,exp,pct):
    _,store,d=tracking;correct(store,**values)
    p=current(d)
    assert p['reading']['exp']==exp and p['reading']['percentage']==pct
    assert p['reading']['evidence']=='manual_admin' and p['segment'] is None
    assert p['estimates']['exp_per_hour'] is None
    if 'current_exp' not in values:assert p['reading']['estimated_exp']
    elif pct is not None:assert p['reading']['estimated_percentage']


def test_older_and_delayed_frames_cannot_override_but_fresh_ocr_resumes(tracking):
    _,store,d=tracking
    save(d,'run',1,0,3300);save(d,'run',2,20,3305)
    correct(store,level=65,current_exp=100,percentage_bp=0)
    assert current(d)['reading']['exp']=='100'
    # Acquired before the edit, delivered after it.
    save(d,'run',3,23,3310,received_at=at(30).isoformat())
    p=current(d,30)
    assert p['reading']['exp']=='100' and p['display_level']['value']==65
    # Unique EXP arithmetic with no level readers cannot replace the manual level.
    save(d,'run',4,40,3315,visual_level=None,visual_status='unavailable',neural_level=None)
    p=current(d,40)
    assert p['display_level']['value']==65 and p['display_level']['evidence']['status']=='manual_admin'
    # New reader agreement releases the level and ordinary OCR releases the numeric pair.
    save(d,'run',5,60,3320,neural_level=dict(level=64,text='64',status='numeric_candidate',score=.99))
    p=current(d,60)
    assert p['display_level']['value']==64 and p['reading']['percentage']=='33.20'
    assert p['reading']['evidence']=='strict_full'


@pytest.mark.parametrize('level,bp',[(64,6000),(65,10),(63,4000)])
@pytest.mark.parametrize('full',[True,False])
def test_correction_boundary_preserves_old_and_new_gains_without_artificial_gain(tracking,level,bp,full):
    _,store,d=tracking
    save(d,'run',1,0,3300,full=full);save(d,'run',2,20,3310,full=full)
    before=d.rolling_history('alpha',now=at(20))['tracked_exp']['approximate']
    checkpoints={};eta_cache={}
    d.rolling_history('alpha',now=at(24),checkpoints=checkpoints)
    d.recent_snapshot('alpha',now=at(24),checkpoints=checkpoints,eta_cache=eta_cache)
    correct(store,level=level,current_exp=777777,percentage_bp=bp)
    for seconds in (25,30):
        assert d.rolling_history('alpha',now=at(seconds),checkpoints=checkpoints)['tracked_exp']['approximate']==before
    for index,seconds,value in ((3,40,bp),(4,60,bp+10)):
        save(d,'run',index,seconds,value,level=level,full=full,
             neural_level=dict(level=level,text=str(level),status='numeric_candidate',score=.99))
    result=d.rolling_history('alpha',now=at(60),checkpoints=checkpoints)
    snap=d.snapshot('alpha',now=at(60));after=[r for r in snap['observations'] if r['manual_epoch']]
    from exp_tracker.product import reading as public_reading
    from exp_tracker.pace_intervals import endpoint_interval
    expected=before+endpoint_interval(public_reading(after[0]),public_reading(after[1]))[0]['value']['approximate']
    assert result['tracked_exp']['approximate']==expected
    assert result['coverage_seconds']['approximate']==40
    assert len(result['chart_intervals'])==2
    assert sum(g['value']['approximate'] for g in result['chart_intervals'])==expected
    for minutes,metric in result['windows'].items():
        assert metric['gain']['approximate']==expected
        assert metric['rate']['approximate']==expected*60/int(minutes)
        assert metric['observed']['coverage_seconds']['approximate']==40
    assert result==d.rolling_history('alpha',now=at(60))
    assert d.recent_snapshot('alpha',now=at(60),checkpoints=checkpoints,eta_cache=eta_cache)==d.recent_snapshot('alpha',now=at(60))


def test_selected_character_and_session_isolation_and_clear(tracking):
    _,store,d=tracking;original=store.state('alpha')['selected_character_id']
    correct(store,level=65,percentage_bp=4000)
    assert current(d)['reading']['percentage']=='40.00'
    correct(store,35,clear=True)
    assert current(d,36)['reading'] is None
    assert len(store.manual_history('alpha'))==2
    correct(store,40,level=66,percentage_bp=0)
    other=store.add_character('alpha','Other');store.select_character('alpha',other,at=at(45))
    store.start_session('alpha',at=at(45))
    assert current(d,50)['reading'] is None and current(d,50).get('manual_correction') is None
    store.select_character('alpha',original,at=at(55));store.start_session('alpha',at=at(55))
    assert current(d,60)['reading'] is None and current(d,60).get('manual_correction') is None
    store.add_channel('beta');assert store.manual_history('beta')==[]
    foreign=store.add_character('beta','Foreign')
    with pytest.raises(ValueError,match='belong'):
        store.correct_manual('alpha','wrong',foreign,level=67,percentage_bp=0,effective_at=at(60))


def test_clear_and_supersede_are_new_baselines_and_fresh_ocr_can_resume(tracking):
    _,store,d=tracking;correct(store,level=65,current_exp=50)
    second=correct(store,30,level=65,percentage_bp=0)
    p=current(d,31)
    assert p['reading']['exp'] is None and p['reading']['percentage']=='0.00'
    correct(store,35,clear=True)
    save(d,'run',1,40,3300);save(d,'run',2,60,3310)
    p=current(d,60)
    assert p['reading']['evidence']=='strict_full' and p['reading']['manual_epoch']!=second['id']
    assert p['display_level'] is None  # One visual reader is still available in reading.level.
    assert d.rolling_history('alpha',now=at(60))['intervals']==1


@pytest.mark.parametrize('values',[
    {},{'level':0},{'level':201},{'level':True},{'level':1.5},{'current_exp':-1},{'current_exp':2**63},
    {'current_exp':'123'},{'percentage_bp':10000},{'percentage_bp':-1},{'percentage_bp':1.1},
    {'level':64,'clear':True},{'clear':True,'percentage_bp':0},{'reason':''},{'level':64,'reason':'x\ny'},
    {'level':64,'effective_at':datetime(2026,1,1)},{'level':64,'effective_at':'2026-01-01'},
    {'level':64,'effective_at':datetime.now(timezone.utc)+timedelta(days=1)},
])
def test_invalid_input_is_atomic(tracking,values):
    _,store,_=tracking;cid=store.state('alpha')['selected_character_id']
    with pytest.raises(ValueError):store.correct_manual('alpha','bad',cid,**values)
    assert store.manual_history('alpha')==[]


def test_duplicate_conflicting_and_out_of_order_events(tracking):
    _,store,d=tracking;event=correct(store,level=64,percentage_bp=0)
    duplicate=correct(store,level=64,percentage_bp=0)
    assert duplicate['duplicate'] and duplicate['id']==event['id']
    cid=store.state('alpha')['selected_character_id']
    assert store.correct_manual('alpha','correction-25',cid,level=64,percentage_bp=0,now=True)['duplicate']
    with pytest.raises(ValueError,match='different contents'):correct(store,level=65,percentage_bp=0)
    with pytest.raises(ValueError):
        store.correct_manual('alpha','pre-session',cid,level=65,percentage_bp=0,effective_at=at(-1))
    store.correct_manual('alpha','earlier',cid,level=65,percentage_bp=0,effective_at=at(20))
    assert current(d)['display_level']['value']==64  # Effective order, not submission order.
    # UTC normalization, including offset-form input.
    utc_event=store.correct_manual('alpha','offset',cid,level=65,percentage_bp=0,
        effective_at=datetime.fromisoformat('2025-12-31T19:00:30-05:00'))
    assert utc_event['effective_at'].startswith('2026-01-01T00:00:30.')


def test_manual_level_supplies_future_percentage_context_without_revalidating_old_ocr(tracking):
    _,store,d=tracking
    save(d,'run',1,0,3300,full=False,visual_level=None,visual_status='unavailable',neural_level=None)
    correct(store,level=64,percentage_bp=5000)
    for index,seconds,bp in ((2,40,5000),(3,60,5010)):
        save(d,'run',index,seconds,bp,full=False,visual_level=None,visual_status='unavailable',neural_level=None)
    snap=d.snapshot('alpha',now=at(60));p=current(d,60)
    assert snap['observations'][0]['experimental_level']['value'] is None
    assert p['reading']['evidence']=='strict_percentage_only' and p['reading']['percentage']=='50.10'
    assert p['display_level']['evidence']['status']=='manual_admin'
    assert p['reading']['level']['identity_verified'] is False
    assert p['responsive_pace']['coverage_seconds']['approximate']==20
    assert d.rolling_history('alpha',now=at(60))['intervals']==1
    assert not store.db.execute('SELECT 1 FROM observations').fetchone()


def test_duplicate_source_frames_and_out_of_order_ocr_do_not_release_override(tracking):
    _,store,d=tracking
    save(d,'run',1,0,3300)
    event=correct(store,level=64,current_exp=123,percentage_bp=5000)
    save(d,'run',2,40,3300,frame_sha256=f'{0:064x}')
    p=current(d,40)
    assert p['reading']['exp']=='123' and p['reading']['evidence']=='manual_admin'
    save(d,'run',3,30,3301)  # A late attempt whose acquisition predates the preceding one.
    p=current(d,45)
    assert p['reading']['exp']=='123'
    save(d,'run',4,60,5010)
    p=current(d,60)
    assert p['reading']['evidence']=='strict_full' and p['reading']['manual_epoch']==event['id']
    assert d.rolling_history('alpha',now=at(60))['tracked_exp'] is None


def test_no_progress_fabricated_with_unknown_transition_requirements(tracking):
    _,store,d=tracking
    save(d,'run',1,0,3300);save(d,'run',2,20,3310)
    before=d.rolling_history('alpha',now=at(20))['tracked_exp']
    correct(store,level=99,current_exp=10,percentage_bp=0)
    for index,seconds,level in ((3,40,99),(4,60,100)):
        save(d,'run',index,seconds,100,level=level,full=True,
             neural_level=dict(level=level,text=str(level),status='numeric_candidate',score=.99))
    result=d.rolling_history('alpha',now=at(60))
    assert result['tracked_exp']==before and len(result['chart_intervals'])==1


def test_current_level_filter_uses_manual_level_immediately_without_capture(tracking):
    _,store,d=tracking
    save(d,'run',1,0,3300,neural_level=dict(level=64,text='64',status='numeric_candidate',score=.99))
    save(d,'run',2,20,3310,neural_level=dict(level=64,text='64',status='numeric_candidate',score=.99))
    correct(store,level=65,percentage_bp=0)
    p=current(d,30);tracked=d.rolling_history('alpha',now=at(30))
    assert p['display_level']['value']==65 and tracked['current_level']==65
    assert p['recent_windows']['5']['gain'] is not None
    assert tracked['windows']['5']['gain'] is not None
    assert p['current_level_windows']['5']['gain'] is None
    assert tracked['current_level_windows']['5']['gain'] is None


def test_manual_boundaries_exclude_resets_and_losses_from_earned_gain():
    from exp_tracker.pace_intervals import window_endpoints
    # A loss interval and a correction both start new earned-EXP baselines.
    points=[]
    for index,exp in enumerate((600000,599900,700000,700300)):
        points.append(dict(event_id=str(index),timestamp=at(index*20).isoformat(),level=dict(value=67),
            exp=str(exp),bp=100,evidence='strict_full',accounting_scope='1:1',manual_epoch=None if index<2 else 1))
    _,gain,_=window_endpoints(points,start=NOW,end=at(60))
    assert gain['value']['approximate']==300 and gain['coverage_seconds']['approximate']==20


def test_trusted_accounting_resumes_with_ocr_baseline_not_manual_gain(tracking,profile):
    _,store,d=tracking;sid=store.state('alpha')['session']['id']
    ingest=lambda event,seconds,exp:store.ingest('alpha',event,at(seconds),reading(exp,10,64),profile=profile,session_id=sid)
    ingest('before',0,1000);ingest('earned',20,1100)
    correct(store,level=65,current_exp=500000)
    after=ingest('after',40,500000)
    assert after['outcome']=='baseline' and after['gained_exp'] is None
    assert ingest('new-earned',60,500100)['gained_exp']==100
    assert store.state('alpha')['observed_session_exp']==200


def test_publication_and_directory_invalidation_without_new_capture(tracking):
    path,store,d=tracking;save(d,'run',1,0,3300)
    with create_server(path,port=0,diagnostic_dashboard=True) as server:
        cache={};before=tuple(d.heads()[0]);d.directory(cache)
        first=json.loads(request((server,None),'/api/players/alpha')[2])
        event=correct(store,level=70,current_exp=123456,percentage_bp=5000)
        assert tuple(d.heads()[0])!=before
        second=json.loads(request((server,None),'/api/players/alpha')[2])
        board=json.loads(request((server,None),'/api/players')[2])['players'][0]
        assert first['player']['reading']!=second['player']['reading']
        assert board['reading']==second['player']['reading']
        assert board['reading']['exp']=='123456' and board['display_level']['value']==70
        assert d.directory(cache)['streams'][0]['player']['manual_correction']['id']==event['id']
        for route in ('/','/stream/alpha','/live/overlay/alpha'):
            assert request((server,None),route)[0]==200
        assert request((server,None),'/api/players/alpha','POST')[0]==405


def test_background_publisher_detects_external_cli_style_write(tracking):
    path,store,d=tracking
    with create_server(path,port=0,diagnostic_dashboard=True,background=True) as server:
        def wait(predicate):
            until=time.monotonic()+10
            while time.monotonic()<until:
                if predicate():return
                time.sleep(.02)
            pytest.fail(f'publication timeout: {server.publisher.stats}')
        wait(lambda:server.publisher.entry('alpha') is not None)
        with Store(path) as writer:event=correct(writer,level=72,percentage_bp=1234)
        # No wake() from capture or a browser request.
        # The correction drops the old publication at once, so the entry is briefly None until the rebuild.
        wait(lambda:(e:=server.publisher.entry('alpha')) is not None and e['card']['player'].get('manual_correction',{}).get('id')==event['id'])
        assert json.loads(server.publisher.character('alpha'))['player']['reading']['percentage']=='12.34'


def test_cli_inspect_set_history_clear_and_errors(tracking,capsys):
    path,store,_=tracking;args=['--db',str(path),'--channel','alpha']
    assert main(args+['inspect'])==0
    assert json.loads(capsys.readouterr().out)['selected_character_id']
    command=args+['set','--character','Test character','--level','64','--exp','0','--percentage','0.00',
                  '--event-id','cli','--effective-at',at(25).isoformat(),'--reason','Test baseline']
    assert main(command)==0;assert json.loads(capsys.readouterr().out)['provenance']=='manual_admin'
    assert main(command)==0;assert json.loads(capsys.readouterr().out)['duplicate']
    assert main(args+['history'])==0;assert len(json.loads(capsys.readouterr().out)['corrections'])==1
    for tail in (['set','--character','Test character'],['set','--character','Wrong','--level','64'],
                 ['set','--character','Test character','--percentage','99.999'],
                 ['set','--character','Test character','--level','201'],
                 ['set','--character','Test character','--level','64','--effective-at','2026-01-01'],
                 ['set','--character','Test character','--percentage','NaN'],
                 ['set','--character','Test character','--level','64','--bogus']):
        with pytest.raises(SystemExit) as error:main(args+tail)
        assert error.value.code==2
    assert len(store.manual_history('alpha'))==1
    assert main(args+['clear','--character','Test character','--effective-at',at(30).isoformat()])==0
    assert store.manual_history('alpha')[-1]['action']=='clear'
