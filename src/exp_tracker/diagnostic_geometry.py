"""One bounded experimental HUD geometry check, shared with saved-evidence review."""
import math
import re


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
