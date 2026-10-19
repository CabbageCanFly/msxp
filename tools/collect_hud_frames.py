"""Opt-in native full-frame evidence collection; no localization, OCR or database."""

import argparse
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import sys
import time

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from exp_tracker.video import CaptureError, MAX_PIXELS, MAX_PNG_BYTES, Source, VideoSession

MAX_ATTEMPTS = 10
MAX_SECONDS = 60


class DiagnosticSession(VideoSession):
    def __init__(self, *args, **kwargs):
        try:
            super().__init__(*args, **kwargs)
        except KeyboardInterrupt:
            # Match shadow capture's cleanup of interrupted partial startup.
            self.close()
            raise


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    source = cli.add_mutually_exclusive_group(required=True)
    source.add_argument('--file', type=Path, help='Existing authorized local video')
    source.add_argument('--channel', help='Single Twitch login, never a playback URL')
    cli.add_argument('--authorized', action='store_true', help='Confirm streamer permission for THIS Twitch trial')
    cli.add_argument('--quality', default='best', help='Named Twitch rendition/selector; ignored for local video')
    cli.add_argument('--count', type=int, default=3, help='Distinct frames requested, 1..5')
    cli.add_argument('--timeout', type=float, default=10, help='Per-frame wait, 1..20 seconds')
    cli.add_argument('--interval', type=float, default=5, help='Pause between attempts, 1..10 seconds')
    cli.add_argument('--start', type=float, default=0, help='Local video seek request, 0..86400 seconds')
    cli.add_argument('--output', type=Path, required=True, help='NEW collection directory directly under private/obscured-hud/')
    return cli


def prepare(args):
    if not 1 <= args.count <= 5:
        raise ValueError('count must be 1..5')
    for name, low, high in (('timeout', 1, 20), ('interval', 1, 10), ('start', 0, 86400)):
        if not math.isfinite(getattr(args, name)) or not low <= getattr(args, name) <= high:
            raise ValueError(f'{name} must be finite and {low}..{high}')
    if args.channel is not None:
        if not args.authorized:
            raise ValueError('Twitch requires --authorized: confirm streamer permission for this trial')
        if args.start:
            raise ValueError('--start is only for local video')
        source = Source('twitch', args.channel.lower(), args.quality)
        source.streamlink_command()  # Reuse login/rendition validation before any connection or output.
    else:
        if not args.file.is_file():
            raise ValueError('An existing authorized local video is required')
        source = Source('file', str(args.file.resolve()))
    if args.output.exists() or args.output.is_symlink():
        raise ValueError('Never overwrite an existing output file or directory')
    output = args.output.resolve()
    if output.parent != ROOT / 'private' / 'obscured-hud':
        raise ValueError('Output must be a new directory directly under private/obscured-hud/')
    return source, output


def collect(args, *, session_factory=DiagnosticSession, clock=time.monotonic, sleep=time.sleep):
    source, output = prepare(args)
    output.mkdir(parents=True, exist_ok=False)
    manifest = dict(version=1, trusted=False,
        source=dict(kind=source.kind, channel=source.value if source.kind == 'twitch' else None,
            identity_sha256=hashlib.sha256(json.dumps([source.kind, source.value]).encode()).hexdigest(),
            requested_rendition=source.quality if source.kind == 'twitch' else None,
            requested_video_offset_seconds=args.start if source.kind == 'file' else None,
            verified_source_pts=None, source_age_known=False),
        limits=dict(requested_frames=args.count, max_frames=5, max_attempts=MAX_ATTEMPTS,
            collection_seconds=MAX_SECONDS, frame_timeout_seconds=args.timeout,
            interval_seconds=args.interval, max_local_age_seconds=5,
            max_png_bytes=MAX_PNG_BYTES, max_pixels=MAX_PIXELS),
        frames=[], attempts=[], status='incomplete', stop_reason='attempt_limit')
    started = clock()
    deadline = started + MAX_SECONDS
    session = None
    seen = set()
    sequence = 0
    with (output / 'manifest.json').open('x', encoding='utf-8') as handle:
        try:
            session = session_factory(source, file_offset=args.start)
            for index in range(1, MAX_ATTEMPTS + 1):
                remaining = deadline - clock()
                if remaining <= 0:
                    manifest['stop_reason'] = 'collection_deadline'
                    break
                attempt = dict(index=index, outcome='capture_failed')
                manifest['attempts'].append(attempt)
                try:
                    frame = session.frame(after_sequence=sequence,
                        timeout=min(args.timeout, remaining), max_age=5)
                except CaptureError as error:
                    # Never persist raw exceptions, subprocess stderr or signed URLs.
                    attempt['outcome'] = 'frame_timeout' if str(error) == 'frame_timeout' else 'capture_failed'
                    if attempt['outcome'] != 'frame_timeout':
                        manifest['stop_reason'] = 'capture_failed'
                        break
                else:
                    sequence = frame.sequence
                    age = clock() - frame.arrived_monotonic
                    if clock() >= deadline:
                        attempt['outcome'] = 'deadline_exceeded'
                        manifest['stop_reason'] = 'collection_deadline'
                        break
                    if not 0 <= age <= 5:
                        attempt['outcome'] = 'stale_local_frame'
                    elif len(frame.png) > MAX_PNG_BYTES:
                        raise ValueError('Frame exceeds PNG byte limit')
                    else:
                        digest = hashlib.sha256(frame.png).hexdigest()
                        if digest in seen:
                            attempt['outcome'] = 'duplicate'
                        else:
                            with Image.open(BytesIO(frame.png)) as image:
                                width, height = image.size
                                if image.format != 'PNG' or not 0 < width * height <= MAX_PIXELS:
                                    raise ValueError('Invalid native PNG geometry')
                                image.verify()
                            filename = f'frame-{len(seen) + 1:02d}.png'
                            with (output / filename).open('xb') as png:
                                png.write(frame.png)
                            seen.add(digest)
                            manifest['frames'].append(dict(file=filename, sha256=digest,
                                width=width, height=height, png_bytes=len(frame.png),
                                received_at=frame.received_at, sequence=frame.sequence,
                                local_age_seconds=age))
                            attempt['outcome'] = 'saved'
                    if len(seen) == args.count:
                        manifest.update(status='complete', stop_reason='requested_count_reached')
                        break
                if index < MAX_ATTEMPTS:
                    sleep(max(0, min(args.interval, deadline - clock())))
        except KeyboardInterrupt:
            manifest['stop_reason'] = 'operator_interrupted'
        except (OSError, RuntimeError, ValueError):
            manifest['stop_reason'] = 'collection_failed'
        finally:
            try:
                if session is not None:
                    session.close()
            finally:
                manifest.update(distinct_frames=len(seen),
                    fewer_distinct_frames=len(seen) < args.count,
                    wall_seconds=clock() - started)
                json.dump(manifest, handle, indent=2, allow_nan=False)
                handle.write('\n')
    return manifest


def main(argv=None, *, session_factory=DiagnosticSession):
    args = parser().parse_args(argv)
    try:
        result = collect(args, session_factory=session_factory)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, RuntimeError):
        print('Diagnostic collection failed; preserve any partial output.', file=sys.stderr)
        return 1
    print(f"Saved {result['distinct_frames']}/{args.count} distinct frames; {result['stop_reason']}.")
    if result['stop_reason'] == 'operator_interrupted':
        return 130
    return 0 if result['status'] == 'complete' else 2


if __name__ == '__main__':
    raise SystemExit(main())
