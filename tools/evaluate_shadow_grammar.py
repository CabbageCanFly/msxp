"""Replay frozen shadow evidence into separate grammar hypotheses and strict-only pace."""

import argparse
from collections import Counter
import json
from pathlib import Path
import time

from grammar_recovery import propose
from percentage_progress import progress
from shadow_review import checked_manifest, digest, dump_new, private, read_run, read_sealed


def compare(reading, expected):
    fields = [('level', 'visual_level')] if reading['kind']=='level_text' else [('percentage','percentage')]
    if reading['kind']=='full_exp_pair':
        fields.append(('exp','exp'))
    unknown = False
    for actual, reference in fields:
        target = expected[reference][0]
        if target is None:
            unknown = True
        elif str(reading[actual]) != (f'{target:.2f}' if reference=='percentage' else str(target)):
            return 'disagreement'
    return 'unknown_reference' if unknown else 'agreement'


def control_intent(path):
    """Read the recorded source intent, not a label inferred from corrupted OCR."""
    source = json.loads(path.read_text(encoding='utf-8'))['examples'][0]
    return dict(exp=[source['current_exp']], percentage=[source['percentage']])


def evaluate(prepared, output, pixel_review, level_diagnostics, negatives, negative_results, contamination):
    prepared, output = private(prepared), private(output)
    if output.exists():
        raise ValueError('Use a new output directory; never replace evidence')
    manifest = checked_manifest(prepared)
    references = read_sealed(prepared/'references.json')
    evaluation_path = prepared/'evaluation.json'
    frozen = json.loads(evaluation_path.read_text(encoding='utf-8'))
    if (references['manifest_sha256'] != digest(prepared/'manifest.json')
            or frozen['references_sha256'] != digest(prepared/'references.json')):
        raise ValueError('Frozen evaluation and reference seals disagree')
    paths = {private(prepared/path) for path in manifest['inputs']}
    paths.update(path for path in prepared.iterdir() if path.is_file())
    paths.update(private(path) for path in (pixel_review, level_diagnostics, negatives, negative_results, contamination))
    intent_path = private('private/rapidocr-context/negatives/manifest.json')
    paths.add(intent_path)
    negative_manifest = json.loads(Path(negatives).read_text(encoding='utf-8'))
    paths.update(private(Path(negatives).parent/e['exp_crop'].replace('\\','/')) for e in negative_manifest['examples'])
    before = {str(path.relative_to(Path.cwd())):digest(path) for path in sorted(paths)}
    output.mkdir(parents=True, exist_ok=False)
    dump_new(output/'input-hashes.json', before)
    started, cpu = time.perf_counter(), time.process_time()
    pixels = json.loads(Path(pixel_review).read_text(encoding='utf-8'))
    cases, paces = [], {}
    for stream in manifest['streams']:
        config, attempts = read_run(private(prepared/stream['log']))
        paces[stream['id']] = progress(attempts, interval_seconds=config['interval'])
    for old in frozen['results']:
        review = pixels['cases'].get(old['id'], {})
        result = propose(old['raw_text'], source_complete=review.get('source_complete'))
        scores = [compare(p['reading'],old['expected']) for p in result['proposals']]
        cases.append(dict(id=old['id'], stream=old['stream'], index=old['index'],
            diagnostic=result, pixel_review=review, proposal_scores=scores,
            reference=old['expected'], baseline_scores=old['scores'],
            strict_comparison=compare(result['strict'],old['expected']) if result['strict'] else 'unavailable'))
    assert len(cases)==len(manifest['entries'])==sum(stream['attempts'] for stream in manifest['streams'])
    levels = []
    for case in json.loads(Path(level_diagnostics).read_text(encoding='utf-8')):
        if case['stream'] != 'stream-b':
            continue
        tokens = case['variants']['neutral180_unrestricted_psm7']
        raw = ' '.join(token['text'] for token in tokens)
        old = next(row for row in frozen['results'] if row['stream']=='S02' and row['index']==case['index'])
        probe = propose(raw, field='level', numeric_level_context=True)
        levels.append(dict(index=case['index'], raw_tokens=tokens, diagnostic=probe,
            proposal_scores=[compare(p['reading'],old['expected']) for p in probe['proposals']],
            pixel_review='Two visible orange numeric tiles; native glyph is 5-like/S-like; familiar AI-assisted review only'))
    controls = []
    saved = json.loads(Path(negative_results).read_text(encoding='utf-8'))
    for example in negative_manifest['examples']:
        neural = next(row for row in saved['records'] if row['id']==example['id'] and row['scale']==2 and row['mode']=='line_recognize')
        raw = propose(neural['text'])
        # Source intent is a synthetic-control construction, not a human label of damaged pixels.
        expected = control_intent(intent_path)
        controls.append(dict(id=example['id'], geometry=example['geometry'], diagnostic=raw,
            source_intent_provenance='Existing controlled mutations of the 74,059 / 25.17 source; not independent truth',
            proposal_numeric_comparisons=[compare(p['reading'], expected) for p in raw['proposals']],
            raw_strict_source_comparison=compare(raw['strict'],expected) if raw['strict'] else 'unavailable',
            pixel_review=pixels['controls'].get(example['geometry'], 'Not newly adjudicated'),
            full_field_refused=example['geometry'] in ('missing_close','cropped_close','missing_open','misaligned_left',
                'damaged_close_top','damaged_close_bottom','missing_decimal','trailing_white_digit1','trailing_green_digit1')))
    contaminated = next(row for row in json.loads(Path(contamination).read_text(encoding='utf-8'))['records']
                        if row['id']=='stream2/21')
    controls.append(dict(id='real_contamination', diagnostic=propose(contaminated['text']),
        raw_strict_source_comparison=compare(propose(contaminated['text'])['strict'],
            dict(exp=[contaminated['expected']['current_exp']],percentage=[contaminated['expected']['percentage']])),
        pixel_review='Existing +4px neighboring-label contamination counterexample; wrong complete 2345 versus source 345',
        full_field_refused=False))
    summary = {stream['id']:dict(denominator=stream['attempts'],
        classifications=dict(Counter(row['diagnostic']['classification'] for row in cases if row['stream']==stream['id'])),
        strict_scores=dict(Counter(row['strict_comparison'] for row in cases if row['stream']==stream['id'])),
        proposal_scores=dict(Counter(score for row in cases if row['stream']==stream['id'] for score in row['proposal_scores'])),
        original_metrics=frozen['streams'][stream['id']]['metrics']) for stream in manifest['streams']}
    report = dict(trusted=False, exploratory=True, provenance=frozen['provenance'],
        pixel_review_provenance=pixels['provenance'], baseline_unchanged=True,
        summary=summary, cases=cases, level_hypotheses=levels, negative_controls=controls,
        percentage_progress=paces, wall_seconds=time.perf_counter()-started,
        cpu_seconds=time.process_time()-cpu)
    dump_new(output/'report.json',report)
    if any(digest(Path(path)) != value for path,value in before.items()):
        raise ValueError('Input changed during diagnostics; do not use the report')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared',type=Path,default=Path('private/reliability/review-01'))
    parser.add_argument('--pixel-review',type=Path,default=Path('private/grammar-pace/pixel-review.json'))
    parser.add_argument('--level-diagnostics',type=Path,default=Path('private/percentage-level51/level-diagnostic/results.json'))
    parser.add_argument('--negative-manifest',type=Path,default=Path('private/rapidocr-auto/negative-manifest.json'))
    parser.add_argument('--negative-results',type=Path,default=Path('private/rapidocr-auto/negative-results.json'))
    parser.add_argument('--contamination',type=Path,default=Path('private/rapidocr-context/stream2-pad4.json'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        report=evaluate(args.prepared,args.output,args.pixel_review,args.level_diagnostics,
                        args.negative_manifest,args.negative_results,args.contamination)
    except (OSError,ValueError,KeyError,StopIteration) as error:
        parser.error(str(error))
    print(json.dumps({s:{k:v for k,v in summary.items() if k!='original_metrics'}
                      for s,summary in report['summary'].items()},indent=2))


if __name__=='__main__':
    main()
