"""All credentials/responses are synthetic; never load the operator's .env."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from http.client import HTTPException
import json
import threading
from urllib.error import HTTPError,URLError
from urllib.parse import parse_qs

import pytest

from exp_tracker.twitch_auth import AppTokens,AuthError,_NoRedirect,credentials,oauth_json
from exp_tracker.twitch_probe import StreamAvailability


class OAuth:
    def __init__(self):
        self.now=100;self.calls=[];self.expiries={};self.invalid=set();self.error=None
    def __call__(self,request):
        self.calls.append(request)
        if self.error:raise self.error
        assert '?' not in request.full_url
        if request.get_method()=='POST':
            assert request.full_url=='https://id.twitch.tv/oauth2/token'
            assert parse_qs(request.data.decode())==dict(client_id=['testclient'],client_secret=['testsecret'],grant_type=['client_credentials'])
            token=f'TOKEN{len(self.expiries)+1}';self.expiries[token]=self.now+7200
            return dict(access_token=token,expires_in=7200,token_type='bearer')
        assert request.full_url=='https://id.twitch.tv/oauth2/validate'
        token=request.get_header('Authorization').removeprefix('OAuth ')
        if token in self.invalid:raise HTTPError('private',401,'private',{},None)
        return dict(client_id='testclient',expires_in=self.expiries.get(token,self.now+7200)-self.now)
    @property
    def grants(self):return sum(r.get_method()=='POST' for r in self.calls)


@pytest.fixture
def managed(tmp_path):
    oauth=OAuth()
    manager=AppTokens(env_file=tmp_path/'absent.env',environ=dict(TWITCH_CLIENT_ID='testclient',
        TWITCH_CLIENT_SECRET='testsecret',TWITCH_ACCESS_TOKEN='MANUAL'),request=oauth,clock=lambda:oauth.now)
    yield manager,oauth
    manager.close()


def test_acquisition_cache_hourly_validation_and_expiry(managed):
    manager,oauth=managed
    assert manager.get()==('testclient','TOKEN1')  # Secret takes precedence over legacy token.
    assert len(oauth.calls)==2 and oauth.grants==1
    assert manager.get()==('testclient','TOKEN1') and len(oauth.calls)==2
    oauth.now+=3600
    assert manager.get()[1]=='TOKEN1' and len(oauth.calls)==3
    oauth.now=7240  # Renew 60 seconds before the original 7300 expiry.
    assert manager.get()[1]=='TOKEN2' and oauth.grants==2 and len(oauth.calls)==5


def test_hourly_validation_runs_even_without_a_new_helix_request(managed):
    manager,oauth=managed;manager.get()
    class Hour:
        calls=0
        def wait(self,seconds):
            assert seconds==3600
            self.calls+=1
            if self.calls==1:oauth.now+=3600;return False
            return True
        def is_set(self):return False
        def set(self):pass
    manager._stop=Hour();manager._maintenance()
    assert oauth.grants==1 and len(oauth.calls)==3


def test_revoked_existing_app_token_is_reacquired_once(managed):
    manager,oauth=managed;manager.get();oauth.invalid.add('TOKEN1');oauth.now+=3600
    assert manager.get()[1]=='TOKEN2' and oauth.grants==2
    assert len(oauth.calls)==5  # Initial pair, rejected validation, replacement pair.


def test_concurrent_callers_and_stale_401s_share_one_replacement(managed):
    manager,oauth=managed
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert set(pool.map(lambda _:manager.get(),range(24)))=={('testclient','TOKEN1')}
        assert set(pool.map(lambda _:manager.get(rejected_token='TOKEN1'),range(24)))=={('testclient','TOKEN2')}
    assert oauth.grants==2 and len(oauth.calls)==4


def test_helix_401_retries_current_page_once_and_preserves_pagination(managed):
    manager,oauth=managed;calls=[]
    def fetch(endpoint,params,client,token,**kwargs):
        calls.append((dict(params),token))
        if params.get('after')=='next' and token=='TOKEN1':raise HTTPError('private',401,'private',{},None)
        return dict(data=[],pagination={}) if params.get('after') else dict(data=[dict(user_login='alpha',type='live')],pagination=dict(cursor='next'))
    cache=StreamAvailability(enabled=True,fetch=fetch,auth=manager,clock=lambda:oauth.now)
    result=cache.snapshot(['alpha','beta'])
    assert result['alpha']['status']=='live' and result['beta']['status']=='offline'
    assert len(calls)==3 and calls[1][0]==calls[2][0] and calls[2][1]=='TOKEN2'
    assert oauth.grants==2
    cache.snapshot(['alpha','beta']);assert len(calls)==3


def test_repeated_helix_401s_stop_and_back_off(managed):
    manager,oauth=managed;calls=[]
    def fetch(*a,**kw):
        calls.append(True);raise HTTPError('private',401,'private',{},None)
    cache=StreamAvailability(enabled=True,fetch=fetch,auth=manager,clock=lambda:oauth.now)
    result=cache.snapshot(['alpha'])
    assert result['alpha']['status']=='unknown' and result['alpha']['reason']=='credentials_rejected'
    assert len(calls)==2 and oauth.grants==2
    oauth.now+=60;cache.snapshot(['alpha'])
    assert len(calls)==2 and oauth.grants==2
    oauth.now+=240;cache.snapshot(['alpha'])
    assert len(calls)==4 and oauth.grants==4


def test_later_page_authentication_failure_preserves_confirmed_live(managed):
    manager,oauth=managed
    def fetch(endpoint,params,*args,**kwargs):
        if params.get('after'):
            oauth.error=HTTPError('private',400,'private',{},None)
            raise HTTPError('private',401,'private',{},None)
        return dict(data=[dict(user_login='alpha',type='live')],pagination=dict(cursor='next'))
    result=StreamAvailability(enabled=True,auth=manager,fetch=fetch,clock=lambda:oauth.now).snapshot(['alpha','beta'])
    assert result['alpha']['status']=='live'
    assert result['beta']['status']=='unknown' and result['beta']['reason']=='credentials_rejected'


@pytest.mark.parametrize('error,reason,delay',[
    (HTTPError('private',400,'private',{},None),'credentials_rejected',300),
    (HTTPError('private',401,'private',{},None),'credentials_rejected',300),
    (HTTPError('private',429,'private',{'Retry-After':'120'},None),'auth_rate_limited',120),
    (HTTPError('private',503,'private',{},None),'auth_unavailable',60),
    (TimeoutError('private'),'auth_unavailable',60),
    (URLError('private'),'auth_unavailable',60),
    (ValueError('private'),'auth_unavailable',60),
    (HTTPException('private'),'auth_unavailable',60),
])
def test_auth_failures_are_safe_unknown_and_do_not_retry_storm(managed,error,reason,delay):
    manager,oauth=managed;oauth.error=error
    cache=StreamAvailability(enabled=True,auth=manager,fetch=lambda *a,**k:pytest.fail('No Helix with failed authentication'),clock=lambda:oauth.now)
    assert cache.snapshot(['alpha'])['alpha']['reason']==reason
    assert cache.results['alpha']['status']=='unknown'
    assert len(oauth.calls)==1
    oauth.now+=delay-1
    with pytest.raises(AuthError) as caught:manager.get()
    assert str(caught.value)==reason and 'private' not in str(caught.value)
    assert len(oauth.calls)==1
    oauth.error=None;oauth.now+=1
    assert manager.get()[1]=='TOKEN1'


@pytest.mark.parametrize('payload',[None,{},dict(access_token='token',expires_in=True,token_type='bearer'),
    dict(access_token='token',expires_in=-1,token_type='bearer'),dict(access_token='bad\ntoken',expires_in=100,token_type='bearer'),
    dict(access_token='token',expires_in=100,token_type='other')])
def test_malformed_token_responses_are_rejected(managed,payload):
    manager,_=managed;manager._request=lambda _:payload
    with pytest.raises(AuthError,match='invalid_auth_response'):manager.get()


def test_validation_must_match_client_and_does_not_loop(managed):
    manager,oauth=managed
    def request(req):
        result=oauth(req)
        if req.get_method()=='GET':result['client_id']='other'
        return result
    manager._request=request
    with pytest.raises(AuthError,match='invalid_token_validation'):manager.get()
    with pytest.raises(AuthError):manager.get()
    assert len(oauth.calls)==2


def test_new_token_rejected_during_validation_does_not_mint_repeated_tokens(managed):
    manager,oauth=managed;oauth.invalid.add('TOKEN1')
    with pytest.raises(AuthError,match='credentials_rejected'):manager.get()
    assert oauth.grants==1 and len(oauth.calls)==2


def test_legacy_token_is_validated_but_cannot_be_replaced_without_secret(tmp_path):
    oauth=OAuth()
    manager=AppTokens(env_file=tmp_path/'absent',environ=dict(TWITCH_CLIENT_ID='testclient',TWITCH_ACCESS_TOKEN='MANUAL'),request=oauth,clock=lambda:oauth.now)
    assert manager.get()[1]=='MANUAL' and oauth.grants==0 and len(oauth.calls)==1
    with pytest.raises(AuthError,match='credentials_rejected'):manager.get(rejected_token='MANUAL')
    assert len(oauth.calls)==1


def test_dotenv_precedence_quotes_no_expansion_or_environment_mutation(tmp_path):
    path=tmp_path/'.env'
    path.write_text('# local only\nexport TWITCH_CLIENT_ID="file-client"\nTWITCH_CLIENT_SECRET=\'file-secret\' # comment\n'
        'TWITCH_ACCESS_TOKEN=file-token\nUNRELATED=$(not-executed)\n')
    env={'TWITCH_CLIENT_ID':'environment-client','TWITCH_CLIENT_SECRET':''}
    before=env.copy()
    assert credentials(path,env)==dict(TWITCH_CLIENT_ID='environment-client',TWITCH_CLIENT_SECRET='',TWITCH_ACCESS_TOKEN='file-token')
    assert env==before
    path.write_text('TWITCH_CLIENT_ID="unterminated\n')
    assert credentials(path,env)['TWITCH_CLIENT_ID']=='environment-client'
    with pytest.raises(AuthError,match='invalid_credentials_file'):credentials(path,{})


def test_repository_dotenv_is_used_automatically_only_when_enabled(monkeypatch,tmp_path):
    path=tmp_path/'.env';path.write_text('TWITCH_CLIENT_ID=testclient\nTWITCH_CLIENT_SECRET=testsecret\n')
    monkeypatch.setattr('exp_tracker.twitch_auth.DEFAULT_ENV_FILE',path)
    oauth=OAuth();manager=AppTokens(environ={},request=oauth,clock=lambda:oauth.now)
    cache=StreamAvailability(enabled=False,auth=manager,clock=lambda:oauth.now)
    assert cache.snapshot(['alpha'])['alpha']['reason']=='not_enabled' and not oauth.calls
    cache=StreamAvailability(enabled=True,auth=manager,fetch=lambda *a,**kw:dict(data=[]),clock=lambda:oauth.now)
    assert cache.snapshot(['alpha'])['alpha']['status']=='offline' and oauth.grants==1


def test_hourly_timer_reschedules_after_a_mid_hour_replacement(managed):
    manager,oauth=managed;manager.get();delays=[]
    class Timer:
        def wait(self,delay):
            delays.append(delay)
            if len(delays)==1:
                oauth.now=110;manager.get(rejected_token='TOKEN1');oauth.now=3700;return False
            if len(delays)==2:oauth.now+=delay;return False
            return True
        def is_set(self):return False
        def set(self):pass
    manager._stop=Timer();manager._maintenance()
    assert delays==[3600,10,3600] and oauth.grants==2 and len(oauth.calls)==5


def test_dotenv_size_and_header_injection_are_rejected(tmp_path):
    path=tmp_path/'.env';path.write_bytes(b'#'*16385)
    with pytest.raises(AuthError,match='invalid_credentials_file'):credentials(path,{})
    with pytest.raises(AuthError,match='invalid_credentials'):credentials(tmp_path/'missing',{'TWITCH_CLIENT_ID':'bad\nheader'})
    manager=AppTokens(env_file=tmp_path/'absent',environ={},request=lambda _:pytest.fail('No authentication with missing credentials'))
    with pytest.raises(AuthError,match='missing_credentials'):manager.get()


def test_transport_no_secret_urls_no_redirects_bounded_reads(monkeypatch,managed):
    manager,oauth=managed
    class Opener:
        def open(self,request,timeout):
            assert timeout==3
            payload=json.dumps(oauth(request)).encode()
            class Response(BytesIO):
                def read(self,size):assert size==16385;return super().read(size)
            return Response(payload)
    def opener(handler):
        assert isinstance(handler,_NoRedirect) and handler.redirect_request(None,None,None,None,None,None) is None
        return Opener()
    monkeypatch.setattr('exp_tracker.twitch_auth.build_opener',opener)
    manager._request=oauth_json
    assert manager.get()[1]=='TOKEN1'


def test_server_owns_hourly_timer_and_closes_it_without_capture(monkeypatch,tmp_path,managed):
    from exp_tracker.server import create_server
    from exp_tracker.store import Store
    manager,oauth=managed;manager._maintain=True
    monkeypatch.setattr('exp_tracker.server.AppTokens',lambda **kw:manager)
    path=tmp_path/'tracker.sqlite3'
    with Store(path):pass
    with create_server(path,port=0,twitch_status=True) as server:
        assert not oauth.calls  # Opt-in does not create an OAuth session until first use.
        server.twitch_availability.auth.get()
        assert manager._thread.is_alive()
    assert not manager._thread.is_alive()
    with pytest.raises(AuthError,match='auth_stopped'):manager.get()


def test_status_only_cli_is_read_only_and_prints_no_credentials(monkeypatch,managed,capsys):
    from exp_tracker.twitch_probe import main
    manager,_=managed
    monkeypatch.setattr('exp_tracker.twitch_probe.AppTokens',lambda **kw:manager)
    monkeypatch.setattr('exp_tracker.twitch_probe.helix',lambda *a,**kw:dict(data=[dict(user_login='alpha',type='live')]))
    assert main(['--status-only','alpha','beta'])==0
    text=capsys.readouterr().out;result=json.loads(text)['channels']
    assert result['alpha']['status']=='live' and result['beta']['status']=='offline'
    assert all(secret not in text for secret in ('testclient','testsecret','TOKEN1','MANUAL'))


def test_waiting_authentication_does_not_hold_capture_database_writes(managed,tmp_path):
    from exp_tracker.server import create_server
    from exp_tracker.store import Store
    from exp_tracker.diagnostics import Diagnostics
    from tests.test_server import request
    from tests.test_product import append,NOW
    manager,oauth=managed;entered=threading.Event();release=threading.Event()
    def blocked(req):
        entered.set();assert release.wait(5)
        return oauth(req)
    manager._request=blocked
    path=tmp_path/'tracker.sqlite3'
    with Store(path) as store:
        store.add_channel('alpha');cid=store.add_character('alpha','Main');store.select_character('alpha',cid);store.start_session('alpha',at=NOW)
        d=Diagnostics(store);d.begin('run','alpha',dict(type='configuration',trusted=False,interval=15,source_kind='twitch'))
        append(d,1,'[33.00%]')
        with create_server(path,port=0,diagnostic_dashboard=True) as http,ThreadPoolExecutor(max_workers=1) as pool:
            http.twitch_availability=StreamAvailability(enabled=True,auth=manager,fetch=lambda *a,**kw:dict(data=[]),clock=lambda:oauth.now)
            pending=pool.submit(request,(http,None),'/api/players/alpha')
            try:
                assert entered.wait(2)
                append(d,2,'[33.01%]')
                assert store.db.execute('select count(*) from diagnostic_attempts').fetchone()[0]==2
                assert not pending.done()
            finally:release.set()
            assert pending.result(timeout=5)[0]==200
