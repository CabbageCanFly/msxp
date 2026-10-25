"""Offline, review-only name OCR. Never opens a tracker database or network source."""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from exp_tracker.recognition import _ocr, configure_tesseract
from exp_tracker.video import MAX_PIXELS, MAX_PNG_BYTES
from adaptive_hud import locate
from evaluate_adaptive_hud import frame_at
from shadow_neural import EXP_SIZE, png_bytes


def name_text(text):
    """Conservative diagnostic syntax, not a claim about all game naming rules."""
    text = text.strip() if isinstance(text, str) else ''
    # shortcut: Latin/digit names only; expand after labeled non-Latin footage exists.
    return text if re.fullmatch(r'[A-Za-z][A-Za-z0-9]{1,11}', text) else None


def checked_box(box, size):
    if (len(box) != 4 or any(type(v) is not int for v in box)
            or not 0 <= box[0] < box[2] <= size[0]
            or not 0 <= box[1] < box[3] <= size[1]):
        raise ValueError('Region must be nonempty integer pixels inside the image')
    if box[2] - box[0] > EXP_SIZE[0] or box[3] - box[1] > EXP_SIZE[1]:
        raise ValueError('Name region exceeds the existing OCR crop limit')
    return list(box)


def name_region(layout, size):
    """Extract from an ALREADY located HUD; performs no localization or OCR."""
    hp, step = layout['anchors']['hp'], layout['anchor_step']
    # shortcut: name beneath job in the Classic status panel; other UI needs a manual region.
    box = [round(hp['x'] - 1.28 * step), round(hp['y'] + .10 * step),
           round(hp['x'] - .06 * step), round(hp['y'] + .265 * step)]
    # Rounded HUD offsets can put the bottom padding one pixel beyond a flush frame edge.
    if box[3] == size[1] + 1:
        box[3] = size[1]
    return dict(box=checked_box(box, size), ownership='status_panel_candidate',
                anchors=layout['anchors'], anchor_step=step)


def job_region(layout, size):
    """The job line directly above the name; same left and right edges."""
    hp, step = layout['anchors']['hp'], layout['anchor_step']
    name = name_region(layout, size)['box']
    return checked_box([name[0], round(hp['y'] - .065 * step), name[2], round(hp['y'] + .10 * step)], size)


def second_look(crop):
    """The name crop without its right panel edge, with background margin all round.
    It reads touching glyphs ("yv" read as "w") that the plain crop misses, but it also
    misreads some names the plain crop gets right, so it may only confirm a known name."""
    crop = crop.convert('RGB').crop((0, 0, crop.width - 3, crop.height))
    padded = Image.new('RGB', (crop.width + 12, crop.height + 12), crop.getpixel((0, 0)))
    padded.paste(crop, (6, 6))
    return padded


def name_regions(image):
    """Reuse HUD anchor agreement; retain every layout rather than choosing one."""
    layouts = locate(image)
    regions = []
    for layout in layouts:
        try:
            regions.append(name_region(layout, image.size))
        except ValueError:
            continue
    # Include invalid geometries in ambiguity accounting too.
    return regions, len(layouts)


def tesseract(crop, box):
    started = time.perf_counter()
    processed = ImageOps.invert(crop.convert('L')).resize(
        (crop.width * 2, crop.height * 2), Image.Resampling.BICUBIC)
    tokens = _ocr(processed, 7)
    raw = [dict(t, box=[box[0] + t['x'] / 2, box[1] + t['y'] / 2,
                       box[0] + (t['x'] + t['width']) / 2,
                       box[1] + (t['y'] + t['height']) / 2]) for t in tokens]
    return dict(engine='tesseract', text=' '.join(t['text'] for t in tokens),
                score=min((t['confidence'] for t in tokens), default=0), raw=raw,
                seconds=time.perf_counter() - started)


def rapidocr(crop, python):
    """Reuse the isolated local-model worker, including its no-download policy."""
    started = time.perf_counter()
    worker = Path(__file__).with_name('shadow_rapidocr.py')
    process = subprocess.run([str(python), str(worker)], input=png_bytes(crop, EXP_SIZE),
                             capture_output=True, timeout=30, check=True)
    evidence = json.loads(process.stdout)
    scores = evidence['raw'].get('scores') or []
    return dict(engine='rapidocr', text=evidence['text'],
                score=scores[0] if len(scores) == 1 else 0, raw=evidence,
                seconds=time.perf_counter() - started)


def candidate(region, attempts):
    names = sorted({name for a in attempts if a.get('score', 0) >= .5
                    and (name := name_text(a.get('text'))) is not None})
    return dict(**region, names=names, attempts=attempts,
                status='candidate' if len(names) == 1 else 'ambiguous' if names else 'unknown')


def summarize(frames):
    """Agreement is a review proposal, never character selection or tracking truth."""
    support = {}
    ambiguous = False
    for frame in frames:
        # Any second HUD (even unreadable) defeats ownership by uniqueness.
        if frame['layout_count'] > 1:
            ambiguous = True
            continue
        for item in frame['candidates']:
            if item['ownership'] == 'unverified_region':
                continue
            if len(item['names']) > 1:
                ambiguous = True
            for name in item['names']:
                support.setdefault(name, set()).add(frame['pixel_sha256'])
    counts = {name: len(hashes) for name, hashes in sorted(support.items())}
    if ambiguous or len(counts) > 1:
        status, reason, proposed = 'ambiguous', 'conflicting_names_or_multiple_huds', None
    elif counts and next(iter(counts.values())) >= 2:
        status, reason, proposed = 'review_required', 'agreement_across_distinct_frames', next(iter(counts))
        latest = frames[-1]['candidates']
        if not any(proposed in item['names'] and item['ownership'] != 'unverified_region' for item in latest):
            status, reason, proposed = 'unknown', 'latest_frame_has_no_owner_evidence', None
    else:
        status, reason, proposed = 'unknown', 'insufficient_owner_scoped_agreement', None
    return dict(status=status, reason=reason, proposed_name=proposed,
                distinct_frame_support=counts, trusted=False)


def inspect_frame(image, source, *, engine='tesseract', rapid_python=None, region=None,
                  owner_field=False):
    started = time.perf_counter()
    if image.width * image.height > MAX_PIXELS or min(image.size) < 1:
        raise ValueError('Frame exceeds existing capture pixel limit')
    image = image.convert('RGB')
    digest = hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest()
    if region is None:
        regions, layout_count = name_regions(image)
    else:
        regions = [dict(box=checked_box(region, image.size),
                        ownership='operator_asserted_field' if owner_field else 'unverified_region')]
        layout_count = 0
    if len(regions) > 8:
        return dict(source=source, size=image.size, pixel_sha256=digest,
                    layout_count=layout_count, candidates=[], reason='candidate_limit',
                    seconds=time.perf_counter() - started)
    candidates = []
    for field in regions:
        crop = image.crop(field['box'])
        attempts = []
        for selected in (('tesseract', 'rapidocr') if engine == 'both' else (engine,)):
            try:
                attempt = tesseract(crop, field['box']) if selected == 'tesseract' else rapidocr(crop, rapid_python)
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
                attempt = dict(engine=selected, text=None, score=0, error=type(error).__name__)
            attempts.append(attempt)
        candidates.append(candidate(field, attempts))
    return dict(source=source, size=image.size, pixel_sha256=digest,
                layout_count=layout_count, candidates=candidates,
                seconds=time.perf_counter() - started)


def write_review(report, images, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    with output.with_suffix('.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['frame', 'source', 'box', 'ownership', 'status', 'names', 'engine', 'text', 'score', 'error'])
        for i, frame in enumerate(report['frames']):
            for item in frame['candidates']:
                for a in item['attempts']:
                    writer.writerow([i, frame['source'], item['box'], item['ownership'], item['status'],
                                     '|'.join(item['names']), a['engine'], a.get('text'), a.get('score'), a.get('error')])
    rows = [(i, item) for i, f in enumerate(report['frames']) for item in f['candidates']]
    if not rows:
        return
    sheet = Image.new('RGB', (1000, 110 * len(rows)), 'white')
    draw = ImageDraw.Draw(sheet)
    for row, (index, item) in enumerate(rows):
        crop = images[index].crop(item['box'])
        crop = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.NEAREST)
        crop.thumbnail((980, 72))
        sheet.paste(crop, (10, row * 110 + 30))
        label = f"{index}: {item['ownership']} {item['status']} {item['names']} {item['box']}"
        draw.text((10, row * 110 + 5), label, fill='black')
    sheet.save(output.with_suffix('.png'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('images', nargs='*', type=Path)
    parser.add_argument('--video', type=Path)
    parser.add_argument('--times', help='Comma-separated local-video timestamps in seconds')
    parser.add_argument('--region', help='Manual name-line region: x0,y0,x1,y1 in source pixels')
    parser.add_argument('--owner-field', action='store_true', help='Operator asserts this region is the own-name field')
    parser.add_argument('--engine', choices=['tesseract', 'rapidocr', 'both'], default='tesseract')
    parser.add_argument('--rapid-python', type=Path, help='Existing isolated RapidOCR Python executable')
    parser.add_argument('--output', type=Path, default=Path('private/character-name-ocr/report.json'))
    args = parser.parse_args(argv)
    try:
        if bool(args.images) == bool(args.video) or args.video and not args.times or args.times and not args.video:
            raise ValueError('Supply images OR a local --video with --times')
        if args.owner_field and not args.region:
            raise ValueError('--owner-field requires an explicit --region')
        if args.output.suffix.lower() != '.json':
            raise ValueError('--output must end in .json; derived CSV/PNG contain private evidence')
        if args.engine != 'tesseract' and (not args.rapid_python or not args.rapid_python.is_file()):
            raise ValueError('Neural OCR requires an existing --rapid-python executable')
        region = [int(v) for v in args.region.split(',')] if args.region else None
        sources = args.images
        times = [float(v) for v in args.times.split(',')] if args.video else []
        if len(sources or times) > 32:
            raise ValueError('Limit the investigation to at most 32 samples per command')
        if any(not math.isfinite(v) or v < 0 for v in times):
            raise ValueError('Video times must be finite nonnegative seconds')
        times.sort()
        for path in sources or [args.video]:
            if not path.is_file():
                raise ValueError(f'Local input file required: {path}')
        if region is None or args.engine != 'rapidocr':
            configure_tesseract()
        images, frames = [], []
        for path, seconds in ([(p, None) for p in sources] if sources else [(args.video, t) for t in times]):
            if seconds is None:
                if path.stat().st_size > MAX_PNG_BYTES:
                    raise ValueError('Image exceeds existing capture byte limit')
                with Image.open(path) as source:
                    if source.width * source.height > MAX_PIXELS:
                        raise ValueError('Frame exceeds existing capture pixel limit')
                    image = source.convert('RGB')
            else:
                image = frame_at(path.resolve(), seconds)
            images.append(image)
            label = str(path.resolve()) + (f' @ {seconds:g}s' if seconds is not None else '')
            frames.append(inspect_frame(image, label, engine=args.engine, rapid_python=args.rapid_python,
                                        region=region, owner_field=args.owner_field))
        report = dict(schema=1, engine=args.engine, preprocessing='fixed_2x',
                      score_note='Uncalibrated engine scores; names are case sensitive; no spelling repair',
                      frames=frames, summary=summarize(frames))
        write_review(report, images, args.output)
        print(json.dumps(dict(output=str(args.output), **report['summary'])))
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f'{type(error).__name__}: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
