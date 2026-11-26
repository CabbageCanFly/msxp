"""Level badge digits from the orange tiles' white ink, scored by a small learned linear model.

Streams scale the badge differently, so each digit's ink is normalised to its own height
before scoring; the model (data/badge-digits.json) was trained on hand-checked badges from
many streams (docs/badge-digits.md). Any doubt returns no level.
"""
from functools import cache
import json
import math
from pathlib import Path

from PIL import Image, ImageChops

from .diagnostic_geometry import level_tile_box

MODEL = Path(__file__).with_name('data') / 'badge-digits.json'
GATE = .9  # Every tile's top digit probability; errors began near .6 in cross-stream checks.
MIN_TILE = 10  # Smaller tiles were too blurry to check by eye.


@cache
def model():
    data = json.loads(MODEL.read_text())
    weights = data['weights']
    if (data['version'] != 1 or len(weights) != data['grid'] ** 2 + 1
            or any(len(row) != 10 for row in weights)):
        raise ValueError('Invalid badge digit model')
    return data


def tiles(crop):
    """Equal cells across the orange tiles; the count is the one whose cells are near-square."""
    box = level_tile_box(crop)
    if box is None:
        return None, 'no_tiles'
    if box[0] == 0 or box[1] == 0 or box[2] == crop.width or box[3] == crop.height:
        return None, 'clipped'
    w, h = box[2] - box[0], box[3] - box[1]
    if h < MIN_TILE:
        return None, 'too_small'
    fits = [n for n in (1, 2, 3) if .75 <= w / (n * h) <= 1.25]
    if len(fits) != 1:
        return None, 'tile_count'
    n = fits[0]
    red, green, blue = crop.convert('RGB').split()
    ink = ImageChops.darker(ImageChops.darker(red, green), blue)  # White stays bright, orange goes dark.
    return [ink.crop((box[0] + round(i * w / n), box[1], box[0] + round((i + 1) * w / n), box[3]))
            for i in range(n)], None


def feature(cell, grid, ink):
    """Ink inside the tile border, cropped to itself, height-normalised and centred; zero-mean unit-norm."""
    w, h = cell.size
    inner = cell.crop((round(w * .12), round(h * .12), w - round(w * .12), h - round(h * .12)))
    pixels = list(inner.tobytes())
    lo, hi = sorted(pixels)[len(pixels) // 4], max(pixels)
    if hi - lo < 60:
        return None
    threshold = lo + (hi - lo) * ink
    box = inner.point(lambda p: 255 if p > threshold else 0).getbbox()
    if not box:
        return None
    glyph = inner.crop(box).point(lambda p: max(0, min(255, round((p - lo) * 255 / (hi - lo)))))
    width = max(1, min(grid, round(glyph.width * grid / glyph.height)))
    canvas = Image.new('L', (grid, grid), 0)
    canvas.paste(glyph.resize((width, grid), Image.BILINEAR), ((grid - width) // 2, 0))
    values = [p / 255 for p in canvas.tobytes()]
    mean = sum(values) / len(values)
    values = [v - mean for v in values]
    norm = math.sqrt(sum(v * v for v in values)) or 1
    return [v / norm for v in values]


def probabilities(vector, data):
    scale, weights = data['scale'], data['weights']
    scores = [weights[-1][d] + scale * sum(v * row[d] for v, row in zip(vector, weights)) for d in range(10)]
    top = max(scores)
    exps = [math.exp(s - top) for s in scores]
    total = sum(exps)
    return [e / total for e in exps]


def read_badge(crop, *, gate=GATE):
    """(level, details); level is None unless every tile's digit clears the gate."""
    data = model()
    cells, reason = tiles(crop)
    if cells is None:
        return None, dict(reason=reason)
    text, confidence = '', 1.0
    for cell in cells:
        vector = feature(cell, data['grid'], data['ink'])
        if vector is None:
            return None, dict(reason='no_ink')
        p = probabilities(vector, data)
        digit = max(range(10), key=p.__getitem__)
        confidence = min(confidence, p[digit])
        if p[digit] < gate:
            return None, dict(reason='unsure', confidence=confidence)
        text += str(digit)
    if text[0] == '0' or not 1 <= int(text) <= 200:
        return None, dict(reason='range', text=text)
    return int(text), dict(reason='read', text=text, confidence=confidence)
