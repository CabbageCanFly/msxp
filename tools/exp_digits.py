"""Isolated native EXP experiment: verified brackets, column runs, local glyph shifts.

Uses existing manually calibrated glyph profiles without changing them. Results are
experimental candidates, never ingestion evidence. No resizing or OCR fallback.
"""

import argparse
from functools import lru_cache
import json
from pathlib import Path
import re

from PIL import Image

from exp_tracker.glyphs import GlyphProfile, mask
from level_digits import bits


WHITE = '0123456789,.%'


def bitmap(value, width, height):
    image = Image.new('L', (width, height))
    image.putdata([255 if value >> i & 1 else 0 for i in range(width * height)])
    return image


def horizontal_trim(image):
    box = image.getbbox()
    return image.crop((box[0], 0, box[2], image.height)) if box else None


def prepare(profile, templates=None):
    if profile.bracket_mode != 'green_excess':
        raise ValueError('The experiment requires a calibrated green-excess profile')
    if templates is None:
        templates = {c: [horizontal_trim(bitmap(v, profile.widths[c], profile.height))
                         for v in profile.templates[c]] for c in WHITE}
    # A fixed padded canvas makes bounded native shifts cheap and preserves pixels.
    stride = max(im.width for variants in templates.values() for im in variants) + 4
    packed = {}
    for char, variants in templates.items():
        values = set()
        for image in variants:
            canvas = Image.new('L', (stride, profile.height + 4))
            canvas.paste(image, (2, 2))
            value = bits(canvas)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    shift = dx + dy * stride
                    values.add(value << shift if shift >= 0 else value >> -shift)
        packed[char] = tuple(values)
    boxes = {c: [bitmap(v, profile.widths[c], profile.height).getbbox()
                 for v in profile.templates[c]] for c in WHITE}
    # Allow each neighbor's one-pixel alignment, while detecting erased slots.
    gaps = {(a, b): max(profile.widths[a] - x[2] + y[0] for x in boxes[a] for y in boxes[b]) + 2
            for a in WHITE for b in WHITE}
    trailing = {c: max(profile.widths[c] - b[2] for b in boxes[c]) + 2 for c in WHITE}
    return profile, (stride, packed, gaps, trailing)


def load_bank(path):
    """Read manually reviewed character boxes; calibration never consumes OCR guesses."""
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('experimental bank exceeds 1 MiB')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not 1 <= len(data['families']) <= 4:
        raise ValueError('unsupported experimental bank')
    bank = []
    for family in data['families']:
        profile = GlyphProfile.load(path.parent / family['profile'])
        if not 1 <= len(family['characters']) <= 512:
            raise ValueError('too many calibration characters')
        templates = {c: [] for c in WHITE}
        for row in family['characters']:
            if row['split'] != 'development' or row['char'] not in WHITE:
                raise ValueError('Only manually verified development characters may calibrate')
            with Image.open(path.parent / row['image']) as image:
                left, top, right, bottom = row['box']
                if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
                    raise ValueError('character box is outside image')
                if bottom - top != profile.height or right - left > 32:
                    raise ValueError('unsupported native character geometry')
                patch = horizontal_trim(image.crop(tuple(row['box'])).convert('L').point(
                    lambda p: 255 if p > profile.digit_threshold else 0))
            if patch is None:
                raise ValueError('empty development character')
            variants = templates[row['char']]
            if not any(v.size == patch.size and v.tobytes() == patch.tobytes() for v in variants):
                variants.append(patch)
        if any(not 1 <= len(v) <= 32 for v in templates.values()):
            raise ValueError('calibration must cover all digits and white punctuation')
        bank.append(prepare(profile, templates))
    return bank


def columns(image):
    """Keep every nonempty run, including punctuation and unknown fragments."""
    runs = []
    start = None
    for x in range(image.width + 1):
        present = x < image.width and image.crop((x, 0, x + 1, image.height)).getbbox()
        if present and start is None:
            start = x
        if not present and start is not None:
            runs.append((start, x))
            start = None
    return runs


def character(image, templates):
    stride, packed = templates[:2]
    if image.width > stride - 4:
        return None, dict(best=None, margin=None, nearest=None)
    canvas = Image.new('L', (stride, image.height + 4))
    canvas.paste(image, (2, 2))
    value = bits(canvas)
    ranked = sorted((min((value ^ template).bit_count() for template in variants), char)
                    for char, variants in packed.items())
    best, char = ranked[0]
    margin = ranked[1][0] - best
    # Development leave-cell-out distances overlap wrong classes above this bound.
    # Tiny punctuation classes differ by one pixel in verified development images.
    accepted = (best == 0 and margin >= 1) if char in ',.' else (best <= 3 and margin >= 2)
    return char if accepted else None, dict(best=best, margin=margin, nearest=char)


def field(image, templates, kind, segmentation, *, gray=None, alternative=None):
    def read(left, right):
        patch = image.crop((left, 0, right, image.height))
        char, evidence = character(patch, templates)
        if alternative is not None:
            value, detail = alternative(patch, gray.crop((left, 0, right, gray.height)))
            if char is None:
                char = value
            elif char.isdigit() and value is not None and value != char:
                char = None  # Confident disagreement is a veto, not a correction.
            evidence = {**evidence, 'alternative': detail}
        return char, evidence

    runs = columns(image)
    if not runs or len(runs) > 16:
        return None, dict(reason='missing_or_extra_characters')
    choices = []
    details = []
    for left, right in runs:
        patch = image.crop((left, 0, right, image.height))
        char, evidence = read(left, right)
        options = {char} if char is not None else set()
        if segmentation == 'valleys':
            # Every pixel belongs to one side; splitting never erases bridge pixels.
            counts = [sum(bool(v) for v in patch.crop((x, 0, x+1, patch.height)).tobytes())
                      for x in range(patch.width)]
            cuts = [x for x in range(1, patch.width) if min(counts[x-1:x+1]) <= 1]

            @lru_cache(None)
            def decode(start):
                texts = set()
                for end in [*cuts, patch.width]:
                    if end <= start:
                        continue
                    part = patch.crop((start, 0, end, patch.height))
                    box = part.getbbox()
                    if box is None:
                        continue
                    digit, _ = read(left + start + box[0], left + start + box[2])
                    if digit is None:
                        continue
                    for suffix in ({''} if end == patch.width else decode(end)):
                        if len(digit + suffix) <= 16:
                            texts.add(digit + suffix)
                    if len(texts) > 16:
                        raise ValueError('ambiguous_segmentation')
                return frozenset(texts)

            try:
                options.update(decode(0))
            except ValueError:
                return None, dict(reason='ambiguous_segmentation')
        details.append(dict(box=[left, right], options=sorted(options), **evidence))
        choices.append(options)
    if any(not c for c in choices):
        return None, dict(reason='unknown_or_ambiguous_character', characters=details)
    texts = {''}
    for index, options in enumerate(choices):
        texts = {a+b for a in texts for b in options if len(a+b) <= 16 and
                 (not a or runs[index][0] - runs[index-1][1] <= templates[2][a[-1], b[0]])}
        if len(texts) > 32:
            return None, dict(reason='ambiguous_segmentation', characters=details)
    texts = {t for t in texts if image.width - runs[-1][1] <= templates[3][t[-1]]}
    pattern = r'(?:0|[1-9][0-9]{0,11}|[1-9][0-9]{0,2}(?:,[0-9]{3}){1,3})' if kind == 'exp' else r'(?:0|[1-9][0-9]?)\.[0-9]{2}' + ('%' if kind == 'percentage' else '')
    valid = sorted(t for t in texts if re.fullmatch(pattern, t))
    if len(valid) != 1:
        return None, dict(reason='ambiguous_or_invalid_field', texts=sorted(texts), characters=details)
    text = valid[0]
    value = int(text.replace(',', '')) if kind == 'exp' else float(text.removesuffix('%'))
    return value, dict(text=text, reason=None, characters=details)


def shape(value, width, height):
    rows = [(value >> (y * width)) & ((1 << width) - 1) for y in range(height)]
    occupied = [y for y, row in enumerate(rows) if row]
    if not occupied:
        return 0, 0
    cols = 0
    for row in rows:
        cols |= row
    return cols.bit_length() - (cols & -cols).bit_length() + 1, occupied[-1] - occupied[0] + 1


def plausible_shape(value, references, width, height):
    """Bounded partial stroke agreement, never permission to supply absent ink."""
    actual_width, actual_height = shape(value, width, height)
    if actual_height < .65 * (height - 4):
        return None
    matches = []
    for reference in references:
        ref_width, ref_height = shape(reference, width, height)
        error = (value ^ reference).bit_count()
        if (abs(actual_width - ref_width) <= 1 and abs(actual_height - ref_height) <= 1
                and error <= min(8, (reference.bit_count() + 3) // 4)):
            matches.append(error)
    return min(matches, default=None)


def grammar_percentage(image, profile, templates, segmentation, *, gray=None, alternative=None):
    runs = columns(image)
    if len(runs) < 5:
        return None, dict(reason='no_separate_percent_suffix')
    left, right = runs[-1]
    if image.width - right > templates[3]['%']:
        return None, dict(reason='suffix_spacing')
    patch = image.crop((left, 0, right, image.height))
    _, evidence = character(patch, templates)
    # All numeric competitors remain active, even though grammar expects a percent.
    if evidence['nearest'] != '%' or evidence['margin'] < 4:
        return None, dict(reason='digit_like_or_ambiguous_suffix')
    stride, packed = templates[:2]
    canvas = Image.new('L', (stride, image.height + 4))
    canvas.paste(patch, (2, 2))
    error = plausible_shape(bits(canvas), packed['%'], stride, canvas.height)
    if error is None:
        return None, dict(reason='implausible_percent_shape')
    value, detail = field(image.crop((0, 0, left, image.height)), templates, 'percentage_digits', segmentation,
                         gray=gray.crop((0, 0, left, gray.height)) if gray is not None else None,
                         alternative=alternative)
    if value is None:
        return None, dict(reason='unverified_percentage_digits', numeric=detail)
    return value, dict(reason=None, text=detail['text'] + '%', inferred_percent=True,
                       suffix_error=error, numeric=detail)


def brackets(image, profile, *, infer_closing=False, templates=None):
    """Find both colored delimiters before interpreting any white numeric text."""
    matches = {'[': [], ']': []}
    masks = [mask(image, max(0, min(255, profile.punctuation_threshold + offset)), green_excess=True)
             for offset in (-4, 0, 4)]
    for char in matches:
        width = profile.widths[char]
        for x in range(image.width - width + 1):
            values = [sum(((value >> (y * image.width + x)) & ((1 << width) - 1)) << (y * width)
                          for y in range(profile.height)) for value in masks]
            best = min((value ^ template).bit_count()
                       for value in values if value for template in profile.templates[char]) if any(values) else None
            # Preserve the calibrated production bracket bound, independently of digits.
            if best is not None and best <= 4:
                matches[char].append(x)
            elif infer_closing and char == ']':
                white = image.crop((x, 0, x + width, profile.height)).convert('L')
                if sum(p > profile.digit_threshold for p in white.tobytes()) > 2:
                    continue  # Never hide white digit pixels inside an inferred bracket.
                for value in values:
                    error = plausible_shape(value, profile.templates[char], width, profile.height)
                    if error is None:
                        continue
                    patch = horizontal_trim(bitmap(value, width, profile.height))
                    _, evidence = character(patch, templates)
                    if evidence['best'] is not None and evidence['best'] >= error + 4:
                        matches[char].append(x)
                        break
    return matches


def recognize(crop, bank, *, segmentation='valleys', grammar_suffix=False, localized=False, alternative=None):
    if segmentation not in ('columns', 'valleys'):
        raise ValueError('unknown segmentation method')
    if grammar_suffix and not localized:
        raise ValueError('Grammar-assisted suffixes require an independently localized field ROI')
    if crop.width > 512 or crop.height > 96 or not 1 <= len(bank) <= 4:
        return dict(exp=None, percentage=None, status='unavailable', reason='input_bounds', attempts=[])
    attempts = []
    for index, (profile, templates) in enumerate(bank):
        reader = (lambda binary, gray: alternative(index, binary, gray)) if alternative is not None else None
        white = crop.convert('L').point(lambda p: 255 if p > profile.digit_threshold else 0)
        bands = [(a, b) for a, b in columns(white.transpose(Image.Transpose.TRANSPOSE))
                 if profile.height - 2 <= b-a <= profile.height]
        if len(bands) != 1:
            continue
        top, bottom = bands[0]
        # Keep the complete text band; a separate one-row progress bar is not text.
        for y in range(max(0, bottom - profile.height), min(top, crop.height - profile.height) + 1):
            color_line = crop.crop((0, y, crop.width, y + profile.height))
            gray_line = color_line.convert('L') if reader is not None else None
            line = white.crop((0, y, crop.width, y + profile.height))
            anchors = brackets(color_line, profile)
            strict_closings = set(anchors[']'])
            if grammar_suffix:
                anchors = brackets(color_line, profile, infer_closing=True, templates=templates)
            for opening in anchors['[']:
                for closing in anchors[']']:
                    begin = opening + profile.widths['[']
                    end = closing + profile.widths[']']
                    if opening == 0 or closing <= begin or line.crop((end, 0, line.width, line.height)).getbbox():
                        continue
                    exp, exp_detail = field(line.crop((0, 0, opening, line.height)), templates, 'exp', segmentation,
                        gray=gray_line.crop((0, 0, opening, line.height)) if reader else None, alternative=reader)
                    percent, percent_detail = field(line.crop((begin, 0, closing, line.height)), templates, 'percentage', segmentation,
                        gray=gray_line.crop((begin, 0, closing, line.height)) if reader else None, alternative=reader)
                    if grammar_suffix and percent is None:
                        percent, percent_detail = grammar_percentage(
                            line.crop((begin, 0, closing, line.height)), profile, templates, segmentation,
                            gray=gray_line.crop((begin, 0, closing, line.height)) if reader else None, alternative=reader)
                    if closing not in strict_closings:
                        # A guessed close is usable only with independently verified numbers.
                        if percent is None:
                            continue
                        percent_detail = {**percent_detail, 'inferred_closing': True}
                    attempts.append(dict(profile=index, y=y, opening=opening, closing=closing,
                                         exp=exp, percentage=percent, exp_detail=exp_detail,
                                         percentage_detail=percent_detail))
    values = {key: {a[key] for a in attempts if a[key] is not None} for key in ('exp', 'percentage')}
    if any(len(v) > 1 for v in values.values()):
        return dict(exp=None, percentage=None, status='ambiguous', reason='conflicting_candidates', attempts=attempts)
    exp, percent = (next(iter(values[k]), None) for k in ('exp', 'percentage'))
    # Partial fields may be reported, but a complete pair must share one segmentation.
    complete = exp is not None and percent is not None and any(
        a['exp'] == exp and a['percentage'] == percent for a in attempts)
    return dict(exp=exp, percentage=percent, status='candidate' if complete else 'unavailable',
                reason=None if complete else 'incomplete_fields' if attempts else 'no_verified_bracket_pair',
                attempts=attempts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--bank', type=Path, required=True)
    parser.add_argument('--segmentation', choices=('columns', 'valleys'), default='valleys')
    parser.add_argument('--grammar-suffix', action='store_true')
    parser.add_argument('--localized', action='store_true', help='Input ROI was independently localized/verified')
    args = parser.parse_args(argv)
    bank = load_bank(args.bank)
    with Image.open(args.image) as image:
        print(json.dumps(recognize(image, bank, segmentation=args.segmentation,
            grammar_suffix=args.grammar_suffix, localized=args.localized), indent=2))


if __name__ == '__main__':
    main()
