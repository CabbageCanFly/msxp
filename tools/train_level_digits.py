"""Calibrate PRIVATE level templates from manual development labels, never OCR guesses.

JSON examples: image (relative path), box, level, split='development', family.
Each family needs all ten digits. Output is game-derived material; keep it ignored.
"""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

from level_digits import THRESHOLDS, bits, ink, load_profile, segment_tiles


def train(annotation, output):
    data = json.loads(annotation.read_text(encoding='utf-8'))
    families = {}
    for row in data['examples']:
        if row['split'] != 'development' or type(row['level']) is not int or not 1<=row['level']<=200:
            raise ValueError('Only manually labeled development levels 1..200 may train')
        with Image.open(annotation.parent/row['image']) as image:
            tiles,reason = segment_tiles(image.crop(tuple(row['box'])))
        text = str(row['level'])
        if reason or len(tiles) != len(text):
            raise ValueError(f"Unverified tile segmentation in {row['id']}: {reason}")
        family = families.setdefault(row['family'],{c:[] for c in '0123456789'})
        for digit,tile in zip(text,tiles):
            entry = dict(size=list(tile.size),masks={str(t):bits(ink(tile,t)) for t in THRESHOLDS})
            if entry not in family[digit]:
                family[digit].append(entry)
    payload = dict(version=1,families=[dict(id=name,digits=digits) for name,digits in families.items()],
                   provenance=dict(annotation_sha256=hashlib.sha256(annotation.read_bytes()).hexdigest(),
                                   training_ids=[r['id'] for r in data['examples']]))
    # Validate before replacing any output, including complete alphabet and masks.
    import tempfile
    with tempfile.TemporaryDirectory(dir=annotation.parent) as directory:
        check = Path(directory)/'profile.json'
        check.write_text(json.dumps(payload),encoding='utf-8')
        load_profile(check)
    output.write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8')
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('annotation',type=Path)
    parser.add_argument('output',type=Path)
    args = parser.parse_args(argv)
    train(args.annotation,args.output)


if __name__=='__main__':main()
