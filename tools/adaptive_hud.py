"""Isolated, read-only HUD localization/normalization experiment (not capture integration).

No game assets or calibration ship here. Bank paths resolve relative to its JSON:
{"profiles": [{"path": "glyph-profile.json", "anchor_step": 109.0}]}.
anchor_step is the HP-to-MP distance in that profile's development imagery.
"""

import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import re
import time

from PIL import Image, ImageChops, ImageOps

from exp_tracker.glyphs import GlyphProfile, match_exp
from exp_tracker.models import Reading, Recognition, Region, reading_errors
from exp_tracker.parsing import parse_exp, parse_level
from exp_tracker.recognition import _ocr, _read_field, configure_tesseract
from exp_tracker.trust import guard_unverified_exp


def label(token):
    # Sparse OCR sometimes merges a label with its following value (e.g. MP5/5).
    text = token["text"].upper()
    for value in ("HP", "MP", "EXP", "LV"):
        if re.match(rf"^{value}(?:$|[\W\d])", text):
            return value
    return None


def layouts(tokens, size):
    """Bind all four anchors. Distances are relative to the HP/MP spacing."""
    width, height = size
    candidates = []
    for hp in (t for t in tokens if label(t) == "HP"):
        for mp in (t for t in tokens if label(t) == "MP"):
            step = mp["x"] - hp["x"]
            if step < 5 * max(hp["height"], mp["height"]):
                continue
            if abs(mp["y"] - hp["y"]) > .08 * step:
                continue
            exps = [t for t in tokens if label(t) == "EXP"
                    and .8 * step <= t["x"] - mp["x"] <= 1.2 * step
                    and abs(t["y"] - hp["y"]) <= .08 * step]
            levels = [t for t in tokens if label(t) == "LV"
                      and 1.6 * step <= hp["x"] - t["x"] <= 2.2 * step
                      and -.04 * step <= t["y"] - hp["y"] <= .15 * step]
            for exp in exps:
                for lv in levels:
                    # shortcut: one classic HUD layout family; reject other layouts until validated.
                    boxes = dict(level=(lv["x"] + .29 * step, lv["y"] - .04 * step,
                                        lv["x"] + .62 * step, lv["y"] + .17 * step),
                                 exp=(hp["x"] + 2.26 * step, hp["y"] + .015 * step,
                                      hp["x"] + 3.12 * step, hp["y"] + .105 * step))
                    if any(x0 < 0 or y0 < 0 or x1 > width or y1 > height
                           for x0,y0,x1,y1 in boxes.values()):
                        continue
                    regions = {key: Region(x0/width,y0/height,x1/width,y1/height)
                               for key,(x0,y0,x1,y1) in boxes.items()}
                    candidate = dict(regions=regions, anchor_step=step,
                                     anchors={"hp":hp,"mp":mp,"exp":exp,"lv":lv})
                    if candidate not in candidates:
                        candidates.append(candidate)
    return candidates


def locate(image):
    """Search the whole frame so a small/offset game isn't tied to stream borders."""
    if image.width * image.height > 4096 * 2160:
        return []
    configure_tesseract()
    for magnification in (2.0,3.0):
        scale = min(magnification, math.sqrt(1920 * 1080 * magnification**2 / (image.width * image.height)))
        gray = image.convert("L").resize((round(image.width*scale),round(image.height*scale)),
                                         Image.Resampling.BICUBIC)
        tokens = _ocr(gray.point(lambda p: 0 if p > 160 else 255), 11)
        for token in tokens:
            for key in ("x","y","width","height"):
                token[key] /= scale
        candidates=layouts(tokens, image.size)
        if candidates:
            return candidates
    return []


def level_reading(crop):
    """Suppress orange tile backgrounds with RGB minimum, not luma thresholding."""
    red,green,blue = crop.convert("RGB").split()
    orange=ImageChops.darker(red.point(lambda p:255 if p>160 else 0),
                            ImageChops.darker(ImageChops.subtract(red,green).point(lambda p:255 if p>30 else 0),
                                              ImageChops.subtract(green,blue).point(lambda p:255 if p>20 else 0)))
    box=orange.getbbox()
    if box is None:
        return None,[]
    gray = ImageChops.darker(ImageChops.darker(red,green),blue)
    gray = gray.crop(box)
    gray = gray.resize((gray.width*5,gray.height*5),Image.Resampling.BICUBIC)
    attempts=[]
    for threshold in (160,180,200):
        processed=ImageOps.expand(gray.point(lambda p:0 if p>threshold else 255),10,fill=255)
        tokens=_ocr(processed,7,"0123456789")
        attempts.append(dict(variant=f"neutral{threshold}",text="".join(t['text'] for t in tokens),
                             confidence=min((t['confidence'] for t in tokens),default=0)))
    def options():
        return [(v,a['confidence']) for a in attempts
                if a['confidence']>=.4 and (v:=parse_level(a['text'])) is not None]
    confident=options()
    if len(confident)<2:
        attempts.extend(_read_field(crop,'level',None))
        confident=options()
    if len(confident)<2 or len({v for v,c in confident})!=1:
        return None,attempts
    return confident[0][0],attempts


def recognize_fields(image, candidate, bank):
    regions=candidate['regions']
    level,attempts=level_reading(image.crop(regions['level'].pixels(*image.size)))
    crop=image.crop(regions['exp'].pixels(*image.size))
    matches=[]
    probes=[]
    for entry in bank:
        scale=candidate['anchor_step']/entry['anchor_step']
        if abs(scale-1)<.025:
            scale=1.0
        if not .5<=scale<=4:
            continue
        attempt=match_exp(crop,entry['profile'],scales=(scale,))
        attempt={**attempt,'profile_id':entry['id'],'scale':scale}
        probes.append(attempt)
        if attempt.get('veto'):
            return Recognition('ambiguous',reasons=['conflicting_pixel_readings'],
                               raw=dict(level=attempts,exp=probes),regions=regions)
        if (value:=parse_exp(attempt.get('text') or '')) is not None:
            matches.append((value,attempt,entry['profile']))
    raw=dict(level=attempts,exp=probes)
    values={value for value,attempt,profile in matches}
    if len(values)>1:
        return Recognition('ambiguous',reasons=['conflicting_profiles'],raw=raw,regions=regions)
    if level is None or not values:
        return Recognition('unreadable',reasons=['unverified_level' if level is None else 'no_complete_pixel_match'],
                           raw=raw,regions=regions)
    (exp,percentage),attempt,profile=matches[0]
    reading=Reading(level,exp,percentage)
    errors=reading_errors(reading)
    result=Recognition('invalid' if errors else 'accepted',reading,attempt['confidence'],errors,raw,regions)
    return guard_unverified_exp(result,profile)


def load_bank(path):
    entries=json.loads(path.read_text(encoding='utf-8'))['profiles']
    if not 1<=len(entries)<=4:
        raise ValueError('bank must contain 1..4 profiles')
    bank=[]
    for index,entry in enumerate(entries):
        step=entry['anchor_step']
        if type(step) not in (float,int) or not math.isfinite(step) or step<=0:
            raise ValueError('invalid reference anchor spacing')
        bank.append(dict(id=str(index),profile=GlyphProfile.load(path.parent/entry['path']),anchor_step=step))
    return bank


def inspect(image, bank):
    started=time.perf_counter()
    candidates=locate(image)
    location_seconds=time.perf_counter()-started
    started=time.perf_counter()
    if len(candidates)!=1:
        result=Recognition('ambiguous' if candidates else 'missing_hud',
                           reasons=['multiple_huds' if candidates else 'no_complete_anchor_layout'])
    else:
        result=recognize_fields(image,candidates[0],bank)
    return dict(location_seconds=location_seconds,field_seconds=time.perf_counter()-started,
                candidates=len(candidates),anchor_step=candidates[0]['anchor_step'] if len(candidates)==1 else None,
                result=asdict(result))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image',type=Path)
    parser.add_argument('--bank',type=Path,required=True)
    args=parser.parse_args(argv)
    os.environ.setdefault('OMP_THREAD_LIMIT','1')
    bank=load_bank(args.bank)
    with Image.open(args.image) as image:
        print(json.dumps(inspect(image.convert('RGB'),bank),indent=2))


if __name__=='__main__': main()
