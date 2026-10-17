"""Read-only saved-log comparison of versioned diagnostic grammar and published EXP data."""

import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import time
import tracemalloc

from PIL import Image, ImageDraw

from check_exp_consistency import MODES, assess
from evaluate_live_grammar import agreement
from exp_tracker.exp_requirements import community_table
from exp_tracker.shadow_grammar import interpret_exp, propose_full_exp
from shadow_review import private, read_run, read_sealed, digest, dump_new


def percentage_agreement(reading, reference):
    if reading is None:
        return 'unavailable'
    bp = reference['percentage_bp']
    return 'unknown_reference' if bp is None else ('provisional_agreement' if
        reading['percentage'] == f'{bp//100}.{bp%100:02d}' else 'disagreement')


def single(field):
    return field['proposals'][0]['reading'] if field['classification'] == 'unique_proposal' else None


def evaluate(log, reviews, output, reported_level):
    log, reviews, output = (private(p) for p in (log, reviews, output))
    if output.exists() or type(reported_level) is not int or not 1 <= reported_level <= 200:
        raise ValueError('Use a NEW output directory and an explicitly reported level 1–200')
    config, attempts = read_run(log)
    review = read_sealed(reviews)
    if review['input_log_sha256'] != digest(log) or [r['index'] for r in review['entries']] != [r['index'] for r in attempts]:
        raise ValueError('Frozen review must match every scheduled attempt')
    table, table_sha = community_table()
    requirements = {int(k): v for k, v in table['to_next'].items()}
    inputs = {p: digest(p) for p in [log, reviews, reviews.with_suffix('.sha256'), *log.with_suffix('').rglob('*.png')]}
    cases = []
    for row, ref in zip(attempts, review['entries']):
        crop = log.with_suffix('') / f'{row["index"]:04d}' / 'exp.png'
        if digest(crop) != ref['crop_sha256']:
            raise ValueError('Reviewed source crop changed')
        raw = (row.get('neural') or {}).get('text')
        v1, v2 = propose_full_exp(raw), interpret_exp(raw)
        reviewed = interpret_exp(raw, source_complete=ref['source_complete'])
        strict, full, percentage = v2['strict_full'], single(v2['full_exp']), single(v2['percentage'])
        arithmetic = {}
        for name, reading in [('strict', strict), ('grammar_full', full)]:
            arithmetic[name] = {mode: assess(reported_level, int(reading['exp']), reading['percentage'], requirements, mode)
                               if reading else dict(status='unavailable_pair') for mode in MODES}
        cases.append(dict(index=row['index'], attempted_at=row['attempted_at'], received_at=row.get('received_at'),
            original_candidate=row.get('candidate'), visual_level=row.get('visual_level'), neural_level=row.get('neural_level'),
            original_level_evidence=row.get('level_evidence'), reference=ref, legacy=v1, interpretations=v2,
            source_review_interpretations=reviewed, arithmetic=arithmetic,
            strict_comparison=agreement(strict, ref), full_proposal_comparison=agreement(full, ref),
            percentage_proposal_comparison=percentage_agreement(percentage, ref)))
    previous = private('private/live-grammar-review-01/evaluation-01/report.json')
    inputs[previous] = digest(previous)
    controls = []
    for old in json.loads(previous.read_text())['negative_controls']:
        v2 = interpret_exp(old['diagnostic']['raw'])
        controls.append(dict(id=old['id'], source_intent=old['reference'], interpretations=v2,
            full_comparison=agreement(v2['strict_full'] or single(v2['full_exp']), old['reference']),
            percentage_comparison=percentage_agreement(v2['strict_full'] or v2['strict_percentage_only'] or single(v2['percentage']), old['reference']),
            source_review_refuses_full_field=old['source_review_refuses_full_field']))
    times = []
    started_cpu = time.process_time()
    for _ in range(100):
        start = time.perf_counter()
        for case in cases:
            interpret_exp(case['interpretations']['raw'])
        times.append((time.perf_counter()-start)*1000)
    cpu_ms = (time.process_time()-started_cpu)*1000 / (100*len(cases))
    tracemalloc.start()
    retained = [interpret_exp(c['interpretations']['raw']) for c in cases]
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    summary = dict(attempts=len(cases), strict_full_pairs=sum(c['original_candidate'] is not None for c in cases),
        original_percentage_only=sum(c['interpretations']['strict_percentage_only'] is not None for c in cases),
        legacy_full=dict(Counter(c['legacy']['classification'] for c in cases)),
        v2_full=dict(Counter(c['interpretations']['full_exp']['classification'] for c in cases)),
        v2_percentage=dict(Counter(c['interpretations']['percentage']['classification'] for c in cases)),
        full_proposal_comparisons=dict(Counter(c['full_proposal_comparison'] for c in cases)),
        percentage_proposal_comparisons=dict(Counter(c['percentage_proposal_comparison'] for c in cases)),
        strict_arithmetic={mode: dict(Counter(c['arithmetic']['strict'][mode]['status'] for c in cases if c['original_candidate'])) for mode in MODES},
        grammar_arithmetic={mode: dict(Counter(c['arithmetic']['grammar_full'][mode]['status'] for c in cases if single(c['interpretations']['full_exp']))) for mode in MODES})
    report = dict(trusted=False, provenance=review['provenance'], configuration=config, summary=summary, cases=cases,
        negative_controls=controls, reported_level_assumption=reported_level, requirements_version=table['version'],
        requirements_sha256=table_sha, table_provenance=table,
        timings=dict(median_batch_ms=statistics.median(times), p95_batch_ms=sorted(times)[94],
                     cpu_ms_per_field=cpu_ms, retained_python_bytes=current, peak_python_bytes=peak,
                     scope='Warm v2 text interpretation only, no OCR/capture/HTTP/imports'),
        input_hashes={str(p): sha for p, sha in inputs.items()})
    if any(digest(p) != sha for p, sha in inputs.items()):
        raise ValueError('Frozen input changed')
    output.mkdir(parents=True)
    dump_new(output/'report.json', report)
    changed = [c for c in cases if c['legacy']['classification'] != 'raw_strict' and
               c['legacy']['classification'] != c['interpretations']['full_exp']['classification'] or
               c['interpretations']['full_exp']['reason'] == 'percentage_decimal_repair_does_not_establish_exp_completeness']
    page = Image.new('RGB', (1280, 70+220*len(changed)), '#19273a')
    draw = ImageDraw.Draw(page)
    draw.text((15, 15), 'SAVED NATIVE PIXELS | Existing provisional review, not blinded truth. Grammar does not verify digits.', fill='white', font_size=18)
    for i, case in enumerate(changed):
        y = 70+i*220
        crop = log.with_suffix('')/f'{case["index"]:04d}'/'exp.png'
        with Image.open(crop) as opened:
            image = opened.convert('RGB')
        page.paste(image, (20, y+25))
        page.paste(image.resize((image.width*6, image.height*6), Image.Resampling.NEAREST), (20, y+50))
        v2 = case['interpretations']
        draw.text((20, y), f'Attempt {case["index"]} | raw: {v2["raw"]}', fill='#ffdc9c', font_size=16)
        draw.text((20, y+150), f'Full EXP: {single(v2["full_exp"])} | Percentage: {single(v2["percentage"])}', fill='white', font_size=15)
        draw.text((20, y+177), case['reference']['notes'][:150], fill='#c6d7e9', font_size=13)
    page.save(output/'changed-cases.png')
    return report


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--log', type=Path, required=True)
    cli.add_argument('--reviews', type=Path, required=True)
    cli.add_argument('--output', type=Path, required=True)
    cli.add_argument('--reported-level', type=int, required=True, help='Independent reported-level assumption, not selected by arithmetic')
    args = cli.parse_args()
    result = evaluate(args.log, args.reviews, args.output, args.reported_level)
    print(json.dumps(dict(summary=result['summary'], timings=result['timings']), indent=2))


if __name__ == '__main__':
    main()
