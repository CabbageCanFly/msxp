"""Responsive-only pooling: unsupported frames never become interval endpoints."""
from datetime import timedelta

import pytest

from exp_tracker.product import history,responsive_pace,window_comparisons
from tests.test_product import NOW,append,get,tracking


def neural(level=64):
    return dict(text=str(level),level=level,status='numeric_candidate',score=.99,preprocessing='neutral4')


def full(d,index,exp,percentage,**changes):
    append(d,index,f'{exp:,}[{percentage:.2f}%]',candidate=[exp,percentage],status='diagnostic_pair',
        visual_level=None,visual_status='unavailable',neural_level=neural(),frame_sha256=f'{index:064x}',**changes)


def seed(d):
    full(d,1,494285,33.00);full(d,2,495034,33.05);full(d,3,495783,33.10)


def missing(d):
    append(d,4,None,status='unavailable',current=False,localization=dict(count=0),local_age_seconds=2,
        visual_level=None,neural_level=None,reasons=['missing_hud'],frame_sha256=f'{4:064x}')


def test_matching_reacquisition_pools_only_valid_integer_edges(tracking):
    _,store,d=tracking
    seed(d);missing(d)
    full(d,5,497281,33.20)
    before=get(d,60)
    snap=d.snapshot('alpha',now=NOW+timedelta(seconds=60))
    # One ordinary missing HUD no longer discards the corroborated reader context.
    assert snap['observations'][-1]['experimental_level']['status']=='provisional_neural'
    assert snap['observations'][-1]['percentage_review']['progress_eligible']
    assert before['responsive_pace']['active']
    assert before['responsive_pace']['readings']==4
    full(d,6,498030,33.25);full(d,7,498779,33.30)
    snap=d.snapshot('alpha',now=NOW+timedelta(seconds=90))
    frozen_windows=window_comparisons(snap,now=NOW+timedelta(seconds=90))
    frozen_history=history(snap)
    pace=responsive_pace(snap,dict(value=64),now=NOW+timedelta(seconds=90))
    assert pace['active'] and pace['readings']==6 and pace['interruptions']==0
    assert pace['interval_counts']==dict(direct=4,endpoint_supported=1)
    assert pace['coverage_seconds']['approximate']==90 and pace['span_seconds']['approximate']==90
    assert pace['basis']=='observed_exp_endpoints'
    assert pace['estimates']['exp_per_hour']['value']['approximate']==pytest.approx(4494*3600/90)
    assert pace['estimates']['percentage_per_hour']['value']['approximate']==pytest.approx(12)
    assert pace['estimates']['percentage_per_hour']['nearest_half_up']['lower']['approximate']==pytest.approx(11.6)
    assert window_comparisons(snap,now=NOW+timedelta(seconds=90))==frozen_windows
    assert history(snap)==frozen_history
    assert not frozen_history[4]['connect_previous'] and frozen_history[5]['connect_previous']
    assert frozen_history[6]['connect_previous']
    assert not any(w['eligible'] for w in frozen_windows.values())
    assert not store.db.execute('SELECT 1 FROM observations').fetchone()


@pytest.mark.parametrize('kind',['conflict','level','loss','quarantine','duplicate','stale','crop','source','session','restart'])
def test_hard_boundaries_block_crossing_and_keep_unrelated_same_context_intervals(tracking,kind):
    from exp_tracker.pace_intervals import collect
    from exp_tracker.product import reading
    _,_,d=tracking
    seed(d);missing(d);full(d,5,497281,33.20);full(d,6,498030,33.25);full(d,7,498779,33.30)
    snap=d.snapshot('alpha',now=NOW+timedelta(seconds=90));row=snap['observations'][4]
    if kind=='conflict':row['experimental_level'].update(status='conflict',value=None,neural=65)
    elif kind=='level':row['experimental_level'].update(value=65,status='agreement',neural=65,visual=65)
    elif kind=='stale':row.update(status='stale_local_frame',fresh_at_capture=False)
    elif kind=='crop':row['crop_suspect']=True
    elif kind=='duplicate':row['frame_sha256']=snap['observations'][2]['frame_sha256']
    elif kind=='source':row['source_identity']='b'*64
    elif kind=='session':row['session_id']=999
    elif kind=='restart':row['run_id']='restart'
    else:
        row['percentage_review'].update(public_eligible=kind=='loss',progress_eligible=kind=='loss',break_before='confirmed_change_new_baseline' if kind=='loss' else None)
    pace=responsive_pace(snap,dict(value=64),now=NOW+timedelta(seconds=90))
    assert pace['total_gain']['approximate']==498779-494285
    assert pace['coverage_seconds']['approximate']==90
    strict=collect(snap,now=NOW+timedelta(seconds=90),read=reading,max_interval_seconds=300)
    if kind in ('conflict','stale','crop','duplicate'):
        assert all(row['event_id'] not in (e['before']['event_id'],e['after']['event_id']) for e in strict['intervals'])


def test_pool_ages_without_new_captures_and_expired_history_is_not_current(tracking):
    _,_,d=tracking
    for i in range(1,22):append(d,i,f'[33.{i:02}%]')
    before=get(d,300)['responsive_pace']
    after=get(d,345)['responsive_pace']
    assert before['readings']==21 and after['readings']==18
    assert after['coverage_seconds']['approximate']==255
    assert after['start']==(NOW+timedelta(seconds=45)).isoformat()
    old=get(d,601)
    assert old['responsive_pace']['recent_pool_expired']
    assert not old['responsive_pace']['active'] and old['responsive_pace']['retained_history']
    from exp_tracker.product import refresh
    shown=refresh(old,now=NOW+timedelta(seconds=601),activity=dict(state='waiting'))
    assert shown['responsive_pace']['presentation']['state']=='historical'
    assert shown['responsive_pace']['presentation']['estimates']['exp_per_hour']
    assert shown['responsive_pace']['presentation']['estimates']['eta'] is None


def test_directory_cache_expires_intervals_without_a_new_sqlite_revision(tracking):
    _,_,d=tracking
    for i in range(1,22):append(d,i,f'[33.{i:02}%]')
    cache={}
    before=d.directory(cache,now=NOW+timedelta(seconds=300))['streams'][0]['player']['responsive_pace']
    after=d.directory(cache,now=NOW+timedelta(seconds=345))['streams'][0]['player']['responsive_pace']
    assert before['readings']==21 and after['readings']==18
    assert after['coverage_seconds']['approximate']==255
    assert after['start']==(NOW+timedelta(seconds=45)).isoformat()
    expired=d.directory(cache,now=NOW+timedelta(seconds=601))['streams'][0]['player']['responsive_pace']
    assert not expired['active'] and expired['recent_pool_expired']


def test_contradictory_integer_on_pending_frame_is_not_a_soft_gap(tracking):
    _,_,d=tracking
    seed(d);missing(d)
    full(d,5,1,33.20)  # Strict syntax, gross contradiction at the earlier supported level.
    full(d,6,498030,33.25);full(d,7,498779,33.30)
    pace=get(d,90)['responsive_pace']
    assert pace['active'] and pace['readings']==5
    assert pace['coverage_seconds']['approximate']==90 and pace['interruptions']==0
    assert all(e['first_event_id']!='run:5' and e['last_event_id']!='run:5' for e in pace['intervals'])


@pytest.mark.parametrize('kind',['other_level_without_percentage','duplicate_missing_frame'])
def test_unreadable_frames_do_not_conceal_conflicts_or_duplicate_pixels(tracking,kind):
    _,_,d=tracking
    seed(d);missing(d)
    if kind=='other_level_without_percentage':
        append(d,5,'?',status='malformed_or_unavailable',visual_level=None,neural_level=neural(65),frame_sha256=f'{5:064x}')
    else:
        append(d,5,None,status='unavailable',current=False,localization=dict(count=0),local_age_seconds=2,
            visual_level=None,neural_level=None,reasons=['missing_hud'],frame_sha256=f'{4:064x}')
    full(d,6,498030,33.25);full(d,7,498779,33.30);full(d,8,499528,33.35)
    pace=get(d,105)['responsive_pace']
    assert pace['active'] and pace['readings']==6
    assert pace['coverage_seconds']['approximate']==105
    assert pace['interruptions']==0
    assert pace['intervals'][-1]['start']==(NOW+timedelta(seconds=90)).isoformat()


def test_clean_rotation_and_same_assignment_twitch_restart_retain_numeric_pool(tracking):
    _,_,d=tracking
    seed(d);missing(d);full(d,5,497281,33.20);full(d,6,498030,33.25);full(d,7,498779,33.30)
    snap=d.snapshot('alpha',now=NOW+timedelta(seconds=90))
    import exp_tracker.product as module
    from unittest.mock import patch
    for row in snap['observations']:
        row.update(source_identity='a'*64,coordinator_instance='b'*32)
    # Simulate the already-validated diagnostic rotation link at the comparison seam.
    snap['observations'][5]['index']=60
    snap['observations'][6].update(run_id='rotated',index=1,rotation_from='run')
    snap['run_id']='rotated'
    with patch.object(module,'project',lambda rows:rows):
        linked=responsive_pace(snap,dict(value=64),now=NOW+timedelta(seconds=90))
        assert linked['readings']==6 and linked['interruptions']==0
        assert linked['total_gain']['approximate']==498779-494285
        snap['observations'][6]['rotation_from']=None
        unlinked=responsive_pace(snap,dict(value=64),now=NOW+timedelta(seconds=90))
        assert unlinked['active'] and not unlinked['retained_history']
        assert unlinked['total_gain']==linked['total_gain']
        assert unlinked['coverage_seconds']==linked['coverage_seconds']
