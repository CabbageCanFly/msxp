from io import BytesIO
from datetime import datetime,timedelta,timezone
from urllib.error import HTTPError,URLError

from PIL import Image
import pytest

from exp_tracker.twitch_probe import inspect_thumbnail, main, thumbnail_url
from exp_tracker.twitch_probe import StreamAvailability,helix


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
        seconds[0]+=60;failure[0]=error
        result=status.snapshot(['alpha','beta'],now=now+timedelta(seconds=seconds[0]))
        assert all(r['status']=='unknown' and r['reason']==reason for r in result.values())
        assert result['alpha']['last_known_status']=='live'
        assert all('private' not in str(r) and 'secret' not in str(r) for r in result.values())
    seconds[0]+=60;failure[0]=None
    assert status.snapshot(['alpha','beta'],now=now+timedelta(seconds=seconds[0]))['alpha']['status']=='live'


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
    assert cache.snapshot(['alpha'],now=now+timedelta(seconds=61))['alpha']['status']=='unknown'


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
