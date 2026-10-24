"""Numeric endpoints across bounded missed localization and explicit interrupted restart."""
from dataclasses import asdict
from datetime import datetime,timedelta
import json

import pytest

from exp_tracker.diagnostic_geometry import overlapping_hud_gap
from exp_tracker.exp_requirements import requirement
from exp_tracker.pace_intervals import collect,exp_interval
from exp_tracker.product import reading,player,tracked_statistics
from exp_tracker.shadow_grammar import interpret_exp
from exp_tracker.shadow_view import observation
from exp_tracker.publisher import board as listed
from tests.test_endpoint_pace import point,missing,snapshot
from tests.test_exp_level_inference import display
from tests.test_hud_dedup import candidates,SIZE
from tests.test_product import tracking,NOW,get  # noqa: F401 (pytest fixture)


def geometry_record():
    group=candidates()
    return dict(status='unavailable',reasons=['multiple_huds'],current=False,candidate=None,neural=None,
        visual_level=None,neural_level=None,frame_size=list(SIZE),localization=dict(count=2,candidates=[
            {**c,'regions':{k:asdict(v) for k,v in c['regions'].items()}} for c in group]))


@pytest.mark.parametrize('kind',['separate_hud','disputed_exp_anchor','disjoint_crop','missing_geometry',
    'nonfinite','out_of_bounds','many_candidates','numeric_claim','bad_count'])
def test_genuine_or_unvalidated_ambiguity_cannot_be_an_ordinary_gap(kind):
    r=geometry_record();group=r['localization']['candidates']
    if kind=='separate_hud':group[1]['anchors']['mp']['y']-=200
    elif kind=='disputed_exp_anchor':group[1]['anchors']['exp']['x']+=20
    elif kind=='disjoint_crop':group[1]['regions']['exp'].update(x0=.7,x1=.8)
    elif kind=='missing_geometry':del r['frame_size']
    elif kind=='nonfinite':group[1]['anchors']['hp']['x']=float('nan')
    elif kind=='out_of_bounds':group[0]['regions']['exp']['x1']=1.1
    elif kind=='many_candidates':r['localization'].update(count=9,candidates=group*4+group[:1])
    elif kind=='numeric_claim':r['neural']=dict(text='123[0.01%]')
    else:r['localization']['count']=2.0
    assert not overlapping_hud_gap(r)
    assert not observation(r)['overlapping_hud_gap']


def numeric(index,seconds,exp=371476,**changes):
    r=point(index,seconds,exp,display(exp,requirement(69)['to_next']),level=69)
    r.update(source_identity='c'*64,coordinator_instance='a'*32,**changes)
    return r


def edges(rows,end=60):
    return collect(snapshot(rows,end),now=NOW+timedelta(seconds=end),read=reading,max_interval_seconds=300)['intervals']


def localization_miss():
    r=missing(2,20);stamp=(NOW+timedelta(seconds=20)).isoformat()
    r.update(status='unavailable',received_at=stamp,capture_acquired=True,hud_count=2,frame_sha256='2'*64,
        reasons=['multiple_huds'],local_age_seconds=2,source_identity='c'*64,coordinator_instance='a'*32,
        overlapping_hud_gap=observation(geometry_record())['overlapping_hud_gap'])
    return r


@pytest.mark.parametrize('kind',['ordinary','percentage_endpoint','separate_hud','stale','missing_receipt','duplicate','contradiction','level','session'])
def test_localization_gap_requires_supported_same_level_numeric_endpoints(kind):
    rows=[numeric(1,0),localization_miss(),numeric(3,46,373179)]
    if kind=='percentage_endpoint':
        rows[-1].update(candidate=None,raw_text='[19.08%]')
    elif kind=='separate_hud':rows[1]['overlapping_hud_gap']=False
    elif kind=='stale':rows[1]['local_age_seconds']=16
    elif kind=='missing_receipt':rows[1].update(received_at=None,capture_acquired=False)
    elif kind=='duplicate':rows[1]['frame_sha256']=rows[0]['frame_sha256']
    elif kind=='contradiction':rows.insert(1,numeric(4,10,10))
    elif kind=='level':rows[-1]['visual_level']=rows[-1]['neural_level']['level']=70;rows[-1]['neural_level']['text']='70'
    elif kind=='session':rows[-1]['session_id']=2
    result=edges(rows)
    if kind=='ordinary':
        assert len(result)==1 and exp_interval(result[0])['value']['approximate']==1703
        assert result[0]['missing_event_ids']==['run:2'] and result[0]['kind']=='endpoint_supported'
    else:assert not result


def restart_rows():
    old=numeric(1,0,run_interrupted=True)
    stop=missing(2,20);stop.update(source_identity='c'*64,coordinator_instance='a'*32,
        run_interrupted=True,reasons=['operator_interrupted'])
    new=numeric(1,27,373760,run_id='restart',event_id='restart:1',run_start_reason='process_start')
    new.update(coordinator_instance='b'*32,frame_sha256='3'*64)
    return [old,stop,new]


@pytest.mark.parametrize('kind',['ordinary','session','character','source','file','no_source_identity','not_interrupted',
    'not_operator_stop','unknown_start','same_process','missing_process','not_first','decrease','level','stale',
    'duplicate','too_long','overlapping_time','percentage_endpoint','competing_hud'])
def test_short_interrupted_restart_needs_explicit_continuity(kind):
    rows=restart_rows();a,stop,b=rows
    if kind=='session':b['session_id']=2
    elif kind=='character':b['character_id']=2
    elif kind=='source':b['source_identity']='d'*64
    elif kind=='file':
        for r in rows:r['source_kind']='file'
    elif kind=='no_source_identity':
        for r in rows:r['source_identity']=None
    elif kind=='not_interrupted':stop['run_interrupted']=False
    elif kind=='not_operator_stop':stop['reasons']=['network_unavailable']
    elif kind=='unknown_start':b['run_start_reason']=None
    elif kind=='same_process':b['coordinator_instance']='a'*32
    elif kind=='missing_process':b['coordinator_instance']=None
    elif kind=='not_first':b['index']=2
    elif kind=='decrease':b.update(candidate=dict(exp='370000',percentage='18.92'),raw_text='370,000[18.92%]')
    elif kind=='level':b['visual_level']=b['neural_level']['level']=70;b['neural_level']['text']='70'
    elif kind=='stale':b['fresh_at_capture']=False
    elif kind=='duplicate':b['frame_sha256']=a['frame_sha256']
    elif kind in ('too_long','overlapping_time'):
        stamp=(NOW+timedelta(seconds=301 if kind=='too_long' else 15)).isoformat();b.update(received_at=stamp,attempted_at=stamp)
    elif kind=='percentage_endpoint':b.update(candidate=None,raw_text='[19.11%]')
    elif kind=='competing_hud':
        bad=localization_miss();bad.update(event_id='run:3',index=3,overlapping_hud_gap=False)
        rows.insert(1,bad)
    result=edges(rows,end=400)
    if kind=='ordinary':
        assert len(result)==1 and exp_interval(result[0])['value']['approximate']==2284
        assert exp_interval(result[0])['restart']=='interrupted_same_assignment'
    else:assert not result


def test_numeric_gap_state_streaming_matches_full_replay():
    rows=[numeric(1,0),localization_miss(),numeric(3,46,373179)];snap=snapshot(rows,60)
    state={};actual=[]
    for row in snap['observations']:
        actual+=collect(dict(observations=[row],percentage_progress=dict(percentage_reviews=[row['percentage_review']])),
            now=NOW+timedelta(seconds=60),read=reading,max_interval_seconds=300,state=state)['intervals']
    assert actual==edges(rows)


@pytest.mark.parametrize('raw',['P384,812119.68%1','P384,812[19.68%]','P384.812119.68%1'])
def test_label_tail_recovers_complete_pair_without_changing_digits(raw):
    value=interpret_exp(raw);proposal=value['full_exp']['proposals'][0]
    assert value['full_exp']['classification']=='unique_proposal'
    assert proposal['reading']==dict(kind='full_exp_pair',exp='384812',percentage='19.68')
    repaired=list(raw)
    for e in proposal['edits']:
        assert repaired[e['index']]==e['old'];repaired[e['index']]=e['new']
    assert ''.join(repaired)==proposal['interpretation']
    assert proposal['edits'][0]['category']=='exp_label_tail' and not proposal['trusted']
    assert value['percentage']['proposals'][0]['reading']['percentage']=='19.68'


@pytest.mark.parametrize('raw',['P384,,812[19.68%1','P384,8SS[19.68%1',
    'P999,999,999,999,999,999,999119.68%1'])
def test_clear_percentage_survives_unusable_absolute_exp(raw):
    value=interpret_exp(raw)
    assert not value['full_exp']['proposals']
    assert value['percentage']['classification']=='unique_proposal'
    assert value['percentage']['proposals'][0]['reading']['percentage']=='19.68'


@pytest.mark.parametrize('raw',['PP384,812119.68%1','p384,812119.68%1','P384,8SS119.68%1',
    'P384812119.68%1','P384,812119.6%1','P384,812119.68X1','P384,812119.68%1 junk',
    'P384,812119.68%1 386,552[19.76%]','P384,8SS[19.68%1[19.76%]','P19.68%1'])
def test_label_tail_does_not_choose_ambiguous_or_incomplete_fields(raw):
    value=interpret_exp(raw)
    assert not value['full_exp']['proposals'] and not value['percentage']['proposals']


def test_source_clipping_vetoes_absolute_recovery_but_not_clear_percentage():
    value=interpret_exp('P384,812119.68%1',source_complete=False)
    assert not value['full_exp']['proposals'] and value['percentage']['proposals'][0]['reading']['percentage']=='19.68'


def test_percentage_only_label_recovery_retains_level_and_reaches_public_projection(tracking):
    from tests.test_exp_level_product import attempt
    _,_,d=tracking
    attempt(d,1,exp=383748,pct='19.62')
    attempt(d,2,pct='19.68',neural=dict(text='P384,8SS[19.68%1'),status='malformed_or_unavailable')
    p=get(d,15)
    assert p['display_level']['value']==69 and p['reading']['percentage']=='19.68'
    assert p['reading']['exp'] is None and p['reading']['evidence']=='grammar_recovered'
    assert d.snapshot('alpha',now=NOW+timedelta(seconds=15))['observations'][-1]['percentage_review']['progress_eligible']


def saved_replay(store):
    from tests.test_cross_level_product import replay,SAVED
    folders=['20261019T095936Z-ef8a3750','20261019T103818Z-62816188']
    if not (SAVED/folders[1]/'streamer_a/capture.jsonl').is_file():pytest.skip('private CharA capture unavailable')
    now=datetime.fromisoformat('2026-10-19T10:40:56.881611+00:00')
    return replay(store,'streamer_a',folders,as_of=now)


def test_saved_streamer_a_boundary_and_recovered_gains_and_unchanged_source_records(tracking,monkeypatch):
    import exp_tracker.server as server_module
    from tests.test_server import request
    path,store,_=tracking;d,now=saved_replay(store)
    raw=[r[0] for r in store.db.execute('select payload_json from diagnostic_attempts order by id')]
    snap=d.snapshot('streamer_a',now=now,limit=640);recent=d.recent_snapshot('streamer_a',now=now)
    rolling=d.rolling_history('streamer_a',now=now);p=tracked_statistics(player(snap,now=now,recent_snapshot=recent),rolling,now=now)
    window=rolling['windows']['5'];assert window['gain']['approximate']==17175+987
    assert p['recent_windows']['5']['gain']==window['gain']
    gains=[g for g in rolling['chart_intervals'] if g['start']>=window['window_start']]
    restored=[g for g in gains if g['value']['approximate'] in (1703,2284,3419)]
    assert sorted(g['value']['approximate'] for g in restored)==[1703,2284,3419]
    assert sum(g['value']['approximate'] for g in gains if g not in restored)==9769
    assert sum(g['value']['approximate'] for g in gains)==388651-371476
    crossing=[g for g in rolling['chart_intervals'] if g['start']<window['window_start']<=g['end']]
    assert len(crossing)==1 and crossing[0]['value']['approximate']==371476-370489==987
    assert sum(g['value']['approximate'] for g in gains+crossing)==window['gain']['approximate']
    collected=collect(recent,now=now,read=reading,max_interval_seconds=300)['intervals']
    assert [exp_interval(g)['restart'] for g in collected if g.get('restart')]==['interrupted_same_assignment']
    values=[rolling['windows'][m]['gain']['approximate'] for m in ('5','10','15','30','60')]
    assert values==sorted(values)
    tail=next(r for r in recent['observations'] if r['event_id']=='b607401ffc2948b4b54f612e04dab645:5')
    assert reading(tail)['exp']=='384812' and reading(tail)['percentage']=='19.68'
    assert reading(tail)['evidence']=='grammar_recovered' and tail['raw_text']=='P384,812119.68%1'
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return now
    monkeypatch.setattr(server_module,'datetime',Clock)
    with server_module.create_server(path,port=0,diagnostic_dashboard=True,background=True) as server:
        server.publisher.settle()
        card=json.loads(request((server,None),'/api/players/streamer_a')[2])
        home=json.loads(request((server,None),'/api/players')[2])
        chart=json.loads(request((server,None),'/api/players/streamer_a/history')[2])
        assert card['player']['recent_windows']['5']['gain']==window['gain']
        assert next(r for r in home['players'] if r['channel']=='streamer_a')['recent_windows']==listed(card['player'])['recent_windows']
        assert chart['windows']['5']['gain']==window['gain']
    assert raw==[r[0] for r in store.db.execute('select payload_json from diagnostic_attempts order by id')]
    assert not store.db.execute('select 1 from observations').fetchone()
