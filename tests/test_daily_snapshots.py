"""Daily storage uses only synthetic source readings and never supplies live evidence."""
from datetime import datetime,timedelta,timezone
import sqlite3

import pytest

from exp_tracker.diagnostics import Diagnostics
from exp_tracker.retention import prune,checkpoint
from exp_tracker.store import Store,utc
from tests.test_product import tracking,NOW
from tests.test_tracked_exp_totals import save
from tests.test_diagnostic_history import config
from tests.test_invalidations import apply,single
from tests.test_store import profile,reading as recognition
from tests.test_retention import metrics


def observed(d,run,index,when,*,bp=3300,level=64,**changes):
    changes.setdefault('neural_level',dict(level=level,text=str(level),status='numeric_candidate',score=.99))
    save(d,run,index,int((when-NOW).total_seconds()),bp,level=level,
        **changes)


def close(d,run,count):
    d.append(run,dict(type='summary',trusted=False,attempts=count,interrupted=False))


def daily(store):
    return [dict(r) for r in store.db.execute('SELECT * FROM daily_character_exp ORDER BY character_id,utc_date')]


def test_utc_midnight_last_usable_percentage_and_empty_days(tracking):
    _,store,d=tracking
    times=[NOW+timedelta(hours=23),NOW+timedelta(hours=23,minutes=42),NOW+timedelta(hours=23,minutes=50),
        NOW+timedelta(hours=23,minutes=55),NOW+timedelta(days=1,seconds=5),NOW+timedelta(days=2,hours=12)]
    for i,when in enumerate(times,1):
        observed(d,'run',i,when,bp=3300+i*5,level=65 if i==5 else 64,full=i!=2,missing=i in (4,6))
    apply(store,single(store,'run:3'));close(d,'run',6)
    prune(store,now=NOW+timedelta(days=6))
    assert daily(store)==[]  # Reporting never writes snapshots.
    prune(store,now=NOW+timedelta(days=6),dry_run=False)
    first,second=daily(store)
    assert first['utc_date']=='2026-01-01' and first['observed_at']==utc(times[1])
    assert first['level']==64 and first['current_exp'] is None and first['percentage_bp']==3310
    assert first['exp_basis'] is None and first['percentage_basis']=='strict_percentage_only'
    assert second['utc_date']=='2026-01-02' and second['observed_at']==utc(times[4])
    assert second['level']==65 and second['current_exp'] is not None
    assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]==0


def test_later_cycle_and_cold_restart_replace_same_day_only_with_later_reading(tracking):
    path,store,d=tracking
    observed(d,'run',1,NOW,bp=3300);observed(d,'run',2,NOW+timedelta(minutes=5),bp=3305);close(d,'run',2)
    d.begin('late','alpha',config('late'))
    observed(d,'late',1,NOW+timedelta(hours=23,minutes=40),bp=3400)
    observed(d,'late',2,NOW+timedelta(hours=23,minutes=42),bp=3405);close(d,'late',2)
    first_now=NOW+timedelta(days=1,hours=12)
    before=metrics(d,first_now)
    prune(store,now=first_now,dry_run=False)
    assert metrics(d,first_now)==before
    assert daily(store)[0]['observed_at']==utc(NOW+timedelta(minutes=5))
    with Store(path) as cold:
        now=NOW+timedelta(days=3)
        expected=metrics(Diagnostics(cold),now)
        prune(cold,now=now,dry_run=False)
        assert metrics(Diagnostics(cold),now)==expected
        rows=daily(cold)
        assert len(rows)==1 and rows[0]['observed_at']==utc(NOW+timedelta(hours=23,minutes=42))
        prune(cold,now=now+timedelta(days=90),dry_run=False)
        assert daily(cold)==rows
        assert not cold.db.execute('PRAGMA foreign_key_check').fetchall()


def test_identity_rename_archived_character_and_timezone_offset(tracking):
    _,store,d=tracking
    stamp=NOW+timedelta(hours=23,minutes=42)
    local=stamp.astimezone(timezone(timedelta(hours=-4))).isoformat()
    observed(d,'run',1,stamp,attempted_at=local,received_at=local);close(d,'run',1)
    other=store.add_character('alpha','Other')
    store.select_character('alpha',other,at=NOW+timedelta(days=1));store.start_session('alpha',at=NOW+timedelta(days=1))
    d.begin('other','alpha',config('other'))
    observed(d,'other',1,NOW+timedelta(days=1,hours=12),level=80);close(d,'other',1)
    prune(store,now=NOW+timedelta(days=5),dry_run=False)
    rows=daily(store)
    assert [(r['character_id'],r['utc_date'],r['level']) for r in rows]==[(1,'2026-01-01',64),(other,'2026-01-02',80)]
    assert rows[0]['observed_at']==utc(stamp)
    store.rename_character('alpha',1,'Renamed',reason='Synthetic rename')
    store.select_character('alpha',1,at=NOW+timedelta(days=100));store.start_session('alpha',at=NOW+timedelta(days=100))
    prune(store,now=NOW+timedelta(days=101),dry_run=False)
    assert daily(store)==rows and store._channel('alpha')['selected_character_id']==1
    assert checkpoint(store,1)['display']['reading']['timestamp']==stamp.isoformat()


def test_manual_point_is_archived_but_standalone_baseline_and_bad_capture_are_not(tracking):
    _,store,d=tracking
    observed(d,'run',1,NOW+timedelta(hours=10))
    observed(d,'run',2,NOW+timedelta(hours=11))
    store.correct_manual('alpha','point',1,level=65,percentage_bp=500,
        effective_at=NOW+timedelta(hours=11),kind='point',target_kind='diagnostic',target_event_id='run:2')
    observed(d,'run',3,NOW+timedelta(hours=12),current=False)
    observed(d,'run',4,NOW+timedelta(hours=13),localization=dict(count=2))
    anchors={name:dict(text=name.upper(),y=y,height=height) for name,y,height in
        (('hp',100,15),('mp',105,8),('exp',105,8),('lv',110,8))}
    observed(d,'run',5,NOW+timedelta(hours=14),exp_crop_box=[0,100,100,110],
        localization=dict(count=1,candidates=[dict(anchor_step=100,anchors=anchors)]))
    observed(d,'run',6,NOW+timedelta(hours=15));apply(store,single(store,'run:6'))
    close(d,'run',6)
    store.correct_manual('alpha','baseline',1,level=70,current_exp=12345,effective_at=NOW+timedelta(days=1))
    prune(store,now=NOW+timedelta(days=4),dry_run=False)
    row,=daily(store)
    assert row['observed_at']==utc(NOW+timedelta(hours=11))
    assert row['source']=='manual_correction' and row['level_basis']=='manual_admin'
    assert row['level']==65 and row['current_exp'] is None and row['percentage_bp']==500


def test_trusted_replay_excludes_invalidated_latest_and_keeps_manual_fix_of_rejected_source(tracking,profile):
    _,store,d=tracking
    from exp_tracker.models import Recognition
    session=store.state('alpha')['session']['id']
    for i in (1,2):
        store.ingest('alpha',f'ocr{i}',NOW+timedelta(hours=i),recognition(1000*i),profile=profile,session_id=session)
    rejected=store.ingest('alpha','missing',NOW+timedelta(hours=3),Recognition('unreadable'),profile=profile,session_id=session)
    store.correct_manual('alpha','fix',1,level=60,current_exp=34567,effective_at=NOW+timedelta(hours=3),
        kind='point',target_kind='observation',target_event_id=str(rejected['id']))
    last=store.ingest('alpha','invalid',NOW+timedelta(hours=4),recognition(5000),profile=profile,session_id=session)
    apply(store,single(store,last['id'],kind='observation'))
    # At the same actual time, the explicit operator fix wins over diagnostic OCR.
    observed(d,'run',1,NOW+timedelta(hours=3));close(d,'run',1)
    prune(store,now=NOW+timedelta(days=3),dry_run=False)
    row,=daily(store)
    assert row['observed_at']==utc(NOW+timedelta(hours=3)) and row['current_exp']==34567
    assert row['source']=='manual_correction' and row['percentage_basis']=='derived_from_manual_exp'


def test_snapshots_are_atomic_with_deletion(tracking,monkeypatch):
    _,store,d=tracking
    observed(d,'run',1,NOW);close(d,'run',1)
    def fail(*args):
        assert daily(store) and store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]==0
        raise ValueError('after deletion')
    monkeypatch.setattr('exp_tracker.retention._trusted',fail)
    with pytest.raises(ValueError,match='after deletion'):prune(store,now=NOW+timedelta(days=3),dry_run=False)
    assert daily(store)==[] and not checkpoint(store,1)
    assert store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts').fetchone()[0]==1
    assert store.db.execute('SELECT revision FROM retention_meta').fetchone()[0]==0


def test_snapshots_never_supply_public_or_trusted_metrics(tracking):
    _,store,d=tracking
    observed(d,'run',1,NOW);close(d,'run',1)
    now=NOW+timedelta(days=3)
    prune(store,now=now,dry_run=False)
    d.begin('live','alpha',config('live'))
    observed(d,'live',1,now,bp=3400);observed(d,'live',2,now+timedelta(seconds=20),bp=3405)
    now+=timedelta(seconds=20)
    public=d.directory({},now=now);rolling=metrics(d,now);trusted=store.state('alpha',as_of=now)
    store.db.execute('UPDATE daily_character_exp SET level=199,current_exp=9223372036854775807,percentage_bp=9999')
    assert d.directory({},now=now)==public and metrics(d,now)==rolling and store.state('alpha',as_of=now)==trusted


def test_schema_eight_upgrade_is_additive_and_readers_do_not_migrate(tmp_path):
    from exp_tracker import schema
    path=tmp_path/'schema8.sqlite3'
    with sqlite3.connect(path) as db:
        for statement in (*schema.STATEMENTS,*schema.MIGRATION_2,*schema.MIGRATION_3,*schema.MIGRATION_4,
                *schema.MIGRATION_5,*schema.MIGRATION_6,*schema.MIGRATION_7,*schema.MIGRATION_8):db.execute(statement)
        db.execute('PRAGMA user_version=8')
    before=path.read_bytes()
    with Store(path,read_only=True) as store:assert store.schema_version==8
    assert before==path.read_bytes()
    with Store(path) as store:
        assert store.schema_version==9 and daily(store)==[]
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall()


@pytest.mark.parametrize('full',[True,False])
def test_inferred_level_is_labelled_and_percentage_only_does_not_invent_exp(tracking,full):
    _,store,d=tracking
    for i in range(1,4):
        observed(d,'run',i,NOW+timedelta(seconds=i*20),bp=3300+i*5,full=full,visual_level=None,neural_level=None)
    close(d,'run',3)
    prune(store,now=NOW+timedelta(days=3),dry_run=False)
    row,=daily(store)
    if full:
        assert row['level']==64 and row['level_basis']=='exp_derived' and row['current_exp'] is not None
    else:
        assert row['level'] is None and row['current_exp'] is None and row['percentage_bp']==3315
        assert row['exp_basis'] is None


def test_existing_supported_conditional_recovery_is_archived_as_experimental(tracking):
    _,store,d=tracking
    observed(d,'run',1,NOW,bp=2263,level=67)
    observed(d,'run',2,NOW+timedelta(seconds=20),bp=2269,level=67)
    observed(d,'run',3,NOW+timedelta(seconds=40),bp=2282,level=67,
        candidate=None,neural=dict(text='401.128122.82X1'),status='malformed_or_unavailable',visual_level=None,neural_level=None)
    close(d,'run',3)
    prune(store,now=NOW+timedelta(days=3),dry_run=False)
    row,=daily(store)
    assert row['observed_at']==utc(NOW+timedelta(seconds=40))
    assert row['current_exp']==401128 and row['percentage_bp']==2282
    assert row['level_basis']=='conditional_context'
    assert row['source']=='diagnostic' and row['exp_basis']==row['percentage_basis']=='conditional_symbol'
