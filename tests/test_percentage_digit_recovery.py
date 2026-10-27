"""Single S/O/B repairs use ordinary grammar and downstream validation."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import pytest
from exp_tracker.pace_intervals import collect_observed
from exp_tracker.product import history, observed_display, reading
from exp_tracker.shadow_grammar import interpret_exp
from exp_tracker.diagnostic_evidence import project
from tests.test_endpoint_pace import NOW, point, snapshot
from tests.test_product import tracking, append


def glyph_rows(text):
    rows=[point(1,0,172330,'64.62',level=39),point(2,20,173038,'64.89',level=39),point(3,40,174132,'65.30',level=39)]
    rows[-1].update(raw_text=text,candidate=None,status='malformed_or_unavailable')
    return rows


@pytest.mark.parametrize('text,exp,pct',[
    ('174.13216S.30%1','174132','65.30'),('175,30516S.74%1','175305','65.74'),
    ('174,132[65.3O%]','174132','65.30'),('182,144[6B.30%]','182144','68.30'),
    ('17S,305[65.74%]','175305','65.74'),('174,13O[65.29%]','174130','65.29'),
    ('1B2,144[68.30%]','182144','68.30'),('17S.305165.74%1','175305','65.74'),
])
def test_glyph_in_either_numeric_field_reaches_display_and_chart(text,exp,pct):
    parsed=interpret_exp(text)
    assert parsed['strict_full'] is None and not parsed['symbol_hypotheses']
    proposal,=parsed['full_exp']['proposals']
    edits=[e for e in proposal['edits'] if e['category'] in ('percentage_digit','exp_digit')]
    assert len(edits)==1 and (edits[0]['old'],edits[0]['new']) in (('S','5'),('O','0'),('B','8'))
    assert not proposal['trusted'] and not proposal['numerical_identity_verified']
    snap=snapshot(glyph_rows(text),40);frozen=deepcopy(snap);now=NOW+timedelta(seconds=40)
    value=reading(snap['observations'][-1])
    assert (value['exp'],value['percentage'])==(exp,pct)
    assert value['evidence']=='grammar_recovered' and not value['trusted']
    assert observed_display(snap,now=now)['reading']==history(snap)[-1]['reading']==value
    assert snap==frozen


@pytest.mark.parametrize('text,pct',[
    ('[6S.30%]','65.30'),('6S.30%','65.30'),('[65.3O%]','65.30'),
    ('[6B.30%1','68.30'),('[S.30%]','5.30'),('[O.00%]','0.00'),
])
def test_percentage_only_needs_no_numeric_exp_or_prior_full_readings(text,pct):
    current=glyph_rows(text)[-1];current.update(index=1,event_id='run:1')
    snap=snapshot([current],40);value=reading(snap['observations'][0])
    assert value['percentage']==pct and value['exp'] is None
    assert value['evidence']=='grammar_recovered' and value['estimated_exp'] is not None
    assert not interpret_exp(text)['full_exp']['proposals']
    assert history(snap)[0]['reading']==value


@pytest.mark.parametrize('text,pct',[
    ('[$S.70%]','55.70'),('[S$.79%]','55.79'),('[SS.70%]','55.70'),
    ('[$5.70%]','55.70'),('[5$.70%]','55.70'),('[5S.7$%]','55.75'),
    ('[$.00%]','5.00'),('[99.$$%]','99.55'),
])
def test_bounded_five_lookalikes_keep_raw_text_and_reach_percentage_projection(text,pct):
    from exp_tracker.shadow_view import observation
    from exp_tracker.shadow_types import parse_percentage_only
    raw=dict(type='attempt',candidate=None,neural={'text':text},status='malformed_or_unavailable')
    sanitized=observation(raw)
    assert sanitized['raw_text']==text and not sanitized['raw_text_redacted']
    parsed=interpret_exp(sanitized['raw_text'])
    assert parsed['policy']=='bounded_exp_v13' and parsed['raw']==text
    assert parse_percentage_only(text) is None and parsed['strict_percentage_only'] is None
    assert not parsed['full_exp']['proposals'] and not parsed['percentage_hypotheses']
    proposal,=parsed['percentage']['proposals']
    assert proposal['reading']['percentage']==pct and 1<=len(proposal['edits'])<=2
    assert all(e['old'] in 'S$' and e['new']=='5' for e in proposal['edits'])
    current=point(1,0,174132,pct,level=39)
    current.update(raw_text=sanitized['raw_text'],candidate=None,status='malformed_or_unavailable')
    value=reading(snapshot([current],0)['observations'][0])
    assert value['percentage']==pct and value['exp'] is None and value['evidence']=='grammar_recovered'
    assert raw['neural']['text']==text and not value['trusted']


@pytest.mark.parametrize('text',[
    '$55.70','[$55.70%]','[S$S.70%]','[S$.7S%]','[5$.7$%1',
    '$S.70%','[$S.70%1','1$S.70%1','[$S.70%]junk','junk[$S.70%]',
    '[$S.70%][$S.71%]','[$S70%]','[$S.7%]','[$S.700%]','[$S.70]',
    '[$S.70X]','[S$.7O%]','[s$.70%]','123[$S.70%]','1$3[55.70%]',
])
def test_five_lookalikes_never_repair_other_formats_or_more_than_two_digits(text):
    parsed=interpret_exp(text)
    assert not parsed['full_exp']['proposals'] and not parsed['percentage']['proposals']
    assert not parsed['percentage_hypotheses']


def test_clipped_percentage_vetoes_dollar_and_double_s_recovery():
    for text in ('[$S.70%]','[SS.70%]'):
        assert not interpret_exp(text,source_complete=False)['percentage']['proposals']


@pytest.mark.parametrize('text',[
    '[6S.3O%]','17S,305[6S.74%]','[6s.30%]','[6Z.30%]','[6I.30%]',
    '[6S30%]','[6S.3%]','[6S.300%]','[6S.30X1','[6S.30]',
    '[6S.30%]junk','junk[6S.30%]','17413216S.30%1','W74,132[65.30%]',
    'S','174,S32','[1O0.01%]',
])
def test_multiple_repairs_missing_digits_unknown_letters_and_extra_text_stay_rejected(text):
    parsed=interpret_exp(text)
    assert not parsed['symbol_hypotheses']
    assert not parsed['full_exp']['proposals'] and not parsed['percentage']['proposals']


@pytest.mark.parametrize('text',['[6S.30%]','174,132[6S.30%]','17S,305[65.74%]'])
def test_clipped_source_vetoes_glyph_recovery(text):
    parsed=interpret_exp(text,source_complete=False)
    assert not parsed['full_exp']['proposals'] and not parsed['percentage']['proposals']


def test_malformed_exp_grouping_does_not_become_a_full_pair():
    parsed=interpret_exp('17S,13[65.30%]')
    assert not parsed['full_exp']['proposals']
    assert parsed['percentage']['proposals'][0]['reading']['percentage']=='65.30'


@pytest.mark.parametrize('text',['170,132[6S.30%]','17S,305[65.30%]'])
def test_existing_arithmetic_veto_still_blocks_contradictory_full_pairs(text):
    snap=snapshot(glyph_rows(text),40)
    assert snap['observations'][-1]['exp_validity']['whole_pair_rejected']
    assert reading(snap['observations'][-1]) is None


@pytest.mark.parametrize('prefix,pct,exp',[('S0,000','18.75','50000'),('B0,000','30.00','80000')])
@pytest.mark.parametrize('kind',['match','mismatch','no_level','unsupported_level'])
def test_leading_s_or_b_exp_needs_independent_arithmetic_even_on_first_capture(prefix,pct,exp,kind):
    text=f'{prefix}[{pct if kind!="mismatch" else "31.00"}%]'
    current=point(1,0,int(exp),pct,level=150 if kind=='unsupported_level' else 39)
    current.update(raw_text=text,candidate=None,status='malformed_or_unavailable')
    if kind=='no_level':current.update(visual_level=None,neural_level=None)
    snap=snapshot([current],0);row=snap['observations'][0];value=reading(row)
    assert value is not None and value['percentage']==(pct if kind!='mismatch' else '31.00')
    if kind=='match':
        assert value['exp']==exp and row['exp_validity']['status']=='consistent'
    else:
        assert value['exp'] is None
        assert row['exp_validity']['reason']=='leading_exp_glyph_requires_independent_arithmetic'
    assert project(snap['observations'])==snap['observations']


def test_repeated_leading_exp_repairs_cannot_infer_the_level_that_would_verify_them():
    rows=[]
    for index in range(1,5):
        current=point(index,(index-1)*20,50000,'18.75',level=39)
        current.update(raw_text='S0,000[18.75%]',candidate=None,status='malformed_or_unavailable',visual_level=None,neural_level=None)
        rows.append(current)
    snap=snapshot(rows,60)
    assert all(r['experimental_level']['value'] is None for r in snap['observations'])
    assert all(reading(r)['exp'] is None for r in snap['observations'])


@pytest.mark.parametrize('seconds,accepted',[(70,True),(150,False)])
def test_leading_repair_can_use_recent_independent_level_support_but_not_expired_support(seconds,accepted):
    rows=[point(1,0,49000,'18.37',level=39),point(2,20,49500,'18.56',level=39),
          point(3,seconds,50000,'18.75',level=39)]
    rows[-1].update(raw_text='S0,000[18.75%]',candidate=None,status='malformed_or_unavailable',visual_level=None,neural_level=None)
    snap=snapshot(rows,seconds)
    assert (reading(snap['observations'][-1])['exp']=='50000') is accepted


@pytest.mark.parametrize('text',['PS0,000[18.75%]','PB0,000[30.00%]','junkS0,000[18.75%]'])
def test_leading_repair_is_not_extracted_from_a_label_or_other_prefix(text):
    assert not interpret_exp(text)['full_exp']['proposals']


@pytest.mark.parametrize('kind',['stale','two_huds','out_of_order','future','crop','duplicate','invalidated','conflict'])
@pytest.mark.parametrize('text',['[6S.30%]','[6$.30%]','[$S.70%]'])
def test_glyph_recovery_does_not_bypass_normal_endpoint_checks(kind,text):
    rows=glyph_rows(text);last=rows[-1];seconds=40
    if kind=='stale':last.update(fresh_at_capture=False,status='stale_local_frame')
    elif kind=='two_huds':last['hud_count']=2
    elif kind=='out_of_order':last['timestamp_ordered']=False
    elif kind=='future':seconds=20
    elif kind=='crop':last['crop_suspect']=True
    elif kind=='duplicate':last['frame_sha256']=rows[0]['frame_sha256']
    elif kind=='invalidated':last['reading_invalidated']=True
    else:last['neural_level'].update(level=40,text='40')
    snap=snapshot(rows,seconds)
    collected=collect_observed(snap,now=NOW+timedelta(seconds=seconds),read=reading,max_interval_seconds=300)
    if kind=='conflict':
        assert snap['observations'][-1]['experimental_level']['value'] is None
        assert all(e['after']['event_id']!='run:3' for e in collected['intervals'])
    else:assert all(p['event_id']!='run:3' for p in collected['points'])


@pytest.mark.parametrize('percentage_only',[False,True])
def test_recovery_survives_api_restart_and_preserves_sqlite_payloads(tracking,percentage_only):
    from exp_tracker.server import create_server
    from exp_tracker.store import Store
    from tests.test_server import request
    path,store,d=tracking
    start=datetime.now(timezone.utc)-timedelta(seconds=30)
    records=([(1,'[33.1O%]',None,None)] if percentage_only else
        [(1,'494,285[33.00%]',494285,33.0),(2,'495,034[33.05%]',495034,33.05),(3,'49S.783133.10%1',None,None)])
    for index,text,exp,pct in records:
        stamp=(start+timedelta(seconds=(index-1)*15)).isoformat()
        append(d,index,text,candidate=[exp,pct] if exp is not None else None,
            status='diagnostic_pair' if exp is not None else 'malformed_or_unavailable',
            frame_sha256=f'{index:064x}',received_at=stamp,attempted_at=stamp)
    payloads=store.db.execute('SELECT payload_json FROM diagnostic_attempts ORDER BY id').fetchall()
    for _ in range(2):
        with create_server(path,port=0,diagnostic_dashboard=True) as http:
            result=json.loads(request((http,None),'/api/players/alpha')[2])
            assert result['player']['reading']['percentage']=='33.10'
            assert result['player']['reading']['evidence']=='grammar_recovered'
            assert result['history'][-1]['reading']['exp']==(None if percentage_only else '495783')
    with Store(path,read_only=True) as reopened:
        assert reopened.db.execute('SELECT payload_json FROM diagnostic_attempts ORDER BY id').fetchall()==payloads
        assert not reopened.db.execute('SELECT 1 FROM observations').fetchone()
