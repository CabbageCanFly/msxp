"""Bounded token recovery, short missing-HUD context and dated character ETA."""
from copy import deepcopy
from datetime import datetime,timedelta
import json
import sqlite3
from pathlib import Path

import pytest

from exp_tracker.diagnostic_evidence import project
from exp_tracker.diagnostic_progress import percentage_point
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.product import player,recent_windows,refresh,history,window_comparisons
from exp_tracker.shadow_grammar import interpret_exp
from exp_tracker.shadow_types import parse_percentage_only
from exp_tracker.store import Store
from tests.test_endpoint_pace import point,missing,snapshot
from tests.test_product import tracking,NOW
from tests.test_numerical_windows import saved_attempt,false_pair
from tests.test_diagnostic_history import config


@pytest.mark.parametrize('raw',['56.97%1','56.97%','56.97%|||','56.97%]','00.85%1'])
def test_complete_standalone_token_never_invents_an_opening_bracket(raw):
    result=interpret_exp(raw)
    proposal=result['percentage']['proposals'][0]
    assert result['policy']=='bounded_exp_v8'
    assert not result['full_exp']['proposals'] and result['strict_percentage_only'] is None
    assert parse_percentage_only(raw) is None
    assert proposal['interpretation']==raw[:raw.index('%')+1]
    assert proposal['reading']['percentage']==f'{float(raw[:5]):.2f}'
    assert all(edit['new']=='' for edit in proposal['edits'])
    assert not proposal['trusted'] and not proposal['numerical_identity_verified']


@pytest.mark.parametrize('raw',['0.85%1','170 57%1','156.97%1','56.97%123',
    '56.97%1 57.06%1','56.97%1[57.06%]','56,97%1','56.9%1','56.970%1','56.97X1','P56.97%1'])
def test_missing_digits_and_competing_tokens_are_not_reconstructed(raw):
    result=interpret_exp(raw)
    assert not result['percentage']['proposals'] and not result['full_exp']['proposals']


def test_new_token_runs_through_percentage_review_and_never_evades_whole_pair_veto():
    rows=[point(1,0,1000197,'56.90'),point(2,20,1001428,'56.97'),point(3,40,1001779,'56.99')]
    rows[-1].update(raw_text='56.80%1',candidate=None,status='malformed_or_unavailable')
    snap=snapshot(rows,40)
    assert snap['observations'][-1]['percentage_review']['status']=='pending_exp_decrease'
    assert not snap['observations'][-1]['percentage_review']['progress_eligible']
    bad=snapshot(false_pair(),45)['observations'][-1]
    assert percentage_point(bad)==(None,'arithmetic_pair_veto')


def neural_rows():
    rows=[point(1,0,657877,'37.43'),point(2,20,659373,'37.51'),point(3,40,660978,'37.60')]
    for row in rows:row.update(visual_level=None,visual_status='unavailable')
    return rows


def test_short_missing_capture_retains_reader_context_but_no_numeric_point():
    rows=neural_rows()+[missing(4,60),point(5,80,662457,'37.69')]
    rows[-1].update(visual_level=None,visual_status='unavailable')
    original=deepcopy(rows);values=project(rows)
    assert values[3]['experimental_level']['reason']=='ordinary_unreadable_context_preserved'
    assert values[3]['experimental_level']['value'] is None and percentage_point(values[3])[0] is None
    assert values[4]['experimental_level']['value']==67
    assert values[4]['experimental_level']['context_gap_attempts']==1
    assert values[4]['experimental_level']['strict_window_eligible'] is False
    state={};chunks=project(rows[:4],state=state)+project(rows[4:],state=state)
    assert chunks==values and rows==original
    snap=snapshot(rows,80)
    assert snap['observations'][-1]['percentage_review']['progress_eligible']
    assert not history(snap)[-1]['connect_previous']
    pace=recent_windows(snap,None,now=NOW+timedelta(seconds=80))['5']['pace']
    assert pace['interval_counts']['endpoint_supported']==1 and pace['readings']==4


@pytest.mark.parametrize('boundary',['stale','duplicate','conflict','source','session','restart','expired','ambiguous','late','clipped'])
def test_short_reader_context_breaks_but_fresh_arithmetic_can_reestablish_level(boundary):
    rows=neural_rows()+[missing(4,60),point(5,80,662457,'37.69')]
    rows[-1].update(visual_level=None,visual_status='unavailable')
    if boundary=='stale':rows[3].update(status='stale_local_frame')
    elif boundary=='duplicate':rows[3]['frame_sha256']=rows[2]['frame_sha256']
    elif boundary=='conflict':rows[3].update(visual_level=68,visual_status='available')
    elif boundary=='source':rows[-1]['source_identity']='different'
    elif boundary=='session':rows[-1]['session_id']=2
    elif boundary=='restart':rows[-1].update(run_id='restart',index=1)
    elif boundary=='expired':rows[-1]['received_at']=(NOW+timedelta(seconds=170)).isoformat()
    elif boundary=='late':rows[3]['local_age_seconds']=16
    elif boundary=='clipped':rows[3]['neural_level']=dict(status='not_run',level=None,source_complete=False)
    else:rows[3]['hud_count']=2
    values=project(rows)
    assert values[3]['experimental_level']['value'] is None
    final=values[-1]['experimental_level']
    assert final['value']==67 and final['status']=='exp_derived'
    assert final['exp_derived']['unique_level']==67 and not final.get('contextual')


def test_carried_level_frame_does_not_relax_strict_completed_window_evidence():
    rows=[]
    for index in range(1,22):
        seconds=(index-1)*20
        if index==4:rows.append(missing(index,seconds));continue
        bp=3000+index
        r=point(index,seconds,bp*1757815//10000,f'{bp//100}.{bp%100:02}')
        r.update(visual_level=None,visual_status='unavailable');rows.append(r)
    carried=snapshot(rows[:20],380)
    w=window_comparisons(carried,now=NOW+timedelta(seconds=380))['5']
    assert w['eligibility_checks']['ninety_percent_span']
    assert not w['eligibility_checks']['reader_supported_levels'] and not w['eligible']
    # Once the context-dependent endpoint ages out, ordinary strict criteria apply.
    independent=snapshot(rows,400)
    assert window_comparisons(independent,now=NOW+timedelta(seconds=400))['5']['eligible']


@pytest.mark.parametrize('count',[1,2,5,10])
def test_eta_survives_failed_ocr_and_selected_window_expiry(count):
    rows=[point(1,0,657877,'37.43'),point(2,20,659373,'37.51')]
    original=recent_windows(snapshot(rows,20),None,now=NOW+timedelta(seconds=20))
    rows.extend(missing(i+3,40+i*20) for i in range(count))
    now=NOW+timedelta(hours=2)
    windows=recent_windows(snapshot(rows,int((now-NOW).total_seconds())),None,now=now)
    for minutes in ('5','10','15','30','60'):
        value=windows[minutes]
        assert not value['available'] and value['gain'] is None
        assert value['eta']['estimate']==original[minutes]['eta']['estimate']
        assert value['eta']['historical'] and value['eta']['window_minutes']==int(minutes)
        assert value['eta']['estimated_at']==rows[1]['received_at']
        assert value['eta']['static_duration']


def test_eta_does_not_reestimate_itself_as_old_window_samples_age_out():
    rows=[]
    for i,delta in enumerate((0,10,20,40,80,100,110)):
        bp=3300+delta
        rows.append(point(i+1,i*50,bp*1757815//10000,f'{bp//100}.{bp%100:02}'))
    snap=snapshot(rows,300)
    windows=[recent_windows(snap,None,now=NOW+timedelta(seconds=s))['5'] for s in (300,351,700)]
    assert windows[0]['pace']['estimates']['exp_per_hour']!=windows[1]['pace']['estimates']['exp_per_hour']
    assert windows[0]['eta']['estimate']==windows[1]['eta']['estimate']==windows[2]['eta']['estimate']
    assert windows[0]['eta']['estimated_at']==windows[2]['eta']['estimated_at']
    assert not windows[2]['available'] and windows[2]['gain'] is None


def test_sqlite_restores_dated_eta_across_restart_and_beyond_recent_query(tracking):
    path,store,d=tracking
    for i in range(1,4):saved_attempt(d,'run',i,(i-1)*20,3300+i*5)
    now=NOW+timedelta(seconds=40)
    first=player(d.snapshot('alpha',now=now),now=now,recent_snapshot=d.recent_snapshot('alpha',now=now))
    d.begin('restart','alpha',config('restart',source_identity=None))
    failed=dict(type='attempt',trusted=False,index=1,current=False,
        attempted_at=(NOW+timedelta(hours=2)).isoformat(),status='capture_failed',
        source=dict(kind='twitch',channel='alpha'))
    d.append('restart',failed)
    now=NOW+timedelta(hours=2,seconds=1)
    raw=[r[0] for r in store.db.execute('select payload_json from diagnostic_attempts order by id')]
    with Store(path,read_only=True) as reopened:
        reader=Diagnostics(reopened);cache={}
        recent=reader.recent_snapshot('alpha',now=now,eta_cache=cache)
        assert recent['eta_history_status']=='ready'
        assert recent['historical_etas']['5']['estimated_at']==first['recent_windows']['5']['eta']['estimated_at']
        result=player(reader.snapshot('alpha',now=now),now=now,recent_snapshot=recent)
        for minutes in ('5','10','15','30','60'):
            assert result['recent_windows'][minutes]['eta']['estimate']==first['recent_windows'][minutes]['eta']['estimate']
            assert not result['recent_windows'][minutes]['available']
        # A no-revision poll ages metadata only; it cannot erase or count down ETA.
        aged=refresh(result,now=now+timedelta(hours=5),activity={'state':'capture_failing'})
        assert aged['recent_windows']['5']['eta']['estimate']==result['recent_windows']['5']['eta']['estimate']
        assert aged['recent_windows']['5']['eta']['age_seconds']>result['recent_windows']['5']['eta']['age_seconds']
        assert len(cache)==1
        reader.recent_snapshot('alpha',now=now+timedelta(seconds=10),eta_cache=cache)
        assert len(cache)==1
    assert raw==[r[0] for r in store.db.execute('select payload_json from diagnostic_attempts order by id')]
    assert not store.db.execute('select 1 from observations').fetchone()
    store.end_session('alpha',at=now);store.start_session('alpha',at=now+timedelta(seconds=1))
    assert not any(w['eta'] for w in player(d.snapshot('alpha',now=now),now=now,
        recent_snapshot=d.recent_snapshot('alpha',now=now))['recent_windows'].values())


@pytest.mark.parametrize('kind',['level_conflict','unsupported','disputed','stationary','one_reading'])
def test_eta_can_remain_unavailable_for_genuine_evidence_limits(kind):
    rows=[point(1,0,657877,'37.43'),point(2,20,659373,'37.51')]
    if kind=='level_conflict':
        rows.append(point(3,40,660978,'37.60'));rows[-1]['neural_level'].update(level=68,text='68')
    elif kind in ('unsupported','disputed'):
        level=100 if kind=='unsupported' else 99
        for r in rows:r.update(visual_level=level);r['neural_level'].update(level=level,text=str(level))
    elif kind=='one_reading':rows=rows[:1]
    else:rows[1]=point(2,20,657877,'37.43')
    assert not any(w['eta'] for w in recent_windows(snapshot(rows,40),None,now=NOW+timedelta(seconds=40)).values())


def test_refresh_dates_eta_without_sticky_historical_state_or_offline_live_claims(tracking):
    _,_,d=tracking
    for i in range(1,3):saved_attempt(d,'run',i,(i-1)*20,3300+i*5)
    now=NOW+timedelta(seconds=20)
    value=player(d.snapshot('alpha',now=now),now=now)
    assert value['recent_windows']['5']['eta']['historical']
    active=refresh(value,now=now,activity=dict(state='waiting'))
    assert not active['recent_windows']['5']['eta']['historical']
    active['twitch']=dict(status='offline')
    offline=refresh(active,now=now,activity=dict(state='waiting'))
    assert offline['recent_windows']['5']['eta']['historical']
    assert offline['recent_windows']['5']['eta']['estimate']==active['recent_windows']['5']['eta']['estimate']


def test_empty_restart_with_changed_source_does_not_restore_another_sources_eta(tracking):
    _,_,d=tracking
    for i in range(1,4):saved_attempt(d,'run',i,(i-1)*20,3300+i*5)
    d.begin('new-source','alpha',config('new-source'))  # New explicit source identity.
    now=NOW+timedelta(hours=2)
    result=player(d.snapshot('alpha',now=now),now=now,recent_snapshot=d.recent_snapshot('alpha',now=now))
    assert not any(w['eta'] for w in result['recent_windows'].values())


def test_eta_history_work_limit_is_explicit_and_does_not_affect_trusted_state(tracking,monkeypatch):
    from exp_tracker import rolling_history
    _,store,d=tracking
    for i in range(1,4):saved_attempt(d,'run',i,(i-1)*20,3300+i*5)
    monkeypatch.setattr(rolling_history,'MAX_EVENTS',2)
    now=NOW+timedelta(hours=2)
    result=player(d.snapshot('alpha',now=now),now=now,recent_snapshot=d.recent_snapshot('alpha',now=now))
    assert result['recent_history']['eta_status']=='history_limit'
    assert not any(w['eta'] for w in result['recent_windows'].values())
    assert not store.db.execute('select 1 from observations').fetchone()


def test_dated_eta_restoration_preserves_read_only_schema_v3_compatibility(tracking,tmp_path):
    _,store,d=tracking
    for i in range(1,4):saved_attempt(d,'run',i,(i-1)*20,3300+i*5)
    legacy=tmp_path/'legacy.sqlite3'
    with sqlite3.connect(legacy) as db:
        store.db.backup(db)
        db.execute('DROP INDEX diagnostic_recent');db.execute('DROP INDEX diagnostic_time')
        db.execute('ALTER TABLE diagnostic_attempts DROP COLUMN session_id')
        db.execute('PRAGMA user_version=3')
    now=NOW+timedelta(hours=2)
    with Store(legacy,read_only=True) as reopened:
        assert reopened.schema_version==3
        reader=Diagnostics(reopened)
        result=player(reader.snapshot('alpha',now=now),now=now,recent_snapshot=reader.recent_snapshot('alpha',now=now))
        assert all(w['eta'] for w in result['recent_windows'].values())
        assert reopened.db.execute('PRAGMA user_version').fetchone()[0]==3


def test_single_fresh_endpoint_after_long_gap_cannot_erase_the_previous_eta(tracking):
    _,_,d=tracking
    for i in range(1,4):saved_attempt(d,'run',i,(i-1)*20,3300+i*5)
    now=NOW+timedelta(seconds=40)
    old=player(d.snapshot('alpha',now=now),now=now,recent_snapshot=d.recent_snapshot('alpha',now=now))['recent_windows']['5']['eta']
    saved_attempt(d,'run',4,7200,3400)
    now=NOW+timedelta(seconds=7200)
    current=player(d.snapshot('alpha',now=now),now=now,recent_snapshot=d.recent_snapshot('alpha',now=now))['recent_windows']['5']
    assert current['gain'] is None  # No long-gap subtraction.
    assert current['eta']['estimate']==old['estimate'] and current['eta']['historical']
    assert current['eta']['estimated_at']==old['estimated_at']
    saved_attempt(d,'run',5,7220,3405)
    now=NOW+timedelta(seconds=7220)
    recovered=player(d.snapshot('alpha',now=now),now=now,recent_snapshot=d.recent_snapshot('alpha',now=now))['recent_windows']['5']
    assert recovered['eta']['estimated_at']==now.isoformat()
    assert recovered['pace']['readings']==2 and recovered['pace']['coverage_seconds']['approximate']==20


def test_historical_eta_replay_prunes_only_after_supported_intervals(tracking,monkeypatch):
    from exp_tracker import rolling_history,diagnostics
    _,_,d=tracking
    now=NOW+timedelta(seconds=4200*20)
    runs=[dict(run_id=f'run-{n}',session_id=1,configuration_json='{}',summary_json='{}') for n in range(70)]
    def batch(diagnostic,channel,run,*,now,receipt):
        n=int(run['run_id'][4:]);rows=[]
        for i in range(60):
            ordinal=n*60+i+1;bp=3000+ordinal
            row=point(ordinal,ordinal*20,bp*1757815//10000,f'{bp//100}.{bp%100:02}')
            row.update(run_id=f'run-{n}',index=i+1,rotation_from=f'run-{n-1}' if n else None,
                source_identity='b'*64,coordinator_instance='a'*32)
            rows.append(row)
        receipt['context_attempts']+=len(rows);receipt['run_count']+=1
        return (run['run_id'],'{}','{}',60,n),rows
    # Sanitized synthetic batches isolate bounded retention; real SQLite rotation
    # validation is exercised by the existing multi-run history regressions.
    monkeypatch.setattr(rolling_history,'select_runs',lambda *args,**kwargs:runs)
    monkeypatch.setattr(rolling_history,'run_rows',batch)
    monkeypatch.setattr(diagnostics,'rotation_link',lambda before,after:before is not None)
    result=rolling_history.recent_snapshot(d,'alpha',now=now,_historical=True)
    assert result['recent_history_status']=='ready'
    assert result['recent_history_receipt']['context_attempts']==4200
    assert 2<=len(result['observations'])<4096
    assert result['observations'][-1]['received_at']==now.isoformat()
    assert result['observations'][-1]['percentage_review']['progress_eligible']


@pytest.mark.parametrize('channel',['telfer1','niru'])
def test_saved_followup_checkpoints(tmp_path,channel):
    path=(Path('private/multi-alpha/runs/20261018T195958Z-eee70469/telfer1/93dddb3313a5445e86d7d12dd3fb9917/capture.jsonl')
        if channel=='telfer1' else Path('private/multi-alpha/runs/20261018T211439Z-794bf39d/niru/capture.jsonl'))
    if not path.exists():pytest.skip('Private source unavailable')
    with Store(tmp_path/'saved.sqlite3') as store:
        store.add_channel(channel);cid=store.add_character(channel,'Saved review');store.select_character(channel,cid);store.start_session(channel)
        d=Diagnostics(store)
        paths=list(path.parent.parent.rglob('capture.jsonl')) if channel=='telfer1' else [path]
        paths.sort(key=lambda p:next(json.loads(x)['attempted_at'] for x in p.read_text().splitlines() if json.loads(x)['type']=='attempt'))
        for source in paths:d.replay(channel,source)
        rid=json.loads(path.read_text().splitlines()[0])['run_id']
        raw=[dict(r,run_interrupted=False) for r in d.snapshot(channel,limit=640)['observations'] if r['run_id']==rid][:7]
        seconds=(datetime.fromisoformat(raw[-1]['received_at'])-NOW).total_seconds()
        snap=snapshot(raw,seconds)
        row=snap['observations'][4]
        assert row['percentage_review']['progress_eligible']
        assert percentage_point(row)[0]['percentage']==('56.97' if channel=='telfer1' else '77.54')
        assert row['experimental_level']['value']==(67 if channel=='telfer1' else 56)
        if channel=='niru':assert history(snap)[3]['reading'] is None
        assert not store.db.execute('select 1 from observations').fetchone()
