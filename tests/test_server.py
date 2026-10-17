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


def request(http_server, path="/api/streams/demo/state", method="GET"):
    httpd, _ = http_server
    wire = MemorySocket(f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode("ascii"))
    server.Handler(wire, ("127.0.0.1", 0), httpd)
    response = http.client.HTTPResponse(MemorySocket(wire.output.getvalue()))
    response.begin()
    return response.status, dict(response.getheaders()), response.read()


def state(http_server):
    status, _, body = request(http_server)
    assert status == 200
    return json.loads(body)


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
                       ("/static/leaderboard.js", "text/javascript"), ("/static/leaderboard.svg", "image/svg+xml")):
        code, headers, body = request(http_server, path)
        assert code == 200 and headers["Content-Type"].startswith(mime) and body
        assert headers["Cache-Control"] == "no-store"
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
def test_existing_real_ocr_replay_database_can_feed_overlay():
    path = Path(__file__).resolve().parents[1] / "artifacts/accounting-bridge.sqlite3"
    if not path.exists():
        pytest.skip("Private saved OCR replay database is intentionally absent")
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
