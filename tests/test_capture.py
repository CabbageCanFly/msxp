import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from exp_tracker.capture import main
from exp_tracker import capture
from exp_tracker.video import CaptureError
from exp_tracker.video import Source, VideoSession


def test_missing_ffmpeg_returns_setup_error(capsys):
    assert main(["--channel", "example", "--ffmpeg", "nonexistent-ffmpeg-1234"]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "ffmpeg_not_found"


@pytest.mark.parametrize("args", [["--interval", "nan"], ["--timeout", "0"], ["--count", "0"]])
def test_bad_scheduling_arguments(args):
    with pytest.raises(SystemExit):
        main(["--channel", "example", *args])


@pytest.fixture
def generated_video(tmp_path):
    executable = shutil.which("ffmpeg")
    if not executable:
        pytest.skip("Optional FFmpeg integration test")
    video = tmp_path / "synthetic.mp4"
    subprocess.run([executable, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=160x90:rate=5", "-t", "2", "-c:v", "libx264", "-threads", "1",
                    "-g", "5", "-pix_fmt", "yuv420p", str(video)], check=True, timeout=20)
    return video


def test_real_decoder_and_cleanup(generated_video):
    session = VideoSession(Source("file", str(generated_video)))
    try:
        frame = session.frame(timeout=5)
        assert frame.image().size == (160, 90)
    finally:
        session.close()
    assert session.decoder.poll() is not None
    assert not any(thread.is_alive() for thread in session.threads)


def test_missing_video_does_not_hang():
    if not shutil.which("ffmpeg"):
        pytest.skip("Optional FFmpeg integration test")
    session = VideoSession(Source("file", "definitely-not-a-video.mp4"))
    try:
        with pytest.raises(RuntimeError):
            session.frame(timeout=2)
    finally:
        session.close()


@pytest.mark.ocr
def test_video_to_ocr_reports_missing_hud(generated_video):
    pytest.importorskip("psutil")
    result = subprocess.run([sys.executable, "-m", "exp_tracker.capture", "--file", str(generated_video),
                             "--count", "1", "--timeout", "5"], capture_output=True, text=True, timeout=15)
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.returncode == 0
    assert records[0]["status"] == "missing_hud"
    assert records[0]["transition"] is None
    assert records[-1]["frames_recognized"] == 1


def test_capture_failure_emits_reason_and_closes_session(tmp_path, monkeypatch, capsys):
    pytest.importorskip("psutil")
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg setup required for capture CLI")
    path = tmp_path / "source.mp4"
    path.write_bytes(b"fixture")
    sessions = []
    class FailingSession:
        source_bytes = 0
        closed = False
        def __init__(self, *_args, **_kwargs):
            sessions.append(self)
        def frame(self, **_kwargs):
            raise CaptureError("offline_or_unavailable")
        def close(self):
            self.closed = True
    monkeypatch.setattr(capture, "VideoSession", FailingSession)
    assert main(["--file", str(path), "--count", "1"]) == 2
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records[0]["status"] == "capture_failed"
    assert records[0]["reason"] == "offline_or_unavailable"
    assert records[-1]["frames_recognized"] == 0
    assert sessions[0].closed
