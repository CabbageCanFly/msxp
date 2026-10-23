from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import http.client
from io import BytesIO
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import threading

import pytest

from exp_tracker import server
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.glyphs import GlyphProfile, SYMBOLS
from exp_tracker.models import Reading, Recognition
from exp_tracker.schema import STATEMENTS, VERSION
from exp_tracker.store import Store
from tools.demo_tracking import main as demo


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "overlay demo #1.sqlite3"
    demo(path)
    return path


@pytest.fixture
def http_server(database, monkeypatch):
    with Store(database, read_only=True) as store:
        last = store.state("demo")["last_trusted"]
    clock = [datetime.fromisoformat(last["observed_at"]) + timedelta(seconds=5)]
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz)
    monkeypatch.setattr(server, "datetime", Clock)
    with server.create_server(database, port=0) as httpd:
        yield httpd, clock


class MemorySocket:
    """Exercise HTTP parsing/serialization without requiring local network access."""
    def __init__(self, data):
        self.input = BytesIO(data)
        self.output = BytesIO()

    def makefile(self, *_args):
        return self.input

    def sendall(self, data):
        self.output.write(data)


def request(http_server, path="/api/streams/demo/state", method="GET", origin=None):
    httpd, _ = http_server
    sent = f"Origin: {origin}\r\n" if origin else ""
    wire = MemorySocket(f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n{sent}Connection: close\r\n\r\n".encode("ascii"))
    server.Handler(wire, ("127.0.0.1", 0), httpd)
    response = http.client.HTTPResponse(MemorySocket(wire.output.getvalue()))
    response.begin()
    return response.status, dict(response.getheaders()), response.read()


def state(http_server):
    status, _, body = request(http_server)
    assert status == 200
    return json.loads(body)


@pytest.mark.parametrize('path', ['/dashboard/demo', '/dev/api/streams/demo/diagnostics'])
def test_persisted_dashboard_is_opt_in(http_server, path):
    assert request(http_server, path)[0] == 404


def test_persisted_dashboard_uses_only_selected_session_and_preserves_trusted_api(database):
    with Store(database) as store:
        trusted_before = store.state('demo')
        Diagnostics(store).begin('run', 'demo', dict(type='configuration', trusted=False, interval=15))
        Diagnostics(store).append('run', dict(type='attempt', index=1, trusted=False,
            attempted_at=datetime.now(timezone.utc).isoformat(), current=True, status='diagnostic_pair',
            source=dict(kind='twitch', channel='demo'), candidate=[98765, 25.0],
            neural=dict(text='98765[25.00%]', token='secret'), visual_level=51))
    with server.create_server(database, port=0, diagnostic_dashboard=True) as httpd:
        fixture = (httpd, None)
        status, headers, body = request(fixture, '/dev/api/streams/demo/diagnostics?file=secret')
        data = json.loads(body)
        assert status == 200 and headers['Cache-Control'] == 'no-store'
        assert headers['Content-Security-Policy'].startswith("default-src 'self'")
        assert data['observations'][0]['candidate']['exp'] == '98765' and not data['trusted']
        assert data['trusted_state']['last_trusted'] == trusted_before['last_trusted']
        assert data['selected_character']['id'] == trusted_before['selected_character_id']
        assert 'secret' not in body.decode()
        for path in ['/dashboard/demo', '/static/shadow.js', '/static/shadow.css']:
            assert request(fixture, path)[0] == 200
        assert request(fixture, '/dev/shadow')[0] == 404
        assert request(fixture, '/dev/api/streams/absent/diagnostics')[0] == 404
        assert request(fixture, '/dev/api/streams/bad!/diagnostics')[0] == 400
        assert request(fixture, '/dev/api/streams/demo/diagnostics', 'POST')[0] == 405
        trusted = json.loads(request(fixture)[2])
        assert trusted['last_trusted'] == trusted_before['last_trusted']
        assert trusted['observed_session_exp'] == trusted_before['observed_session_exp']
        with Store(database) as store:
            store.end_session('demo')
        empty = json.loads(request(fixture, '/dev/api/streams/demo/diagnostics')[2])
        assert empty['source_status'] == 'unconfigured' and empty['observations'] == []


def test_wrong_dashboard_url_identifies_database_mismatch(database):
    with server.create_server(database, port=0, diagnostic_dashboard=True) as httpd:
        for path in ('/dashboard/other_channel', '/dev/api/streams/other_channel/diagnostics'):
            status, headers, body = request((httpd, None), path)
            assert status == 404 and headers['Cache-Control'] == 'no-store'
            value = json.loads(body)
            assert value['configured_channels'] == ['demo']
            assert 'Check --db and the dashboard URL' in value['message']
            assert 'does not start capture' in value['message']


def test_server_only_startup_prints_real_urls_and_does_not_capture(database, monkeypatch, capsys):
    def stop(self):
        raise KeyboardInterrupt
    monkeypatch.setattr(server.ThreadingHTTPServer, 'serve_forever', stop)
    assert server.main(['--db', str(database), '--port', '0', '--diagnostic-dashboard']) == 0
    output = capsys.readouterr().out
    assert 'capture is NOT started' in output and '/dashboard/demo' in output
    assert '/dashboard/CHANNEL' not in output


def test_public_only_startup_prints_only_public_urls(database, monkeypatch, capsys):
    def stop(self):
        raise KeyboardInterrupt
    monkeypatch.setattr(server.ThreadingHTTPServer, 'serve_forever', stop)
    assert server.main(['--db', str(database), '--port', '0', '--public-only']) == 0
    output = capsys.readouterr().out
    assert '/stream/demo' in output and '/live/overlay/demo' in output and '/dashboard/' not in output
    assert server.main(['--db', str(database), '--port', '0', '--public-only', '--diagnostic-dashboard']) == 1
    assert 'public-only' in capsys.readouterr().err


def test_api_matches_real_store_and_is_not_cached(database, http_server):
    result = state(http_server)
    with Store(database, read_only=True) as store:
        expected = store.state("demo", as_of=http_server[1][0])
    assert all(result[key] == value for key, value in expected.items())
    assert result["selected_character"] == {"id": 1, "label": "Synthetic character"}
    assert result["last_trusted"]["current_exp"] == 1500
    assert result["last_trusted"]["percentage_bp"] == 1500
    assert result["observed_session_exp"] == 500 and result["bridged_session_exp"] == 0
    assert result["age_seconds"] == 5 and not result["stale"]
    assert result["stale_after_seconds"] == 120
    assert datetime.fromisoformat(result["served_at"]) == http_server[1][0]
    status, headers, _ = request(http_server, "/api/streams/DEMO/state")
    assert status == 200 and headers["Cache-Control"] == "no-store"
    assert "diagnostic_json" not in result and "profile_hash" not in result["last_trusted"]


def test_actual_loopback_http_smoke(http_server):
    httpd, _ = http_server
    worker = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": .01})
    worker.start()
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=2)
    try:
        try:
            connection.request("GET", "/api/streams/demo/state")
        except PermissionError as error:
            if getattr(error, "winerror", None) == 10013:
                pytest.skip("Session policy blocks loopback client sockets; HTTP handler tests run in memory")
            raise
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["last_trusted"]["current_exp"] == 1500
    finally:
        connection.close()
        httpd.shutdown()
        worker.join(timeout=5)


def test_freshness_advances_without_worker_or_database_changes(database, http_server):
    before = state(http_server)
    http_server[1][0] += timedelta(seconds=115)
    assert state(http_server)["age_seconds"] == 120 and not state(http_server)["stale"]
    http_server[1][0] += timedelta(seconds=1)
    after = state(http_server)
    assert after["stale"] and after["age_seconds"] == 121
    assert after["status"] == "paused" and after["reason"] == "stale"
    assert after["last_trusted"] == before["last_trusted"]
    assert after["observed_session_exp"] == 500
    with Store(database, read_only=True) as store:
        assert store.db.execute("SELECT status FROM tracking_state").fetchone()[0] == "tracking"
        assert store.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 2


@pytest.mark.parametrize("failure,hard", [("unreadable", False), ("paused", True), ("offline", True)])
def test_failures_preserve_api_values_and_expose_pause_reason(database, http_server, failure, hard):
    before = state(http_server)
    with Store(database) as store:
        store.ingest("demo", "failed", http_server[1][0], Recognition(failure),
                     profile=GlyphProfile(9, {c: 6 for c in SYMBOLS}, {c: (1 << i,) for i, c in enumerate(SYMBOLS)}),
                     session_id=before["session"]["id"])
    after = state(http_server)
    assert after["last_trusted"] == before["last_trusted"]
    assert after["status"] == ("offline" if failure == "offline" else "paused")
    assert after["reason"] == failure and after["continuity_broken"] == hard
    assert after["last_event_at"] == http_server[1][0].isoformat(timespec="microseconds")
    assert not after["stale"] and after["observed_session_exp"] == 500


def test_missing_selection_session_and_reading(database, http_server):
    with Store(database) as store:
        store.add_channel("empty")
    status, _, body = request(http_server, "/api/streams/empty/state")
    value = json.loads(body)
    assert status == 200 and value["selected_character"] is None
    assert value["session"] is None and value["last_trusted"] is None
    assert value["status"] == "unconfigured" and value["stale"]
    with Store(database) as store:
        character = store.add_character("empty", "Selected character")
        store.select_character("empty", character)
    assert json.loads(request(http_server, "/api/streams/empty/state")[2])["session"] is None
    with Store(database) as store:
        store.start_session("empty")
    value = json.loads(request(http_server, "/api/streams/empty/state")[2])
    assert value["status"] == "waiting" and value["last_trusted"] is None
    assert value["age_seconds"] is None and value["observed_session_exp"] == 0


@pytest.mark.parametrize("path,status,error", [
    ("/api/streams/unknown/state", 404, "unknown_channel"),
    ("/api/streams//state", 400, "invalid_channel"),
    ("/api/streams/%27OR%201=1/state", 400, "invalid_channel"),
    ("/api/streams/" + "a" * 26 + "/state", 400, "invalid_channel"),
    ("/api/streams/demo", 404, "not_found"),
    ("/overlay/%3Cscript%3E", 400, "invalid_channel"),
    ("/static/../store.py", 404, "not_found"),
    ("/database.sqlite3", 404, "not_found"),
])
def test_bad_paths_and_channels(http_server, path, status, error):
    code, _, body = request(http_server, path)
    assert code == status and json.loads(body) == {"error": error}


def test_http_and_connection_are_read_only(database, http_server):
    before = state(http_server)
    assert http_server[0].server_address[0] == "127.0.0.1"
    for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
        code, headers, body = request(http_server, method=method)
        assert code == 405 and json.loads(body) == {"error": "read_only"}
        assert headers["Allow"] == "GET"
    assert state(http_server) == before
    with Store(database, read_only=True) as reader:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.db.execute("DELETE FROM observations")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.add_channel("forbidden")
        assert reader.db.total_changes == 0


@pytest.mark.parametrize("version", [0, 1, VERSION + 1])
def test_reader_refuses_to_initialize_or_migrate_schema(tmp_path, version):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        for statement in STATEMENTS:
            db.execute(statement)
        db.execute(f"PRAGMA user_version={version}")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="schema version"):
        server.create_server(path, port=0)
    assert path.read_bytes() == before
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == version
        assert "missing_observations" not in [row[1] for row in db.execute("PRAGMA table_info(observations)")]


def test_missing_database_is_not_created(tmp_path, capsys):
    path = tmp_path / "missing.sqlite3"
    assert server.main(["--db", str(path), "--port", "0"]) == 1
    assert "Cannot start" in capsys.readouterr().err
    assert not path.exists()


def test_unavailable_database_returns_503(database, http_server):
    with sqlite3.connect(database) as db:
        db.execute(f"PRAGMA user_version={VERSION + 1}")
    status, _, body = request(http_server)
    assert status == 503 and json.loads(body) == {"error": "database_unavailable"}


def test_overlay_assets_are_served_from_allowlist(http_server):
    for path, mime in (("/overlay/demo", "text/html"), ("/static/overlay.css", "text/css"), ("/static/overlay.js", "text/javascript")):
        code, headers, body = request(http_server, path)
        assert code == 200 and headers["Content-Type"].startswith(mime) and body
        assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert b"background: transparent" in request(http_server, "/static/overlay.css")[2]
    assert b"fetch(" in request(http_server, "/static/overlay.js")[2]


def test_simulated_leaderboard_assets_keep_existing_http_security(database, http_server, monkeypatch):
    before = database.read_bytes()
    def forbidden(*args, **kwargs):
        pytest.fail("The simulated leaderboard must not read or write tracking state")
    monkeypatch.setattr(server, "Store", forbidden)
    for path, mime in (("/demo/leaderboard", "text/html"), ("/static/leaderboard.css", "text/css"),
                       ("/static/leaderboard.js", "text/javascript"), ("/static/leaderboard.svg", "image/svg+xml"),
                       ("/static/fonts/fredoka-latin.woff2", "font/woff2"), ("/static/fonts/nunito-latin.woff2", "font/woff2"),
                       ("/static/steely.png", "image/png"), ("/static/sleepywood.webp", "image/webp"),
                       ("/static/sleepywood-forest.webp", "image/webp"), ("/static/mobs/blue-snail-move.gif", "image/gif")):
        code, headers, body = request(http_server, path)
        assert code == 200 and headers["Content-Type"].startswith(mime) and body
        assert headers["Cache-Control"] == ("public, max-age=86400" if path in server.CACHED_ASSETS else "no-store")
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert "default-src 'self'" in headers["Content-Security-Policy"]
        assert "Access-Control-Allow-Origin" not in headers
    html = request(http_server, "/demo/leaderboard")[2]
    assert b"SIMULATED DEMO" in html and b"No real stream or tracking data" in html
    assert b"http://" not in html and b"https://" not in html
    assert database.read_bytes() == before


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_leaderboard_has_no_write_endpoint(http_server, method):
    code, headers, body = request(http_server, "/demo/leaderboard", method)
    assert code == 405 and json.loads(body) == {"error": "read_only"}
    assert headers["Allow"] == "GET"


@pytest.mark.parametrize("path", ["/demo/leaderboard/other", "/static/leaderboard.html", "/demo/../private/log.jsonl"])
def test_leaderboard_does_not_expand_file_serving(http_server, path):
    assert request(http_server, path)[0] == 404


def test_leaderboard_frontend_logic():
    node = shutil.which("node")
    if not node:
        pytest.skip("Optional Node.js frontend tests")
    subprocess.run([node, "--test", "tools/leaderboard.test.mjs"], check=True, timeout=20)


@pytest.mark.parametrize('path', ['/dev/shadow', '/dev/api/shadow', '/static/shadow.js', '/static/shadow.css'])
def test_shadow_routes_are_opt_in(http_server, path):
    assert request(http_server, path)[0] == 404


def test_shadow_api_is_sanitized_read_only_and_cannot_select_arbitrary_files(database, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    log = tmp_path / 'private/trial.jsonl'
    log.parent.mkdir()
    row = dict(type='attempt', index=1, status='capture_failed', reasons=['access_denied'],
               attempted_at='2026-01-01T00:00:00Z', source={'kind':'twitch', 'channel':'synthetic', 'url':'secret'})
    log.write_text(json.dumps(row)+'\n')
    before = database.read_bytes(), log.read_bytes()
    with server.create_server(database, port=0, shadow_log=log) as httpd:
        def forbidden(*args, **kwargs):
            pytest.fail('Diagnostic HTTP requests must not open Store')
        monkeypatch.setattr(server, 'Store', forbidden)
        code, headers, body = request((httpd, None), '/dev/api/shadow?path=outside.jsonl')
        assert code == 200 and json.loads(body)['source_status'] == 'capture_failed'
        assert b'secret' not in body and b'outside.jsonl' not in body
        assert headers['Cache-Control'] == 'no-store' and 'default-src' in headers['Content-Security-Policy']
        for path in ['/dev/shadow', '/static/shadow.js', '/static/shadow.css']:
            assert request((httpd, None), path)[0] == 200
        assert b'UNVERIFIED' in request((httpd, None), '/dev/shadow')[2]
        for path in ['/dev/shadow/raw', '/dev/shadow/crop.png', '/private/trial.jsonl']:
            assert request((httpd, None), path)[0] == 404
        assert request((httpd, None), '/dev/api/shadow', 'POST')[0] == 405
    assert (database.read_bytes(), log.read_bytes()) == before


def test_shadow_frontend_logic():
    node = shutil.which('node')
    if not node:
        pytest.skip('Optional Node.js frontend tests')
    subprocess.run([node, '--test', 'tools/shadow.test.mjs'], check=True, timeout=20)


def test_stream_directory_frontend_logic():
    node = shutil.which('node')
    if not node: pytest.skip('Optional Node.js frontend tests')
    subprocess.run([node,'--test','tools/streams.test.mjs'],check=True,timeout=20)


@pytest.mark.parametrize('script', ['product', 'admin-invalidations', 'admin-streamers', 'admin-time', 'obs-client'])
def test_site_and_admin_frontend_logic(script):
    node = shutil.which('node')
    if not node: pytest.skip('Optional Node.js frontend tests')
    subprocess.run([node,'--test',f'tools/{script}.test.mjs'],check=True,timeout=20)


def test_directory_opt_in_cache_freshness_and_assignment_isolation(database,monkeypatch):
    with server.create_server(database,port=0) as httpd:
        for path in ('/streams','/dev/api/streams','/static/streams.js'):
            assert request((httpd,None),path)[0]==404
    with Store(database) as store:
        for name in ('alpha','beta','waiting'):
            store.add_channel(name)
            char=store.add_character(name,f'{name} explicitly selected')
            store.select_character(name,char);store.start_session(name)
        d=Diagnostics(store)
        for name in ('alpha','beta'):
            d.begin(name,name,dict(type='configuration',trusted=False,interval=15))
            d.append(name,dict(type='attempt',index=1,trusted=False,current=True,status='malformed_or_unavailable',
                attempted_at='2026-01-01T00:00:00Z',received_at='2026-01-01T00:00:00Z',source=dict(kind='twitch',channel=name),
                neural=dict(text='5,031[33,05%]'),visual_level=64,visual_status='available',localization=dict(count=1),
                secret_url='https://private/playback?token=secret'))
    before=database.read_bytes()
    with server.create_server(database,port=0,diagnostic_dashboard=True) as httpd:
        calls=[];original=Diagnostics._snapshot
        def count(self,channel,**kwargs):
            calls.append(channel);return original(self,channel,**kwargs)
        monkeypatch.setattr(Diagnostics,'_snapshot',count)
        code,headers,body=request((httpd,None),'/dev/api/streams?path=private.jsonl')
        assert code==200 and b'secret' not in body and b'private.jsonl' not in body
        result=json.loads(body);rows={r['channel']:r for r in result['streams']}
        assert rows['alpha']['percentage']['percentage']=='33.05'
        assert rows['alpha']['full_exp'] is None
        assert rows['waiting']['source_status']=='waiting' and rows['waiting']['percentage'] is None
        assert rows['alpha']['stale'] and rows['alpha']['run_status']=='unfinished'
        assert headers['Cache-Control']=='no-store' and 'default-src' in headers['Content-Security-Policy']
        first=len(calls);request((httpd,None),'/dev/api/streams');assert len(calls)==first
        httpd.active_run_ids.add('alpha')
        active=json.loads(request((httpd,None),'/dev/api/streams')[2])
        assert next(r for r in active['streams'] if r['channel']=='alpha')['run_status']=='active'
        assert request((httpd,None),'/streams')[0]==request((httpd,None),'/static/streams.js')[0]==200
        assert request((httpd,None),'/dev/api/streams','POST')[0]==405
        assert request((httpd,None),'/dashboard/beta')[0]==200
        assert request((httpd,None),'/dashboard/no_such_channel')[0]==404
    assert database.read_bytes()==before
    with Store(database) as store:
        char=store.add_character('alpha','Explicit switch')
        store.select_character('alpha',char);store.start_session('alpha')
    with server.create_server(database,port=0,diagnostic_dashboard=True) as httpd:
        rows=json.loads(request((httpd,None),'/dev/api/streams')[2])['streams']
        a=next(r for r in rows if r['channel']=='alpha')
        assert a['percentage'] is None and a['character']['label']=='Explicit switch'


def test_shadow_http_follows_completed_appends_without_touching_log(database, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    log = tmp_path / 'artifacts/growing.jsonl'
    log.parent.mkdir()
    with server.create_server(database, port=0, shadow_log=log) as httpd:
        def snapshot():
            return json.loads(request((httpd, None), '/dev/api/shadow')[2])
        assert snapshot()['log_status'] == 'missing' and not log.exists()
        row = dict(type='attempt', index=1, status='diagnostic_pair', candidate=[0,0.0],
                   attempted_at='2026-01-01T00:00:00Z')
        log.write_text(json.dumps(row))
        assert snapshot()['incomplete_tail'] and not snapshot()['observations']
        with log.open('a') as writer:
            writer.write('\n')
        assert snapshot()['observations'][0]['candidate'] == {'exp':'0','percentage':'0.00'}
        with log.open('a') as writer:
            writer.write(json.dumps({**row,'index':2,'status':'capture_failed','candidate':None,
                                    'reasons':['offline_or_unavailable']})+'\n')
        result = snapshot()
        assert len(result['observations']) == 2 and result['source_status'] == 'offline_or_unavailable'


def test_api_reads_committed_snapshot_while_guarded_observation_is_written(database, http_server):
    before = state(http_server)
    writing, release = threading.Event(), threading.Event()
    def write():
        with Store(database) as store:
            def hold():
                writing.set()
                assert release.wait(timeout=5)
                return 0
            store.db.create_function("hold_write", 0, hold)
            store.db.execute("""CREATE TRIGGER hold_state BEFORE UPDATE ON tracking_state
                                BEGIN SELECT hold_write(); END""")
            profile = GlyphProfile(9, {c: 6 for c in SYMBOLS}, {c: (1 << i,) for i, c in enumerate(SYMBOLS)})
            result = Recognition("accepted", Reading(60, 2000, 20), .99,
                                 raw={"exp": [dict(variant="pixel", text="2,000[20.00%]", confidence=.99)]})
            try:
                return store.ingest("demo", "concurrent", http_server[1][0], result,
                                    profile=profile, session_id=before["session"]["id"])
            finally:
                store.db.execute("DROP TRIGGER hold_state")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(write)
        try:
            assert writing.wait(timeout=2)
            assert state(http_server) == before  # No lock wait or partially inserted observation.
        finally:
            release.set()
        assert future.result(timeout=2)["gained_exp"] == 500
    after = state(http_server)
    assert after["last_trusted"]["current_exp"] == 2000
    assert after["observed_session_exp"] == 1000 and after["age_seconds"] == 0


def test_animated_demo_uses_real_guard_and_appends_without_rewriting(tmp_path, monkeypatch, capsys):
    from tools import demo_tracking
    clock = [datetime.now(timezone.utc)]
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz)
    monkeypatch.setattr(demo_tracking, "datetime", Clock)
    monkeypatch.setattr(demo_tracking.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + timedelta(seconds=seconds)))
    path = tmp_path / "animated.sqlite3"
    demo_tracking.main(path, animate=True)
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["status"] for row in records] == ["tracking", "tracking", "paused", "tracking", "offline", "tracking", "tracking"]
    assert records[-1]["observed_session_exp"] == 1600 and records[-1]["bridged_session_exp"] == 600
    assert records[4]["last_trusted"] == records[3]["last_trusted"]
    with Store(path, read_only=True) as store:
        assert store.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 7
    with pytest.raises(ValueError, match="new database"):
        demo_tracking.main(path, animate=True)


@pytest.mark.parametrize("interval", [0, float("nan"), 61])
def test_animated_demo_rejects_invalid_interval_before_creating_database(tmp_path, interval):
    path = tmp_path / "invalid.sqlite3"
    with pytest.raises(ValueError, match="interval"):
        demo(path, animate=True, interval=interval)
    assert not path.exists()


def test_overlay_renderer_regressions():
    node = shutil.which("node")
    if not node:
        pytest.skip("Optional Node.js renderer checks; Python HTTP tests still run")
    subprocess.run([node, "--test", "tools/overlay.test.mjs"], check=True,
                   cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=15)


@pytest.mark.samples
def test_existing_real_ocr_replay_database_can_feed_overlay(tmp_path):
    path = Path(__file__).resolve().parents[1] / "artifacts/accounting-bridge.sqlite3"
    if not path.exists():
        pytest.skip("Private saved OCR replay database is intentionally absent")
    # Historical evidence stays unchanged; migrate a snapshot, as a user would a working copy.
    working = tmp_path / 'real-replay.sqlite3'
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as original:
        with sqlite3.connect(working) as copied:
            original.backup(copied)
    with Store(working):
        pass
    path = working
    with server.create_server(path, port=0) as httpd:
        status, _, body = request((httpd, None), "/api/streams/telfer1/state")
    assert status == 200
    result = json.loads(body)
    assert result["channel"] == "telfer1"
    assert result["last_trusted"]["level"] == 60
    assert result["last_trusted"]["current_exp"] == 879217
    assert result["last_trusted"]["percentage_bp"] == 7266
    assert result["observed_session_exp"] == 6121 and result["bridged_session_exp"] == 1592
    assert result["status"] == "paused" and result["stale"]


def test_populated_statistics_are_read_from_guarded_history_not_api_constants(tmp_path, monkeypatch):
    from tools.demo_statistics import main as statistics_demo
    end = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return end.astimezone(tz)
    monkeypatch.setattr(server, "datetime", Clock)
    path = tmp_path / "statistics.sqlite3"
    seeded = statistics_demo(path, as_of=end)
    with server.create_server(path, port=0) as httpd:
        result = state((httpd, None))
    assert result["statistics"] == seeded["statistics"]
    assert result["statistics"]["last_5_min"]["exp"] == 20000
    assert result["statistics"]["exp_per_hour_30m"]["exp_per_hour"] == 240000
    assert result["statistics"]["to_next_level"]["seconds"] == 11400
    assert "ranking" not in result


def test_cors_allows_only_configured_origins_on_every_response(database, capsys):
    pages = "https://msxp.pages.dev"
    with server.create_server(database, port=0, public_only=True, cors_origins=[pages]) as httpd:
        fixture = (httpd, None)
        for path, method, status in [("/api/players", "GET", 200), ("/api/players/missing", "GET", 404),
                ("/api/players/bad!", "GET", 400), ("/dev/api/streams", "GET", 404), ("/api/players", "POST", 405)]:
            got, headers, _ = request(fixture, path, method, origin=pages)
            assert got == status and headers["Access-Control-Allow-Origin"] == pages and headers["Vary"] == "Origin", path
            assert headers["Access-Control-Expose-Headers"] == "Retry-After" and headers["Cache-Control"] == "no-store"
        for origin in (None, "https://evil.example", "http://msxp.pages.dev", "https://msxp.pages.dev.evil.example", "null"):
            _, headers, _ = request(fixture, "/api/players", origin=origin)
            assert "Access-Control-Allow-Origin" not in headers and headers["Vary"] == "Origin", origin
    with server.create_server(database, port=0, public_only=True) as httpd:  # Not configured: no CORS headers at all.
        assert not {"Access-Control-Allow-Origin", "Vary"} & set(request((httpd, None), "/api/players", origin=pages)[1])
    for bad in ("*", "https://msxp.pages.dev/", "http://msxp.pages.dev", "https://*.pages.dev", "https://MSXP.pages.dev", "null"):
        with pytest.raises(ValueError, match="CORS"):
            server.create_server(database, port=0, cors_origins=[bad])
    assert server.main(["--db", str(database), "--port", "0", "--public-only", "--cors-origin", "*"]) == 1
    assert "CORS origins" in capsys.readouterr().err
