from datetime import datetime, timezone
from dataclasses import asdict
import json

from PIL import Image
import pytest

from exp_tracker.models import Recognition
from tools import replay_capture_crops as replay


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_capture_record_encodings(tmp_path, encoding):
    path = tmp_path / "records.jsonl"
    path.write_text('{"type":"observation","index":0}\n{"type":"summary"}\n', encoding=encoding)
    assert replay.read_records(path) == [{"type": "observation", "index": 0}]


def test_early_level_failure_does_not_require_unsaved_exp(tmp_path, monkeypatch):
    directory = tmp_path / "0000"
    directory.mkdir()
    Image.new("RGB", (10, 10), "red").save(directory / "level-crop.png")
    record = dict(index=0, frame_size=[20, 10], recognition=dict(
        regions={"level": dict(x0=0, y0=0, x1=.5, y1=1), "exp": dict(x0=.5, y0=0, x1=1, y1=1)},
        raw={"level": []}))
    def recognize(image, **_kwargs):
        assert image.getpixel((2, 2)) == (255, 0, 0)
        assert image.getpixel((12, 2)) == (0, 0, 0)
        return Recognition("unreadable", reasons=["cannot_parse_level"])
    monkeypatch.setattr(replay, "recognize", recognize)
    assert replay.recognize_saved(record, tmp_path).reasons == ["cannot_parse_level"]


def test_capture_failure_without_crops_is_diagnostic(tmp_path):
    result = replay.recognize_saved(dict(status="capture_failed", reason="offline_or_unavailable"), tmp_path)
    assert result.status == "capture_failed"


def test_database_replay_requires_explicit_profile_and_channel():
    with pytest.raises(SystemExit):
        replay.main(["unused.jsonl", "unused-crops", "--database", "unused.sqlite3"])


def test_missing_profile_is_clear_error(tmp_path, capsys):
    assert replay.main(["unused.jsonl", "unused-crops", "--glyph-profile", str(tmp_path / "missing.json")]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "error"


def test_historical_session_start_cli(tmp_path, capsys):
    from exp_tracker.tracking import main
    from exp_tracker.store import Store
    path = tmp_path / "historical.sqlite3"
    args = ["--db", str(path), "--channel", "replay"]
    for command in (["init"], ["character", "Explicit replay character"], ["select", "1"],
                    ["start", "--at", "2026-01-01T00:00:00Z"]):
        assert main([*args, *command]) == 0
        capsys.readouterr()
    with Store(path) as store:
        start = store.state("replay")["session"]["started_at"]
        assert datetime.fromisoformat(start) == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_replay_cli_persists_idempotently(tmp_path, monkeypatch, capsys):
    from exp_tracker.glyphs import GlyphProfile, SYMBOLS
    from exp_tracker.models import Reading
    from exp_tracker.store import Store
    profile = GlyphProfile(9, {c: 6 for c in SYMBOLS}, {c: (1 << i,) for i, c in enumerate(SYMBOLS)},
                           punctuation_threshold=11, bracket_mode="green_excess")
    profile_path = tmp_path / "synthetic.json"
    profile_path.write_text(json.dumps({"version": 2, **asdict(profile)}))
    records = tmp_path / "records.jsonl"
    records.write_text('\n'.join(json.dumps(dict(type="observation", index=i, status="accepted",
        received_at=f"2026-01-01T00:00:0{i+1}+00:00")) for i in range(2)))
    path = tmp_path / "replay.sqlite3"
    with Store(path) as store:
        store.add_channel("replay")
        char = store.add_character("replay", "Synthetic character")
        store.select_character("replay", char)
        store.start_session("replay", at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    def synthetic(record, *_args):
        exp = 1000 + record["index"] * 100
        return Recognition("accepted", Reading(60, exp, exp / 100), .99,
                           raw={"exp": [dict(variant="pixel", text=f"{exp:,}[{exp/100:.2f}%]", confidence=.99)]})
    monkeypatch.setattr(replay, "recognize_saved", synthetic)
    args = [str(records), str(tmp_path), "--glyph-profile", str(profile_path),
            "--database", str(path), "--tracking-channel", "replay"]
    for duplicate in (False, True):
        assert replay.main(args) == 0
        assert all(json.loads(line)["tracking"]["duplicate"] == duplicate for line in capsys.readouterr().out.splitlines())
    with Store(path) as store:
        assert store.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 2
        assert store.state("replay")["observed_session_exp"] == 100
