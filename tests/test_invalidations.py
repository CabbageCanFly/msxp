"""Source exclusions precede inference; no OCR or original accounting rows are rewritten."""
from datetime import timedelta
import json
import sqlite3
import uuid

import pytest

from exp_tracker.invalidations import Invalidations,revision,PAGE
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.product import player,history
from exp_tracker.store import Store
from exp_tracker.schema import VERSION
from exp_tracker.admin_server import AdminServer
from exp_tracker.server import create_server
from tests.test_admin_server import request,preview,commit
from tests.test_product import tracking,NOW
from tests.test_manual_admin import at,current
from tests.test_store import profile,reading
from tests.test_tracked_exp_totals import save,fill
from tests.test_server import request as public_request


def single(store, identity, action='invalidate', kind='diagnostic', seconds=None):
    service=Invalidations(store);cid=store.state('alpha')['selected_character_id']
    row=service.source('alpha',cid,kind,str(identity))
    return dict(action=action,kind=kind,identity=str(identity),timestamp=row['original_at'])


def apply(store,spec,cid=None,event_id=None):
    cid=cid or store.state('alpha')['selected_character_id'];service=Invalidations(store)
    preview=service.preview('alpha',cid,spec)
    return service.commit('alpha',cid,event_id or uuid.uuid4().hex,spec,preview['fingerprint'],'Synthetic review')


@pytest.mark.parametrize('only', [None, 'run:1', [['diagnostic','absent:1']],
    [['diagnostic','run:1'],['diagnostic','run:1']], [['other','run:1']], [['diagnostic',1]]])
def test_explicit_range_selection_rejects_ambiguous_sources(tracking, only):
    _,store,d=tracking
    save(d,'run',1,20,3310)
    spec=dict(action='invalidate',start=at(0).isoformat(),end=at(40).isoformat(),only=only)
    with pytest.raises(ValueError):Invalidations(store).selection('alpha',store.state('alpha')['selected_character_id'],spec)
    assert store.db.execute('SELECT COUNT(*) FROM reading_batches').fetchone()[0]==0


def test_single_exclusion_and_restore_preserve_source_restart_and_history(tracking):
    path,store,d=tracking
    for i,t in enumerate((0,20,40,60),1):save(d,'run',i,t,3300+i*10)
    original=[tuple(r) for r in store.db.execute('SELECT * FROM diagnostic_attempts')]
    before=d.rolling_history('alpha',now=at(61))['tracked_exp']
    event=apply(store,single(store,'run:2'))
    snapshot=d.snapshot('alpha',now=at(61));row=snapshot['observations'][1]
    assert row['reading_invalidated']['batch_id']==event['id']
    assert row['experimental_level']['value'] is None and row['candidate'] is None and row['visual_level'] is None
    assert 'run:2' not in [r['event_id'] for r in history(snapshot)]
    assert all(p['event_id']!='run:2' for p in d.rolling_history('alpha',now=at(61)).get('points',[]))
    assert d.rolling_history('alpha',now=at(61))['tracked_exp']['approximate']<=before['approximate']
    with pytest.raises(ValueError,match='already invalidated'):apply(store,single(store,'run:2'))
    with Store(path,read_only=True) as reopened:assert revision(reopened,'alpha')==1
    apply(store,single(store,'run:2','restore'))
    assert d.rolling_history('alpha',now=at(61))['tracked_exp']==before
    assert [tuple(r) for r in store.db.execute('SELECT * FROM diagnostic_attempts')]==original
    with pytest.raises(ValueError,match='not invalidated'):apply(store,single(store,'run:2','restore'))
    for table in ('reading_batches','reading_events','reading_commits'):
        for action in (f'DELETE FROM {table}',f'UPDATE {table} SET id=id'):
            with pytest.raises(sqlite3.IntegrityError,match='append-only'):store.db.execute(action)


def test_latest_and_false_level_up_cannot_supply_confirmation(tracking):
    _,store,d=tracking
    for i,t in enumerate((0,20,40,60),1):
        level=64 if i<3 else 65
        save(d,'run',i,t,3300+i*10 if level==64 else 10+i,level=level,
            neural_level=dict(level=level,text=str(level),status='numeric_candidate',score=.99))
    assert current(d,61)['display_level']['value']==65
    event=apply(store,dict(action='invalidate',start=at(40).isoformat(),end=at(61).isoformat()))
    result=current(d,61)
    assert result['display_level']['value']==64 and result['reading']['event_id']=='run:2'
    assert all(p['event_id'] not in ('run:3','run:4') for p in history(d.snapshot('alpha',now=at(61))))
    apply(store,dict(action='restore',batch_id=event['id']))
    assert current(d,61)['display_level']['value']==65


def test_complete_range_beyond_dashboard_limit_and_half_open_boundaries(tracking):
    _,store,d=tracking
    fill(d,181)
    spec=dict(action='invalidate',start=at(20).isoformat(),end=at(3600).isoformat())
    cid=store.state('alpha')['selected_character_id'];service=Invalidations(store)
    p=service.preview('alpha',cid,spec)
    assert p['total']==p['count']==179 and len(p['readings'])==PAGE
    last=service.preview('alpha',cid,spec,p['pages']-1)
    assert len(last['readings'])==29
    event=apply(store,spec)
    assert event['count']==179
    states=list(store.db.execute("SELECT * FROM reading_validity WHERE action='invalidate'"))
    assert min(r['original_at'] for r in states)==at(20).isoformat(timespec='microseconds')
    assert max(r['original_at'] for r in states)==at(3580).isoformat(timespec='microseconds')
    apply(store,dict(action='restore',batch_id=event['id']))
    assert not store.db.execute("SELECT 1 FROM reading_validity WHERE action='invalidate'").fetchone()


def test_already_invalidated_batch_members_individual_restore_and_reinvalidations(tracking):
    _,store,d=tracking
    for i in range(1,5):save(d,'run',i,(i-1)*20,3300+i*10)
    old=apply(store,single(store,'run:1'))
    spec=dict(action='invalidate',start=at(0).isoformat(),end=at(61).isoformat())
    service=Invalidations(store);cid=store.state('alpha')['selected_character_id']
    p=service.preview('alpha',cid,spec)
    assert p['total']==4 and p['count']==3 and p['already_invalidated']==1
    batch=apply(store,spec)
    apply(store,single(store,'run:2','restore'))
    newer=apply(store,single(store,'run:2'))
    restore=apply(store,dict(action='restore',batch_id=batch['id']))
    assert restore['count']==2
    active=list(store.db.execute("SELECT target_event_id,batch_id FROM reading_validity WHERE action='invalidate' ORDER BY target_event_id"))
    assert [tuple(r) for r in active]==[('run:1',old['id']),('run:2',newer['id'])]


def test_capture_inside_range_invalidates_preview_but_outside_does_not(tracking):
    _,store,d=tracking;save(d,'run',1,0,3300)
    service=Invalidations(store);cid=store.state('alpha')['selected_character_id']
    spec=dict(action='invalidate',start=at(0).isoformat(),end=at(50).isoformat())
    p=service.preview('alpha',cid,spec)
    save(d,'run',2,20,3310)
    with pytest.raises(ValueError,match='changed since review'):service.commit('alpha',cid,'stale',spec,p['fingerprint'])
    assert revision(store,'alpha')==0
    p=service.preview('alpha',cid,spec);save(d,'run',3,60,3320)
    receipt=service.commit('alpha',cid,'stable',spec,p['fingerprint'])
    assert receipt['count']==2
    assert service.commit('alpha',cid,'stable',spec,p['fingerprint'])==receipt


def test_no_partial_publication_when_capture_arrives_during_chunked_save(tracking,monkeypatch):
    import exp_tracker.invalidations as module
    _,store,d=tracking
    for i in range(1,5):save(d,'run',i,(i-1)*20,3300+i*10)
    monkeypatch.setattr(module,'WRITE_CHUNK',1)
    service=Invalidations(store);cid=store.state('alpha')['selected_character_id']
    spec=dict(action='invalidate',start=at(0).isoformat(),end=at(100).isoformat())
    p=service.preview('alpha',cid,spec)
    original=service.selection;calls=[]
    def selection(*args):
        calls.append(1)
        if len(calls)==2:
            # Same writer connection, inside final lock: emulate capture committed before activation.
            d._append('run',dict(type='attempt',index=5,attempted_at=at(80).isoformat(),received_at=at(80).isoformat(),
                trusted=False,current=True,status='diagnostic_percentage_only',source=dict(kind='twitch',channel='alpha'),neural=dict(text='[33.50%]')))
        return original(*args)
    monkeypatch.setattr(service,'selection',selection)
    with pytest.raises(ValueError,match='nothing was applied'):service.commit('alpha',cid,'interrupted',spec,p['fingerprint'])
    assert store.db.execute('SELECT COUNT(*) FROM reading_events').fetchone()[0]==4
    assert revision(store,'alpha')==0
    assert not store.db.execute('SELECT 1 FROM reading_validity').fetchone()


def test_point_corrections_and_invalidations_cannot_compete(tracking):
    _,store,d=tracking;save(d,'run',1,0,3300)
    cid=store.state('alpha')['selected_character_id']
    point=store.correct_manual('alpha','point',cid,level=49,current_exp=1,effective_at=at(0),
        kind='point',target_kind='diagnostic',target_event_id='run:1')
    with pytest.raises(ValueError,match='manual correction'):apply(store,single(store,'run:1'))
    store.retract_manual('alpha','undo',point['id'],reason='wrong point')
    apply(store,single(store,'run:1'))
    with pytest.raises(ValueError,match='restore it'):store.correct_manual('alpha','point-again',cid,level=49,current_exp=1,
        effective_at=at(0),kind='point',target_kind='diagnostic',target_event_id='run:1')


def test_character_session_ownership_and_incorrect_timestamp_are_rejected(tracking):
    _,store,d=tracking;save(d,'run',1,0,3300)
    spec=single(store,'run:1');other=store.add_character('alpha','Other')
    with pytest.raises(ValueError,match='belong'):apply(store,spec,cid=other)
    spec['timestamp']=at(1).isoformat()
    with pytest.raises(ValueError,match='timestamp'):apply(store,spec)
    store.add_channel('beta');foreign=store.add_character('beta','Foreign')
    with pytest.raises(ValueError,match='belong'):Invalidations(store).preview('beta',foreign,single(store,'run:1'))


def test_incremental_and_cold_replay_and_publisher_refresh(tracking):
    path,store,d=tracking;end=fill(d,181)
    cache={};eta={};before=d.rolling_history('alpha',now=end,checkpoints=cache)
    d.recent_snapshot('alpha',now=end,checkpoints=cache,eta_cache=eta)
    with create_server(path,port=0,diagnostic_dashboard=True) as server:
        server.publisher.settle()
        receipt=apply(store,single(store,'gain-3:1'))
        value=d.rolling_history('alpha',now=end,checkpoints=cache)
        assert value==d.rolling_history('alpha',now=end)
        assert d.recent_snapshot('alpha',now=end,checkpoints=cache,eta_cache=eta)==d.recent_snapshot('alpha',now=end)
        for window in value['windows'].values():assert window['gain'] is None or window['gain']['approximate']<=before['tracked_exp']['approximate']
        response=json.loads(public_request((server,None),'/api/players/alpha')[2])
        assert all(p['event_id']!='gain-3:1' for p in response['history'])
        assert response['player']['reading']['event_id']!='gain-3:1'
        apply(store,dict(action='restore',batch_id=receipt['id']))
        assert d.rolling_history('alpha',now=end,checkpoints=cache)==before


def test_trusted_accounting_last_state_and_future_ingest_use_retained_inputs(tracking,profile):
    _,store,_=tracking;sid=store.state('alpha')['session']['id']
    first=store.ingest('alpha','first',at(1),reading(1000,10),profile=profile,session_id=sid)
    middle=store.ingest('alpha','middle',at(2),reading(1500,11),profile=profile,session_id=sid)
    last=store.ingest('alpha','last',at(3),reading(2000,12),profile=profile,session_id=sid)
    originals=[tuple(r) for r in store.db.execute('SELECT * FROM observations')]
    apply(store,single(store,middle['id'],kind='observation'))
    state=store.state('alpha',as_of=at(4))
    assert state['observed_session_exp']==1000 and state['accounting_source']=='retained_trusted_ocr_replay'
    assert state['original_accounting']['observed_session_exp']==1000
    apply(store,single(store,last['id'],kind='observation'))
    state=store.state('alpha',as_of=at(4))
    assert state['last_trusted']['id']==first['id'] and state['observed_session_exp']==0
    next_row=store.ingest('alpha','next',at(5),reading(1800,11.5),profile=profile,session_id=sid)
    assert next_row['outcome']=='accepted' and next_row['gained_exp']==800
    assert next_row['interval_start_observation_id']==first['id']
    assert [tuple(r) for r in store.db.execute('SELECT * FROM observations WHERE id<=?',(last['id'],))]==originals
    apply(store,single(store,last['id'],'restore',kind='observation'))
    assert store.state('alpha',as_of=at(6))['last_trusted']['id']==last['id']
    apply(store,single(store,middle['id'],'restore',kind='observation'))
    # All restored: a capture accepted against the temporarily older anchor is rechecked, too.
    assert store.state('alpha',as_of=at(6))['last_trusted']['id']==last['id']


def test_admin_preview_pages_and_save_protection(tracking):
    path,store,d=tracking;fill(d,121)
    cid=store.state('alpha')['selected_character_id']
    data=dict(action='invalidate',channel='alpha',character_id=str(cid),start=at(0).isoformat(),end=at(2500).isoformat())
    with AdminServer(path,0) as server:
        p=preview(server,data)
        assert p['count']==121 and len(p['readings'])==PAGE
        page=request(server,f"/api/invalidation-preview?preview_id={p['preview_id']}&page=1")[2]
        assert len(page['readings'])==PAGE and page['page']==1
        for _ in range(2):assert request(server,'/api/save','POST',dict(preview_id=p['preview_id']))[0]==200
        assert len(request(server)[2]['invalidation_history']['batches'])==1
        assert request(server,'/api/invalidated?channel=alpha&character_id='+str(cid))[2]['next_before']
        result=commit(server,dict(action='restore_batch',channel='alpha',character_id=str(cid),batch_id=str(request(server)[2]['invalidation_history']['batches'][0]['id'])))
        assert result['event']['count']==121


def test_schema_six_additive_upgrade_and_old_reader_does_not_migrate(tmp_path):
    import exp_tracker.schema as schema
    path=tmp_path/'old.sqlite3'
    with sqlite3.connect(path) as db:
        for command in (*schema.STATEMENTS,*schema.MIGRATION_2,*schema.MIGRATION_3,*schema.MIGRATION_4,*schema.MIGRATION_5,*schema.MIGRATION_6):db.execute(command)
        db.execute('PRAGMA user_version=6')
    before=path.read_bytes()
    with Store(path,read_only=True) as store:assert store.schema_version==6
    assert path.read_bytes()==before
    with Store(path) as store:assert store.schema_version==VERSION


def test_wrong_middle_frame_is_removed_before_level_and_gain_reconstruction(tracking):
    _,store,d=tracking
    for i,t,level,bp in [(1,0,64,3300),(2,20,65,20),(3,40,64,3310)]:
        save(d,'run',i,t,bp,level=level,neural_level=dict(level=level,text=str(level),status='numeric_candidate',score=.99))
    apply(store,single(store,'run:2'))
    result=d.rolling_history('alpha',now=at(41))
    assert current(d,41)['display_level']['value']==64
    assert result['tracked_exp']['approximate']>0
    assert len(result['chart_intervals'])==1
    edge=result['chart_intervals'][0]
    assert edge['kind']=='endpoint_supported'
    assert edge['value']['approximate']==result['tracked_exp']['approximate']
    for minutes,metric in result['windows'].items():
        assert metric['gain']==result['tracked_exp']
        assert metric['rate']['approximate']==result['tracked_exp']['approximate']*60/int(minutes)


def test_removing_multiple_huds_preserves_a_barrier(tracking):
    _,store,d=tracking
    for i,t in enumerate((0,20,40),1):
        save(d,'run',i,t,3300+i*10,localization=dict(count=2 if i==2 else 1),
            neural_level=dict(level=64,text='64',status='numeric_candidate',score=.99))
    apply(store,single(store,'run:2'))
    result=d.rolling_history('alpha',now=at(41))
    assert result['tracked_exp'] is None or result['tracked_exp']['approximate']==0


def test_mixed_source_range_preserves_exact_fractional_and_offset_boundaries(tracking,profile):
    _,store,d=tracking;sid=store.state('alpha')['session']['id'];cid=store.state('alpha')['selected_character_id']
    for i,microsecond in enumerate((123455,123456,123457),1):
        stamp=at(20).replace(microsecond=microsecond)
        save(d,'run',i,20+i,3300+i,attempted_at=stamp.isoformat(),received_at=stamp.isoformat())
        store.ingest('alpha',f'trusted-{i}',stamp,reading(1000+i,10),profile=profile,session_id=sid)
    # Same UTC instant, expressed in a different offset. Both namespaces are included.
    from datetime import timezone
    spec=dict(action='invalidate',start=at(20).replace(microsecond=123456).astimezone(timezone(timedelta(hours=1))).isoformat(),
              end=at(20).replace(microsecond=123457).isoformat())
    value=Invalidations(store).preview('alpha',cid,spec)
    assert value['total']==2 and {r['kind'] for r in value['readings']}=={'diagnostic','observation'}
    assert all(r['timestamp'].endswith('20.123456+00:00') for r in value['readings'])


def test_excluding_all_readings_has_an_empty_public_state_and_restore_recovers(tracking):
    _,store,d=tracking
    for i in range(1,4):save(d,'run',i,i*20,3300+i*10)
    before=current(d,61)
    event=apply(store,dict(action='invalidate',start=at(0).isoformat(),end=at(61).isoformat()))
    result=current(d,61)
    assert result['reading'] is None and result['display_level'] is None
    assert history(d.snapshot('alpha',now=at(61)))==[]
    apply(store,dict(action='restore',batch_id=event['id']))
    assert current(d,61)==before


def test_baseline_survives_independent_exclusion_and_unsafe_checkpoints_match(tracking):
    _,store,d=tracking;cid=store.state('alpha')['selected_character_id']
    store.correct_manual('alpha','baseline',cid,level=64,percentage_bp=3300,effective_at=at(0))
    for i in range(1,5):save(d,'run',i,i*20,3300+i*10,localization=dict(count=2 if i==2 else 1))
    cache={};d.rolling_history('alpha',now=at(81),checkpoints=cache)
    apply(store,single(store,'run:2'))
    assert d.rolling_history('alpha',now=at(81),checkpoints=cache)==d.rolling_history('alpha',now=at(81))
    assert current(d,81)['display_level']['value']==64


def test_membership_cannot_change_after_activation(tracking):
    _,store,d=tracking;save(d,'run',1,0,3300)
    event=apply(store,single(store,'run:1'))
    with pytest.raises(sqlite3.IntegrityError,match='already committed'):
        store.db.execute('''INSERT INTO reading_events(batch_id,kind,source_id,target_event_id,session_id,original_at)
            SELECT batch_id,kind,source_id+1,target_event_id,session_id,original_at FROM reading_events WHERE batch_id=?''',(event['id'],))


def test_admin_capture_invalidates_both_review_page_and_save(tracking):
    path,store,d=tracking;save(d,'run',1,0,3300)
    with AdminServer(path,0) as server:
        p=preview(server,dict(action='invalidate',channel='alpha',character_id='1',start=at(0).isoformat(),end=at(50).isoformat()))
        save(d,'run',2,20,3310)
        assert request(server,f"/api/invalidation-preview?preview_id={p['preview_id']}&page=0")[0]==400
        assert request(server,'/api/save','POST',dict(preview_id=p['preview_id']))[0]==409
        assert revision(store,'alpha')==0


def test_session_isolation_for_same_character_and_new_selection(tracking):
    _,store,d=tracking;save(d,'run',1,0,3300)
    first_session=store.state('alpha')['session']['id']
    store.end_session('alpha',at=at(10));store.start_session('alpha',at=at(11))
    d.begin('next','alpha',dict(type='configuration',trusted=False,interval=20,source_kind='twitch'))
    save(d,'next',1,20,4400)
    batch=apply(store,single(store,'run:1'))
    assert current(d,21)['reading']['event_id']=='next:1'
    assert d.snapshot('alpha',session_id=first_session,now=at(21))['observations'][0]['reading_invalidated']
    other=store.add_character('alpha','Other');store.select_character('alpha',other,at=at(22))
    with pytest.raises(ValueError,match='belong'):Invalidations(store).preview('alpha',other,dict(action='restore',batch_id=batch['id']))
    assert current(d,23)['reading'] is None


def test_range_limit_is_an_error_never_a_silent_partial_selection(tracking,monkeypatch):
    import exp_tracker.invalidations as module
    _,store,d=tracking
    for i in range(1,4):save(d,'run',i,i*20,3300+i)
    monkeypatch.setattr(module,'MAX_SELECTION',2)
    with pytest.raises(ValueError,match='smaller range'):apply(store,dict(action='invalidate',start=at(0).isoformat(),end=at(70).isoformat()))
    assert revision(store,'alpha')==0


def test_explicit_trusted_pause_and_original_accounting_remain_visible(tracking,profile):
    from exp_tracker.models import Recognition
    _,store,_=tracking;sid=store.state('alpha')['session']['id']
    store.ingest('alpha','first',at(1),reading(1000,10),profile=profile,session_id=sid)
    pause=store.ingest('alpha','pause',at(2),Recognition('paused'),profile=profile,session_id=sid)
    last=store.ingest('alpha','last',at(3),reading(2000,11),profile=profile,session_id=sid)
    apply(store,single(store,pause['id'],kind='observation'))
    result=store.state('alpha',as_of=at(4))
    assert result['last_trusted']['id']==last['id'] and result['observed_session_exp']==0
    assert result['original_accounting']['observed_session_exp']==0
    assert result['statistics']['last_5_min']['exp'] is None


@pytest.mark.parametrize('fields',[{'start':'2026-01-01T00:00'}, {'reason':'bad\nreason'}, {'character_id':'9223372036854775808'},
    {'end':'2025-01-01T00:00:00Z'}, {'unexpected':'x'}, {'kind':'other','identity':'run:1','timestamp':'2026-01-01T00:00:00Z'}])
def test_invalid_admin_requests_cannot_write(tracking,fields):
    path,store,d=tracking;save(d,'run',1,0,3300)
    data=dict(action='invalidate',channel='alpha',character_id='1',start=at(0).isoformat(),end=at(50).isoformat());data.update(fields)
    with AdminServer(path,0) as server:
        assert request(server,'/api/preview','POST',data)[0]==400
        assert revision(store,'alpha')==0


def test_revised_trusted_rates_and_eta_exclude_latest_and_recover_after_restore(tracking,profile):
    _,store,_=tracking;sid=store.state('alpha')['session']['id'];rows=[]
    for i in range(91):rows.append(store.ingest('alpha',f'trusted-{i}',at(i*20),reading(1000+i*100,10+i/100),profile=profile,session_id=sid))
    before=store.state('alpha',as_of=at(1800))
    apply(store,single(store,rows[45]['id'],kind='observation'))
    result=store.state('alpha',as_of=at(1800))
    assert result['statistics']['exp_per_hour_30m']['exp_per_hour']==before['statistics']['exp_per_hour_30m']['exp_per_hour']
    assert result['statistics']['to_next_level']['seconds']==before['statistics']['to_next_level']['seconds']
    apply(store,single(store,rows[-1]['id'],kind='observation'))
    result=store.state('alpha',as_of=at(1800))
    assert result['last_trusted']['id']==rows[-2]['id'] and result['observed_session_exp']==8900
    assert result['original_accounting']['observed_session_exp']==9000
    assert result['statistics']['exp_per_hour_30m']['exp_per_hour']==18000
    apply(store,single(store,rows[-1]['id'],'restore',kind='observation'))
    result=store.state('alpha',as_of=at(1800))
    assert result['statistics']['exp_per_hour_30m']['missing_observations']==1
    assert result['statistics']['exp_per_hour_30m']['exp_per_hour']==before['statistics']['exp_per_hour_30m']['exp_per_hour']
    apply(store,single(store,rows[45]['id'],'restore',kind='observation'))
    assert store.state('alpha',as_of=at(1800))['statistics']==before['statistics']


def test_trusted_history_limit_never_falls_back_to_original_accounting(tracking,profile,monkeypatch):
    import exp_tracker.trusted_replay as module
    _,store,_=tracking;sid=store.state('alpha')['session']['id'];rows=[]
    for i in range(3):rows.append(store.ingest('alpha',str(i),at(i+1),reading(1000+i*100,10+i),profile=profile,session_id=sid))
    apply(store,single(store,rows[1]['id'],kind='observation'))
    monkeypatch.setattr(module,'MAX_ROWS',2)
    result=store.state('alpha',as_of=at(4))
    assert result['accounting_status']=='history_limit' and result['last_trusted'] is None
    assert result['observed_session_exp'] is None and result['original_accounting']['observed_session_exp']==200
    with pytest.raises(ValueError,match='history limit'):
        store.ingest('alpha','next',at(5),reading(1400,14),profile=profile,session_id=sid)


def test_new_recording_does_not_redisplay_an_invalidated_previous_trusted_anchor(tracking,profile):
    _,store,_=tracking;sid=store.state('alpha')['session']['id']
    first=store.ingest('alpha','first',at(1),reading(1000,10),profile=profile,session_id=sid)
    last=store.ingest('alpha','last',at(2),reading(2000,11),profile=profile,session_id=sid)
    apply(store,single(store,last['id'],kind='observation'))
    store.end_session('alpha',at=at(3));new_session=store.start_session('alpha',at=at(4))
    result=store.state('alpha',as_of=at(5))
    assert result['status']=='waiting' and result['last_trusted']['id']==first['id']
    assert result['observed_session_exp']==0 and result['continuity_broken']
    assert result['statistics']['last_5_min']['exp'] is None
    new=store.ingest('alpha','new',at(6),reading(3000,12),profile=profile,session_id=new_session)
    assert new['outcome']=='baseline' and new['gained_exp'] is None
    assert store.state('alpha',as_of=at(7))['last_trusted']['id']==new['id']
