"""Offline recording benchmark for adaptive_hud; output contains PRIVATE annotations.

Manifest: video path relative to JSON, field_boxes in native pixels, and examples
containing seconds, complete, level, current_exp, percentage. No labels reach OCR.
Requires optional capture dependencies for the process-tree resource monitor.
"""

import argparse
from collections import Counter
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import statistics
import subprocess

from PIL import Image, ImageChops

from adaptive_hud import inspect, load_bank
from exp_tracker.models import Region
from exp_tracker.parsing import parse_exp, parse_level


def frame_at(video, seconds):
    output=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-ss',str(seconds),
                           '-i',str(video),'-frames:v','1','-f','image2pipe','-c:v','png','pipe:1'],
                          check=True,capture_output=True,timeout=30)
    with Image.open(BytesIO(output.stdout)) as image:
        return image.convert('RGB')


def field_truth(image, boxes):
    """Visible-ink bounds within independently supplied numeric-only field boxes."""
    result={}
    for field,box in boxes.items():
        crop=image.crop(tuple(box)).convert('RGB')
        r,g,b=crop.split()
        neutral=ImageChops.darker(ImageChops.darker(r,g),b).point(lambda p:255 if p>175 else 0)
        if field=='exp':
            # Same green-excess definition as the existing glyph mask.
            green=Image.new('L',crop.size)
            rgb=crop.tobytes()
            green.putdata([255 if 2*rgb[i+1]-rgb[i]-rgb[i+2]>=22 else 0
                           for i in range(0,len(rgb),3)])
            neutral=ImageChops.lighter(neutral,green)
        bounds=neutral.getbbox()
        if bounds is None:
            raise ValueError(f'empty manually labeled {field} field')
        result[field]=(box[0]+bounds[0],box[1]+bounds[1],box[0]+bounds[2],box[1]+bounds[3])
    return result


def score(output, expected, truth, size):
    result=output['result']
    reading=result['reading']
    wanted={key:expected[key] for key in ('level','current_exp','percentage')} if expected['complete'] else None
    accepted=result['status']=='accepted'
    correct=reading==wanted and wanted is not None
    regions={key:Region(**value).pixels(*size) for key,value in result['regions'].items() if value is not None}
    contained={}
    location=False
    if truth and len(regions)==2:
        for field,(x0,y0,x1,y1) in truth.items():
            a,b,c,d=regions[field]
            contained[field]=a<=x0 and b<=y0 and c>=x1 and d>=y1
        location=all(regions[f][0]<=(box[0]+box[2])/2<=regions[f][2]
                     and regions[f][1]<=(box[1]+box[3])/2<=regions[f][3] for f,box in truth.items())
    levels=[parse_level(a['text']) for a in result['raw'].get('level',[]) if a['confidence']>=.4]
    levels=[v for v in levels if v is not None]
    level=levels[0] if len(levels)>=2 and len(set(levels))==1 else None
    exps={value for a in result['raw'].get('exp',[]) if (value:=parse_exp(a.get('text') or '')) is not None}
    exp=next(iter(exps)) if len(exps)==1 else None
    return dict(category='accepted_correct' if accepted and correct else 'accepted_incorrect' if accepted
                else 'incomplete' if reading is None else 'rejected_complete',
                location_correct=location,fields_contained=contained,
                correct_missing_rejection=not expected['complete'] and not accepted and not output['candidates'],
                level_correct=bool(wanted and level==wanted['level']),
                exp_correct=bool(wanted and exp and exp[0]==wanted['current_exp']),
                percentage_correct=bool(wanted and exp and exp[1]==wanted['percentage']))


def main(argv=None):
    from exp_tracker.metrics import ResourceMonitor
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--bank',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True,help='Save under ignored private/ or artifacts/')
    args=parser.parse_args(argv)
    os.environ.setdefault('OMP_THREAD_LIMIT','1')
    data=json.loads(args.manifest.read_text(encoding='utf-8'))
    video=args.manifest.parent/data['video']
    bank=load_bank(args.bank)
    inputs=[Path(__file__).with_name('adaptive_hud.py'),args.manifest,args.bank]
    inputs.extend(args.bank.parent/row['path'] for row in json.loads(args.bank.read_text())['profiles'])
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    records=[]
    for item in data['examples']:
        image=frame_at(video,item['seconds'])
        truth=field_truth(image,data['field_boxes']) if item['complete'] else None
        monitor=ResourceMonitor(sample_interval=.01,scope='adaptive localization + field OCR; excludes FFmpeg decoding')
        try:
            output=inspect(image,bank)
        finally:
            monitor.close()
        records.append(dict(expected=item,**output,**score(output,item,truth,image.size),resources=monitor.snapshot()))
        if len(records)%10==0:
            print(len(records),dict(Counter(r['category'] for r in records)),flush=True)
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    totals=Counter(r['category'] for r in records)
    summary=dict(categories=dict(totals),readable=sum(r['expected']['complete'] for r in records),
                 **{key:sum(r[key] for r in records) for key in
                    ('location_correct','level_correct','exp_correct','percentage_correct','correct_missing_rejection')},
                 both_fields_contained=sum(len(r['fields_contained'])==2 and all(r['fields_contained'].values()) for r in records),
                 location_mean_seconds=statistics.mean(r['location_seconds'] for r in records),
                 field_mean_seconds=statistics.mean(r['field_seconds'] for r in records),
                 peak_tree_rss_mib=max(r['resources']['peak_tree_rss_mib_sampled'] for r in records),
                 sampled_cpu_seconds=sum(r['resources']['cpu_seconds_sampled'] for r in records))
    payload=dict(input_hashes=hashes,summary=summary,records=records)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))
    return 1 if totals['accepted_incorrect'] else 0


if __name__=='__main__':raise SystemExit(main())
