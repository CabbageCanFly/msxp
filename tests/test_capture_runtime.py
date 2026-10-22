from datetime import datetime,timedelta,timezone
import json

from exp_tracker.capture_runtime import CaptureRuntime,RuntimeReader,HEARTBEAT_SECONDS
from exp_tracker.store import Store
import pytest


def test_heartbeat_reports_runtime_expires_and_closes_without_history_writes(tmp_path):
    database=tmp_path/'history.sqlite3'
    with Store(database):pass
    before=database.read_bytes();path=tmp_path/'runtime.json';runtime=CaptureRuntime(path,database)
    try:
        runtime.coordinator_status['alpha']=dict(state='running',run_id='a',updated_at=datetime.now(timezone.utc).isoformat(),expected_completion_seconds=45)
        runtime.active_run_ids.add('a');runtime.publish()
        now=datetime.now(timezone.utc);reader=RuntimeReader(path,database)
        states,runs=reader.read(now)
        assert states==runtime.coordinator_status and runs=={'a'}
        assert reader.read(now+timedelta(seconds=HEARTBEAT_SECONDS+1))==({},set())
        assert reader.read(now-timedelta(minutes=1))==({},set())
        other=tmp_path/'other.sqlite3'
        with Store(other):pass
        assert RuntimeReader(path,other).read(now)==({},set())
    finally:runtime.server_close()
    assert reader.read(datetime.now(timezone.utc))==({},set())
    assert database.read_bytes()==before


def test_broken_or_missing_heartbeat_never_claims_active_capture(tmp_path):
    database=tmp_path/'history.sqlite3'
    with Store(database):pass
    path=tmp_path/'runtime.json';reader=RuntimeReader(path,database);now=datetime.now(timezone.utc)
    assert reader.read(now)==({},set())
    path.write_text('{broken')
    assert reader.read(now)==({},set())
    path.write_text(json.dumps(dict(format=1,database=reader.database,written_at=now.isoformat(),states=[],active_runs=[])))
    assert reader.read(now)==({},set())
    path.write_text(json.dumps(dict(format=1,database=reader.database,written_at=now.isoformat(),states=dict(alpha=dict(state='running')),active_runs=[])))
    assert reader.read(now)==({},set())


def test_runtime_writer_refuses_history_marker_and_unrelated_files(tmp_path):
    database=tmp_path/'history.sqlite3'
    with Store(database):pass
    marker=database.with_suffix(database.suffix+'.multi-alpha.json');marker.write_text('{}')
    unrelated=tmp_path/'unrelated.json';unrelated.write_text('{"keep":true}')
    for target in (database,marker,unrelated):
        before=target.read_bytes()
        with pytest.raises(ValueError):CaptureRuntime(target,database)
        assert target.read_bytes()==before


def test_one_malformed_channel_does_not_hide_other_capture_activity(tmp_path):
    database=tmp_path/'history.sqlite3'
    with Store(database):pass
    path=tmp_path/'runtime.json';reader=RuntimeReader(path,database);now=datetime.now(timezone.utc)
    good=dict(state='running',updated_at=now.isoformat(),expected_completion_seconds=45)
    path.write_text(json.dumps(dict(format=1,database=reader.database,written_at=now.isoformat(),
        states=dict(alpha=good,beta=dict(state='future_state'),gamma=dict(state='running')),active_runs=['a'])))
    assert reader.read(now)==(dict(alpha=good),{'a'})
