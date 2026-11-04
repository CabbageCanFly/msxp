from copy import deepcopy
from datetime import timedelta

import pytest

from exp_tracker.diagnostic_progress import progress
from tests.test_diagnostic_progress import row,NOW
from tests.test_diagnostics import configured


def sequence(values,interval=15,**changes):
    return [row(i,pct,frame_sha256=f'{i:064x}',interval_seconds=interval,
        received_at=(NOW+timedelta(seconds=(i-1)*interval)).isoformat(),**changes) for i,pct in enumerate(values,1)]


def evaluate(rows,extra=0):
    from datetime import datetime
    return progress(rows,now=datetime.fromisoformat(rows[-1]['received_at'])+timedelta(seconds=extra))


def numerical_recovery(interval):
    from decimal import Decimal
    rows=sequence(['35.96','89.00','89.10','89.20'],interval=20)
    for i,r in enumerate(rows):
        percentage=r['percentage_only_candidate']['percentage']
        exp=str(round(Decimal(percentage)*294216/100))
        r.update(received_at=(NOW+timedelta(seconds=interval*i)).isoformat(),
            raw_text=f'{exp}[{percentage}%]',candidate=dict(exp=exp,percentage=percentage),
            percentage_only_candidate=None,status='diagnostic_pair',visual_level=40,
            neural_level=dict(level=40,text='40',score=.99,status='numeric_candidate',preprocessing='neutral4'),local_age_seconds=1)
    return rows


@pytest.mark.parametrize('interval',[40,50,70,120,180,300])
def test_slow_numerical_recovery_starts_new_baseline_without_counting_gap(interval):
    rows=numerical_recovery(interval);before=deepcopy(rows)
    assert evaluate(rows[:2])['latest_percentage']['percentage']=='35.96'
    recovered=evaluate(rows[:3])
    assert recovered['latest_percentage']['percentage']=='89.10'
    assert recovered['percentage_reviews'][-1]['break_before']=='confirmed_change_new_baseline'
    assert recovered['current_segment']['readings']==1
    assert recovered['current_segment']['difference_bp']==0
    assert recovered['current_pace'] is None
    assert evaluate(rows)['latest_percentage']['percentage']=='89.20'
    assert rows==before


@pytest.mark.parametrize('change',[
    dict(frame_sha256=None),dict(frame_sha256='2'.zfill(64)),dict(crop_suspect=True),
    dict(local_age_seconds=16),dict(local_age_seconds=None),dict(fresh_at_capture=False),
    dict(hud_count=2),dict(candidate_invalid=True),dict(reading_invalidated=True),
    dict(neural_level=dict(level=40,score=.99,source_complete=False)),
    dict(candidate=dict(exp='1',percentage='89.10'),raw_text='1[89.10%]'),
])
def test_slow_recovery_does_not_bypass_bad_capture_or_arithmetic(change):
    rows=numerical_recovery(180);rows[2].update(change)
    result=evaluate(rows[:3])
    assert result['latest_percentage']['percentage']=='35.96'
    assert result['current_pace'] is None


def test_slow_recovery_is_bounded_and_percentage_only_keeps_strict_confirmation():
    assert evaluate(numerical_recovery(301)[:3])['latest_percentage']['percentage']=='35.96'
    rows=sequence(['35.96','89.00','89.10'],interval=20)
    for i,r in enumerate(rows):r['received_at']=(NOW+timedelta(seconds=i*180)).isoformat()
    assert evaluate(rows)['latest_percentage']['percentage']=='35.96'


@pytest.mark.parametrize('change',[dict(index=4),dict(source_identity='other'),dict(character_id=2),
    dict(session_id=2),dict(run_id='other'),dict(visual_level=41,neural_level=dict(level=41,score=.99))])
def test_slow_recovery_cannot_confirm_across_missing_attempt_or_context_change(change):
    rows=numerical_recovery(180);rows[2].update(change)
    decision=evaluate(rows[:3])['percentage_reviews'][-1]
    assert decision['break_before']!='confirmed_change_new_baseline'
    assert decision['resolves_event_id'] is None


def test_slow_upward_spike_returns_to_old_reference_without_counted_gain():
    rows=numerical_recovery(180)
    rows[2]=deepcopy(rows[0])
    rows[2].update(index=3,event_id='run:3',frame_sha256='3'.zfill(64),
        received_at=(NOW+timedelta(seconds=360)).isoformat())
    result=evaluate(rows[:3])
    assert result['latest_percentage']['percentage']=='35.96'
    assert result['percentage_reviews'][-1]['resolution']=='suspected_ocr_anomaly'
    assert all(s['difference_bp']==0 for s in result['segments'])


def test_slow_recovery_matches_incremental_review():
    from datetime import datetime
    from exp_tracker.diagnostic_evidence import project
    from exp_tracker.diagnostic_percentage import review
    from exp_tracker.diagnostic_progress import percentage_point
    rows=project(numerical_recovery(180))
    state={};incremental=[]
    for r in rows:
        incremental+=review([r],[percentage_point(r)],now=datetime.fromisoformat(r['received_at']),state=state)
    assert incremental[-1]['public_eligible']
    assert incremental[2]['break_before']=='confirmed_change_new_baseline'
    assert [r['public_eligible'] for r in incremental]==[r['public_eligible'] for r in evaluate(rows)['percentage_reviews']]


def test_endpoint_totals_count_only_progress_after_slow_recovery():
    from datetime import datetime
    from exp_tracker.diagnostic_evidence import project
    from exp_tracker.pace_intervals import collect_observed,endpoint_interval
    from exp_tracker.product import reading
    rows=project(numerical_recovery(180));result=evaluate(rows)
    for r,decision in zip(rows,result['percentage_reviews']):r['percentage_review']=decision
    collected=collect_observed(dict(observations=rows,percentage_progress=result),
        now=datetime.fromisoformat(rows[-1]['received_at']),read=reading,max_interval_seconds=300)
    points=collected['points']
    assert [p['event_id'] for p in points]==['run:1','run:3','run:4']
    assert endpoint_interval(points[0],points[1])==(None,'confirmed_change_new_baseline')
    gain,_=endpoint_interval(points[1],points[2])
    assert gain['value']['approximate']==int(rows[3]['candidate']['exp'])-int(rows[2]['candidate']['exp'])


def test_slow_recovery_reaches_public_player_and_survives_restart(configured):
    import json
    from datetime import datetime
    from exp_tracker.store import Store
    from exp_tracker.diagnostics import Diagnostics
    from exp_tracker.product import player
    rows=numerical_recovery(180);now=datetime.fromisoformat(rows[2]['received_at'])
    with Store(configured) as store:
        d=Diagnostics(store);d.begin('slow','alpha',dict(type='configuration',trusted=False,interval=20))
        for r in rows[:3]:
            d.append('slow',dict(type='attempt',trusted=False,current=True,index=r['index'],
                attempted_at=r['received_at'],received_at=r['received_at'],frame_sha256=r['frame_sha256'],
                source=dict(kind='twitch',channel='alpha'),neural=dict(text=r['raw_text']),
                candidate=[int(r['candidate']['exp']),float(r['candidate']['percentage'])],
                visual_level=40,visual_status='available',neural_level=r['neural_level'],
                status='diagnostic_pair',local_age_seconds=1,localization=dict(count=1)))
        result=player(d.snapshot('alpha',now=now),now=now)
        assert result['reading']['percentage']=='89.10'
        assert result['segment']['readings']==1
        assert result['estimates']['exp_per_hour'] is None
        tracked=d.rolling_history('alpha',now=now)
        assert tracked['intervals']==0
        raw=[r[0] for r in store.db.execute('SELECT payload_json FROM diagnostic_attempts')]
        assert len(raw)==3 and json.loads(raw[1])['candidate'][1]==89
    with Store(configured,read_only=True) as store:
        assert player(Diagnostics(store).snapshot('alpha',now=now),now=now)==result
        assert raw==[r[0] for r in store.db.execute('SELECT payload_json FROM diagnostic_attempts')]


@pytest.mark.parametrize('interval',[7,15,20,30])
@pytest.mark.parametrize('lower',[('76.50','76.50'),('76.50','76.75')])
def test_two_distinct_lower_captures_confirm_new_baseline_without_negative_or_recovery_gain(interval,lower):
    rows=sequence(['77.00',*lower,'76.80','76.90'],interval)
    pending=evaluate(rows[:2]);assert pending['latest_percentage']['percentage']=='77.00'
    assert pending['current_segment'] is None and pending['percentage_state']['status']=='pending_exp_decrease'
    result=evaluate(rows);confirmed=result['percentage_reviews'][2]
    assert confirmed['status']=='corroborated_lower_baseline'
    assert result['segments'][-1]['start_percentage']==lower[1]
    assert result['segments'][-1]['difference_bp']==7690-int(float(lower[1])*100)
    assert result['segments'][-1]['first_event_id']==rows[2]['event_id']
    assert not any(c['change']=='negative' for c in result['comparisons'])
    assert result['percentage_reviews'][1]['status']=='pending_exp_decrease'  # No retrospective promotion.


def test_isolated_decrease_recovers_causally_without_bridging_excluded_interval():
    rows=sequence(['74.76','74.22','74.81','74.85']);before=deepcopy(rows)
    result=evaluate(rows)
    assert result['percentage_reviews'][2]['resolution']=='suspected_ocr_anomaly'
    assert result['segments'][-1]['start_percentage']=='74.81'
    assert result['segments'][-1]['difference_bp']==4 and rows==before


def test_unknown_level_percentage_reference_still_quarantines_decreases_without_confirming_loss():
    rows=sequence(['74.94','74.92','75.00'],visual_level=None)
    pending=evaluate(rows[:2]);assert pending['latest_percentage']['percentage']=='74.94'
    assert pending['percentage_state']['status']=='unresolved_numerical_continuity'
    recovered=evaluate(rows);assert recovered['latest_percentage']['percentage']=='75.00'
    assert recovered['percentage_state']['resolution']=='suspected_ocr_anomaly'
    assert recovered['current_segment'] is None


@pytest.mark.parametrize('change',[
    dict(frame_sha256='2'.zfill(64)),dict(frame_sha256=None),dict(crop_suspect=True),
    dict(raw_text='76,50%1',percentage_only_candidate=None),
])
def test_duplicate_unknown_or_suspect_visual_evidence_does_not_confirm(change):
    rows=sequence(['77.00','76.50','76.50']);rows[2].update(change)
    assert evaluate(rows)['latest_percentage']['percentage']=='77.00'
    assert evaluate(rows)['current_segment'] is None


def test_repeated_grammar_repairs_cannot_confirm_numeric_loss():
    rows=sequence(['77.00','76.50','76.60'])
    for r in rows[1:]:r.update(raw_text=r['raw_text'][:-1]+'1',percentage_only_candidate=None,status='malformed_or_unavailable')
    result=evaluate(rows)
    assert result['latest_percentage']['percentage']=='77.00' and result['current_pace'] is None


def test_large_drop_remains_unresolved_even_with_two_or_three_distinct_clean_frames():
    rows=sequence(['75.68','25.21','25.24','75.60','75.74'])
    for n in (2,3,4):
        result=evaluate(rows[:n]);assert result['latest_percentage']['percentage']=='75.68'
        assert result['percentage_state']['status']=='unresolved_numerical_continuity'
    recovered=evaluate(rows)
    assert recovered['latest_percentage']['percentage']=='75.74' and recovered['current_segment']['readings']==1


def test_false_upward_spike_is_not_a_fallible_public_reference_or_counted_gain():
    rows=sequence(['75.00','95.00','75.10','75.15'])
    assert evaluate(rows[:2])['latest_percentage']['percentage']=='75.00'
    result=evaluate(rows);assert result['percentage_reviews'][2]['resolution']=='suspected_ocr_anomaly'
    assert result['current_segment']['difference_bp']==5
    legitimate=evaluate(sequence(['75.00','95.00','95.10']))
    assert legitimate['latest_percentage']['percentage']=='95.10'  # No maximum gain/rate cap.
    assert legitimate['current_segment']['readings']==1


@pytest.mark.parametrize('values,status',[
    (['75.00','95.00','74.90'],'pending_exp_decrease'),
    (['75.00','74.50','95.00'],'pending_large_increase'),
])
def test_resolving_one_suspicion_never_bypasses_confirmation_in_the_opposite_direction(values,status):
    result=evaluate(sequence(values))
    assert result['latest_percentage']['percentage']=='75.00'
    assert result['percentage_state']['status']==status


def test_timeout_keeps_old_receipt_age_and_requires_fresh_pair_or_return():
    rows=sequence(['77.00','76.50'],30)
    expired=evaluate(rows,extra=61)
    assert expired['percentage_state']['reason']=='confirmation_expired' and expired['stale']
    assert expired['latest_percentage']['timestamp']==rows[0]['received_at']
    # A late lower observation is not confirmation of the first one.
    rows+=sequence(['76.60'],30)
    rows[-1].update(index=3,event_id='run:3',frame_sha256='3'.zfill(64),received_at=(NOW+timedelta(seconds=95)).isoformat())
    assert evaluate(rows)['latest_percentage']['percentage']=='77.00'


def test_repeated_timed_out_candidates_never_refresh_the_old_public_value():
    result=evaluate(sequence(['77.00','76.50','76.60'],300))
    state=result['percentage_state']
    assert state['reason']=='confirmation_expired'
    assert state['verification_deadline']==(NOW+timedelta(seconds=360)).isoformat()
    assert result['latest_percentage']['timestamp']==NOW.isoformat()


@pytest.mark.parametrize('span,confirmed',[(60,True),(61,False)])
def test_explicit_maximum_confirmation_span(span,confirmed):
    rows=sequence(['77.00','76.50','76.60'],60)
    rows[2]['received_at']=(NOW+timedelta(seconds=60+span)).isoformat()
    assert (evaluate(rows)['percentage_state']['status']=='corroborated_lower_baseline') is confirmed


def test_future_level_cannot_discard_a_valid_reference_for_subsequent_decrease():
    rows=sequence(['77.00','20.00','76.50'])
    rows[1].update(visual_level=65,received_at=(NOW+timedelta(seconds=300)).isoformat())
    result=evaluate(rows)
    assert result['latest_percentage']['percentage']=='77.00'


@pytest.mark.parametrize('changes',[
    dict(status='capture_failed',capture_acquired=False),dict(fresh_at_capture=False),dict(hud_count=2),
    dict(visual_level=None),dict(neural_level=dict(level=54)),
])
def test_failure_or_uncertain_level_cannot_count_towards_confirmation(changes):
    rows=sequence(['77.00','76.50','76.60','76.70']);rows[2].update(changes)
    assert evaluate(rows)['latest_percentage']['percentage']=='77.00'
    assert evaluate(rows)['current_segment'] is None


@pytest.mark.parametrize('changes',[
    dict(visual_level=65),dict(character_id=2),dict(session_id=2),dict(run_id='other'),dict(channel='other')])
def test_explicit_boundaries_establish_separate_baseline_not_an_inferred_loss(changes):
    rows=sequence(['77.00','76.50','10.00']);rows[2].update(changes)
    result=evaluate(rows)
    assert result['latest_percentage']['percentage']=='10.00'
    assert result['segments'][-1]['readings']==1


def test_sqlite_api_and_restart_share_quarantine_without_mutating_raw_or_trusted_state(configured,monkeypatch):
    import json
    from datetime import datetime
    from exp_tracker.store import Store
    from exp_tracker.diagnostics import Diagnostics
    from exp_tracker.product import player
    import exp_tracker.server as http
    import exp_tracker.diagnostics as persistence
    from tests.test_server import request
    clock=[NOW]
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return clock[0]
    monkeypatch.setattr(http,'datetime',Clock);monkeypatch.setattr(persistence,'datetime',Clock)
    rows=sequence(['77.00','76.50','76.60'])
    with Store(configured) as store:
        before=store.state('alpha',as_of=NOW);d=Diagnostics(store)
        d.begin('loss','alpha',dict(type='configuration',trusted=False,interval=15))
        def append(r):
            d.append('loss',dict(type='attempt',trusted=False,current=True,index=r['index'],
                attempted_at=r['received_at'],received_at=r['received_at'],frame_sha256=r['frame_sha256'],
                source=dict(kind='twitch',channel='alpha'),neural=dict(text=r['raw_text']),
                visual_level=64,visual_status='available',status='diagnostic_percentage_only',localization=dict(count=1)))
        append(rows[0]);append(rows[1]);clock[0]=NOW+timedelta(seconds=15)
        with http.create_server(configured,port=0,diagnostic_dashboard=True) as server:
            for p in (json.loads(request((server,None),'/api/players')[2])['players'][0],
                      json.loads(request((server,None),'/api/players/alpha')[2])['player']):
                assert p['reading']['percentage']=='77.00' and p['reading']['event_id']=='loss:1'
                assert p['percentage_state']['status']=='pending_exp_decrease'
                assert (p.get('estimates') or {}).get('exp_per_hour') is None  # The Streamers list never carries it.
            raw=json.loads(request((server,None),'/dev/api/streams/alpha/diagnostics')[2])['observations'][-1]
            assert raw['raw_text']=='[76.50%]' and not raw['percentage_review']['public_eligible']
        append(rows[2]);clock[0]=NOW+timedelta(seconds=30)
        result=player(d.snapshot('alpha',now=clock[0]),now=clock[0])
        assert result['reading']['percentage']=='76.60' and result['segment']['readings']==1
        payloads=[r[0] for r in store.db.execute('select payload_json from diagnostic_attempts')]
        assert store.state('alpha',as_of=NOW)==before
        assert not store.db.execute('select 1 from observations').fetchone()
    with Store(configured,read_only=True) as store:
        assert player(Diagnostics(store).snapshot('alpha',now=clock[0]),now=clock[0])==result
        assert payloads==[r[0] for r in store.db.execute('select payload_json from diagnostic_attempts')]
