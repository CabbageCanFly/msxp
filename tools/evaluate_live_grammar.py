"""Offline replay of saved full-EXP grammar hypotheses; no OCR inference or DB writes."""

import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import time

from grammar_recovery import propose_full_exp
from shadow_review import private, read_run, read_sealed, digest, dump_new


def agreement(reading, reference):
    if reading is None:
        return 'unavailable'
    exp, bp = reference['current_exp'], reference['percentage_bp']
    if exp is not None and reading['exp'] != str(exp):
        return 'disagreement'
    if bp is not None and reading['percentage'] != f'{bp//100}.{bp%100:02d}':
        return 'disagreement'
    return 'unknown_reference' if exp is None or bp is None else 'provisional_agreement'


def evaluate(log, reviews, output):
    log, reviews, output = (private(path) for path in (log, reviews, output))
    if output.exists():
        raise ValueError('Use a NEW output directory; never overwrite evidence')
    config, attempts = read_run(log)
    review = read_sealed(reviews)
    if review['input_log_sha256'] != digest(log) or [r['index'] for r in review['entries']] != [r['index'] for r in attempts]:
        raise ValueError('Review does not match the complete original log')
    inputs = {log: digest(log), reviews: digest(reviews)}
    cases = []
    for row, reference in zip(attempts, review['entries']):
        crop = log.with_suffix('') / f'{row["index"]:04d}' / 'exp.png'
        if digest(crop) != reference['crop_sha256']:
            raise ValueError('Reviewed crop changed')
        inputs[crop] = digest(crop)
        raw = (row.get('neural') or {}).get('text')
        diagnostic = propose_full_exp(raw, source_complete=reference['source_complete'])
        text_only = propose_full_exp(raw)
        cases.append(dict(index=row['index'], diagnostic=diagnostic,
            text_only_classification=text_only['classification'], reference=reference,
            strict_comparison=agreement(diagnostic['strict'], reference),
            proposal_comparisons=[agreement(p['reading'], reference) for p in diagnostic['proposals']],
            visual_level=row.get('visual_level'), neural_level=row.get('neural_level'),
            saved_candidate=row.get('candidate'), current=row.get('current')))
    # Replay the existing saved controls and their construction intent, not new model outputs.
    old_path = private('private/grammar-pace/final-report/report.json')
    intent_path = private('private/rapidocr-context/negatives/manifest.json')
    contamination = private('private/rapidocr-context/stream2-pad4.json')
    for path in (old_path, intent_path, contamination):
        inputs[path] = digest(path)
    intent = json.loads(intent_path.read_text())['examples'][0]
    contaminated = next(r for r in json.loads(contamination.read_text())['records'] if r['id']=='stream2/21')['expected']
    controls = []
    for old in json.loads(old_path.read_text())['negative_controls']:
        target = contaminated if old['id']=='real_contamination' else intent
        reference = dict(current_exp=target['current_exp'], percentage_bp=round(target['percentage']*100))
        diagnostic = propose_full_exp(old['diagnostic']['raw'])
        controls.append(dict(id=old['id'], geometry=old.get('geometry'), diagnostic=diagnostic,
            reference=reference, provenance='Saved controlled source intent; not new human ground truth',
            strict_comparison=agreement(diagnostic['strict'],reference),
            proposal_comparisons=[agreement(p['reading'],reference) for p in diagnostic['proposals']],
            source_review_refuses_full_field=old['full_field_refused']))
    raw = [(row.get('neural') or {}).get('text') for row in attempts]
    durations=[]
    cpu = time.process_time()
    for _ in range(100):
        started=time.perf_counter()
        for text in raw:
            propose_full_exp(text)
        durations.append((time.perf_counter()-started)*1000)
    timings=dict(repeats=100, median_batch_ms=statistics.median(durations), p95_batch_ms=sorted(durations)[94],
                 cpu_ms_per_field=(time.process_time()-cpu)*1000/(100*len(raw)),
                 median_ms_per_field=statistics.median(durations)/len(raw),
                 scope='Warm in-process text grammar only; no image/OCR, import, HTTP or DB costs')
    summary=dict(denominator=len(attempts), classifications=dict(Counter(c['diagnostic']['classification'] for c in cases)),
        strict_comparisons=dict(Counter(c['strict_comparison'] for c in cases)),
        proposal_comparisons=dict(Counter(v for c in cases for v in c['proposal_comparisons'])),
        text_only_classifications=dict(Counter(c['text_only_classification'] for c in cases)))
    report=dict(provenance=review['provenance'], trusted=False, configuration=config,
                summary=summary, cases=cases, negative_controls=controls, timings=timings,
                input_hashes={str(path):sha for path,sha in inputs.items()})
    if any(digest(path)!=sha for path,sha in inputs.items()):
        raise ValueError('Frozen input changed')
    output.mkdir(parents=True)
    dump_new(output/'report.json',report)
    return report


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--log',type=Path,required=True)
    cli.add_argument('--reviews',type=Path,required=True)
    cli.add_argument('--output',type=Path,required=True)
    args=cli.parse_args()
    result=evaluate(args.log,args.reviews,args.output)
    print(json.dumps(dict(summary=result['summary'],timings=result['timings']),indent=2))


if __name__=='__main__':
    main()
