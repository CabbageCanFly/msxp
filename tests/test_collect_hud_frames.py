"""Offline collector checks: injected native PNGs plus a generated local video."""

import hashlib
import importlib
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess

from PIL import Image
import pytest

from exp_tracker.video import CaptureError, Frame, VideoSession


@pytest.fixture
def collector(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'tools'))
    module = importlib.import_module('collect_hud_frames')
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    return module


@pytest.fixture
def args(collector, tmp_path):
    video = tmp_path / 'private-token-source.mp4'
    video.write_bytes(b'synthetic input; acquisition injected')
    return collector.parser().parse_args(['--file', str(video), '--output',
        str(tmp_path / 'private/obscured-hud/new'), '--count', '2', '--interval', '1'])


def frame(color, sequence, arrived=100):
    payload = BytesIO()
    Image.new('RGB', (32, 16), color).save(payload, format='PNG')
    return Frame(payload.getvalue(), sequence, arrived, '2026-10-19T10:00:00+00:00')


class Session:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.calls = []
        self.closed = False

    def frame(self, **kwargs):
        self.calls.append(kwargs)
        value = next(self.frames)
        if isinstance(value, BaseException):
            raise value
        return value

    def close(self):
        self.closed = True


def run(collector, args, session, **kwargs):
    return collector.collect(args, session_factory=lambda *a, **k: session,
        clock=kwargs.pop('clock', lambda: 100), sleep=kwargs.pop('sleep', lambda _: None), **kwargs)


def test_saves_original_bytes_dimensions_hashes_and_private_source_identity(collector, args):
    frames = [frame('red', 1), frame('blue', 2)]
    session = Session(frames)
    result = run(collector, args, session)
    manifest = json.loads((args.output / 'manifest.json').read_text())
    assert manifest == result and result['status'] == 'complete'
    assert session.closed and not result['fewer_distinct_frames']
    assert [c['after_sequence'] for c in session.calls] == [0, 1]
    assert all(c['max_age'] == 5 for c in session.calls)
    assert len(list(args.output.iterdir())) == 3
    for saved, original in zip(result['frames'], frames):
        data = (args.output / saved['file']).read_bytes()
        assert data == original.png
        assert saved['sha256'] == hashlib.sha256(data).hexdigest()
        assert (saved['width'], saved['height']) == (32, 16)
        assert saved['png_bytes'] == len(data) and saved['received_at'] == original.received_at
    source = result['source']
    assert source['identity_sha256'] == hashlib.sha256(json.dumps(['file', str(args.file.resolve())]).encode()).hexdigest()
    assert source['requested_rendition'] is None and source['verified_source_pts'] is None
    assert args.file.name not in json.dumps(result)
    assert not list(collector.ROOT.rglob('*.sqlite*')) and not list(collector.ROOT.rglob('*.jsonl'))


def test_duplicate_frames_are_skipped_and_sequence_advances(collector, args):
    session = Session([frame('red', 1), frame('red', 2), frame('blue', 3)])
    result = run(collector, args, session)
    assert [a['outcome'] for a in result['attempts']] == ['saved', 'duplicate', 'saved']
    assert [c['after_sequence'] for c in session.calls] == [0, 1, 2]
    assert result['distinct_frames'] == 2 and session.closed


def test_identical_stream_stops_after_ten_attempts_and_labels_shortfall(collector, args):
    session = Session([frame('red', i) for i in range(1, 11)])
    result = run(collector, args, session)
    assert len(session.calls) == 10 and session.closed
    assert result['distinct_frames'] == 1 and result['fewer_distinct_frames']
    assert result['status'] == 'incomplete' and result['stop_reason'] == 'attempt_limit'
    assert len(list(args.output.glob('*.png'))) == 1


def test_five_frame_ceiling(collector, args):
    args.count = 5
    session = Session([frame((i, 0, 0), i) for i in range(1, 7)])
    result = run(collector, args, session)
    assert result['distinct_frames'] == len(session.calls) == 5
    assert len(list(args.output.iterdir())) == 6


@pytest.mark.parametrize('name,value', [('count', 0), ('count', 6), ('timeout', 0), ('timeout', 21),
    ('timeout', float('nan')), ('interval', 0), ('interval', 11), ('interval', float('inf')),
    ('start', -1), ('start', 86401), ('start', float('nan'))])
def test_limits_are_validated_before_output_or_acquisition(collector, args, name, value):
    setattr(args, name, value)
    with pytest.raises(ValueError):
        collector.collect(args, session_factory=lambda *a, **k: pytest.fail('Invalid input acquired'))
    assert not args.output.exists()


@pytest.mark.parametrize('path', ['outside', 'private/obscured-hud', 'private/obscured-hud/../escape',
    'private/obscured-hud/parent/nested'])
def test_output_must_be_new_direct_child_of_private_root(collector, args, path):
    args.output = collector.ROOT / path
    with pytest.raises(ValueError, match='Output must'):
        collector.collect(args, session_factory=lambda *a, **k: pytest.fail('Invalid output acquired'))
    assert not args.output.exists()


@pytest.mark.parametrize('directory', [False, True])
def test_refuses_existing_file_or_directory_without_changing_it(collector, args, directory):
    args.output.parent.mkdir(parents=True)
    if directory:
        args.output.mkdir()
        evidence = args.output / 'existing.png'
    else:
        evidence = args.output
    evidence.write_bytes(b'preserve')
    with pytest.raises(ValueError, match='Never overwrite'):
        collector.collect(args, session_factory=lambda *a, **k: pytest.fail('Existing output acquired'))
    assert evidence.read_bytes() == b'preserve'


def test_resolved_output_cannot_escape_through_symlink(collector, args, tmp_path):
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    private = tmp_path / 'private'
    private.mkdir()
    try:
        (private / 'obscured-hud').symlink_to(elsewhere, target_is_directory=True)
    except OSError:
        pytest.skip('OS does not permit creating test symlinks')
    with pytest.raises(ValueError, match='Output must'):
        collector.prepare(args)
    assert not list(elsewhere.iterdir())


def test_remote_authorization_required_before_any_connection_or_output(collector, args, capsys):
    assert collector.main(['--channel', 'TriciaIsABirdy', '--output', str(args.output)],
        session_factory=lambda *a, **k: pytest.fail('Unauthorized source acquired')) == 1
    assert '--authorized' in capsys.readouterr().err
    assert not args.output.exists()


@pytest.mark.parametrize('extra', [['--channel', ''], ['--channel', 'https://example.invalid/?token=secret'],
    ['--channel', 'valid', '--quality', 'best;token=secret'], ['--channel', 'valid', '--start', '1']])
def test_remote_input_validation_reuses_existing_contract(collector, args, extra):
    parsed = collector.parser().parse_args([*extra, '--authorized', '--output', str(args.output)])
    with pytest.raises(ValueError):
        collector.collect(parsed, session_factory=lambda *a, **k: pytest.fail('Invalid source acquired'))
    assert not args.output.exists()


def test_authorized_remote_metadata_without_network(collector, args):
    args.file, args.channel, args.authorized, args.quality = None, 'TriciaIsABirdy', True, '1080p60'
    calls = []
    session = Session([frame('red', 1), frame('blue', 2)])
    def factory(source, **kwargs):
        calls.append(source)
        return session
    result = collector.collect(args, session_factory=factory, clock=lambda: 100, sleep=lambda _: None)
    assert calls[0].value == 'triciaisabirdy' and calls[0].quality == '1080p60'
    assert result['source']['channel'] == 'triciaisabirdy'
    assert result['source']['requested_rendition'] == '1080p60'
    assert 'https://' not in json.dumps(result)


def test_missing_local_video_is_rejected_before_output(collector, args):
    args.file = collector.ROOT / 'missing.mp4'
    with pytest.raises(ValueError, match='existing authorized local video'):
        collector.collect(args)
    assert not args.output.exists()


def test_deadline_bounds_waits_and_session_lifetime(collector, args):
    args.timeout, args.interval = 20, 7
    now = [100]
    sleeps, waits = [], []
    session = Session([])
    def wait(**kwargs):
        waits.append(kwargs['timeout'])
        now[0] += kwargs['timeout']
        raise CaptureError('frame_timeout')
    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds
    session.frame = wait
    result = run(collector, args, session, clock=lambda: now[0], sleep=sleep)
    assert result['stop_reason'] == 'collection_deadline' and result['wall_seconds'] == 60
    assert session.closed and waits == [20, 20, 6] and sleeps == [7, 7, 0]


@pytest.mark.parametrize('arrived', [90, 101])
def test_stale_or_future_receipt_is_not_saved(collector, args, arrived):
    result = run(collector, args, Session([frame('red', 1, arrived), CaptureError('source_ended')]))
    assert result['attempts'][0]['outcome'] == 'stale_local_frame'
    assert result['distinct_frames'] == 0 and not list(args.output.glob('*.png'))


def test_frame_returned_after_deadline_is_not_saved(collector, args):
    now = [100]
    session = Session([])
    def wait(**kwargs):
        now[0] = 161
        return frame('red', 1, 161)
    session.frame = wait
    result = run(collector, args, session, clock=lambda: now[0])
    assert result['stop_reason'] == 'collection_deadline'
    assert result['distinct_frames'] == 0 and session.closed


@pytest.mark.parametrize('limit', ['MAX_PNG_BYTES', 'MAX_PIXELS'])
def test_native_frame_limits_are_enforced_before_saving(collector, args, monkeypatch, limit):
    monkeypatch.setattr(collector, limit, 1)
    session = Session([frame('red', 1)])
    result = run(collector, args, session)
    assert result['stop_reason'] == 'collection_failed' and session.closed
    assert not list(args.output.glob('*.png'))


@pytest.mark.parametrize('error,reason', [(KeyboardInterrupt(), 'operator_interrupted'),
    (CaptureError('https://secret.invalid/?token=private-secret'), 'capture_failed'),
    (OSError('private-secret'), 'collection_failed')])
def test_failures_keep_partial_manifest_close_session_and_redact_details(collector, args, error, reason):
    session = Session([frame('red', 1), error])
    result = run(collector, args, session)
    assert result['stop_reason'] == reason and session.closed
    assert result['distinct_frames'] == 1 and result['fewer_distinct_frames']
    assert 'private-secret' not in (args.output / 'manifest.json').read_text()


def test_interrupt_during_constructor_closes_partial_session(collector, monkeypatch):
    closed = []
    def start(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(VideoSession, '__init__', start)
    monkeypatch.setattr(VideoSession, 'close', lambda self: closed.append(True))
    with pytest.raises(KeyboardInterrupt):
        collector.DiagnosticSession(None)
    assert closed == [True]


def test_generated_local_video_uses_real_decoder_and_saved_hash(collector, args):
    executable = shutil.which('ffmpeg')
    if not executable:
        pytest.skip('Optional FFmpeg integration test')
    video = collector.ROOT / 'generated.mp4'
    subprocess.run([executable, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
        'testsrc2=size=160x90:rate=5', '-t', '2', '-c:v', 'libx264', '-threads', '1',
        '-g', '5', '-pix_fmt', 'yuv420p', str(video)], check=True, timeout=20)
    args.file, args.count = video, 1
    sessions = []
    def factory(source, **kwargs):
        session = collector.DiagnosticSession(source, **kwargs)
        sessions.append(session)
        return session
    result = collector.collect(args, session_factory=factory)
    saved = result['frames'][0]
    assert result['status'] == 'complete' and (saved['width'], saved['height']) == (160, 90)
    assert hashlib.sha256((args.output / saved['file']).read_bytes()).hexdigest() == saved['sha256']
    assert sessions[0].decoder.poll() is not None
    assert not any(thread.is_alive() for thread in sessions[0].threads)
