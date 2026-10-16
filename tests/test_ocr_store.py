"""Real OCR and SQLite on private saved evidence; no capture network requests."""

from dataclasses import asdict
from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
import subprocess

from PIL import Image
import pytest

from exp_tracker.glyphs import GlyphProfile
from exp_tracker.models import Region
from exp_tracker.recognition import recognize
from exp_tracker.store import Store
from tools.replay_capture_crops import read_records, recognize_saved, restore_frame


ROOT = Path(__file__).resolve().parents[1]
TRIAL = "green-test-20261015-215403"
pytestmark = [pytest.mark.samples, pytest.mark.ocr]


@pytest.fixture(scope="module")
def saved():
    records = ROOT / f"artifacts/{TRIAL}.jsonl"
    profile = ROOT / "private/ocr-evaluation/glyph-profile-green-experimental.json"
    if not records.exists() or not profile.exists():
        pytest.skip("Private captures/profile are intentionally absent in a public checkout")
    return read_records(records), ROOT / f"artifacts/{TRIAL}", profile


def setup(path, started):
    with Store(path) as store:
        store.add_channel("replay")
        character = store.add_character("replay", "Explicit saved-session character")
        store.select_character("replay", character)
        return store.start_session("replay", at=started)


def test_real_saved_ocr_trust_sqlite_restart_and_bridging_policy(saved, tmp_path):
    records, crops, profile_path = saved
    profile = GlyphProfile.load(profile_path)
    when = lambda r: datetime.fromisoformat(r["received_at"])
    path = tmp_path / "real-ocr.sqlite3"
    session_id = setup(path, when(records[0]) - timedelta(seconds=1))
    results = []
    trusted_values = []
    # Closing/reopening after every observation is stronger than a single restart.
    for record in records:
        result = recognize_saved(record, crops, profile)
        results.append(result)
        with Store(path) as restarted:
            before = restarted.state("replay")["last_trusted"]
            row = restarted.ingest("replay", f"private-frame-{record['index']}", when(record), result,
                                   profile=profile, session_id=session_id, source="saved-crops")
            after = restarted.state("replay")["last_trusted"]
            if row["outcome"] in {"accepted", "baseline"}:
                assert asdict(result.reading) == record["recognition"]["reading"]
                assert after["current_exp"] == result.reading.current_exp
                assert row["profile_hash"] and row["current_exp"] is not None
                trusted_values.append(result.reading.current_exp)
            else:
                assert row["current_exp"] is None
                assert after == before
    with Store(path) as restarted:
        state = restarted.state("replay")
        assert len(trusted_values) == 14
        assert state["last_trusted"]["current_exp"] == 879217
        assert state["status"] == "paused"
        assert state["observed_session_exp"] == 6121
        assert state["bridged_session_exp"] == 1592
        assert state["pending_missing_observations"] == 1
        assert not state["continuity_broken"]
        bridged = restarted.db.execute("""SELECT gained_exp,missing_observations,interval_start_observation_id
                                          FROM observations WHERE missing_observations>0 ORDER BY id""").fetchall()
        assert [(row["gained_exp"], row["missing_observations"]) for row in bridged] == [(738, 1), (854, 1)]
        assert all(row["interval_start_observation_id"] is not None for row in bridged)
        assert restarted.db.execute("SELECT COUNT(*) FROM observations WHERE outcome='baseline'").fetchone()[0] == 1
        assert restarted.db.execute("SELECT COUNT(*) FROM observations WHERE outcome='accepted'").fetchone()[0] == 13
        assert trusted_values[-1] - trusted_values[0] == 6121
        assert restarted.db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
        assert restarted.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 17
        duplicate = restarted.ingest("replay", "private-frame-0", when(records[0]), results[0],
                                     profile=profile, session_id=session_id, source="saved-crops")
        assert duplicate["duplicate"]
        assert restarted.state("replay")["observed_session_exp"] == 6121


def test_real_plausible_tesseract_fallback_is_never_trusted(saved, tmp_path):
    records, crops, profile_path = saved
    sample = ROOT / "samples/maplestory-classic-stream1.png"
    if not sample.exists():
        pytest.skip("Private original screenshot is intentionally absent")
    profile = GlyphProfile.load(profile_path)
    regions = {k: Region(*v) for k, v in json.loads((ROOT / "configs/stream1.json").read_text()).items()}
    with Image.open(sample) as image:
        fallback = recognize(image.convert("RGB"), regions=regions, glyph_profile=profile)
    assert fallback.status == "accepted" and fallback.reading.current_exp == 71441
    assert fallback.raw["exp"][0]["variant"] == "pixel" and not fallback.raw["exp"][0]["text"]
    start = datetime.fromisoformat(records[0]["received_at"])
    path = tmp_path / "fallback.sqlite3"
    session = setup(path, start - timedelta(seconds=10))
    with Store(path) as store:
        rejected = store.ingest("replay", "fallback-first", start - timedelta(seconds=5), fallback,
                                profile=profile, session_id=session)
        assert rejected["outcome"] == "rejected" and rejected["reason"] == "unverified_tesseract_exp"
        assert store.state("replay")["last_trusted"] is None
        trusted = recognize_saved(records[0], crops, profile)
        store.ingest("replay", "real-good", start, trusted, profile=profile, session_id=session)
        before = store.state("replay")["last_trusted"]
        store.ingest("replay", "fallback-after", start + timedelta(seconds=1), fallback,
                     profile=profile, session_id=session)
        assert store.state("replay")["last_trusted"] == before


def test_real_capture_cli_profile_ocr_sqlite_on_lossless_saved_video(saved, tmp_path, capsys):
    pytest.importorskip("psutil")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("Optional real FFmpeg integration")
    from exp_tracker.capture import main
    records, crops, profile_path = saved
    frame, _ = restore_frame(records[0], crops)
    image_path, video_path = tmp_path / "private-hud.png", tmp_path / "private-hud.mkv"
    frame.save(image_path)
    # Periodic file capture seeks past t=0; keep a second identical keyframe.
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-loop", "1", "-framerate", "2", "-i", str(image_path),
                    "-frames:v", "2", "-c:v", "ffv1", "-g", "1", "-pix_fmt", "bgr0", str(video_path)], check=True, timeout=20)
    path = tmp_path / "capture-ocr.sqlite3"
    # The new local decoder delivery uses current time; replay above uses original times.
    setup(path, datetime.now().astimezone() - timedelta(seconds=1))
    assert main(["--file", str(video_path), "--database", str(path), "--tracking-channel", "replay",
                 "--glyph-profile", str(profile_path), "--config", str(ROOT / "configs/telfer1-live.json"),
                 "--count", "1", "--timeout", "10"]) == 0
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output[0]["tracking"]["outcome"] == "baseline"
    with Store(path) as restarted:
        state = restarted.state("replay")
        assert state["last_trusted"]["level"] == 60
        assert state["last_trusted"]["current_exp"] == 873096
        assert state["last_trusted"]["percentage_bp"] == 7216
