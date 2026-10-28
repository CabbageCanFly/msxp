from io import BytesIO
from datetime import datetime,timedelta,timezone
from urllib.error import HTTPError,URLError
import os

from PIL import Image
import pytest

from exp_tracker.twitch_probe import capture_paused, outside_maplestory, inspect_thumbnail, main, thumbnail_url
from exp_tracker.twitch_probe import MAX_STREAM_PAGES,StreamAvailability,helix


@pytest.fixture(autouse=True)
def isolated_manual_auth(monkeypatch,tmp_path):
    # Legacy status/pagination tests must never load the operator's real .env.
    monkeypatch.setattr('exp_tracker.twitch_auth.DEFAULT_ENV_FILE',tmp_path/'absent.env')
    monkeypatch.delenv('TWITCH_CLIENT_SECRET',raising=False)
    monkeypatch.setattr('exp_tracker.twitch_auth.oauth_json',lambda request:
        dict(client_id=os.environ.get('TWITCH_CLIENT_ID'),expires_in=7200))


def test_only_official_https_thumbnail_host():
    template = "https://static-cdn.jtvnw.net/previews/live-{width}x{height}.jpg"
    assert thumbnail_url(template, 1920, 1080).endswith("1920x1080.jpg")
    for url in ("http://static-cdn.jtvnw.net/a", "https://example.com/a", "https://127.0.0.1/a"):
        with pytest.raises(ValueError):
            thumbnail_url(url, 1920, 1080)


def test_thumbnail_metrics_without_retaining_image():
    payload = BytesIO()
    Image.new("RGB", (64, 32), "black").save(payload, format="PNG")
    result = inspect_thumbnail(payload.getvalue())
    assert result["image_size"] == [64, 32]
    assert len(result["sha256"]) == 64
    assert "recognition" not in result


def test_missing_credentials_do_not_make_network_requests(monkeypatch, capsys):
    monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TWITCH_ACCESS_TOKEN", raising=False)
    assert main(["somechannel"]) == 1
    assert "TWITCH_CLIENT_ID" in capsys.readouterr().err


@pytest.mark.parametrize('state,game,paused',[
    ('offline',None,True),('unknown',None,False),('live','Just Chatting',True),
    ('live','MapleStory',False),('live','MapleStory Worlds',False),('live','',False),('live',None,False),
])
def test_capture_pause_requires_fresh_offline_or_other_category(state,game,paused):
    now=datetime(2026,1,1,tzinfo=timezone.utc)
    status=dict(status=state,game_name=game,checked_at=now.isoformat(),valid_until=(now+timedelta(seconds=60)).isoformat())
    assert capture_paused(status,now=now) is paused
    assert capture_paused(status,now=now,any_category=True) is (state=='offline')
    assert not capture_paused(status,now=now+timedelta(seconds=60))
    assert not capture_paused(status,now=now-timedelta(seconds=1))


@pytest.mark.parametrize('changes',[
    {'checked_at':None},{'valid_until':None},{'valid_until':'invalid'},
    {'valid_until':'2026-01-01T00:01:00'},{'checked_at':'invalid'},
])
def test_invalid_status_dates_allow_capture(changes):
    now=datetime(2026,1,1,tzinfo=timezone.utc)
    status=dict(status='offline',checked_at=now.isoformat(),valid_until=(now+timedelta(seconds=60)).isoformat())
    assert not capture_paused(dict(status,**changes),now=now)
    assert not capture_paused(None,now=now)
    assert not capture_paused({'status':'offline'},now=now)


def test_batched_stream_status_cache_never_confuses_api_failure_with_offline(monkeypatch):
    monkeypatch.setenv('TWITCH_CLIENT_ID','private-client');monkeypatch.setenv('TWITCH_ACCESS_TOKEN','private-token')
    seconds=[0];calls=[];failure=[None]
    def fetch(endpoint,params,client,token,**kwargs):
        calls.append((endpoint,params,kwargs))
        if failure[0]:raise failure[0]
        return dict(data=[dict(user_login='alpha',type='live')],pagination={})
    status=StreamAvailability(enabled=True,fetch=fetch,clock=lambda:seconds[0]);now=datetime(2026,1,1,tzinfo=timezone.utc)
    result=status.snapshot(['beta','alpha'],now=now)
    assert result['alpha']['status']=='live' and result['beta']['status']=='offline'
    assert calls==[('streams',dict(user_login=['alpha','beta'],first=100),dict(timeout=3))]
    for second in (1,30,59):
        seconds[0]=second;assert status.snapshot(['alpha','beta'],now=now+timedelta(seconds=second))==result
    assert len(calls)==1
    for error,reason in ((HTTPError('secret-url',401,'secret-token',{},None),'credentials_rejected'),
                         (URLError('secret-url'),'api_unavailable'),
                         (HTTPError('secret-url',503,'secret-token',{},None),'api_error')):
        seconds[0]+=300;failure[0]=error
        result=status.snapshot(['alpha','beta'],now=now+timedelta(seconds=seconds[0]))
        assert result['alpha']['status']=='live' and result['beta']['status']=='offline'
        assert all(r['reason']==reason for r in result.values())
        assert result['alpha']['last_known_status']=='live'
        assert all('private' not in str(r) and 'secret' not in str(r) for r in result.values())
    seconds[0]+=60;failure[0]=None
    assert status.snapshot(['alpha','beta'],now=now+timedelta(seconds=seconds[0]))['alpha']['status']=='live'


@pytest.mark.parametrize('started,expected',[
    ('2025-12-31T21:47:00Z','2025-12-31T21:47:00+00:00'),
    ('2025-12-31T16:47:00-05:00','2025-12-31T21:47:00+00:00'),
    (None,None),('',None),('invalid',None),('2025-12-31T21:47:00',None),
    ('2026-01-01T00:00:01Z',None),(123,None),('x'*1000,None),
    ('0001-01-01T00:00:00+14:00',None),
])
def test_broadcast_start_is_validated_without_losing_live_status_or_extra_requests(monkeypatch,started,expected):
    monkeypatch.setenv('TWITCH_CLIENT_ID','private');monkeypatch.setenv('TWITCH_ACCESS_TOKEN','private')
    calls=[]
    def fetch(*args,**kwargs):
        calls.append(args)
        return dict(data=[dict(user_login='alpha',type='live',started_at=started)])
    now=datetime(2026,1,1,tzinfo=timezone.utc)
    cache=StreamAvailability(enabled=True,fetch=fetch,clock=lambda:0)
    statuses=cache.snapshot(['alpha','beta'],now=now)
    assert statuses['alpha']['status']=='live' and statuses['alpha']['started_at']==expected
    assert statuses['beta']['status']=='offline' and statuses['beta']['started_at'] is None
    assert cache.snapshot(['alpha','beta'],now=now+timedelta(seconds=30))==statuses
    assert len(calls)==1
    stale=cache.snapshot(['alpha','beta'],now=now+timedelta(seconds=121))['alpha']
    assert stale['status']=='live' and stale['started_at']==expected and stale['reason']=='stale_check'


def test_disabled_missing_credentials_expired_cache_and_malformed_status_are_unknown(monkeypatch):
    monkeypatch.delenv('TWITCH_CLIENT_ID',raising=False);monkeypatch.delenv('TWITCH_ACCESS_TOKEN',raising=False)
    forbidden=lambda *a,**kw:pytest.fail('No request without credentials and opt-in')
    assert StreamAvailability(fetch=forbidden).snapshot(['alpha'])['alpha']['reason']=='not_enabled'
    assert StreamAvailability(enabled=True,fetch=forbidden).snapshot(['alpha'])['alpha']['reason']=='missing_credentials'
    monkeypatch.setenv('TWITCH_CLIENT_ID','private');monkeypatch.setenv('TWITCH_ACCESS_TOKEN','private')
    now=datetime(2026,1,1,tzinfo=timezone.utc)
    for payload in ({},{'data':None},{'data':[{}]}, {'data':[],'pagination':{'cursor':'more'}}):
        value=StreamAvailability(enabled=True,fetch=lambda *a,**kw:payload).snapshot(['alpha'],now=now)['alpha']
        assert value['status']=='unknown'
    cache=StreamAvailability(enabled=True,fetch=lambda *a,**kw:{'data':[]},clock=lambda:0)
    assert cache.snapshot(['alpha'],now=now)['alpha']['status']=='offline'
    stale=cache.snapshot(['alpha'],now=now+timedelta(seconds=121))['alpha']
    assert stale['status']=='offline' and not capture_paused(stale,now=now+timedelta(seconds=121))


@pytest.mark.parametrize('failure',[None,'rate_limit','wrong_batch'])
def test_large_roster_uses_bounded_batches_and_preserves_known_statuses(monkeypatch,failure):
    monkeypatch.setenv('TWITCH_CLIENT_ID','private');monkeypatch.setenv('TWITCH_ACCESS_TOKEN','private')
    channels=[f'channel{i:03}' for i in range(201)];calls=[]
    def fetch(endpoint,params,*args,**kwargs):
        batch=params['user_login'];calls.append(batch)
        assert 1<=len(batch)<=100
        if failure and len(calls)==2:
            if failure=='rate_limit':raise HTTPError('private',429,'private',{'Retry-After':'120'},None)
            return dict(data=[dict(user_login=channels[0],type='live')])
        return dict(data=[dict(user_login=batch[0],type='live')])
    cache=StreamAvailability(enabled=True,fetch=fetch,clock=lambda:0)
    result=cache.snapshot(channels)
    completed=channels if failure is None else channels[:100]
    assert calls==[channels[i:i+100] for i in range(0,201 if failure is None else 200,100)]
    for i,c in enumerate(channels):
        expected='unknown' if c not in completed else 'live' if i%100==0 else 'offline'
        assert result[c]['status']==expected
        if expected=='unknown':assert result[c]['reason']==('rate_limited' if failure=='rate_limit' else 'api_unavailable')
    assert cache.snapshot(channels)==result


def test_completed_batch_expires_without_bypassing_later_batch_backoff(monkeypatch):
    monkeypatch.setenv('TWITCH_CLIENT_ID','private');monkeypatch.setenv('TWITCH_ACCESS_TOKEN','private')
    channels=[f'channel{i:03}' for i in range(101)];calls=[];seconds=[0]
    def fetch(endpoint,params,*args,**kwargs):
        calls.append(params)
        if len(calls)>1:raise HTTPError('private',429,'private',{'Retry-After':'900'},None)
        return dict(data=[dict(user_login=channels[0],type='live')])
    cache=StreamAvailability(enabled=True,fetch=fetch,clock=lambda:seconds[0])
    now=datetime(2026,1,1,tzinfo=timezone.utc)
    initial=cache.snapshot(channels,now=now)
    assert initial[channels[0]]['status']=='live' and initial[channels[1]]['status']=='offline'
    assert cache.next_check==900
    seconds[0]=121
    expired=cache.snapshot(channels,now=now+timedelta(seconds=121))
    for channel,previous in ((channels[0],'live'),(channels[1],'offline')):
        assert expired[channel]['status']==previous and expired[channel]['reason']=='stale_check'
        assert expired[channel]['last_known_status']==previous
        assert not capture_paused(expired[channel],now=now+timedelta(seconds=121))
    assert len(calls)==2


@pytest.mark.parametrize('initial',['live','offline'])
def test_failed_refresh_keeps_display_status_and_uptime_without_renewing_capture_freshness(monkeypatch,initial):
    monkeypatch.setenv('TWITCH_CLIENT_ID','private');monkeypatch.setenv('TWITCH_ACCESS_TOKEN','private')
    now=datetime(2026,1,1,tzinfo=timezone.utc);seconds=[0];failed=[False];online=[initial=='live']
    def fetch(*args,**kwargs):
        if failed[0]:raise URLError('unavailable')
        return dict(data=[dict(user_login='alpha',type='live',game_name='MapleStory',started_at='2025-12-31T23:00:00Z')] if online[0] else [])
    cache=StreamAvailability(enabled=True,fetch=fetch,clock=lambda:seconds[0])
    first=cache.snapshot(['alpha'],now=now)['alpha']
    failed[0]=True
    for elapsed in (61,121,181):
        seconds[0]=elapsed
        value=cache.snapshot(['alpha'],now=now+timedelta(seconds=elapsed))['alpha']
        assert value['status']==initial and value['started_at']==first['started_at']
        assert value['game_name']==first['game_name'] and value['reason']=='api_unavailable'
        assert value['checked_at']==first['checked_at'] and value['valid_until']==first['valid_until']
        assert capture_paused(value,now=now+timedelta(seconds=elapsed)) is (initial=='offline' and elapsed<120)
    failed[0]=False;online[0]=not online[0];seconds[0]=241
    changed=cache.snapshot(['alpha'],now=now+timedelta(seconds=241))['alpha']
    assert changed['status']==('offline' if initial=='live' else 'live') and changed['reason'] is None
    assert changed['started_at']==(None if initial=='live' else '2025-12-31T23:00:00+00:00')


def test_minute_refreshes_overlap_for_four_rounds_of_250_channels(monkeypatch):
    monkeypatch.setenv('TWITCH_CLIENT_ID','private');monkeypatch.setenv('TWITCH_ACCESS_TOKEN','private')
    now=datetime(2026,1,1,tzinfo=timezone.utc);seconds=[0];batches=[]
    def fetch(endpoint,params,*args,**kwargs):
        batches.append(len(params['user_login']));seconds[0]+=.25
        return dict(data=[])
    cache=StreamAvailability(enabled=True,fetch=fetch,clock=lambda:seconds[0])
    channels=[f'channel{i:03}' for i in range(250)]
    for _ in range(4):
        statuses=cache.snapshot(channels,now=now+timedelta(seconds=seconds[0]))
        seconds[0]=cache.next_check
        assert all(s['status']=='offline' and capture_paused(s,now=now+timedelta(seconds=seconds[0])) for s in statuses.values())
    assert batches==[100,100,50]*4


def test_rate_limit_respects_bounded_retry_after(monkeypatch):
    monkeypatch.setenv('TWITCH_CLIENT_ID','private');monkeypatch.setenv('TWITCH_ACCESS_TOKEN','private')
    calls=[];seconds=[0]
    def fail(*a,**kw):
        calls.append(True);raise HTTPError('secret',429,'secret',{'Retry-After':'120'},None)
    cache=StreamAvailability(enabled=True,fetch=fail,clock=lambda:seconds[0])
    assert cache.snapshot(['alpha'])['alpha']['reason']=='rate_limited'
    seconds[0]=119;cache.snapshot(['alpha']);assert len(calls)==1
    seconds[0]=120;cache.snapshot(['alpha']);assert len(calls)==2


def test_helix_encodes_multiple_logins_and_bounds_response(monkeypatch):
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,size):assert size==262145;return b'{"data": []}'
    def open(request,timeout):
        assert 'user_login=alpha&user_login=beta' in request.full_url
        assert request.get_header('Authorization')=='Bearer token' and timeout==3
        return Response()
    monkeypatch.setattr('exp_tracker.twitch_probe.urlopen',open)
    assert helix('streams',dict(user_login=['alpha','beta']), 'client','token',timeout=3)==dict(data=[])


def paginated_cache(monkeypatch,pages):
    monkeypatch.setenv('TWITCH_CLIENT_ID','private-client');monkeypatch.setenv('TWITCH_ACCESS_TOKEN','private-token')
    calls=[]
    def fetch(endpoint,params,client,token,**kwargs):
        assert endpoint=='streams' and kwargs==dict(timeout=3)
        calls.append(params)
        page=pages[len(calls)-1]
        if isinstance(page,Exception):raise page
        return page
    return StreamAvailability(enabled=True,fetch=fetch,clock=lambda:0),calls


def test_live_channel_with_cursor_and_empty_final_page_checks_offline_and_caches(monkeypatch):
    cache,calls=paginated_cache(monkeypatch,[
        dict(data=[dict(user_login='streamer_a',type='live')],pagination=dict(cursor='next')),
        dict(data=[],pagination={})])
    result=cache.snapshot(['streamer_a','streamer_b'])
    assert result['streamer_a']['status']=='live' and result['streamer_b']['status']=='offline'
    assert calls==[dict(user_login=['streamer_a','streamer_b'],first=100),
                   dict(user_login=['streamer_a','streamer_b'],first=100,after='next')]
    assert cache.snapshot(['streamer_b','streamer_a'])==result and len(calls)==2


@pytest.mark.parametrize('failure,reason',[
    (dict(data=[],pagination=dict(cursor='next')),'pagination_repeated_cursor'),
    (dict(data=[dict(user_login='unexpected',type='live')]),'api_unavailable'),
    (dict(data=None),'api_unavailable'),
    (HTTPError('secret',401,'secret',{},None),'credentials_rejected'),
    (HTTPError('secret',503,'secret',{},None),'api_error'),
    (HTTPError('secret',429,'secret',{'Retry-After':'120'},None),'rate_limited'),
    (URLError('secret'),'api_unavailable'),
])
def test_incomplete_pagination_preserves_verified_live_and_leaves_rest_unknown(monkeypatch,failure,reason):
    cache,calls=paginated_cache(monkeypatch,[
        dict(data=[dict(user_login='alpha',type='live')],pagination=dict(cursor='next')),failure])
    result=cache.snapshot(['alpha','beta'])
    assert len(calls)==2
    assert result['alpha']['status']=='live' and result['alpha']['reason'] is None
    assert result['beta']['status']=='unknown' and result['beta']['reason']==reason
    assert 'secret' not in str(result)
    assert cache.next_check==(120 if reason=='rate_limited' else 300 if reason=='credentials_rejected' else 60)


def test_page_limit_is_unknown_not_offline_and_retains_live(monkeypatch):
    cache,calls=paginated_cache(monkeypatch,[dict(data=[dict(user_login='alpha',type='live')],
        pagination=dict(cursor=f'page-{i}')) for i in range(MAX_STREAM_PAGES)])
    result=cache.snapshot(['alpha','beta'])
    assert len(calls)==MAX_STREAM_PAGES
    assert result['alpha']['status']=='live'
    assert result['beta']['status']=='unknown' and result['beta']['reason']=='pagination_limit'


def test_all_requested_channels_live_does_not_follow_unnecessary_cursor(monkeypatch):
    cache,calls=paginated_cache(monkeypatch,[dict(data=[dict(user_login=c,type='live') for c in ('alpha','beta')],
        pagination=dict(cursor='unneeded'))])
    assert all(r['status']=='live' for r in cache.snapshot(['alpha','beta']).values())
    assert len(calls)==1


def test_rate_limit_backoff_does_not_extend_partial_live_freshness(monkeypatch):
    cache,calls=paginated_cache(monkeypatch,[
        dict(data=[dict(user_login='alpha',type='live')],pagination=dict(cursor='next')),
        HTTPError('secret',429,'secret',{'Retry-After':'120'},None)])
    now=datetime(2026,1,1,tzinfo=timezone.utc)
    assert cache.snapshot(['alpha','beta'],now=now)['alpha']['status']=='live'
    assert cache.next_check==120
    expired=cache.snapshot(['alpha','beta'],now=now+timedelta(seconds=121))
    assert expired['alpha']['status']=='live' and expired['alpha']['last_known_status']=='live'
    assert len(calls)==2


def test_live_category_is_kept_and_only_a_named_other_category_is_outside_maplestory(monkeypatch):
    monkeypatch.setenv('TWITCH_CLIENT_ID','private-client');monkeypatch.setenv('TWITCH_ACCESS_TOKEN','private-token')
    rows=[dict(user_login='alpha',type='live',game_name='MapleStory'),dict(user_login='beta',type='live',game_name='Just Chatting'),
          dict(user_login='gamma',type='live',game_name='')]
    result=StreamAvailability(enabled=True,fetch=lambda *a,**kw:dict(data=rows,pagination={}),clock=lambda:0).snapshot(['alpha','beta','gamma','delta'])
    channels=('alpha','beta','gamma','delta')
    assert [result[c]['game_name'] for c in channels]==['MapleStory','Just Chatting','',None]
    # Only a named non-MapleStory category counts; blank, unknown and offline never pause capture.
    assert [outside_maplestory(result[c]) for c in channels]==[False,True,False,False]
    assert not outside_maplestory(dict(status='live',game_name='MapleStory Worlds')) and not outside_maplestory(None)
