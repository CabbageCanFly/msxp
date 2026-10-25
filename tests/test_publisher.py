"""Background-published public state must equal the synchronous full-replay reference."""
from datetime import datetime,timedelta
from copy import deepcopy
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
from exp_tracker.publisher import PRIVATE_FIELDS,broadcast,encode,public,public_character,public_roster,revision
from exp_tracker.store import Store,utc
from exp_tracker.twitch_probe import StreamAvailability
from tests.test_product import tracking,NOW
from tests.test_diagnostic_history import config
from tests.test_tracked_exp_totals import save,nested
from tests.test_incremental_history import scenario
from tests.test_cross_level_product import SAVED,REPLAY_LOGS,replay


@pytest.fixture
def clock(monkeypatch):
    class Clock(datetime):
        at=NOW
        @classmethod
        def now(cls,tz=None):return cls.at
    monkeypatch.setattr(server_module,'datetime',Clock)
    # Status-cache expiry must advance with the replay, not with full-replay CPU time.
    monkeypatch.setattr(server_module,'StreamAvailability',lambda **kwargs:
        StreamAvailability(**kwargs,clock=lambda:Clock.at.timestamp()))
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
        roster=public_roster(d.roster(channel),(card['player'].get('display_level') or {}).get('value'))
        for row in roster:
            summary=server.publisher.summary(head,row['id'],now)
            row['last_exp_at']=(summary.get('reading') or {}).get('timestamp')
    card['player']['character']=public_character(card['player']['character'])
    value=tracked_statistics(refresh(card['player'],now=now,activity=operation(extras['lifecycle'],None,now)),tracked,now=now,pace_as_of=card_at)
    # The removed broadcasts(): Twitch status for channels whose latest run is a Twitch source.
    row=store.db.execute('''SELECT r.configuration_json AS config,(SELECT payload_json FROM diagnostic_attempts
        WHERE run_id=r.run_id ORDER BY attempt_index DESC LIMIT 1) AS payload FROM streamers s JOIN diagnostic_runs r
        ON r.rowid=(SELECT rowid FROM diagnostic_runs WHERE streamer_id=s.id ORDER BY rowid DESC LIMIT 1) WHERE s.login=?''',(channel,)).fetchone()
    twitch=[channel] if row and (json.loads(row['config'] or '{}').get('source_kind') or json.loads(row['payload'] or '{}').get('source',{}).get('kind'))=='twitch' else []
    statuses=server.twitch_availability.snapshot(twitch,now=now)
    body=dict(player=broadcast([value],statuses,now)[0],tracked_history=tracked,history=extras['history'],truncated=extras['truncated'],
        roster=roster,view=dict(character_id=head['selected_character_id'],current=True))
    return public(json.loads(encode(body)))  # Public responses never carry PRIVATE_FIELDS.


def published(server,channel):
    body=json.loads(server.publisher.character(channel))
    for key in ('served_at','experimental','poll_seconds'):body.pop(key)
    assert (body.pop('history_revision'),body.pop('tracked_revision'))==(revision(body['history']),revision(body['tracked_history']))
    return body


def first_difference(actual,expected,path='$'):
    """Keep saved-replay failures readable without excluding any JSON fields."""
    if actual==expected:return None
    if isinstance(actual,dict) and isinstance(expected,dict):
        for key in sorted(actual.keys()|expected.keys()):
            child=f'{path}.{key}'
            if key not in actual or key not in expected:
                return child,'present' if key in actual else 'missing','present' if key in expected else 'missing'
            difference=first_difference(actual[key],expected[key],child)
            if difference is not None:return difference
    if isinstance(actual,list) and isinstance(expected,list):
        if len(actual)!=len(expected):return f'{path}.length',len(actual),len(expected)
        for index,(left,right) in enumerate(zip(actual,expected)):
            difference=first_difference(left,right,f'{path}[{index}]')
            if difference is not None:return difference
    return path,actual,expected


def assert_publication(store,server,channel,now,tmp_path,**context):
    difference=first_difference(published(server,channel),reference(store,server,channel,now))
    if difference is None:return
    entry=server.publisher.entry(channel)
    report=dict(context,now=now.isoformat(),
        difference=dict(zip(('path','published','reference'),difference)),
        publication_key=entry['key'],database_head=tuple(Diagnostics(store).heads(channel)[0]),
        built_at=entry['built_at'],card_at=entry['card']['recent_as_of'],publisher_stats=server.publisher.stats)
    diagnostic=tmp_path/'publication-mismatch.json'
    diagnostic.write_text(json.dumps(report,indent=2),encoding='utf-8')
    pytest.fail(f'Publication mismatch {difference!r}; replay={context!r}; diagnostic={diagnostic}')


@pytest.mark.parametrize('actual,expected,difference',[
    ({'player':{'windows':[{'gain':17}]}},{'player':{'windows':[{'gain':18}]}},('$.player.windows[0].gain',17,18)),
    ({'gain':None},{'gain':None},None),
    ({},{'gain':None},('$.gain','missing','present')),
    ({'history':[1]},{'history':[]},('$.history.length',1,0)),
    ({'gain':'17'},{'gain':17},('$.gain','17',17)),
])
def test_first_publication_difference(actual,expected,difference):
    assert first_difference(actual,expected)==difference


def test_publication_mismatch_writes_first_field_and_replay_context(tracking,clock,tmp_path,monkeypatch):
    path,store,d=tracking;d.begin('one','alpha',config('one',interval=20));save(d,'one',1,20,3300)
    clock.at=NOW+timedelta(seconds=20)
    original=published
    def wrong(server,channel):
        body=original(server,channel);body['player']['channel']='wrong';return body
    with server_module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        server.publisher.settle();monkeypatch.setitem(globals(),'published',wrong)
        with pytest.raises(pytest.fail.Exception,match=r'\$\.player.channel'):
            assert_publication(store,server,'alpha',clock.at,tmp_path,step=1,event_id='one:1')
    report=json.loads((tmp_path/'publication-mismatch.json').read_text())
    assert report['difference']==dict(path='$.player.channel',published='wrong',reference='alpha')
    assert report['step']==1 and report['event_id']=='one:1'
    assert report['publication_key']==report['database_head'] and report['publisher_stats']['failures']==0


def test_reference_status_cache_uses_replay_clock_not_test_duration(tracking,clock,tmp_path,monkeypatch):
    path,store,d=tracking;d.begin('one','alpha',config('one',interval=20));save(d,'one',1,20,3300)
    wall=[0];initialize=StreamAvailability.__init__
    def availability(self,**kwargs):
        kwargs.setdefault('clock',lambda:wall[0]);initialize(self,**kwargs)
    monkeypatch.setattr(StreamAvailability,'__init__',availability)
    clock.at=NOW+timedelta(seconds=20)
    with server_module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        server.publisher.settle()
        checked=server.publisher.statuses['alpha']['checked_at']
        clock.at+=timedelta(seconds=20);wall[0]=61  # Slow full replay crosses the real cache TTL.
        assert_publication(store,server,'alpha',clock.at,tmp_path,step=1)
        assert server.twitch_availability.results['alpha']['checked_at']==checked
        clock.at+=timedelta(seconds=41);server.publisher.settle()  # Actual replay time expires it.
        assert server.publisher.statuses['alpha']['checked_at']==clock.at.isoformat()
        assert_publication(store,server,'alpha',clock.at,tmp_path,step=2)


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
        home=json.loads(server.publisher.homepage());tracked=server.publisher.entry('alpha')['public']['tracked']
        assert tracked['as_of']==clock.at.isoformat() and 'warming' not in home
        assert home['players'][0]['tracked_windows']['1440']['gain']==tracked['windows']['1440']['gain']
        buckets=tracked['buckets']
        assert len(buckets)==48 and home['players'][0]['day_buckets']==[None if b['chart_value'] is None else round(b['chart_value']['approximate']) for b in buckets]
    assert compared>20


@pytest.mark.parametrize('gap', [3600, 3601, 7200])
def test_homepage_mini_chart_omits_long_gap_gain_but_keeps_recent_gain_and_daily_total(tracking,clock,gap):
    path,_,d=tracking
    d.begin('one','alpha',config('one',interval=20))
    save(d,'one',1,20,3300)
    save(d,'one',2,20+gap,3400)
    save(d,'one',3,35+gap,3401)
    clock.at=NOW+timedelta(seconds=35+gap)
    with server_module.create_server(path,port=0,public_only=True) as server:
        server.publisher.settle()
        player=json.loads(server.publisher.homepage())['players'][0]
        tracked=server.publisher.entry('alpha')['public']['tracked']
        assert player['day_buckets']==[None if b['chart_value'] is None else round(b['chart_value']['approximate']) for b in tracked['buckets']]
        chart=sum(v for v in player['day_buckets'] if v is not None)
        total=sum(round(b['value']['approximate']) for b in tracked['buckets'] if b['value'] is not None)
        assert chart>0 and (chart==total if gap==3600 else chart<total)
        assert player['tracked_windows']['1440']['gain']==tracked['tracked_exp']


@pytest.mark.parametrize('delta',[0,61,901])
@pytest.mark.parametrize('status',['live','offline','unknown'])
def test_homepage_matches_card_presentation_without_mutating_publications(tracking,clock,delta,status):
    from exp_tracker.diagnostics import present_card
    from exp_tracker.publisher import board
    path,_,d=tracking;d.begin('one','alpha',config('one',interval=20))
    for i in range(1,5):save(d,'one',i,i*20,3300+i*5)
    clock.at=NOW+timedelta(seconds=80)
    with server_module.create_server(path,port=0,public_only=True) as server:
        p=server.publisher;p.settle();clock.at+=timedelta(seconds=delta)
        server.coordinator_status['alpha']=dict(state='waiting',next_due_at=clock.at.isoformat(),requested_interval_seconds=20)
        p.statuses={'alpha':dict(status=status)}
        before=deepcopy(p.entries);entry=p.entry('alpha')
        card=present_card(dict(entry['card'],player=entry['public']['player']),now=clock.at,
            active_runs=server.active_run_ids,coordinator_status=server.coordinator_status)
        value=tracked_statistics(card['player'],entry['public']['tracked'],now=clock.at,
            pace_as_of=datetime.fromisoformat(entry['card']['recent_as_of']))
        value['activity']=public(value['activity'])
        value['day_buckets']=[None if b['chart_value'] is None else round(b['chart_value']['approximate']) for b in entry['public']['tracked']['buckets']]
        expected=board(broadcast([value],p.statuses,clock.at)[0])
        actual=json.loads(p.homepage())['players'][0]
        assert actual==json.loads(encode(expected))
        assert p.entries==before


@pytest.mark.parametrize('channel',['streamer_f','streamer_e','streamer_a'])
def test_saved_publications_match_reference(tmp_path,clock,channel):
    # Read each file once: active rotation tails must not change this invocation's inputs.
    captures=sorted(((p,p.read_text()) for p in Path(SAVED).glob(f'*/{channel}/**/capture.jsonl')),
        key=lambda item:json.loads(item[1].splitlines()[1])['attempted_at'])[:REPLAY_LOGS]
    if not captures:pytest.skip('private saved capture unavailable')
    db=tmp_path/'saved.sqlite3';steps=0
    with Store(db) as store:
        store.add_channel(channel);cid=store.add_character(channel,'Saved review');store.select_character(channel,cid)
        store.start_session(channel,at=datetime.fromisoformat(json.loads(captures[0][1].splitlines()[1])['attempted_at']))
        d=Diagnostics(store)
        with server_module.create_server(db,port=0,diagnostic_dashboard=True) as server:
            for path,text in captures:
                records=[json.loads(s) for s in text.splitlines()];rid=records[0]['run_id'];d.begin(rid,channel,records[0])
                for r in records[1:]:
                    d.append(rid,r);steps+=1
                    if r['type']=='attempt':clock.at=datetime.fromisoformat(r.get('received_at') or r['attempted_at'])
                    if steps%60==0:server.publisher.settle()  # Publications keep resuming checkpoints.
                    if steps%240==0:
                        assert_publication(store,server,channel,clock.at,tmp_path,
                            step=steps,path=str(path),event_id=f'{rid}:{r.get("index")}')
            last=clock.at
            for delta in (0,11,3901,90001):
                clock.at=last+timedelta(seconds=delta);server.publisher.settle()
                assert_publication(store,server,channel,clock.at,tmp_path,step=steps,expiry_delta=delta)
                nested(server.publisher.entry(channel)['tracked'])


def test_saved_publication_preserves_pruned_level_decrease(tracking,clock,tmp_path):
    path,store,_=tracking
    clock.at=datetime.fromisoformat('2026-10-19T03:52:21.976670+00:00')
    replay(store,'streamer_a',['20261018T021930Z-a5713c06','20261019T025444Z-0fbaad78'],as_of=clock.at)
    with server_module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        for delta in (0,31,31):
            clock.at+=timedelta(seconds=delta);server.publisher.settle()
            assert_publication(store,server,'streamer_a',clock.at,tmp_path)
            assert server.publisher.entry('streamer_a')['tracked']['exclusion_counts']['observed_level_decrease']==1


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


def test_retention_fold_keeps_publication_on_show_until_its_rebuild(tracking,clock,monkeypatch):
    path,store,d=tracking;d.begin('one','alpha',config('one',interval=20))
    for i in range(1,4):save(d,'one',i,i*20,3300+i*5)
    clock.at=NOW+timedelta(seconds=60)
    with server_module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        p=server.publisher;p.settle();shown=p.entry('alpha')
        with store._transaction():store.db.execute('UPDATE retention_meta SET revision=revision+1 WHERE id=1')
        original=Diagnostics.card
        monkeypatch.setattr(Diagnostics,'card',lambda *a,**k:(_ for _ in ()).throw(OSError('disk')))
        p.step()
        # Unlike an operator revision, a fold changes no shown value: the page is never withdrawn.
        assert p.entry('alpha') is shown and p.character('alpha') is not None and p.failures['alpha'][0]==1
        monkeypatch.setattr(Diagnostics,'card',original)
        clock.at+=timedelta(seconds=6);p.settle()  # Past the first retry backoff.
        assert p.entry('alpha') is not shown and p.entry('alpha')['key'][10]==shown['key'][10]+1


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
        third=server.publisher.homepage()  # Same publication and clock; new coordinator activity (it drives pace presentation).
        assert third is not second
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
        wait_for(lambda:(entry:=server.publisher.entry('alpha')) is not None and entry['tracked']['character_id']==other)
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


def test_new_capture_is_published_before_time_only_expiry(tracking,clock,monkeypatch):
    path,store,d=tracking;store.add_channel('aaa')  # Sorts first, so only the rank can put alpha ahead.
    with server_module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        p=server.publisher;p.settle();before=p.entry('aaa')['built_at']
        monkeypatch.setattr('exp_tracker.publisher.due',lambda *a:True)  # Every rolling window has aged.
        clock.at+=timedelta(seconds=11)
        save(d,'run',1,20,3301)
        p.step()
        assert p.entry('alpha')['built_at']==clock.at.isoformat() and p.entry('aaa')['built_at']==before


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


@pytest.mark.parametrize('count',[40,80])
def test_channels_beyond_25_are_published_and_can_be_requested(tracking,clock,count):
    from tests.test_server import request
    path,store,d=tracking
    for i in range(count):store.add_channel(f'channel{i:02}')
    with server_module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        server.publisher.settle()  # Each inline pass still bounds its work to 64 builds.
        for endpoint in (f'/api/players/channel{count-1:02}',f'/api/players/channel{count-1:02}/history'):
            status,headers,body=request((server,None),endpoint)
            assert status==200
            assert 'Retry-After' not in headers
        home=json.loads(server.publisher.homepage())
        assert len(home['players'])==count+1 and not home['truncated']


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


def test_public_only_publishes_in_background_and_refuses_developer_routes(tracking,clock):
    path,store,d=tracking;d.begin('one','alpha',config('one',interval=20));save(d,'one',1,20,3300);clock.at=NOW+timedelta(seconds=20)
    from tests.test_server import request
    with server_module.create_server(path,port=0,background=True,public_only=True) as server:
        get=lambda p,method='GET':request((server,None),p,method)
        wait_for(lambda:server.publisher.entry('alpha'))
        for p in ('/','/streams','/stream/alpha','/live/overlay/alpha','/api/players','/api/players/alpha','/api/players/alpha/history',
                  '/static/product.js','/static/product.css','/static/leaderboard.css','/static/leaderboard.svg','/static/overlay.css',
                  '/static/fonts/fredoka-latin.woff2','/static/fonts/nunito-latin.woff2','/static/steely.png','/static/live-overlay.css','/static/mobs/blue-snail-move.gif'):
            assert get(p)[0]==200,p
        assert [p['channel'] for p in json.loads(get('/api/players')[2])['players']]==['alpha']
        assert all(b'data-site="public"' in get(p)[2] for p in ('/','/stream/alpha','/live/overlay/alpha'))
        assert get('/api/players/missing')[0]==404 and get('/stream/bad!')[0]==400 and get('/api/players','POST')[0]==405
        for p in ('/dev/streams','/dev/api/streams','/dev/api/streams/alpha/diagnostics','/dev/api/streams/alpha/diagnostics?session=1',
                  '/dev/api/streams/alpha/sessions','/dev/api/streams/alpha/runs','/dashboard/alpha','/dashboard/missing','/dev/shadow',
                  '/dev/api/shadow','/static/shadow.js','/static/shadow.css','/static/streams.js','/api/streams/alpha/state',
                  '/overlay/alpha','/demo/leaderboard','/static/leaderboard.js','/static/overlay.js','/static/tracker.html'):
            status,_,body=get(p);assert (status,json.loads(body))==(404,{'error':'not_found'}),p
    with server_module.create_server(path,port=0,diagnostic_dashboard=True) as server:  # Developer mode is unchanged.
        assert b'data-site' not in request((server,None),'/')[2] and request((server,None),'/dev/api/streams')[0]==200
    for kwargs in (dict(diagnostic_dashboard=True),dict(shadow_log=path)):
        with pytest.raises(ValueError,match='public-only'):server_module.create_server(path,port=0,public_only=True,**kwargs)


def test_character_polls_omit_only_sections_the_viewer_already_holds(tracking,clock,monkeypatch):
    path,store,d=tracking;d.begin('one','alpha',config('one',interval=20))
    for i in range(1,4):save(d,'one',i,i*20,3300+i*5)
    clock.at=NOW+timedelta(seconds=60)
    from tests.test_server import request
    with server_module.create_server(path,port=0,public_only=True) as server:
        p=server.publisher;p.settle()
        def body(known=(None,None)):
            with p.lock:p.presented.clear()  # Each call presents afresh at the pinned clock.
            return json.loads(p.character('alpha',known))
        first=body();held=(first['history_revision'],first['tracked_revision'])  # First load: everything.
        assert held==(revision(first['history']),revision(first['tracked_history'])) and first['history']
        same=body(held)
        assert 'history' not in same and 'tracked_history' not in same and same['player']==first['player']
        assert (same['history_revision'],same['tracked_revision'])==held
        assert body((held[0],'0'*16))['tracked_history']==first['tracked_history'] and 'history' not in body((held[0],'0'*16))
        # Over HTTP, only valid revisions count; anything else is a full body.
        status,_,raw=request((server,None),f'/api/players/alpha?history={held[0]}&tracked={held[1]}')
        assert status==200 and 'history' not in json.loads(raw)
        for query in ('?history=x&tracked=y',f'?history={held[0]}&history={held[0]}&tracked={held[1]}',f'?history={held[0].upper()}&tracked={held[1]}'):
            assert 'history' in json.loads(request((server,None),'/api/players/alpha'+query)[2]),query
        # A new capture changes the chart history; the old revision gets the new rows.
        save(d,'one',4,80,3330);clock.at=NOW+timedelta(seconds=80);p.settle()
        after=body(held)
        assert after['history_revision']!=held[0] and after['history'][-1]['timestamp']==(NOW+timedelta(seconds=80)).isoformat()
        assert after['tracked_revision']!=held[1] and after['tracked_history']==p.entry('alpha')['public']['tracked']
        held=(after['history_revision'],after['tracked_revision'])
        # Time-only refresh: each section is resent exactly when its content changed.
        clock.at+=timedelta(seconds=31);p.settle();entry=p.entry('alpha');aged=body(held)
        assert ('history' in aged)==(revision(entry['public']['history'])!=held[0])
        assert ('tracked_history' in aged)==(revision(entry['public']['tracked'])!=held[1]) and aged['tracked_revision']==revision(entry['public']['tracked'])
        held=(aged['history_revision'],aged['tracked_revision'])
        # A publication between the decision and the presentation is sent in full, never mislabeled.
        present=p.present
        def publish_first(key,build,runtime=''):
            save(d,'one',5,round((clock.at-NOW).total_seconds())+1,3340);clock.at+=timedelta(seconds=2);p.settle()
            return present(key,build,runtime)
        monkeypatch.setattr(p,'present',publish_first)
        raced=json.loads(p.character('alpha',held));monkeypatch.setattr(p,'present',present)
        assert raced['history_revision']!=held[0] and raced['history']==p.entry('alpha')['public']['history']
        held=(raced['history_revision'],raced['tracked_revision'])
        # Character change: new identity, new revisions, full sections.
        other=store.add_character('alpha','Other');store.end_session('alpha',at=clock.at);store.select_character('alpha',other);store.start_session('alpha',at=clock.at)
        p.settle();changed=body(held)
        assert changed['tracked_history']['character_id']==other and 'history' in changed
        # Presentation state stays bounded per channel whatever revisions viewers send.
        for i in range(20):p.character('alpha',(f'{i:016x}',f'{i:016x}'))
        assert len([k for k in p.present_locks if k[:2]==('character','alpha')])<=4


def test_public_responses_omit_private_fields_while_internal_state_keeps_them(tracking,clock):
    path,store,d=tracking;d.begin('one','alpha',config('one',interval=20))
    for i in range(1,8):save(d,'one',i,i*20,3300+i*5)
    save(d,'one',8,160,3340,missing=True)
    clock.at=NOW+timedelta(seconds=165)
    from tests.test_server import request
    from exp_tracker.publisher import CHARACTER_ONLY,board
    def keys(value,found):
        if isinstance(value,dict):
            for k,v in value.items():found.add(k);keys(v,found)
        elif isinstance(value,list):
            for v in value:keys(v,found)
        return found
    with server_module.create_server(path,port=0,diagnostic_dashboard=True) as server:
        server.coordinator_status['alpha']=dict(state='waiting',run_id='one',updated_at=clock.at.isoformat(),next_due_at=clock.at.isoformat(),
            requested_interval_seconds=20,actual_interval_seconds=20.1,skipped_deadlines=0)
        get=lambda p:json.loads(request((server,None),p)[2])
        home,character,packet=get('/api/players'),get('/api/players/alpha'),get('/api/players/alpha/history')
        assert not keys([home,character,packet],set())&PRIVATE_FIELDS
        player=home['players'][0]
        assert character['player']['activity']=={'state':'waiting'} and 'activity' not in player
        # The homepage keeps only what the Streamers list reads and adds its mini chart; every value it keeps equals the character page's.
        assert not set(CHARACTER_ONLY)&set(player) and all(character['player'][f] for f in CHARACTER_ONLY)
        assert 'day_buckets' not in character['player'] and len(player.pop('day_buckets'))==48
        assert player==board(character['player'])
        assert packet=={**character['tracked_history'],'served_at':packet['served_at']}
        # Calculations, publisher state and developer diagnostics keep the full data.
        entry=server.publisher.entry('alpha')
        assert {'source_identity','run_id','run_ids','session_id','excluded','holes','latest_endpoint','eligibility_checks'}<=keys(entry['card']['player'],set())
        assert {'source_identity','run_id','session_id'}<=keys(get('/dev/api/streams/alpha/diagnostics'),set())


def test_cross_origin_viewer_can_read_warming_and_published_bodies(tracking,clock,monkeypatch):
    path,store,d=tracking;d.begin('one','alpha',config('one',interval=20));save(d,'one',1,20,3300);clock.at=NOW+timedelta(seconds=20)
    release=threading.Event();original=Diagnostics.card
    monkeypatch.setattr(Diagnostics,'card',lambda self,*a,**k:(release.wait(10),original(self,*a,**k))[1])
    from tests.test_server import request
    pages='https://msxp.pages.dev'
    with server_module.create_server(path,port=0,background=True,public_only=True,cors_origins=[pages]) as server:
        status,headers,body=request((server,None),'/api/players/alpha',origin=pages)
        assert (status,json.loads(body)['error'],headers['Retry-After'])==(503,'warming_up','2')
        assert headers['Access-Control-Allow-Origin']==pages and headers['Access-Control-Expose-Headers']=='Retry-After'
        release.set();wait_for(lambda:server.publisher.entry('alpha'))
        for route in ('/api/players','/api/players/alpha','/api/players/alpha/history'):
            status,headers,_=request((server,None),route,origin=pages)
            assert status==200 and headers['Access-Control-Allow-Origin']==pages,route
