"""Re-run current OCR on saved field crops; original capture records stay untouched."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from PIL import Image

from exp_tracker.models import Region
from exp_tracker.recognition import recognize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", type=Path, help="Capture JSONL containing frame_size and recognition regions")
    parser.add_argument("crops", type=Path, help="Directory containing numbered crop subdirectories")
    args = parser.parse_args()
    # PowerShell redirection can use UTF-16; internal benchmark files use UTF-8.
    payload = args.records.read_bytes()
    encoding = "utf-16" if payload.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    for line in payload.decode(encoding).splitlines():
        record = json.loads(line)
        if record.get("type") != "observation" or not record.get("recognition", {}).get("regions"):
            continue
        regions = {key: Region(**value) for key, value in record["recognition"]["regions"].items()}
        width, height = record["frame_size"]
        # Only cropped pixels are restored into an otherwise blank in-memory canvas.
        if width * height > 4096 * 2160:
            raise ValueError("Recorded frame size exceeds limit")
        image = Image.new("RGB", (width, height), "black")
        for field, roi in regions.items():
            with Image.open(args.crops / f"{record['index']:04d}" / f"{field}-crop.png") as crop:
                image.paste(crop, roi.pixels(width, height)[:2])
        result = recognize(image, regions=regions)
        print(json.dumps({"index": record["index"], "original_status": record["status"],
                          "replayed": asdict(result)}))


if __name__ == "__main__":
    main()
