"""Background-published public state must equal the synchronous full-replay reference."""
from datetime import datetime,timedelta
import json
from pathlib import Path
import threading
import time
from urllib.request import urlopen
from urllib.error import HTTPError

import pytest

import exp_tracker.server as server_module
import exp_tracker.diagnostics as diagnostics_module
from exp_tracker.diagnostics import Diagnostics,operation
from exp_tracker.product import refresh,tracked_statistics
from exp_tracker.publisher import broadcast,encode
from exp_tracker.store import Store,utc
from tests.test_product import tracking,NOW
from tests.test_diagnostic_history import config
from tests.test_tracked_exp_totals import save,nested
from tests.test_incremental_history import scenario
from tests.test_cross_level_product import SAVED


@pytest.fixture
def clock(monkeypatch):
    class Clock(datetime):
        at=NOW
        @classmethod
        def now(cls,tz=None):return cls.at
    monkeypatch.setattr(server_module,'datetime',Clock)
    return Clock


def reference(store,server,channel,now):
    """Full replay without checkpoints at the published entry's own as-of clocks, presented at `now`.

    A card is rebuilt on a new revision or when its rolling windows age (Diagnostics.due);
    otherwise the last card is reused, as the request path always did. Its pace is labeled
    with that computation time, never with the time of serving.
    """
    entry=server.publisher.entry(channel)
    card_at=datetime.fromisoformat(entry['card']['recent_as_of']);tracked_at=datetime.fromisoformat(entry['built_at'])
    d=Diagnostics(store)
    with store._transaction():
        head=d.heads(channel)[0]
        _,card,extras=d.card({},head,now=card_at)
        tracked=d.rolling_history(channel,now=tracked_at)
    value=tracked_statistics(refresh(card['player'],now=now,activity=operation(extras['lifecycle'],None,now)),tracked,now=now,pace_as_of=card_at)
    # The removed broadcasts(): Twitch status for channels whose latest run is a Twitch source.
    row=store.db.execute('''SELECT r.configuration_json AS config,(SELECT payload_json FROM diagnostic_attempts
        WHERE run_id=r.run_id ORDER BY attempt_index DESC LIMIT 1) AS payload FROM streamers s JOIN diagnostic_runs r
        ON r.rowid=(SELECT rowid FROM diagnostic_runs WHERE streamer_id=s.id ORDER BY rowid DESC LIMIT 1) WHERE s.login=?''',(channel,)).fetchone()
    twitch=[channel] if row and (json.loads(row['config'] or '{}').get('source_kind') or json.loads(row['payload'] or '{}').get('source',{}).get('kind'))=='twitch' else []
    statuses=server.twitch_availability.snapshot(twitch,now=now)
    body=dict(player=broadcast([value],statuses,now)[0],tracked_history=tracked,history=extras['history'],truncated=extras['truncated'])
    return json.loads(encode(body))


def published(server,channel):
    body=json.loads(server.publisher.character(channel))
    for key in ('served_at','experimental','poll_seconds'):body.pop(key)
    return body


def wait_for(condition,seconds=60):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if condition():return
        time.sleep(.02)
    raise AssertionError('Timed out waiting for publication')


def current(server,store,channel):
    with store._transaction():head=tuple(Diagnostics(store).heads(channel)[0])
    entry=server.publisher.entry(channel)
    return entry is not None and entry['key']==head and entry['built_at']==server_module.datetime.at.isoformat()


def test_background_publication_matches_reference_through_rotation_restart_loss_level_and_source(tracking,clock):
    path,store,d=tracking;compared=0
    with server_module.create_server(path,port=0,diagnostic_dashboard=True,background=True) as server:
        for n,(run,index,seconds,bp,changes) in enumerate(scenario(store,d)):
            if run=='rotate':
                d.rotate('a','b','alpha',dict(type='summary',trusted=False,attempts=60,interrupted=False,
                    completion_reason='scheduled_rotation',next_run_id='b'),config('b','a',interval=20));continue
            if run=='restart':
                d.append('b',dict(type='summary',trusted=False,attempts=30,interrupted=True));d.begin('c','alpha',config('c',interval=20));continue
            save(d,run,index,seconds,bp,**changes);clock.at=NOW+timedelta(seconds=seconds)
            if n%7==0 or index in (44,45,46):  # Includes the level-up transition.
                server.publisher.wake.set();wait_for(lambda:current(server,store,'alpha'))
                assert published(server,'alpha')==reference(store,server,'alpha',clock.at);compared+=1
        last=clock.at;rebuilt=set()
        for delta in (11,31,3901,90001):  # Time-only expiry without new captures.
            clock.at=last+timedelta(seconds=delta);server.publisher.wake.set()
            wait_for(lambda:server.publisher.entry('alpha')['built_at']==clock.at.isoformat())
            rebuilt.add(server.publisher.entry('alpha')['card']['recent_as_of'])
            assert published(server,'alpha')==reference(store,server,'alpha',clock.at);compared+=1
        assert len(rebuilt)>=3  # Aging windows rebuilt the card; an expired one was reused.
        home=json.loads(server.publisher.homepage())
        assert home['players'][0]['tracked_as_of']==clock.at.isoformat() and 'warming' not in home
    assert compared>20


@pytest.mark.parametrize('channel',['emmies','niru','telfer1'])
def test_saved_publications_match_reference(tmp_path,clock,channel):
    paths=sorted(Path(SAVED).glob(f'*/{channel}/**/capture.jsonl'),key=lambda p:json.loads(p.read_text().splitlines()[1])['attempted_at'])
    if not paths:pytest.skip('private saved capture unavailable')
    db=tmp_path/'saved.sqlite3';steps=0
    with Store(db) as store:
        store.add_channel(channel);cid=store.add_character(channel,'Saved review');store.select_character(channel,cid)
        store.start_session(channel,at=datetime.fromisoformat(json.loads(paths[0].read_text().splitlines()[1])['attempted_at']))
        d=Diagnostics(store)
        with server_module.create_server(db,port=0,diagnostic_dashboard=True) as server:
            for path in paths:
                records=[json.loads(s) for s in path.read_text().splitlines()];rid=records[0]['run_id'];d.begin(rid,channel,records[0])
                for r in records[1:]:
                    d.append(rid,r);steps+=1
                    if r['type']=='attempt':clock.at=datetime.fromisoformat(r.get('received_at') or r['attempted_at'])
                    if steps%60==0:server.publisher.settle()  # Publications keep resuming checkpoints.
                    if steps%240==0:assert published(server,channel)==reference(store,server,channel,clock.at)
            last=clock.at
            for delta in (0,11,3901,90001):
                clock.at=last+timedelta(seconds=delta);server.publisher.settle()
                assert published(server,channel)==reference(store,server,channel,clock.at)
                nested(server.publisher.entry(channel)['tracked'])


def test_concurrent_viewers_share_one_projection_per_publication(tracking,clock,monkeypatch):
    path,store,d=tracking;d.begin('one','alpha',config('one',interval=20))
    for i in range(1,5):save(d,'one',i,i*20,3300+i*5)
    clock.at=NOW+timedelta(seconds=80)
    calls=[];original=diagnostics_module.player
    def slow(*args,**kwargs):
        calls.append(1);time.sleep(.3);return original(*args,**kwargs)
    monkeypatch.setattr(diagnostics_module,'player',slow)
    with server_module.create_server(path,port=0,diagnostic_dashboard=True,background=True) as server:
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        results=[]
        def get(url):
            try:
                with urlopen(f'http://127.0.0.1:{server.server_port}{url}',timeout=10) as response:results.append(response.status)
            except HTTPError as error:results.append(error.code)
        viewers=[threading.Thread(target=get,args=('/api/players' if i%2 else '/api/players/alpha',)) for i in range(20)]
        for viewer in viewers:viewer.start()
        for viewer in viewers:viewer.join()
        wait_for(lambda:server.publisher.entry('alpha') is not None)
        for viewer in [threading.Thread(target=get,args=('/api/players/alpha',)) for _ in range(20)]:viewer.start();viewer.join()
        server.shutdown();thread.join(5)
        assert len(calls)==1  # Forty requests, one card projection.
        assert set(results)<={200,503} and results[-20:]==[200]*20
        assert server.publisher.stats['presentations']<=4


def test_cold_channels_are_warming_until_published_and_wanted_first(tracking,clock,monkeypatch):
    path,store,d=tracking;d.begin('one','alpha',config('one',interval=20));save(d,'one',1,20,3300)
    store.add_channel('mu');store.add_channel('zulu');clock.at=NOW+timedelta(seconds=20)
    release=threading.Event();order=[];original=Diagnostics.card
    def gated(self,cache,head,**kwargs):
        release.wait(10);order.append(head['login']);return original(self,cache,head,**kwargs)
    monkeypatch.setattr(Diagnostics,'card',gated)
    with server_module.create_server(path,port=0,diagnostic_dashboard=True,background=True) as server:
        from tests.test_server import request
        status,headers,body=request((server,None),'/api/players/zulu')
        assert status==503 and json.loads(body)['error']=='warming_up' and headers['Retry-After']=='2'
        assert request((server,None),'/api/players/missing')[0]==404
        home=json.loads(request((server,None),'/api/players')[2])
        assert home['players']==[] and home['warming']==['alpha','mu','zulu']
        release.set();wait_for(lambda:all(server.publisher.entry(c) for c in ('alpha','mu','zulu')))
        assert order.index('zulu')<order.index('mu')  # The waiting viewer's channel goes first.
        assert request((server,None),'/api/players/zulu')[0]==200
        assert server.publisher.stats['ready_at'] is not None


def test_failed_refresh_keeps_last_entry_with_real_ages_and_retries_with_backoff(tracking,clock,monkeypatch):
    path,store,d=tracking;d.begin('one','alpha',config('one',interval=20))
    for i in range(1,4):save(d,'one',i,i*20,3300+i*5)
    clock.at=NOW+timedelta(seconds=60)
    with server_module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        server.publisher.settle();good=server.publisher.entry('alpha')
        save(d,'one',4,80,3320);clock.at=NOW+timedelta(seconds=80)
        original=Diagnostics.rolling_history
        monkeypatch.setattr(Diagnostics,'rolling_history',lambda *a,**k:(_ for _ in ()).throw(OSError('disk')))
        server.publisher.settle()
        assert server.publisher.entry('alpha') is good and server.publisher.failures['alpha'][0]==1
        body=json.loads(server.publisher.character('alpha'))
        assert body['player']['latest_attempt_at']==(NOW+timedelta(seconds=60)).isoformat() and body['served_at']==utc(clock.at)
        clock.at+=timedelta(seconds=2);server.publisher.settle()
        assert server.publisher.failures['alpha'][0]==1  # Still backing off; no retry storm.
        monkeypatch.setattr(Diagnostics,'rolling_history',original)
        clock.at+=timedelta(seconds=4);server.publisher.settle()
        assert 'alpha' not in server.publisher.failures and server.publisher.entry('alpha')['key']!=good['key']


def test_presented_bodies_are_reused_until_publication_or_clock_changes(tracking,clock):
    path,store,d=tracking;d.begin('one','alpha',config('one',interval=20))
    for i in range(1,4):save(d,'one',i,i*20,3300+i*5)
    clock.at=NOW+timedelta(seconds=60)
    with server_module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        server.publisher.settle();first=server.publisher.homepage()
        assert server.publisher.homepage() is first
        clock.at+=timedelta(milliseconds=999);assert server.publisher.homepage() is first
        clock.at+=timedelta(milliseconds=2);second=server.publisher.homepage()
        assert second is not first and json.loads(second)['served_at']!=json.loads(first)['served_at']
        server.coordinator_status['alpha']=dict(state='capture_failing',updated_at=clock.at.isoformat(),next_due_at=clock.at.isoformat())
        third=server.publisher.homepage()  # Same publication and clock; new coordinator activity.
        assert third is not second and json.loads(third)['players'][0]['activity']['state']=='capture_failing'
        save(d,'one',4,80,3320);server.publisher.settle()
        assert server.publisher.homepage() is not third
        entry=server.publisher.entry('alpha');before=json.dumps(entry,default=str)
        json.loads(server.publisher.character('alpha'));json.loads(server.publisher.homepage())
        assert json.dumps(server.publisher.entry('alpha'),default=str)==before  # Presentation never mutates it.


def test_character_change_rebuilds_and_shutdown_stops_the_refresher(tracking,clock):
    path,store,d=tracking;d.begin('one','alpha',config('one',interval=20))
    for i in range(1,4):save(d,'one',i,i*20,3300+i*5)
    clock.at=NOW+timedelta(seconds=60)
    server=server_module.create_server(path,port=0,diagnostic_dashboard=True,background=True)
    try:
        wait_for(lambda:server.publisher.entry('alpha') is not None)
        assert server.publisher.entry('alpha')['tracked']['tracked_exp'] is not None
        other=store.add_character('alpha','Other');store.end_session('alpha',at=clock.at);store.select_character('alpha',other);store.start_session('alpha',at=clock.at)
        server.publisher.wake.set()
        wait_for(lambda:server.publisher.entry('alpha')['tracked']['character_id']==other)
        assert server.publisher.entry('alpha')['tracked']['tracked_exp'] is None
    finally:server.server_close()
    assert not server.publisher.thread.is_alive()


@pytest.mark.parametrize('change_character',[False,True])
def test_character_change_with_failed_build_withholds_previous_identity(tracking,clock,monkeypatch,change_character):
    path,store,d=tracking
    with server_module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        p=server.publisher;p.settle()
        old=p.character('alpha');p.homepage();p.history('alpha')
        store.end_session('alpha',at=clock.at)
        if change_character:
            other=store.add_character('alpha','Other');store.select_character('alpha',other)
        store.start_session('alpha',at=clock.at)
        monkeypatch.setattr(Diagnostics,'card',lambda *a,**k:(_ for _ in ()).throw(OSError('disk')))
        p.step()
        assert p.character('alpha') is None, 'Previous character must not remain published after selection changes'
        assert p.history('alpha') is None
        home=json.loads(p.homepage())
        assert home['players']==[] and home['warming']==['alpha']
        assert old is not None


def test_changed_channel_cannot_starve_expired_channel(tracking,clock):
    path,store,d=tracking;store.add_channel('quiet')
    with server_module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        p=server.publisher;p.settle();before=p.entry('quiet')['built_at']
        clock.at+=timedelta(seconds=31)
        for i in range(1,4):
            save(d,'run',i,i*20,3300+i)
            p.step()
        assert p.entry('quiet')['built_at']!=before


def test_unknown_requests_do_not_allocate_unbounded_presentation_state(tracking,clock):
    path,store,d=tracking
    with server_module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        p=server.publisher;p.settle()
        for i in range(100):
            assert p.character(f'unknown{i}') is None
            assert p.history(f'unknown{i}') is None
        assert len(p.present_locks)<=1


def test_presentation_cache_is_not_resurrected_after_removal(tracking,clock):
    path,store,d=tracking
    with server_module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        p=server.publisher;p.settle()
        def removed_during_presentation(now):
            p.publish_heads([],{});return b'old response'
        p.present(('character','alpha'),removed_during_presentation)
        assert ('character','alpha') not in p.presented


def test_channel_beyond_publication_limit_is_not_promised_a_never_built_entry(tracking,clock):
    from tests.test_server import request
    path,store,d=tracking
    for i in range(25):store.add_channel(f'channel{i:02}')
    with server_module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        for endpoint in ('/api/players/channel24','/api/players/channel24/history'):
            status,headers,body=request((server,None),endpoint)
            assert status==503 and json.loads(body)==dict(error='publication_limit',limit=25)
            assert 'Retry-After' not in headers
        assert 'channel24' not in server.publisher.wanted


def test_identity_invalidation_precedes_network_and_build_clock_follows_it(tracking,clock,monkeypatch):
    path,store,d=tracking
    with server_module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        p=server.publisher;p.settle()
        other=store.add_character('alpha','Other')
        store.end_session('alpha',at=clock.at);store.select_character('alpha',other)
        store.start_session('alpha',at=clock.at)
        def network(channels,*,now):
            assert p.entry('alpha') is None, 'Identity changes must not wait behind a network lookup'
            clock.at+=timedelta(seconds=10)
            return {}
        monkeypatch.setattr(server.twitch_availability,'snapshot',network)
        p.step()
        assert p.entry('alpha')['built_at']==clock.at.isoformat()


def test_http_never_serves_previous_character_while_replacement_build_is_blocked(tracking,clock,monkeypatch):
    from tests.test_server import request
    path,store,d=tracking;started=threading.Event();release=threading.Event()
    with server_module.create_server(path,port=0,diagnostic_dashboard=True,background=True) as server:
        wait_for(lambda:server.publisher.entry('alpha') is not None)
        for url in ('/api/players','/api/players/alpha','/api/players/alpha/history'):
            assert request((server,None),url)[0]==200  # Warm the serialized old generation too.
        def blocked(*args,**kwargs):
            started.set();release.wait(5);raise OSError('injected build failure')
        monkeypatch.setattr(Diagnostics,'card',blocked)
        other=store.add_character('alpha','Other')
        store.end_session('alpha',at=clock.at);store.select_character('alpha',other)
        store.start_session('alpha',at=clock.at);server.publisher.wake.set()
        try:
            assert started.wait(5)
            for url in ('/api/players/alpha','/api/players/alpha/history'):
                status,headers,body=request((server,None),url)
                assert status==503 and json.loads(body)['error']=='warming_up'
            home=json.loads(request((server,None),'/api/players')[2])
            assert home['players']==[] and home['warming']==['alpha']
        finally:release.set()


def test_disabled_public_pages_do_not_start_background_history_work(tracking,clock):
    path,store,d=tracking
    with server_module.create_server(path,port=0,background=True) as server:
        assert server.publisher.thread is None
        assert server.publisher.stats['steps']==0


def test_capture_committing_between_card_and_totals_cannot_mix_revisions(tracking,clock,monkeypatch):
    path,store,d=tracking
    for i in range(1,4):save(d,'run',i,i*20,3300+i*5)
    clock.at=NOW+timedelta(seconds=90)
    ready=threading.Event();release=threading.Event();original=Diagnostics.card
    def card(*args,**kwargs):
        value=original(*args,**kwargs);ready.set();release.wait(5);return value
    monkeypatch.setattr(Diagnostics,'card',card)
    with server_module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        worker=threading.Thread(target=server.publisher.step)
        worker.start()
        try:
            assert ready.wait(5)
            save(d,'run',4,80,3320)  # Commit is visible to new readers, but not the build's transaction.
        finally:
            release.set();worker.join(5)
        assert not worker.is_alive()
        entry=server.publisher.entry('alpha')
        assert entry['tracked']['context_attempts']==3
        assert entry['card']['last_attempt_at']==(NOW+timedelta(seconds=60)).isoformat()
        server.publisher.step()
        entry=server.publisher.entry('alpha')
        assert entry['tracked']['context_attempts']==4
        assert entry['card']['last_attempt_at']==(NOW+timedelta(seconds=80)).isoformat()
