"""Username changes preserve original evidence and never splice live EXP state."""
from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest

from exp_tracker import streamer_aliases as aliases, streamer_merge as merge, streamer_roster as roster
from exp_tracker.store import Store, utc


def change(store,login,**settings):
    action='roster_update' if roster.entry(store,login) else 'roster_add'
    if action=='roster_add':settings.setdefault('public_visible',True)
    return roster.commit(store,roster.preview(store,dict(action=action,channel=login,reason='Synthetic username change',**settings)))


def acknowledge(store):
    for row in roster.entries(store):
        store.db.execute('''INSERT OR REPLACE INTO streamer_runtime VALUES(?,?,?,?,?,?,?)''',
            (row['streamer_id'],row['revision'],'paused' if not row['tracking_enabled'] else 'waiting',None,None,None,utc()))


@pytest.fixture
def fixture(tmp_path):
    path=roster.create(tmp_path/'merge.sqlite3')
    with Store(path) as store:
        for login in ('streamer_a','streamer_b','streamer_c'):change(store,login,tracking_enabled=False)
        old=store.add_character('streamer_a','CharA');alt=store.add_character('streamer_a','CharB')
        new=store.add_character('streamer_b','CharA');other=store.add_character('streamer_c','CharZ')
        now=datetime.now(timezone.utc)
        for login,cid,ago in [('streamer_a',old,10),('streamer_a',alt,8),('streamer_b',new,1),('streamer_c',other,1)]:
            store.select_character(login,cid,at=now-timedelta(days=ago))
            store.start_session(login,at=now-timedelta(days=ago))
            store.end_session(login,at=now-timedelta(days=ago)+timedelta(hours=1))
        store.select_character('streamer_a',old,at=now-timedelta(days=7))
        for cid,level in [(old,90),(new,91),(alt,70),(other,60)]:
            store.db.execute('INSERT INTO character_level_guard(character_id,level,proof_json,updated_at) VALUES(?,?,?,?)',
                (cid,level,json.dumps(dict(received_at=utc(now-timedelta(days=1)))),utc()))
        for cid,level,ago,bp in [(old,90,5,3400),(old,90,4,5000),(alt,70,8,8300),(new,91,1,3200)]:
            stamp=utc(now-timedelta(days=ago))
            store.db.execute('INSERT INTO daily_character_exp VALUES(?,?,?,?,?,?,?,?,?,?)',
                (cid,stamp[:10],stamp,level,1000,bp,'diagnostic','agreement','observed_integer','displayed'))
        store.db.execute('INSERT INTO retention_state VALUES(?,?,?)',(old,utc(now-timedelta(days=2)),json.dumps(dict(display={}))))
        acknowledge(store)
    return path,old,alt,new,other


def state(store):
    return {table:[tuple(r) for r in store.db.execute('SELECT * FROM '+table)] for table in
        ('streamers','characters','sessions','diagnostic_runs','daily_character_exp','retention_state','streamer_capture','streamer_roster_events')}


def test_merge_moves_distinct_character_copies_daily_archive_keeps_evidence_and_unrelated_stream(fixture):
    path,old,alt,new,other=fixture
    with Store(path) as store:
        before=state(store);plan=merge.preview(store,'streamer_a','streamer_b',{old:new})
        assert state(store)==before  # A preview does not create tables, pause lanes or edit records.
        original_checkpoint=store.db.execute('SELECT * FROM retention_state WHERE character_id=?',(old,)).fetchone()
        assert merge.commit(store,plan)['saved']
        sid=store._channel('streamer_b')['id']
        assert store.db.execute('SELECT streamer_id FROM characters WHERE id=?',(alt,)).fetchone()[0]==sid
        assert store.db.execute('SELECT streamer_id FROM sessions WHERE character_id=?',(alt,)).fetchone()[0]==sid
        assert tuple(store.db.execute('SELECT * FROM retention_state WHERE character_id=?',(old,)).fetchone())==tuple(original_checkpoint)
        assert store.db.execute('SELECT count(*) FROM daily_character_exp WHERE character_id=?',(new,)).fetchone()[0]==3
        assert store.db.execute('SELECT count(*) FROM daily_character_exp WHERE character_id=?',(old,)).fetchone()[0]==2
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
        assert not roster.entry(store,'streamer_a')['public_visible']
        assert store._channel('streamer_b')['selected_character_id']==new
        assert before['characters'][-1]==tuple(store.db.execute('SELECT * FROM characters WHERE id=?',(other,)).fetchone())
        saved=aliases.load(store)
        assert aliases.canonical(saved,'streamer_a',f'character={old}&layout=chart')==('streamer_b',f'character={new}&layout=chart')
        assert aliases.canonical(saved,'streamer_b',f'character={old}')==('streamer_b',f'character={new}')
        assert aliases.canonical(saved,'streamer_a',f'character={alt}')==('streamer_b',f'character={alt}')
        assert merge.preview(store,'streamer_a','streamer_b',{old:new})['duplicate']
        with pytest.raises(sqlite3.IntegrityError,match='retired Twitch username'):
            change(store,'streamer_a',tracking_enabled=True)
        with pytest.raises(sqlite3.IntegrityError,match='append-only'):
            store.db.execute('DELETE FROM streamer_merges')


def test_missing_explicit_mapping_and_wrong_owner_are_refused(fixture):
    path,old,alt,new,other=fixture
    with Store(path) as store:
        for mapping in ({},{old:other},{other:new},{old:new,alt:new}):
            with pytest.raises(ValueError):merge.preview(store,'streamer_a','streamer_b',mapping)


def test_duplicate_raw_evidence_is_not_discarded(fixture):
    path,old,alt,new,_=fixture
    with Store(path) as store:
        sid=store._channel('streamer_a')['id']
        session=store.db.execute('SELECT id FROM sessions WHERE character_id=?',(old,)).fetchone()[0]
        store.db.execute('INSERT INTO diagnostic_runs VALUES(?,?,?,?,?,?,?)',('old_run',sid,old,session,utc(),'{}','{}'))
        store.db.execute('''INSERT INTO diagnostic_attempts(run_id,attempt_index,attempted_at,recorded_at,payload_json,session_id)
            VALUES(?,?,?,?,?,?)''',('old_run',1,utc(),utc(),'{}',session))
        with pytest.raises(ValueError,match='raw evidence'):merge.preview(store,'streamer_a','streamer_b',{old:new})
        assert store.db.execute('SELECT count(*) FROM diagnostic_attempts').fetchone()[0]==1


def test_nonduplicate_append_only_operator_audit_is_never_rewritten(fixture):
    path,old,alt,new,_=fixture
    with Store(path) as store:
        store.rename_character('streamer_a',alt,'CharC',reason='Synthetic operator rename')
        before=state(store)
        with pytest.raises(ValueError,match='operator audit'):merge.preview(store,'streamer_a','streamer_b',{old:new})
        assert state(store)==before


def test_overlapping_duplicate_dates_and_level_regression_are_refused(fixture):
    path,old,alt,new,_=fixture
    with Store(path) as store:
        store.db.execute('UPDATE character_level_guard SET level=92 WHERE character_id=?',(old,))
        with pytest.raises(ValueError,match='validated level'):merge.preview(store,'streamer_a','streamer_b',{old:new})
        store.db.execute('UPDATE character_level_guard SET level=93 WHERE character_id=?',(new,))
        stamp=utc();store.db.execute('UPDATE daily_character_exp SET utc_date=?,observed_at=? WHERE character_id=? AND utc_date=(SELECT MAX(utc_date) FROM daily_character_exp WHERE character_id=?)',
            (stamp[:10],stamp,old,old))
        with pytest.raises(ValueError,match='overlap'):merge.preview(store,'streamer_a','streamer_b',{old:new})


def test_drain_confirmation_and_stale_preview_are_required(fixture):
    path,old,alt,new,_=fixture
    with Store(path) as store:
        plan=merge.preview(store,'streamer_a','streamer_b',{old:new})
        store.db.execute("UPDATE streamer_runtime SET state='draining'")
        with pytest.raises(ValueError,match='drained'):merge.commit(store,plan)
        acknowledge(store)
        store.db.execute('UPDATE characters SET label=? WHERE id=?',('CharC',alt))
        with pytest.raises(ValueError,match='preview changed'):merge.commit(store,plan)


def test_failure_after_data_moves_rolls_back_all_changes(fixture):
    path,old,alt,new,_=fixture
    with Store(path) as store:
        for statement in aliases.DDL:store.db.execute(statement)
        store.db.execute("CREATE TRIGGER reject_merge BEFORE INSERT ON streamer_merges BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        before=state(store);plan=merge.preview(store,'streamer_a','streamer_b',{old:new})
        with pytest.raises(sqlite3.IntegrityError,match='synthetic failure'):merge.commit(store,plan)
        assert state(store)==before and aliases.load(store)=={}


def test_apply_drain_timeout_restores_settings_and_preserves_backup(fixture,tmp_path):
    path,old,alt,new,_=fixture
    with Store(path) as store:
        for login in ('streamer_a','streamer_b'):change(store,login,tracking_enabled=True)
    backup=tmp_path/'before.sqlite3'
    with pytest.raises(ValueError,match='did not confirm lane drain'):
        merge.apply(path,'streamer_a','streamer_b',{old:new},backup,timeout=0)
    with Store(path) as store,Store(backup,read_only=True) as saved:
        assert all(roster.entry(store,n)['tracking_enabled'] for n in ('streamer_a','streamer_b'))
        assert aliases.load(store)=={}
        assert store.db.execute('SELECT streamer_id FROM characters WHERE id=?',(alt,)).fetchone()[0]==store._channel('streamer_a')['id']
        assert saved.db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    with pytest.raises(FileExistsError):merge.apply(path,'streamer_a','streamer_b',{old:new},backup,timeout=0)


def test_apply_acknowledged_pause_resumes_only_destination(fixture,tmp_path,monkeypatch):
    path,old,alt,new,_=fixture
    tracking=merge._tracking
    def coordinator_ack(store,login,enabled):
        tracking(store,login,enabled);acknowledge(store)
    monkeypatch.setattr(merge,'_tracking',coordinator_ack)
    with Store(path) as store:
        for login in ('streamer_a','streamer_b'):change(store,login,tracking_enabled=True)
    result=merge.apply(path,'streamer_a','streamer_b',{old:new},tmp_path/'backup.sqlite3')
    assert result['saved']
    with Store(path) as store:
        assert not roster.entry(store,'streamer_a')['tracking_enabled']
        assert roster.entry(store,'streamer_b')['tracking_enabled']


def test_repeated_username_changes_flatten_previous_links(fixture):
    path,old,alt,new,other=fixture
    with Store(path) as store:
        merge.commit(store,merge.preview(store,'streamer_a','streamer_b',{old:new}))
        # No duplicate at the next destination: move the original IDs and their live histories intact.
        acknowledge(store)
        merge.commit(store,merge.preview(store,'streamer_b','streamer_c',{}))
        saved=aliases.load(store)
        assert aliases.previous(saved)=={'streamer_c':['streamer_b','streamer_a']}
        assert aliases.canonical(saved,'streamer_a',f'character={old}')==('streamer_c',f'character={new}')
        assert aliases.canonical(saved,'streamer_b',f'character={alt}')==('streamer_c',f'character={alt}')


def test_public_redirects_profiles_metadata_and_daily_history(fixture):
    from exp_tracker.server import create_server
    from tests.test_server import request
    from tests.test_character_profiles import get
    path,old,alt,new,other=fixture
    with Store(path) as store:merge.commit(store,merge.preview(store,'streamer_a','streamer_b',{old:new}))
    with create_server(path,port=0,public_only=True) as server:
        for route in (f'/api/players/streamer_a?character={old}',f'/stream/streamer_a?character={old}',
                      f'/live/overlay/streamer_a?character={old}&layout=chart'):
            status,headers,_=request((server,None),route)
            assert status==307
            assert 'streamer_b' in headers['Location'] and f'character={new}' in headers['Location']
        status,headers,_=request((server,None),f'/api/players/streamer_b?character={old}')
        assert status==307 and headers['Location']==f'/api/players/streamer_b?character={new}'
        status,_,body=request((server,None),'/api/players')
        assert status==200
        board=json.loads(body)
        assert 'streamer_a' not in {p['channel'] for p in board['players']}
        assert any(p['channel']=='streamer_b' for p in board['players']), (board,server.publisher.stats,server.publisher.failures)
        current=next(p for p in board['players'] if p['channel']=='streamer_b')
        assert current['previous_usernames']==['streamer_a']
        status,_,body=request((server,None),'/api/players?mode=characters')
        assert status==200
        rows=[r for r in json.loads(body)['characters'] if r['channel']=='streamer_b']
        assert {r['id'] for r in rows}=={new,alt}
        assert all(r['previous_usernames']==['streamer_a'] for r in rows)
        for character in (new,alt):
            status,profile=get(server,f'/api/players/streamer_b?character={character}')
            assert status==200
            assert profile['player']['previous_usernames']==['streamer_a']
            assert profile['view']['current']==(character==new)
        status,_,body=request((server,None),f'/api/players/streamer_b/daily-history?character={new}&days=365')
        assert status==200 and len(json.loads(body)['points'])==3
        assert request((server,None),f'/api/players/streamer_b?character={other}')[0]==404
