"""Bounded, sanitized read-only view of an explicitly selected private shadow log."""

from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import re
import stat

MAX_BYTES = 512 * 1024
MAX_LINE = 64 * 1024
MAX_LINES = 512
MAX_ROWS = 120
STATUSES = {'diagnostic_pair', 'malformed_or_unavailable', 'stale_local_frame',
            'capture_failed', 'recognition_failed', 'unavailable'}
REASONS = {'missing_hud', 'multiple_huds', 'local_receipt_age_exceeded', 'strict_pair_unavailable',
           'visual_level_unavailable', 'visual_level_failed', 'visual_unavailable', 'conflict',
           'unsupported_visual_level', 'localization_failed', 'neural_timeout', 'neural_worker_failed',
           'neural_failed', 'invalid_neural_response', 'exp_crop_exceeds_limit', 'recognition_failed',
           'offline_or_unavailable', 'access_denied', 'network_unavailable', 'source_ended',
           'decoder_failed', 'frame_timeout', 'capture_process_failed', 'frame_exceeds_byte_limit',
           'frame_exceeds_pixel_limit', 'invalid_decoder_output', 'invalid_png_header'}
RELATIONS = {'visual_unavailable', 'unsupported_visual_level', 'pair_unavailable', 'conflict',
             'agreement_not_verification', 'compatible_but_ambiguous'}


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc).isoformat() if parsed.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


def number(value, maximum):
    return value if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= maximum else None


def raw_text(value):
    # Not a number parser: suspicious/unbounded text is explicitly redacted, never repaired.
    return value if isinstance(value, str) and len(value) <= 160 and re.fullmatch(
        r'[0-9EXPexpOoIlSB.,\[\]()%? _\-\t]*', value) else None


def hypothesis(value):
    value = value if isinstance(value, dict) else {}
    levels = value.get('levels')
    if not isinstance(levels, list) or len(levels) > 200 or any(type(n) is not int or not 1 <= n <= 200 for n in levels):
        return dict(status='unavailable', levels=[])
    status = value.get('status')
    return dict(status=status if status in {'unique', 'ambiguous', 'incompatible', 'unavailable', 'invalid_input'} else 'unknown',
                levels=levels)


def observation(row):
    source = row.get('source') if isinstance(row.get('source'), dict) else {}
    channel = source.get('channel')
    channel = channel if isinstance(channel, str) and re.fullmatch(r'[A-Za-z0-9_]{1,25}', channel) else None
    neural = row.get('neural') if isinstance(row.get('neural'), dict) else {}
    text = neural.get('text')
    candidate = row.get('candidate')
    pair = None
    if isinstance(candidate, list) and len(candidate) == 2 and type(candidate[0]) is int and 0 <= candidate[0] <= 2**63-1:
        pct = number(candidate[1], 99.99)
        if pct is not None and Decimal(str(pct)) * 100 == (Decimal(str(pct)) * 100).to_integral_value():
            pair = dict(exp=str(candidate[0]), percentage=f'{pct:.2f}')
    evidence = row.get('level_evidence') if isinstance(row.get('level_evidence'), dict) else {}
    hypotheses = evidence.get('hypotheses') if isinstance(evidence.get('hypotheses'), dict) else {}
    visual = row.get('visual_level')
    reasons = row.get('reasons') if isinstance(row.get('reasons'), list) else []
    attempts = row.get('visual_attempts') if isinstance(row.get('visual_attempts'), list) else []
    return dict(index=row.get('index') if type(row.get('index')) is int and 1 <= row['index'] <= 10000 else None,
                channel=channel, source_kind=source.get('kind') if source.get('kind') in ('file', 'twitch') else 'unknown',
                attempted_at=timestamp(row.get('attempted_at')), received_at=timestamp(row.get('received_at')),
                status=row.get('status') if row.get('status') in STATUSES else 'unknown_status',
                reasons=[reason for reason in reasons[:32] if isinstance(reason, str) and reason in REASONS],
                candidate=pair, candidate_invalid=candidate is not None and pair is None,
                raw_text=raw_text(text), raw_text_redacted=text is not None and raw_text(text) is None,
                visual_level=visual if type(visual) is int and 1 <= visual <= 200 else None,
                visual_status=row.get('visual_status') if row.get('visual_status') in ('available', 'unavailable', 'failed', 'not_run') else 'unknown',
                neural_status=row.get('neural_status') if row.get('neural_status') in ('single_line', 'no_single_line', 'failed', 'not_run') else 'unknown',
                visual_attempts=[raw_text(a.get('text')) for a in attempts[:6] if isinstance(a, dict)],
                hypotheses={mode: hypothesis(hypotheses.get(mode)) for mode in ('nearest_half_up', 'truncate')},
                relation=evidence.get('relation') if evidence.get('relation') in RELATIONS else 'unavailable',
                local_age_seconds=number(row.get('local_age_seconds'), 86400),
                fresh_at_capture=row.get('current') is True, trusted=False)


class ShadowLog:
    def __init__(self, path):
        self.root = Path.cwd().resolve()
        self.path = Path(path).absolute()
        self.validate_path()

    def validate_path(self):
        resolved = self.path.resolve()
        if resolved.suffix.lower() != '.jsonl' or not any(
                resolved.is_relative_to(self.root / name) for name in ('private', 'artifacts')):
            raise ValueError('Shadow log must be a JSONL under the working directory private/ or artifacts/')
        return resolved

    def snapshot(self, now=None):
        now = now or datetime.now(timezone.utc)
        result = dict(trusted=False, served_at=now.isoformat(), log_status='ready', observations=[],
                      channel=None, source_status='waiting', age_seconds=None, stale=False,
                      interval_seconds=None, stale_after_seconds=45, malformed_lines=0,
                      incomplete_tail=False, truncated=False, bytes_read=0, poll_seconds=2)
        try:
            path = self.validate_path()  # Recheck replacement symlinks before every read.
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError('Not a regular file')
            with path.open('rb') as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise ValueError('Not a regular file')
                header = handle.readline(MAX_LINE + 1)
                handle.seek(0, 2)
                end = handle.tell()
                start = max(0, end - MAX_BYTES)
                handle.seek(start)
                payload = handle.read(min(end - start, MAX_BYTES))
                result['bytes_read'] = len(header) + len(payload)
                if start:
                    payload = payload.partition(b'\n')[2]  # Never parse a clipped leading line.
                    result['truncated'] = True
        except FileNotFoundError:
            return {**result, 'log_status': 'missing'}
        except (OSError, ValueError):
            return {**result, 'log_status': 'unavailable'}
        rows = deque(maxlen=MAX_ROWS)
        interval = None
        finished = None
        try:
            configuration = json.loads(header) if header.endswith(b'\n') and len(header) <= MAX_LINE else {}
            if isinstance(configuration, dict) and configuration.get('type') == 'configuration':
                interval = number(configuration.get('interval'), 300)
                interval = interval if interval and interval >= 1 else None
        except (ValueError, UnicodeError, RecursionError):
            pass
        lines = payload.split(b'\n')
        result['incomplete_tail'] = bool(lines[-1])
        completed = lines[:-1]
        result['truncated'] |= len(completed) > MAX_LINES
        for line in completed[-MAX_LINES:]:
            if not line.strip():
                continue
            try:
                if len(line) > MAX_LINE:
                    raise ValueError('Line exceeds limit')
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError('Expected object')
                if row.get('type') == 'attempt':
                    if len(rows) == MAX_ROWS:
                        result['truncated'] = True
                    rows.append(observation(row))
                    finished = None
                elif row.get('type') == 'summary':
                    finished = 'interrupted' if row.get('interrupted') is True else 'completed'
            except (ValueError, UnicodeError, TypeError, OverflowError, RecursionError):
                result['malformed_lines'] += 1
                result['truncated'] |= len(rows) == MAX_ROWS
                # Unknown evidence creates a visible timeline break, never a guessed observation.
                rows.append(dict(status='malformed_log_line', trusted=False, candidate=None,
                                 received_at=None, attempted_at=None))
        observations = list(rows)
        result.update(observations=observations, interval_seconds=interval,
                      stale_after_seconds=max(45, 3 * interval) if interval else 45)
        channels = {row.get('channel') for row in observations if row.get('channel')}
        result['channel'] = next(iter(channels)) if len(channels) == 1 else None
        result['mixed_channels'] = len(channels) > 1
        if observations:
            latest = observations[-1]
            result['source_status'] = ('offline_or_unavailable' if 'offline_or_unavailable' in latest.get('reasons', [])
                                       else latest['status'])
        last = next((row for row in reversed(observations) if row.get('attempted_at') or row.get('received_at')), None)
        if last:
            when = datetime.fromisoformat(last.get('received_at') or last['attempted_at'])
            age = (now - when).total_seconds()
            result['age_seconds'] = max(0, age)
            result['stale'] = age < 0 or age > result['stale_after_seconds']
        result['run_status'] = finished or ('unfinished' if observations else 'waiting')
        return result
