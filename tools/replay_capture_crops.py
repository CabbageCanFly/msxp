"""Re-run current OCR on saved field crops; original capture records stay untouched."""

import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

from PIL import Image

from exp_tracker.glyphs import GlyphProfile
from exp_tracker.models import Region, Recognition
from exp_tracker.recognition import recognize
from exp_tracker.store import Store
from exp_tracker.trust import guard_unverified_exp


def read_records(path):
    # PowerShell redirection can use UTF-16; internal benchmark files use UTF-8.
    payload = path.read_bytes()
    encoding = "utf-16" if payload.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    return [record for line in payload.decode(encoding).splitlines()
            if (record := json.loads(line)).get("type") == "observation"]


def restore_frame(record, crops):
    """Reconstruct only saved fields in RAM; never reuse a recorded numeric answer."""
    recorded = record["recognition"]
    regions = {key: Region(**value) for key, value in recorded["regions"].items()}
    width, height = record["frame_size"]
    if width <= 0 or height <= 0 or width * height > 4096 * 2160:
        raise ValueError("Recorded frame size exceeds limit")
    image = Image.new("RGB", (width, height), "black")
    # An early level failure has no saved EXP crop, and will fail again at level.
    for field in recorded.get("raw", regions):
        if field not in {"level", "exp"}:
            raise ValueError("Unexpected saved field")
        roi = regions[field]
        with Image.open(crops / f"{record['index']:04d}" / f"{field}-crop.png") as crop:
            image.paste(crop, roi.pixels(width, height)[:2])
    return image, regions


def recognize_saved(record, crops, profile=None):
    if not record.get("recognition", {}).get("regions"):
        status = record.get("status")
        return Recognition(status if status in {"capture_failed", "processing_failed", "offline", "missing_hud"} else "unreadable",
                           reasons=[record.get("reason", "no_saved_hud_regions")])
    image, regions = restore_frame(record, crops)
    return guard_unverified_exp(recognize(image, regions=regions, glyph_profile=profile), profile)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", type=Path, help="Capture JSONL containing frame_size and recognition regions")
    parser.add_argument("crops", type=Path, help="Directory containing numbered crop subdirectories")
    parser.add_argument("--glyph-profile", type=Path)
    parser.add_argument("--database", type=Path, help="Existing dedicated replay DB with a historical open session")
    parser.add_argument("--tracking-channel", help="Explicit channel in the replay database")
    args = parser.parse_args(argv)
    if args.database and (not args.glyph_profile or not args.tracking_channel):
        parser.error("database replay requires --glyph-profile and --tracking-channel")
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    store = None
    try:
        profile = GlyphProfile.load(args.glyph_profile) if args.glyph_profile else None
        if args.database:
            if not args.database.is_file():
                raise ValueError("initialize a dedicated replay database first")
            store = Store(args.database)
            if not store.state(args.tracking_channel)["session"]:
                raise ValueError("select a character and start a historical session before replay")
        digest = hashlib.sha256(args.records.read_bytes()).hexdigest()
        for record in read_records(args.records):
            session = store.state(args.tracking_channel)["session"] if store else None
            result = recognize_saved(record, args.crops, profile)
            output = {"index": record["index"], "original_status": record["status"], "replayed": asdict(result)}
            if store:
                saved = store.ingest(args.tracking_channel, record.get("event_id") or f"replay:{digest}:{record['index']}",
                                     datetime.fromisoformat(record.get("received_at") or record["attempted_at"]),
                                     result, profile=profile, session_id=session["id"] if session else None,
                                     source="saved-crops")
                output["tracking"] = {key: saved[key] for key in (
                    "id", "outcome", "reason", "gained_exp", "interval_start_observation_id", "missing_observations", "duplicate")}
            print(json.dumps(output), flush=True)
        return 0
    except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error) as error:
        print(json.dumps({"status": "error", "reason": str(error)}), file=sys.stderr)
        return 1
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
