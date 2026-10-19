"""Public gains use displayed observations, never diagnostic connection eligibility."""
from datetime import datetime,timedelta
import json

import pytest

from exp_tracker.exp_requirements import requirement
from exp_tracker.product import recent_windows,player,tracked_statistics,reading,fraction
from tests.test_endpoint_pace import point,missing,snapshot,NOW
from tests.test_observed_endpoint_totals import numeric
from tests.test_product import tracking
from tests.test_cross_level_product import replay,SAVED


def window(rows,seconds=300,*,level=None,current=False):
    return recent_windows(snapshot(rows,seconds),dict(value=level) if level else None,
        now=NOW+timedelta(seconds=seconds),current_level_only=current)['5']


@pytest.mark.parametrize('change',[{},dict(run_id='restarted',event_id='restarted:4',source_identity=None),
    dict(source_kind='file',run_id='seek',event_id='seek:4'),dict(session_id=2),dict(coordinator_instance='new')])
def test_numeric_endpoints_ignore_acquisition_and_process_metadata(change):
    rows=[numeric(1,0,10000),numeric(2,60,11000),missing(3,120),dict(numeric(4,300,15000),**change)]
    w=window(rows)
    assert w['gain']['approximate']==5000
    assert w['observed']['coverage_seconds']['approximate']==300
    assert w['pace']['estimates']['exp_per_hour']['value']['approximate']==60000


def percentage(index,seconds,bp,level=69,**change):
    from exp_tracker.shadow_types import parse_percentage_only
    r=point(index,seconds,0,f'{bp//100}.{bp%100:02}',level=level,**change)
    r.update(candidate=None,raw_text=f'[{bp//100}.{bp%100:02}%]',status='diagnostic_percentage_only')
    r['percentage_only_candidate']=parse_percentage_only(r['raw_text'])
    return r


def test_percentage_only_restart_uses_rounded_graph_coordinates():
    rows=[percentage(1,0,6545),missing(2,30),percentage(3,276,6627,run_id='restart',event_id='restart:1')]
    w=window(rows,276)
    assert w['gain']['approximate']==1296076-1280038==16038
    assert w['pace']['coverage_seconds']['approximate']==276
    assert w['pace']['basis']=='displayed_percentage_endpoints'


def test_mixed_interior_percentage_does_not_replace_numeric_window_endpoints():
    rows=[numeric(1,0,10000),percentage(2,120,54),numeric(3,300,15000)]
    assert window(rows)['gain']['approximate']==5000


@pytest.mark.parametrize('clock,expected',[(300,5000),(300.000001,4000),(360,4000),(601,None)])
def test_exact_window_boundary_and_partial_history(clock,expected):
    rows=[numeric(1,0,10000),numeric(2,60,11000),numeric(3,300,15000)]
    w=window(rows,clock)
    assert (w['gain']['approximate'] if w['gain'] else None)==expected
    if expected==4000:
        assert w['observed']['start']==rows[1]['received_at']
        assert w['observed']['span_seconds']['approximate']==240
    if expected is None:assert w['reason']=='two_distinct_observation_times_required'


def test_level_up_uses_requirement_and_current_level_uses_its_observed_endpoints():
    total=requirement(69)['to_next']
    rows=[point(1,0,total-100,'99.99',level=69),point(2,30,200,'0.01',level=70),point(3,90,300,'0.01',level=70)]
    all_levels=window(rows,90)
    assert all_levels['gain']['approximate']==400
    assert all_levels['pace']['estimates']['exp_per_hour']['transition_gain_included']
    current=window(rows,90,level=70,current=True)
    assert current['gain']['approximate']==100 and current['observed']['coverage_seconds']['approximate']==60
    multiple=[rows[0],point(4,90,300,'0.01',level=71)]
    assert window(multiple,90)['gain']['approximate']==requirement(70)['to_next']+400


def test_missing_transition_table_is_explicit_but_current_numeric_level_still_works():
    rows=[point(1,0,100,'0.01',level=90),point(2,30,200,'0.01',level=91),point(3,60,300,'0.01',level=91)]
    w=window(rows,60)
    assert w['gain'] is None and w['reason']=='level_transition_requirement_unavailable'
    assert window(rows,60,level=91,current=True)['gain']['approximate']==100


def test_exp_loss_is_net_not_a_sum_of_only_positive_intervals():
    rows=[numeric(1,0,11000),numeric(2,60,10999),numeric(3,120,12000)]
    assert window(rows,120)['gain']['approximate']==1000
    w=window(rows[:2],60)
    assert w['gain'] is None and w['reason']=='observed_exp_decrease'


def test_no_five_second_rate_gate_and_stationary_observations_are_useful():
    rows=[numeric(1,0,10000),numeric(2,1,10000)]
    w=window(rows,1)
    assert w['gain']['approximate']==0 and w['pace']['coverage_seconds']['approximate']==1
    assert w['pace']['estimates']['exp_per_hour']['value']['approximate']==0


def test_current_level_only_follows_the_visible_possible_level_without_changing_inference(tracking):
    from tests.test_exp_level_product import stream
    _,_,d=tracking;stream(d,until=7);now=NOW+timedelta(seconds=90)
    p=player(d.snapshot('alpha',now=now),now=now)
    assert p['display_level']['value']==42  # Provenance still holds the supported old level.
    assert p['level_context']['transition']['to_level']==43
    assert all(w['gain'] is None for w in p['current_level_windows'].values())
    assert d.rolling_history('alpha',now=now)['current_level']==43


@pytest.mark.parametrize('clock,folders,expected',[
    ('2026-10-19T14:42:43.515014+00:00',['20261019T143653Z-028bbd29','20261019T144105Z-03f4aa88'],16038),
    ('2026-10-19T11:28:56.524233+00:00',['20261019T103818Z-62816188','20261019T112644Z-9a0733f3','20261019T112802Z-be8257c7'],16977),
    ('2026-10-19T10:40:56.881611+00:00',['20261019T095936Z-ef8a3750','20261019T103818Z-62816188'],17175)])
def test_exact_real_windows_public_cards_api_and_selected_graph(tracking,monkeypatch,clock,folders,expected):
    import exp_tracker.server as http
    from tests.test_server import request
    if any(not (SAVED/folder/'telfer1/capture.jsonl').exists() for folder in folders):pytest.skip('Private saved capture unavailable')
    path,store,_=tracking;now=datetime.fromisoformat(clock);d,_=replay(store,'telfer1',folders,as_of=now)
    raw=[r[0] for r in store.db.execute('select payload_json from diagnostic_attempts order by id')]
    snap=d.recent_snapshot('telfer1',now=now);rolling=d.rolling_history('telfer1',now=now)
    p=tracked_statistics(player(d.snapshot('telfer1',now=now),now=now,recent_snapshot=snap),rolling,now=now)
    w=p['recent_windows']['5'];assert w['gain']['approximate']==expected
    assert w['pace']['total_gain']==w['gain']
    assert fraction(w['pace']['estimates']['exp_per_hour']['value'])==expected*3600/fraction(w['observed']['span_seconds'])
    graph=[g for g in rolling['chart_intervals'] if datetime.fromisoformat(g['start'])>=now-timedelta(minutes=5)]
    assert sum(fraction(g['value']) for g in graph)==expected
    if expected==16038:
        public_only=next(r for r in snap['observations'] if r['event_id']=='94320e2c03f849c6a0d4454a456b24d9:2')
        assert reading(public_only) and not public_only['percentage_review']['progress_eligible']
        assert w['observed']['start']=='2026-10-19T14:38:07.930824+00:00'
        assert w['observed']['span_seconds']['approximate']==275.58419
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return now
    monkeypatch.setattr(http,'datetime',Clock)
    with http.create_server(path,port=0,diagnostic_dashboard=True,background=True) as server:
        server.publisher.settle()
        detail=json.loads(request((server,None),'/api/players/telfer1')[2])
        home=json.loads(request((server,None),'/api/players')[2])
        chart=json.loads(request((server,None),'/api/players/telfer1/history')[2])
        assert detail['player']['recent_windows']['5']['gain']['approximate']==expected
        assert next(p for p in home['players'] if p['channel']=='telfer1')['recent_windows']['5']['gain']['approximate']==expected
        assert chart['windows']['5']['gain']['approximate']==expected
    assert raw==[r[0] for r in store.db.execute('select payload_json from diagnostic_attempts order by id')]
    assert not store.db.execute('select 1 from observations').fetchone()
