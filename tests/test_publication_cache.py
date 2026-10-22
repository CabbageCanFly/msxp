"""Restart recovery is disposable, causal and never changes capture history."""
from datetime import timedelta
import json
import sqlite3

import pytest

from exp_tracker.publication_cache import PublicationCache,encoded,decoded
from exp_tracker.server import create_server
from exp_tracker.store import Store
from tests.test_product import tracking,NOW
from tests.test_publisher import clock,published,reference
from tests.test_tracked_exp_totals import save


def prepare(d):
    for i in range(1,5):save(d,'run',i,(i-1)*20,3300+i*5)
    d.append('run',dict(type='summary',trusted=False,attempts=4,interrupted=False))


def test_restart_restores_dated_publication_and_exact_typed_checkpoints(tracking,clock,tmp_path,monkeypatch):
    path,store,d=tracking;prepare(d);clock.at=NOW+timedelta(seconds=60)
    cache=tmp_path/'warm.sqlite3'
    raw=[tuple(r) for r in store.db.execute('SELECT * FROM diagnostic_attempts')]
    with create_server(path,port=0,public_only=True,publication_cache=cache) as server:
        server.publisher.settle()
        expected=published(server,'alpha');checkpoints=dict(server.checkpoints)
        assert checkpoints and not server.publisher.stats['cache_error']
    clock.at+=timedelta(seconds=20)
    with create_server(path,port=0,public_only=True,publication_cache=cache) as server:
        assert server.publisher.stats['restored']==1
        body=json.loads(server.publisher.character('alpha'))
        assert body['player']['publication']==dict(state='restored',computed_at=(NOW+timedelta(seconds=60)).isoformat(),updating=True)
        assert body['player']['latest_attempt_at']==expected['player']['latest_attempt_at']
        assert body['tracked_history']['as_of']==expected['tracked_history']['as_of']
        assert json.loads(server.publisher.homepage())['warming']==['alpha']
        head=server.publisher.heads[0]
        with Store(path,read_only=True) as reader:
            server.publication_cache.restore_checkpoints(reader,head,server.checkpoints,clock.at)
        assert server.checkpoints==checkpoints
        assert decoded(encoded(checkpoints[next(iter(checkpoints))]))==checkpoints[next(iter(checkpoints))]
        server.publisher.settle()
        assert published(server,'alpha')==reference(store,server,'alpha',clock.at)
        assert 'publication' not in json.loads(server.publisher.character('alpha'))['player']
        assert not server.publisher.stats['cache_error']
    assert raw==[tuple(r) for r in store.db.execute('SELECT * FROM diagnostic_attempts')]


@pytest.mark.parametrize('change',('code','payload','owner','correction','invalidation','retention','clock','corrupt'))
def test_restart_withholds_invalid_or_incompatible_cached_results(tracking,clock,tmp_path,monkeypatch,change):
    from exp_tracker import publication_cache
    path,store,d=tracking;prepare(d);clock.at=NOW+timedelta(seconds=60);cache=tmp_path/'warm.sqlite3'
    with create_server(path,port=0,public_only=True,publication_cache=cache) as server:server.publisher.settle()
    if change=='code':monkeypatch.setattr(publication_cache,'code_revision',lambda:'new-policy')
    elif change=='payload':
        row=store.db.execute('SELECT id,payload_json FROM diagnostic_attempts LIMIT 1').fetchone()
        payload=json.loads(row[1]);payload['neural']['text']='[99.00%]'
        store.db.execute('UPDATE diagnostic_attempts SET payload_json=? WHERE id=?',(json.dumps(payload),row[0]))
    elif change=='owner':
        cid=store.add_character('alpha','Another');store.select_character('alpha',cid,at=clock.at)
    elif change=='correction':
        store.correct_manual('alpha','manual',store.state('alpha')['selected_character_id'],level=64,current_exp=1000,
            effective_at=clock.at,reason='reviewed correction')
    elif change=='invalidation':
        from exp_tracker.invalidations import Invalidations
        service=Invalidations(store);cid=store.state('alpha')['selected_character_id']
        spec=dict(action='invalidate',kind='diagnostic',identity='run:1',timestamp=NOW.isoformat())
        preview=service.preview('alpha',cid,spec)
        service.commit('alpha',cid,'exclude',spec,preview['fingerprint'])
    elif change=='retention':store.db.execute('UPDATE retention_meta SET revision=revision+1 WHERE id=1')
    elif change=='clock':clock.at=NOW
    else:
        with sqlite3.connect(cache) as db:db.execute("UPDATE entries SET payload=x'000102'")
    with create_server(path,port=0,public_only=True,publication_cache=cache) as server:
        assert server.publisher.entry('alpha') is None
        server.publisher.settle()
        assert server.publisher.entry('alpha') is not None


def test_new_attempt_rebuilds_from_restored_prefix_without_reusing_old_totals(tracking,clock,tmp_path):
    path,store,d=tracking;prepare(d);clock.at=NOW+timedelta(seconds=60);cache=tmp_path/'warm.sqlite3'
    with create_server(path,port=0,public_only=True,publication_cache=cache) as server:server.publisher.settle()
    d.begin('next','alpha',dict(type='configuration',trusted=False,interval=20,source_kind='twitch'))
    save(d,'next',1,80,3400);clock.at=NOW+timedelta(seconds=80)
    with create_server(path,port=0,public_only=True,publication_cache=cache) as server:
        assert server.publisher.entry('alpha')['restored']
        server.publisher.settle()
        assert published(server,'alpha')==reference(store,server,'alpha',clock.at)


def test_run_closed_while_api_stopped_rebuilds_a_restorable_cache(tracking,clock,tmp_path):
    path,store,d=tracking;cache=tmp_path/'warm.sqlite3'
    for i in range(1,4):save(d,'run',i,(i-1)*20,3300+i*5)
    clock.at=NOW+timedelta(seconds=40)
    with create_server(path,port=0,public_only=True,publication_cache=cache) as server:server.publisher.settle()
    save(d,'run',4,60,3320)
    d.append('run',dict(type='summary',trusted=False,attempts=4,interrupted=False))
    clock.at=NOW+timedelta(seconds=60)
    with create_server(path,port=0,public_only=True,publication_cache=cache) as server:
        assert server.publisher.stats['restored']==0
        server.publisher.settle()
        assert published(server,'alpha')==reference(store,server,'alpha',clock.at)
        assert not server.publisher.stats['cache_error']
    with create_server(path,port=0,public_only=True,publication_cache=cache) as server:
        assert server.publisher.stats['restored']==1


def test_cache_cannot_overwrite_history_or_another_database_and_has_single_owner(tracking,tmp_path):
    path,store,_=tracking;before=path.read_bytes()
    with pytest.raises(ValueError,match='separate'):PublicationCache(path,path,store.schema_version)
    foreign=tmp_path/'foreign.sqlite3'
    with sqlite3.connect(foreign) as db:db.execute('CREATE TABLE keep_me (value TEXT)')
    with pytest.raises(ValueError,match='not an owned'):PublicationCache(foreign,path,store.schema_version)
    with sqlite3.connect(foreign) as db:assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()==[('keep_me',)]
    cache=PublicationCache(tmp_path/'warm.sqlite3',path,store.schema_version)
    try:
        with pytest.raises(ValueError,match='Another API'):PublicationCache(cache.path,path,store.schema_version)
    finally:cache.close()
    assert path.read_bytes()==before


def test_corrupt_cache_database_falls_back_to_a_cold_api(tracking,clock,tmp_path):
    path,_,d=tracking;prepare(d);clock.at=NOW+timedelta(seconds=60)
    cache=tmp_path/'broken.sqlite3';cache.write_bytes(b'not a SQLite file')
    with create_server(path,port=0,public_only=True,publication_cache=cache) as server:
        assert server.publisher.stats['cache_error']=='cache_unavailable'
        server.publisher.settle()
        assert server.publisher.entry('alpha') is not None
    assert cache.read_bytes()==b'not a SQLite file'


def test_heartbeat_expiry_is_presented_even_without_another_history_build(tracking,clock,tmp_path):
    from exp_tracker.publication_cache import identity
    path,_,d=tracking;prepare(d);clock.at=NOW+timedelta(seconds=60)
    runtime=tmp_path/'runtime.json'
    runtime.write_text(json.dumps(dict(format=1,database=identity(path),written_at=clock.at.isoformat(),
        states=dict(alpha=dict(state='running',updated_at=clock.at.isoformat(),expected_completion_seconds=45)),active_runs=['run'])))
    with create_server(path,port=0,public_only=True,runtime_state=runtime) as server:
        assert json.loads(server.publisher.runtime('alpha'))[0]['state']=='running'
        clock.at+=timedelta(seconds=16)
        assert json.loads(server.publisher.runtime('alpha'))[0] is None
        assert not server.active_run_ids


def test_closed_run_signature_skips_rescanning_payloads_within_one_api_lifetime(tracking,tmp_path):
    path,store,d=tracking;prepare(d)
    cache=PublicationCache(tmp_path/'warm.sqlite3',path,store.schema_version)
    try:
        with Store(path,read_only=True) as reader:
            (run,summary),=reader.db.execute('SELECT run_id,summary_json FROM diagnostic_runs')
            assert summary is not None
            through=reader.db.execute('SELECT MAX(id) FROM diagnostic_attempts').fetchone()[0]
            scans=[];reader.db.set_trace_callback(lambda sql:scans.append(sql) if 'payload_json' in sql else None)
            first=cache.signature(reader,[run],through)
            assert scans and cache.signature(reader,[run],through)==first and len(scans)==2
            assert cache.signature(reader,[run],through+1)==first and len(scans)==2
    finally:cache.close()
