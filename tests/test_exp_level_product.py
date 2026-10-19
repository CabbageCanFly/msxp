"""Synthetic obscured-level-HUD stream through SQLite, the player response and HTTP API."""
from datetime import datetime,timedelta
from fractions import Fraction
import json

from exp_tracker.diagnostics import Diagnostics
from exp_tracker.exp_requirements import requirement
from exp_tracker.server import create_server
from tests.test_exp_level_inference import display
from tests.test_product import tracking,NOW,get  # noqa: F401 (pytest fixture)
from tests.test_server import request

T42,T43=requirement(42)['to_next'],requirement(43)['to_next']


def attempt(d,index,*,exp=None,pct=None,total=T42,**changes):
    """Level HUD covered: no reader level, only EXP text."""
    pct=pct or display(exp,total)
    stamp=(NOW+timedelta(seconds=(index-1)*15)).isoformat()
    record=dict(type='attempt',trusted=False,index=index,attempted_at=stamp,received_at=stamp,current=True,
        source=dict(kind='twitch',channel='alpha'),status='diagnostic_pair' if exp is not None else 'diagnostic_percentage_only',
        neural=dict(text=f'{exp:,}[{pct}%]' if exp is not None else f'[{pct}%]'),
        candidate=[exp,float(pct)] if exp is not None else None,visual_level=None,visual_status='unavailable',
        neural_level=dict(status='not_run',text=None,level=None,score=None),localization=dict(count=1),
        frame_sha256=f'{index:064x}')
    record.update(changes);d.append('run',record)


STREAM=[dict(exp=e) for e in (352000,352400,352800)]+[dict(pct=p) for p in ('98.90','99.40','99.92')]+[
    dict(pct=p) for p in ('0.18','0.45','0.81','1.16')]+[dict(exp=e,total=T43) for e in (5000,5400,5800)]
"""Pairs establish 42 (1-3), percentage-only through a hidden level-up (7 wraps, 10 provisional), EXP returns."""


def stream(d,until=len(STREAM)):
    for index,values in enumerate(STREAM[:until],1):attempt(d,index,**values)
    return until


def test_public_player_shows_inferred_retained_possible_provisional_and_corroborated_levels(tracking):
    _,store,d=tracking
    seen={}
    for index,values in enumerate(STREAM,1):
        attempt(d,index,**values);seen[index]=get(d,(index-1)*15)
    value=lambda i:(seen[i]['display_level'] or {}).get('value')
    status=lambda i:(seen[i]['display_level'] or {}).get('evidence',{}).get('status')
    assert value(1)==42 and value(2)==42
    p=seen[3]
    assert (value(3),status(3))==(42,'exp_derived') and p['reading']['level']['status']=='exp_derived'
    assert p['level_context']['last_supported_level']==42 and p['level_context']['source']=='exp_derived'
    p=seen[6]
    assert (value(6),status(6))==(42,'retained_level') and p['reading']['exp'] is None
    assert p['reading']['estimated_exp']['requirement']['to_next']==T42
    p=seen[7]
    assert p['level_context']['transition']['phase']=='possible' and p['level_context']['last_supported_level']==42
    assert value(7)==42 and p['display_level']['last_known'] is True
    # The public reading holds the last ordered value while the drop is unresolved.
    assert p['reading']['percentage']=='99.92' and p['percentage_state']['status']=='unresolved_numerical_continuity'
    assert seen[10]['reading']['percentage']=='1.16' and seen[10]['percentage_state']['public_eligible']
    p=seen[10]
    assert (value(10),status(10))==(43,'provisional_level_up')
    assert p['level_context']['transition']['phase']=='provisional' and p['level_context']['last_supported_level']==42
    assert [(e['level'],e['status'],e['inferred']) for e in p['level_events']]==[(43,'provisional',True)]
    assert p['reading']['estimated_exp']['requirement']['to_next']==T43
    p=seen[13]
    assert (value(13),status(13))==(43,'exp_derived')
    assert p['level_context']['last_transition']['phase']=='corroborated'
    assert [(e['level'],e['status']) for e in p['level_events']]==[(43,'corroborated')]
    assert not store.db.execute('SELECT 1 FROM observations').fetchone()


def test_uncertain_boundary_never_manufactures_exp_or_spans_levels(tracking):
    _,store,d=tracking
    last=stream(d)
    for i,exp in enumerate((6200,6600,7000),last+1):attempt(d,i,exp=exp,total=T43)
    now=NOW+timedelta(seconds=15*(last+2))
    p=get(d,15*(last+2))
    wrap=datetime.fromisoformat(p['level_context']['last_transition']['detected_at'])
    rolling=Diagnostics(store).rolling_history('alpha',now=now)
    intervals=rolling['chart_intervals']
    assert intervals and {g['level'] for g in intervals}=={42,43}
    for g in intervals:
        start,end=datetime.fromisoformat(g['start']),datetime.fromisoformat(g['end'])
        assert not start<wrap<=end and Fraction(g['value']['numerator'],g['value']['denominator'])>=0
    # Unknown boundary EXP stays unknown: the total is exactly the per-level intervals.
    total=sum(Fraction(g['value']['numerator'],g['value']['denominator']) for g in intervals)
    assert Fraction(rolling['tracked_exp']['numerator'],rolling['tracked_exp']['denominator'])==total
    assert total<T43  # Not a whole level, nor (100% - 99.92%) + 1.16%-style boundary arithmetic.
    windows=rolling['windows']
    for small,large in zip(('5','10','15','30'),('10','15','30','60')):
        a,b=(Fraction(windows[m]['gain']['numerator'],windows[m]['gain']['denominator']) if windows[m]['gain'] else 0 for m in (small,large))
        assert a<=b
    assert rolling['current_level']==43
    assert {g['level'] for g in intervals if g['end']>p['level_context']['last_transition']['detected_at']}=={43}
    pace=p['responsive_pace']
    assert pace and all(i['level']==43 for i in pace['intervals'] if i['start']>=wrap.isoformat())
    assert not store.db.execute('SELECT 1 FROM observations').fetchone()


def test_misread_wrap_leaves_level_and_events_unchanged(tracking):
    _,_,d=tracking
    for i,exp in enumerate((352000,352400,352800),1):attempt(d,i,exp=exp)
    for i,pct in enumerate(('99.40','0.18','99.45','99.50'),4):attempt(d,i,pct=pct)
    p=get(d,6*15)
    assert p['display_level']['value']==42 and p['display_level']['evidence']['status']=='retained_level'
    assert p['level_context']['last_transition']['phase']=='abandoned' and p['level_events']==[]


def test_http_api_exposes_level_provenance_without_raw_ocr(tracking):
    path,_,d=tracking
    for i,exp in enumerate((278125,278525,278925),1):attempt(d,i,exp=exp)
    attempt(d,4,pct='78.20')
    with create_server(path,port=0,diagnostic_dashboard=True) as server:
        value=json.loads(request((server,None),'/api/players/alpha')[2])['player']
        assert value['display_level']['value']==42
        assert value['display_level']['evidence']['status']=='retained_level'
        assert value['level_context']['last_supported_level']==42 and value['level_context']['verified'] is False
        assert 'raw_text' not in json.dumps(value)
