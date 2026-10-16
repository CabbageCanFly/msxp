"""Describe paired saved RapidOCR outputs, without voting, repairing or trusting them."""

import argparse
from collections import Counter
import json
from pathlib import Path

from benchmark_rapidocr import interpret


def complete_pair(text):
    parsed = interpret(text)
    return parsed['pair'] if parsed['bracketed_syntax'] else None


def index_rows(records):
    indexed = {r['id']: r for r in records}
    if len(indexed) != len(records):
        raise ValueError('Duplicate frame IDs; select one fixed recognition variant')
    return indexed


def describe(rows, interval):
    """Adjacent means the specified sampling interval, never the next available value."""
    pairs = [complete_pair(r['text']) for r in rows]
    edges = []
    episodes = []
    run = None
    for i, (row, pair) in enumerate(zip(rows, pairs)):
        adjacent = i > 0 and abs(row['seconds'] - rows[i-1]['seconds'] - interval) < 1e-6
        if adjacent:
            a, b = rows[i-1]['level'], row['level']
            relation = 'unknown' if a is None or b is None else 'same' if a == b else 'changed'
            edges.append(dict(before=rows[i-1]['id'], after=row['id'],
                kind='unavailable' if pairs[i-1] is None or pair is None else
                     'agreement' if pair == pairs[i-1] else 'different', level_relation=relation))
        if pair is None:
            run = None
        elif run is not None and adjacent and pair == run['pair'] and row['level'] == run['level']:
            run.update(end=row['seconds'], last_id=row['id'], frames=run['frames']+1)
        else:
            run = dict(start=row['seconds'], end=row['seconds'], first_id=row['id'],
                       last_id=row['id'], pair=pair, level=row['level'], frames=1)
            episodes.append(run)
    neighbor_available = []
    for i, pair in enumerate(pairs):
        if pair is None and any(
            0 <= j < len(rows) and pairs[j] is not None and
            abs(abs(rows[j]['seconds']-rows[i]['seconds'])-interval) < 1e-6
            for j in (i-1, i+1)):
            neighbor_available.append(rows[i]['id'])
    return dict(frames=len(rows), complete=sum(p is not None for p in pairs),
        unavailable=sum(p is None for p in pairs),
        malformed=sum(bool(r['text']) and p is None for r,p in zip(rows,pairs)),
        missing_regions=sum(r['missing_crop'] for r in rows),
        no_text_with_region=sum(not r['missing_crop'] and not r['text'] for r in rows),
        edge_counts=dict(Counter(e['kind'] for e in edges)), edges=edges,
        episodes=episodes, repeat_episodes=[e for e in episodes if e['frames'] >= 2],
        unavailable_with_complete_neighbor=neighbor_available)


def analyze(manifest, localization, zero, padded):
    expected = index_rows(manifest['examples'])
    located = index_rows(localization['records'])
    variants = {0:index_rows(zero['records']), 2:index_rows(padded['records'])}
    if any(set(rows) != set(expected) for rows in [located, *variants.values()]):
        raise ValueError('All inputs must contain exactly the same frame IDs')
    windows = {}
    for item in expected.values():
        windows.setdefault(item['window'], []).append(item)
    output = {}
    for window, items in windows.items():
        items.sort(key=lambda e:e['seconds'])
        if len({e['seconds'] for e in items}) != len(items):
            raise ValueError('Duplicate timestamps in a window')
        summaries = {}
        for padding, records in variants.items():
            rows = []
            for item in items:
                row, location = records[item['id']], located[item['id']]
                if row['seconds'] != item['seconds'] or location['seconds'] != item['seconds']:
                    raise ValueError('Timestamps disagree')
                if row['mode'] != 'line_recognize' or row['scale'] != 2 or row['padding_pixels'] != padding:
                    raise ValueError('Expected fixed 2x line recognition at padding 0 and 2')
                rows.append({**row, 'level':location['level']})
            summaries[str(padding)] = describe(rows, 1)
        comparisons = []
        for item in items:
            frame_id = item['id']
            a, b = (complete_pair(v[frame_id]['text']) for v in variants.values())
            kind = ('agreement' if a == b else 'contradiction') if a is not None and b is not None else (
                'padded_only' if b is not None else 'zero_only' if a is not None else 'both_unavailable')
            comparisons.append(dict(id=frame_id, seconds=item['seconds'], kind=kind,
                                    zero_pair=a, padded_pair=b))
        output[window] = dict(padding=summaries, crop_comparisons=comparisons,
            crop_comparison_counts=dict(Counter(r['kind'] for r in comparisons)))
    return dict(trusted=False, note='Agreement is correlated diagnostic evidence, never independent verification',
                windows=output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest', 'localization', 'zero', 'padded', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    inputs = [args.manifest, args.localization, args.zero, args.padded]
    if args.output.exists() or args.output.resolve() in [p.resolve() for p in inputs]:
        parser.error('Output must be a new file; saved evidence is never overwritten')
    result = analyze(*(json.loads(p.read_text(encoding='utf-8')) for p in inputs))
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
