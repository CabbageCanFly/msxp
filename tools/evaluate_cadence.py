"""Offline availability audit; no trust, cached ROI recovery or gain calculation."""

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import time

from analyze_temporal_ocr import complete_pair, describe, index_rows


def coverage(rows, available, interval=15):
    """Sample runs and bounded endpoint gaps, never continuous coverage estimates."""
    if len(rows) != len(available) or interval <= 0:
        raise ValueError('Mismatched availability or invalid interval')
    if any(b['seconds'] - a['seconds'] != interval for a,b in zip(rows, rows[1:])):
        raise ValueError('Expected the frozen regular schedule')
    runs = []
    for row, good in zip(rows, available):
        if not runs or good != runs[-1]['available']:
            runs.append(dict(available=good, start=row['seconds'], end=row['seconds'], samples=1))
        else:
            runs[-1].update(end=row['seconds'], samples=runs[-1]['samples']+1)
    for run in runs:
        run['sample_span_seconds'] = run['end']-run['start']
        run['boundary_censored'] = run['start']==rows[0]['seconds'] or run['end']==rows[-1]['seconds']
    successes = [r['seconds'] for r,good in zip(rows, available) if good]
    gaps = [b-a for a,b in zip(successes,successes[1:])]
    return dict(runs=runs, success_endpoint_gaps_seconds=gaps,
                longest_success_endpoint_gap_seconds=max(gaps,default=None),
                gaps_over_120_seconds=sum(g>120 for g in gaps),
                note='Unavailable run spans omit unknown edges; boundary runs are censored. Timing alone does not authorize bridging.')


def localize(manifest, output):
    from PIL import Image
    from adaptive_hud import locate, level_reading
    from evaluate_cross_stream import target_category
    from exp_tracker.metrics import ResourceMonitor
    data=json.loads(manifest.read_text(encoding='utf-8'))
    records=[]
    os.environ['OMP_THREAD_LIMIT']='1'
    monitor=ResourceMonitor(sample_interval=.025,scope='Fresh full-frame localization and unchanged level reader, including Tesseract children')
    try:
        for item in data['examples']:
            with Image.open(manifest.parent/item['frame']) as file:
                image=file.convert('RGB')
            started=time.perf_counter(); candidates=locate(image); elapsed=time.perf_counter()-started
            level=None; attempts=[]; level_seconds=0
            if len(candidates)==1:
                directory=manifest.parent/'automatic-crops'/item['id'].split('/')[1]
                directory.mkdir(parents=True,exist_ok=True)
                for name,region in candidates[0]['regions'].items():
                    if region is not None:
                        image.crop(region.pixels(*image.size)).save(directory/f'{name}.png')
                started=time.perf_counter()
                region=candidates[0]['regions']['level']
                level,attempts=level_reading(image.crop(region.pixels(*image.size))) if region is not None else (None,[])
                level_seconds=time.perf_counter()-started
            records.append(dict(id=item['id'],seconds=item['seconds'],expected=item,
                candidates=[{**c,'regions':{k:asdict(v) if v is not None else None for k,v in c['regions'].items()}} for c in candidates],
                location=target_category(candidates,item['hud_box'],item.get('secondary_box'),image.size),
                level=level,level_attempts=attempts,location_seconds=elapsed,level_seconds=level_seconds))
            print(f"{len(records)}/{len(data['examples'])} {item['window']} {item['seconds']}s candidates={len(candidates)} level={level}",flush=True)
    finally:
        monitor.close()
    output.write_text(json.dumps(dict(records=records,resources=monitor.snapshot(),
        manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest()),indent=2)+'\n',encoding='utf-8')


def analyze(manifest, localization, neural):
    expected=index_rows(manifest['examples'])
    located=index_rows(localization['records']); recognized=index_rows(neural['records'])
    if set(expected)!=set(located) or set(expected)!=set(recognized):
        raise ValueError('Evidence IDs do not match')
    windows={}
    for item in expected.values():
        loc,ocr=located[item['id']],recognized[item['id']]
        if loc['seconds']!=item['seconds'] or ocr['seconds']!=item['seconds']:
            raise ValueError('Evidence timestamps do not match')
        if (ocr['mode'],ocr['scale'],ocr['padding_pixels'])!=('line_recognize',2,2):
            raise ValueError('Expected unchanged line recognition at 2x with 2px padding')
        pair=complete_pair(ocr['text'])
        # Review boxes score target selection only; they never supply a missing crop.
        main=loc['location']=='main'
        reviewed=item.get('pre_review',False)
        truth=[item['current_exp'],item['percentage']]
        pair_comparison=('unreviewed' if not reviewed or None in truth else
                         'unavailable' if pair is None else 'match' if pair==truth else 'mismatch')
        level_comparison=('unreviewed' if not reviewed or item['level'] is None else
                          'unavailable' if loc['level'] is None else 'match' if loc['level']==item['level'] else 'mismatch')
        triple_comparison=('unreviewed' if 'unreviewed' in (pair_comparison,level_comparison) else
                           'unavailable' if pair is None or loc['level'] is None else
                           'match' if pair_comparison==level_comparison=='match' else 'mismatch')
        row=dict(id=item['id'],seconds=item['seconds'],text=ocr['text'],pair=pair,level=loc['level'],
                 location=loc['location'],missing_crop=ocr['missing_crop'],
                 main_pair=main and pair is not None,main_triple=main and pair is not None and loc['level'] is not None,
                 pair_comparison=pair_comparison,level_comparison=level_comparison,triple_comparison=triple_comparison,
                 frame_hash=item['image_sha256'])
        windows.setdefault(item['window'],[]).append(row)
    summaries={}
    for name,rows in windows.items():
        rows.sort(key=lambda r:r['seconds'])
        checks=[]
        for a,b in zip(rows,rows[1:]):
            if a['level'] is not None and b['level'] is not None and a['level']!=b['level']:
                checks.append(dict(before=a['seconds'],after=b['seconds'],kind='level_changed_not_verified_transition'))
            if a['pair'] is not None and b['pair'] is not None and a['level']==b['level'] and a['level'] is not None:
                if b['pair'][0]<a['pair'][0] or b['pair'][1]<a['pair'][1]:
                    checks.append(dict(before=a['seconds'],after=b['seconds'],kind='same_level_decrease_unresolved'))
                elif b['pair'][0]==a['pair'][0] and b['pair'][1]!=a['pair'][1]:
                    checks.append(dict(before=a['seconds'],after=b['seconds'],kind='unchanged_exp_changed_percentage'))
        summaries[name]=dict(frames=len(rows),location_counts=dict(Counter(r['location'] for r in rows)),
            level_available=sum(r['level'] is not None for r in rows),
            raw_triples=sum(r['pair'] is not None and r['level'] is not None for r in rows),
            temporal=describe(rows,15),pair_coverage=coverage(rows,[r['main_pair'] for r in rows]),
            triple_coverage=coverage(rows,[r['main_triple'] for r in rows]),
            provisional_comparisons={key:dict(Counter(r[key+'_comparison'] for r in rows)) for key in ('pair','level','triple')},
            repeated_full_frame_hashes=len(rows)-len({r['frame_hash'] for r in rows}),
            diagnostic_flags=checks,rows=rows)
    return dict(trusted=False,human_verified_accuracy_available=False,windows=summaries)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('localize','analyze'))
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--localization',type=Path)
    parser.add_argument('--neural',type=Path)
    args=parser.parse_args()
    if args.output.exists():
        parser.error('Output must be new; never overwrite saved evidence')
    if args.action=='localize':
        localize(args.manifest,args.output)
    else:
        if not args.localization or not args.neural:
            parser.error('Analysis requires --localization and --neural')
        result=analyze(*(json.loads(p.read_text(encoding='utf-8')) for p in (args.manifest,args.localization,args.neural)))
        args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
