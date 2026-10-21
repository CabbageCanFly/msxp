"""Public windows subtract level/EXP endpoints; diagnostic graph gaps stay separate."""
from copy import deepcopy
from datetime import datetime,timedelta
from fractions import Fraction
import json
from pathlib import Path

import pytest

from exp_tracker.diagnostics import Diagnostics
from exp_tracker.diagnostic_evidence import full_reading
from exp_tracker.exp_requirements import requirement
from exp_tracker.product import recent_windows,window_comparisons,history,player,fraction,responsive_pace
from exp_tracker.store import Store
from tests.test_endpoint_pace import point,snapshot,missing
from tests.test_diagnostic_progress import NOW
from tests.test_product import tracking


def levels():
    return [point(1,0,1757100,'99.96'),point(2,20,1757288,'99.97'),
        point(3,40,103,'0.01',level=68),point(4,60,435,'0.02',level=68),
        point(5,80,1010,'0.05',level=68)]


def expected_net(snap,now,minutes=1440,level=None):
    """Independent sum of eligible adjacent nonnegative level/EXP coordinates."""
    from exp_tracker.product import reading
    points=[v for r in snap['observations'] if (v:=reading(r)) and v['fresh_at_capture']
        and not r.get('crop_suspect') and not v['simulated'] and v['level']['value'] is not None
        and datetime.fromisoformat(v['timestamp'])<=now]
    def value(p):return int(p['exp']) if p['exp'] is not None else (p['bp']*requirement(p['level']['value'])['to_next']+5000)//10000
    ordered=[]
    for p in points:
        if ordered and p['timestamp']<=ordered[-1]['timestamp']:continue
        ordered.append(p)
    gains=[]
    for first,last in zip(ordered,ordered[1:]):
        a,b=first['level']['value'],last['level']['value']
        before,after=map(datetime.fromisoformat,(first['timestamp'],last['timestamp']))
        if not now-timedelta(minutes=minutes)<=after<=now or after-before>timedelta(minutes=minutes):continue
        if level is not None and (a!=level or b!=level):continue
        if b<a or first.get('manual_epoch')!=last.get('manual_epoch'):continue
        if str(first.get('accounting_scope')).partition(':')[0]!=str(last.get('accounting_scope')).partition(':')[0]:continue
        totals=[requirement(i)['to_next'] for i in range(a,b)]
        if any(t is None for t in totals):continue
        if any(p['exp'] is None and requirement(p['level']['value'])['to_next'] is None for p in (first,last)):continue
        amount=sum(totals)+value(last)-value(first)
        if amount>=0:gains.append(amount)
    return sum(gains) if gains else None


def test_mixed_window_subtracts_level_exp_coordinates():
    rows=levels();snap=snapshot(rows,80);now=NOW+timedelta(seconds=80)
    before=history(snap);strict=window_comparisons(snap,now=now)
    expected=requirement(67)['to_next']-1757100+1010
    for w in recent_windows(snap,None,now=now).values():
        assert w['gain']['approximate']==expected
        assert w['pace']['coverage_seconds']['approximate']==80
        assert w['pace']['estimates']['exp_per_hour']['value']['approximate']==expected*60/w['minutes']
        assert w['pace']['estimates']['percentage_per_hour'] is None
        assert w['pace']['estimates']['exp_per_hour']['transition_gain_included']
        assert w['eta']['level']==68
    assert history(snap)==before and window_comparisons(snap,now=now)==strict
    assert not before[2]['connect_previous']


def test_percentage_endpoints_use_rounded_level_coordinates():
    from exp_tracker.shadow_types import parse_percentage_only
    rows=levels()
    for r in rows:
        text=f'[{r["candidate"]["percentage"]}%]'
        r.update(candidate=None,raw_text=text,percentage_only_candidate=parse_percentage_only(text))
    w=recent_windows(snapshot(rows,80),None,now=NOW+timedelta(seconds=80))['5']
    first=(9996*requirement(67)['to_next']+5000)//10000
    last=(5*requirement(68)['to_next']+5000)//10000
    assert w['gain']['approximate']==requirement(67)['to_next']-first+last
    assert w['pace']['basis']=='displayed_percentage_endpoints'
    assert w['pace']['coverage_seconds']['approximate']==80


def test_current_level_filter_does_not_change_axis_or_cross_level_total_policy():
    snap=snapshot(levels(),80);now=NOW+timedelta(seconds=80);original=deepcopy(snap)
    all_levels=recent_windows(snap,dict(value=68),now=now)['5']
    current=recent_windows(snap,dict(value=68),now=now,current_level_only=True)['5']
    assert all_levels['gain']['approximate']==requirement(67)['to_next']-1757100+1010
    assert current['gain']['approximate']==1010-103
    assert current['pace']['coverage_seconds']['approximate']==40
    assert snap==original


def test_level_up_rate_and_eta_include_known_transition_gain():
    rows=levels()[:3];w=recent_windows(snapshot(rows,40),dict(value=68),now=NOW+timedelta(seconds=40))['5']
    expected=requirement(67)['to_next']-1757100+103
    assert w['gain']['approximate']==expected
    assert w['eta']['level']==68
    assert w['pace']['estimates']['exp_per_hour']['transition_gain_included']


def test_mixed_numeric_percentage_window_uses_one_endpoint_pair():
    from exp_tracker.shadow_types import parse_percentage_only
    rows=levels();last=rows[-1];last.update(candidate=None,raw_text='[0.05%]',percentage_only_candidate=parse_percentage_only('[0.05%]'))
    snap=snapshot(rows,80);w=recent_windows(snap,None,now=NOW+timedelta(seconds=80))['5']
    expected=requirement(67)['to_next']-1757100+(5*requirement(68)['to_next']+5000)//10000
    assert w['gain']['approximate']==expected and w['pace']['basis']=='mixed_exp_and_percentage_endpoints'
    old=recent_windows(snap,None,now=NOW+timedelta(seconds=1000))['5']
    assert old['gain'] is None and old['last_observed_pace']['retained_history']


def test_missing_transition_requirement_does_not_hide_current_numeric_gain():
    rows=levels()[:2]+[point(3,40,100,'0.01',level=100),point(4,60,200,'0.02',level=100)]
    snap=snapshot(rows,60);now=NOW+timedelta(seconds=60)
    w=recent_windows(snap,dict(value=100),now=now)['5']
    assert w['gain']['approximate']==288  # Known intervals remain valid around an unknown transition.
    current=recent_windows(snap,dict(value=100),now=now,current_level_only=True)['5']
    assert current['gain']['approximate']==100 and current['eta'] is None


def test_larger_window_includes_disconnected_new_level_and_gap_time():
    rows=levels()[:2]+[point(3,600,435,'0.02',level=68)]
    windows=recent_windows(snapshot(rows,600),None,now=NOW+timedelta(seconds=600))
    assert windows['5']['gain'] is None
    w=windows['60'];assert w['gain']['approximate']==requirement(67)['to_next']-1757100+435
    assert w['pace']['coverage_seconds']['approximate']==600 and w['eta']['level']==68


@pytest.mark.parametrize('boundary',['restart','session','source','stale','missing','loss'])
def test_acquisition_and_process_boundaries_do_not_exclude_level_up_gain(boundary):
    rows=levels()
    if boundary=='restart':
        for r in rows[2:]:r.update(run_id='restart',event_id=f'restart:{r["index"]}',index=r['index']-2)
    elif boundary in ('session','source'):
        for r in rows[2:]:r['session_id' if boundary=='session' else 'source_identity']=99 if boundary=='session' else 'new-source'
    elif boundary=='stale':rows[2].update(status='stale_local_frame',fresh_at_capture=False)
    elif boundary=='missing':rows.insert(2,missing(8,30))
    else:rows[2]=point(3,40,1757100,'99.96')
    w=recent_windows(snapshot(rows,80),None,now=NOW+timedelta(seconds=80))['5']
    expected=requirement(67)['to_next']-1757100+1010
    assert w['pace'] and w['gain']['approximate']==expected
    assert not w['complete_window']


SAVED=Path('private/multi-alpha/runs')


def replay(store,channel,folders,stop=None,as_of=None):
    cutoff=as_of.isoformat() if as_of else None
    if stop is not None:
        path=SAVED/folders[-1]/channel/'capture.jsonl'
        if not path.exists():pytest.skip('private saved capture unavailable')
        endpoint=next(json.loads(s) for s in path.read_text().splitlines() if json.loads(s).get('type')=='attempt' and json.loads(s).get('index')==stop)
        cutoff=endpoint.get('received_at') or endpoint['attempted_at']
    paths=sorted([p for f in folders for p in (SAVED/f/channel).rglob('capture.jsonl')],
        key=lambda p:json.loads(p.read_text().splitlines()[1])['attempted_at'])
    if cutoff:paths=[p for p in paths if json.loads(p.read_text().splitlines()[1])['attempted_at']<=cutoff]
    if not paths:pytest.skip('private saved capture unavailable')
    store.add_channel(channel);cid=store.add_character(channel,'Saved review');store.select_character(channel,cid)
    store.start_session(channel,at=datetime.fromisoformat(json.loads(paths[0].read_text().splitlines()[1])['attempted_at']))
    d=Diagnostics(store);stamps=[]
    for n,path in enumerate(paths):
        records=[json.loads(s) for s in path.read_text().splitlines()];rid=records[0]['run_id'];d.begin(rid,channel,records[0])
        for r in records[1:]:
            if r['type']=='attempt' and (cutoff is None or (r.get('received_at') or r['attempted_at'])<=cutoff):
                d.append(rid,r);stamps.append(r.get('received_at') or r['attempted_at'])
            elif r['type']=='summary' and n<len(paths)-1:d.append(rid,r)
    return d,datetime.fromisoformat(max(stamps))


def test_saved_level68_checkpoint_includes_old_level_and_restores_after_restart(tmp_path):
    db=tmp_path/'saved.sqlite3'
    with Store(db) as store:
        d,now=replay(store,'telfer1',['20261019T001945Z-65cc75a7','20261019T003226Z-cbe9ba29'],10)
        snap=d.snapshot('telfer1',now=now,limit=640);recent=d.recent_snapshot('telfer1',now=now)
        before=[r[0] for r in store.db.execute('select payload_json from diagnostic_attempts')]
        p=player(snap,now=now,recent_snapshot=recent)
        assert p['recent_windows']['5']['gain']['approximate']==expected_net(recent,now,5)
        assert p['recent_windows']['60']['gain']['approximate']==expected_net(recent,now,60)
        assert p['current_level_windows']['60']['gain']['approximate']==6753
        assert p['recent_windows']['60']['pace']['readings']>=36
        assert p['recent_windows']['60']['eta']['level']==68
        assert p['level_events'][-1]['level']==68
        assert [r[0] for r in store.db.execute('select payload_json from diagnostic_attempts')]==before
        assert not store.db.execute('select 1 from observations').fetchone()
    with Store(db,read_only=True) as store:
        d=Diagnostics(store)
        assert player(d.snapshot('telfer1',now=now,limit=640),now=now,recent_snapshot=d.recent_snapshot('telfer1',now=now))['recent_windows']==p['recent_windows']


def test_saved_65_to_66_and_unobserved_niru_advancement(tmp_path):
    with Store(tmp_path/'saved.sqlite3') as store:
        d,now=replay(store,'telfer1',['20261018T001050Z-b970792e'])
        snap=d.recent_snapshot('telfer1',now=now);w=recent_windows(snap,None,now=now)['60']
        assert w['pace']['levels']==[65,66] and w['gain']['approximate']==expected_net(snap,now,60)
        assert w['pace']['coverage_seconds']==w['pace']['span_seconds']
        d,now=replay(store,'niru',['20261018T211439Z-794bf39d','20261019T000710Z-bda4f628'],34)
        snap=d.recent_snapshot('niru',now=now);w=recent_windows(snap,None,now=now)['60']
        assert w['pace']['levels']==[57]  # level 56 was hours earlier, outside the actual window
        # The crossing 64,808 -> 65,705 interval adds 897 to the old contained total.
        # Numeric endpoints also retain the 875s timeout gap (+34,537) and restart (+806).
        assert w['gain']['approximate']==91765+34537+806+897==192813-64808
        old=d.rolling_history('niru',now=now)
        assert old['tracked_exp']['approximate']>w['gain']['approximate']


def test_unobserved_niru_level_advance_retains_both_sides_but_no_transition_gain(tmp_path):
    with Store(tmp_path/'niru.sqlite3') as store:
        d,_=replay(store,'niru',['20261018T211439Z-794bf39d'],as_of=datetime.fromisoformat('2026-10-18T23:02:00+00:00'))
        now=datetime.fromisoformat('2026-10-18T23:02:00+00:00')
        snap=d.snapshot('niru',now=now,limit=640)
        p=player(snap,now=now,recent_snapshot=d.recent_snapshot('niru',now=now))
        assert p['recent_windows']['5']['gain']['approximate']==9330
        old=p['current_level_windows']['60']['gain']['approximate']
        w=p['recent_windows']['60'];assert old==9330
        assert w['gain']['approximate']==expected_net(d.recent_snapshot('niru',now=now),now,60)
        assert w['pace']['levels']==[56,57] and w['pace']['readings']>=127
        assert w['pace']['coverage_seconds']==w['pace']['span_seconds']
        assert fraction(w['pace']['estimates']['exp_per_hour']['value'])==fraction(w['gain'])  # Selected 60m denominator.
        by_id={r['event_id']:r for r in snap['observations']}
        pace=responsive_pace(d.recent_snapshot('niru',now=now),dict(value=57),now=now,minutes=60,pool_history=True,retain_history=False)
        for edge in pace['intervals']:
            a,b=(by_id[edge[k]] for k in ('first_event_id','last_event_id'))
            assert a['experimental_level']['value']<=b['experimental_level']['value']
            if edge['basis']=='observed_exp_endpoints' and a['experimental_level']['value']==b['experimental_level']['value']:
                assert edge['gain']['approximate']==int(full_reading(b)['exp'])-int(full_reading(a)['exp'])
        assert w['eta']['level']==57 and p['level_events']==[]


def test_same_level_rotation_stays_connected_but_level_reset_never_becomes_negative_gain(tracking):
    from tests.test_diagnostic_history import config,rotate
    from tests.test_diagnostics import attempt
    _,store,d=tracking
    d.begin('rotation-a','alpha',config('rotation-a'))
    def save(run,i,seconds,level,bp):
        exp=bp*requirement(level)['to_next']//10000;pct=f'{bp//100}.{bp%100:02}'
        r=attempt(i);stamp=(NOW+timedelta(seconds=seconds)).isoformat()
        r.update(received_at=stamp,attempted_at=stamp,visual_level=level,visual_status='available',
            neural_level=None,candidate=[exp,float(pct)],neural=dict(text=f'{exp:,}[{pct}%]'),
            frame_sha256=f'{seconds:064x}',localization=dict(count=1),current=True,status='diagnostic_pair')
        d.append(run,r);return exp
    first=last=None
    for i in range(1,61):
        value=save('rotation-a',i,i*3,67,9900+i)
        if first is None:first=value
        last=value
    rotate(d,'rotation-a','rotation-b')
    final_old=save('rotation-b',1,183,67,9962)
    a=save('rotation-b',2,186,68,1);b=save('rotation-b',3,189,68,2)
    now=NOW+timedelta(seconds=189);snap=d.recent_snapshot('alpha',now=now)
    w=recent_windows(snap,None,now=now)['5']
    assert w['pace']['levels']==[67,68] and w['gain']['approximate']==requirement(67)['to_next']-first+b
    assert w['pace']['coverage_seconds']['approximate']==186
    assert not w['complete_window'] and not store.db.execute('select 1 from observations').fetchone()
