"""Twitch coordinator path with generated frames, mocked OCR/acquisition, and disposable DBs."""
from datetime import timedelta
import json
import socket
import sqlite3
from types import SimpleNamespace

import pytest

from exp_tracker.character_automation import original
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.store import Store
from tests.test_identity_coordinator import coordinator, payloads, BASE  # noqa: F401
from tests.test_multi_alpha import multi  # noqa: F401


@pytest.fixture
def live(coordinator):
    module, old, config, played, steps, scripts = coordinator
    root = old.parent/'character-live-trial'/'isolated-test'
    root.mkdir(parents=True)
    path, db, logs = root/'config.json', root/'tracking.sqlite3', root/'logs'
    row = config['streams'][0]
    row.update(source='twitch', authorized=True, interval=60, count=6, character='PendingOCR')
    row.pop('file')
    config.update(database=str(db), streams=[row], port=0)
    scripts['alpha'] = [('Alpha',67,4000+i*10) for i in range(6)]
    return SimpleNamespace(module=module,path=path,db=db,logs=logs,config=config,scripts=scripts,steps=steps,played=played)


def run(live, *extra, automatic=True):
    live.path.write_text(json.dumps(live.config))
    return live.module.main(['--config',str(live.path),'--log-root',str(live.logs),'--exit-after-capture',
                            *(['--automatic-characters'] if automatic else []),*extra])


@pytest.mark.parametrize('neural_level',[False,True])
def test_placeholder_discovers_name_and_unreadable_names_keep_numeric_tracking(live, monkeypatch, neural_level):
    live.config['streams'][0]['experimental_neural_level']=neural_level
    live.scripts['alpha'] = [('Alpha',67,4000),('Alpha',67,4010),(None,67,4020),
                             ('Alpha',67,4030),('Alpha',67,4040),('Alpha',67,4050)]
    observed = []
    real = live.module.shadow.capture_attempt
    def capture(args,source,requirements,index,*,seek=None,**options):
        assert source.kind=='twitch' and source.value=='alpha' and args.authorized and seek is None
        assert args.automatic_characters and args.character_names
        observed.append(id(options['resident']))
        return real(args,source,requirements,index,seek=seek,**options)
    monkeypatch.setattr(live.module.shadow,'capture_attempt',capture)
    assert run(live)==0
    rows = payloads(live.db,'alpha')
    assert 'identity_hold' in rows[0]
    assert rows[1]['automatic_selection']['name']=='Alpha' and rows[1]['current']
    assert rows[2]['current'] and original(rows[2])['character_name']['evidence']['name'] is None
    assert all(row['current'] for row in rows[1:])
    if neural_level:assert rows[1]['neural_level']['level']==67
    assert len(set(observed))==1
    with Store(live.db,read_only=True) as store:
        assert [r[0] for r in store.db.execute('SELECT label FROM characters ORDER BY id')]==['PendingOCR','Alpha']
        assert store.db.execute('SELECT COUNT(*) FROM automatic_character_events').fetchone()[0]==1
        assert store.db.execute('SELECT level FROM character_level_guard WHERE level IS NOT NULL').fetchone()[0]==67
        assert store.db.execute('SELECT COUNT(*) FROM retention_state').fetchone()[0]==0
        now=BASE+timedelta(seconds=365)
        history=Diagnostics(store).rolling_history('alpha',now=now)
        assert history['windows']['5']['gain'] and history['windows']['1440']['gain']
    marker=json.loads(live.db.with_suffix('.sqlite3.multi-alpha.json').read_text())
    assert marker['automatic_characters'] and marker['live_twitch_trial'] and marker['channels']==['alpha']
    assert len(list(live.logs.glob('*/alpha/**/capture.jsonl')))==2


def test_switch_back_reuses_ids_and_restart_preserves_selection_and_floor(live):
    live.scripts['alpha']=[('Alpha',67,4000),('Alpha',67,4010),('Beta',30,4000),('Beta',30,4010),
                           ('Alpha',67,4020),('Alpha',67,4030)]
    assert run(live)==0
    rows=payloads(live.db,'alpha')
    assert 'identity_hold' in rows[2] and 'identity_hold' in rows[4]
    assert [row['automatic_selection']['name'] for row in rows if 'automatic_selection' in row]==['Alpha','Beta','Alpha']
    with Store(live.db,read_only=True) as store:
        cid=store._channel('alpha')['selected_character_id']
        sid=store._open_session(store._channel('alpha')['id'])['id']
        assert store.db.execute('SELECT COUNT(*) FROM characters').fetchone()[0]==3
        assert store.db.execute('SELECT character_id FROM diagnostic_runs ORDER BY rowid DESC LIMIT 1').fetchone()[0]==cid
        old_alpha=store.db.execute("SELECT character_id FROM diagnostic_runs r JOIN characters c ON c.id=r.character_id WHERE c.label='Alpha' ORDER BY r.rowid LIMIT 1").fetchone()[0]
        assert old_alpha==cid
    live.scripts['alpha']=[('Alpha',67,4040)]
    live.config['streams'][0]['count']=2
    assert run(live)==0
    with Store(live.db,read_only=True) as store:
        assert store._channel('alpha')['selected_character_id']==cid
        assert store._open_session(store._channel('alpha')['id'])['id']==sid
        assert store.db.execute('SELECT COUNT(*) FROM characters').fetchone()[0]==3
        assert store.db.execute('SELECT level FROM character_level_guard WHERE character_id=?',(cid,)).fetchone()[0]==67
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
        assert store.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


def test_failed_stale_duplicate_and_multiple_hud_frames_cannot_confirm_switch(live):
    live.config['streams'][0]['count']=11
    live.scripts['alpha']=[('Alpha',67,4000),('Alpha',67,4010),('Beta',67,4020),'FAIL',
                           ('Beta',67,4030),('STALE','Beta',67,4040),('Alpha',67,4050),
                           ('Beta',67,4060),('DUPLICATE','Beta',67,4060),('MULTI','Beta',67,4070),('Alpha',67,4080)]
    assert run(live)==0
    rows=payloads(live.db,'alpha')
    assert len(rows)==11 and rows[3]['status']=='capture_failed'
    assert original(rows[5])['character_name']['evidence']['status']=='stale_local_frame'
    assert original(rows[8])['character_name']['suggestion']['latest_status']=='duplicate_frame'
    assert original(rows[9])['character_name']['evidence']['status']=='multiple_huds'
    assert rows[-1]['current']
    with Store(live.db,read_only=True) as store:
        assert store.db.execute('SELECT COUNT(*) FROM automatic_character_events').fetchone()[0]==1
        assert store.db.execute("SELECT COUNT(*) FROM characters WHERE label='Beta'").fetchone()[0]==0


def test_overnight_level_jump_requires_two_named_levels_and_keeps_history(live):
    live.config['streams'][0]['count']=2
    assert run(live)==0
    with Store(live.db,read_only=True) as store:
        cid=store._channel('alpha')['selected_character_id']
        sid=store._open_session(store._channel('alpha')['id'])['id']
    live.steps['alpha']=480  # Local receipt gap of roughly eight hours, no broadcast resets.
    live.scripts['alpha']=[('Alpha',70,1000),('Alpha',70,1010)]
    assert run(live)==0
    rows=payloads(live.db,'alpha')
    assert rows[2]['level_hold']['reason']=='level_confirmation_pending'
    assert rows[3]['current']
    with Store(live.db,read_only=True) as store:
        assert store._channel('alpha')['selected_character_id']==cid
        assert store._open_session(store._channel('alpha')['id'])['id']==sid
        assert store.db.execute('SELECT level FROM character_level_guard WHERE character_id=?',(cid,)).fetchone()[0]==70
        assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]==4


@pytest.mark.parametrize('case',['database','log-root','port','interval','authorization','workers','retention','cache','channels','mixed'])
def test_live_isolation_preflight_refuses_unsafe_settings_without_writes(live,case):
    extra=['--check']
    if case=='database':live.config['database']=str(live.db.parent.parent.parent/'main.sqlite3')
    if case=='log-root':extra+=['--log-root',str(live.path.parent.parent/'other-logs')]
    if case=='port':live.config['port']=8765
    if case=='interval':live.config['streams'][0]['interval']=15
    if case=='authorization':live.config['streams'][0]['authorized']=False
    if case=='workers':extra+=['--workers','2']
    if case=='retention':extra+=['--continuous','--retention-24h']
    if case=='cache':extra+=['--hud-cache-seconds','60']
    if case=='channels':live.config['streams'] += [dict(live.config['streams'][0],channel=c) for c in ('bravo','charlie')]
    if case=='mixed':live.config['streams'].append(dict(live.config['streams'][0],channel='bravo',source='file',file='unused.mp4'))
    assert run(live,*extra)==1
    assert not live.db.exists() and not live.logs.exists() and not live.steps


def test_check_is_read_only_and_port_collision_refuses_before_db_creation(live):
    assert run(live,'--check')==0
    assert not live.db.exists() and not live.logs.exists() and not live.steps
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as occupied:
        occupied.bind(('127.0.0.1',0));occupied.listen()
        live.config['port']=occupied.getsockname()[1]
        assert run(live)==1
    assert not live.db.exists() and not live.db.with_suffix('.sqlite3.multi-alpha.json').exists() and not live.steps


@pytest.mark.parametrize('kind',['unowned','nonautomatic','offline-automatic','old-schema'])
def test_trial_never_adopts_or_migrates_existing_database(live,kind):
    if kind=='old-schema':
        assert run(live)==0
        with sqlite3.connect(live.db) as db:db.execute('PRAGMA user_version=9')
    else:
        with Store(live.db):pass
        if kind!='unowned':
            live.db.with_suffix('.sqlite3.multi-alpha.json').write_text(json.dumps(dict(application=live.module.APP,
                **({'automatic_characters':True} if kind=='offline-automatic' else {}))))
    before=live.db.read_bytes();count=dict(live.steps)
    assert run(live,'--check')==1 and run(live)==1
    assert live.db.read_bytes()==before and live.steps==count


def test_coordinator_lease_and_sqlite_writer_lock_prevent_trial_writes(live):
    assert run(live)==0
    trial=dict(live_twitch_trial=True,database=str(live.db),channels=['alpha'])
    before=len(payloads(live.db,'alpha'));count=dict(live.steps)
    with live.module.ownership(live.db,automatic=True,trial=trial):
        assert run(live,'--check')==1 and run(live)==1
    with sqlite3.connect(live.db) as other:
        other.execute('BEGIN IMMEDIATE')
        assert run(live)==1
        other.rollback()
    assert len(payloads(live.db,'alpha'))==before and live.steps==count


def test_two_twitch_channels_use_separate_character_ids_and_floors(live):
    live.config['streams'].append(dict(live.config['streams'][0],channel='bravo'))
    live.scripts['bravo']=[('Alpha',40,1000+i*10) for i in range(6)]
    assert run(live)==0
    with Store(live.db,read_only=True) as store:
        ids=[store._channel(c)['selected_character_id'] for c in ('alpha','bravo')]
        assert len(set(ids))==2
        assert [store.db.execute('SELECT level FROM character_level_guard WHERE character_id=?',(cid,)).fetchone()[0]
                for cid in ids]==[67,40]
        for channel,level in (('alpha',67),('bravo',40)):
            rows=Diagnostics(store).snapshot(channel,now=BASE+timedelta(minutes=7))['observations']
            assert {row['assigned_channel'] for row in rows}=={channel}
            assert {row['visual_level'] for row in rows}=={level}


def test_standalone_twitch_name_preview_still_requires_authorization_and_no_db(live):
    shadow=live.module.shadow
    argv=['--channel','alpha','--character-names','--output',str(live.path.parent/'review.jsonl')]
    with pytest.raises(ValueError,match='authorized'):shadow.prepare(shadow.parser().parse_args(argv))
    source,*_=shadow.prepare(shadow.parser().parse_args([*argv,'--authorized']))
    assert source.kind=='twitch' and source.value=='alpha'


def test_trial_restart_cannot_silently_drop_automation_flags(live):
    assert run(live)==0
    count=dict(live.steps);before=len(payloads(live.db,'alpha'))
    assert run(live,'--check',automatic=False)==1
    assert run(live,automatic=False)==1
    assert live.steps==count and len(payloads(live.db,'alpha'))==before


def test_store_no_migration_guard_checks_inside_writer_transaction(live):
    with Store(live.db,allow_migration=False):pass
    with sqlite3.connect(live.db) as db:db.execute('PRAGMA user_version=9')
    before=live.db.read_bytes()
    with pytest.raises(ValueError,match='migration disabled'):Store(live.db,allow_migration=False)
    assert live.db.read_bytes()==before


def test_nonautomatic_twitch_keeps_existing_path_and_defaults(live,monkeypatch):
    live.config.update(database=str(live.db.parent/'nonautomatic.sqlite3'),port=0)
    live.config['streams'][0]['character']='Alpha'
    original_capture=live.module.shadow.capture_attempt
    def capture(args,*rest,**kwargs):
        assert not args.character_names and not args.automatic_characters and 'identity' not in kwargs
        return original_capture(args,*rest,**kwargs)
    monkeypatch.setattr(live.module.shadow,'capture_attempt',capture)
    assert run(live,automatic=False)==0
    db=live.db.parent/'nonautomatic.sqlite3'
    with Store(db,read_only=True) as store:
        assert store.db.execute('SELECT COUNT(*) FROM automatic_character_events').fetchone()[0]==0
        assert store.db.execute('SELECT COUNT(*) FROM character_level_guard').fetchone()[0]==0
    marker=json.loads(db.with_suffix('.sqlite3.multi-alpha.json').read_text())
    assert marker==dict(application=live.module.APP)
