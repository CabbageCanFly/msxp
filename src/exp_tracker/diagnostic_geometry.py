"""One bounded experimental HUD geometry check, shared with saved-evidence review."""
import math
import re

from .models import Region


def overlapping_hud_gap(record):
    """Disputed crops on one anchor group may be skipped, never read as unique."""
    try:
        location=record['localization'];candidates=location['candidates'];size=record['frame_size']
        if (record.get('status')!='unavailable' or record.get('reasons')!=['multiple_huds']
                or record.get('current') is not False or record.get('candidate') is not None
                or record.get('neural') is not None or record.get('visual_level') is not None
                or (record.get('neural_level') or {}).get('level') is not None
                or type(location['count']) is not int or not isinstance(candidates,list)
                or not 2<=location['count']==len(candidates)<=8
                or len(size)!=2 or any(type(n) is not int or n<=0 for n in size) or size[0]*size[1]>4096*2160):
            return False
        for i,a in enumerate(candidates):
            step=a['anchor_step']
            if type(step) not in (int,float) or not math.isfinite(step) or step<=0:return False
            box=Region(**a['regions']['exp']).pixels(*size)
            for b in candidates[:i]:
                limit=.05*min(step,b['anchor_step'])
                if abs(step-b['anchor_step'])>limit:return False
                for name in ('hp','mp','exp'):
                    for axis in ('x','y'):
                        x,y=a['anchors'][name][axis],b['anchors'][name][axis]
                        if (type(x) not in (int,float) or type(y) not in (int,float)
                                or not math.isfinite(x) or not math.isfinite(y)
                                or not 0<=x<size[0 if axis=='x' else 1] or not 0<=y<size[0 if axis=='x' else 1]
                                or abs(x-y)>limit):return False
                other=Region(**b['regions']['exp']).pixels(*size)
                # Wider than deduplication only because no crop/value is selected here.
                if max(abs(x-y) for x,y in zip(box,other))>2*limit:return False
                if min(box[2],other[2])<=max(box[0],other[0]) or min(box[3],other[3])<=max(box[1],other[1]):return False
        return True
    except (KeyError,TypeError,ValueError,OverflowError,AttributeError):return False


def exp_vertical_origin(anchors,step):
    try:
        if type(step) not in (int,float) or not math.isfinite(step) or step<=0:return None
        hp,mp,exp,lv=(anchors[k] for k in ('hp','mp','exp','lv'))
        for label,t in zip(('HP','MP','EXP','LV'),(hp,mp,exp,lv)):
            if not re.fullmatch(label+r'[.:]?',t['text'],re.I):return None
            if any(type(t[k]) not in (int,float) or not math.isfinite(t[k]) for k in ('y','height')):return None
        if (exp['y']-hp['y']>.04*step and exp['y']-hp['y']<=.08*step
                and abs(mp['y']-exp['y'])<=.025*step and .03*step<=lv['y']-exp['y']<=.10*step
                and .05*step<=exp['height']<=.12*step and hp['height']>1.3*exp['height']):
            return exp['y']
    except (KeyError,TypeError):pass
    return None


def suspect_crop(record):
    """Only flags the known cut-off-bottom pattern; False is not a completeness guarantee."""
    try:
        location=record['localization'];box=record['exp_crop_box']
        if location['count']!=1 or len(location['candidates'])!=1 or len(box)!=4:return False
        if any(type(n) not in (int,float) or not math.isfinite(n) for n in box):return False
        candidate=location['candidates'][0];step=candidate['anchor_step']
        origin=exp_vertical_origin(candidate['anchors'],step)
        return origin is not None and box[3]<math.ceil(origin+.105*step)
    except (KeyError,TypeError):return False
