"""Public estimates use unique punctuation recovery without claiming verification."""
from datetime import datetime,timedelta
import json

import pytest

from exp_tracker.diagnostic_evidence import full_reading,project
from exp_tracker.exp_requirements import requirement
from exp_tracker.product import history,responsive_pace
from tests.test_exp_level_inference import pair,only,display,wrapped
from tests.test_endpoint_pace import snapshot
from tests.test_diagnostic_progress import NOW
from tests.test_product import tracking  # noqa: F401 (pytest fixture)


def recovered(index,text,**changes):
    return pair(index,0,raw_text=text,candidate=None,status='malformed_or_unavailable',**changes)


def test_fixed_percentage_numeric_progress_supplies_level_exp_history_and_pace():
    rows=[pair(1,82330,'21.05'),recovered(2,'82,330121.05%1'),
          pair(3,82338,'21.05'),pair(4,82342,'21.05')]
    snap=snapshot(rows,45)
    assert [r['experimental_level']['value'] for r in snap['observations']]==[43]*4
    assert all(r['experimental_level']['trusted'] is False for r in snap['observations'])
    assert all(r['exp_validity']['status']=='indeterminate' for r in snap['observations'])
    chart=history(snap)
    assert [r['gain']['value']['approximate'] for r in chart[1:]]==[0,8,4]
    pace=responsive_pace(snap,dict(value=43),now=NOW+timedelta(seconds=45))
    assert pace['total_gain']['approximate']==12
    assert pace['estimates']['exp_per_hour']['value']['approximate']==960
    assert pace['evidence_counts']['grammar_recovered']==1


@pytest.mark.parametrize('text,exp,pct',[
    ('415.930136.26%]','415930','36.26'),('416.913136.34%1','416913','36.34')])
def test_unique_complete_grammar_pair_can_supply_the_initial_level(text,exp,pct):
    original=recovered(1,text);projected=project([original])[0]
    assert projected['raw_text']==text and projected['candidate'] is None
    assert {k:full_reading(projected)[k] for k in ('exp','percentage')}==dict(exp=exp,percentage=pct)
    assert projected['experimental_level']['value']==59
    assert projected['experimental_level']['status']=='exp_derived'
    assert projected['experimental_level']['level_context']['verified'] is False
    assert projected['exp_validity']['reason']=='level_derived_from_exp_pairs'


def test_recovered_pairs_renew_retained_level_and_supply_numeric_intervals():
    rows=[recovered(1,'415.930136.26%]'),recovered(2,'416.913136.34%1'),only(3,'36.35'),
          recovered(4,f'416.950[{display(416950,requirement(59)["to_next"])}%1')]
    snap=snapshot(rows,45)
    assert [r['experimental_level']['status'] for r in snap['observations']]==[
        'exp_derived','exp_derived','retained_level','exp_derived']
    chart=history(snap)
    assert chart[1]['gain']['value']['approximate']==983
    assert chart[1]['gain']['basis']=='observed_exp_endpoints'
    assert chart[1]['reading']['evidence']=='grammar_recovered'
    assert snap['observations'][-1]['experimental_level']['level_context']['unsupported_frames']==0


def test_stationary_pairs_display_a_level_without_inventing_progress():
    snap=snapshot([pair(i,82330,'21.05') for i in range(1,4)],30)
    assert [r['experimental_level']['value'] for r in snap['observations']]==[43]*3
    assert all(r['gain']['value']['approximate']==0 for r in history(snap)[1:])
    pace=responsive_pace(snap,dict(value=43),now=NOW+timedelta(seconds=30))
    assert pace['total_gain']['approximate']==0


@pytest.mark.parametrize('text',[
    '415.930136.2%]','415.930136.26%] 416.913136.34%1','2345[92.74%1','1,241199.82%]'])
def test_incomplete_competing_or_numerically_incompatible_text_does_not_seed(text):
    assert project([recovered(1,text)])[0]['experimental_level']['value'] is None


@pytest.mark.parametrize('changes',[
    dict(hud_count=2),dict(crop_suspect=True),dict(fresh_at_capture=False),
    dict(timestamp_ordered=False),dict(neural_level=dict(source_complete=False)),
    dict(frame_sha256=None)])
def test_recovery_does_not_bypass_capture_safeguards(changes):
    assert project([recovered(1,'415.930136.26%]',**changes)])[0]['experimental_level']['value'] is None


@pytest.mark.parametrize('changes',[
    dict(character_id=2),dict(session_id=2),dict(source_identity='b'*64),dict(run_id='restart')])
def test_fresh_inference_across_identity_boundaries_cannot_connect_exp(changes):
    rows=[pair(1,82330,'21.05'),pair(2,82338,'21.05',**changes),pair(3,82342,'21.05',**changes)]
    snap=snapshot(rows,30);chart=history(snap)
    assert [r['experimental_level']['value'] for r in snap['observations']]==[43]*3
    assert chart[1]['gain'] is None
    assert chart[2]['gain']['value']['approximate']==4


def test_numeric_loss_within_one_percentage_bin_is_not_counted_as_a_gain():
    snap=snapshot([pair(1,82342,'21.05'),pair(2,82330,'21.05'),pair(3,82338,'21.05')],30)
    chart=history(snap)
    assert chart[1]['gain'] is None and chart[2]['gain']['value']['approximate']==8
    pace=responsive_pace(snap,dict(value=43),now=NOW+timedelta(seconds=30))
    assert pace['total_gain']['approximate']==8


def test_grammar_recovered_pair_can_corroborate_a_real_wrap_hypothesis():
    total=requirement(43)['to_next']
    rows=wrapped()+[recovered(11,f'5.0001{display(5000,total)}%1')]
    final=project(rows)[-1]['experimental_level']
    assert final['value']==43 and final['status']=='exp_derived'
    assert final['level_context']['last_transition']['phase']=='corroborated'


def test_complete_recovery_can_confirm_loss_without_counting_the_boundary():
    rows=[pair(1,280000),recovered(2,f'275.0001{display(275000)}%1'),
          recovered(3,f'275.1001{display(275100)}%1'),pair(4,275200)]
    snap=snapshot(rows,45)
    reviews=snap['percentage_progress']['percentage_reviews']
    assert reviews[1]['public_eligible'] is False
    assert reviews[2]['status']=='corroborated_lower_baseline'
    chart=history(snap)
    assert chart[1]['gain'] is None and chart[2]['gain'] is None
    assert chart[3]['gain']['value']['approximate']==100


def test_background_publisher_and_public_routes_include_unique_recovery(tracking,monkeypatch):
    import exp_tracker.server as server_module
    import exp_tracker.diagnostics as diagnostics_module
    from tests.test_exp_level_product import attempt
    from tests.test_publisher import wait_for,current
    from tests.test_server import request
    class Clock(datetime):
        at=NOW
        @classmethod
        def now(cls,tz=None):return cls.at
    monkeypatch.setattr(server_module,'datetime',Clock)
    monkeypatch.setattr(diagnostics_module,'datetime',Clock)
    path,store,d=tracking
    with server_module.create_server(path,port=0,diagnostic_dashboard=True,background=True) as server:
        for index,text in enumerate(('415.930136.26%]','416.913136.34%1'),1):
            attempt(d,index,exp=0,candidate=None,neural=dict(text=text),status='malformed_or_unavailable')
            Clock.at=NOW+timedelta(seconds=(index-1)*15)
            server.publisher.wake.set();wait_for(lambda:current(server,store,'alpha'))
            result=json.loads(request((server,None),'/api/players/alpha')[2])
            value=result['player']
            assert value['display_level']['value']==59
            assert value['reading']['evidence']=='grammar_recovered'
            assert value['reading']['exp']==('415930' if index==1 else '416913')
            assert value['level_context']['verified'] is False
            home=json.loads(request((server,None),'/api/players')[2])
            assert home['players'][0]['display_level']['value']==59
        assert value['responsive_pace']['total_gain']['approximate']==983
        assert result['history'][-1]['gain']['value']['approximate']==983
        assert result['tracked_history']['tracked_exp']['approximate']==983
        for route in ('/','/stream/alpha','/live/overlay/alpha','/dashboard/alpha'):
            assert request((server,None),route)[0]==200
        assert not store.db.execute('SELECT 1 FROM observations').fetchone()
