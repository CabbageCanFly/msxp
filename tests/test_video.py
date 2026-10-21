from datetime import datetime, timezone
from io import BytesIO
import struct
import sys
import threading
import time

from PIL import Image
import pytest

from exp_tracker.video import CaptureError, Frame, Source, VideoSession, ffmpeg_command, read_png


def png_bytes():
    data = BytesIO()
    Image.new("RGB", (16, 8), "red").save(data, format="PNG")
    return data.getvalue()


def test_image_pipe_reads_distinct_frames_without_eof_delimiters():
    payload = png_bytes()
    pipe = BytesIO(payload + payload)
    assert read_png(pipe) == payload
    assert read_png(pipe) == payload
    with pytest.raises(EOFError):
        read_png(pipe)


def test_png_parser_bounds_allocation_before_reading_body():
    payload = b"\x89PNG\r\n\x1a\n" + struct.pack(">I4s", 2**30, b"IDAT")
    with pytest.raises(CaptureError, match="byte_limit"):
        read_png(BytesIO(payload))
    with pytest.raises(CaptureError, match="invalid_decoder"):
        read_png(BytesIO(b"notapng!"))


def test_png_parser_bounds_resolution():
    payload = b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", 10000, 10000) + b"\x00" * 9
    with pytest.raises(CaptureError, match="pixel_limit"):
        read_png(BytesIO(payload))


def test_source_disables_browser_and_cached_credentials():
    command = Source("twitch", "example").streamlink_command()
    assert command[command.index("--webbrowser") + 1] == "false"
    assert "--no-config" in command and "--no-plugin-cache" in command
    assert "--no-plugin-sideloading" in command
    assert "--twitch-disable-ads" not in command
    assert command[-2:] == ["https://www.twitch.tv/example", "best"]
    with pytest.raises(ValueError):
        Source("twitch", "example;anything").streamlink_command()
    with pytest.raises(ValueError):
        Source("twitch", "example", "--other-option").streamlink_command()


def test_file_seek_does_not_use_scientific_notation():
    command = ffmpeg_command("ffmpeg", Source("file", "example.mp4"), file_offset=1e-8)
    assert command[command.index("-ss") + 1] == "0.000000"
    assert command[command.index("-threads") + 1] == "1"
    assert command[command.index("-skip_frame") + 1] == "nokey"


def bare_session(frame=None):
    session = VideoSession.__new__(VideoSession)
    session.condition = threading.Condition()
    session.latest = frame
    session.error = None
    session.logs = {"streamlink": bytearray(), "ffmpeg": bytearray()}
    return session


def test_latest_frame_and_repeated_sequence_gate():
    frame = Frame(png_bytes(), 10, time.monotonic(), datetime.now(timezone.utc).isoformat())
    session = bare_session(frame)
    assert session.frame(after_sequence=9) is frame
    assert frame.image().size == (16, 8)
    with pytest.raises(CaptureError):
        session.frame(after_sequence=10, timeout=.001)


def test_stale_delivery_is_never_returned_as_current():
    session = bare_session(Frame(png_bytes(), 1, time.monotonic() - 100, "past"))
    with pytest.raises(CaptureError):
        session.frame(max_age=5, timeout=.001)


@pytest.mark.parametrize("text,reason", [
    (b"No playable streams found", "offline_or_unavailable"),
    (b"Failed to resolve host", "network_unavailable"),
    (b"WinError 10013", "network_unavailable"),
    (b"403 access denied", "access_denied"),
])
def test_safe_error_classification(text, reason):
    session = bare_session()
    session.logs["streamlink"] = bytearray(text)
    assert session.reason() == reason


@pytest.mark.parametrize('kind',['file','twitch'])
def test_real_hung_capture_children_timeout_and_are_reaped(monkeypatch,kind):
    command=[sys.executable,'-c','import time; time.sleep(60)']
    monkeypatch.setattr('exp_tracker.video.ffmpeg_command',lambda *a,**kw:command)
    monkeypatch.setattr(Source,'streamlink_command',lambda _:command)
    started=time.monotonic()
    session=VideoSession(Source(kind,'synthetic'))
    try:
        with pytest.raises(CaptureError,match='frame_timeout'):
            session.frame(timeout=.15)
    finally:
        session.close()
    assert time.monotonic()-started<6
    assert session.decoder.poll() is not None
    assert session.producer is None or session.producer.poll() is not None
    assert all(not thread.is_alive() for thread in session.threads)
    session.close()  # Shutdown remains idempotent.


def test_real_decoder_exit_is_unavailable_not_a_fresh_frame(monkeypatch):
    monkeypatch.setattr('exp_tracker.video.ffmpeg_command',lambda *a,**kw:[sys.executable,'-c','raise SystemExit(2)'])
    session=VideoSession(Source('file','synthetic'))
    try:
        with pytest.raises(CaptureError,match='source_ended'):
            session.frame(timeout=2)
    finally:
        session.close()
    assert session.latest is None and session.decoder.poll()==2


def test_live_small_producer_chunk_reaches_decoder_without_filling_relay_buffer(monkeypatch):
    payload=png_bytes()
    producer=[sys.executable,'-c',
        f'import sys,time; sys.stdout.buffer.write({payload!r}); sys.stdout.buffer.flush(); time.sleep(60)']
    decoder=[sys.executable,'-c',
        f'import sys,time; data=sys.stdin.buffer.read({len(payload)}); '
        'sys.stdout.buffer.write(data); sys.stdout.buffer.flush(); time.sleep(60)']
    monkeypatch.setattr(Source,'streamlink_command',lambda _:producer)
    monkeypatch.setattr('exp_tracker.video.ffmpeg_command',lambda *a,**kw:decoder)
    session=VideoSession(Source('twitch','synthetic'))
    try:
        assert session.frame(timeout=2).png==payload
        assert session.source_bytes==len(payload)<16384
    finally:
        session.close()
    assert all(not thread.is_alive() for thread in session.threads)


def test_live_short_stderr_is_available_for_safe_failure_classification(monkeypatch):
    producer=[sys.executable,'-c',
        'import sys,time; sys.stderr.write("403 access denied https://private.invalid/?token=secret\\n"); '
        'sys.stderr.flush(); time.sleep(60)']
    decoder=[sys.executable,'-c','import time; time.sleep(60)']
    monkeypatch.setattr(Source,'streamlink_command',lambda _:producer)
    monkeypatch.setattr('exp_tracker.video.ffmpeg_command',lambda *a,**kw:decoder)
    session=VideoSession(Source('twitch','synthetic'))
    try:
        with pytest.raises(CaptureError,match='^access_denied$'):
            session.frame(timeout=2)
    finally:
        session.close()
