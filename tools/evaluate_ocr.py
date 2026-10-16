"""Offline, labeled-crop comparison. Never captures video or updates labels.

Manifest examples contain id RUN/INDEX, split development|heldout, level,
current_exp and percentage. crop_root is relative to the manifest; folders are
RUN-crops/INDEX:04d/{level,exp}-crop.png, as emitted by benchmark_capture.py.
Use separate processes for baseline and hybrid to compare peak memory fairly.
Outputs include private labels; save under ignored artifacts/ or private/.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import time

from PIL import Image

from exp_tracker.glyphs import GlyphProfile, match_exp
from exp_tracker.models import Reading, Region
from exp_tracker.parsing import parse_exp
from exp_tracker.recognition import recognize


def load_crops(manifest: Path, item: dict, data: dict):
    run, index = item["id"].split("/")
    if Path(run).name != run or not index.isdigit():
        raise ValueError("invalid dataset id")
    directory = manifest.parent / data["crop_root"] / f"{run}-crops" / f"{int(index):04d}"
    with Image.open(directory / "level-crop.png") as image:
        level = image.convert("RGB")
    with Image.open(directory / "exp-crop.png") as image:
        exp = image.convert("RGB")
    if max(level.width, exp.width) > 512 or max(level.height, exp.height) > 96:
        raise ValueError("field crop exceeds evaluation size limit")
    # Powers of two make ROI boundaries exact, avoiding float roundoff when
    # restoring disjoint fields into a small blank canvas. This is not HUD geometry.
    width = 2 ** math.ceil(math.log2(max(level.width, exp.width)))
    height = 2 ** math.ceil(math.log2(level.height + exp.height))
    canvas = Image.new("RGB", (width, height))
    canvas.paste(level, (0, 0))
    canvas.paste(exp, (0, level.height))
    regions = {"level": Region(0, 0, level.width / width, level.height / height),
               "exp": Region(0, level.height / height, exp.width / width,
                             (level.height + exp.height) / height)}
    return canvas, regions, exp


def main(argv=None):
    from exp_tracker.metrics import ResourceMonitor
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--engine", choices=("baseline", "hybrid", "pixel-exp"), default="baseline")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--split", choices=("all", "development", "heldout"), default="all")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not 1 <= args.repeat <= 100:
        parser.error("repeat must be 1..100")
    if args.engine != "baseline" and not args.profile:
        parser.error("hybrid and pixel-exp require --profile")
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    profile = GlyphProfile.load(args.profile) if args.profile else None
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    examples = [e for e in data["examples"] if args.split == "all" or e["split"] == args.split]
    if not examples:
        raise ValueError("dataset split is empty")
    prepared = [(e, *load_crops(args.manifest, e, data)) for e in examples]
    records = []
    monitor = ResourceMonitor(sample_interval=.01, scope="offline OCR Python + Tesseract subprocesses")
    try:
        for repeat in range(args.repeat):
            for expected, image, regions, crop in prepared:
                started = time.perf_counter()
                cpu_started = time.process_time()
                if args.engine == "pixel-exp":
                    attempt = match_exp(crop, profile)
                    accepted = bool(attempt["text"])
                    correct = parse_exp(attempt["text"]) == (expected["current_exp"], expected["percentage"])
                    result = attempt
                else:
                    result = recognize(image, regions=regions,
                                       glyph_profile=profile if args.engine == "hybrid" else None)
                    accepted = result.status == "accepted"
                    correct = result.reading == Reading(expected["level"], expected["current_exp"], expected["percentage"])
                    result = asdict(result)
                seconds = time.perf_counter() - started
                python_cpu = time.process_time() - cpu_started
                records.append(dict(id=expected["id"], split=expected["split"], repeat=repeat,
                                    correct_accepted=accepted and correct,
                                    incorrect_accepted=accepted and not correct, rejected=not accepted,
                                    elapsed_seconds=seconds, python_cpu_seconds=python_cpu, result=result))
    finally:
        monitor.close()
    splits = {}
    for split in sorted({r["split"] for r in records}):
        subset = [r for r in records if r["split"] == split]
        splits[split] = {key: sum(r[key] for r in subset)
                         for key in ("correct_accepted", "incorrect_accepted", "rejected")}
    timings = sorted(r["elapsed_seconds"] for r in records)
    output = dict(engine=args.engine, scope="EXP only" if args.engine == "pixel-exp" else "level + EXP + percentage",
                  platform=platform.platform(), python=platform.python_version(),
                  manifest_sha256=hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
                  profile_sha256=hashlib.sha256(args.profile.read_bytes()).hexdigest() if args.profile else None,
                  repeat=args.repeat, splits=splits, mean_seconds=statistics.mean(timings),
                  median_seconds=statistics.median(timings), p95_seconds=timings[math.ceil(.95 * len(timings)) - 1],
                  python_cpu_seconds=sum(r["python_cpu_seconds"] for r in records),
                  resources=monitor.snapshot(), records=records)
    payload = json.dumps(output, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(json.dumps({key: value for key, value in output.items() if key != "records"}, indent=2))
    return 1 if any(r["incorrect_accepted"] for r in records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
