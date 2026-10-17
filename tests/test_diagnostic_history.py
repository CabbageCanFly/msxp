from datetime import timedelta
import json
import sqlite3

import pytest

from exp_tracker.diagnostics import Diagnostics
from exp_tracker.schema import STATEMENTS,MIGRATION_2,MIGRATION_3
from exp_tracker.store import Store
from exp_tracker.server import create_server
from tests.test_server import request
from tests.test_diagnostics import NOW,CONFIG,attempt,configured


def config(run,previous=None,**changes):
    value={**CONFIG,'run_id':run,'count':60,'source_kind':'twitch','coordinator':'multi_alpha_v1',
        'coordinator_instance':'a'*32,'source_identity':'b'*64,'requirements_sha256':'c'*64,
        'timing_mode':'real','start_reason':'scheduled_rotation' if previous else 'process_start','previous_run_id':previous}
    value.update(changes);return value


def fill(diagnostic,run,offset=0,count=60):
    for i in range(1,count+1):
        value=attempt(i);when=(NOW+timedelta(seconds=(offset+i)*15)).isoformat()
        value.update(received_at=when,attempted_at=when,neural=dict(text=f'[{25+(offset+i)/100:.2f}%]'),
            candidate=None,visual_level=64,visual_status='available',status='diagnostic_percentage_only',
            neural_level=None,localization=dict(count=1))
        diagnostic.append(run,value)


def rotate(diagnostic,previous,following):
    return diagnostic.rotate(previous,following,'alpha',dict(type='summary',trusted=False,attempts=60,
        interrupted=False,completion_reason='scheduled_rotation',next_run_id=following),config(following,previous))


def test_history_keyset_sessions_runs_time_ranges_and_isolation(configured):
    with Store(configured) as store:
        diagnostic=Diagnostics(store);diagnostic.begin('a','alpha',config('a'));fill(diagnostic,'a')
        rotate(diagnostic,'a','b');fill(diagnostic,'b',60)
        rotate(diagnostic,'b','c');fill(diagnostic,'c',120,count=5)
        session=store.state('alpha')['session']['id']
        now=NOW+timedelta(seconds=125*15)
        snap=diagnostic.snapshot('alpha',now=now)
        assert len(snap['observations'])==120 and snap['truncated']
        assert snap['percentage_progress']['current_segment']['readings']==120
        assert snap['percentage_progress']['current_segment']['run_ids']==['a','b','c']
        next_page=diagnostic.snapshot('alpha',session_id=session,before=snap['history']['next_before'],now=now)
        assert len(next_page['observations'])==5 and not next_page['truncated']
        assert not ({r['event_id'] for r in snap['observations']} & {r['event_id'] for r in next_page['observations']})
        assert next_page['historical'] and next_page['percentage_progress']['current_pace'] is None
        narrow=diagnostic.snapshot('alpha',session_id=session,start=(NOW+timedelta(seconds=300)).isoformat(),end=(NOW+timedelta(seconds=345)).isoformat(),now=now)
        assert [r['index'] for r in narrow['observations']]==[20,21,22]
        runs=diagnostic.runs('alpha',session,limit=2)
        assert [r['run_id'] for r in runs['runs']]==['c','b']
        assert [r['run_id'] for r in diagnostic.runs('alpha',session,before=runs['next_before'])['runs']]==['a']
        with pytest.raises(ValueError): diagnostic.snapshot('alpha',run_id='missing')
        old_payloads=[r[0] for r in store.db.execute('SELECT payload_json FROM diagnostic_attempts ORDER BY id')]
        store.end_session('alpha',at=now+timedelta(seconds=1))
        other=store.add_character('alpha','Other character');store.select_character('alpha',other)
        new_session=store.start_session('alpha',at=now+timedelta(seconds=2))
        assert new_session!=session and not diagnostic.snapshot('alpha',now=now)['observations']
        archived=diagnostic.snapshot('alpha',session_id=session,now=now)
        assert archived['selected_character']['id']!=other and len(archived['observations'])==120
        assert [r['id'] for r in diagnostic.sessions('alpha')['sessions']]==[new_session,session]
        store.add_channel('beta');cid=store.add_character('beta','Beta');store.select_character('beta',cid);store.start_session('beta',at=NOW)
        with pytest.raises(ValueError):diagnostic.snapshot('beta',session_id=session)
        with pytest.raises(ValueError):diagnostic.runs('beta',session)
        assert old_payloads==[r[0] for r in store.db.execute('SELECT payload_json FROM diagnostic_attempts ORDER BY id')]
        assert not store.db.execute('SELECT 1 FROM observations').fetchone()


def test_rotation_transaction_rolls_back_summary_on_incompatible_successor(configured):
    with Store(configured) as store:
        diagnostic=Diagnostics(store);diagnostic.begin('a','alpha',config('a'));fill(diagnostic,'a')
        with pytest.raises(ValueError,match='rotation'):
            diagnostic.rotate('a','b','alpha',dict(type='summary',trusted=False,attempts=60,interrupted=False,
                completion_reason='scheduled_rotation',next_run_id='b'),config('b','a',source_identity='d'*64))
        assert store.db.execute('SELECT summary_json FROM diagnostic_runs WHERE run_id="a"').fetchone()[0] is None
        assert not store.db.execute('SELECT 1 FROM diagnostic_runs WHERE run_id="b"').fetchone()
        rotate(diagnostic,'a','b')
        with pytest.raises(ValueError): diagnostic.append('a',attempt(1))


def test_simulated_header_cannot_produce_pace_even_if_attempt_flag_is_missing(configured):
    with Store(configured) as store:
        diagnostic=Diagnostics(store);diagnostic.begin('simulated','alpha',config('simulated',timing_mode='simulated'))
        fill(diagnostic,'simulated',count=3)
        snap=diagnostic.snapshot('alpha',now=NOW+timedelta(seconds=45))
        assert snap['percentage_progress']['current_pace'] is None
        assert snap['percentage_progress']['comparisons'][-1]['reason']=='simulated_timing_not_real_progress'
        assert all(r['timing_mode']=='simulated' for r in snap['observations'])


def test_v3_read_compatibility_and_v4_additive_migration_preserve_payloads(tmp_path):
    path=tmp_path/'legacy.sqlite3'
    with sqlite3.connect(path) as db:
        for sql in (*STATEMENTS,*MIGRATION_2,*MIGRATION_3):db.execute(sql)
        db.execute('PRAGMA user_version=3')
        db.execute("INSERT INTO streamers(id,login,selected_character_id) VALUES(1,'alpha',1)")
        db.execute("INSERT INTO characters VALUES(1,1,'Legacy')")
        db.execute('INSERT INTO sessions(id,streamer_id,character_id,started_at) VALUES(1,1,1,?)',(NOW.isoformat(),))
        db.execute('INSERT INTO diagnostic_runs VALUES(?,?,?,?,?,?,?)',('legacy',1,1,1,NOW.isoformat(),json.dumps(CONFIG),None))
        raw=json.dumps(attempt(),indent=2)
        db.execute('INSERT INTO diagnostic_attempts(run_id,attempt_index,attempted_at,recorded_at,payload_json) VALUES(?,?,?,?,?)',('legacy',1,NOW.isoformat(),NOW.isoformat(),raw))
    before=path.read_bytes()
    with Store(path,read_only=True) as store:
        assert len(Diagnostics(store).snapshot('alpha')['observations'])==1
        assert store.schema_version==3
    assert before==path.read_bytes()
    with Store(path) as store:
        row=store.db.execute('SELECT payload_json,session_id FROM diagnostic_attempts').fetchone()
        assert row[0]==raw and row[1]==1 and store.schema_version==4
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
        assert len(Diagnostics(store).snapshot('alpha')['observations'])==1


@pytest.mark.parametrize('kwargs',[
    {'session_id':-1},{'before':0},{'before':2**63},{'start':'not-time'},
    {'start':NOW.isoformat(),'end':(NOW-timedelta(seconds=1)).isoformat()},
    {'start':NOW.isoformat(),'end':(NOW+timedelta(days=32)).isoformat()}])
def test_invalid_history_queries_are_rejected(configured,kwargs):
    with Store(configured,read_only=True) as store:
        with pytest.raises(ValueError):Diagnostics(store).snapshot('alpha',**kwargs)


def test_history_http_status_security_and_coordinator_activity(configured):
    with Store(configured) as store:
        diagnostic=Diagnostics(store)
        diagnostic.begin('a','alpha',{**CONFIG,'source_kind':'file','source_identity':'private/secret',
            'coordinator_instance':'https://signed-secret.invalid','start_reason':'private/path'})
        fill(diagnostic,'a',count=3)
        session=store.state('alpha')['session']['id']
    before=configured.read_bytes()
    with create_server(configured,port=0,diagnostic_dashboard=True) as server:
        fixture=(server,None)
        endpoint='/dev/api/streams/alpha'
        assert request(fixture,endpoint+'/sessions')[0]==200
        assert request(fixture,endpoint+f'/runs?session={session}')[0]==200
        for query in ('session=-1','session=999','before=0','before=1&before=2','start=not-time','run=not-found'):
            assert request(fixture,endpoint+'/diagnostics?'+query)[0]==400
        status,_,body=request(fixture,endpoint+f'/diagnostics?session={session}&start=2026-01-01T00:00:15Z&end=2026-01-01T00:00:45Z')
        value=json.loads(body)
        assert status==200 and len(value['observations'])==2
        assert value['historical'] and value['operation']['state']=='historical_session'
        assert 'signed-secret' not in body.decode() and 'private/' not in body.decode()
        value=json.loads(request(fixture,endpoint+'/diagnostics')[2])
        assert value['operation']['state']=='previous_unfinished_run'
        server.coordinator_status['alpha']=dict(state='waiting',run_id='a',updated_at=NOW.isoformat(),next_due_at=NOW.isoformat())
        value=json.loads(request(fixture,'/dev/api/streams')[2])
        assert value['streams'][0]['source_kind']=='file'
        assert value['streams'][0]['operation']['state']=='capture_delayed'
        server.coordinator_status.clear()
        assert json.loads(request(fixture,'/dev/api/streams')[2])['streams'][0]['operation']['state']=='previous_unfinished_run'
    assert configured.read_bytes()==before
