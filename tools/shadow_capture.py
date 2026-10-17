"""Bounded, serial capture -> experimental OCR diagnostics. Never trusted ingestion."""

import argparse
from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from exp_tracker.metrics import ResourceMonitor
from exp_tracker.video import CaptureError, Source, VideoSession
from exp_tracker.shadow_types import parse_percentage_only, partial_percentage
from exp_tracker.store import Store
from exp_tracker.diagnostics import Diagnostics
from adaptive_hud import locate, level_reading
from analyze_temporal_ocr import complete_pair
from benchmark_rapidocr import context_box, interpret
from infer_exp_level import infer_levels
from shadow_neural import EXP_SIZE, png_bytes, pack, checked_level, empty_level


class ShadowSession(VideoSession):
    def __init__(self, *args, **kwargs):
        try:
            super().__init__(*args, **kwargs)
        except KeyboardInterrupt:
            # The production constructor handles OSError; also close partial startup on Ctrl+C.
            self.close()
            raise


def neural_line(crop, python, timeout, level_crop=None, *, experimental_neural_level=False):
    invalid_level=False
    try:
        payload = pack(crop,level_crop) if experimental_neural_level else png_bytes(crop,EXP_SIZE)
    except ValueError:
        if not experimental_neural_level:
            raise CaptureError('exp_crop_exceeds_limit') from None
        try:
            payload=pack(crop,None)
        except ValueError:
            raise CaptureError('exp_crop_exceeds_limit') from None
        invalid_level=True
    command=[str(python),str(ROOT/'tools/shadow_rapidocr.py')]
    if experimental_neural_level:
        command.append('--experimental-neural-level')
    started=time.monotonic()
    try:
        result = subprocess.run(command,
                                input=payload, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise CaptureError('neural_timeout') from None
    if result.returncode or len(result.stdout) > 65536:
        raise CaptureError('neural_worker_failed')
    try:
        response=json.loads(result.stdout)
        json.dumps(response,allow_nan=False)
        if not isinstance(response,dict) or 'text' not in response or (
                response['text'] is not None and (not isinstance(response['text'],str) or len(response['text'])>160)):
            raise ValueError('Invalid EXP response')
        if experimental_neural_level:
            response['neural_level']=empty_level('invalid_crop') if invalid_level else checked_level(response.get('neural_level'))
            response['worker_wall_seconds']=time.monotonic()-started
        return response
    except (ValueError, UnicodeError, RecursionError):
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
            read_level=level_reading, clock=time.monotonic, crop_dir=None, experimental_neural_level=False):
    """No value reuse. Even completed stale work is explicitly ineligible/current=false."""
    result = dict(status='unavailable', trusted=False, current=False, reasons=[], timings={},
                  candidate=None, visual_level=None, visual_attempts=[], neural=None,
                  diagnostic_type='unavailable', percentage_only_candidate=None, partial_percentage_evidence=None,
                  visual_status='not_run', neural_status='not_run',
                  localization=None, level_evidence=level_evidence(None, None, requirements))
    if experimental_neural_level:
        result['neural_level']=empty_level('not_run')

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
    level_crop = image.crop(regions['level'].pixels(*image.size))
    result['exp_crop_box'] = box
    if crop_dir:
        crop_dir.mkdir(parents=True, exist_ok=False)
        crop.save(crop_dir / 'exp.png')
        level_crop.save(crop_dir / 'level.png')
    started = clock()
    try:
        response=read_line(crop,level_crop) if experimental_neural_level else read_line(crop)
        result['neural']=dict(response)
        if experimental_neural_level:
            result['neural_level']=checked_level(result['neural'].pop('neural_level',None))
        result['neural_status'] = 'single_line' if result['neural']['text'] is not None else 'no_single_line'
    except (OSError, RuntimeError, ValueError) as error:
        result['neural_status'] = 'failed'
        if experimental_neural_level:
            result['neural_level']=empty_level('failed')
        result['reasons'].append(str(error) if isinstance(error, CaptureError) else 'neural_failed')
    result['timings']['neural_bridge_seconds'] = clock() - started
    if result['neural'] is not None:
        result['parsed_diagnostic'] = interpret(result['neural']['text'])
        result['candidate'] = complete_pair(result['neural']['text'])
        if result['candidate'] is not None:
            result['diagnostic_type'] = 'full_exp_pair'
        else:
            result['percentage_only_candidate'] = parse_percentage_only(result['neural']['text'])
            if result['percentage_only_candidate'] is not None:
                result['diagnostic_type'] = 'percentage_only'
            else:
                result['partial_percentage_evidence'] = partial_percentage(result['parsed_diagnostic']['percentage'])
    if not fresh():
        return result
    started = clock()
    try:
        visual, attempts = read_level(level_crop)
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
    result['status'] = ('diagnostic_pair' if result['candidate'] is not None else
                        'diagnostic_percentage_only' if result['percentage_only_candidate'] is not None else
                        'malformed_or_unavailable')
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
    cli.add_argument('--experimental-neural-level',action='store_true',help='Opt in to UNVERIFIED neutral4 level diagnostics in the existing neural worker')
    cli.add_argument('--db', type=Path, help='Opt in to separate SQLite diagnostic persistence; initialize/select/start first')
    cli.add_argument('--tracking-channel', help='Explicit DB channel assignment for a local video only')
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
                          diagnostic_type='unavailable', percentage_only_candidate=None, partial_percentage_evidence=None,
                          visual_status='not_run', neural_status='not_run',
                          level_evidence=level_evidence(None, None, requirements))
            if getattr(args,'experimental_neural_level',False):
                record['neural_level']=empty_level('not_run')
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
                    experimental=getattr(args,'experimental_neural_level',False)
                    reader=(lambda crop,level: neural_line(crop,args.ocr_python,args.ocr_timeout,level,
                             experimental_neural_level=True)) if experimental else (
                             lambda crop: neural_line(crop,args.ocr_python,args.ocr_timeout))
                    options={'experimental_neural_level':True} if experimental else {}
                    analyzed = analyze_frame(frame, requirements, reader,
                        max_age=args.max_age,
                        crop_dir=args.output.with_suffix('') / f'{index+1:04d}' if args.save_crops else None,**options)
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


def prepare(args):
    """Shared offline preflight. No database writes or remote connections."""
    if not 1 <= args.count <= 60:
        raise ValueError('count must be 1..60')
    for name, low, high in [('interval', 5, 300), ('timeout', 1, 30), ('max_age', 1, 30),
                            ('ocr_timeout', 1, 30), ('start', 0, 86400)]:
        value = getattr(args, name)
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{name} must be finite and {low}..{high}')
    if args.channel and not args.authorized:
        raise ValueError('Twitch requires --authorized: confirm streamer permission for this trial')
    if args.tracking_channel and (not args.db or args.channel):
        raise ValueError('--tracking-channel requires --db with a local video')
    if args.db and not (args.channel or args.tracking_channel):
        raise ValueError('--db requires an explicit channel assignment')
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
    return source, table_bytes, table, requirements


def main(argv=None, *, on_record=None):
    cli = parser()
    args = cli.parse_args(argv)
    stack = ExitStack()
    try:
        source, table_bytes, table, requirements = prepare(args)
        if args.db and not args.db.is_file():
            raise ValueError('Existing --db is required; initialize/select/start first')
        diagnostics = Diagnostics(stack.enter_context(Store(args.db))) if args.db else None
        if diagnostics:
            # Fail before connecting. Actual immutable binding is created with the configuration below.
            state = diagnostics.store.state(args.channel or args.tracking_channel)
            if not state['session'] or state['session']['character_id'] != state['selected_character_id']:
                raise ValueError('Explicitly select a character and start a session first')
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        stack.close()
        cli.error(str(error))
    os.environ['OMP_THREAD_LIMIT'] = '1'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    monitor = ResourceMonitor(sample_interval=.05, scope='serial shadow runner + capture + OCR children')
    try:
        with args.output.open('x', encoding='utf-8') as output:
            run_id = uuid.uuid4().hex if diagnostics else None
            def emit(record):
                record = {**record, 'resources': monitor.snapshot()}
                output.write(json.dumps(record, allow_nan=False) + '\n')
                output.flush()
                try:
                    if diagnostics:
                        if record['type'] == 'configuration':
                            diagnostics.begin(run_id, args.channel or args.tracking_channel, record)
                        else:
                            diagnostics.append(run_id, record)
                except (ValueError, sqlite3.Error):
                    if on_record:
                        on_record(record, False)
                    raise
                if on_record:
                    on_record(record, diagnostics is not None)
            emit(dict(type='configuration', trusted=False, interval=args.interval, count=args.count,
                      timeout=args.timeout, max_local_age=args.max_age, neural_timeout=args.ocr_timeout,
                      requirements_sha256=hashlib.sha256(table_bytes).hexdigest(),
                      table_provenance={key: value for key, value in table.items() if key != 'to_next'},
                      neural_scale=2, native_padding=2, queue_capacity=0, capture_mode='periodic_keyframes',
                      numerical_verification=False, character_identity_verified=False,
                      **({'run_id':run_id} if diagnostics else {}),
                      **({'experimental_neural_level':True,'neural_level_preprocessing':'neutral4'}
                         if args.experimental_neural_level else {})))
            summary = run(args, source, requirements, emit)
            monitor.close()
            emit(summary)
    except (OSError, ValueError, sqlite3.Error) as error:
        print('Shadow capture/persistence stopped; inspect the private JSONL and explicit session assignment', file=sys.stderr)
        return 1
    finally:
        monitor.close()
        stack.close()
    return 130 if summary['interrupted'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
