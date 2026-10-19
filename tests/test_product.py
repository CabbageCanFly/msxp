from datetime import datetime,timedelta,timezone
import json

import pytest

from exp_tracker.store import Store
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.product import player
from exp_tracker.publisher import public
from exp_tracker.server import create_server
from tests.test_server import request

NOW=datetime(2026,1,1,tzinfo=timezone.utc)


@pytest.fixture
def tracking(tmp_path):
    path=tmp_path/'tracker.sqlite3'
    with Store(path) as store:
        store.add_channel('alpha');char=store.add_character('alpha','Test character')
        store.select_character('alpha',char);store.start_session('alpha',at=NOW)
        diagnostic=Diagnostics(store)
        diagnostic.begin('run','alpha',dict(type='configuration',trusted=False,interval=15,source_kind='twitch'))
        yield path,store,diagnostic


def append(diagnostic,index,text,**changes):
    stamp=(NOW+timedelta(seconds=(index-1)*15)).isoformat()
    record=dict(type='attempt',trusted=False,index=index,attempted_at=stamp,received_at=stamp,current=True,
        source=dict(kind='twitch',channel='alpha'),status='diagnostic_percentage_only',neural=dict(text=text),
        visual_level=64,visual_status='available',neural_level=dict(text='64',level=64,status='numeric_candidate',score=.99),localization=dict(count=1))
    record.update(changes);diagnostic.append('run',record)


def get(diagnostic,seconds=30):
    return player(diagnostic.snapshot('alpha',now=NOW+timedelta(seconds=seconds)),now=NOW+timedelta(seconds=seconds))


def test_percentage_only_drives_estimated_rates_and_eta_without_absolute_exp(tracking):
    _,store,d=tracking
    before=store.state('alpha',as_of=NOW)
    for i,pct in enumerate(('33.00','33.05','33.10'),1):append(d,i,f'[{pct}%]')
    result=get(d)
    assert result['reading']['exp'] is None and result['reading']['percentage']=='33.10'
    rates=result['estimates']
    assert rates['percentage_per_hour']['value']['approximate']==12
    assert rates['exp_per_hour']['value']['approximate']==pytest.approx(179739.84)
    assert rates['exp_per_hour']['requirement']['status']=='community_provisional'
    assert rates['eta']['seconds']['approximate']==pytest.approx(20070)
    assert rates['eta']['hypotheses']['nearest_half_up']['lower_seconds']['approximate']<20070
    assert rates['eta']['hypotheses']['truncation']['upper_seconds']['approximate']>20070
    assert store.state('alpha',as_of=NOW)==before
    assert not store.db.execute('SELECT 1 FROM observations').fetchone()


def test_reading_is_coherent_and_never_pairs_old_exp_with_new_percentage(tracking):
    _,_,d=tracking
    append(d,1,'100[33.00%]',candidate=[100,33.0],status='diagnostic_pair')
    # Original syntax is preserved, but this intentionally inconsistent integer is withheld.
    assert get(d,0)['reading']['exp'] is None
    assert get(d,0)['reading']['exp_validity']['status']=='invalid'
    assert d.snapshot('alpha',now=NOW)['observations'][0]['candidate']['exp']=='100'
    append(d,2,'[33.05%]')
    assert get(d,15)['reading']['exp'] is None
    append(d,3,'500,000133.10%1',status='malformed_or_unavailable')
    recovered=get(d)['reading']
    assert recovered['exp'] is None and recovered['evidence']=='grammar_recovered'
    assert recovered['exp_validity']['status']=='invalid'  # syntactic recovery is not numeric validation
    append(d,4,'5,031[33,15%]',status='malformed_or_unavailable')
    assert get(d,45)['reading']['exp'] is None
    assert get(d,45)['reading']['percentage']=='33.15'


def test_failed_stale_conflicting_and_insufficient_readings_keep_values_without_estimates(tracking):
    _,_,d=tracking
    append(d,1,'[33.00%]');assert get(d,0)['estimates']['eta'] is None
    append(d,2,'[33.05%]');append(d,3,'[33.10%]')
    assert get(d)['estimates']['exp_per_hour']
    assert get(d,100)['stale'] and get(d,100)['estimates']['exp_per_hour'] is None
    append(d,4,None,status='capture_failed',received_at=None,current=False)
    failed=get(d,45)
    assert failed['reading']['percentage']=='33.10' and failed['estimates']['eta'] is None
    append(d,5,'[33.20%]',neural_level=dict(text='54',level=54,status='numeric_candidate',score=.99))
    conflict=get(d,60)
    assert conflict['reading']['level']['value'] is None and conflict['reading']['level']['status']=='conflict'
    assert conflict['estimates']['percentage_per_hour'] is None


def test_zero_display_change_has_pace_bounds_but_no_eta(tracking):
    _,_,d=tracking
    for i in range(1,4):append(d,i,'[33.00%]')
    result=get(d)
    assert result['estimates']['exp_per_hour']['value']['approximate']==0
    assert result['estimates']['eta'] is None
    assert result['estimates']['percentage_per_hour']['nearest_half_up']['lower']['approximate']<0


@pytest.mark.parametrize('level', [99,100,200])
def test_missing_or_disputed_requirement_does_not_invent_exp_rates(tracking,level):
    _,_,d=tracking
    for i,pct in enumerate(('33.00','33.05','33.10'),1):
        append(d,i,f'[{pct}%]',visual_level=level,
            neural_level=dict(text=str(level),level=level,status='numeric_candidate',score=.99))
    result=get(d)
    assert result['reading']['level']['value']==level
    assert result['estimates']['percentage_per_hour']['value']['approximate']==12
    assert result['estimates']['exp_per_hour'] is None


def test_quantization_ambiguity_prevents_eta_even_with_small_positive_change(tracking):
    _,_,d=tracking
    for i,pct in enumerate(('33.00','33.00','33.01'),1):append(d,i,f'[{pct}%]')
    result=get(d)
    assert result['estimates']['percentage_per_hour']['value']['approximate']>0
    assert result['estimates']['eta'] is None


def test_product_http_reuses_sqlite_and_keeps_trusted_and_advanced_routes(tracking):
    path,store,d=tracking
    append(d,1,'[33.00%]')
    with create_server(path,port=0,diagnostic_dashboard=True) as server:
        for route in ('/','/streams','/stream/alpha','/live/overlay/alpha','/dev/streams','/dashboard/alpha'):
            status,headers,_=request((server,None),route)
            assert status==200 and headers['Cache-Control']=='no-store'
        value=json.loads(request((server,None),'/api/players')[2])['players'][0]
        assert value['reading']['percentage']=='33.00' and value['reading']['exp'] is None
        assert 'raw_text' not in json.dumps(value) and 'source_identity' not in json.dumps(value)
        assert request((server,None),'/api/players/alpha','POST')[0]==405
        assert request((server,None),'/api/players/missing')[0]==404
        assert request((server,None),'/api/players/bad!')[0]==400
        assert request((server,None),'/api/streams/alpha/state')[0]==200
        assert request((server,None),'/overlay/alpha')[0]==200
        assert not store.db.execute('SELECT 1 FROM observations').fetchone()


def test_product_and_diagnostic_apis_share_integer_veto_without_rewriting_saved_pair(tracking):
    path,store,d=tracking
    neural=dict(text='65',level=65,status='numeric_candidate',score=.97,preprocessing='neutral4')
    append(d,1,'713,015[45.13%]',candidate=[713015,45.13],status='diagnostic_pair',visual_level=65,neural_level=neural)
    append(d,2,'2,458[45.14%]',candidate=[2458,45.14],status='diagnostic_pair',visual_level=63,neural_level=neural)
    payloads=[r[0] for r in store.db.execute('select payload_json from diagnostic_attempts')]
    with create_server(path,port=0,diagnostic_dashboard=True) as server:
        p=json.loads(request((server,None),'/api/players/alpha')[2])['player']['reading']
        board=json.loads(request((server,None),'/api/players')[2])['players'][0]['reading']
        diagnostic=json.loads(request((server,None),'/dev/api/streams/alpha/diagnostics')[2])['observations'][-1]
        assert p==board and p['exp'] is None and p['percentage']=='45.14'
        assert p['level']['value']==65 and p['exp_validity']['status']=='invalid'
        assert diagnostic['candidate']['exp']=='2458' and public(diagnostic['exp_validity'])==p['exp_validity']  # Public omits diagnostics only.
        assert diagnostic['visual_level']==63 and diagnostic['neural_level']['level']==65
    assert [r[0] for r in store.db.execute('select payload_json from diagnostic_attempts')]==payloads
    assert not store.db.execute('select 1 from observations').fetchone()


def test_percentage_exp_estimate_is_separate_exact_bounded_and_does_not_replace_raw(tracking):
    from exp_tracker.exp_consistency import assess
    from exp_tracker.product import fraction
    from fractions import Fraction
    _,store,d=tracking
    append(d,1,'[67.72%]',visual_level=65,
        neural_level=dict(text='65',level=65,status='numeric_candidate',score=.99))
    before=store.db.execute('select payload_json from diagnostic_attempts').fetchone()[0]
    value=get(d,0)['reading'];e=value['estimated_exp']
    assert value['exp'] is None and e['level_evidence']['value']==65
    assert fraction(e['value'])==Fraction(6772*1579913,10000)
    assert not e['trusted'] and e['requirement']['status']=='community_provisional'
    for mode,b in e['hypotheses'].items():
        for x in (b['min'],b['max']):assert assess(65,x,'67.72',{65:1579913},mode)['status']=='consistent'
    assert e['hypotheses']['nearest_half_up']!=e['hypotheses']['truncate']
    assert store.db.execute('select payload_json from diagnostic_attempts').fetchone()[0]==before
    assert store.state('alpha')['last_trusted'] is None
    assert not store.db.execute('select 1 from observations').fetchone()
    # Contradictory integer withheld; percentage estimate remains distinct.
    append(d,2,'2,458[67.72%]',candidate=[2458,67.72],status='diagnostic_pair',visual_level=65,
        neural_level=dict(text='65',level=65,status='numeric_candidate',score=.99))
    assert get(d,15)['reading']['exp_validity']['status']=='invalid'
    e2=get(d,15)['reading']['estimated_exp']
    assert e2['value']==e['value'] and e2['hypotheses']==e['hypotheses']
    assert e2['level_evidence']['temporal_samples']==2  # Evidence retains the current frame's provenance.


@pytest.mark.parametrize('percentage',['0.00','100.00'])
def test_percentage_estimate_retains_zero_and_within_level_bin_limits(tracking,percentage):
    _,_,d=tracking;append(d,1,f'[{percentage}%]')
    estimate=get(d,0)['reading']['estimated_exp']
    for b in estimate['hypotheses'].values():
        assert b['min']>=0 and b['max']<1497832
    if percentage=='100.00':assert estimate['hypotheses']['truncate']['count']==0


def test_raw_exp_priority_and_unresolved_level_never_become_computed_readings(tracking):
    _,_,d=tracking
    append(d,1,'1,069,917[67.72%]',candidate=[1069917,67.72],status='diagnostic_pair',visual_level=65,
        neural_level=dict(text='65',level=65,status='numeric_candidate',score=.99))
    assert get(d,0)['reading']['exp']=='1069917' and get(d,0)['reading']['estimated_exp'] is None
    append(d,2,'[67.73%]',visual_level=99,neural_level=None)
    assert get(d,15)['reading']['estimated_exp'] is None  # Disputed requirement.
    append(d,3,'[67.74%]',visual_level=None,neural_level=dict(text='65',level=65,status='numeric_candidate',score=.75))
    assert get(d,30)['reading']['level']['value'] is None and get(d,30)['reading']['estimated_exp'] is None


def test_estimate_abstains_when_neither_hypothesis_has_a_compatible_integer():
    from exp_tracker.product import percentage_exp
    assert percentage_exp(5000,dict(value=1,status='agreement')) is None  # 15 EXP requirement cannot display 50.00%.
