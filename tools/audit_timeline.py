"""Audit saved OCR outputs, without running recognition or changing tracking state.

Outputs contain private benchmark labels: keep --output under private/.
Interval checks are conditional opportunities, not a replay of production trust.
"""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from evaluate_exp_digits import score
from exp_tracker.models import Reading
from exp_tracker.validation import Observation, validate_transition


METRICS = ('complete_exp', 'complete_tesseract', 'complete_pixel')
FILES = {
    'fixed': {
        'strict': 'exp-digits/recording-valleys-final.json',
        'grammar': 'grammar-suffix/recording.json',
        'grayscale': 'numeric-classifier/recording.json',
    },
    'automatic': {
        'strict': 'exp-digits/recording-adaptive.json',
        'grammar': 'grammar-suffix/recording-adaptive.json',
        'grayscale': 'numeric-classifier/recording-adaptive.json',
    },
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_records(path, examples, levels, manifest_hash, levels_hash):
    data = json.loads(path.read_text(encoding='utf-8'))
    # Saved source revisions may differ; frozen labels and level inputs must not.
    hashes = data['hashes'].values()
    if manifest_hash not in hashes or levels_hash not in hashes:
        raise ValueError(f'{path}: frozen input hash mismatch')
    records = data['records']
    if len(records) != len(examples) or {r['id'] for r in records} != set(examples):
        raise ValueError(f'{path}: duplicate or missing benchmark IDs')
    for r in records:
        expected = {k: examples[r['id']][k] for k in ('level', 'current_exp', 'percentage')}
        if r['seconds'] != examples[r['id']]['seconds'] or r['expected'] != expected:
            raise ValueError(f'{path}: timestamp/label mismatch: {r["id"]}')
        if r['metrics'] != score(r['result'], expected, levels[r['id']]):
            raise ValueError(f'{path}: cached score mismatch: {r["id"]}')
    return sorted(records, key=lambda r: r['seconds'])


def correct(records, metric):
    return [r for r in records if r['metrics'][metric] == 'correct']


def gaps(records):
    return sorted([
        dict(start=a['seconds'], end=b['seconds'], seconds=b['seconds'] - a['seconds'],
             levels=[a['expected']['level'], b['expected']['level']])
        for a, b in zip(records, records[1:])
    ], key=lambda g: (-g['seconds'], g['start']))


def episodes(records, max_separation=5):
    """Proximity groups, not independent trials; a run may span multiple seconds."""
    groups = []
    for r in sorted(records, key=lambda r: r['seconds']):
        if (not groups or r['seconds'] - groups[-1][-1]['seconds'] > max_separation
                or r['expected']['level'] != groups[-1][-1]['expected']['level']):
            groups.append([])
        groups[-1].append(r)
    return [[r['seconds'] for r in group] for group in groups]


def summary(records, metric):
    successes = correct(records, metric)
    return dict(counts={k: sum(r['metrics'][metric] == k for r in records)
                        for k in ('correct', 'incorrect', 'unavailable')},
                correct_seconds=[r['seconds'] for r in successes],
                incorrect_seconds=[r['seconds'] for r in records if r['metrics'][metric] == 'incorrect'],
                unavailable_seconds=[r['seconds'] for r in records if r['metrics'][metric] == 'unavailable'],
                gaps=gaps(successes),
                first=successes[0]['seconds'] if successes else None,
                last=successes[-1]['seconds'] if successes else None,
                by_level={str(level): dict(
                    correct=sum(r['expected']['level'] == level for r in successes),
                    total=sum(r['expected']['level'] == level for r in records),
                    gaps=gaps([r for r in successes if r['expected']['level'] == level]))
                    for level in range(1, 11)})


def compare(before, after, metric):
    old, new = correct(before, metric), correct(after, metric)
    old_ids, new_ids = {r['id'] for r in old}, {r['id'] for r in new}
    recovered = [r for r in new if r['id'] not in old_ids]
    contexts = []
    for r in recovered:
        prior = [a['seconds'] for a in old if a['seconds'] < r['seconds']]
        later = [a['seconds'] for a in old if a['seconds'] > r['seconds']]
        contexts.append(dict(seconds=r['seconds'], expected=r['expected'],
                             previous=prior[-1] if prior else None,
                             next=later[0] if later else None,
                             nearest_seconds=min((abs(a['seconds'] - r['seconds']) for a in old), default=None)))
    return dict(recovered=contexts, lost=[r['seconds'] for r in old if r['id'] not in new_ids],
                episodes_5s=episodes(recovered))


def conditional_intervals(records, metric):
    """Check the existing numeric guard, assuming identity/session and soft failures.

    This is deliberately not ingestion. Each level needs a separately confirmed
    baseline, and offline/hard-pause history is not available in these screenshots.
    A correct pair alone supplies no recognized level, so it is never checked.
    """
    if metric == 'complete_exp':
        raise ValueError('pairs do not provide recognized level evidence')
    successes = correct(records, metric)
    output = []
    epoch = datetime(2000, 1, 1, tzinfo=timezone.utc)
    for a, b in zip(successes, successes[1:]):
        between = [r for r in records if a['seconds'] < r['seconds'] < b['seconds']]
        def observation(r):
            return Observation('conditionally-same-character', epoch + timedelta(seconds=r['seconds']),
                               Reading(**r['expected']))
        transition = validate_transition(observation(a), observation(b))
        # Do not skip known contrary evidence merely because the endpoints agree.
        contrary = any(r['expected']['level'] not in (None, a['expected']['level'])
                       or r['metrics'][metric] == 'incorrect' for r in between)
        labeled = [r for r in [a, *between, b] if r['expected']['level'] is not None]
        contrary |= any(x['expected']['level'] == y['expected']['level']
                        and (y['expected']['current_exp'] < x['expected']['current_exp']
                             or y['expected']['percentage'] < x['expected']['percentage'])
                        for x, y in zip(labeled, labeled[1:]))
        output.append(dict(start=a['seconds'], end=b['seconds'],
                           seconds=b['seconds'] - a['seconds'],
                           level=a['expected']['level'], missing_samples=len(between),
                           status='hard_break' if contrary else transition.status,
                           reason='intervening_contrary_evidence' if contrary else transition.reason,
                           gained_exp=transition.gained_exp if not contrary else None))
    return output


def transitions(records, metric, examples):
    output = []
    successes = correct(records, metric)
    for level in range(1, 10):
        old = [e['seconds'] for e in examples.values() if e['level'] == level]
        new = [e['seconds'] for e in examples.values() if e['level'] == level + 1]
        before = [r['seconds'] for r in successes if r['expected']['level'] == level]
        after = [r['seconds'] for r in successes if r['expected']['level'] == level + 1]
        output.append(dict(levels=[level, level + 1], label_bracket=[max(old), min(new)],
                           last_old_correct=max(before) if before else None,
                           first_new_correct=min(after) if after else None))
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('private'))
    parser.add_argument('--output', type=Path, default=Path('private/timeline-audit/report.json'))
    args = parser.parse_args(argv)
    manifest_path = args.root / 'levelup-evaluation/manifest.json'
    examples = {e['id']: e for e in json.loads(manifest_path.read_text(encoding='utf-8'))['examples']}
    ordered = sorted(examples.values(), key=lambda e: e['seconds'])
    report = dict(inputs={str(manifest_path): sha256(manifest_path)},
                  sampling=dict(count=len(ordered), first=ordered[0]['seconds'], last=ordered[-1]['seconds'],
                                step_counts=dict(Counter(b['seconds'] - a['seconds'] for a, b in zip(ordered, ordered[1:])))),
                  scopes={})
    for scope, files in FILES.items():
        levels_path = args.root / ('exp-digits/levels-fixed.json' if scope == 'fixed' else 'exp-digits/levels-adaptive.json')
        levels = json.loads(levels_path.read_text(encoding='utf-8'))['readings']
        report['inputs'][str(levels_path)] = sha256(levels_path)
        modes = {}
        for mode, filename in files.items():
            path = args.root / filename
            report['inputs'][str(path)] = sha256(path)
            modes[mode] = load_records(path, examples, levels, sha256(manifest_path), sha256(levels_path))
        report['scopes'][scope] = dict(
            modes={mode: {metric: dict(**summary(records, metric),
                                      transitions=transitions(records, metric, examples),
                                      conditional_intervals=conditional_intervals(records, metric)
                                      if metric != 'complete_exp' else None)
                          for metric in METRICS} for mode, records in modes.items()},
            comparisons={f'{a}_to_{b}': {metric: compare(modes[a], modes[b], metric) for metric in METRICS}
                         for a, b in [('strict', 'grammar'), ('grammar', 'grayscale')]})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'Audited {len(examples)} samples across six saved evaluations: {args.output}')


if __name__ == '__main__':
    main()
