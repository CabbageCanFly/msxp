"""Reproduce baseline and resolution-limit measurements without writing images."""

from dataclasses import asdict
import json
from pathlib import Path
import time

from PIL import Image

from exp_tracker.models import Region
from exp_tracker.recognition import recognize

root = Path(__file__).resolve().parents[1]
for number in (1, 2):
    with Image.open(root / f"samples/maplestory-classic-stream{number}.png") as source:
        image = source.convert("RGB")
    data = json.loads((root / f"configs/stream{number}.json").read_text())
    regions = {key: Region(*value) for key, value in data.items()}
    for name, frame, config in [
        ("automatic", image, None), ("calibrated", image, regions),
        ("720p", image.resize((1280, 720), Image.Resampling.LANCZOS), regions),
        ("1440p", image.resize((2560, 1440), Image.Resampling.LANCZOS), regions),
    ]:
        start = time.perf_counter()
        result = recognize(frame, regions=config)
        print(json.dumps(dict(sample=number, mode=name, status=result.status,
                              reading=asdict(result.reading) if result.reading else None,
                              confidence=result.confidence, reasons=result.reasons,
                              elapsed_seconds=round(time.perf_counter() - start, 3))))
