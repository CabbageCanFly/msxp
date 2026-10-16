"""Offline level/EXP scoring; expected answers never reach experimental recognition.

Accepts the frozen recording manifest or examples with relative exp_crop paths.
--levels joins saved outputs from unchanged level recognizers, never OCR labels.
All outputs contain private observations and must remain in ignored directories.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time

from PIL import Image

from exp_tracker.glyphs import GlyphProfile, match_exp
from exp_tracker.parsing import parse_exp
from exp_digits import load_bank, recognize


def score(result, expected, levels):
    def category(value, target):
        return 'unavailable' if value is None else 'correct' if value == target else 'incorrect'
    pair = (result['exp'], result['percentage']) if result['status'] == 'candidate' else None
    target = (expected['current_exp'], expected['percentage'])
    metrics = dict(exp=category(result['exp'], expected['current_exp']),
                   percentage=category(result['percentage'], expected['percentage']),
                   complete_exp=category(pair, target))
    for name, level in levels.items():
        full = (level, *pair) if pair is not None and level is not None else None
        metrics['complete_' + name] = category(full, (expected['level'], *target))
    return metrics


def main(argv=None):
    from exp_tracker.metrics import ResourceMonitor
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--engine', choices=('baseline', 'columns', 'valleys', 'grammar'), required=True)
    parser.add_argument('--bank', type=Path)
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--levels', type=Path, required=True)
    parser.add_argument('--adaptive-results', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if (args.engine == 'baseline' and not args.profile) or (args.engine != 'baseline' and not args.bank):
        parser.error('baseline needs --profile; experimental modes need --bank')
    os.environ.setdefault('OMP_THREAD_LIMIT', '1')
    data = json.loads(args.manifest.read_text(encoding='utf-8'))
    levels = json.loads(args.levels.read_text(encoding='utf-8'))['readings']
    if set(levels) != {e['id'] for e in data['examples']}:
        raise ValueError('level outputs must cover exactly the scoring inputs')
    profile = GlyphProfile.load(args.profile) if args.profile else None
    bank = load_bank(args.bank) if args.bank else None
    paths = [args.manifest, args.levels, Path(__file__).with_name('exp_digits.py')]
    paths += [p for p in (args.bank, args.profile, args.adaptive_results) if p]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    automatic = None
    if args.adaptive_results:
        from evaluate_adaptive_hud import frame_at
        from exp_tracker.models import Region
        automatic = {r['expected']['id']: r for r in json.loads(args.adaptive_results.read_text())['records']}
    prepared = []
    for item in data['examples']:
        image = None
        if automatic is not None:
            row = automatic[item['id']]
            assert all(row['expected'][k] == item[k] for k in ('level', 'current_exp', 'percentage', 'seconds'))
            if row['candidates'] == 1:
                frame = frame_at(args.manifest.parent / data['video'], item['seconds'])
                image = frame.crop(Region(**row['result']['regions']['exp']).pixels(*frame.size))
                del frame
        else:
            if 'exp_crop' in item:
                path = args.manifest.parent / item['exp_crop']
            else:
                run, index = item['id'].split('/')
                path = args.manifest.parent / data['crop_root'] / f'{run}-crops' / f'{int(index):04d}' / 'exp-crop.png'
            if path.exists():
                with Image.open(path) as im:
                    image = im.convert('RGB')
            elif item['current_exp'] is not None:
                raise FileNotFoundError(path)
        prepared.append((item, image))
    rows = []
    monitor = ResourceMonitor(sample_interval=.01, scope='EXP/percentage only; excludes image loading, localization and level OCR')
    cpu_start = time.process_time()
    try:
        for expected, image in prepared:
            start = time.perf_counter()
            if image is None:
                result = dict(exp=None, percentage=None, status='unavailable', reason='missing_crop_or_location')
            elif args.engine == 'baseline':
                attempt = match_exp(image, profile)
                value = parse_exp(attempt['text'])
                result = dict(exp=value[0] if value else None, percentage=value[1] if value else None,
                              status='candidate' if value else 'unavailable', attempt=attempt)
            else:
                result = recognize(image, bank, segmentation='valleys' if args.engine == 'grammar' else args.engine,
                                   grammar_suffix=args.engine == 'grammar', localized=True)
            elapsed = time.perf_counter() - start
            rows.append(dict(id=expected['id'], seconds=expected.get('seconds'),
                expected={k: expected[k] for k in ('level', 'current_exp', 'percentage')},
                metrics=score(result, expected, levels[expected['id']]), result=result, seconds_elapsed=elapsed))
    finally:
        cpu_seconds = time.process_time() - cpu_start
        monitor.close()
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in hashes.items())
    timings = sorted(r['seconds_elapsed'] for r in rows)
    summary = dict(counts={k: dict(Counter(r['metrics'][k] for r in rows)) for k in rows[0]['metrics']},
        mean_seconds=statistics.mean(timings), p95_seconds=timings[math.ceil(.95 * len(timings))-1],
        python_cpu_seconds=cpu_seconds, resources=monitor.snapshot())
    args.output.write_text(json.dumps(dict(engine=args.engine, hashes=hashes,
        summary=summary, records=rows), indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 1 if any(c.get('incorrect', 0) for c in summary['counts'].values()) else 0


if __name__ == '__main__':
    raise SystemExit(main())
