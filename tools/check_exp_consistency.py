"""Conditional arithmetic diagnostics for saved RapidOCR output, never ingestion.

Requirements must come from explicit external data. Rounding is an explicit
hypothesis, not a fitted tolerance; neither model confidence nor labels are used.
"""

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

from benchmark_rapidocr import interpret


MODES = ('nearest_half_up', 'truncate')


def assess(level, exp, percentage, requirements, mode):
    if mode not in MODES:
        raise ValueError('Unknown rounding hypothesis')
    result = dict(status='unavailable_numeric', trusted=False, authoritative=False)
    if type(exp) is not int or exp < 0 or percentage is None or isinstance(percentage, bool):
        return result
    try:
        percent = Decimal(str(percentage))
        if not percent.is_finite() or not 0 <= percent <= 100:
            return result
        bp = percent * 100
        if bp != bp.to_integral_value():
            return result  # No decimal reconstruction or extra rounding of OCR output.
        bp = int(bp)
    except (InvalidOperation, ValueError):
        return result
    if level is None:
        return {**result, 'status': 'unavailable_level'}
    if type(level) is not int or level < 1:
        return {**result, 'status': 'invalid_level'}
    total = requirements.get(level)
    if total is None:
        return {**result, 'status': 'unavailable_requirement'}
    if type(total) is not int or total <= 0:
        raise ValueError('EXP requirement must be a positive integer')
    numerator = 10000 * exp
    if mode == 'truncate':
        actual = numerator // total
        lower, upper, divisor = bp * total, (bp + 1) * total, 10000
    else:
        actual = (2 * numerator + total) // (2 * total)
        lower, upper, divisor = (2 * bp - 1) * total, (2 * bp + 1) * total, 20000
    minimum = max(0, -(-lower // divisor))
    maximum = min(total - 1, -(-upper // divisor) - 1)
    count = max(0, maximum - minimum + 1)
    consistent = exp < total and actual == bp
    return {**result, 'status': 'consistent' if consistent else 'inconsistent',
            'requirement': total, 'displayed_bp': bp, 'calculated_bp': actual,
            'exact_halfway': 2 * (numerator % total) == total,
            'exp_bin': dict(min=minimum, max=maximum, count=count),
            'reason': ('exp_outside_level_or_transition' if exp >= total else
                       None if consistent else 'percentage_disagrees')}


def evaluate(records, levels, requirements, engine, mode, scale=2):
    rows = [r for r in records if r['scale'] == scale and r['mode'] == 'line_recognize']
    ids = [r['id'] for r in rows]
    if len(set(ids)) != len(ids) or set(ids) != set(levels):
        raise ValueError('Cached levels must cover exactly the selected unique OCR frames')
    results = []
    for row in rows:
        parsed = interpret(row['text'])
        pair = parsed['pair'] if parsed['bracketed_syntax'] else None
        level = levels[row['id']][engine]
        check = (assess(level, *pair, requirements, mode) if pair is not None else
                 dict(status='unavailable_pair', trusted=False, authoritative=False))
        results.append(dict(id=row['id'], seconds=row['seconds'], raw_text=row['text'],
                            level=level, pair=pair, check=check))
    candidates = [r for r in results if r['pair'] is not None]
    return dict(records=results, summary=dict(frames=len(rows), complete_candidates=len(candidates),
        candidate_statuses=dict(Counter(r['check']['status'] for r in candidates)),
        unavailable_pairs=len(rows)-len(candidates),
        consistent_unique=sum(r['check']['status']=='consistent' and r['check']['exp_bin']['count']==1 for r in candidates),
        consistent_multiple=sum(r['check']['status']=='consistent' and r['check']['exp_bin']['count']>1 for r in candidates)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('readings', type=Path)
    parser.add_argument('--levels', type=Path, required=True, help='Existing {readings: {id: {tesseract, pixel}}} cache format')
    parser.add_argument('--requirements', type=Path, required=True, help='Externally sourced {to_next: {level: integer}} JSON')
    parser.add_argument('--rounding', choices=MODES, required=True)
    parser.add_argument('--level-engine', choices=('tesseract','pixel'), default='tesseract')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('Refusing to overwrite an existing artifact; choose a new output path')
    paths = [args.readings,args.levels,args.requirements,Path(__file__),Path(__file__).with_name('benchmark_rapidocr.py')]
    hashes = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    table = json.loads(args.requirements.read_text(encoding='utf-8'))
    result = evaluate(json.loads(args.readings.read_text(encoding='utf-8'))['records'],
        json.loads(args.levels.read_text(encoding='utf-8'))['readings'],
        {int(k):v for k,v in table['to_next'].items()},args.level_engine,args.rounding)
    result.update(rounding_hypothesis=args.rounding, level_engine=args.level_engine,
                  authoritative=False, table_provenance={k:v for k,v in table.items() if k!='to_next'}, input_hashes=hashes)
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result['summary']))


if __name__ == '__main__':
    main()
