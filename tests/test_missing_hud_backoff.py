"""Live scheduling backs off only sustained, explicit missing-HUD results."""
from copy import deepcopy

import pytest

from exp_tracker.video import Source
from tests.test_capture_performance import lanes, schedule  # noqa: F401


def missing(index):
    return dict(type='attempt',index=index,status='unavailable',received_at='fresh',
                reasons=['missing_hud'],localization=dict(count=0))


def run(schedule, response=missing, *, continuous=True, source='twitch', interval=20, count=10, work=0):
    now=[0.];starts=[];records=[];activity={};group=lanes('channel',count=count,interval=interval)
    group[0]['source']=Source(source,'channel' if source=='twitch' else 'unused')
    def perform(lane,index,seek):
        starts.append(now[0]);now[0]+=work
        return response(index)
    result=schedule(group,perform,lambda lane,record:records.append(deepcopy(record)),
        clock=lambda:now[0],sleep=lambda seconds:now.__setitem__(0,now[0]+max(0,seconds)),
        continuous=continuous,max_attempts=count,activity=activity)
    assert result is False
    return group[0],starts,records,activity


def test_two_minutes_of_missing_hud_switches_to_minute_checks_without_skipped_deadlines(schedule):
    lane,starts,records,activity=run(schedule)
    assert starts==[0,20,40,60,80,100,120,180,240,300]
    assert not any(r['hud_backoff']['active'] for r in records[:6])
    assert all(r['hud_backoff']['active'] for r in records[6:])
    assert lane['skipped']==0 and lane['args'].interval==20
    assert activity['channel']['effective_interval_seconds']==60
    assert records[-1]['hud_backoff']['missing_seconds']==300


def test_brief_misses_do_not_accumulate_across_a_detected_hud(schedule):
    def response(index):
        return dict(type='attempt',index=index,status='malformed_or_unavailable',received_at='fresh',
                    reasons=['exp_unavailable'],localization=dict(count=1)) if index==7 else missing(index)
    _,starts,records,_=run(schedule,response,count=15)
    assert starts==list(range(0,261,20))+[320]
    assert records[12]['hud_backoff']['active'] is False
    assert records[13]['hud_backoff']['active'] is True


@pytest.mark.parametrize('recovery',[
    dict(status='malformed_or_unavailable',reasons=['exp_unavailable'],localization=dict(count=1)),
    dict(status='unavailable',reasons=['multiple_huds'],localization=dict(count=2)),
    dict(status='capture_failed',reasons=['stream_ended'],localization=None,received_at=None),
    dict(status='stale_local_frame',reasons=['missing_hud','local_receipt_age_exceeded']),
    dict(status='unavailable',reasons=['localization_failed'],localization=None),
    dict(received_at=None),
])
def test_detected_or_ambiguous_hud_and_capture_errors_restore_normal_cadence(schedule,recovery):
    def response(index):
        row=missing(index)
        if index==8:row.update(recovery)
        return row
    _,starts,records,_=run(schedule,response,count=9)
    assert starts==[0,20,40,60,80,100,120,180,200]
    assert records[7]['hud_backoff']==dict(active=False,missing_seconds=0,next_interval_seconds=20)
    assert records[8]['hud_backoff']['missing_seconds']==0


@pytest.mark.parametrize('continuous,source,interval',[(False,'twitch',20),(True,'file',20),(True,'twitch',90)])
def test_bounded_capture_local_files_and_slower_requested_intervals_keep_their_cadence(schedule,continuous,source,interval):
    _,starts,records,_=run(schedule,continuous=continuous,source=source,interval=interval)
    assert starts==list(range(0,10*interval,interval))
    assert not any(r.get('hud_backoff',{}).get('active') for r in records)


def test_at_least_three_missing_frames_are_required_even_when_work_is_slow(schedule):
    lane,starts,records,_=run(schedule,count=2,work=130)
    assert starts==[0,140] and lane['effective_interval']==20
    assert not records[-1]['hud_backoff']['active']


def test_long_work_counts_only_real_missed_slots_on_the_effective_interval(schedule):
    lane,starts,_,_=run(schedule,count=4,work=70)
    assert starts==[0,80,160,280] and lane['skipped']==8


def test_one_channel_backing_off_keeps_other_channels_at_the_requested_interval(schedule):
    now=[0.];starts={'quiet':[],'playing':[]};group=lanes('quiet','playing',count=10,interval=20)
    for lane in group:lane['source']=Source('twitch',lane['channel'])
    def perform(lane,index,seek):
        starts[lane['channel']].append(now[0])
        return missing(index) if lane['channel']=='quiet' else dict(type='attempt',index=index,status='diagnostic_pair',received_at='fresh')
    schedule(group,perform,lambda *_:None,continuous=True,max_attempts=10,
             clock=lambda:now[0],sleep=lambda seconds:now.__setitem__(0,now[0]+seconds))
    assert starts['quiet']==[0,20,40,60,80,100,120,180,240,300]
    assert starts['playing']==list(range(0,200,20))


def test_recheck_cadence_survives_capture_run_rotation(schedule):
    now=[0.];starts=[];rotated=[];group=lanes('channel',interval=20)
    group[0]['source']=Source('twitch','channel')
    def perform(lane,index,seek):starts.append(now[0]);return missing(index)
    schedule(group,perform,lambda *_:None,continuous=True,max_attempts=62,
             rotate=lambda lane:rotated.append(lane['effective_interval']),
             clock=lambda:now[0],sleep=lambda seconds:now.__setitem__(0,now[0]+seconds))
    assert rotated==[60] and starts[-1]-starts[-2]==60
