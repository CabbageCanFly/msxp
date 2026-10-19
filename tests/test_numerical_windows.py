"""Read-time numerical veto and independently sampled, SQLite-backed window cards."""
from copy import deepcopy
from datetime import datetime,timedelta
import json
from pathlib import Path

import pytest

from exp_tracker.diagnostic_evidence import project
from exp_tracker.diagnostic_progress import percentage_point
from exp_tracker.product import player,reading,history,recent_windows,window_comparisons
from exp_tracker.exp_requirements import requirement
from exp_tracker.store import Store
from exp_tracker.diagnostics import Diagnostics
from tests.test_endpoint_pace import point,snapshot,missing
from tests.test_product import tracking,NOW
from tests.test_diagnostics import attempt
from tests.test_diagnostic_history import config


def false_pair():
    rows=[point(1,0,657877,'37.43'),point(2,20,659373,'37.51'),point(3,45,680978,'37.80')]
    rows[-1].update(raw_text='680.978137.80%1',candidate=None,status='malformed_or_unavailable',
        visual_level=None,visual_status='unavailable')
    rows[-1]['neural_level']['score']=.71
    return rows


def test_telfer_wrong_pair_is_vetoed_before_percentage_baseline_and_public_history():
    rows=false_pair();before=deepcopy(rows);snap=snapshot(rows,45)
    bad=snap['observations'][-1]
    assert bad['exp_validity']['whole_pair_rejected']
    assert bad['exp_validity']['level_context']['value']==67
    assert all(h['status']=='inconsistent' for h in bad['exp_validity']['hypotheses'].values())
    assert percentage_point(bad)==(None,'arithmetic_pair_veto')
    assert reading(bad) is None and history(snap)[-1]['reading'] is None
    assert bad['percentage_review']['public_eligible'] is False
    rows.append(point(4,65,662457,'37.69'))
    recovered=snapshot(rows,65)
    assert recovered['observations'][-1]['percentage_review']['status']=='accepted_observation'
    assert not any(e['event_id']=='run:3' for e in recovered['percentage_progress']['percentage_reviews'] if e['progress_eligible'])
    assert rows[:3]==before


def test_recent_level_can_veto_without_a_usable_current_reader_but_cannot_repair_digits():
    rows=false_pair();rows[-1]['neural_level']=None
    bad=project(rows)[-1]
    assert bad['exp_validity']['whole_pair_rejected'] and reading(bad) is None
    # Arithmetic cannot detect a wrong integer still in the displayed bin.
    rows[-1].update(raw_text='660,979[37.60%]',candidate=dict(exp='660979',percentage='37.60'),status='diagnostic_pair')
    assert project(rows)[-1]['exp_validity']['status']=='consistent'
    assert reading(project(rows)[-1])['exp']=='660979'


@pytest.mark.parametrize('kind',['expired','different_level','restart','session','source','stale'])
def test_old_level_context_cannot_veto_through_real_boundaries(kind):
    rows=false_pair();r=rows[-1]
    if kind=='expired':r.update(received_at=(NOW+timedelta(seconds=170)).isoformat())
    elif kind=='different_level':
        r.update(visual_level=68,visual_status='available');r['neural_level'].update(level=68,text='68',score=.99)
    elif kind=='restart':r.update(run_id='restart',index=1)
    elif kind=='session':r['session_id']=2
    elif kind=='source':r['source_identity']='different'
    else:r.update(status='stale_local_frame',fresh_at_capture=False)
    assert not project(rows)[-1]['exp_validity'].get('whole_pair_rejected')


@pytest.mark.parametrize('seconds',[20,35,40,60,90])
def test_neural_confirmation_uses_actual_bounded_spacing_not_nominal_cadence(seconds):
    rows=[point(i+1,i*seconds,518725,'47.70',level=58) for i in range(5)]
    for r in rows:r.update(visual_level=None,visual_status='unavailable')
    values=project(rows)
    assert [r['experimental_level']['value'] for r in values]==[58]*5
    assert values[0]['experimental_level']['status']=='exp_derived'
    rows[2].update(status='stale_local_frame',fresh_at_capture=False)
    values=project(rows)
    assert [r['experimental_level']['value'] for r in values]==[58,58,None,58,58]
    assert values[3]['experimental_level']['status']=='exp_derived'
    assert all(not r['exp_validity'].get('whole_pair_rejected') for r in values)


def test_duplicate_frames_and_conflicting_neural_levels_do_not_corroborate():
    rows=[point(i+1,i*40,518725,'47.70',level=58) for i in range(3)]
    for r in rows:r.update(visual_level=None,visual_status='unavailable')
    rows[1]['frame_sha256']=rows[0]['frame_sha256']
    values=project(rows)
    assert [r['experimental_level']['value'] for r in values]==[58,None,58]
    assert values[2]['experimental_level']['status']=='exp_derived'
    rows[1]['frame_sha256']='a'*64;rows[1]['neural_level'].update(level=57,text='57')
    values=project(rows)
    assert all(r['experimental_level']['value']==58 and r['experimental_level']['status']=='exp_derived' for r in values)
    assert values[1]['experimental_level']['unselected_reader_claims']==dict(neural=57)


def saved_attempt(d,run,index,seconds,bp,source_kind='twitch'):
    stamp=(NOW+timedelta(seconds=seconds)).isoformat();value=attempt(index)
    percentage=f'{bp//100}.{bp%100:02}';exp=bp*1497832//10000
    value.update(attempted_at=stamp,received_at=stamp,current=True,
        neural=dict(text=f'{exp:,}[{percentage}%]'),candidate=[exp,float(percentage)],
        visual_level=64,visual_status='available',neural_level=dict(status='numeric_candidate',text='64',level=64,score=.99,preprocessing='neutral4'),
        status='diagnostic_pair',localization=dict(count=1),frame_sha256=f'{seconds:064x}',source=dict(kind=source_kind,channel='alpha'))
    d.append(run,value)
    return exp


def test_sqlite_recent_numeric_windows_include_bound_restart_and_actual_gap_time(tracking):
    path,store,d=tracking
    d.begin('first','alpha',config('first'))
    old=[saved_attempt(d,'first',i+1,i*60,3300+i*5) for i in range(3)]
    d.begin('restart','alpha',config('restart'))
    new=[saved_attempt(d,'restart',i+1,600+i*60,3320+i*10) for i in range(3)]
    now=NOW+timedelta(seconds=720)
    original=[r[0] for r in store.db.execute('select payload_json from diagnostic_attempts order by id')]
    snap=d.snapshot('alpha',now=now,limit=640)
    strict=window_comparisons(snap,now=now)
    p=player(snap,now=now,recent_snapshot=d.recent_snapshot('alpha',now=now))
    windows=p['recent_windows'];both=new[-1]-old[0]
    assert windows['5']['gain']['approximate']==new[-1]-new[0]
    for minutes in ('15','30','60'):
        w=windows[minutes]
        assert w['gain']['approximate']==both
        assert w['pace']['coverage_seconds']['approximate']==720
        assert w['pace']['readings']==6 and w['pace']['interruptions']==0
        assert w['pace']['estimates']['exp_per_hour']['value']['approximate']==both*5
        assert not w['complete_window']
    assert windows['10']['gain']['approximate']==new[-1]-old[-1]
    assert p['windows']==strict
    with Store(path,read_only=True) as restarted:
        again=Diagnostics(restarted)
        assert player(again.snapshot('alpha',now=now,limit=640),now=now,recent_snapshot=again.recent_snapshot('alpha',now=now))['recent_windows']==windows
    assert [r[0] for r in store.db.execute('select payload_json from diagnostic_attempts order by id')]==original
    assert not store.db.execute('select 1 from observations').fetchone()
    later=NOW+timedelta(seconds=1080)
    aged=player(d.snapshot('alpha',now=later),now=later,recent_snapshot=d.recent_snapshot('alpha',now=later))
    assert not aged['recent_windows']['5']['available']
    assert aged['recent_windows']['30']['gain']==windows['30']['gain']
    store.end_session('alpha',at=later);store.start_session('alpha',at=later+timedelta(seconds=1))
    saved=player(d.snapshot('alpha',now=later),now=later,recent_snapshot=d.recent_snapshot('alpha',now=later))
    assert saved['recent_windows']['60']['gain']==windows['60']['gain']
    assert not saved['recent_windows']['60']['pace']['active']


def test_recent_sqlite_query_exceeds_browser_history_cap_and_keeps_clean_rotation(tracking):
    _,store,d=tracking
    for n in range(12):
        run=f'long-{n}';configuration=config(run,f'long-{n-1}' if n else None,interval=3,source_kind='file',offline_fast_test=True)
        if n:
            d.rotate(f'long-{n-1}',run,'alpha',dict(type='summary',trusted=False,attempts=60,interrupted=False,
                completion_reason='scheduled_rotation',next_run_id=run),configuration)
        else:d.begin(run,'alpha',configuration)
        for i in range(1,61):saved_attempt(d,run,i,(n*60+i)*3,3300+n*60+i,source_kind='file')
    now=NOW+timedelta(seconds=2160)
    snap=d.snapshot('alpha',now=now,limit=640)
    assert snap['truncated'] and len(snap['observations'])==640
    full=d.recent_snapshot('alpha',now=now)
    assert len(full['observations'])==720
    p=player(snap,now=now,recent_snapshot=full)
    assert p['recent_windows']['60']['pace']['readings']==720
    assert p['recent_windows']['60']['pace']['coverage_seconds']['approximate']==2157
    assert p['recent_windows']['60']['pace']['interruptions']==0


def test_two_supported_readings_keep_dated_eta_through_missing_capture_but_need_requirement():
    rows=[point(1,0,659373,'37.51'),point(2,20,660978,'37.60')]
    snap=snapshot(rows,20)
    w=recent_windows(snap,dict(value=67),now=NOW+timedelta(seconds=20))['5']
    assert w['pace']['tentative'] and w['pace']['estimates']['eta']
    assert not any(x['eligible'] for x in window_comparisons(snap,now=NOW+timedelta(seconds=20)).values())
    stale=snapshot(rows+[missing(3,40)],40)
    saved=recent_windows(stale,dict(value=67),now=NOW+timedelta(seconds=40))['5']
    assert saved['eta']['estimate']==w['eta']['estimate'] and saved['eta']['historical']
    assert saved['eta']['estimated_at']==rows[1]['received_at']
    for r in rows:
        r.update(visual_level=100);r['neural_level'].update(level=100,text='100')
    assert recent_windows(snapshot(rows,20),dict(value=100),now=NOW+timedelta(seconds=20))['5']['pace']['estimates']['eta'] is None


def test_integer_rate_can_support_eta_inside_one_displayed_percentage_bin():
    rows=[point(1,0,660960,'37.60'),point(2,20,660978,'37.60')]
    pace=recent_windows(snapshot(rows,20),dict(value=67),now=NOW+timedelta(seconds=20))['5']['pace']
    assert pace['estimates']['percentage_per_hour']['value']['approximate']==0
    assert pace['estimates']['exp_per_hour']['value']['approximate']==3240
    eta=pace['estimates']['eta']
    assert eta['seconds']['approximate']==pytest.approx((1757815-660978)/3240*3600)
    assert eta['hypotheses'] is None and not eta['trusted']


def test_display_only_level_cannot_select_the_current_level_filter():
    rows=[point(1,0,660960,'37.60'),point(2,20,660978,'37.60'),
        point(3,40,103,'0.01',level=68),point(4,60,435,'0.02',level=68)]
    for r in rows:r['neural_level']=None
    snap=snapshot(rows,60)
    mixed=recent_windows(snap,dict(value=67,display_only=True),now=NOW+timedelta(seconds=60))['5']
    assert mixed['pace']['levels']==[67,68] and mixed['gain']['approximate']==requirement(67)['to_next']-660960+435
    result=recent_windows(snap,dict(value=67,display_only=True),now=NOW+timedelta(seconds=60),current_level_only=True)['5']
    assert result['pace']['level']==67 and result['pace']['readings']==2
    assert result['gain']['approximate']==18


def test_selected_window_expires_gain_but_retains_its_own_dated_rate():
    rows=[point(1,0,657877,'37.43'),point(2,20,659373,'37.51'),point(3,40,660978,'37.60'),missing(4,400)]
    snap=snapshot(rows,400)
    windows=recent_windows(snap,dict(value=67),now=NOW+timedelta(seconds=400))
    assert not windows['5']['available'] and windows['5']['gain'] is None
    saved=windows['5']['last_observed_pace']
    assert not saved['active'] and saved['readings']==3 and saved['end']==rows[2]['received_at']
    assert saved['estimates']['eta'] is None  # OBS/live semantics remain separate.
    assert saved['last_observed_eta']==windows['5']['eta']['estimate']
    assert windows['5']['eta']['historical']
    assert windows['10']['available'] and windows['10']['pace']['trend_seconds']==600


def test_directory_ages_selected_samples_and_expires_them_without_new_attempts(tracking):
    _,_,d=tracking
    for i in range(1,4):saved_attempt(d,'run',i,(i-1)*20,3300+i*5)
    cache={}
    first=d.directory(cache,now=NOW+timedelta(seconds=320))['streams'][0]['player']
    assert first['recent_windows']['5']['pace']['readings']==2
    assert first['recent_windows']['5']['observed']['age_seconds']==280
    later=d.directory(cache,now=NOW+timedelta(seconds=321))['streams'][0]['player']
    assert not later['recent_windows']['5']['available']
    assert later['recent_windows']['5']['last_observed_pace']['age_seconds']==281
    assert later['recent_windows']['10']['observed']['age_seconds']==281


def test_recent_history_limit_fails_closed(tracking,monkeypatch):
    from exp_tracker import rolling_history
    _,_,d=tracking
    for i in range(1,4):saved_attempt(d,'run',i,i*20,3300+i*5)
    monkeypatch.setattr(rolling_history,'MAX_EVENTS',2)
    now=NOW+timedelta(seconds=60)
    history_snapshot=d.recent_snapshot('alpha',now=now)
    assert history_snapshot['recent_history_status']=='history_limit'
    result=player(d.snapshot('alpha',now=now),now=now,recent_snapshot=history_snapshot)
    assert all(w['status']=='history_limit' and not w['available'] and w['gain'] is None for w in result['recent_windows'].values())


def test_recent_window_replays_old_rotation_quarantine_before_retaining_one_hour(tracking):
    _,_,d=tracking
    for n in range(3):
        run=f'quarantine-{n}';cfg=config(run,f'quarantine-{n-1}' if n else None,interval=60)
        if n:d.rotate(f'quarantine-{n-1}',run,'alpha',dict(type='summary',trusted=False,attempts=60,
            interrupted=False,completion_reason='scheduled_rotation',next_run_id=run),cfg)
        else:d.begin(run,'alpha',cfg)
        for i in range(1,61):
            ordinal=n*60+i
            bp=7500 if ordinal==1 else 7510 if ordinal==179 else 7520 if ordinal==180 else 2500
            saved_attempt(d,run,i,ordinal*60,bp)
    now=NOW+timedelta(minutes=180)
    recent=d.recent_snapshot('alpha',now=now)
    assert recent['recent_history_receipt']['context_attempts']==180
    assert len(recent['observations'])==66
    # A cold start at the time-range boundary would accept the repeated 25%.
    assert all(not r['percentage_review']['public_eligible'] for r in recent['observations'][:-2])
    result=recent_windows(recent,dict(value=64),now=now)['60']
    assert result['pace']['readings']==2 and result['pace']['coverage_seconds']['approximate']==60
    assert result['gain']['approximate']==(7520*1497832//10000)-(7510*1497832//10000)


@pytest.mark.parametrize('channel',['telfer1','shiphtur'])
def test_saved_live_failure_checkpoints_are_causal_read_only_regressions(tmp_path,channel):
    source=(Path('private/multi-alpha/runs/20261018T185429Z-fdb644c0/telfer1/096543bcaabb45f18f07f30eebc4111e/capture.jsonl')
        if channel=='telfer1' else Path('private/multi-alpha/runs/20261018T195958Z-eee70469/shiphtur/capture.jsonl'))
    if not source.exists():pytest.skip('Private live-capture fixture unavailable')
    db=tmp_path/'saved.sqlite3'
    with Store(db) as s:
        s.add_channel(channel);c=s.add_character(channel,'Saved review');s.select_character(channel,c);s.start_session(channel,at=NOW)
        d=Diagnostics(s)
        if channel=='telfer1':d.replay(channel,source.parent.parent/'capture.jsonl')
        d.replay(channel,source)
    with Store(db,read_only=True) as s:
        d=Diagnostics(s);raw=d.snapshot(channel,limit=640)['observations']
        run=json.loads(source.read_text().splitlines()[0])['run_id']
        raw=[dict(r,run_interrupted=False) for r in raw if r['run_id']==run]
        stop=24 if channel=='telfer1' else 42
        raw=raw[:stop];end=datetime.fromisoformat(raw[-1]['received_at'])
        from exp_tracker.diagnostic_progress import progress
        rows=project(raw);data=progress(rows,now=end,stale_after_seconds=60,current_run_id=run)
        for r,decision in zip(rows,data['percentage_reviews']):r['percentage_review']=decision
        if channel=='telfer1':
            assert rows[20]['exp_validity']['whole_pair_rejected']
            assert reading(rows[20]) is None and reading(rows[21])['percentage']=='37.69'
            assert all(rows[i]['percentage_review']['progress_eligible'] for i in (17,18,19,21,22,23))
        else:
            assert rows[32]['status']=='stale_local_frame'
            assert not rows[32]['percentage_review']['public_eligible']
            assert rows[33]['experimental_level']['value']==58
            assert rows[33]['experimental_level']['status']=='exp_derived'
            assert rows[33]['percentage_review']['progress_eligible']
            assert all(r['experimental_level']['value']==58 and r['percentage_review']['progress_eligible'] for r in rows[34:42])
        assert not s.db.execute('select 1 from observations').fetchone()
