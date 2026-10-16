"""Isolated native numeric-glyph evidence; never repairs or trusts neural output."""

from PIL import Image

from exp_digits import bitmap, columns
from exp_tracker.glyphs import mask
from level_digits import distance


def segment_prefix(image):
    """Column projection before colored punctuation; retain every white fragment.

    Color only separates the region for diagnosis, not bracket authentication.
    shortcut: no fragment joining; abstain when projection splits a glyph.
    """
    if not 1 <= image.width <= 512 or not 1 <= image.height <= 96:
        return dict(reason='input_bounds', boxes=[], patches=[])
    image = image.convert('RGB')
    white = image.convert('L').point(lambda p:255 if p > 180 else 0)
    bands = [(a,b) for a,b in columns(white.transpose(Image.Transpose.TRANSPOSE)) if 6 <= b-a <= 24]
    if len(bands) != 1:
        return dict(reason='ambiguous_text_band', boxes=[], patches=[])
    top,bottom = bands[0]
    line = image.crop((0,top,image.width,bottom))
    green = bitmap(mask(line,11,green_excess=True),line.width,line.height)
    delimiters = columns(green)
    if len(delimiters) != 2:
        return dict(reason='ambiguous_color_regions', boxes=[], patches=[])
    opening = delimiters[0][0]
    prefix = white.crop((0,top,opening,bottom))
    boxes = [(a,top,b,bottom) for a,b in columns(prefix)]
    if not boxes or len(boxes) > 24:
        return dict(reason='missing_or_extra_segments', boxes=[], patches=[])
    return dict(reason=None, boxes=boxes, patches=[white.crop(box) for box in boxes])


def rank_patch(patch, references):
    """Independent all-digit competition at native size with existing +/-1 shifts.

    Existing EXP distance <=3 / margin >=2 is retained, not fitted to these cases.
    Missing classes, uncertain ink and ties abstain; raw ranks remain diagnostic.
    """
    if not 1 <= patch.width <= 32 or not 6 <= patch.height <= 24 or patch.getbbox() is None:
        return dict(digit=None, reason='invalid_or_empty_patch', ranked=[], margin=None)
    scores = {}
    for digit, images in references.items():
        if digit not in '0123456789' or len(digit) != 1:
            raise ValueError('Reference labels must be single decimal digits')
        eligible = [r for r in images if r.height == patch.height and r.getbbox() is not None]
        if eligible:
            scores[digit] = min(distance(patch,r) for r in eligible)
    ranked = sorted((score,digit) for digit,score in scores.items())
    result = dict(digit=None, reason='missing_native_classes',
                  ranked=[dict(digit=d,distance=s) for s,d in ranked], margin=None)
    if set(scores) != set('0123456789'):
        return result
    best,digit = ranked[0]
    result['margin'] = ranked[1][0]-best
    if best > 3:
        result['reason'] = 'distance'
    elif result['margin'] < 2:
        result['reason'] = 'ambiguous'
    else:
        result.update(digit=digit,reason=None)
    return result
