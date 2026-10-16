"""Build a PRIVATE font profile from explicitly annotated permitted glyph cells.

Annotation JSON: {"height":9,"digit_threshold":175,"punctuation_threshold":100,
"samples":[{"image":"relative/path.png","split":"development",
"id":"example-id","text":"12,345[67.89%]","origin":[1,1],
"widths":{"0":6,...}}]}. Widths include each glyph's trailing advance.
Version 1 is the default. For green brackets set version=2,
bracket_mode="green_excess", punctuation_threshold=11 in the annotation.
All ten digits and punctuation must be present. Held-out samples are forbidden.
Use manual crop geometry; no recognition output is used as a training label.
"""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

from exp_tracker.glyphs import GlyphProfile, SYMBOLS, mask


def train(annotation: Path, output: Path):
    data = json.loads(annotation.read_text(encoding="utf-8"))
    version = data.get("version", 1)
    mode = data.get("bracket_mode", "max_channel")
    if (version, mode) not in ((1, "max_channel"), (2, "green_excess")):
        raise ValueError("Use version 1/max_channel or version 2/green_excess")
    templates = {c: set() for c in SYMBOLS}
    widths = None
    height = data["height"]
    for sample in data["samples"]:
        if sample["split"] != "development":
            raise ValueError("Only development examples may train a profile")
        if widths is not None and sample["widths"] != widths:
            raise ValueError("Glyph advances must agree across training samples")
        widths = sample["widths"]
        with Image.open(annotation.parent / sample["image"]) as image:
            x, y = sample["origin"]
            for char in sample["text"]:
                width = widths[char]
                if x < 0 or y < 0 or x + width > image.width or y + height > image.height:
                    raise ValueError("Annotated cell falls outside image")
                colored = char in "[]"
                threshold = data["punctuation_threshold"] if colored else data["digit_threshold"]
                templates[char].add(mask(image.crop((x, y, x + width, y + height)), threshold,
                                         color=colored, green_excess=colored and mode == "green_excess"))
                x += width
    profile = GlyphProfile(height, widths, {c: tuple(sorted(v)) for c, v in templates.items()},
                           data["digit_threshold"], data["punctuation_threshold"], mode)
    result = dict(version=version, height=height, widths=widths, templates=profile.templates,
                  digit_threshold=profile.digit_threshold,
                  punctuation_threshold=profile.punctuation_threshold,
                  provenance={"annotation_sha256": hashlib.sha256(annotation.read_bytes()).hexdigest(),
                              "training_ids": [s["id"] for s in data["samples"]]})
    if version == 2:
        result["bracket_mode"] = mode
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return profile


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("annotation", type=Path)
    parser.add_argument("output", type=Path, help="Store under private/, never commit screenshot-derived profiles")
    args = parser.parse_args()
    train(args.annotation, args.output)
