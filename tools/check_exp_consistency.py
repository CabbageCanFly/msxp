"""Conditional arithmetic diagnostics for saved RapidOCR output, never ingestion.

Requirements must come from explicit external data. Rounding is an explicit
hypothesis, not a fitted tolerance; neither model confidence nor labels are used.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from benchmark_rapidocr import interpret


from exp_tracker.exp_consistency import MODES, assess


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
