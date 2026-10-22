"""Disposable, versioned restart acceleration; never writes the tracking database."""
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import zlib

from .retention import dumps, loads
from .rolling_history import LOCK, MAX_BYTES, MAX_EVENTS, MAX_RUNS, MAX_CHECKPOINTS, select_runs
from .writer_lock import writer_lease

APPLICATION_ID = 0x4D535850
FORMAT = 1


def identity(database):
    path=Path(database).resolve();stat=path.stat()
    return [str(path),stat.st_dev,stat.st_ino]


def code_revision():
    root=Path(__file__).parent;digest=hashlib.sha256()
    for path in sorted([*root.glob('*.py'),*root.joinpath('data').glob('*.json')]):
        digest.update(path.name.encode());digest.update(path.read_bytes())
    return digest.hexdigest()


def encoded(value):
    raw=dumps(value).encode()
    if len(raw)>MAX_BYTES:raise ValueError('publication cache record exceeds limit')
    return zlib.compress(raw,1)


def decoded(value):
    decoder=zlib.decompressobj();raw=decoder.decompress(value,MAX_BYTES+1)
    if len(raw)>MAX_BYTES or decoder.unconsumed_tail or not decoder.eof:
        raise ValueError('invalid publication cache record')
    return loads(raw)


class PublicationCache:
    def __init__(self,path,database,schema):
        self.path=Path(path).resolve();self.db=None;self.lease=None;self.digests={}
        self.scope=[FORMAT,identity(database),schema,code_revision()]
        if self.path in (Path(database).resolve(),Path(database).resolve().with_suffix(Path(database).suffix+'.multi-alpha.json')) or (self.path.exists() and self.path.samefile(database)):
            raise ValueError('publication cache must be separate from the tracking database')
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        lock=self.path.with_suffix(self.path.suffix+'.lock');lock.touch(mode=0o600,exist_ok=True)
        self.lease=writer_lease(lock,message='Another API process owns this publication cache')
        self.lease.__enter__()
        try:
            existing=self.path.exists() and self.path.stat().st_size>0
            self.db=sqlite3.connect(self.path,timeout=1,check_same_thread=False)
            if existing and self.db.execute('PRAGMA application_id').fetchone()[0]!=APPLICATION_ID:
                raise ValueError('not an owned publication cache; choose a new cache file')
            self.db.execute(f'PRAGMA application_id={APPLICATION_ID}')
            self.db.execute('CREATE TABLE IF NOT EXISTS metadata (scope TEXT NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS entries (channel TEXT PRIMARY KEY,payload BLOB NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS checkpoints (channel TEXT PRIMARY KEY,prefix TEXT NOT NULL,payload BLOB NOT NULL)')
            row=self.db.execute('SELECT scope FROM metadata').fetchone()
            try:scope=json.loads(row[0]) if row else None
            except ValueError:scope=None
            if scope!=self.scope:
                for table in ('entries','checkpoints','metadata'):self.db.execute('DELETE FROM '+table)
                self.db.execute('INSERT INTO metadata VALUES(?)',(json.dumps(self.scope),))
            self.db.commit()
            self.path.chmod(0o600)
        except Exception:
            self.close();raise

    def close(self):
        if self.db:self.db.close();self.db=None
        if self.lease:self.lease.__exit__(None,None,None);self.lease=None

    def signature(self,store,runs,through):
        if len(runs)>MAX_RUNS:raise ValueError('cache run limit')
        digest=hashlib.sha256();count=0;size=0
        for run in runs:
            head=store.db.execute('SELECT configuration_json,summary_json FROM diagnostic_runs WHERE run_id=?',(run,)).fetchone()
            if head is None:raise ValueError('cached run no longer exists')
            # Closed runs are immutable during an API lifetime, so skip rescanning their payloads on every save;
            # a restart starts with an empty memo and verifies every byte again.
            # An old publication may cover only part of a run that has since closed.
            last=store.db.execute('SELECT COALESCE(MAX(id),0) FROM diagnostic_attempts WHERE run_id=?',(run,)).fetchone()[0]
            key=(run,*head,min(through,last))
            saved=self.digests.get(key) if head[1] is not None else None
            if saved is None:
                mark=store.db.execute('SELECT COUNT(*),COALESCE(SUM(LENGTH(CAST(payload_json AS BLOB))),0) FROM diagnostic_attempts WHERE run_id=? AND id<=?',(run,through)).fetchone()
                if mark[0]>60 or count+mark[0]>MAX_EVENTS or size+mark[1]>MAX_BYTES:raise ValueError('cache source limit')
                rows=store.db.execute('SELECT id,payload_json FROM diagnostic_attempts WHERE run_id=? AND id<=? ORDER BY id',(run,through)).fetchall()
                saved=(hashlib.sha256(json.dumps([run,list(head),[list(r) for r in rows]],ensure_ascii=True).encode()).hexdigest(),*mark)
                if head[1] is not None:
                    if len(self.digests)>=MAX_RUNS*2:self.digests.pop(next(iter(self.digests)))
                    self.digests[key]=saved
            count+=saved[1];size+=saved[2]
            if count>MAX_EVENTS or size>MAX_BYTES:raise ValueError('cache source limit')
            digest.update(saved[0].encode())
        return digest.hexdigest()

    def wrap(self,store,value,runs):
        through=store.db.execute('SELECT COALESCE(MAX(id),0) FROM diagnostic_attempts').fetchone()[0]
        return dict(value=value,runs=runs,through=through,signature=self.signature(store,runs,through))

    def read(self,table,store,channel):
        row=self.db.execute('SELECT payload FROM '+table+' WHERE channel=? AND LENGTH(payload)<=?',(channel,MAX_BYTES)).fetchone()
        if row is None:return None
        try:
            saved=decoded(row[0])
            if saved['signature']==self.signature(store,saved['runs'],saved['through']):return saved['value']
        except (ValueError,KeyError,TypeError,OverflowError,zlib.error,json.JSONDecodeError):pass
        return None

    @staticmethod
    def compatible(key,head):
        current=tuple(head)
        # Ordinary capture appends may leave a dated publication available while rebuilding.
        return len(key)==len(current) and key[:3]==current[:3] and key[7:]==current[7:]

    def restore_entry(self,store,head,now):
        entry=self.read('entries',store,head['login'])
        if (entry and self.compatible(entry['key'],head)
                and timedelta(0)<=now-datetime.fromisoformat(entry['built_at'])<=timedelta(hours=24)):
            entry['restored']=True
            return entry

    def restore_checkpoints(self,store,head,checkpoints,now):
        saved=self.read('checkpoints',store,head['login'])
        if not saved or not self.compatible(saved['head'],head):return
        with LOCK:
            for key,value in saved['items']:
                if value['now']<=now:
                    if key not in checkpoints and len(checkpoints)>=MAX_CHECKPOINTS:checkpoints.pop(next(iter(checkpoints)))
                    checkpoints[key]=value

    def save(self,store,diagnostics,head,entry,checkpoints):
        channel=head['login'];now=datetime.fromisoformat(entry['built_at'])
        runs=[r['run_id'] for r in select_runs(diagnostics,channel,start=now-timedelta(hours=48,minutes=5),now=now)]
        with LOCK:items=[(k,v) for k,v in checkpoints.items() if k[1:3]==(channel,head['selected_character_id'])]
        prefix=hashlib.sha256(dumps([(k,v['runs']) for k,v in items]).encode()).hexdigest()
        old=self.db.execute('SELECT prefix FROM checkpoints WHERE channel=?',(channel,)).fetchone()
        # Encode before the transaction so failure cannot persist half of a publication.
        payload=encoded(self.wrap(store,entry,runs))
        checkpoint=None
        if items and (not old or old[0]!=prefix):
            covered=sorted({r[0] for _,v in items for r in v['runs']})
            checkpoint=encoded(self.wrap(store,dict(head=tuple(head),items=items),covered))
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO entries VALUES(?,?)',(channel,payload))
            if checkpoint is not None:self.db.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)',(channel,prefix,checkpoint))

    def prune(self,channels):
        for table in ('entries','checkpoints'):
            for row in self.db.execute('SELECT channel FROM '+table).fetchall():
                if row[0] not in channels:self.db.execute('DELETE FROM '+table+' WHERE channel=?',row)
        self.db.commit()
