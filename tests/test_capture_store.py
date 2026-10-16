from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

from PIL import Image
import pytest

from exp_tracker import capture
from exp_tracker.glyphs import GlyphProfile, SYMBOLS
from exp_tracker.models import Reading, Recognition
from exp_tracker.store import Store
from exp_tracker.video import CaptureError


def test_capture_guard_database_and_worker_restart(tmp_path, monkeypatch, capsys):
    metrics = pytest.importorskip("exp_tracker.metrics")
    now = datetime.now(timezone.utc)
    path = tmp_path / "capture.sqlite3"
    video = tmp_path / "owned.mp4"
    video.write_bytes(b"owned-fixture")
    with Store(path) as store:
        store.add_channel("demo")
        char = store.add_character("demo", "Mage")
        store.select_character("demo", char)
        session_id = store.start_session("demo", at=now - timedelta(seconds=20))
    profile = GlyphProfile(9, {c: 6 for c in SYMBOLS}, {c: (1 << i,) for i, c in enumerate(SYMBOLS)})
    tick = 0

    class Session:
        source_bytes = 0
        def __init__(self, *_args, **_kwargs):
            pass
        def close(self):
            pass
        def frame(self, **_kwargs):
            if tick == 3:
                raise CaptureError("offline_or_unavailable")
            return SimpleNamespace(sequence=1, png=b"owned-synthetic-frame", image=lambda: Image.new("RGB", (100, 20)),
                                   arrived_monotonic=capture.time.monotonic(),
                                   received_at=(now - timedelta(seconds=10 - tick)).isoformat())

    def recognize(*_args, **_kwargs):
        exp = 1000 + tick * 500
        return Recognition("accepted", Reading(60, exp, exp / 100), .99,
                           raw={"exp": [dict(variant="pixel" if tick < 2 else "unrestricted-line",
                                             text=f"{exp:,}[{exp / 100:.2f}%]", confidence=.99)]})

    monkeypatch.setattr(capture.shutil, "which", lambda _name: "mock-ffmpeg")
    monkeypatch.setattr(capture.GlyphProfile, "load", lambda _path: profile)
    monkeypatch.setattr(capture, "VideoSession", Session)
    monkeypatch.setattr(capture, "recognize", recognize)
    monkeypatch.setattr(metrics, "ResourceMonitor", lambda: SimpleNamespace(snapshot=lambda: {}, close=lambda: None))
    args = ["--file", str(video), "--database", str(path), "--tracking-channel", "demo",
            "--glyph-profile", "owned-profile.json", "--count", "1"]
    # Each CLI call constructs a fresh worker and opens the persisted state.
    for tick in range(4):
        assert capture.main(args) == (2 if tick == 3 else 0)
        records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert records[0]["tracking"]["outcome"] == ("baseline" if tick == 0 else "accepted" if tick == 1 else "rejected")
        with Store(path) as restarted:
            state = restarted.state("demo")
            assert state["session"]["id"] == session_id
            assert state["last_trusted"]["current_exp"] == (1000 if tick == 0 else 1500)
            assert state["observed_session_exp"] == (0 if tick == 0 else 500)
            assert restarted.db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
            assert restarted.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == tick + 1
    with Store(path) as store:
        store.db.execute("""CREATE TRIGGER fail_insert BEFORE INSERT ON observations
                          BEGIN SELECT RAISE(ABORT, 'injected disk failure'); END""")
    tick = 4
    assert capture.main(args) == 1
    assert json.loads(capsys.readouterr().out.splitlines()[0])["status"] == "persistence_failed"
    with Store(path) as store:
        assert store.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 4
        assert store.state("demo")["last_trusted"]["current_exp"] == 1500


def test_database_capture_requires_profile_before_connecting(tmp_path, monkeypatch, capsys):
    pytest.importorskip("psutil")
    video = tmp_path / "owned.mp4"
    video.write_bytes(b"fixture")
    path = tmp_path / "tracker.sqlite3"
    with Store(path):
        pass
    monkeypatch.setattr(capture.shutil, "which", lambda _name: "mock-ffmpeg")
    monkeypatch.setattr(capture, "VideoSession", lambda *_a, **_kw: pytest.fail("must not capture"))
    assert capture.main(["--file", str(video), "--database", str(path), "--tracking-channel", "demo"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "setup_error"
