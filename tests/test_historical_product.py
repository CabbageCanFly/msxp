from datetime import timedelta

from exp_tracker.product import player
from exp_tracker.diagnostics import operation
from tests.test_product import tracking,append,NOW


def test_completed_capture_retains_dated_comparable_piece_not_reset_tail(tracking):
    _,store,d=tracking
    for i in range(1,8):
        append(d,i,f'[33.{(i-1)*5:02}%]',**(dict(localization=dict(count=2)) if i==5 else {}))
    fresh=NOW+timedelta(seconds=91)
    live=player(d.snapshot('alpha',now=fresh),now=fresh)
    assert not any(w['observed']['available'] for w in live['windows'].values())
    assert live['responsive_pace']['readings']==6
    d.append('run',dict(type='summary',trusted=False,attempts=7,interrupted=False))
    for age in (0,300,4680):
        now=fresh+timedelta(seconds=age);snap=d.snapshot('alpha',now=now);p=player(snap,now=now)
        assert operation(snap,None,now)['state']=='capture_finished'
        for window in p['windows'].values():
            observed=window['observed']
            assert observed['available'] and observed['historical'] and observed['paused']
            assert observed['span_seconds']['approximate']==45 and observed['readings']==4
            assert observed['difference_percentage_points']=='0.15'
            assert not window['eligible']
        pace=p['responsive_pace']
        assert pace['readings']==6 and not pace['active']
        assert pace['interruptions']==1  # Both safe pieces survive; ambiguity supplies no edge.
        assert pace['coverage_seconds']['approximate']==60
        assert pace['end']==(NOW+timedelta(seconds=90)).isoformat()
        assert pace['age_seconds']==1+age and pace['estimates']['eta'] is None
    assert not store.db.execute('select 1 from observations').fetchone()


def test_completed_history_cannot_supply_old_level_or_manual_run_comparison(tracking):
    _,_,d=tracking
    for i in range(1,5):append(d,i,f'[33.{i:02}%]')
    for i in (5,6):append(d,i,'[0.10%]',visual_level=65,neural_level=None)
    d.append('run',dict(type='summary',trusted=False,attempts=6,interrupted=False))
    now=NOW+timedelta(seconds=76)
    p=player(d.snapshot('alpha',now=now),now=now)
    assert not any(w['observed']['available'] for w in p['windows'].values())
    d.begin('manual','alpha',dict(type='configuration',trusted=False,interval=15,source_kind='twitch'))
    d.append('manual',dict(type='summary',trusted=False,attempts=0,interrupted=False))
    p=player(d.snapshot('alpha',now=now),now=now)
    assert not any(w['observed']['available'] for w in p['windows'].values())


def test_recorded_completion_does_not_override_actual_in_process_activity():
    now=NOW
    for value,state in ((dict(run_status='completed'),'capture_finished'),(dict(run_status='interrupted'),'capture_interrupted'),
            (dict(historical=True),'historical_session'),(dict(unfinished_run_count=1),'previous_unfinished_run'),({},'coordinator_stopped')):
        assert operation(value,None,now)['state']==state
        runtime=dict(state='waiting',next_due_at=(now+timedelta(seconds=15)).isoformat())
        assert operation(value,runtime,now)['state']=='waiting'


def test_retained_window_never_selects_a_different_source(tracking):
    _,_,d=tracking
    for i in range(1,5):append(d,i,f'[33.{i:02}%]')
    append(d,5,'[33.05%]',source=dict(kind='file',channel=None))
    d.append('run',dict(type='summary',trusted=False,attempts=5,interrupted=False))
    now=NOW+timedelta(seconds=61)
    p=player(d.snapshot('alpha',now=now),now=now)
    assert not any(w['observed']['available'] for w in p['windows'].values())
