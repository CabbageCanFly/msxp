"""Extract the labelled test frames from their recordings once, as a small private golden set.

    python tools/extract_test_frames.py           # write missing frames to samples/frames/ (~300 MB)
    python tools/extract_test_frames.py --check   # verify every saved frame is pixel-identical to its recording

Frames are lossless WebP, so tests/test_recorded_streams.py reads exactly the pixels it would decode from the
video. Afterwards the multi-GB recordings are only needed to cut new examples. Frames show streamers' content
and Nexon's artwork: they stay private (samples/ is never in Git); back them up instead.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / 'tests/data/recorded_frames.json'
OUT = ROOT / 'samples/frames'


def name(frame):
    return f"{Path(frame['video']).stem}-{frame['seconds']}s.webp"


def decode(frame):
    output = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-ss', str(frame['seconds']), '-i', str(ROOT / frame['video']),
                             '-frames:v', '1', '-f', 'image2pipe', '-c:v', 'png', 'pipe:1'], check=True, capture_output=True, timeout=120).stdout
    with Image.open(BytesIO(output)) as image:return image.convert('RGB')


def one(frame, check):
    path = OUT / name(frame)
    if not check and path.exists():return 'kept'
    if not (ROOT / frame['video']).is_file():return 'no recording'
    image = decode(frame)
    if check:
        if not path.exists():return 'missing'
        with Image.open(path) as saved:return 'identical' if saved.convert('RGB').tobytes() == image.tobytes() else 'DIFFERENT'
    image.save(path, 'WEBP', lossless=True, method=4)
    return 'written'


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    cli.add_argument('--check', action='store_true', help='compare saved frames with their recordings; write nothing')
    args = cli.parse_args(argv)
    frames = json.loads(FRAMES.read_text(encoding='utf-8'))['frames']
    OUT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=6) as pool:results = list(pool.map(lambda f: one(f, args.check), frames))
    counts = {k: results.count(k) for k in sorted(set(results))}
    size = sum(p.stat().st_size for p in OUT.glob('*.webp'))
    print(f'{counts}; {OUT} holds {size / 1e6:.0f} MB')
    return 1 if 'DIFFERENT' in counts else 0


if __name__ == '__main__':
    sys.exit(main())
