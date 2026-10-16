"""Small command-line interface; credentials are never command-line arguments."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

from PIL import Image

from .models import Region
from .glyphs import GlyphProfile
from .recognition import recognize


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect a MapleStory Classic HUD screenshot")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("image", type=Path)
    inspect.add_argument("--config", type=Path, help="JSON with normalized level and exp ROIs")
    inspect.add_argument("--search", default="0,0.7,1,1", help="normalized discovery rectangle")
    inspect.add_argument("--min-confidence", type=float, default=.4)
    inspect.add_argument("--debug-dir", type=Path)
    inspect.add_argument("--glyph-profile", type=Path, help="Private calibrated EXP font profile; Tesseract fallback")
    inspect.add_argument("--pixel-scale", type=float, action="append", help="Explicit glyph scale(s), default 1")
    args = parser.parse_args(argv)
    try:
        regions = None
        if args.config:
            config = json.loads(args.config.read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                raise ValueError("ROI configuration must be a JSON object with level and exp keys")
            regions = {key: Region(*value) for key, value in config.items()}
        search = Region(*map(float, args.search.split(",")))
        profile = GlyphProfile.load(args.glyph_profile) if args.glyph_profile else None
        start = time.perf_counter()
        with Image.open(args.image) as image:
            result = recognize(image.convert("RGB"), regions=regions, search=search,
                               min_confidence=args.min_confidence, debug_dir=args.debug_dir,
                               glyph_profile=profile, pixel_scales=tuple(args.pixel_scale or [1]))
        print(json.dumps({**asdict(result), "elapsed_seconds": round(time.perf_counter() - start, 3)}, indent=2))
        return 0 if result.status == "accepted" else 2
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        print(json.dumps({"status": "error", "error": str(error)}), file=sys.stderr)
        return 1

