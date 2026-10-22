"""Private in-memory Twitch credentials. No token/secret serialization or logging."""

import json
import math
import os
from http.client import HTTPException
from pathlib import Path
import re
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

DEFAULT_ENV_FILE=Path(__file__).resolve().parents[2]/'.env'
KEYS=('TWITCH_CLIENT_ID','TWITCH_CLIENT_SECRET','TWITCH_ACCESS_TOKEN')


class AuthError(RuntimeError):
    def __init__(self,reason,retry_after=300):
        super().__init__(reason)
        self.reason=reason;self.retry_after=retry_after


def credentials(env_file=None,environ=None,*,keys=KEYS):
    """A deliberately small KEY=value reader: no expansion, execution or env writes."""
    values={};path=Path(env_file) if env_file is not None else DEFAULT_ENV_FILE
    environment=os.environ if environ is None else environ
    try:
        if any(key not in environment for key in keys) and path.exists():
            with path.open('rb') as source:payload=source.read(16385)
            if len(payload)>16384:raise ValueError
            for line in payload.decode('utf-8-sig').splitlines():
                line=line.strip()
                if line.startswith('export '):line=line[7:].lstrip()
                key,separator,value=line.partition('=');key=key.strip()
                if key not in keys or key in environment:continue
                if not separator:raise ValueError
                value=value.strip()
                if value[:1] in ('"',"'"):
                    end=value.find(value[0],1)
                    if end<1 or value[end+1:].strip() and not value[end+1:].strip().startswith('#'):raise ValueError
                    value=value[1:end]
                else:value=re.split(r'\s+#',value,maxsplit=1)[0].strip()
                values[key]=value
    except (OSError,ValueError):raise AuthError('invalid_credentials_file') from None
    values={key:environment.get(key,values.get(key,'')) for key in keys}
    if any(not isinstance(v,str) or len(v)>4096 or any(c.isspace() or ord(c)<32 or ord(c)==127 for c in v) for v in values.values()):
        raise AuthError('invalid_credentials')
    return values


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None  # Never forward authentication headers or POST secrets elsewhere.


def oauth_json(request):
    with build_opener(_NoRedirect()).open(request,timeout=3) as response:
        payload=response.read(16385)
        if len(payload)>16384:raise ValueError('Authentication response exceeds limit')
        return json.loads(payload)


def retry_delay(error):
    try:return max(60,min(900,int((error.headers or {}).get('Retry-After','60'))))
    except (TypeError,ValueError):return 60


class AppTokens:
    """Single-flight acquisition/validation; app tokens are reacquired, not refreshed."""
    def __init__(self,*,env_file=None,environ=None,request=None,clock=time.monotonic,maintain=False):
        self._env_file=env_file;self._environ=environ;self._request=request or oauth_json;self._clock=clock
        self._lock=threading.Lock();self._credentials=None;self._token=None
        self._renew_at=0;self._validate_at=0;self._retry_at=0;self._reason=None
        self._maintain=maintain;self._stop=threading.Event();self._thread=None

    def _maintenance(self):
        while not self._stop.wait(max(1,min(3600,max(self._validate_at,self._retry_at)-self._clock()))):
            try:self.get()
            except AuthError:pass  # Safe reason/backoff stays available to the status checker.

    def close(self):
        self._stop.set()
        if self._thread:self._thread.join(timeout=10)

    def _fail(self,reason,delay):
        self._reason=reason;self._retry_at=self._clock()+delay
        raise AuthError(reason,delay) from None

    def _json(self,request):
        try:return self._request(request)
        except HTTPError as error:
            if error.code==401:raise
            self._fail('credentials_rejected' if error.code==400 else 'auth_rate_limited' if error.code==429 else 'auth_unavailable',
                300 if error.code==400 else retry_delay(error) if error.code==429 else 60)
        except (OSError,ValueError,TypeError,HTTPException):self._fail('auth_unavailable',60)

    @staticmethod
    def _ttl(response):
        ttl=response['expires_in']
        if type(ttl) is not int or not 0<ttl<=2**31-1:raise ValueError
        return ttl

    def _acquire(self):
        body=urlencode(dict(client_id=self._credentials['TWITCH_CLIENT_ID'],
            client_secret=self._credentials['TWITCH_CLIENT_SECRET'],grant_type='client_credentials')).encode('ascii')
        request=Request('https://id.twitch.tv/oauth2/token',data=body,
            headers={'Content-Type':'application/x-www-form-urlencoded'},method='POST')
        try:
            response=self._json(request);ttl=self._ttl(response);token=response['access_token']
            if response.get('token_type')!='bearer' or not isinstance(token,str) or not token or len(token)>4096 or not token.isascii() or not token.isprintable() or any(c.isspace() for c in token):raise ValueError
        except HTTPError:self._fail('credentials_rejected',300)
        except (ValueError,TypeError,KeyError,AttributeError):self._fail('invalid_auth_response',60)
        self._token=token;self._renew_at=self._clock()+ttl-min(60,ttl/10);self._validate_at=0

    def _validate(self):
        response=self._json(Request('https://id.twitch.tv/oauth2/validate',
            headers={'Authorization':'OAuth '+self._token}))
        try:
            ttl=self._ttl(response)
            if response['client_id']!=self._credentials['TWITCH_CLIENT_ID']:raise ValueError
        except (ValueError,TypeError,KeyError):self._token=None;self._fail('invalid_token_validation',300)
        self._renew_at=self._clock()+ttl-min(60,ttl/10)
        self._validate_at=self._clock()+3600

    def get(self,*,rejected_token=None):
        with self._lock:
            if self._stop.is_set():raise AuthError('auth_stopped')
            now=self._clock()
            if now<self._retry_at:raise AuthError(self._reason,max(1,math.ceil(self._retry_at-now)))
            if self._credentials is None:
                try:self._credentials=credentials(self._env_file,self._environ)
                except AuthError as error:self._fail(error.reason,error.retry_after)
            client=self._credentials['TWITCH_CLIENT_ID'];managed=bool(self._credentials['TWITCH_CLIENT_SECRET'])
            if not client or not managed and not self._credentials['TWITCH_ACCESS_TOKEN']:
                self._fail('missing_credentials',300)
            if rejected_token is not None and rejected_token==self._token:
                self._token=None
                if not managed:self._fail('credentials_rejected',300)
            acquired=False
            if self._token is None or now>=self._renew_at:
                if managed:self._acquire();acquired=True
                else:self._token=self._credentials['TWITCH_ACCESS_TOKEN'];self._validate_at=0
            if self._clock()>=self._validate_at:
                try:self._validate()
                except HTTPError:
                    self._token=None
                    if not managed or acquired:self._fail('credentials_rejected',300)
                    self._acquire()
                    try:self._validate()
                    except HTTPError:self._token=None;self._fail('credentials_rejected',300)
            self._reason=None;self._retry_at=0
            if self._maintain and self._thread is None:
                self._thread=threading.Thread(target=self._maintenance,daemon=True)
                self._thread.start()
            return client,self._token

    def reject(self,token):
        """A second Helix 401 ends this authentication attempt; no refresh loop."""
        with self._lock:
            if token==self._token:
                self._token=None;self._reason='credentials_rejected';self._retry_at=self._clock()+300
