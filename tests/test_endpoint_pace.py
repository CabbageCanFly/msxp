"""Endpoint-supported averages are not intermediate observations or trusted gains."""
from copy import deepcopy
from datetime import timedelta

import pytest

from exp_tracker.diagnostic_evidence import project
from exp_tracker.diagnostic_progress import progress
from exp_tracker.exp_requirements import requirement
from exp_tracker.product import responsive_pace,window_comparisons,history
from tests.test_diagnostic_progress import row,NOW
from tests.test_product import tracking,append


def point(index,seconds,exp,percentage,level=67,**changes):
    stamp=(NOW+timedelta(seconds=seconds)).isoformat()
    return row(index,percentage,received_at=stamp,attempted_at=stamp,interval_seconds=20,
        raw_text=f'{exp:,}[{percentage}%]',candidate=dict(exp=str(exp),percentage=percentage),
        percentage_only_candidate=None,status='diagnostic_pair',visual_level=level,
        neural_level=dict(status='numeric_candidate',text=str(level),level=level,score=.99,preprocessing='neutral4'),
        frame_sha256=f'{index:064x}',**changes)


def missing(index,seconds,**changes):
    stamp=(NOW+timedelta(seconds=seconds)).isoformat()
    return row(index,received_at=None,attempted_at=stamp,raw_text=None,candidate=None,
        percentage_only_candidate=None,status='capture_failed',fresh_at_capture=False,capture_acquired=False,
        hud_count=0,visual_level=None,visual_status='unavailable',interval_seconds=20,**changes)


def snapshot(rows,seconds):
    now=NOW+timedelta(seconds=seconds);rows=project(rows)
    data=progress(rows,now=now,stale_after_seconds=60,current_run_id=rows[-1]['run_id'])
    for r,d in zip(rows,data['percentage_reviews']):r['percentage_review']=d
    return dict(observations=rows,percentage_progress=data,run_id=rows[-1]['run_id'])


@pytest.fixture
def synthetic_requirement(monkeypatch):
    import exp_tracker.product as product
    import exp_tracker.diagnostic_evidence as evidence
    import exp_tracker.pace_intervals as intervals
    value=dict(requirement(67),to_next=10_000_000,version='synthetic-endpoint-test')
    monkeypatch.setattr(product,'requirement',lambda level:value)
    monkeypatch.setattr(evidence,'requirement',lambda level:value)
    monkeypatch.setattr(intervals,'requirement',lambda level:value)


def timeline():
    return [point(1,0,100000,'1.00'),point(2,20,200000,'2.00'),missing(3,40),
        point(4,60,400000,'4.00'),missing(5,80),point(6,100,600000,'6.00'),
        point(7,120,700000,'7.00'),point(8,140,800000,'8.00')]


def test_required_100k_to_800k_timeline_uses_all_elapsed_time(synthetic_requirement):
    original=timeline();frozen=deepcopy(original);snap=snapshot(original,140)
    strict=window_comparisons(snap,now=NOW+timedelta(seconds=140));chart=history(snap)
    pace=responsive_pace(snap,dict(value=67),now=NOW+timedelta(seconds=140))
    assert pace['active'] and pace['readings']==6
    assert pace['coverage_seconds']['approximate']==140
    assert pace['total_gain']['approximate']==700000
    assert pace['estimates']['exp_per_hour']['value']['approximate']==8_400_000
    assert pace['interval_counts']==dict(direct=3,endpoint_supported=2)
    assert pace['missing_attempts']==2
    assert [(e['first_event_id'],e['last_event_id']) for e in pace['intervals']]==[
        ('run:1','run:2'),('run:2','run:4'),('run:4','run:6'),('run:6','run:7'),('run:7','run:8')]
    assert [e['elapsed_seconds']['approximate'] for e in pace['intervals']]==[20,40,40,20,20]
    assert original==frozen and window_comparisons(snap,now=NOW+timedelta(seconds=140))==strict
    assert history(snap)==chart and not chart[3]['connect_previous'] and not chart[5]['connect_previous']
    assert not any(w['eligible'] for w in strict.values())


def test_uneven_gain_inside_gaps_cannot_bias_the_denominator(synthetic_requirement):
    rows=timeline();rows[5]=point(6,100,650000,'6.50')
    pace=responsive_pace(snapshot(rows,140),dict(value=67),now=NOW+timedelta(seconds=140))
    assert pace['total_gain']['approximate']==700000 and pace['coverage_seconds']['approximate']==140
    assert pace['estimates']['exp_per_hour']['value']['approximate']==8_400_000
    direct=[e for e in pace['intervals'] if e['kind']=='direct']
    assert sum(e['gain']['approximate'] for e in direct)==250000
    assert sum(e['elapsed_seconds']['approximate'] for e in direct)==60


def test_omitted_attempt_indices_are_disclosed_without_inventing_ids(synthetic_requirement):
    rows=[point(1,0,100000,'1.00'),point(2,20,200000,'2.00'),point(5,80,400000,'4.00')]
    p=responsive_pace(snapshot(rows,80),dict(value=67),now=NOW+timedelta(seconds=80))
    assert p['missing_attempts']==2
    assert p['intervals'][-1]['unrecorded_attempts']==2 and p['intervals'][-1]['missing_event_ids']==[]
    assert p['coverage_seconds']['approximate']==80


@pytest.mark.parametrize('count',[1,2,5,10])
def test_missing_captures_hold_sample_then_next_endpoint_updates_without_warmup(synthetic_requirement,count):
    rows=[point(1,0,100000,'1.00'),point(2,20,200000,'2.00')]
    rows += [missing(i+3,40+i*20) for i in range(count)]
    before=responsive_pace(snapshot(rows,20+count*20),dict(value=67),now=NOW+timedelta(seconds=20+count*20))
    assert not before['active'] and before['readings']==2 and before['total_gain']['approximate']==100000
    end=40+count*20;rows.append(point(count+3,end,400000,'4.00'))
    pace=responsive_pace(snapshot(rows,end),dict(value=67),now=NOW+timedelta(seconds=end))
    assert pace['active'] and pace['readings']==3 and pace['coverage_seconds']['approximate']==end
    assert pace['total_gain']['approximate']==300000
    assert pace['estimates']['exp_per_hour']['value']['approximate']==3_600_000
    assert pace['interval_counts']==dict(direct=1,endpoint_supported=1)
    assert pace['missing_attempts']==count


@pytest.mark.parametrize('kind',['quarantine','conflict','stale','duplicate','invalid_exp','crop'])
def test_unsafe_row_blocks_subtraction_but_retains_disjoint_intervals(synthetic_requirement,kind):
    from exp_tracker.pace_intervals import collect
    from exp_tracker.product import reading
    rows=[point(1,0,100000,'1.00'),point(2,20,200000,'2.00'),point(3,40,300000,'3.00'),point(4,60,400000,'4.00'),point(5,80,500000,'5.00')]
    if kind=='quarantine':rows[2].update(raw_text='50,000[0.50%]',candidate=dict(exp='50000',percentage='0.50'))
    elif kind=='conflict':rows[2]['neural_level'].update(level=57,text='57',score=.99)
    elif kind=='stale':rows[2].update(status='stale_local_frame',fresh_at_capture=False)
    elif kind=='duplicate':rows[2]['frame_sha256']=rows[1]['frame_sha256']
    elif kind=='invalid_exp':rows[2].update(raw_text='5,000[3.00%]',candidate=dict(exp='5000',percentage='3.00'))
    else:rows[2]['crop_suspect']=True
    snap=snapshot(rows,80);now=NOW+timedelta(seconds=80)
    public=responsive_pace(snap,dict(value=67),now=now)
    assert public['total_gain']['approximate']==400000 and public['coverage_seconds']['approximate']==80
    strict=collect(snap,now=now,read=reading,max_interval_seconds=300)
    assert all((e['before']['event_id'],e['after']['event_id'])!=('run:2','run:4') for e in strict['intervals'])


def x_rows(text='401.128122.82X1',**changes):
    rows=[point(1,0,397820,'22.63'),point(2,20,398923,'22.69')]
    last=point(3,40,401128,'22.82')
    last.update(raw_text=text,candidate=None,status='malformed_or_unavailable',visual_level=None,
        visual_status='unavailable',neural_level=None,**changes)
    return rows+[last]


def test_unique_x_percent_can_contribute_only_to_experimental_endpoints():
    snap=snapshot(x_rows(),40);frozen=deepcopy(snap)
    pace=responsive_pace(snap,dict(value=67),now=NOW+timedelta(seconds=40))
    recovery,=pace['conditional_recoveries']
    assert recovery['status']=='eligible_experimental' and not recovery['trusted']
    assert recovery['value']['exp']=='401128' and recovery['value']['percentage']=='22.82'
    assert pace['readings']==3 and pace['active']
    assert snap==frozen and snap['percentage_progress']['current_segment'] is None
    assert all(not v['eligible'] for v in window_comparisons(snap,now=NOW+timedelta(seconds=40)).values())
    assert history(snap)[-1]['reading'] is None


@pytest.mark.parametrize('text,reason',[
    ('4,059122.82X1','full_pair_not_arithmetically_supported'),
    ('401.128122.25X1','full_pair_not_arithmetically_supported'),
    ('396.684122.57X1','temporal_numeric_contradiction'),
])
def test_x_rejects_arithmetic_or_temporal_contradictions(text,reason):
    pace=responsive_pace(snapshot(x_rows(text),40),dict(value=67),now=NOW+timedelta(seconds=40))
    assert pace['conditional_recoveries'][0]['reason']==reason
    assert not pace['active'] and pace['readings']==2


def test_x_can_start_a_new_baseline_without_crossing_or_repairing_an_anomaly():
    from exp_tracker.pace_intervals import collect
    from exp_tracker.product import reading
    rows=x_rows();bad=point(3,40,399979,'22.25')
    bad.update(raw_text='399.979122.25%1',candidate=None,status='malformed_or_unavailable')
    bad['neural_level'].update(level=57,text='57',score=.68772)
    rows[-1].update(index=4,event_id='run:4',received_at=(NOW+timedelta(seconds=60)).isoformat(),frame_sha256=f'{4:064x}')
    rows.insert(2,bad);snap=snapshot(rows,60);now=NOW+timedelta(seconds=60)
    strict=collect(snap,now=now,read=reading,max_interval_seconds=300)
    assert strict['recoveries'][0]['starts_new_baseline']
    assert all(e['after']['event_id']!='run:4' for e in strict['intervals'])
    public=responsive_pace(snap,dict(value=67),now=now)
    assert public['total_gain']['approximate']==401128-397820
    assert not public['conditional_recoveries'][0]['numerical_identity_verified']


@pytest.mark.parametrize('kind',['one_prior','old_support','one_recent','ambiguous','competing_level','clipped','unsupported_requirement','missing_hash'])
def test_x_abstains_without_every_required_corroboration(kind,monkeypatch):
    import exp_tracker.pace_intervals as module
    rows=x_rows()
    if kind=='one_prior':rows=rows[1:]
    elif kind=='old_support':rows[-1].update(received_at=(NOW+timedelta(seconds=200)).isoformat())
    elif kind=='one_recent':
        rows[1]['received_at']=(NOW+timedelta(seconds=120)).isoformat()
        rows[-1]['received_at']=(NOW+timedelta(seconds=140)).isoformat()
    elif kind=='competing_level':rows[-1]['neural_level']=dict(status='numeric_candidate',text='57',level=57,score=.99)
    elif kind=='clipped':rows[-1]['crop_suspect']=True
    elif kind=='missing_hash':rows[0]['frame_sha256']=None
    elif kind=='unsupported_requirement':
        for r in rows:
            r.update(visual_level=100,neural_level=dict(status='numeric_candidate',text='100',level=100,score=.99))
    snap=snapshot(rows,200)
    if kind=='ambiguous':
        original=module.interpret_exp
        def duplicate(text):
            result=deepcopy(original(text))
            if result['symbol_hypotheses']:result['symbol_hypotheses']*=2
            return result
        monkeypatch.setattr(module,'interpret_exp',duplicate)
    pace=responsive_pace(snap,dict(value=100 if kind=='unsupported_requirement' else 67),now=NOW+timedelta(seconds=200))
    # One prior reading has no interval at all; its recovery decision is still
    # available from the shared collector used by Advanced.
    result=module.collect(snap,now=NOW+timedelta(seconds=200),read=__import__('exp_tracker.product',fromlist=['reading']).reading,max_interval_seconds=300)
    assert result['recoveries'][0]['status']=='rejected'
    assert pace is None or not pace['active']


def test_confirmed_new_level_after_a_gap_never_subtracts_old_exp():
    rows=[point(1,0,1757000,'99.95'),point(2,20,1757300,'99.97'),missing(3,40),point(4,60,103,'0.01',level=68),point(5,80,435,'0.02',level=68)]
    snap=snapshot(rows,80);now=NOW+timedelta(seconds=80)
    pace=responsive_pace(snap,dict(value=68),now=now)
    assert pace['total_gain']['approximate']==requirement(67)['to_next']-1757000+435
    assert pace['estimates']['exp_per_hour']['transition_gain_included']
    assert pace['coverage_seconds']['approximate']==80


def test_conditional_recovery_is_queryable_after_restart_without_changing_sqlite(tracking):
    import json
    from exp_tracker.server import create_server
    from exp_tracker.store import Store
    from tests.test_server import request
    path,store,d=tracking
    append(d,1,'494,285[33.00%]',candidate=[494285,33.0],status='diagnostic_pair',frame_sha256=f'{1:064x}')
    append(d,2,'495,034[33.05%]',candidate=[495034,33.05],status='diagnostic_pair',frame_sha256=f'{2:064x}')
    append(d,3,'495.783133.10X1',candidate=None,status='malformed_or_unavailable',frame_sha256=f'{3:064x}')
    payload=store.db.execute('SELECT payload_json FROM diagnostic_attempts ORDER BY id DESC LIMIT 1').fetchone()[0]
    with create_server(path,port=0,diagnostic_dashboard=True) as http:
        public=json.loads(request((http,None),'/api/players/alpha')[2])['player']
        assert public['reading']['evidence']=='conditional_symbol' and public['reading']['exp']=='495783'
        assert public['original_percentage_state']['public_eligible'] is False
        advanced=json.loads(request((http,None),'/dev/api/streams/alpha/diagnostics')[2])
        assert advanced['observations'][-1]['candidate'] is None
        assert advanced['observations'][-1]['conditional_percent']['status']=='eligible_experimental'
        assert request((http,None),'/api/players/alpha','POST')[0]==405
    with Store(path,read_only=True) as reopened:
        assert reopened.db.execute('SELECT payload_json FROM diagnostic_attempts ORDER BY id DESC LIMIT 1').fetchone()[0]==payload
        assert not reopened.db.execute('SELECT 1 FROM observations').fetchone()
