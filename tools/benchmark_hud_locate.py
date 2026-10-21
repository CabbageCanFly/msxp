"""Compare baseline and batched HUD localization OCR on identical frames; output is PRIVATE.

Frames are image paths or VIDEO@SECONDS (decoded in memory by FFmpeg, nothing saved).
Both variants must return identical tokens at both scales; any difference exits 1.
Child (Tesseract) CPU comes from os.times() and is unavailable on Windows.
Run N copies at once to measure contention, as N capture workers would.
"""

import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import time

from PIL import Image

from adaptive_hud import layouts, merge_layouts, scan


def load(spec):
    video,at,seconds=spec.rpartition('@')
    if at and not Path(spec).is_file():
        from evaluate_adaptive_hud import frame_at
        return frame_at(Path(video),float(seconds))
    with Image.open(spec) as image:
        return image.convert('RGB')


def measure(image, batched):
    before,started=os.times(),time.perf_counter()
    pages=scan(image,batched=batched)
    wall,after=time.perf_counter()-started,os.times()
    candidates=merge_layouts([c for tokens in pages for c in layouts(tokens,image.size,deduplicate=False)],image.size)
    child=after.children_user+after.children_system-before.children_user-before.children_system
    return pages,candidates,dict(wall=wall,own_cpu=after.user+after.system-before.user-before.system,
                                 child_cpu=None if os.name=='nt' else child)


def geometry(candidates, size):
    return [{field:region.pixels(*size) if region else None for field,region in c['regions'].items()}
            for c in candidates]


def summary(values):
    values=[v for v in values if v is not None]
    return dict(mean=statistics.mean(values),median=statistics.median(values),max=max(values)) if values else None


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('frames',nargs='+')
    parser.add_argument('--output',type=Path,required=True,help='new private JSON file')
    args=parser.parse_args(argv)
    os.environ.setdefault('OMP_THREAD_LIMIT','1')
    rows=[]
    for index,spec in enumerate(args.frames):
        image=load(spec)
        # Alternate order so neither variant always runs with warm caches.
        order=(False,True) if index%2==0 else (True,False)
        runs={batched:measure(image,batched) for batched in order}
        (base_pages,base,base_time),(new_pages,_,new_time)=runs[False],runs[True]
        rows.append(dict(frame=spec,size=image.size,identical=base_pages==new_pages,candidates=len(base),
                         geometry=geometry(base,image.size),baseline=base_time,batched=new_time))
        print(f"{spec}: {len(base)} candidates, identical={rows[-1]['identical']}, "
              f"{base_time['wall']:.2f}s -> {new_time['wall']:.2f}s",flush=True)
    result=dict(frames=len(rows),mismatches=[r['frame'] for r in rows if not r['identical']],
                **{variant:{key:summary([r[variant][key] for r in rows]) for key in ('wall','own_cpu','child_cpu')}
                   for variant in ('baseline','batched')})
    with args.output.open('x',encoding='utf-8') as handle:  # Never overwrite earlier evidence.
        json.dump(dict(summary=result,rows=rows),handle,indent=1)
    print(json.dumps(result,indent=1))
    return 1 if result['mismatches'] else 0


if __name__=='__main__': sys.exit(main())
