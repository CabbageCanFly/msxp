"""Bounded, serial capture -> experimental OCR diagnostics. Never trusted ingestion."""

import argparse
from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import shutil
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from exp_tracker.metrics import ResourceMonitor
from exp_tracker.recognition import ocr_engine
from exp_tracker.video import CaptureError, Source, VideoSession
from exp_tracker.shadow_types import parse_percentage_only, partial_percentage
from exp_tracker.store import Store
from exp_tracker.diagnostics import Diagnostics
from adaptive_hud import CachedLocator, locate, level_reading
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


class ResidentNeural:
    """Reused recognizer processes (one per command), so import/model load is paid once.

    Requests are serialized (inference is ~25 ms). A timeout, failure or oversized reply kills
    that process; the next request starts a fresh one.
    """

    def __init__(self):
        self.lock=threading.Lock()
        self.processes={}

    @staticmethod
    def _send(process, data):
        try:
            process.stdin.write(data)
            process.stdin.flush()
        except (OSError, ValueError):
            pass  # A dead worker surfaces as EOF to the reader.

    @staticmethod
    def _read(process, lines):
        try:
            while line := process.stdout.readline(65537):
                lines.put(line)
        except (OSError, ValueError):
            pass
        lines.put(b'')

    def __call__(self, command, payload, timeout, *, metrics=None):
        command=(*command,'--serve')
        queued=time.monotonic() if metrics is not None else None
        with self.lock:
            if metrics is not None:
                metrics['queue_wait_seconds']=time.monotonic()-queued
            process,lines=self.processes.get(command,(None,None))
            if process is None or process.poll() is not None:
                self._stop(command)
                try:
                    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
                except OSError:
                    raise CaptureError('neural_worker_failed') from None
                lines=queue.Queue()
                self.processes[command]=(process,lines)
                threading.Thread(target=self._read,args=(process,lines),daemon=True).start()
            # Write off-thread: a hung worker with a full pipe must not outlive the timeout.
            threading.Thread(target=self._send,args=(process,struct.pack('!I',len(payload))+payload),daemon=True).start()
            try:
                line=lines.get(timeout=timeout)
            except queue.Empty:
                self._stop(command)
                raise CaptureError('neural_timeout') from None
            if not line.endswith(b'\n') or len(line)>65536:
                self._stop(command)
                raise CaptureError('neural_worker_failed')
            return line

    def _stop(self, command):
        process,_=self.processes.pop(command,(None,None))
        if process is None:
            return
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        for pipe in (process.stdin,process.stdout):
            try:
                pipe.close()
            except OSError:
                pass

    def close(self):
        # Lock-free: at shutdown an abandoned attempt may still hold the lock.
        for command in list(self.processes):
            self._stop(command)


def neural_line(crop, python, timeout, level_crop=None, *, experimental_neural_level=False, resident=None, metrics=None):
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
    if resident is not None:
        stdout=resident(command,payload,timeout,**({'metrics':metrics} if metrics is not None else {}))
    else:
        try:
            result = subprocess.run(command,
                                    input=payload, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise CaptureError('neural_timeout') from None
        if result.returncode or len(result.stdout) > 65536:
            raise CaptureError('neural_worker_failed')
        stdout=result.stdout
    try:
        response=json.loads(stdout)
        json.dumps(response,allow_nan=False)
        if not isinstance(response,dict) or 'text' not in response or (
                response['text'] is not None and (not isinstance(response['text'],str) or len(response['text'])>160)):
            raise ValueError('Invalid EXP response')
        if experimental_neural_level:
            response['neural_level']=empty_level('invalid_crop') if invalid_level else checked_level(response.get('neural_level'))
            response['worker_wall_seconds']=time.monotonic()-started
        if metrics is not None:
            response['request_metrics']={**metrics,'bridge_seconds':time.monotonic()-started}
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
            read_level=level_reading, clock=time.monotonic, crop_dir=None, experimental_neural_level=False,
            identity=None, read_name=None):
    """No value reuse. Even completed stale work is explicitly ineligible/current=false."""
    result = dict(status='unavailable', trusted=False, current=False, reasons=[], timings={},
                  candidate=None, visual_level=None, visual_attempts=[], neural=None,
                  diagnostic_type='unavailable', percentage_only_candidate=None, partial_percentage_evidence=None,
                  visual_status='not_run', neural_status='not_run',
                  localization=None, level_evidence=level_evidence(None, None, requirements))
    if experimental_neural_level:
        result['neural_level']=empty_level('not_run')
    image, candidates = None, []

    def finish():
        if identity is not None:
            result['character_name']=identity.inspect(result,frame,image,candidates,read_name,requirements,
                                                       max_age=max_age,clock=clock)
            result['timings']['character_name_seconds']=result['character_name']['evidence']['seconds']
        return result

    def fresh():
        result['local_age_seconds'] = max(0, clock() - frame.arrived_monotonic)
        if result['local_age_seconds'] > max_age:
            result['status'] = 'stale_local_frame'
            result['reasons'].append('local_receipt_age_exceeded')
            return False
        return True

    if not fresh():
        return finish()
    started = clock()
    image = frame.image()
    result['frame_size'] = image.size
    try:
        candidates = locator(image)
    except (OSError, RuntimeError, ValueError) as error:
        result['reasons'].append('localization_failed')
        if isinstance(error,CaptureError) and str(error) in {
                'tesseract_worker_request_timeout','tesseract_worker_start_timeout',
                'tesseract_worker_failed','tesseract_worker_unavailable','tesseract_worker_closed',
                'tesseract_worker_invalid_layout_reply'}:
            result['reasons'].append(str(error))
        result['timings']['localization_seconds'] = clock() - started
        fresh()
        return finish()
    result['timings']['localization_seconds'] = clock() - started
    result['localization'] = dict(count=len(candidates), candidates=[
        {**candidate, 'regions': {key: asdict(region) if region is not None else None
                                for key, region in candidate['regions'].items()}}
        for candidate in candidates], target_identity_verified=False)
    if not fresh():
        return finish()
    if len(candidates) != 1:
        result['reasons'].append('missing_hud' if not candidates else 'multiple_huds')
        return finish()
    regions = candidates[0]['regions']
    box = context_box(regions['exp'], image.size, 2)
    crop = image.crop(box)
    level_crop = image.crop(regions['level'].pixels(*image.size)) if regions['level'] is not None else None
    result['exp_crop_box'] = box
    if crop_dir:
        crop_dir.mkdir(parents=True, exist_ok=False)
        crop.save(crop_dir / 'exp.png')
        if level_crop is not None:
            level_crop.save(crop_dir / 'level.png')
    started = clock()
    try:
        response=read_line(crop,level_crop) if experimental_neural_level else read_line(crop)
        result['neural']=dict(response)
        if experimental_neural_level:
            value=result['neural'].pop('neural_level',None)
            result['neural_level']=checked_level(value) if level_crop is not None else empty_level('missing_crop')
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
        return finish()
    started = clock()
    try:
        visual, attempts = read_level(level_crop) if level_crop is not None else (None,[])
        result['visual_status'] = 'available' if visual is not None else 'unavailable'
    except (OSError, RuntimeError, ValueError):
        visual, attempts = None, []
        result['visual_status'] = 'failed'
        result['reasons'].append('visual_level_failed')
    result['timings']['visual_level_seconds'] = clock() - started
    result['visual_level'], result['visual_attempts'] = visual, attempts
    result['level_evidence'] = level_evidence(result['candidate'], visual, requirements)
    if not fresh():
        return finish()
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
    return finish()


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
    cli.add_argument('--requirements', type=Path, default=ROOT / 'src/exp_tracker/data/community-exp-v2.json',
                     help='Explicit diagnostic table; default community v2 selects agreeing levels 1–89, not disputed 90–99')
    cli.add_argument('--output', type=Path, required=True)
    cli.add_argument('--save-crops', action='store_true', help='Save only field crops beside the NEW JSONL')
    cli.add_argument('--experimental-neural-level',action='store_true',help='Opt in to UNVERIFIED neutral4 level diagnostics in the existing neural worker')
    cli.add_argument('--character-names',action='store_true',help='No-DB review of name suggestions from local video or authorized Twitch; use multi_alpha for isolated automatic tracking')
    cli.add_argument('--name-interval',type=float,default=0,help='Name check interval in seconds; 0 checks every eligible capture. Numeric events and confirmation bypass it')
    cli.add_argument('--resident-neural',action='store_true',help='Reuse the existing neural worker for EXP, level and optional names')
    cli.add_argument('--hud-cache-seconds',type=float,default=0,help='Optional existing regional HUD cache; competing HUDs can go unseen until refresh')
    cli.add_argument('--db', type=Path, help='Opt in to separate SQLite diagnostic persistence; initialize/select/start first')
    cli.add_argument('--tracking-channel', help='Explicit DB channel assignment for a local video only')
    return cli


def capture_attempt(args, source, requirements, index, *, seek=None, session_factory=ShadowSession,
                    analyze_frame=analyze, clock=time.monotonic, resident=None, identity=None, tesseract=None, streamlink=None):
    """One bounded acquisition/OCR operation, shared by coordinators; resident reuses a neural worker.

    tesseract (a resident_tesseract.TesseractPool) serves this attempt's Tesseract calls, on this
    thread only; without it each call runs the Tesseract CLI.
    """
    attempt_started = clock()
    record = dict(type='attempt', index=index, trusted=False, current=False,
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
        session = session_factory(source, file_offset=seek or 0,
            **({'producer_factory':streamlink} if streamlink is not None and source.kind!='file' else {}))
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
        ocr = {}
        scope = ocr_engine.set(lambda image, psm, whitelist: tesseract(image, psm, whitelist, metrics=ocr)) if tesseract else None
        try:
            experimental=getattr(args,'experimental_neural_level',False)
            reader=(lambda crop,level: neural_line(crop,args.ocr_python,args.ocr_timeout,level,
                     experimental_neural_level=True,resident=resident)) if experimental else (
                     lambda crop: neural_line(crop,args.ocr_python,args.ocr_timeout,resident=resident))
            options={'experimental_neural_level':True} if experimental else {}
            if identity is not None:
                def read_name(crop):
                    return neural_line(crop,args.ocr_python,min(2,args.ocr_timeout),
                        experimental_neural_level=experimental,resident=resident,metrics={})
                options.update(identity=identity,read_name=read_name)
            with ExitStack() as stack:
                layout=None
                if tesseract is not None and getattr(args,'layout_first_hud',False):
                    from layout_first_hud import LayoutLocator
                    pages=stack.enter_context(tesseract.layout_pages(metrics=ocr))
                    layout=LayoutLocator(None,None,reader,experimental=experimental,pages=pages)
                    options['locator']=layout;reader=layout.read
                analyzed = analyze_frame(frame, requirements, reader,
                    max_age=args.max_age,
                    crop_dir=args.output.with_suffix('') / f'{index:04d}' if args.save_crops else None,**options)
                if layout is not None:analyzed['hud_layout']=layout.info
            record['timings'].update(analyzed.pop('timings'))
            record.update(analyzed)
        except (OSError, RuntimeError, ValueError) as error:
            # Only CaptureError carries a safe reason; library messages may contain URLs.
            record.update(status='recognition_failed', current=False,
                          reasons=[str(error) if isinstance(error, CaptureError) else 'recognition_failed'])
        finally:
            if scope is not None:
                ocr_engine.reset(scope)
        record['timings'].update(ocr)
        record['timings']['recognition_total_seconds'] = clock() - tick
    if identity is not None and 'character_name' not in record:
        # No analyzed fields were merged, so there is no reading to attribute or hold.
        record['character_name']=dict(evidence=dict(status='capture_or_recognition_failed',trusted=False),
            suggestion=identity.missing(record.get('received_at',record['attempted_at'])),
            reading_hold_recommended=False,hold_reasons=[],tracking_action='none')
    record['timings']['attempt_seconds'] = clock() - attempt_started
    return record


def run(args, source, requirements, emit, *, session_factory=ShadowSession, analyze_frame=analyze,
        clock=time.monotonic, sleep=time.sleep, on_activity=None, resident=None, identity=None):
    started = clock()
    deadline = started
    attempted = 0
    interrupted = False
    try:
        for index in range(args.count):
            sleep(max(0, deadline - clock()))
            if on_activity:on_activity(dict(state='running',updated_at=datetime.now(timezone.utc).isoformat(),
                expected_completion_seconds=args.timeout+args.ocr_timeout+15))
            attempted += 1
            seek = args.start + clock() - started if source.kind == 'file' else None
            record = capture_attempt(args, source, requirements, index+1, seek=seek,
                session_factory=session_factory, analyze_frame=analyze_frame, clock=clock,
                **({'resident':resident} if resident is not None else {}),
                **({'identity':identity} if identity is not None else {}))
            emit(record)
            # No catch-up queue: skip elapsed schedule slots instead of replaying stale work.
            deadline += args.interval
            while deadline < clock():
                deadline += args.interval
            if on_activity:on_activity(dict(state='capture_failing' if record.get('status')=='capture_failed' else 'waiting',
                updated_at=datetime.now(timezone.utc).isoformat(),
                next_due_at=(datetime.now(timezone.utc)+timedelta(seconds=max(0,deadline-clock()))).isoformat()))
    except KeyboardInterrupt:
        interrupted = True
    return dict(type='summary', attempts=attempted, interrupted=interrupted, trusted=False,
                wall_seconds=clock() - started)


def prepare(args, *, allow_missing_video=False, offline_fast_test=False):
    """Shared offline preflight. No database writes or remote connections."""
    if not 1 <= args.count <= 60:
        raise ValueError('count must be 1..60')
    if getattr(args,'character_names',False) and args.db:
        raise ValueError('Standalone --character-names requires no --db; use multi_alpha for identity-aware persistence')
    for name, high in [('name_interval',3600),('hud_cache_seconds',3600)]:
        value=getattr(args,name,0)
        if not math.isfinite(value) or not 0<=value<=high:
            raise ValueError(f'{name} must be finite and 0..{high}')
    if getattr(args,'name_interval',0) and not getattr(args,'character_names',False):
        raise ValueError('--name-interval requires --character-names')
    if offline_fast_test and (args.channel or not args.file):
        raise ValueError('Offline fast testing requires a local video, never Twitch')
    for name, low, high in [('interval', 3 if offline_fast_test else 5, 300), ('timeout', 1, 30), ('max_age', 1, 30),
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
    if args.file and not args.file.is_file() and not allow_missing_video:
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


def configuration(args, table_bytes, table, run_id=None):
    return dict(type='configuration', trusted=False, interval=args.interval, count=args.count,
        timeout=args.timeout, max_local_age=args.max_age, neural_timeout=args.ocr_timeout,
        requirements_sha256=hashlib.sha256(table_bytes).hexdigest(),
        table_provenance={key: value for key, value in table.items() if key != 'to_next'},
        neural_scale=2, native_padding=2, queue_capacity=0, capture_mode='periodic_keyframes',
        numerical_verification=False, character_identity_verified=False,
        **({'run_id': run_id} if run_id else {}),
        **({'experimental_neural_level': True, 'neural_level_preprocessing': 'neutral4'}
           if args.experimental_neural_level else {}),
        **({'character_names':True,'name_interval_seconds':args.name_interval,
            'identity_policy':'autonomous_two_frame_v1' if getattr(args,'automatic_characters',False) else 'review_only_v2'}
           if getattr(args,'character_names',False) else {}),
        **({'automatic_characters':True,'level_policy':'monotone_two_frame_v1'}
           if getattr(args,'automatic_characters',False) else {}),
        **({'resident_neural':True} if getattr(args,'resident_neural',False) or getattr(args,'character_names',False) else {}),
        **({'hud_cache_seconds':args.hud_cache_seconds} if getattr(args,'hud_cache_seconds',0) else {}))


def main(argv=None, *, on_record=None, on_activity=None):
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
    resident = ResidentNeural() if args.resident_neural or args.character_names else None
    if resident: stack.callback(resident.close)
    options={}
    if resident: options['resident']=resident
    if args.hud_cache_seconds:
        from functools import partial
        options['analyze_frame']=partial(analyze,locator=CachedLocator(args.hud_cache_seconds))
    if args.character_names:
        from character_identity import IdentityCapture
        options['identity']=IdentityCapture(args.channel or str(args.file.resolve()),interval=args.name_interval)
    try:
        with args.output.open('x', encoding='utf-8') as output:
            run_id = uuid.uuid4().hex if diagnostics else None
            def emit(record):
                record = {**record, 'resources': monitor.snapshot()}
                output.write(json.dumps(record, allow_nan=False) + '\n')
                output.flush()
                if args.character_names and record['type']=='attempt':
                    name=record.get('character_name',{})
                    suggestion,evidence=name.get('suggestion',{}),name.get('evidence',{})
                    print(json.dumps(dict(index=record['index'],proposed_name=suggestion.get('proposed_name'),
                        pending_switch=(suggestion.get('pending_switch') or {}).get('name'),
                        observed_name=evidence.get('name'),status=suggestion.get('latest_status'),
                        numeric_reason=(name.get('numeric_check') or {}).get('classification'),
                        verification_requested=name.get('verification_requested'),
                        reading_hold_recommended=name.get('reading_hold_recommended'),hold_reasons=name.get('hold_reasons'),
                        source_evidence={k:evidence.get(k) for k in ('received_at','pixel_sha256','box','score')},
                        trusted=False),allow_nan=False),flush=True)
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
            emit(configuration(args, table_bytes, table, run_id))
            summary = run(args, source, requirements, emit,**options,**({'on_activity':on_activity} if on_activity else {}))
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
