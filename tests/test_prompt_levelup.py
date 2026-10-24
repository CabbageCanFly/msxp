"""Saved CharA punctuation and corroborated level-up, using synthetic frames only."""
from datetime import datetime,timedelta
import json

import pytest

from exp_tracker.diagnostic_evidence import full_reading,project
from exp_tracker.exp_requirements import requirement
from exp_tracker.parsing import parse_exp
from exp_tracker.product import history,responsive_pace
from exp_tracker.shadow_grammar import interpret_exp
from tests.test_endpoint_pace import point,snapshot
from tests.test_exp_level_inference import display
from tests.test_exp_level_product import attempt
from tests.test_product import tracking,get,NOW  # noqa: F401 (pytest fixture)


@pytest.mark.parametrize('raw,exp,pct',[
    ('151[0.01%]','151','0.01'),
    ('1.,71910.09%1','1719','0.09'),
    ('3,44410.18%','3444','0.18'),
    ('1,.719[0.09%]','1719','0.09'),
    ('3,444[0.18%','3444','0.18')])
def test_complete_streamer_a_pairs_preserve_digits_and_provenance(raw,exp,pct):
    result=interpret_exp(raw)
    pair=result['strict_full'] or result['full_exp']['proposals'][0]['reading']
    assert (pair['exp'],pair['percentage'])==(exp,pct)
    assert not result['trusted']
    if raw!='151[0.01%]':
        assert parse_exp(raw) is None  # The strict parser and trusted intake stay unchanged.
        proposal=result['full_exp']['proposals'][0]
        assert result['full_exp']['classification']=='unique_proposal'
        repaired=list(raw)+['']
        for edit in proposal['edits']:
            assert repaired[edit['index']]==edit['old']
            repaired[edit['index']]=edit['new']
        assert ''.join(repaired)==proposal['interpretation']
        assert ''.join(c for c in proposal['interpretation'].split('[')[0] if c.isdigit())==exp
        assert not proposal['numerical_identity_verified']


@pytest.mark.parametrize('raw',[
    '1.,71910.09%1','3,44410.18%','3,444[0.18%'])
def test_clipped_field_cannot_supply_recovered_absolute_exp(raw):
    assert not interpret_exp(raw,source_complete=False)['full_exp']['proposals']


@pytest.mark.parametrize('raw',[
    '1.,7110.09%1','1..71910.09%1','1,,71910.09%1',
    '1.,719.,12310.09%1','3,44410.1%','3,44410.18',
    '3,44410.18% extra','3,44410.18% 4,000[0.21%]',
    '1.234.567.89010.18%'])
def test_missing_digits_competing_fields_and_edit_overflow_abstain(raw):
    assert not interpret_exp(raw)['full_exp']['proposals']


def sequence():
    total=requirement(68)['to_next']
    old=total*9991//10000
    rows=[point(1,0,old,display(old,total),level=68),point(2,30,151,'0.01',level=69)]
    for i,exp,pct,raw in [(3,1719,'0.09','1.,71910.09%1'),(4,3444,'0.18','3,44410.18%')]:
        r=point(i,30*(i-1),exp,pct,level=69)
        r.update(raw_text=raw,candidate=None,status='malformed_or_unavailable')
        if i==4:r['visual_level']=None
        rows.append(r)
    return rows


def test_first_agreed_new_level_is_public_and_known_reset_progress_counts():
    rows=sequence()
    for end in range(2,5):
        snap=snapshot(rows[:end],30*(end-1));last=snap['observations'][-1]
        assert last['experimental_level']['value']==69
        assert last['percentage_review']['public_eligible']
        assert full_reading(last)['exp']==str((151,1719,3444)[end-2])
    chart=history(snap)
    assert chart[1]['gain'] is None
    assert [p['gain']['value']['approximate'] for p in chart[2:]]==[1568,1725]
    pace=responsive_pace(snap,dict(value=69),now=NOW+timedelta(seconds=90))
    assert pace['total_gain']['approximate']==requirement(68)['to_next']-int(rows[0]['candidate']['exp'])+3444==5113


@pytest.mark.parametrize('changes',[
    dict(hud_count=2),dict(crop_suspect=True),dict(fresh_at_capture=False),
    dict(timestamp_ordered=False),dict(source_identity='b'*64)])
def test_early_agreement_does_not_bypass_capture_or_identity_boundaries(changes):
    rows=sequence()[:2];rows[1].update(changes)
    snap=snapshot(rows,30)
    assert history(snap)[1]['gain'] is None
    if 'source_identity' not in changes:
        assert not snap['observations'][1]['percentage_review']['public_eligible']


def test_single_disagreeing_reader_does_not_get_early_agreement():
    rows=sequence()[:2];rows[1]['visual_level']=68
    assert project(rows)[-1]['experimental_level']['value'] is None


def test_new_reader_agreement_does_not_borrow_old_level_arithmetic_support():
    rows=sequence()[:3]
    for r,seconds,pct in zip(rows[1:],(15,30),('0.01','0.02')):
        stamp=(NOW+timedelta(seconds=seconds)).isoformat()
        r.update(raw_text=f'[{pct}%]',candidate=None,received_at=stamp,attempted_at=stamp)
    rows[-1]['visual_level']=68
    projected=project(rows)
    assert projected[1]['experimental_level']['value']==69
    assert projected[2]['experimental_level']['value'] is None


@pytest.mark.parametrize('floor,expected',[(57,[57,57]),(None,[None,57])])  # Without a floor the wrap waits for a second read.
def test_validated_new_level_replaces_an_older_exp_derived_level(floor,expected):
    """Live bgi_stream: Lv. 56 known only from EXP arithmetic, then neural-only Lv. 57 frames.
    The guard's floor made the first one select 57, which the stale derived 56 vetoed until both readers agreed."""
    rows=[point(1,0,975705,'99.82',level=56),point(2,40,977258,'99.98',level=56),
          point(3,80,735,'0.07',level=57),point(4,120,903,'0.09',level=57)]
    for r in rows[:2]:r.update(visual_level=None,neural_level=None)  # The EXP pair alone gives Lv. 56.
    for r in rows[2:]:r.update(visual_level=None,validated_level_floor=floor)
    projected=project(rows)
    assert projected[1]['experimental_level']['status'] in ('exp_derived','retained_level')
    assert [r['experimental_level']['value'] for r in projected[2:]]==expected


def test_public_projection_and_rolling_history_resume_without_trusted_writes(tracking):
    _,store,d=tracking
    for index,r in enumerate(sequence(),1):
        attempt(d,index,exp=int(r['candidate']['exp']) if r['candidate'] else None,
            pct=(r['candidate'] or {}).get('percentage','0.09' if index==3 else '0.18'),
            neural=dict(text=r['raw_text']),candidate=[int(r['candidate']['exp']),float(r['candidate']['percentage'])] if r['candidate'] else None,
            visual_level=r['visual_level'],visual_status='available' if r['visual_level'] else 'unavailable',
            neural_level=r['neural_level'])
        if index>=2:
            p=get(d,(index-1)*15)
            assert p['display_level']['value']==69
            assert p['reading']['exp']==str((151,1719,3444)[index-2])
            assert not p['reading']['trusted']
    rolling=d.rolling_history('alpha',now=NOW+timedelta(seconds=45))
    assert rolling['tracked_exp']['approximate']==5113
    assert [g['value']['approximate'] for g in rolling['chart_intervals']]==[1820,1568,1725]
    assert rolling['current_level_windows']['5']['gain']['approximate']==3293
    assert not store.db.execute('select 1 from observations').fetchone()


def test_saved_streamer_a_first_new_level_and_two_punctuation_recoveries(tracking):
    from tests.test_cross_level_product import replay,SAVED
    from exp_tracker.product import player
    from exp_tracker.server import create_server
    from tests.test_server import request
    folder='20261019T080326Z-f4f3d659';rid='764dc5b622f54861bfb90a43168330c4'
    if not (SAVED/folder/'streamer_a'/rid/'capture.jsonl').is_file():pytest.skip('private CharA capture unavailable')
    path,store,_=tracking
    now=datetime.fromisoformat('2026-10-19T09:02:06.728610+00:00')
    d,_=replay(store,'streamer_a',[folder],as_of=now)
    recent=d.recent_snapshot('streamer_a',now=now);rows=recent['observations']
    by_id={r['event_id']:r for r in rows}
    for index,exp,pct in [(11,'151','0.01'),(12,'1719','0.09'),(13,'3444','0.18')]:
        r=by_id[f'{rid}:{index}']
        assert r['experimental_level']['value']==69 and r['percentage_review']['public_eligible']
        assert (full_reading(r)['exp'],full_reading(r)['percentage'])==(exp,pct)
    chart={p['event_id']:p for p in history(recent)}
    assert chart[f'{rid}:11']['gain'] is None
    assert [chart[f'{rid}:{i}']['gain']['value']['approximate'] for i in (12,13)]==[1568,1725]
    expected=player(d.snapshot('streamer_a',now=now),now=now,recent_snapshot=d.recent_snapshot('streamer_a',now=now))
    with create_server(path,port=0,diagnostic_dashboard=True) as server:
        server.publisher.settle()
        actual=json.loads(request((server,None),'/api/players/streamer_a')[2])['player']
        assert actual['display_level']['value']==expected['display_level']['value']==69
        assert (actual['reading']['exp'],actual['reading']['percentage'])==('3444','0.18')
    assert not store.db.execute('select 1 from observations').fetchone()
