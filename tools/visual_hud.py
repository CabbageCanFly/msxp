"""Opt-in visual proposals followed by the existing OCR; all readings use this frame's pixels."""
import json
import math
from pathlib import Path
import re
import subprocess
import time

from PIL import Image

from adaptive_hud import locate
from analyze_temporal_ocr import complete_pair
from benchmark_rapidocr import context_box
from exp_tracker.shadow_types import parse_percentage_only

WORKER=Path(__file__).with_name('visual_hud_proposals.py')
MAX_BYTES=32*1024*1024


def check(python):
    try:
        result=subprocess.run([str(python),str(WORKER),'--check'],capture_output=True,timeout=30)
        if result.returncode or not isinstance(json.loads(result.stdout),dict):raise ValueError
    except (OSError,ValueError,subprocess.SubprocessError):
        raise ValueError('Visual HUD requires OpenCV and NumPy in the existing OCR environment') from None


class VisualLocator:
    """One frame only. A confirmed field response is reused once for the exact same crop."""
    def __init__(self,png,python,resident,reader,*,experimental=False,timeout=10):
        self.png,self.python,self.resident,self.reader=png,python,resident,reader
        self.experimental,self.timeout=experimental,timeout
        self.cached=None
        self.info=dict(path='full',reason='not_run',worker_cpu_seconds=0.,worker_wall_seconds=0.)

    def request(self,image,op,**metadata):
        if not self.resident or len(self.png)>MAX_BYTES:raise ValueError('Visual transport unavailable')
        payload=json.dumps(dict(op=op,**metadata)).encode()+b'\n'+self.png
        started=time.monotonic()
        response=self.resident([str(self.python),str(WORKER)],payload,self.timeout)
        self.info['worker_wall_seconds']+=time.monotonic()-started
        value=json.loads(response)
        if (not isinstance(value,dict) or type(value.get('version')) is not int or value['version']!=1
                or value.get('size')!=list(image.size) or type(value.get('cpu_seconds')) not in (int,float)
                or not math.isfinite(value['cpu_seconds']) or not 0<=value['cpu_seconds']<=300):
            raise ValueError('Invalid visual response')
        self.info['worker_cpu_seconds']+=value['cpu_seconds']
        return value

    def full(self,image,reason,*,learn=True):
        self.info.update(path='full',reason=reason);self.cached=None
        found=locate(image)
        if learn and len(found)==1:
            candidate=found[0];token=candidate.get('anchors',{}).get('exp')
            if token and re.fullmatch('EXP[.:]?',token['text'],re.I) and token.get('confidence',0)>=.4:
                box=[max(0,math.floor(token['x'])),max(0,math.floor(token['y'])),
                    min(image.width,math.ceil(token['x']+token['width'])),min(image.height,math.ceil(token['y']+token['height']))]
                try:self.request(image,'learn',box=box,step=candidate['anchor_step'])
                except (OSError,RuntimeError,ValueError,TypeError):pass
        return found

    @staticmethod
    def key(crops):return tuple(None if crop is None else (crop.mode,crop.size,crop.tobytes()) for crop in crops)

    def read(self,*crops):
        if self.cached is not None and self.key(crops)==self.cached[0]:
            _,response=self.cached;self.cached=None
            return response
        return self.reader(*crops)

    def masked(self,image):
        try:
            proposal=self.request(image,'detect')
            if type(proposal.get('full')) is not bool:raise ValueError('Invalid decision')
            if proposal['full']:
                reason=proposal.get('reason')
                if reason not in {'untrained','no_meters','unknown_label_style','too_many_regions','broad_mask','unexplained_label'}:
                    raise ValueError('Invalid fallback reason')
                self.info['reason']=reason;return None
            boxes=proposal.get('boxes')
            if not isinstance(boxes,list) or not 1<=len(boxes)<=256:raise ValueError('Invalid regions')
            masked=Image.new('RGB',image.size)
            for box in boxes:
                if (not isinstance(box,list) or len(box)!=4 or any(type(n) is not int for n in box)
                        or not 0<=box[0]<box[2]<=image.width or not 0<=box[1]<box[3]<=image.height):
                    raise ValueError('Invalid region')
                masked.paste(image.crop(tuple(box)),tuple(box))
            found=locate(masked)
            if len(found)!=1 or found[0]['regions']['level'] is None:
                self.info['reason']='ocr_incomplete';return None
            regions=found[0]['regions'];crop=image.crop(context_box(regions['exp'],image.size,2))
            crops=(crop,image.crop(regions['level'].pixels(*image.size))) if self.experimental else (crop,)
            # shortcut: confirmation is timed within localization; split it before profiling this path by stage.
            response=self.reader(*crops)
            text=response.get('text') if isinstance(response,dict) else None
            # Let the original detector retry before the existing grammar handles imperfect fields.
            if complete_pair(text) is None and parse_percentage_only(text) is None:
                self.info['reason']='exp_unreadable';return None
            self.cached=(self.key(crops),response)
            self.info.update(path='masked',reason='matched')
            return found
        except (OSError,RuntimeError,ValueError,TypeError):
            self.info['reason']='worker_unavailable';return None

    def __call__(self,image):
        found=self.masked(image)
        return found if found is not None else self.full(image,self.info['reason'],learn=self.info['reason']!='worker_unavailable')
