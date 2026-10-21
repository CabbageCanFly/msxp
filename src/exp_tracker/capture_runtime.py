"""Bounded, atomic heartbeat between the single capture writer and read-only API."""
from datetime import datetime
import json
import math
import os
from pathlib import Path
import tempfile
import threading

from .publication_cache import identity
from .store import utc

MAX_BYTES=1024*1024
HEARTBEAT_SECONDS=15


def validate_path(path,database):
    path=Path(path).resolve();database=Path(database).resolve()
    if path in (database,database.with_suffix(database.suffix+'.multi-alpha.json')) or (
            path.exists() and path.samefile(database)):
        raise ValueError('runtime state must be separate from the database and ownership marker')
    return path


class CaptureRuntime:
    def __init__(self,path,database):
        self.path=validate_path(path,database);self.database=identity(database)
        if self.path.exists():
            try:
                with self.path.open('rb') as source:old=json.loads(source.read(MAX_BYTES+1))
                if not isinstance(old,dict) or old.get('format')!=1:raise ValueError()
            except (ValueError,TypeError):raise ValueError('not an owned runtime file; choose a new heartbeat path') from None
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.coordinator_status={};self.active_run_ids=set();self.stop=threading.Event();self.last_error=None
        self.thread=threading.Thread(target=self.run,name='capture-heartbeat',daemon=True)
        self.publish();self.thread.start()

    def publish(self,stopped=False):
        body=dict(format=1,database=self.database,written_at=utc(),states={} if stopped else self.coordinator_status.copy(),
            active_runs=[] if stopped else sorted(self.active_run_ids.copy()))
        raw=json.dumps(body,allow_nan=False).encode()
        if len(raw)>MAX_BYTES:raise ValueError('runtime state exceeds limit')
        name=None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent,prefix=self.path.name+'.',delete=False) as out:
                name=out.name;out.write(raw);out.flush()
            os.replace(name,self.path)
        finally:
            if name and Path(name).exists():Path(name).unlink()

    def run(self):
        while not self.stop.wait(1):
            try:self.publish()
            except (OSError,ValueError):self.last_error='heartbeat_write_failed'

    def server_close(self):
        self.stop.set();self.thread.join(timeout=2)
        try:self.publish(stopped=True)
        except (OSError,ValueError):pass  # Readers expire the previous heartbeat.


class RuntimeReader:
    def __init__(self,path,database):
        self.path=validate_path(path,database);self.database=identity(database)

    def read(self,now):
        try:
            with self.path.open('rb') as source:raw=source.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:return {},set()
            body=json.loads(raw);age=(now-datetime.fromisoformat(body['written_at'])).total_seconds()
            if body.get('format')!=1 or body['database']!=self.database or not 0<=age<=HEARTBEAT_SECONDS:return {},set()
            states=body['states'];runs=body['active_runs']
            if not isinstance(states,dict) or not isinstance(runs,list) or not all(isinstance(r,str) for r in runs):return {},set()
            if not all(isinstance(k,str) and isinstance(v,dict) and v.get('state') in (
                    'running','waiting','stopped','capture_failing','capture_delayed') for k,v in states.items()):return {},set()
            for state in states.values():
                if state['state'] in ('running','waiting'):
                    field='updated_at' if state['state']=='running' else 'next_due_at'
                    if datetime.fromisoformat(state[field]).utcoffset() is None:return {},set()
                    number=state['expected_completion_seconds'] if state['state']=='running' else state['requested_interval_seconds']
                    if type(number) not in (int,float) or not math.isfinite(number) or number<=0:return {},set()
            return states,set(runs)
        except (OSError,ValueError,KeyError,TypeError,OverflowError):return {},set()
