from copy import deepcopy
from datetime import datetime,timedelta,timezone
from fractions import Fraction
import json
import sqlite3

import pytest

from exp_tracker.diagnostic_evidence import project
from exp_tracker.diagnostic_percentage import review
from exp_tracker.diagnostic_progress import percentage_point
from exp_tracker.product import fraction,history
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.store import Store
from tests.test_product import tracking,append,NOW
from tests.test_diagnostic_progress import row
from tests.test_cross_level_product import expected_net
from tests.test_diagnostic_history import config,fill,rotate


def test_streamed_evidence_and_quarantine_match_full_projection():
    rows=[row(i+1,p,frame_sha256=f'{i:064x}') for i,p in enumerate(
        ['75.00','75.05','74.00','74.05','74.10','74.15','25.00']+['25.01']*100+['74.20','74.25'])]
    before=deepcopy(rows);now=NOW+timedelta(seconds=2000)
    full=project(rows);expected=review(full,[percentage_point(r) for r in full],now=now)
    for size in (1,3,17,60):
        level_state={};percentage_state={};actual=[];projected=[]
        for i in range(0,len(rows),size):
            batch=project(rows[i:i+size],state=level_state);projected+=batch
            actual+=review(batch,[percentage_point(r) for r in batch],now=now,state=percentage_state)
        assert projected==full
        assert [(r['public_eligible'],r['progress_eligible'],r['break_before']) for r in actual]==[(r['public_eligible'],r['progress_eligible'],r['break_before']) for r in expected]
    assert rows==before


def test_totals_include_supported_gap_endpoints_but_percentage_lines_keep_the_gap(tracking):
    path,store,d=tracking
    for i,p in enumerate(('33.00','33.00',None,'33.10','33.15'),1):
        append(d,i,f'[{p}%]' if p else None,**(dict(status='capture_failed',received_at=None,current=False) if not p else {}))
    now=NOW+timedelta(seconds=60)
    result=d.rolling_history('alpha',now=now)
    gains=[r['gain'] for r in history(d.snapshot('alpha',now=now)) if r['gain']]
    # The old adjacent-only chart does not subtract across the failed capture.
    assert len(gains)==2
    assert fraction(result['tracked_exp'])==expected_net(d.snapshot('alpha',now=now),now)
    assert result['intervals']==3 and result['coverage_seconds']['approximate']==60
    assert sum(fraction(b['value']) for b in result['buckets'] if b['value'])==fraction(result['tracked_exp'])
    assert any(b['value'] is None for b in result['buckets']) and len(result['buckets'])==48
    assert not store.db.execute('select 1 from observations').fetchone()
    with Store(path,read_only=True) as restarted:
        assert Diagnostics(restarted).rolling_history('alpha',now=now)==result


@pytest.mark.parametrize('gap', [3600, 3601, 7200])
def test_chart_buckets_exclude_only_gains_over_one_hour_without_changing_totals(tracking, gap):
    _,_,d=tracking
    append(d,1,'[33.00%]')
    for index,seconds,pct in ((2,gap,'34.00'),(3,gap+15,'34.01')):
        stamp=(NOW+timedelta(seconds=seconds)).isoformat()
        append(d,index,f'[{pct}%]',attempted_at=stamp,received_at=stamp)
        if index==2 and gap>3600:
            resumed=d.rolling_history('alpha',now=NOW+timedelta(seconds=seconds))
            assert any(b['value'] is not None and b['chart_value'] is None for b in resumed['buckets'])
    result=d.rolling_history('alpha',now=NOW+timedelta(seconds=gap+15))
    total=sum((fraction(b['value']) for b in result['buckets'] if b['value'] is not None),Fraction(0))
    plotted=sum((fraction(b['chart_value']) for b in result['buckets'] if b['chart_value'] is not None),Fraction(0))
    assert total==fraction(result['tracked_exp']) and total>10000
    assert plotted==(total if gap==3600 else 150)


def test_rolling_edges_do_not_prorate_unknown_gain_or_freeze_to_old_capture(tracking):
    _,_,d=tracking
    for i in range(1,5):append(d,i,f'[33.{i:02}%]')
    result=d.rolling_history('alpha',now=NOW+timedelta(days=1,seconds=7))
    assert result['boundary_intervals_excluded']==0 and result['intervals']==3
    assert result['start']==(NOW+timedelta(seconds=7)).isoformat()
    later=d.rolling_history('alpha',now=NOW+timedelta(days=2))
    assert later['tracked_exp'] is None and later['coverage_seconds']['approximate']==0
    assert all(b['state']=='missing' for b in later['buckets'])


def test_manual_restart_gap_and_same_character_sessions_never_create_intervals(tracking):
    _,store,d=tracking
    for i,p in enumerate(('33.00','33.05','33.10'),1):append(d,i,f'[{p}%]')
    first=d.rolling_history('alpha',now=NOW+timedelta(seconds=30))
    config_row=json.loads(store.db.execute('select configuration_json from diagnostic_runs').fetchone()[0])
    d.begin('manual','alpha',config_row)
    from tests.test_diagnostics import attempt
    for i in (1,2):
        r=attempt(i);r.update(attempted_at=(NOW+timedelta(seconds=600+i*15)).isoformat(),received_at=(NOW+timedelta(seconds=600+i*15)).isoformat(),
            neural=dict(text=f'[34.{i:02}%]'),candidate=None,visual_level=64,neural_level=None,visual_status='available',status='diagnostic_percentage_only',localization=dict(count=1))
        d.append('manual',r)
    result=d.rolling_history('alpha',now=NOW+timedelta(seconds=630))
    assert result['intervals']==4 and result['coverage_seconds']['approximate']==630
    assert fraction(result['tracked_exp'])==expected_net(d.recent_snapshot('alpha',now=NOW+timedelta(seconds=630)),NOW+timedelta(seconds=630))
    store.end_session('alpha',at=NOW+timedelta(seconds=631));store.start_session('alpha',at=NOW+timedelta(seconds=632))
    assert d.rolling_history('alpha',now=NOW+timedelta(seconds=633))['tracked_exp']==result['tracked_exp']
    other=store.add_character('alpha','Other');store.end_session('alpha',at=NOW+timedelta(seconds=634));store.select_character('alpha',other);store.start_session('alpha',at=NOW+timedelta(seconds=635))
    assert d.rolling_history('alpha',now=NOW+timedelta(seconds=636))['tracked_exp'] is None


def test_more_than_640_attempts_and_clean_rotations_are_streamed_without_loss(tracking):
    _,store,d=tracking
    for n in range(12):
        name=f'h{n}'
        if n==0:d.begin(name,'alpha',config(name))
        else:rotate(d,f'h{n-1}',name)
        fill(d,name,n*60)
    now=NOW+timedelta(seconds=720*15)
    result=d.rolling_history('alpha',now=now)
    assert result['context_attempts']==720 and result['intervals']==719
    assert result['coverage_seconds']['approximate']==719*15
    assert fraction(result['tracked_exp'])==(3220*1497832+5000)//10000-(2501*1497832+5000)//10000


@pytest.mark.parametrize('index',[61,100,150])
def test_integer_attempt_indices_above_run_limit_are_rejected(tracking,index):
    _,store,d=tracking
    fill(d,'run')
    from tests.test_diagnostics import attempt
    before=[tuple(r) for r in store.db.execute('select * from diagnostic_attempts order by id')]
    with pytest.raises(ValueError,match='bounded index'):
        d.append('run',attempt(index))
    # Schema-3 constraints retained in schema 4 reject out-of-range integer
    # indices and duplicate indices even without the API's validation.
    sql='INSERT INTO diagnostic_attempts(run_id,attempt_index,attempted_at,received_at,recorded_at,payload_json,session_id) VALUES(?,?,?,?,?,?,?)'
    session=store.db.execute('select session_id from diagnostic_runs where run_id=?',('run',)).fetchone()[0]
    for candidate,error in ((index,'CHECK constraint'),(1,'UNIQUE constraint')):
        with pytest.raises(sqlite3.IntegrityError,match=error),store._transaction():
            store.db.execute(sql,('run',candidate,NOW.isoformat(),NOW.isoformat(),NOW.isoformat(),json.dumps(attempt(candidate)),session))
    assert [tuple(r) for r in store.db.execute('select * from diagnostic_attempts order by id')]==before
    now=NOW+timedelta(seconds=900)
    rows=d._snapshot('alpha',now=now,run_id='run',limit=60,_rows_only=True)
    assert [r['index'] for r in rows]==list(range(1,61))
    assert len({r['event_id'] for r in rows})==60
    result=d.rolling_history('alpha',now=now)
    assert result['context_attempts']==60 and result['intervals']==59


@pytest.mark.parametrize('count',[61,100,150])
def test_unexpected_oversized_sql_run_is_unavailable_not_silently_truncated(tracking,count):
    _,store,d=tracking
    fill(d,'run')
    # SQLite INTEGER affinity is not STRICT: an unsupported raw SQL writer can
    # store fractional indices that satisfy the range CHECK and uniqueness.
    original=store.db.execute('select * from diagnostic_attempts limit 1').fetchone()
    with store._transaction():
        for i in range(1,count-60+1):
            store.db.execute('INSERT INTO diagnostic_attempts(run_id,attempt_index,attempted_at,received_at,recorded_at,payload_json,session_id) VALUES(?,?,?,?,?,?,?)',
                ('run',1+i/1000,original['attempted_at'],original['received_at'],original['recorded_at'],original['payload_json'],original['session_id']))
    result=d.rolling_history('alpha',now=NOW+timedelta(seconds=900))
    assert result['context_attempts']==count and result['status']=='history_limit'
    assert result['tracked_exp'] is None and result['intervals']==0
    assert all(b['value'] is None for b in result['buckets'])


@pytest.mark.parametrize('count',[61,100,150])
@pytest.mark.parametrize('case',['pending_loss','large_anomaly'])
def test_legal_rotated_histories_match_full_causal_replay_at_pending_boundary(tracking,count,case):
    _,store,d=tracking
    from tests.test_diagnostics import attempt
    for offset in range(0,count,60):
        run=f'boundary-{offset//60}'
        if offset==0:d.begin(run,'alpha',config(run))
        else:rotate(d,f'boundary-{offset//60-1}',run)
        for index in range(1,min(60,count-offset)+1):
            ordinal=offset+index;bp=2500+ordinal
            if ordinal>=60 and case=='pending_loss':bp-=51
            if ordinal in (60,61) and case=='large_anomaly':bp=1500+ordinal-60
            value=attempt(index);stamp=(NOW+timedelta(seconds=ordinal*15)).isoformat()
            value.update(attempted_at=stamp,received_at=stamp,candidate=None,neural=dict(text=f'[{bp//100}.{bp%100:02}%]'),
                visual_level=64,neural_level=None,visual_status='available',status='diagnostic_percentage_only',
                localization=dict(count=1),frame_sha256=f'{ordinal:064x}')
            d.append(run,value)
    now=NOW+timedelta(seconds=count*15+1)
    snapshot=d.snapshot('alpha',now=now,limit=count)
    rows=snapshot['observations'];assert len(rows)==count
    assert len({r['event_id'] for r in rows})==count
    assert rows[59]['percentage_review']['progress_eligible'] is False
    if case=='pending_loss':
        assert rows[60]['percentage_review']['status']=='corroborated_lower_baseline'
        assert rows[60]['percentage_review']['break_before']=='confirmed_change_new_baseline'
    else:assert rows[60]['percentage_review']['progress_eligible'] is False
    gains=[p['gain'] for p in history(snapshot) if p['gain']]
    result=d.rolling_history('alpha',now=now)
    assert result['context_attempts']==count and result['intervals']>=len(gains)
    assert (fraction(result['tracked_exp']) if result['tracked_exp'] else None)==expected_net(snapshot,now)
    assert result['coverage_seconds']['approximate']>0
    assert sum((fraction(b['value']) for b in result['buckets'] if b['value'] is not None),Fraction(0))==fraction(result['tracked_exp'])
    assert not store.db.execute('select 1 from observations').fetchone()


@pytest.mark.parametrize('kind',['loss','anomaly','level','stale','multiple_huds'])
def test_hard_boundaries_match_existing_history(tracking,kind):
    _,_,d=tracking
    for i,pct in enumerate(('33.00','33.05','32.00','32.05' if kind=='loss' else '33.10','32.10' if kind=='loss' else '33.15'),1):
        changes=dict(frame_sha256=f'{i:064x}')
        if i>=3 and kind=='level':changes.update(visual_level=65,neural_level=dict(text='65',level=65,status='numeric_candidate',score=.99))
        if i==3 and kind=='stale':changes['current']=False
        if i==3 and kind=='multiple_huds':changes['localization']=dict(count=2)
        append(d,i,f'[{pct}%]',**changes)
    now=NOW+timedelta(seconds=60)
    expected=[p['gain'] for p in history(d.snapshot('alpha',now=now)) if p['gain']]
    result=d.rolling_history('alpha',now=now)
    assert (fraction(result['tracked_exp']) if result['tracked_exp'] else None)==expected_net(d.snapshot('alpha',now=now),now)


def test_utc_24_hours_is_not_a_local_calendar_day(tracking):
    _,_,d=tracking
    for i in (1,2):append(d,i,'[33.00%]')
    # Both sides of a DST change expressed as explicit offsets: always 86400s.
    for now in (datetime.fromisoformat('2026-11-01T01:30:00-04:00'),datetime.fromisoformat('2026-11-01T01:30:00-05:00')):
        r=d.rolling_history('alpha',now=now)
        assert (datetime.fromisoformat(r['end'])-datetime.fromisoformat(r['start'])).total_seconds()==86400
    with pytest.raises(ValueError):d.rolling_history('alpha',now=datetime(2026,1,1))


def test_unsupported_requirements_and_source_changes_cannot_supply_gains(tracking):
    _,_,d=tracking
    for i in (1,2):
        append(d,i,'[33.00%]',visual_level=100,neural_level=None)
    assert d.rolling_history('alpha',now=NOW+timedelta(seconds=15))['tracked_exp'] is None
    append(d,3,'[33.05%]')
    append(d,4,'[33.10%]',source=dict(kind='file',channel=None))
    result=d.rolling_history('alpha',now=NOW+timedelta(seconds=45))
    assert result['tracked_exp']['approximate']==749  # Both usable level-64 endpoints remain comparable.


def test_work_limit_is_unknown_not_an_invented_zero(tracking,monkeypatch):
    _,_,d=tracking
    append(d,1,'[33.00%]');append(d,2,'[33.05%]')
    import exp_tracker.rolling_history as module
    monkeypatch.setattr(module,'MAX_EVENTS',1)
    r=d.rolling_history('alpha',now=NOW+timedelta(seconds=15))
    assert r['status']=='history_limit' and r['tracked_exp'] is None
    assert all(b['value'] is None for b in r['buckets'])
    d.begin('limited-a','alpha',config('limited-a'));fill(d,'limited-a')
    rotate(d,'limited-a','limited-b');fill(d,'limited-b',60)
    monkeypatch.setattr(module,'MAX_EVENTS',65)
    r=d.rolling_history('alpha',now=NOW+timedelta(seconds=1800))
    assert r['status']=='history_limit' and r['intervals']==0
    assert r['basis_counts']=={} and r['requirement_versions']==[]
    assert r['coverage_seconds']['approximate']==0 and all(b['value'] is None for b in r['buckets'])


def test_bucket_boundaries_conserve_large_gains_and_preserve_observed_zero(tracking):
    _,_,d=tracking
    append(d,1,'[33.00%]');append(d,2,'[33.00%]');append(d,3,'[34.00%]')
    # The gain interval straddles an exact 30-minute edge in the rolling axis.
    now=NOW+timedelta(minutes=30,seconds=22)
    result=d.rolling_history('alpha',now=now)
    populated=[b for b in result['buckets'] if b['value'] is not None]
    assert len(populated)==2
    assert sum(fraction(b['value']) for b in populated)==fraction(result['tracked_exp'])==14978
    assert sum(fraction(b['covered']) for b in populated)==30
    assert all(b['state']=='partial' for b in populated)
    zero=d.rolling_history('alpha',now=NOW+timedelta(seconds=15))
    assert fraction(zero['tracked_exp'])==0 and zero['intervals']==1
    assert any(b['value'] is not None and fraction(b['value'])==0 for b in zero['buckets'])


def test_http_rolling_cache_invalidates_on_commit_character_and_clock_without_mutation(tracking,monkeypatch):
    import exp_tracker.server as module
    from tests.test_server import request
    class Clock(datetime):
        at=NOW+timedelta(seconds=15)
        @classmethod
        def now(cls,tz=None):return cls.at
    monkeypatch.setattr(module,'datetime',Clock)
    path,store,d=tracking
    append(d,1,'[33.00%]');append(d,2,'[33.05%]')
    original=[tuple(r) for r in store.db.execute('select * from diagnostic_attempts')]
    with module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        route='/api/players/alpha/history'
        status,headers,body=request((server,None),route)
        value=json.loads(body)
        assert status==200 and headers['Cache-Control']=='no-store'
        assert value['intervals']==1 and value['trusted'] is False
        assert len(value['buckets'])==48 and len(body)<32000
        assert not any(key in body.decode() for key in ('raw_text','source_identity','payload_json','sqlite3','frame_sha256'))
        cached=server.publisher.entry('alpha')['tracked']
        assert json.loads(request((server,None),route)[2])==value
        assert server.publisher.entry('alpha')['tracked'] is cached  # Reused, not recomputed.
        append(d,3,'[33.10%]');Clock.at=NOW+timedelta(seconds=30)
        updated=json.loads(request((server,None),route)[2])
        assert updated['intervals']==2 and fraction(updated['tracked_exp'])==1497
        Clock.at+=timedelta(days=2)
        assert json.loads(request((server,None),route)[2])['tracked_exp'] is None
        Clock.at=NOW+timedelta(seconds=30)
        other=store.add_character('alpha','Other');store.end_session('alpha',at=Clock.at)
        store.select_character('alpha',other);store.start_session('alpha',at=Clock.at)
        assert json.loads(request((server,None),route)[2])['tracked_exp'] is None
        assert request((server,None),'/api/players/missing/history')[0]==404
        assert request((server,None),'/api/players/invalid!/history')[0]==400
        assert request((server,None),route,'POST')[0]==405
    assert [tuple(r) for r in store.db.execute('select * from diagnostic_attempts order by id limit 2')]==original
    assert not store.db.execute('select 1 from observations').fetchone()
    with module.create_server(path,port=0) as server:
        assert request((server,None),route)[0]==404
