"""Rebuild private fixture crops from saved lossless frames, or their source recording.

    python tools/rebuild_fixture_crops.py private/levelup-evaluation/manifest.json           # create missing crops
    python tools/rebuild_fixture_crops.py private/levelup-evaluation/manifest.json --check   # compare, write nothing

A manifest names its recording (`video`, relative to the manifest), the frozen field `boxes` (or
`field_boxes`), its `crop_root` and `examples` with `id` ("run/index") and `seconds`; an example may override them.
Crops land where tools/evaluate_ocr.load_crops reads them: crop_root/<run>-crops/<index:04d>/<field>-crop.png.
Saved frames live beside the recording in frames/<video-stem>-<seconds>s.webp; the recording is optional.
Recordings and crops stay private (never in Git). Existing crops are never overwritten.
"""
import argparse
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image


def frame_at(video, seconds):
    """Prefer the exact saved pixels; decode the recording only when the frame is absent."""
    for timestamp in dict.fromkeys((str(seconds), format(seconds, '.15g'))):
        saved = video.parent / 'frames' / f'{video.stem}-{timestamp}s.webp'
        if saved.is_file():
            with Image.open(saved) as image:return image.convert('RGB')
    if not video.is_file():raise ValueError(f'source frame or recording not found: {video} at {seconds}s')
    output = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-ss', str(seconds), '-i', str(video),
                             '-frames:v', '1', '-f', 'image2pipe', '-c:v', 'png', 'pipe:1'],
                            check=True, capture_output=True, timeout=120).stdout
    with Image.open(BytesIO(output)) as image:
        return image.convert('RGB')


def crop_dir(manifest, data, example):
    run, index = example['id'].rsplit('/', 1)
    return manifest.parent / data['crop_root'] / f'{run}-crops' / f'{int(index):04d}'


def rebuild(manifest, *, check=False, say=print):
    manifest = Path(manifest)
    data = json.loads(manifest.read_text(encoding='utf-8'))
    video = manifest.parent / data['video']
    counts = dict(created=0, identical=0, different=0, missing=0)
    for example in data['examples']:
        target, image = crop_dir(manifest, data, example), None
        boxes = example.get('boxes') or example.get('field_boxes') or data.get('boxes') or data['field_boxes']
        for field, box in boxes.items():
            path = target / f'{field}-crop.png'
            if not check and path.exists():continue
            image = image or frame_at(video, example['seconds'])
            crop = image.crop(tuple(box))
            if check:
                if not path.exists():counts['missing'] += 1;continue
                with Image.open(path) as saved:same = saved.convert('RGB').tobytes() == crop.tobytes()
                counts['identical' if same else 'different'] += 1
                if not same:say(f"different: {example['id']} {field}")
            else:
                target.mkdir(parents=True, exist_ok=True);crop.save(path);counts['created'] += 1
    say(json.dumps(counts))
    return counts


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    cli.add_argument('manifest', type=Path)
    cli.add_argument('--check', action='store_true', help='compare regenerated crops with the saved ones; write nothing')
    args = cli.parse_args(argv)
    try:counts = rebuild(args.manifest, check=args.check)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f'Not rebuilt: {error}', file=sys.stderr);return 1
    return 1 if counts['different'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
