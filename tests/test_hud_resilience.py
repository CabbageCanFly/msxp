"""Presentation-only unreadable-HUD aging; no synthetic gain or accounting."""
from datetime import timedelta
import json

import pytest

from exp_tracker.diagnostics import Diagnostics
from exp_tracker.product import history,player,refresh
from exp_tracker.store import Store
from tests.test_product import NOW,append,tracking
from tests.test_server import request


def at(d,index,seconds,text,**changes):
    stamp=(NOW+timedelta(seconds=seconds)).isoformat()
    append(d,index,text,attempted_at=stamp,received_at=stamp,**changes)


def present(d,seconds,state='waiting',**extra):
    now=NOW+timedelta(seconds=seconds)
    value=player(d.snapshot('alpha',now=now),now=now)
    value.update(extra)
    return refresh(value,now=now,activity=dict(state=state))


@pytest.mark.parametrize('gap',[20,60,180,320])
def test_unreadable_gaps_age_only_presentation_and_recover_without_fake_gain(tracking,gap):
    _,store,d=tracking
    for i in range(1,12):at(d,i,(i-1)*20,f'[33.{(i-1)*2:02}%]')
    base=present(d,200)['responsive_pace']
    rate=base['estimates']['exp_per_hour']['value']['approximate']
    end=200+gap
    for j,seconds in enumerate(range(220,end+1,20),12):
        at(d,j,seconds,'?',status='malformed_or_unavailable',visual_level=None,neural_level=None)
    p=present(d,end);pace=p['responsive_pace'];shown=pace['presentation']
    assert pace['estimates']['exp_per_hour']['value']['approximate']==rate
    if gap>=300:
        assert shown['state']=='paused' and shown['estimates']['exp_per_hour'] is None
    else:
        assert shown['state']=='aging' and shown['assumption']=='no_new_gain_since_last_observed_interval'
        # The rolling pool expires whole old edges while unreadable time advances.
        covered=200 if gap<=60 else 120
        assert pace['coverage_seconds']['approximate']==covered
        assert shown['estimates']['exp_per_hour']['value']['approximate']==pytest.approx(rate*covered/(covered+max(0,gap-20)))
    before=store.state('alpha',as_of=NOW+timedelta(seconds=end))
    index=11+gap//20
    at(d,index+1,end+20,'[34.00%]');at(d,index+2,end+40,'[34.02%]')
    p=present(d,end+40);pace=p['responsive_pace']
    assert pace['active'] and pace['presentation']['state']=='observed'
    assert pace['estimates']['exp_per_hour']['value']['approximate']==pytest.approx(rate)
    rows=history(d.snapshot('alpha',now=NOW+timedelta(seconds=end+40)))
    assert not rows[-2]['connect_previous'] and rows[-1]['connect_previous']
    assert not p['windows']['5']['eligible']
    assert store.state('alpha',as_of=NOW+timedelta(seconds=end))==before
    assert not store.db.execute('SELECT 1 FROM observations').fetchone()


@pytest.mark.parametrize('change',[
    dict(localization=dict(count=2)),dict(current=False),
    dict(neural_level=dict(text='55',level=55,status='numeric_candidate',score=.99)),
    dict(visual_level=65,neural_level=dict(text='65',level=65,status='numeric_candidate',score=.99)),
])
def test_unsafe_or_new_level_evidence_does_not_age_as_unreadable(tracking,change):
    _,_,d=tracking
    at(d,1,0,'[33.00%]');at(d,2,20,'[33.02%]')
    at(d,3,40,'[33.04%]',**change)
    p=present(d,40)
    assert not p['responsive_pace']['active']
    assert p['responsive_pace']['presentation']['state']!='aging'


def test_completed_offline_and_stationary_rates_never_look_like_current_decay(tracking):
    _,_,d=tracking
    at(d,1,0,'[33.00%]');at(d,2,20,'[33.00%]')
    at(d,3,40,'?',status='malformed_or_unavailable')
    assert present(d,60)['responsive_pace']['presentation']['estimates']['exp_per_hour']['value']['approximate']==0
    for state in ('capture_finished','coordinator_stopped','capture_interrupted'):
        shown=present(d,90,state)['responsive_pace']['presentation']
        assert shown['state']=='historical' and shown['assumption'] is None
    offline=present(d,90,twitch=dict(status='offline'))
    assert offline['responsive_pace']['presentation']['state']=='historical'
    assert offline['responsive_pace']['presentation']['estimates']['eta'] is None


def test_restart_restores_evidence_but_does_not_join_new_run(tracking):
    path,store,d=tracking
    at(d,1,0,'[33.00%]');at(d,2,20,'[33.02%]')
    at(d,3,40,'?',status='malformed_or_unavailable')
    saved=present(d,40,'coordinator_stopped')
    with Store(path) as reopened:
        other=Diagnostics(reopened);restored=present(other,40,'coordinator_stopped')
        assert restored==saved and restored['display_level']['value']==64
        assert len(history(other.snapshot('alpha',now=NOW+timedelta(seconds=40))))==3
        other.begin('restart','alpha',dict(type='configuration',trusted=False,interval=20,source_kind='twitch'))
        restored=present(other,40)
        assert not restored['responsive_pace']['active']
        assert restored['responsive_pace']['presentation']['state']=='historical'
        stamp=(NOW+timedelta(seconds=60)).isoformat()
        raw=dict(type='attempt',trusted=False,index=1,attempted_at=stamp,received_at=stamp,current=True,
            source=dict(kind='twitch',channel='alpha'),status='diagnostic_percentage_only',localization=dict(count=1),
            neural=dict(text='[34.00%]'),visual_level=64,visual_status='available')
        other.append('restart',raw)
        assert not present(other,60)['responsive_pace']['active']
        stamp=(NOW+timedelta(seconds=80)).isoformat()
        other.append('restart',dict(raw,index=2,attempted_at=stamp,received_at=stamp,neural=dict(text='[34.02%]')))
        result=present(other,80)['responsive_pace']
        assert result['active'] and result['readings']==2 and result['coverage_seconds']['approximate']==20


def test_real_sqlite_http_batches_official_status_separately_from_capture(tracking,monkeypatch):
    from exp_tracker.server import create_server
    from exp_tracker.twitch_probe import StreamAvailability
    from exp_tracker.twitch_auth import AppTokens
    path,store,d=tracking
    at(d,1,0,'[33.00%]');at(d,2,20,'[33.02%]')
    store.add_channel('beta');cid=store.add_character('beta','Other')
    store.select_character('beta',cid);store.start_session('beta',at=NOW)
    d.begin('beta-run','beta',dict(type='configuration',trusted=False,source_kind='twitch',interval=20))
    monkeypatch.setenv('TWITCH_CLIENT_ID','secret-client');monkeypatch.setenv('TWITCH_ACCESS_TOKEN','secret-token')
    calls=[];seconds=[0]
    def fetch(*args,**kw):
        calls.append(args[1]);return dict(data=[dict(user_login='alpha',type='live')])
    with create_server(path,port=0,diagnostic_dashboard=True) as http:
        auth=AppTokens(env_file=path.parent/'absent.env',environ=dict(TWITCH_CLIENT_ID='secret-client',TWITCH_ACCESS_TOKEN='secret-token'),
            request=lambda request:dict(client_id='secret-client',expires_in=7200),clock=lambda:seconds[0])
        http.twitch_availability=StreamAvailability(enabled=True,fetch=fetch,clock=lambda:seconds[0],auth=auth)
        def get(path):
            status,_,body=request((http,None),path)
            assert status==200 and b'secret' not in body
            return json.loads(body)
        detail=get('/api/players/alpha')['player']
        assert detail['twitch']['status']=='live'
        cards=get('/api/players')['players']
        assert {p['channel']:p['twitch']['status'] for p in cards}==dict(alpha='live',beta='offline')
        assert calls==[dict(user_login=['alpha','beta'],first=100)]
        assert detail['activity']['state']=='previous_unfinished_run'  # Live on Twitch does not start a capture worker.
        assert detail['responsive_pace']['presentation']['state']=='historical'
        assert not store.db.execute('SELECT 1 FROM observations').fetchone()
