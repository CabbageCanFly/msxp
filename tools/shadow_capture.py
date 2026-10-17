"""Bounded, serial capture -> experimental OCR diagnostics. Never trusted ingestion."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from exp_tracker.metrics import ResourceMonitor
from exp_tracker.video import CaptureError, Source, VideoSession
from adaptive_hud import locate, level_reading
from analyze_temporal_ocr import complete_pair
from benchmark_rapidocr import context_box, interpret
from infer_exp_level import infer_levels


class ShadowSession(VideoSession):
    def __init__(self, *args, **kwargs):
        try:
            super().__init__(*args, **kwargs)
        except KeyboardInterrupt:
            # The production constructor handles OSError; also close partial startup on Ctrl+C.
            self.close()
            raise


def neural_line(crop, python, timeout):
    if crop.width > 1024 or crop.height > 256:
        raise CaptureError('exp_crop_exceeds_limit')
    payload = BytesIO()
    crop.save(payload, format='PNG')
    if payload.tell() > 1024 * 1024:
        raise CaptureError('exp_crop_exceeds_limit')
    try:
        result = subprocess.run([str(python), str(ROOT / 'tools/shadow_rapidocr.py')],
                                input=payload.getvalue(), stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise CaptureError('neural_timeout') from None
    if result.returncode or len(result.stdout) > 65536:
        raise CaptureError('neural_worker_failed')
    try:
        return json.loads(result.stdout)
    except (ValueError, UnicodeError):
        raise CaptureError('invalid_neural_response') from None


def level_evidence(pair, visual, requirements):
    exp, percentage = pair if pair is not None else (None, None)
    hypotheses = {mode: infer_levels(exp, percentage, requirements, mode)
                  for mode in ('nearest_half_up', 'truncate')}
    nearest = hypotheses['nearest_half_up']
    if visual is None:
        relation = 'visual_unavailable'
    elif visual not in requirements:
        relation = 'unsupported_visual_level'
    elif pair is None:
        relation = 'pair_unavailable'
    elif nearest['status'] == 'incompatible' or visual not in nearest['levels']:
        relation = 'conflict'
    elif nearest['status'] == 'unique':
        relation = 'agreement_not_verification'
    else:
        relation = 'compatible_but_ambiguous'
    return dict(hypotheses=hypotheses, relation=relation, trusted=False)


def analyze(frame, requirements, read_line, *, max_age=15, locator=locate,
            read_level=level_reading, clock=time.monotonic, crop_dir=None):
    """No value reuse. Even completed stale work is explicitly ineligible/current=false."""
    result = dict(status='unavailable', trusted=False, current=False, reasons=[], timings={},
                  candidate=None, visual_level=None, visual_attempts=[], neural=None,
                  visual_status='not_run', neural_status='not_run',
                  localization=None, level_evidence=level_evidence(None, None, requirements))

    def fresh():
        result['local_age_seconds'] = max(0, clock() - frame.arrived_monotonic)
        if result['local_age_seconds'] > max_age:
            result['status'] = 'stale_local_frame'
            result['reasons'].append('local_receipt_age_exceeded')
            return False
        return True

    if not fresh():
        return result
    started = clock()
    image = frame.image()
    result['frame_size'] = image.size
    try:
        candidates = locator(image)
    except (OSError, RuntimeError, ValueError):
        result['reasons'].append('localization_failed')
        result['timings']['localization_seconds'] = clock() - started
        fresh()
        return result
    result['timings']['localization_seconds'] = clock() - started
    result['localization'] = dict(count=len(candidates), candidates=[
        {**candidate, 'regions': {key: asdict(region) for key, region in candidate['regions'].items()}}
        for candidate in candidates], target_identity_verified=False)
    if not fresh():
        return result
    if len(candidates) != 1:
        result['reasons'].append('missing_hud' if not candidates else 'multiple_huds')
        return result
    regions = candidates[0]['regions']
    box = context_box(regions['exp'], image.size, 2)
    crop = image.crop(box)
    result['exp_crop_box'] = box
    if crop_dir:
        crop_dir.mkdir(parents=True, exist_ok=False)
        crop.save(crop_dir / 'exp.png')
        image.crop(regions['level'].pixels(*image.size)).save(crop_dir / 'level.png')
    started = clock()
    try:
        result['neural'] = read_line(crop)
        result['neural_status'] = 'single_line' if result['neural']['text'] is not None else 'no_single_line'
    except (OSError, RuntimeError, ValueError) as error:
        result['neural_status'] = 'failed'
        result['reasons'].append(str(error) if isinstance(error, CaptureError) else 'neural_failed')
    result['timings']['neural_bridge_seconds'] = clock() - started
    if result['neural'] is not None:
        result['parsed_diagnostic'] = interpret(result['neural']['text'])
        result['candidate'] = complete_pair(result['neural']['text'])
    if not fresh():
        return result
    started = clock()
    try:
        visual, attempts = read_level(image.crop(regions['level'].pixels(*image.size)))
        result['visual_status'] = 'available' if visual is not None else 'unavailable'
    except (OSError, RuntimeError, ValueError):
        visual, attempts = None, []
        result['visual_status'] = 'failed'
        result['reasons'].append('visual_level_failed')
    result['timings']['visual_level_seconds'] = clock() - started
    result['visual_level'], result['visual_attempts'] = visual, attempts
    result['level_evidence'] = level_evidence(result['candidate'], visual, requirements)
    if not fresh():
        return result
    result['current'] = True  # Local delivery age only, never broadcast/source freshness.
    result['status'] = 'diagnostic_pair' if result['candidate'] is not None else 'malformed_or_unavailable'
    if result['candidate'] is None:
        result['reasons'].append('strict_pair_unavailable')
    if visual is None:
        result['reasons'].append('visual_level_unavailable')
    if result['level_evidence']['relation'] in ('conflict', 'unsupported_visual_level'):
        result['reasons'].append(result['level_evidence']['relation'])
    return result


def private_path(path):
    path = path.resolve()
    if not any(path.is_relative_to(ROOT / name) for name in ('private', 'artifacts')):
        raise ValueError('Diagnostics must stay under ignored private/ or artifacts/')
    return path


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    source = cli.add_mutually_exclusive_group(required=True)
    source.add_argument('--file', type=Path)
    source.add_argument('--channel')
    cli.add_argument('--authorized', action='store_true', help='Confirm permission for this Twitch trial')
    cli.add_argument('--quality', default='best')
    cli.add_argument('--start', type=float, default=0, help='Local video seek offset, not verified frame PTS')
    cli.add_argument('--interval', type=float, default=15)
    cli.add_argument('--count', type=int, default=3)
    cli.add_argument('--timeout', type=float, default=20, help='Capture wait limit, seconds')
    cli.add_argument('--max-age', type=float, default=15, help='Local receipt-to-result freshness limit')
    cli.add_argument('--ocr-timeout', type=float, default=10)
    cli.add_argument('--ocr-python', type=Path, default=ROOT / 'private/rapidocr/.venv' /
                     ('Scripts/python.exe' if os.name == 'nt' else 'bin/python'))
    cli.add_argument('--requirements', type=Path, default=ROOT / 'private/exp-consistency/requirements.json')
    cli.add_argument('--output', type=Path, required=True)
    cli.add_argument('--save-crops', action='store_true', help='Save only field crops beside the NEW JSONL')
    return cli


def run(args, source, requirements, emit, *, session_factory=ShadowSession, analyze_frame=analyze,
        clock=time.monotonic, sleep=time.sleep):
    started = clock()
    deadline = started
    attempted = 0
    interrupted = False
    try:
        for index in range(args.count):
            sleep(max(0, deadline - clock()))
            attempt_started = clock()
            attempted += 1
            seek = args.start + clock() - started if source.kind == 'file' else None
            record = dict(type='attempt', index=index + 1, trusted=False, current=False,
                          attempted_at=datetime.now(timezone.utc).isoformat(),
                          source=dict(kind=source.kind, channel=source.value if source.kind == 'twitch' else None,
                                      requested_video_offset_seconds=seek, verified_source_pts=None),
                          freshness=dict(source_age_known=False, broadcast_latency_known=False,
                                         basis='local_decoder_receipt_only'),
                          reasons=[], timings={}, source_bytes=0,
                          candidate=None, visual_level=None, neural=None, localization=None,
                          visual_status='not_run', neural_status='not_run',
                          level_evidence=level_evidence(None, None, requirements))
            session = None
            tick = clock()
            try:
                session = session_factory(source, file_offset=seek or 0)
                frame = session.frame(timeout=args.timeout, max_age=min(5, args.max_age))
                record['received_at'] = frame.received_at
                record['frame_sha256'] = hashlib.sha256(frame.png).hexdigest()
                record['timings']['capture_wait_seconds'] = clock() - tick
            except CaptureError as error:
                record.update(status='capture_failed', reasons=[str(error)])
                frame = None
            except OSError:
                record.update(status='capture_failed', reasons=['capture_process_failed'])
                frame = None
            finally:
                if session is not None:
                    session.close()
                    record['source_bytes'] = session.source_bytes
                record['timings']['capture_and_close_seconds'] = clock() - tick
            if frame is not None:
                tick = clock()
                try:
                    analyzed = analyze_frame(frame, requirements,
                        lambda crop: neural_line(crop, args.ocr_python, args.ocr_timeout),
                        max_age=args.max_age,
                        crop_dir=args.output.with_suffix('') / f'{index+1:04d}' if args.save_crops else None)
                    record['timings'].update(analyzed.pop('timings'))
                    record.update(analyzed)
                except (OSError, RuntimeError, ValueError) as error:
                    # Only CaptureError carries a safe reason; library messages may contain URLs.
                    record.update(status='recognition_failed', current=False,
                                  reasons=[str(error) if isinstance(error, CaptureError) else 'recognition_failed'])
                record['timings']['recognition_total_seconds'] = clock() - tick
            record['timings']['attempt_seconds'] = clock() - attempt_started
            emit(record)
            # No catch-up queue: skip elapsed schedule slots instead of replaying stale work.
            deadline += args.interval
            while deadline < clock():
                deadline += args.interval
    except KeyboardInterrupt:
        interrupted = True
    return dict(type='summary', attempts=attempted, interrupted=interrupted, trusted=False,
                wall_seconds=clock() - started)


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    try:
        if not 1 <= args.count <= 60:
            raise ValueError('count must be 1..60')
        for name, low, high in [('interval', 5, 300), ('timeout', 1, 30), ('max_age', 1, 30),
                                ('ocr_timeout', 1, 30), ('start', 0, 86400)]:
            value = getattr(args, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'{name} must be finite and {low}..{high}')
        if args.channel and not args.authorized:
            raise ValueError('Twitch requires --authorized: confirm streamer permission for this trial')
        if args.file and not args.file.is_file():
            raise ValueError('Video file not found')
        if not args.ocr_python.is_file() or not args.requirements.is_file():
            raise ValueError('Existing isolated OCR Python and requirements file are required')
        if not shutil.which('ffmpeg'):
            raise ValueError('FFmpeg must be installed on PATH')
        args.output = private_path(args.output)
        if args.output.exists() or args.save_crops and args.output.with_suffix('').exists():
            raise ValueError('Never overwrite existing diagnostic evidence')
        source = Source('file' if args.file else 'twitch', str(args.file) if args.file else args.channel,
                        args.quality)
        if args.channel:
            source.streamlink_command()  # Validate channel and rendition before connecting.
        table_bytes = args.requirements.read_bytes()
        table = json.loads(table_bytes)
        requirements = {int(key): value for key, value in table['to_next'].items()}
        infer_levels(None, None, requirements)  # Validate table without OCR predictions.
    except (OSError, ValueError, KeyError) as error:
        cli.error(str(error))
    os.environ['OMP_THREAD_LIMIT'] = '1'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    monitor = ResourceMonitor(sample_interval=.05, scope='serial shadow runner + capture + OCR children')
    try:
        with args.output.open('x', encoding='utf-8') as output:
            def emit(record):
                output.write(json.dumps({**record, 'resources': monitor.snapshot()}, allow_nan=False) + '\n')
                output.flush()
            emit(dict(type='configuration', trusted=False, interval=args.interval, count=args.count,
                      timeout=args.timeout, max_local_age=args.max_age, neural_timeout=args.ocr_timeout,
                      requirements_sha256=hashlib.sha256(table_bytes).hexdigest(),
                      table_provenance={key: value for key, value in table.items() if key != 'to_next'},
                      neural_scale=2, native_padding=2, queue_capacity=0, capture_mode='periodic_keyframes',
                      numerical_verification=False, character_identity_verified=False))
            summary = run(args, source, requirements, emit)
            monitor.close()
            emit(summary)
    finally:
        monitor.close()
    return 130 if summary['interrupted'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
