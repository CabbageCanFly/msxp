"""Capture recent video frames and emit OCR/transition results and measured JSON metrics."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from importlib.util import find_spec
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time

from .models import Region
from .parsing import parse_exp
from .glyphs import GlyphProfile
from .recognition import recognize
from .validation import Observation, validate_transition
from .video import CaptureError, Source, VideoSession



def _guard_unverified_exp(result, profile):
    """Never promote a Tesseract-only EXP guess when a glyph profile was supplied.

    Preserve the candidate and raw attempts for debugging, but only glyph-verified
    EXP may advance live tracking state. This does not impose an EXP gain-rate cap.
    """
    if profile is None or result.status != "accepted":
        return result
    pixel_matches = [parse_exp(a.get("text") or "")
                     for a in result.raw.get("exp", []) if a.get("variant") == "pixel"]
    verified = result.reading is not None and (
        result.reading.current_exp, result.reading.percentage) in pixel_matches
    if not verified:
        result.status = "low_confidence"
        result.confidence = 0.0
        result.reasons.append("unverified_tesseract_exp")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--channel", help="Authorized public Twitch channel login")
    source_group.add_argument("--hls", help="Authorized HTTP(S) HLS playlist, including localhost test source")
    source_group.add_argument("--file", type=Path, help="Local video; periodic mode seeks by elapsed wall time")
    parser.add_argument("--quality", default="best", help="Streamlink rendition, e.g. 1080p60 or best; no silent fallback")
    parser.add_argument("--mode", choices=("periodic", "persistent"), default="periodic")
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--max-frame-age", type=float, default=5, help="Maximum age since LOCAL decoder delivery, not broadcast age")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--glyph-profile", type=Path, help="Require glyph-verified EXP for tracking; Tesseract fallback is diagnostic")
    parser.add_argument("--pixel-scale", type=float, action="append", help="Explicit glyph scale(s), default 1")
    parser.add_argument("--debug-dir", type=Path, help="Opt-in field crops only; use ignored artifacts/ or private/")
    parser.add_argument("--character", default="selected-character", help="Explicit logical character; never inferred from pixels")
    parser.add_argument("--full-decode", action="store_true", help="Decode all frames instead of keyframes only (CPU comparison)")
    parser.add_argument("--ffmpeg", default=os.environ.get("FFMPEG_CMD", "ffmpeg"))
    args = parser.parse_args(argv)
    if not all(math.isfinite(x) and x > 0 for x in (args.interval, args.timeout, args.max_frame_age)) or args.interval < 1 or not 1 <= args.count <= 10000:
        parser.error("interval >=1, timeout/max-frame-age positive and finite, count 1..10000")
    if not shutil.which(args.ffmpeg):
        print(json.dumps({"status": "setup_error", "reason": "ffmpeg_not_found"}))
        return 1
    try:
        from .metrics import ResourceMonitor
        if not args.file and find_spec("streamlink") is None:
            raise ImportError("streamlink")
        source = Source("file", str(args.file)) if args.file else Source("twitch", args.channel, args.quality) if args.channel else Source("hls", args.hls, args.quality)
        if source.kind == "file" and not args.file.is_file():
            raise ValueError("missing_video")
        if source.kind != "file":
            source.streamlink_command()  # validate before resources start
        regions = None
        if args.config:
            config = json.loads(args.config.read_text(encoding="utf-8"))
            if not isinstance(config, dict) or set(config) != {"level", "exp"}:
                raise ValueError("invalid_roi_config")
            regions = {key: Region(*value) for key, value in config.items()}
        profile = GlyphProfile.load(args.glyph_profile) if args.glyph_profile else None
    except (ImportError, ValueError, TypeError, OSError):
        print(json.dumps({"status": "setup_error", "reason": "check_capture_dependencies_source_and_config"}))
        return 1
    # Single-threaded OCR helps bound resources on the target 1 vCPU host.
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    monitor = ResourceMonitor()
    started = time.monotonic()
    deadline = started
    session = None
    last_sequence = 0
    previous = None
    previous_hash = None
    total_bytes = 0
    successes = 0
    accepted = 0
    interrupted = False
    try:
        for index in range(args.count):
            time.sleep(max(0, deadline - time.monotonic()))
            tick_started = time.monotonic()
            record = {"type": "observation", "index": index, "mode": args.mode,
                      "attempted_at": datetime.now(timezone.utc).isoformat(),
                      "source_kind": source.kind, "requested_interval_seconds": args.interval,
                      "frame_captured_at": None, "scheduled_lateness_seconds": round(max(0, tick_started - deadline), 3)}
            try:
                if session is None:
                    session = VideoSession(source, ffmpeg=args.ffmpeg,
                                           file_offset=time.monotonic() - started if args.file else 0,
                                           keyframes_only=not args.full_decode)
                    last_sequence = 0
                frame = session.frame(after_sequence=last_sequence, timeout=args.timeout, max_age=args.max_frame_age)
                last_sequence = frame.sequence
                capture_seconds = time.monotonic() - tick_started
                age = time.monotonic() - frame.arrived_monotonic
                image = frame.image()
                frame_hash = hashlib.sha256(frame.png).hexdigest()
                ocr_started = time.monotonic()
                result = recognize(image, regions=regions,
                                   glyph_profile=profile, pixel_scales=tuple(args.pixel_scale or [1]),
                                   debug_dir=args.debug_dir / f"{index:04d}" if args.debug_dir else None)
                result = _guard_unverified_exp(result, profile)
                ocr_seconds = time.monotonic() - ocr_started
                successes += 1
                transition = None
                if result.status == "accepted":
                    observation = Observation(args.character, datetime.now(timezone.utc), result.reading)
                    transition = validate_transition(previous, observation, max_gap_seconds=max(120, args.interval * 2))
                    if transition.status in {"baseline", "accepted"}:
                        previous = observation
                        accepted += 1
                record.update(status=result.status, recognition=asdict(result),
                              transition=asdict(transition) if transition else None,
                              received_at=frame.received_at, frame_size=list(image.size),
                              frame_sequence=frame.sequence, frame_sha256=frame_hash,
                              same_pixels_as_previous=None if previous_hash is None else previous_hash == frame_hash,
                              capture_wait_seconds=round(capture_seconds, 3),
                              local_delivery_age_seconds=round(age, 3), ocr_seconds=round(ocr_seconds, 3))
                previous_hash = frame_hash
            except CaptureError as error:
                record.update(status="capture_failed", reason=str(error))
                if session:
                    session.close()
                    total_bytes += session.source_bytes
                    session = None
            except (OSError, RuntimeError, ValueError):
                record.update(status="processing_failed", reason="decode_or_ocr_error")
            finally:
                if args.mode == "periodic" and session:
                    session.close()
                    total_bytes += session.source_bytes
                    session = None
            record["tick_seconds"] = round(time.monotonic() - tick_started, 3)
            record["video_payload_bytes_total"] = None if args.file else total_bytes + (session.source_bytes if session else 0)
            record["resources"] = monitor.snapshot()
            print(json.dumps(record), flush=True)
            # Never overlap jobs or catch up with a burst of old scheduled ticks.
            deadline += args.interval
            if deadline < time.monotonic():
                deadline = time.monotonic() + args.interval
    except KeyboardInterrupt:
        interrupted = True
    finally:
        if session:
            session.close()
            total_bytes += session.source_bytes
        monitor.close()
        elapsed = time.monotonic() - started
        print(json.dumps({"type": "summary", "frames_recognized": successes, "readings_accepted": accepted,
                          "video_payload_bytes": None if args.file else total_bytes,
                          "video_payload_mbps": None if args.file else round(total_bytes * 8 / max(elapsed, .001) / 1e6, 4),
                          "bandwidth_scope": "MPEG-TS bytes relayed to FFmpeg; excludes HTTP/TLS/control traffic and prefetch",
                          "mode": args.mode, "interval_seconds": args.interval,
                          "keyframes_only": not args.full_decode, **monitor.snapshot()}), flush=True)
    return 130 if interrupted else 0 if successes else 2


if __name__ == "__main__":
    raise SystemExit(main())
