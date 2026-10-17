"""Synthetic safety tests; no stream access, neural model or private profile needed."""

import importlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from exp_tracker.models import Region
from exp_tracker.video import CaptureError, Frame, Source


@pytest.fixture
def shadow(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'tools'))
    return importlib.import_module('shadow_capture')


@pytest.fixture
def frame():
    payload = BytesIO()
    Image.new('RGB', (200, 100), 'black').save(payload, format='PNG')
    return Frame(payload.getvalue(), 1, 100, '2026-10-17T00:00:00+00:00')


def region():
    return dict(regions=dict(exp=Region(.4, .6, .9, .8), level=Region(.1, .6, .3, .9)),
                anchor_step=100, anchors={})


def analyze(shadow, frame, text='17[50.00%]', visual=2, **options):
    params = dict(locator=lambda image: [region()], read_level=lambda image: (visual, []),
                  clock=lambda: 101)
    params.update(options)
    return shadow.analyze(frame, {1: 15, 2: 34}, lambda image: dict(text=text, raw={'txts': [text]}),
                          **params)


@pytest.mark.parametrize('count,reason', [(0, 'missing_hud'), (2, 'multiple_huds')])
def test_no_silent_hud_selection(shadow, frame, count, reason):
    def forbidden(image):
        pytest.fail('Ambiguous/missing HUD must not reach either recognizer')
    result = shadow.analyze(frame, {1: 15}, forbidden, locator=lambda image: [region()] * count,
                            read_level=forbidden, clock=lambda: 101)
    assert result['reasons'] == [reason]
    assert result['neural'] is None and result['candidate'] is None and not result['trusted']


@pytest.mark.parametrize('text', ['17[50.00%1', '1750.00%]', '17[5.000%]', 'EXP?', '0[50.00%]',
                                 '0.85%1', '[70.63%1', '170 57%1'])
def test_malformed_values_remain_raw_not_candidates(shadow, frame, text):
    result = analyze(shadow, frame, text)
    assert result['candidate'] is None and result['neural']['text'] == text
    assert result['percentage_only_candidate'] is None
    assert result['level_evidence']['hypotheses']['nearest_half_up']['status'] == 'unavailable'


def test_partial_percentage_retained_without_completing_malformed_exp(shadow, frame):
    result = analyze(shadow, frame, '689.,965[92.17%]')
    assert result['partial_percentage_evidence']['percentage'] == '92.17'
    assert result['candidate'] is None and result['percentage_only_candidate'] is None
    assert result['diagnostic_type'] == 'unavailable' and not result['trusted']


def test_zero_retains_all_compatible_levels(shadow, frame):
    result = analyze(shadow, frame, '0[0.00%]')
    nearest = result['level_evidence']['hypotheses']['nearest_half_up']
    assert nearest['levels'] == [1, 2] and nearest['status'] == 'ambiguous'
    assert result['level_evidence']['relation'] == 'compatible_but_ambiguous'
    assert not result['trusted']


@pytest.mark.parametrize('visual,relation', [(2, 'agreement_not_verification'), (1, 'conflict'),
                                          (60, 'unsupported_visual_level'), (None, 'visual_unavailable')])
def test_levels_are_separate_evidence(shadow, frame, visual, relation):
    result = analyze(shadow, frame, visual=visual)
    assert result['candidate'] == [17, 50.0]
    assert result['visual_level'] == visual
    assert result['level_evidence']['hypotheses']['nearest_half_up']['unique_level'] == 2
    assert result['level_evidence']['relation'] == relation
    assert not result['trusted']


def test_rounding_hypotheses_never_selected_per_answer(shadow):
    result = shadow.level_evidence([1, .01], 1, {1: 20000})
    assert result['hypotheses']['nearest_half_up']['unique_level'] == 1
    assert result['hypotheses']['truncate']['status'] == 'incompatible'


def test_crop_uses_source_pixels_with_fixed_two_pixel_context(shadow, frame):
    result = analyze(shadow, frame)
    assert result['exp_crop_box'] == (78, 58, 182, 82)
    assert result['current'] and result['local_age_seconds'] == 1


def test_stale_frame_never_runs_locator(shadow, frame):
    result = analyze(shadow, frame, clock=lambda: 116,
                     locator=lambda image: pytest.fail('Stale frame processed'))
    assert result['status'] == 'stale_local_frame' and not result['current']


def test_stale_completed_work_is_never_current(shadow, frame):
    now = [101]
    def slow_level(image):
        now[0] = 120
        return 2, []
    result = analyze(shadow, frame, clock=lambda: now[0], read_level=slow_level)
    assert result['candidate'] == [17, 50.0]  # Retained diagnostic, not a current reading.
    assert result['status'] == 'stale_local_frame' and not result['current']


def test_level_failure_preserves_raw_neural_evidence(shadow, frame):
    def broken(image):
        raise RuntimeError('private detail')
    result = analyze(shadow, frame, read_level=broken)
    assert result['candidate'] == [17, 50.0] and result['visual_level'] is None
    assert 'visual_level_failed' in result['reasons'] and 'private detail' not in str(result)


def test_neural_failure_still_records_visual_evidence(shadow, frame):
    def broken(image):
        raise CaptureError('neural_timeout')
    result = shadow.analyze(frame, {2: 34}, broken, locator=lambda image: [region()],
                            read_level=lambda image: (2, []), clock=lambda: 101)
    assert result['visual_level'] == 2 and result['neural'] is None
    assert 'neural_timeout' in result['reasons']


def run_options(tmp_path):
    return SimpleNamespace(count=2, interval=15, start=50, timeout=20, max_age=15,
                           ocr_python=Path('unused'), ocr_timeout=10, save_crops=False,
                           output=tmp_path / 'output.jsonl')


@pytest.mark.parametrize('failure', [CaptureError('offline_or_unavailable'), OSError('secret url')])
def test_capture_failure_is_safe_and_closes(shadow, tmp_path, failure):
    sessions = []
    class Failed:
        source_bytes = 7
        def __init__(self, *args, **kwargs):
            self.closed = False
            sessions.append(self)
        def frame(self, **kwargs):
            raise failure
        def close(self):
            self.closed = True
    rows = []
    summary = shadow.run(run_options(tmp_path), Source('twitch', 'example'), {1: 15}, rows.append,
                         session_factory=Failed, clock=lambda: 100, sleep=lambda seconds: None)
    assert summary['attempts'] == 2
    assert all(session.closed for session in sessions)
    assert all(row['status'] == 'capture_failed' and not row['current'] for row in rows)
    assert 'secret url' not in str(rows)


def test_activity_callback_brackets_actual_attempt_and_never_equates_failure_with_offline(shadow,tmp_path,monkeypatch):
    events=[]
    def capture(*args,**kwargs):
        assert events[-1]['state']=='running'
        return dict(type='attempt',status='capture_failed')
    monkeypatch.setattr(shadow,'capture_attempt',capture)
    summary=shadow.run(run_options(tmp_path),Source('file','unused'),{},lambda r:events.append(dict(state='committed')),
        on_activity=events.append,clock=lambda:100,sleep=lambda _:None)
    assert [e['state'] for e in events]==['running','committed','capture_failing']*2
    assert summary['attempts']==2 and not summary['interrupted']
    assert all('offline' not in e['state'] for e in events)


def test_shutdown_interrupt_closes_active_capture(shadow, tmp_path):
    closed = []
    class Interrupted:
        source_bytes = 0
        def __init__(self, *args, **kwargs): pass
        def frame(self, **kwargs): raise KeyboardInterrupt
        def close(self): closed.append(True)
    rows = []
    summary = shadow.run(run_options(tmp_path), Source('file', 'unused'), {1: 15}, rows.append,
                         session_factory=Interrupted, clock=lambda: 100, sleep=lambda seconds: None)
    assert summary['interrupted'] and closed == [True] and rows == []


def test_connections_close_before_ocr_and_missed_slots_are_skipped(shadow, tmp_path, frame):
    now = [100.0]
    closed = [False]
    seeks, sleeps, rows = [], [], []
    class Session:
        source_bytes = 0
        def __init__(self, source, *, file_offset):
            closed[0] = False
            seeks.append(file_offset)
        def frame(self, **kwargs): return frame
        def close(self): closed[0] = True
    def processing(*args, **kwargs):
        assert closed[0]
        now[0] += 31
        return dict(timings={}, status='stale_local_frame', current=False)
    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds
    summary = shadow.run(run_options(tmp_path), Source('file', 'unused'), {1: 15}, rows.append,
                         session_factory=Session, analyze_frame=processing,
                         clock=lambda: now[0], sleep=sleep)
    assert seeks == [50, 95] and sleeps == [0, 14]
    assert summary['attempts'] == 2 and not summary['trusted']
    assert rows[0]['source']['verified_source_pts'] is None
    assert not rows[0]['freshness']['source_age_known']


def test_private_output_and_existing_evidence_protected(shadow, tmp_path):
    with pytest.raises(ValueError, match='ignored'):
        shadow.private_path(shadow.ROOT / 'public-output.jsonl')
    with pytest.raises(ValueError, match='ignored'):
        shadow.private_path(shadow.ROOT / 'private/../../escaped.jsonl')
    assert shadow.private_path(shadow.ROOT / 'private/shadow-capture/result.jsonl').is_absolute()


def test_live_capture_requires_explicit_authorization(shadow):
    with pytest.raises(SystemExit) as error:
        shadow.main(['--channel', 'example', '--output', 'private/shadow-capture/unused.jsonl'])
    assert error.value.code == 2


@pytest.mark.parametrize('flag,value', [('--count', '0'), ('--count', '61'), ('--interval', 'nan'),
                                       ('--timeout', '100'), ('--max-age', '-1')])
def test_invalid_bounds_fail_before_capture(shadow, flag, value):
    with pytest.raises(SystemExit) as error:
        shadow.main(['--file', 'unused', '--output', 'private/shadow-capture/unused.jsonl', flag, value])
    assert error.value.code == 2


def test_neural_worker_timeout_becomes_safe_failure(shadow, monkeypatch):
    def timeout(*args, **kwargs):
        assert kwargs['timeout'] == 3
        assert kwargs['stderr'] == shadow.subprocess.DEVNULL
        raise shadow.subprocess.TimeoutExpired(args[0], 3)
    monkeypatch.setattr(shadow.subprocess, 'run', timeout)
    with pytest.raises(CaptureError, match='neural_timeout'):
        shadow.neural_line(Image.new('RGB', (50, 15)), Path('unused'), 3)


def test_interrupt_during_partial_capture_startup_also_closes(shadow, monkeypatch):
    closed = []
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(shadow.VideoSession, '__init__', interrupted)
    monkeypatch.setattr(shadow.VideoSession, 'close', lambda self: closed.append(True))
    with pytest.raises(KeyboardInterrupt):
        shadow.ShadowSession(Source('file', 'unused'))
    assert closed == [True]


def test_neural_bridge_rejects_oversized_crops_before_launch(shadow, monkeypatch):
    monkeypatch.setattr(shadow.subprocess, 'run', lambda *a, **kw: pytest.fail('Worker launched'))
    with pytest.raises(CaptureError, match='exceeds_limit'):
        shadow.neural_line(Image.new('RGB', (1025, 10)), Path('unused'), 3)


@pytest.mark.parametrize('returncode,payload', [(1, b''), (0, b'not JSON'), (0, b'x' * 65537)],
                         ids=['process_error', 'invalid_json', 'oversized_output'])
def test_neural_failure_outputs_never_leak_raw_stderr(shadow, monkeypatch, returncode, payload):
    monkeypatch.setattr(shadow.subprocess, 'run', lambda *a, **kw:
                        SimpleNamespace(returncode=returncode, stdout=payload))
    with pytest.raises(CaptureError):
        shadow.neural_line(Image.new('RGB', (50, 15)), Path('unused'), 3)


@pytest.mark.parametrize('experimental',[False,True])
def test_cli_writes_configuration_attempt_summary_without_store(shadow, monkeypatch, tmp_path, experimental):
    import json
    monkeypatch.setattr(shadow, 'ROOT', tmp_path)
    monkeypatch.setattr(shadow.shutil, 'which', lambda executable: 'ffmpeg')
    table = tmp_path / 'requirements.json'
    table.write_text(json.dumps({'to_next': {'1': 15}}))
    executable = tmp_path / 'python'
    executable.touch()
    video = tmp_path / 'video.mp4'
    video.touch()
    output = tmp_path / 'private/test.jsonl'
    def run(args, source, requirements, emit):
        assert source.kind == 'file' and requirements == {1: 15}
        emit(dict(type='attempt', trusted=False, candidate=[0, 0.0]))
        return dict(type='summary', interrupted=False, trusted=False)
    monkeypatch.setattr(shadow, 'run', run)
    arguments = ['--file', str(video), '--requirements', str(table), '--ocr-python', str(executable),
                 '--output', str(output)]
    if experimental:
        arguments.append('--experimental-neural-level')
    assert shadow.main(arguments) == 0
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert [row['type'] for row in records] == ['configuration', 'attempt', 'summary']
    assert all(not row['trusted'] for row in records)
    assert records[0].get('experimental_neural_level',False) is experimental
    assert not list(tmp_path.rglob('*.sqlite*')) and not list(tmp_path.rglob('*.png'))
    with pytest.raises(SystemExit):
        shadow.main(arguments)  # Existing evidence cannot be overwritten.
