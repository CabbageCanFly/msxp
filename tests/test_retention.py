"""Disposable synthetic evidence only: retention must preserve public arithmetic."""
from datetime import timedelta

import pytest

from exp_tracker import rolling_history
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.product import player
from exp_tracker.retention import prune,checkpoint
from exp_tracker.store import Store
from tests.test_product import tracking,NOW
from tests.test_diagnostic_history import config
from tests.test_tracked_exp_totals import save


def chain(d, count=8, first=0):
    if not first:d.append('run',dict(type='summary',trusted=False,attempts=0,interrupted=True))
    for n in range(first,first+count):
        rid=f'chain{n}'
        if n==0:d.begin(rid,'alpha',config(rid,interval=300))
        else:d.rotate(f'chain{n-1}',rid,'alpha',dict(type='summary',trusted=False,attempts=60,
            interrupted=False,completion_reason='scheduled_rotation',next_run_id=rid),config(rid,f'chain{n-1}',interval=300))
        for i in range(1,61):
            index=n*60+i-1
            level=64 if index<200 else 65
            save(d,rid,i,index*300,1000+index,missing=index%17==0,
                level=level,neural_level=dict(level=level,text=str(level),status='numeric_candidate',score=.99))
    return NOW+timedelta(seconds=((first+count)*60-1)*300)


def metrics(d,now):
    packet=d.rolling_history('alpha',now=now)
    return {k:packet[k] for k in ('tracked_exp','buckets','windows','current_level_windows','current_level',
        'coverage_seconds','unknown_seconds','chart_intervals','current_level_chart_intervals')}


def test_retention_parity_rotation_levelup_restart_and_inactivity(tracking):
    path,store,d=tracking;now=chain(d)
    before=metrics(d,now);shown=player(d.snapshot('alpha',now=now),now=now)
    count=store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]
    report=prune(store,now=now)
    assert report['attempts']>0 and store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]==count
    prune(store,now=now,dry_run=False)
    assert metrics(d,now)==before
    assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]<count
    assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
    late=now+timedelta(days=100)
    d.append('chain7',dict(type='summary',trusted=False,attempts=60,interrupted=False))
    prune(store,now=late,dry_run=False)
    assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]==0
    # A cold process still has an explicitly dated last-known character state.
    with Store(path,read_only=True) as cold:
        value=player(Diagnostics(cold).snapshot('alpha',now=late),now=late)
        assert value['reading']==shown['reading']
        assert value['display_level']['value']==shown['display_level']['value']
        assert value['stale']
        assert Diagnostics(cold).rolling_history('alpha',now=late)['tracked_exp'] is None
    with pytest.raises(ValueError,match='expired'):
        store.correct_manual('alpha','too-old',1,level=64,current_exp=10,effective_at=NOW)


def test_checkpoint_is_atomic_on_failure(tracking,monkeypatch):
    from exp_tracker import retention
    _,store,d=tracking;now=chain(d)
    before=store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]
    apply=retention._apply
    def fail(*args):
        apply(*args);raise ValueError('injected')  # After every write of the prefix, before its commit.
    monkeypatch.setattr(retention,'_apply',fail)
    with pytest.raises(ValueError,match='injected'):prune(store,now=now,dry_run=False)
    assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]==before
    assert not checkpoint(store,1)
    assert store._channel('alpha')['selected_character_id']==1
    monkeypatch.undo()
    # A later failure (trusted anchors) leaves committed prefixes whole: checkpoint and deletion together.
    monkeypatch.setattr(retention,'_trusted',lambda *args:(_ for _ in ()).throw(ValueError('trusted')))
    with pytest.raises(ValueError,match='trusted'):prune(store,now=now,dry_run=False)
    pruned=before-store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]
    assert pruned>0 and checkpoint(store,1)['through_run']
    assert not store.db.execute('PRAGMA foreign_key_check').fetchall()


def test_trusted_checkpoint_keeps_totals_anchor_and_monotonic_ids(tmp_path):
    from tests.test_store import reading,START
    from exp_tracker.glyphs import GlyphProfile,SYMBOLS
    from exp_tracker.models import Recognition
    calibration=GlyphProfile(9,{c:6 for c in SYMBOLS},{c:(1<<i,) for i,c in enumerate(SYMBOLS)})
    path=tmp_path/'trusted.sqlite3'
    with Store(path) as store:
        store.add_channel('alpha');cid=store.add_character('alpha','Mage');store.select_character('alpha',cid,at=START)
        session=store.start_session('alpha',at=START)
        for i in range(10):
            if i in (5,9):
                store.ingest('alpha',f'missing{i}',START+timedelta(seconds=i*30-15),Recognition('unreadable'),profile=calibration,session_id=session)
            last=store.ingest('alpha',str(i),START+timedelta(seconds=i*30),reading(1000+i*100),profile=calibration,session_id=session)
        before=store.state('alpha',as_of=START+timedelta(minutes=5))
        prune(store,now=START+timedelta(days=2),dry_run=False)
        after=store.state('alpha',as_of=START+timedelta(minutes=5))
        assert after['last_trusted']==before['last_trusted']
        assert after['observed_session_exp']==before['observed_session_exp']==900
        assert after['bridged_session_exp']==before['bridged_session_exp']==200
        assert after['original_accounting']['bridged_session_exp']==200
        assert store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==1
        new=store.ingest('alpha','new',START+timedelta(days=2),reading(2100),profile=calibration,session_id=session)
        assert new['id']>last['id']
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall()


def test_corrections_and_invalidation_audit_survive_expiry(tracking):
    from tests.test_invalidations import apply,single
    from exp_tracker.invalidations import Invalidations
    _,store,d=tracking;now=chain(d)
    old=store.correct_manual('alpha','old',1,level=64,current_exp=1000,
        effective_at=NOW+timedelta(seconds=300),kind='point',target_kind='diagnostic',target_event_id='chain0:2')
    expired=apply(store,single(store,'chain0:3'))
    recent=apply(store,single(store,'chain7:57'))
    before=metrics(d,now)
    audit=[tuple(r) for r in store.db.execute('SELECT * FROM reading_events')]
    prune(store,now=now,dry_run=False)
    assert metrics(d,now)==before
    assert [tuple(r) for r in store.db.execute('SELECT * FROM reading_events')]==audit
    with pytest.raises(ValueError,match='expired'):d.begin('chain0','alpha',config('chain0',interval=300))
    listed=Invalidations(store).excluded('alpha',1)['readings']
    assert any(r.get('expired') and r['original'] is None for r in listed)
    with pytest.raises(ValueError,match='expired'):store.retract_manual('alpha','undo-old',old['id'],reason='Too late')
    with pytest.raises(ValueError,match='expired'):
        apply(store,dict(action='restore',batch_id=expired['id']))
    apply(store,dict(action='restore',batch_id=recent['id']))
    target=store.correct_manual('alpha','recent',1,level=65,current_exp=12345,
        effective_at=NOW+timedelta(seconds=478*300),kind='point',target_kind='diagnostic',target_event_id='chain7:59')
    store.retract_manual('alpha','undo-recent',target['id'],reason='Synthetic undo')
    assert not store.db.execute('PRAGMA foreign_key_check').fetchall()


def test_expired_attempt_ids_cannot_alias_audit_and_restart_retains_identity(tracking):
    from tests.test_invalidations import apply,single
    _,store,d=tracking;now=chain(d)
    apply(store,single(store,'chain7:59'))
    high=store.db.execute('SELECT MAX(id) FROM diagnostic_attempts').fetchone()[0]
    d.append('chain7',dict(type='summary',trusted=False,attempts=60,interrupted=True))
    late=now+timedelta(days=90)
    prune(store,now=late,dry_run=False)
    d.begin('restart','alpha',config('restart',interval=20))
    save(d,'restart',1,int((late-NOW).total_seconds()),1500,level=65)
    assert store.db.execute('SELECT MAX(id) FROM diagnostic_attempts').fetchone()[0]>high
    snap=d.snapshot('alpha',now=late)
    assert not snap['observations'][0].get('reading_invalidated')
    assert snap['selected_character']['label']=='Test character'
    assert d.rolling_history('alpha',now=late)['tracked_exp'] is None


def test_active_runs_are_not_pruned(tracking):
    _,store,d=tracking;now=chain(d)
    count=store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]
    report=prune(store,now=now+timedelta(days=2),dry_run=False,active_runs={'chain0','chain7'})
    assert report['attempts']==0
    assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]==count


def test_artifact_cleanup_is_owned_bounded_and_preserves_active_and_unknown_files(tracking,tmp_path):
    import os
    import json
    from exp_tracker.retention_files import own,cleanup,register,OperatorLog
    path,store,d=tracking
    root=tmp_path/'logs';directory=root/'process';directory.mkdir(parents=True)
    own(directory,path)
    run=directory/'alpha'/'old'/'capture.jsonl';run.parent.mkdir(parents=True)
    run.write_text(json.dumps(dict(type='configuration',run_id='expired'))+'\n')
    crop=run.with_suffix('')/'0001'/'exp.png';crop.parent.mkdir(parents=True);crop.write_bytes(b'synthetic')
    untouched=directory/'notes.txt';untouched.write_text('Keep')
    unowned=root/'unowned'/'operator.jsonl';unowned.parent.mkdir();unowned.write_text('{}\n')
    now=NOW+timedelta(days=10)
    for file in (run,crop,unowned):os.utime(file,(NOW.timestamp(),NOW.timestamp()))
    report=cleanup(root,path,store,now=now)
    assert report['files']==2 and run.exists() and crop.exists()
    cleanup(root,path,store,now=now,dry_run=False,active_logs=[run])
    assert run.exists() and crop.exists()
    cleanup(root,path,store,now=now,dry_run=False)
    assert not run.exists() and not crop.exists() and untouched.exists() and unowned.exists()
    clock=[NOW]
    with OperatorLog(directory,clock=lambda:clock[0]) as log:
        log.write('first\n');log.flush();first=log.path
        clock[0]+=timedelta(hours=1);log.write('second\n');log.flush()
        assert first!=log.path and first.read_text()=='first\n'
    assert log.path.read_text()=='second\n'


def test_dry_run_cli_never_migrates_schema_seven(tmp_path,capsys):
    import sqlite3
    from exp_tracker import schema
    from exp_tracker.retention import main
    path=tmp_path/'old.sqlite3'
    with sqlite3.connect(path) as db:
        for statement in (*schema.STATEMENTS,*schema.MIGRATION_2,*schema.MIGRATION_3,*schema.MIGRATION_4,
                *schema.MIGRATION_5,*schema.MIGRATION_6,*schema.MIGRATION_7):db.execute(statement)
        db.execute('PRAGMA user_version=7')
    before=path.read_bytes()
    assert main(['--db',str(path)])==0
    assert path.read_bytes()==before
    assert '"dry_run": true' in capsys.readouterr().out


def test_independent_last_full_exp_and_saved_pace_survive_percentage_only_and_failures(tracking):
    _,store,d=tracking
    for i in range(1,8):save(d,'run',i,(i-1)*20,3300+i*5,full=i<6,missing=i==7,
        neural_level=dict(level=64,text='64',status='numeric_candidate',score=.99))
    now=NOW+timedelta(seconds=120)
    before=d.directory({},now=now)['streams'][0]
    d.append('run',dict(type='summary',trusted=False,attempts=7,interrupted=True))
    later=NOW+timedelta(days=50)
    prune(store,now=later,dry_run=False)
    value=d.directory({},now=later)['streams'][0]
    assert value['player']['reading']==before['player']['reading']
    assert value['full_exp']==before['full_exp']
    assert value['percentage']==before['percentage']
    assert value['player']['responsive_pace']['total_gain']==before['player']['responsive_pace']['total_gain']
    assert value['player']['recent_windows']['5']['available'] is False
    assert value['player']['recent_windows']['5']['last_observed_pace'] is not None


def test_each_character_keeps_its_own_state_across_sessions(tracking):
    _,store,d=tracking
    save(d,'run',1,0,3300,neural_level=dict(level=64,text='64',status='numeric_candidate',score=.99))
    d.append('run',dict(type='summary',trusted=False,attempts=1,interrupted=True))
    other=store.add_character('alpha','Other character')
    store.select_character('alpha',other,at=NOW+timedelta(seconds=20));store.start_session('alpha',at=NOW+timedelta(seconds=20))
    d.begin('other','alpha',config('other'))
    save(d,'other',1,40,2500,level=80,neural_level=dict(level=80,text='80',status='numeric_candidate',score=.99))
    d.append('other',dict(type='summary',trusted=False,attempts=1,interrupted=True))
    later=NOW+timedelta(days=50)
    prune(store,now=later,dry_run=False)
    assert store._channel('alpha')['selected_character_id']==other
    current=player(d.snapshot('alpha',now=later),now=later)
    assert current['character']['label']=='Other character' and current['display_level']['value']==80
    store.select_character('alpha',1,at=later);store.start_session('alpha',at=later)
    old=player(d.snapshot('alpha',now=later),now=later)
    assert old['character']['label']=='Test character' and old['display_level']['value']==64
    assert old['reading']['percentage']=='33.00'
    assert d.rolling_history('alpha',now=later)['tracked_exp'] is None


def test_trusted_invalidation_checkpoint_preserves_revised_and_original_totals(tmp_path):
    from tests.test_store import reading,START
    from tests.test_invalidations import apply,single
    from exp_tracker.glyphs import GlyphProfile,SYMBOLS
    calibration=GlyphProfile(9,{c:6 for c in SYMBOLS},{c:(1<<i,) for i,c in enumerate(SYMBOLS)})
    with Store(tmp_path/'trusted-invalid.sqlite3') as store:
        store.add_channel('alpha');cid=store.add_character('alpha','Mage');store.select_character('alpha',cid,at=START)
        session=store.start_session('alpha',at=START)
        for i in range(10):
            last=store.ingest('alpha',str(i),START+timedelta(seconds=i*30),reading(1000+i*100),profile=calibration,session_id=session)
        apply(store,single(store,last['id'],kind='observation'))
        now=START+timedelta(days=2)
        before=store.state('alpha',as_of=now)
        prune(store,now=now,dry_run=False)
        after=store.state('alpha',as_of=now)
        assert after['last_trusted']==before['last_trusted']
        assert after['observed_session_exp']==before['observed_session_exp']==800
        assert after['original_accounting']['observed_session_exp']==before['original_accounting']['observed_session_exp']==900
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall()


def test_publisher_heads_and_live_checkpoints_change_on_retention(tracking):
    _,store,d=tracking;now=chain(d)
    cache={}
    before=d.rolling_history('alpha',now=now,checkpoints=cache)
    head=tuple(d.heads()[0])
    prune(store,now=now,dry_run=False)
    assert tuple(d.heads()[0])!=head
    assert metrics(d,now)=={k:before[k] for k in metrics(d,now)}
    full=d.rolling_history('alpha',now=now)
    assert d.rolling_history('alpha',now=now,checkpoints=cache)==full


def both(d,now,checkpoints=None):
    return d.rolling_history('alpha',now=now,checkpoints=checkpoints),d.recent_snapshot('alpha',now=now,checkpoints=checkpoints)


def test_live_checkpoints_resume_across_a_fold_instead_of_replaying_every_run(tracking,monkeypatch):
    _,store,d=tracking;now=chain(d);cache={};character=store._channel('alpha')['selected_character_id']
    prune(store,now=now,dry_run=False);both(d,now,cache)  # Checkpoints from the first floor on.
    later=chain(d,count=4,first=8);both(d,later,cache)
    floor=checkpoint(store,character)['through_run']
    prune(store,now=later,dry_run=False)
    assert checkpoint(store,character)['through_run']>floor
    seen=[];original=rolling_history.run_rows
    monkeypatch.setattr(rolling_history,'run_rows',lambda *a,**k:seen.append(a[2]['run_id']) or original(*a,**k))
    fast=both(d,later,cache)
    assert seen==['chain11','chain11']  # Only the open run: folded and settled runs are not replayed.
    seen.clear();assert fast==both(d,later)  # Totals, windows, paces, ETAs and receipts as a full replay.
    assert len(seen)>2
    assert both(d,later+timedelta(minutes=5),cache)==both(d,later+timedelta(minutes=5))


def test_a_fold_past_the_whole_checkpoint_replays_in_full(tracking):
    _,store,d=tracking;now=chain(d);cache={}
    prune(store,now=now,dry_run=False);both(d,now,cache)
    later=chain(d,count=8,first=8)  # 40 h on: every checkpointed run has expired.
    prune(store,now=later,dry_run=False)
    assert both(d,later,cache)==both(d,later)


def test_pending_loss_at_expired_rotation_boundary_matches_full_causal_replay(tracking):
    _,store,d=tracking
    d.append('run',dict(type='summary',trusted=False,attempts=0,interrupted=True))
    for n in range(3):
        rid=f'pending{n}'
        if n==0:d.begin(rid,'alpha',config(rid,interval=20))
        else:d.rotate(f'pending{n-1}',rid,'alpha',dict(type='summary',trusted=False,attempts=60,
            interrupted=False,completion_reason='scheduled_rotation',next_run_id=rid),config(rid,f'pending{n-1}',interval=20))
        for i in range(1,61):
            index=n*60+i-1
            save(d,rid,i,index*20,3300+index*5-(150 if index>=119 else 0),
                neural_level=dict(level=64,text='64',status='numeric_candidate',score=.99))
    now=NOW+timedelta(hours=24,minutes=5,seconds=2390)
    before=metrics(d,now)
    prune(store,now=now,dry_run=False)
    assert checkpoint(store,1)['tracked']['percentage_state']['pending'] is not None
    assert metrics(d,now)==before


def test_new_reading_does_not_revive_an_expired_transition_hint(tracking):
    _,_,d=tracking
    save(d,'run',1,0,3300,neural_level=dict(level=64,text='64',status='numeric_candidate',score=.99))
    snap=d.snapshot('alpha',now=NOW)
    snap['observations'][-1]['experimental_level'].pop('level_context',None)
    snap['retention_display']={'level_context':{'transition':{'phase':'possible','to_level':65}}}
    result=player(snap,now=NOW)
    assert result['display_level']['value']==64 and result['level_context'] is None


def test_mixed_expired_batch_disables_whole_restore_and_keeps_individual_restore(tracking):
    from tests.test_invalidations import apply,single
    from exp_tracker.invalidations import Invalidations
    _,store,d=tracking
    save(d,'run',1,0,3300);save(d,'run',2,20,3305)
    d.append('run',dict(type='summary',trusted=False,attempts=2,interrupted=False))
    d.begin('later','alpha',config('later'))
    save(d,'later',1,10800,3400);save(d,'later',2,10820,3405)
    batch=apply(store,dict(action='invalidate',start=NOW.isoformat(),end=(NOW+timedelta(hours=4)).isoformat()))
    service=Invalidations(store)
    assert service.history('alpha',1)['batches'][0]['expired_count']==0
    prune(store,now=NOW+timedelta(hours=25),dry_run=False)
    history=service.history('alpha',1)['batches'][0]
    assert history['expired_count']==2 and history['remaining']==4
    readings=service.excluded('alpha',1)['readings']
    assert sum(r['expired'] for r in readings)==2
    assert sum(not r['expired'] for r in readings)==2
    with pytest.raises(ValueError,match='expired'):apply(store,dict(action='restore',batch_id=batch['id']))
    apply(store,single(store,'later:1','restore'))
    history=service.history('alpha',1)['batches'][0]
    assert history['action']=='restore'
    original=next(r for r in service.history('alpha',1)['batches'] if r['id']==batch['id'])
    assert original['remaining']==3 and original['expired_count']==2


def test_retained_trusted_fk_anchor_is_still_expired_for_admin(tracking):
    from tests.test_store import reading
    from tests.test_invalidations import apply,single
    from exp_tracker.glyphs import GlyphProfile,SYMBOLS
    from exp_tracker.invalidations import Invalidations
    _,store,d=tracking
    calibration=GlyphProfile(9,{c:6 for c in SYMBOLS},{c:(1<<i,) for i,c in enumerate(SYMBOLS)})
    session=store.state('alpha')['session']['id']
    first=store.ingest('alpha','old1',NOW,reading(),profile=calibration,session_id=session)
    last=store.ingest('alpha','old2',NOW+timedelta(seconds=20),reading(1100),profile=calibration,session_id=session)
    apply(store,single(store,last['id'],kind='observation'))
    prune(store,now=NOW+timedelta(days=3),dry_run=False)
    assert store.db.execute('SELECT 1 FROM observations WHERE id=?',(last['id'],)).fetchone()
    service=Invalidations(store)
    original=service.excluded('alpha',1)['readings'][0]
    assert original['original'] is not None and original['expired']
    assert service.history('alpha',1)['batches'][0]['expired_count']==1
    from exp_tracker.admin_server import details
    assert all(r['expired'] for r in details(store,'alpha','1')['readings'])


def test_repeated_rotations_pruning_and_cold_writers_match_unpruned_reference(tracking,tmp_path):
    path,store,d=tracking;now=chain(d)
    with Store(tmp_path/'reference.sqlite3') as reference:
        store.db.backup(reference.db)
        golden=Diagnostics(reference)
        prune(store,now=now,dry_run=False)
        for number in (8,9):
            # Reopen between retention cycles; both sides receive the same new evidence.
            with Store(path) as cold:
                current=Diagnostics(cold)
                for target in (current,golden):
                    target.rotate(f'chain{number-1}',f'chain{number}','alpha',dict(type='summary',trusted=False,attempts=60,
                        interrupted=False,completion_reason='scheduled_rotation',next_run_id=f'chain{number}'),
                        config(f'chain{number}',f'chain{number-1}',interval=300))
                    for i in range(1,61):
                        index=number*60+i-1
                        save(target,f'chain{number}',i,index*300,1000+index,level=65,missing=index%17==0,
                            neural_level=dict(level=65,text='65',status='numeric_candidate',score=.99))
                now=NOW+timedelta(seconds=((number+1)*60-1)*300)
                before=metrics(golden,now)
                prune(cold,now=now,dry_run=False)
                assert metrics(current,now)==before
                actual=current.directory({},now=now)['streams'][0]['player']
                expected=golden.directory({},now=now)['streams'][0]['player']
                assert actual['reading']==expected['reading'] and actual['display_level']==expected['display_level']
                assert not cold.db.execute('PRAGMA foreign_key_check').fetchall()
