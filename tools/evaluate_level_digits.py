"""Level-only benchmark. Labels are scored after recognition, never passed to it.

Default inputs are frozen saved level crops. --adaptive-results reuses prior
automatically located ROIs, including unavailable detections, without rerunning
HUD localization. Outputs/annotations must remain private and ignored.
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

from evaluate_ocr import load_crops
from level_digits import load_profile, read_level


def classify(level, expected):
    if level is None:
        return 'unavailable'
    return 'correct' if expected['complete'] and level==expected['level'] else 'incorrect'


def main(argv=None):
    from exp_tracker.metrics import ResourceMonitor
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--profile',type=Path)
    parser.add_argument('--engine',choices=('tesseract','single','consensus'),required=True)
    parser.add_argument('--adaptive-results',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.engine!='tesseract' and not args.profile:
        parser.error('native recognizers require --profile')
    os.environ.setdefault('OMP_THREAD_LIMIT','1')
    data=json.loads(args.manifest.read_text(encoding='utf-8'))
    files=[args.manifest,Path(__file__).with_name('level_digits.py')]
    profile=load_profile(args.profile) if args.profile else None
    if args.profile:files.append(args.profile)
    if args.engine=='tesseract':
        from adaptive_hud import level_reading
        from exp_tracker.recognition import configure_tesseract
        configure_tesseract()
        files.append(Path(__file__).with_name('adaptive_hud.py'))
    prepared=[]
    if args.adaptive_results:
        from evaluate_adaptive_hud import frame_at
        from exp_tracker.models import Region
        files.append(args.adaptive_results)
        cached=json.loads(args.adaptive_results.read_text())
        rows={r['expected']['id']:r for r in cached['records']}
        for item in data['examples']:
            row=rows[item['id']]
            assert all(row['expected'][k]==item[k] for k in ('seconds','level','complete'))
            crop=None
            if row['candidates']==1 and 'level' in row['result']['regions']:
                frame=frame_at(args.manifest.parent/data['video'],item['seconds'])
                crop=frame.crop(Region(**row['result']['regions']['level']).pixels(*frame.size))
                del frame
            prepared.append((item,crop))
    else:
        for item in data['examples']:
            image,regions,_=load_crops(args.manifest,item,data)
            prepared.append((item,image.crop(regions['level'].pixels(*image.size))))
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    monitor=ResourceMonitor(sample_interval=.01,scope='level recognition only; excludes localization and frame extraction')
    records=[]
    try:
        for expected,crop in prepared:
            started=time.perf_counter()
            if crop is None:
                result=dict(level=None,reason='previous_locator_unavailable')
            elif args.engine=='tesseract':
                level,attempts=level_reading(crop)
                result=dict(level=level,attempts=attempts)
            else:
                result=read_level(crop,profile,mode=args.engine)
            elapsed=time.perf_counter()-started
            records.append(dict(id=expected['id'],seconds=expected['seconds'],expected_level=expected['level'],
                                complete=expected['complete'],category=classify(result['level'],expected),
                                elapsed_seconds=elapsed,result=result))
            if len(records)%25==0:print(len(records),dict(Counter(r['category'] for r in records)),flush=True)
    finally:
        monitor.close()
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    timings=sorted(r['elapsed_seconds'] for r in records)
    levels={str(level):dict(Counter(r['category'] for r in records if r['expected_level']==level))
            for level in sorted({r['expected_level'] for r in records if r['expected_level'] is not None})}
    summary=dict(counts=dict(Counter(r['category'] for r in records)),by_level=levels,
                 mean_seconds=statistics.mean(timings),p95_seconds=timings[math.ceil(.95*len(timings))-1],
                 resources=monitor.snapshot())
    payload=dict(engine=args.engine,inputs='prior adaptive ROIs' if args.adaptive_results else 'same saved crops',
                 input_hashes=hashes,summary=summary,records=records)
    args.output.write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))
    return 1 if summary['counts'].get('incorrect') else 0


if __name__=='__main__':raise SystemExit(main())
