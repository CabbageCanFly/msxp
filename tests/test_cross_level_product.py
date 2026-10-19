"""Elapsed windows retain independent EXP intervals on both sides of a level change."""
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


def test_mixed_window_sums_independent_exp_not_cross_level_percentages():
    rows=levels();original=deepcopy(rows);snap=snapshot(rows,80);now=NOW+timedelta(seconds=80)
    strict=window_comparisons(snap,now=now);chart=history(snap)
    windows=recent_windows(snap,None,now=now)
    for w in windows.values():
        pace=w['pace']
        assert pace['levels']==[67,68] and pace['readings']==4
        assert w['gain']['approximate']==188+575
        assert pace['coverage_seconds']['approximate']==40  # first new-level reading awaits confirmation
        assert pace['estimates']['exp_per_hour']['value']['approximate']==763*90
        assert pace['estimates']['percentage_per_hour'] is None
        assert w['observed']['difference_percentage_points'] is None
        assert w['eta']['level']==68
        assert w['eta']['estimate']['seconds']['approximate']==pytest.approx((requirement(68)['to_next']-1010)/763*40)
        assert not pace['estimates']['exp_per_hour']['transition_gain_included']
    assert strict==window_comparisons(snap,now=now) and chart==history(snap)
    assert not chart[2]['connect_previous'] and chart[2]['gain'] is None
    assert rows==original


def test_each_percentage_interval_uses_its_own_level_requirement_and_bounds():
    rows=levels()
    from exp_tracker.shadow_grammar import interpret_exp
    for r in rows:
        text=f'[{r["candidate"]["percentage"]}%]'
        r.update(candidate=None,raw_text=text,percentage_only_candidate=interpret_exp(text)['strict_percentage_only'])
    now=NOW+timedelta(seconds=80);w=recent_windows(snapshot(rows,80),None,now=now)['5']
    expected=Fraction(requirement(67)['to_next'],10000)+Fraction(3*requirement(68)['to_next'],10000)
    assert fraction(w['gain'])==expected
    rate=w['pace']['estimates']['exp_per_hour']
    assert fraction(rate['value'])==expected*90
    assert all(fraction(b['lower'])<=fraction(rate['value'])<=fraction(b['upper']) for b in rate['hypotheses'].values())
    assert {r['level'] for r in rate['requirements']}=={67,68}


def test_current_level_filter_does_not_change_axis_or_cross_level_total_policy():
    snap=snapshot(levels(),80);now=NOW+timedelta(seconds=80)
    all_levels=recent_windows(snap,None,now=now)
    only=recent_windows(snap,dict(value=67,display_only=True),now=now,current_level_only=True)
    for m in all_levels:
        assert only[m]['start']==all_levels[m]['start'] and only[m]['end']==all_levels[m]['end']
        assert only[m]['pace']['levels']==[68] and only[m]['gain']['approximate']==575
        assert only[m]['scope']=='current_level_only'


def test_new_level_eta_can_use_previous_level_rate_without_counting_transition():
    rows=levels()[:4];now=NOW+timedelta(seconds=60)
    assert recent_windows(snapshot(rows[:3],40),None,now=NOW+timedelta(seconds=40))['5']['eta'] is None
    w=recent_windows(snapshot(rows,60),None,now=now)['5']
    assert w['gain']['approximate']==188 and w['pace']['levels']==[67]
    assert w['eta']['level']==68 and w['eta']['estimated_at']==rows[-1]['received_at']
    assert w['eta']['estimate']['seconds']['approximate']==pytest.approx((requirement(68)['to_next']-435)/188*20)
    assert w['eta']['historical']  # rate came from the previous level
    # The old current-level-only mode cannot make a new rate from one point.
    assert not recent_windows(snapshot(rows,60),None,now=now,current_level_only=True)['5']['available']


def test_mixed_integer_percentage_bounds_preserve_each_basis_and_expire_by_time():
    rows=levels()+[point(6,100,2000,'0.11',level=68),point(7,120,3010,'0.16',level=68)]
    from exp_tracker.shadow_grammar import interpret_exp
    rows[4].update(candidate=None,raw_text='[0.05%]',percentage_only_candidate=interpret_exp('[0.05%]')['strict_percentage_only'])
    w=recent_windows(snapshot(rows,120),None,now=NOW+timedelta(seconds=120))['5']
    expected=188+Fraction(9*requirement(68)['to_next'],10000)+1010
    assert fraction(w['gain'])==expected
    rate=w['pace']['estimates']['exp_per_hour']
    assert all(fraction(b['lower'])<=fraction(rate['value'])<=fraction(b['upper']) for b in rate['hypotheses'].values())
    expired=recent_windows(snapshot(rows,1000),None,now=NOW+timedelta(seconds=1000))['5']
    assert not expired['available'] and expired['eta']['historical']
    assert expired['eta']['estimate']==w['eta']['estimate']


def test_unsupported_current_requirement_retains_older_rate_but_cannot_make_eta():
    rows=levels()[:2]+[point(3,40,100,'0.01',level=100),point(4,60,200,'0.02',level=100)]
    w=recent_windows(snapshot(rows,60),None,now=NOW+timedelta(seconds=60))['5']
    assert w['gain']['approximate']==188 and w['pace']['levels']==[67]
    assert w['eta'] is None


def test_disconnected_new_level_can_use_older_selected_window_rate_not_its_missing_gain():
    rows=levels()[:2]+[point(3,600,435,'0.02',level=68)]
    rows[-1]['neural_level']=None
    windows=recent_windows(snapshot(rows,600),None,now=NOW+timedelta(seconds=600))
    assert not windows['5']['available'] and windows['5']['eta'] is None
    w=windows['60']
    assert w['gain']['approximate']==188 and w['eta']['level']==68
    assert w['eta']['historical'] and w['eta']['estimated_at']==rows[-1]['received_at']
    assert w['eta']['rate_observed_at']==rows[1]['received_at'] and w['eta']['rate_age_seconds']==580
    assert w['pace']['coverage_seconds']['approximate']==20


@pytest.mark.parametrize('boundary',['restart','session','source','stale','missing','loss'])
def test_unsafe_boundary_never_adds_a_transition_interval(boundary):
    rows=levels()
    if boundary=='restart':
        for r in rows[2:]:r.update(run_id='restart',event_id=f'restart:{r["index"]}',index=r['index']-2)
    elif boundary in ('session','source'):
        for r in rows[2:]:r['session_id' if boundary=='session' else 'source_identity']=99 if boundary=='session' else 'new-source'
    elif boundary=='stale':rows[2].update(status='stale_local_frame',fresh_at_capture=False)
    elif boundary=='missing':rows.insert(2,missing(8,30))
    else:rows[2]=point(3,40,1757100,'99.96')
    w=recent_windows(snapshot(rows,80),None,now=NOW+timedelta(seconds=80))['5']
    assert w['pace'] and w['gain']['approximate']<=1095
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
        assert p['recent_windows']['5']['gain']['approximate']==pytest.approx(12124.697)
        assert p['recent_windows']['60']['gain']['approximate']==pytest.approx(54663.82)
        assert p['current_level_windows']['60']['gain']['approximate']==5445
        assert p['recent_windows']['60']['pace']['readings']==35
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
        assert w['pace']['levels']==[65,66] and w['gain']['approximate']==pytest.approx(13444.9739)
        assert w['pace']['coverage_seconds']['approximate']==pytest.approx(228.845713)
        d,now=replay(store,'niru',['20261018T211439Z-794bf39d','20261019T000710Z-bda4f628'],34)
        snap=d.recent_snapshot('niru',now=now);w=recent_windows(snap,None,now=now)['60']
        assert w['pace']['levels']==[57]  # level 56 was hours earlier, outside the actual window
        assert w['gain']['approximate']==91765
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
        assert w['gain']['approximate']==102874
        assert w['pace']['levels']==[56,57] and w['pace']['readings']==127
        assert w['pace']['coverage_seconds']['approximate']==pytest.approx(2655.286408)
        assert w['pace']['estimates']['exp_per_hour']['value']['approximate']==pytest.approx(139475.12361913163)
        by_id={r['event_id']:r for r in snap['observations']}
        pace=responsive_pace(d.recent_snapshot('niru',now=now),dict(value=57),now=now,minutes=60,pool_history=True,retain_history=False)
        for edge in pace['intervals']:
            a,b=(by_id[edge[k]] for k in ('first_event_id','last_event_id'))
            assert a['experimental_level']['value']==b['experimental_level']['value']
            if edge['basis']=='observed_exp_endpoints':
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
    assert w['pace']['levels']==[67,68] and w['gain']['approximate']==final_old-first+b-a
    assert w['pace']['coverage_seconds']['approximate']==183
    assert not w['complete_window'] and not store.db.execute('select 1 from observations').fetchone()
