"""Presentation context cannot become numerical or continuity evidence."""
from datetime import timedelta

import pytest

from exp_tracker.diagnostics import operation
from exp_tracker.product import refresh
from exp_tracker.shadow_grammar import interpret_exp
from exp_tracker.shadow_types import parse_percentage_only
from tests.test_product import NOW, append, get, tracking


def test_supported_display_level_survives_conflict_failure_and_quarantine(tracking):
    _,store,d=tracking
    for i,pct in enumerate(('33.00','33.05','33.10'),1):append(d,i,f'[{pct}%]')
    established=get(d)['display_level']
    append(d,4,'[33.15%]',visual_level=None,visual_status='unavailable',
        neural_level=dict(text='55',level=55,status='numeric_candidate',score=.99,preprocessing='neutral4'))
    conflict=get(d,45)
    assert conflict['display_level']['value']==64 and conflict['display_level']['last_known']
    assert conflict['display_level']['timestamp']==established['timestamp']
    assert conflict['reading']['level']['value'] is None
    assert conflict['reading']['estimated_exp'] is None
    assert conflict['estimates']['exp_per_hour'] is None
    assert not conflict['early_pace']['active'] and conflict['early_pace']['segment']['readings']==3
    append(d,5,None,status='capture_failed',received_at=None,current=False)
    assert get(d,60)['display_level']['value']==64
    append(d,6,'[32.00%]',visual_level=None,neural_level=None)
    assert get(d,75)['display_level']['value']==64
    assert not get(d,75)['percentage_state']['public_eligible']
    assert store.state('alpha')['last_trusted'] is None


def test_new_supported_level_replaces_badge_but_new_session_does_not_inherit_it(tracking):
    _,store,d=tracking
    append(d,1,'[33.00%]');append(d,2,'[33.05%]')
    append(d,3,'[34.00%]',visual_level=65,neural_level=dict(text='65',level=65,status='numeric_candidate',score=.99))
    # Agreement of both readers replaces the display immediately; accounting still breaks.
    assert get(d)['display_level']['value']==65
    append(d,4,'[34.05%]',visual_level=65,neural_level=dict(text='65',level=65,status='numeric_candidate',score=.99))
    assert get(d,45)['display_level']['value']==65
    store.end_session('alpha',at=NOW+timedelta(seconds=60))
    store.start_session('alpha',at=NOW+timedelta(seconds=61))
    assert get(d,62)['display_level'] is None


def test_early_pace_is_independent_of_completed_windows_and_ages_without_mutation(tracking):
    _,_,d=tracking
    for i,pct in enumerate(('33.00','33.05','33.10'),1):append(d,i,f'[{pct}%]')
    p=get(d)
    assert p['early_pace']['active'] and p['early_pace']['segment']['span_seconds']['approximate']==30
    assert not p['windows']['5']['eligible']
    old=refresh(p,now=NOW+timedelta(seconds=100))
    assert not old['early_pace']['active'] and old['early_pace']['estimates']['exp_per_hour']
    assert old['estimates']['exp_per_hour'] is None and p['early_pace']['active']
    assert old['display_level']['last_known'] and old['display_level']['age_seconds']==70


def test_exp_label_tail_is_only_a_complete_percentage_hypothesis():
    result=interpret_exp('P[90.78%]')
    assert result['policy']=='bounded_exp_v7'
    assert result['symbol_hypotheses']==[]  # The existing label-tail rule is unchanged.
    assert parse_percentage_only('P[90.78%]') is None
    assert not result['full_exp']['proposals'] and result['strict_percentage_only'] is None
    proposal=result['percentage']['proposals'][0]
    assert proposal['reading']['percentage']=='90.78' and not proposal['trusted']
    assert proposal['edits']==[dict(index=0,old='P',new='',category='exp_label_tail')]


@pytest.mark.parametrize('text',['PP[90.78%]','EXP[90.78%]','p[90.78%]','P90.78%]','P[90.78%1',
    'P[90,78%]','P[90.7%]','P[190.78%]','P[90.78%]text','P[9O.78%]'])
def test_label_tail_rule_does_not_repair_or_trim_arbitrary_text(text):
    assert not interpret_exp(text)['percentage']['proposals']


def test_label_tail_is_still_unverified_and_cannot_detect_valid_wrong_digits():
    assert interpret_exp('P[25.17%]')['percentage']['proposals'][0]['numerical_identity_verified'] is False
    assert interpret_exp('74,050[25.17%1')['full_exp']['proposals'][0]['reading']['exp']=='74050'


def test_waiting_jitter_has_bounded_cadence_grace_and_failures_are_preserved():
    runtime=dict(state='waiting',next_due_at=NOW.isoformat(),requested_interval_seconds=20)
    assert operation({},runtime,NOW+timedelta(seconds=5.54))['state']=='waiting'
    assert operation({},runtime,NOW+timedelta(seconds=10.01))['state']=='capture_delayed'
    assert operation({},dict(state='capture_failing'),NOW)['state']=='capture_failing'
    assert operation({},None,NOW)['state']=='coordinator_stopped'
    assert operation({},dict(state='running',updated_at=NOW.isoformat(),expected_completion_seconds=8),NOW+timedelta(seconds=9))['state']=='capture_delayed'
