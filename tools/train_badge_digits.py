"""Train the level badge digit model from hand-checked private badge crops.

labels.json maps a crop file name (in the same folder's crops/) to its level, or "x" for a
badge nobody can read. Pure-Python softmax regression; `--folds` reports cross-stream
accuracy instead, holding out whole streams (labels' "groups" map: crop -> stream).
"""
import argparse
import json
import math
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PIL import Image

from exp_tracker.badge_digits import GATE, feature, probabilities, tiles

GRID, INK, SCALE = 12, .45, 12


def samples(folder):
    labels = json.loads((folder / 'labels.json').read_text())
    groups = labels.get('groups', {})
    rows = []
    for name, level in sorted(labels['labels'].items()):
        crop = Image.open(folder / 'crops' / name)
        cells, _ = tiles(crop)
        vectors = [feature(c, GRID, INK) for c in cells] if cells else None
        rows.append(dict(name=name, level=level, group=groups.get(name, name), crop=crop, vectors=vectors))
    return rows


def tile_examples(rows):
    return [(v, int(d)) for r in rows if r['level'] != 'x' and r['vectors'] and len(r['vectors']) == len(r['level'])
            for v, d in zip(r['vectors'], r['level']) if v is not None]


def train(examples, *, epochs=60, rate=.05, l2=1e-3, seed=0):
    """Plain SGD on softmax cross-entropy; the bias is the last weight row."""
    weights = [[0.] * 10 for _ in range(GRID * GRID + 1)]
    data = dict(version=1, grid=GRID, ink=INK, scale=SCALE, weights=weights)
    order = list(examples)
    rng = random.Random(seed)
    for epoch in range(epochs):
        rng.shuffle(order)
        step = rate / (1 + epoch / 20)
        for vector, digit in order:
            p = probabilities(vector, data)
            p[digit] -= 1
            for v, row in zip(vector, weights):
                if v:
                    x = SCALE * v
                    for d in range(10):
                        row[d] -= step * (p[d] * x + l2 * row[d])
            for d in range(10):
                weights[-1][d] -= step * p[d]
    data['weights'] = [[round(w, 5) for w in row] for row in weights]
    return data


def score(rows, data, gate=GATE):
    from exp_tracker import badge_digits
    tally = dict(correct=0, wrong=0, unread=0, unreadable_accepted=0, unreadable_rejected=0)
    original = badge_digits.model
    badge_digits.model = lambda: data
    try:
        for r in rows:
            level, _ = badge_digits.read_badge(r['crop'], gate=gate)
            if r['level'] == 'x':
                tally['unreadable_accepted' if level else 'unreadable_rejected'] += 1
            else:
                tally['unread' if level is None else 'correct' if str(level) == r['level'] else 'wrong'] += 1
    finally:
        badge_digits.model = original
    return tally


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('folder', type=Path)
    cli.add_argument('--output', type=Path)
    cli.add_argument('--folds', type=int, default=0)
    cli.add_argument('--epochs', type=int, default=60)
    args = cli.parse_args()
    rows = samples(args.folder)
    if args.folds:
        groups = sorted({r['group'] for r in rows})
        random.Random(0).shuffle(groups)
        fold = {g: i % args.folds for i, g in enumerate(groups)}
        total = {}
        for k in range(args.folds):
            data = train(tile_examples([r for r in rows if fold[r['group']] != k]), epochs=args.epochs)
            for key, n in score([r for r in rows if fold[r['group']] == k], data).items():
                total[key] = total.get(key, 0) + n
            print(k, total, flush=True)
        return
    data = train(tile_examples(rows), epochs=args.epochs)
    print(score(rows, data))
    if args.output:
        args.output.write_text(json.dumps(data, separators=(',', ':')) + '\n', newline='\n')


if __name__ == '__main__':
    main()
