"""Experimental HUD localization shared by offline evaluation and shadow capture.

No game assets or calibration ship here. Bank paths resolve relative to its JSON:
{"profiles": [{"path": "glyph-profile.json", "anchor_step": 109.0}]}.
anchor_step is the HP-to-MP distance in that profile's development imagery.
"""

import argparse
from dataclasses import asdict
from itertools import combinations
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time

from PIL import Image, ImageChops, ImageOps
import pytesseract
from pytesseract import Output

from exp_tracker.glyphs import GlyphProfile, match_exp
from exp_tracker.models import Reading, Recognition, Region, reading_errors
from exp_tracker.parsing import parse_exp, parse_level
from exp_tracker.recognition import _ocr, _read_field, _tokens, configure_tesseract
from exp_tracker.trust import guard_unverified_exp
from exp_tracker.diagnostic_geometry import exp_vertical_origin, level_tile_box


def label(token):
    # Sparse OCR sometimes merges a label with its following value (e.g. MP5/5).
    text = token["text"].upper()
    for value in ("HP", "MP", "EXP", "LV"):
        if re.match(rf"^{value}(?:$|[\W\d])", text):
            return value
    # Small HUDs can merge a misread opening bracket (I/R) into the HP/MP value.
    merged = re.fullmatch(r"(HP|MP)[IR]([\w/|.]{0,24})([)\]])?", text)
    if merged and (not merged[2] or merged[3] or re.search(r"[0-9]", merged[2])):
        return merged[1]
    return None


def layouts(tokens, size, *, deduplicate=True):
    """Bind a classic HUD row; level coordinates require a matching LV anchor."""
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
                for lv in levels or [None]:
                    if lv is None and not (
                            abs(exp['x']-mp['x']-step)<=.05*step
                            and max(abs(t['y']-hp['y']) for t in (mp,exp))<=.04*step
                            and all(re.fullmatch(name+r'[.:]?',t['text'],re.I)
                                    and t.get('confidence',0)>=.4
                                    and .05*step<=t['height']<=.15*step
                                    and .08*step<=t['width']<=.30*step
                                    for name,t in (('HP',hp),('MP',mp),('EXP',exp)))):
                        continue
                    origin_x,origin_y=hp['x'],hp['y']
                    field_step=step
                    # Correct an HP-token outlier only when MP/EXP and LV/MP independently agree.
                    mp_exp=exp['x']-mp['x'];lv_mp=(mp['x']-lv['x'])/2.9 if lv else 0
                    correction=None
                    if (mp_exp>0 and abs(lv_mp-mp_exp)<=.03*mp_exp
                            and .05*mp_exp<abs(step-mp_exp)<=.15*mp_exp
                            and abs(mp['y']-exp['y'])<=.04*mp_exp):
                        field_step=lv_mp;origin_x=mp['x']-field_step;origin_y=mp['y']
                        correction='hp_outlier_mp_exp_lv_consensus'
                    elif lv is not None and all(re.fullmatch(pattern,t['text'],re.I) for pattern,t in (
                            (r'LV[.:]?',lv),(r'MP[.:]?',mp),(r'EXP[.:]?',exp))):
                        # A tall MP token can move its left edge. Check its residual against stable outer labels.
                        outer_step=(exp['x']-lv['x'])/3.9
                        expected_mp=lv['x']+2.9*outer_step
                        expected_hp=lv['x']+1.9*outer_step
                        if (outer_step>0 and .05*outer_step<abs(hp['x']-expected_hp)<=.15*outer_step
                                and abs(mp['x']-expected_mp)<=min(.03*outer_step,mp['width']/4)
                                and abs(mp['y']-exp['y'])<=.04*outer_step):
                            field_step=outer_step;origin_x=expected_hp;origin_y=mp['y']
                            correction='hp_outlier_lv_exp_span_mp_residual'
                    vertical=exp_vertical_origin(dict(hp=hp,mp=mp,exp=exp,lv=lv),field_step)
                    if vertical is not None and vertical!=origin_y:
                        origin_y=vertical
                        correction=(correction+'+' if correction else '')+'hp_vertical_outlier'
                    # shortcut: one classic HUD layout family; reject other layouts until validated.
                    boxes = dict(exp=(origin_x + 2.26 * field_step, origin_y + .015 * field_step,
                                      origin_x + 3.12 * field_step, origin_y + .105 * field_step))
                    if lv is not None:
                        boxes['level']=(lv['x']+.29*field_step,lv['y']-.04*field_step,
                                        lv['x']+.62*field_step,lv['y']+.17*field_step)
                    if any(x0 < 0 or y0 < 0 or x1 > width or y1 > height
                           for x0,y0,x1,y1 in boxes.values()):
                        continue
                    regions = {key: Region(x0/width,y0/height,x1/width,y1/height)
                               for key,(x0,y0,x1,y1) in boxes.items()}
                    regions.setdefault('level',None)
                    candidate = dict(regions=regions, anchor_step=field_step,
                                     anchors={"hp":hp,"mp":mp,"exp":exp,"lv":lv})
                    if correction: candidate['anchor_correction']=correction
                    if lv is None: candidate['anchor_mode']='hp_mp_exp'
                    if candidate not in candidates:
                        candidates.append(candidate)
    return merge_layouts(candidates,size) if deduplicate else candidates


def merge_layouts(candidates,size):
    """Deduplicate EXP geometry; disputed level geometry supplies no level crop."""
    def tolerance(a,b):
        return .05*min(a['anchor_step'],b['anchor_step'])

    def box_delta(a,b,field):
        return max(abs(x-y) for x,y in zip(a['regions'][field].pixels(*size),b['regions'][field].pixels(*size)))

    def same_exp(a,b):
        limit=tolerance(a,b)
        return (abs(a['anchor_step']-b['anchor_step'])<=limit
            and all(abs(a['anchors'][name][axis]-b['anchors'][name][axis])<=limit
                    for name in ('mp','exp') for axis in ('x','y'))
            and box_delta(a,b,'exp')<=limit)

    groups=[]
    for candidate in candidates:
        for group in groups:
            # Compare every member: near-duplicate chains must not bridge conflicting EXP crops.
            if not all(same_exp(candidate,other) for other in group):continue
            group.append(candidate)
            break
        else:
            groups.append([candidate])
    result=[]
    for group in groups:
        levels=[c for c in group if c['regions']['level'] is not None]
        candidate=levels[0] if levels else group[0]
        if (any(c.get('level_ambiguous') for c in group)
                or any(box_delta(a,b,'level')>tolerance(a,b) for a,b in combinations(levels,2))):
            candidate={**candidate,'regions':{**candidate['regions'],'level':None},
                'anchors':{**candidate['anchors'],'lv':None},'anchor_mode':'hp_mp_exp','level_ambiguous':True}
        result.append(candidate)
    return result


def _ocr_pages(images, psm):
    """One Tesseract process for several images: one process start and model load, faster PNG
    encoding of identical pixels. Measured token-identical to one _ocr call per image."""
    with tempfile.TemporaryDirectory(prefix='msxp-hud-') as directory:
        paths=[Path(directory)/f'{index}.png' for index in range(len(images))]
        for image,path in zip(images,paths):
            image.save(path,format='PNG',compress_level=1)
        listing=Path(directory)/'pages.txt'
        # A non-image input file is read by Tesseract as a list of image paths.
        listing.write_text(''.join(f'{path}\n' for path in paths),encoding='utf-8')
        data=pytesseract.image_to_data(str(listing),lang='eng',config=f'--psm {psm}',
                                       output_type=Output.DICT,timeout=10*len(images))
    pages={n for n,level in zip(data.get('page_num',[]),data.get('level',[])) if level==1}
    if pages!=set(range(1,len(images)+1)):
        # A silently skipped page would hide a HUD; fail like a Tesseract error instead.
        raise RuntimeError(f'Tesseract returned pages {sorted(pages)} for {len(images)} images')
    return [_tokens(data,page) for page in range(1,len(images)+1)]


def scan(image, box=None, *, batched=False):
    """Sparse OCR tokens at each magnification (2x, 3x), in full-frame pixels.

    box (pixels) limits OCR to a crop at the full-frame magnification; it cannot see other HUDs.
    batched=True is an opt-in experiment: same images, one Tesseract process.
    """
    if image.width * image.height > 4096 * 2160:
        return []
    configure_tesseract()
    left,top=box[:2] if box else (0,0)
    crop=image.crop(box) if box else image
    scales=[min(magnification, math.sqrt(1920 * 1080 * magnification**2 / (image.width * image.height)))
            for magnification in (2.0,3.0)]
    def binary(scale):
        return crop.convert("L").resize((round(crop.width*scale),round(crop.height*scale)),
                                        Image.Resampling.BICUBIC).point(lambda p: 0 if p > 160 else 255)
    # The default path builds, reads and releases one scale at a time; only batching holds both.
    pages=(_ocr_pages([binary(scale) for scale in scales],11) if batched
           else [_ocr(binary(scale),11) for scale in scales])
    for scale,tokens in zip(scales,pages):
        for token in tokens:
            for key in ("x","y","width","height"):
                token[key] /= scale
            token["x"]+=left;token["y"]+=top
    return pages


def locate(image, box=None, *, batched=False):
    """Search the whole frame so a small/offset game isn't tied to stream borders."""
    return locate_from_tokens(image,scan(image,box,batched=batched))


def locate_from_tokens(image,pages):
    """Apply the same geometry and badge checks to already-recognized scale pages."""
    candidates=[]
    for tokens in pages:
        candidates.extend(layouts(tokens, image.size,deduplicate=False))
    # Both scales must contribute to uniqueness, including partly obscured HUDs.
    found=merge_layouts(candidates,image.size)
    if (len(found)!=1 or found[0]['regions']['level'] is not None
            or found[0].get('anchor_mode')!='hp_mp_exp' or found[0].get('level_ambiguous')):
        return found
    candidate=found[0];hp=candidate['anchors']['hp'];step=candidate['anchor_step']
    # An overlay can hide LV while leaving the native orange digits visible.
    bounds=(hp['x']-1.61*step,hp['y']+.03*step,hp['x']-1.28*step,hp['y']+.24*step)
    if not (0<=bounds[0]<bounds[2]<=image.width and 0<=bounds[1]<bounds[3]<=image.height):
        return found
    region=Region(bounds[0]/image.width,bounds[1]/image.height,bounds[2]/image.width,bounds[3]/image.height)
    crop=image.crop(region.pixels(*image.size))
    tile=level_tile_box(crop)
    if (tile is not None and 0<tile[0]<tile[2]<crop.width and 0<tile[1]<tile[3]<crop.height
            and .05*step<=tile[2]-tile[0]<=.30*step and .06*step<=tile[3]-tile[1]<=.15*step):
        found=[{**candidate,'regions':{**candidate['regions'],'level':region},
                'level_region_source':'hp_mp_exp_orange_badge'}]
    return found


def search_box(candidate, size):
    """Pixel box covering every token layouts() could bind to this HUD, with margin."""
    step,hp=candidate['anchor_step'],candidate['anchors']['hp']
    return (max(0,math.floor(hp['x']-2.6*step)),max(0,math.floor(hp['y']-.5*step)),
            min(size[0],math.ceil(hp['x']+3.6*step)),min(size[1],math.ceil(hp['y']+.6*step)))


class CachedLocator:
    """Search a recent unique full-frame HUD's neighbourhood first; any doubt rescans the full frame.

    Only a unique full-frame result seeds, and reuse never extends the seed. Within
    refresh_seconds a competing HUD elsewhere in the frame is NOT detected.
    """

    def __init__(self, refresh_seconds, *, clock=time.monotonic, scan=locate):
        self.refresh_seconds,self.clock,self.scan=refresh_seconds,clock,scan
        self.seed=None

    def __call__(self, image):
        now=self.clock()
        seed=self.seed
        if seed and image.size==seed['size'] and 0<=now-seed['at']<=self.refresh_seconds:
            found=self.scan(image,seed['box'])
            if len(found)==1 and same_layout(found[0],seed['candidate'],image.size):
                return [{**found[0],'search':'cached_region','full_frame_age_seconds':now-seed['at']}]
        found=self.scan(image)
        self.seed=dict(at=now,size=image.size,candidate=found[0],box=search_box(found[0],image.size)) if len(found)==1 else None
        return found


def same_layout(a, b, size):
    """Same anchor spacing, EXP geometry and level availability as the seed (merge_layouts tolerance)."""
    limit=.05*min(a['anchor_step'],b['anchor_step'])
    if abs(a['anchor_step']-b['anchor_step'])>limit or (a['regions']['level'] is None)!=(b['regions']['level'] is None):
        return False
    return all(abs(x-y)<=limit for field in ('exp','level') if a['regions'][field] is not None
               for x,y in zip(a['regions'][field].pixels(*size),b['regions'][field].pixels(*size)))


def level_reading(crop):
    """Suppress orange tile backgrounds with RGB minimum, not luma thresholding."""
    red,green,blue = crop.convert("RGB").split()
    box=level_tile_box(crop)
    if box is None:
        return None,[]
    gray = ImageChops.darker(ImageChops.darker(red,green),blue)
    gray = gray.crop(box)
    gray = gray.resize((gray.width*5,gray.height*5),Image.Resampling.BICUBIC)
    attempts=[]
    def neutral(*thresholds,psm=7):
        for threshold in thresholds:
            processed=ImageOps.expand(gray.point(lambda p:0 if p>threshold else 255),10,fill=255)
            tokens=_ocr(processed,psm,"0123456789")
            attempts.append(dict(variant=f"neutral{threshold}"+("-word" if psm==8 else ""),text="".join(t['text'] for t in tokens),
                                 confidence=min((t['confidence'] for t in tokens),default=0)))
    def options():
        return [(v,a['confidence']) for a in attempts
                if a['confidence']>=.4 and (v:=parse_level(a['text'])) is not None]
    neutral(160,180,200)
    confident=options()
    if len(confident)<2:
        attempts.extend(_read_field(crop,'level',None))
        confident=options()
    # Last resort: compression can dim thin strokes (a 7's bar) below 160, dropping that digit, and a line
    # read (PSM 7) can still miss a clean two-tile 7 that a word read (PSM 8) gets. Readings that already
    # reach consensus never get here; any confident disagreement still vetoes.
    for psm in (8,7):
        if len(confident)<2:
            neutral(140,120,psm=psm)
            confident=options()
    if len(confident)<2 or len({v for v,c in confident})!=1:
        return None,attempts
    return confident[0][0],attempts


def recognize_fields(image, candidate, bank):
    regions=candidate['regions']
    level,attempts=(level_reading(image.crop(regions['level'].pixels(*image.size)))
                    if regions['level'] is not None else (None,[]))
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
