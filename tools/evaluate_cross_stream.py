"""Sparse private cross-stream evaluation; never calibrates or changes recognition.

Prepare crops/contact sheets, visually annotate manifest.json, then evaluate.
Manual boxes are evaluator-only diagnostics, never passed to the automatic locator.
"""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

from PIL import Image, ImageDraw

from evaluate_adaptive_hud import field_truth, frame_at
from evaluate_exp_digits import score


def probe(video):
    result = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(video)], capture_output=True, timeout=30)
    text = result.stderr.decode('utf-8', errors='replace')
    duration = re.search(r'Duration: (\d+):(\d+):([\d.]+)', text)
    geometry = re.search(r'Video: (\w+).*?, (\d+)x(\d+).*?, ([\d.]+) fps', text)
    if duration is None or geometry is None:
        raise ValueError('FFmpeg metadata unavailable')
    h, m, s = map(float, duration.groups())
    codec, width, height, fps = geometry.groups()
    return dict(duration_seconds=3600*h + 60*m + s, codec=codec,
                width=int(width), height=int(height), fps=float(fps), bytes=video.stat().st_size)


def sample_times(duration, count):
    if count < 2 or duration <= 1:
        raise ValueError('need at least two frames and duration >1 second')
    return [round(i * (duration - 1) / (count - 1), 3) for i in range(count)]


def box(text):
    result = tuple(map(int, text.split(',')))
    if len(result) != 4 or not 0 <= result[0] < result[2] or not 0 <= result[1] < result[3]:
        raise argparse.ArgumentTypeError('expected nonnegative x0,y0,x1,y1')
    return result


def save_sheets(directory, manifest):
    examples = manifest['examples']
    boxes = manifest['field_boxes']
    for page in range(0, len(examples), 9):
        sheet = Image.new('RGB', (1600, 9*240), '#18202b')
        draw = ImageDraw.Draw(sheet)
        for line, row in enumerate(examples[page:page+9]):
            top = line * 240
            draw.text((10, top+3), f"{row['id']}  t={row['seconds']:.3f}s  VISUAL LABELING ONLY", fill='white')
            with Image.open(directory / row['frame']) as image:
                hud = image.crop(row.get('hud_box', manifest['hud_box']))
                hud.thumbnail((1580, 85))
                sheet.paste(hud, (10, top+22))
                for field, left in [('level', 10), ('exp', 350)]:
                    crop = image.crop(row.get('field_boxes', boxes)[field])
                    crop = crop.resize((crop.width*4, crop.height*4), Image.Resampling.NEAREST)
                    sheet.paste(crop, (left, top+108))
        sheet.save(directory / f'hud-{page//9+1:02d}.png')
    context = Image.new('RGB', (1600, ((len(examples)+4)//5)*204), '#18202b')
    draw = ImageDraw.Draw(context)
    for index, row in enumerate(examples):
        left, top = (index % 5)*320, (index//5)*204
        draw.text((left, top), f"{index:02d}: {row['seconds']:.3f}s", fill='white')
        with Image.open(directory / row['frame']) as image:
            image.thumbnail((320, 180))
            context.paste(image, (left, top+22))
    context.save(directory / 'context.png')


def prepare(args):
    directory = args.directory
    if (directory / 'manifest.json').exists():
        raise ValueError('manifest already exists; refusing to overwrite annotations')
    metadata = probe(args.video)
    directory.mkdir(parents=True, exist_ok=True)
    examples = []
    for index, seconds in enumerate(sample_times(metadata['duration_seconds'], args.count)):
        examples.append(dict(id=f'stream{args.stream}/{index}', seconds=seconds,
            frame=f'frames/{index:04d}.png', split='heldout', complete=False,
            level=None, current_exp=None, percentage=None, human_verified=False,
            label_source='Codex visual transcription, provisional', note='not yet labeled'))
    manifest = dict(video=os.path.relpath(args.video.resolve(), directory.resolve()), metadata=metadata,
                    sampling='uniform timestamps including first and duration-1; frozen before OCR',
                    hud_box=args.hud, field_boxes=dict(level=args.level, exp=args.exp),
                    secondary_box=args.secondary, crop_root='manual-crops', examples=examples)
    def extract(row):
        image = frame_at(args.video, row['seconds'])
        frame = directory / row['frame']
        frame.parent.mkdir(parents=True, exist_ok=True)
        image.save(frame)
        run, index = row['id'].split('/')
        crops = directory / 'manual-crops' / f'{run}-crops' / f'{int(index):04d}'
        crops.mkdir(parents=True, exist_ok=True)
        for field, bounds in manifest['field_boxes'].items():
            image.crop(bounds).save(crops / f'{field}-crop.png')
    with ThreadPoolExecutor(max_workers=2) as pool:
        for count, _ in enumerate(pool.map(extract, examples), 1):
            if count % 5 == 0:
                print(f'{directory}: extracted {count}/{len(examples)}', flush=True)
    save_sheets(directory, manifest)
    (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(metadata), flush=True)


def target_category(candidates, hud, secondary, size):
    if len(candidates) != 1:
        return 'ambiguous' if candidates else 'missing'
    regions = candidates[0]['regions']
    if set(regions) != {'level', 'exp'}:
        return 'wrong_other'
    def inside(bounds):
        return bounds is not None and all(
            bounds[0] <= (b[0]+b[2])/2 <= bounds[2] and bounds[1] <= (b[1]+b[3])/2 <= bounds[3]
            for b in (r.pixels(*size) for r in regions.values()))
    return 'main' if inside(hud) else 'wrong_secondary' if inside(secondary) else 'wrong_other'


def provisional_metrics(result, expected, levels):
    metrics = score(result, expected, levels)
    targets = dict(exp=expected['current_exp'], percentage=expected['percentage'],
                   complete_exp=(expected['current_exp'], expected['percentage']),
                   complete_tesseract=(expected['level'], expected['current_exp'], expected['percentage']),
                   complete_pixel=(expected['level'], expected['current_exp'], expected['percentage']))
    for key, value in metrics.items():
        unknown = targets[key] is None or isinstance(targets[key], tuple) and None in targets[key]
        metrics[key] = ('unscored' if unknown else 'mismatch_provisional' if value == 'incorrect'
                        else 'matches_provisional' if value == 'correct' else 'unavailable')
    return metrics


def evaluate(args):
    from adaptive_hud import locate, level_reading
    from exp_digits import load_bank, recognize
    import grayscale_digits
    from level_digits import load_profile, read_level
    from exp_tracker.metrics import ResourceMonitor
    os.environ.setdefault('OMP_THREAD_LIMIT', '1')
    directory = args.manifest.parent
    data = json.loads(args.manifest.read_text(encoding='utf-8'))
    if any(row['note'] == 'not yet labeled' for row in data['examples']):
        raise ValueError('visually annotate before recognition, explicitly marking unknown fields')
    bank_path = Path('private/exp-digits/bank.json')
    model_path = Path('private/numeric-classifier/model.json')
    level_path = Path('private/level-digits/profile.json')
    files = [args.manifest, bank_path, model_path, level_path, Path(__file__)]
    files += [Path(__file__).with_name(name) for name in
              ('adaptive_hud.py', 'exp_digits.py', 'level_digits.py', 'grayscale_digits.py', 'evaluate_exp_digits.py')]
    for family in json.loads(bank_path.read_text())['families']:
        files += [bank_path.parent / family['profile']]
        files += [bank_path.parent / row['image'] for row in family['characters']]
    hashes = {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    snapshot = directory / 'annotations-before-ocr.json'
    if not snapshot.exists():
        snapshot.write_bytes(args.manifest.read_bytes())
    bank = load_bank(bank_path)
    models = grayscale_digits.load(model_path, bank_path)
    profile = load_profile(level_path)
    records = []
    monitor = ResourceMonitor(sample_interval=.02, scope='cross-stream evaluation; no FFmpeg extraction')
    try:
        for item in data['examples']:
            started = time.perf_counter()
            with Image.open(directory / item['frame']) as source:
                image = source.convert('RGB')
            candidates = locate(image)
            located_at = time.perf_counter()
            target = target_category(candidates, item.get('hud_box', data['hud_box']), data['secondary_box'], image.size)
            boxes = item.get('field_boxes', data['field_boxes'])
            truth = field_truth(image, boxes)
            automatic = candidates[0]['regions'] if len(candidates) == 1 else {}
            scopes = {}
            for scope, regions in [('manual', boxes), ('automatic', automatic)]:
                crops = {k: image.crop(v.pixels(*image.size) if hasattr(v, 'pixels') else v) for k,v in regions.items()}
                level, attempts = level_reading(crops['level']) if crops else (None, [])
                pixel = read_level(crops['level'], profile) if crops else dict(level=None, reason='no_region')
                levels = dict(tesseract=level, pixel=pixel['level'])
                level_scores = {k: 'unscored' if item['level'] is None else 'unavailable' if v is None
                                else 'matches_provisional' if v == item['level'] else 'mismatch_provisional'
                                for k,v in levels.items()}
                if scope == 'automatic' and target.startswith('wrong_'):
                    level_scores = {k: 'wrong_target' if levels[k] is not None else v for k,v in level_scores.items()}
                results = {}
                for mode in ('valleys', 'grammar', 'grayscale'):
                    tick = time.perf_counter()
                    if not crops:
                        result = dict(status='unavailable', exp=None, percentage=None, reason='no_region')
                    elif mode == 'grayscale':
                        result = grayscale_digits.recognize(crops['exp'], bank, models)
                    else:
                        result = recognize(crops['exp'], bank, segmentation='valleys',
                                           grammar_suffix=mode == 'grammar', localized=True)
                    metrics = provisional_metrics(result, item, levels)
                    if scope == 'automatic' and target.startswith('wrong_'):
                        availability = score(result, item, levels)
                        metrics = {k: 'wrong_target' if availability[k] != 'unavailable' else v for k,v in metrics.items()}
                    results[mode] = dict(result=result, metrics=metrics, seconds=time.perf_counter()-tick)
                scopes[scope] = dict(levels=levels, level_scores=level_scores,
                                     tesseract_attempts=attempts, pixel_detail=pixel, modes=results)
                if scope == 'automatic' and crops:
                    output = directory / 'automatic-crops' / item['id'].split('/')[1]
                    output.mkdir(parents=True, exist_ok=True)
                    for key, crop in crops.items(): crop.save(output / f'{key}.png')
            contained = {key: all((box[0] <= bounds[0], box[1] <= bounds[1], box[2] >= bounds[2], box[3] >= bounds[3]))
                         for key,bounds in truth.items() if key in automatic
                         for box in [automatic[key].pixels(*image.size)]}
            records.append(dict(id=item['id'], seconds=item['seconds'], expected=item,
                frame_sha256=hashlib.sha256((directory/item['frame']).read_bytes()).hexdigest(),
                location=target, candidates=[{**c, 'regions': {k:asdict(v) for k,v in c['regions'].items()}} for c in candidates],
                fields_contained=contained, location_seconds=located_at-started,
                total_seconds=time.perf_counter()-started, scopes=scopes))
            if len(records) % 5 == 0:
                print(f'{directory}: {len(records)}/{len(data["examples"])}; location {dict(Counter(r["location"] for r in records))}', flush=True)
    finally:
        monitor.close()
    if any(hashlib.sha256(Path(p).read_bytes()).hexdigest() != h for p,h in hashes.items()):
        raise ValueError('frozen input changed during evaluation')
    summary = dict(location=dict(Counter(r['location'] for r in records)),
        annotations='provisional Codex transcriptions; counts are label agreement, not human-verified accuracy',
        human_verified=sum(e['human_verified'] for e in data['examples']), scopes={})
    for scope in ('manual', 'automatic'):
        summary['scopes'][scope] = dict(
            levels={name: dict(Counter(r['scopes'][scope]['level_scores'][name] for r in records)) for name in ('tesseract','pixel')},
            modes={mode: {metric: dict(Counter(r['scopes'][scope]['modes'][mode]['metrics'][metric] for r in records))
                          for metric in records[0]['scopes'][scope]['modes'][mode]['metrics']}
                   for mode in ('valleys','grammar','grayscale')})
    output = args.output or directory / 'results.json'
    output.write_text(json.dumps(dict(input_hashes=hashes, summary=summary, resources=monitor.snapshot(), records=records), indent=2)+'\n', encoding='utf-8')
    print(json.dumps(summary), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('video', type=Path)
    prep.add_argument('directory', type=Path)
    prep.add_argument('--stream', type=int, required=True)
    prep.add_argument('--count', type=int, default=45)
    prep.add_argument('--hud', type=box, required=True)
    prep.add_argument('--level', type=box, required=True)
    prep.add_argument('--exp', type=box, required=True)
    prep.add_argument('--secondary', type=box)
    evaluation = commands.add_parser('evaluate')
    evaluation.add_argument('manifest', type=Path)
    evaluation.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    prepare(args) if args.command == 'prepare' else evaluate(args)


if __name__ == '__main__':
    main()
