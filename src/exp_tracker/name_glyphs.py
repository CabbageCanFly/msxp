"""Optional calibrated status-name 0/O evidence; raw OCR and other letters stay intact."""
from functools import cache
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops

POLICY = 'status_name_0o_v1'
# Name-only alternative evidence, not a replacement OCR confidence or a probability.
MIN_SCORE = .75


@cache
def bank():
    try:
        payload = (Path(__file__).resolve().parents[2] / 'private/name-glyphs.json').read_bytes()
        if len(payload) > 8192:return None
        data = json.loads(payload)
        if data['version'] != 1 or set(data['templates']) != {'0', 'O'}:return None
        templates = {c:patch(value) for c,value in data['templates'].items()}
        return hashlib.sha256(payload).hexdigest(), templates
    except (OSError, ValueError, KeyError, TypeError):
        return None


def patch(value):
    if not isinstance(value,str) or len(value) != 960:raise ValueError('Invalid name glyph')
    return Image.frombytes('L', (24,20), bytes.fromhex(value))


def classify(image, templates):
    errors = {c:sum(ImageChops.difference(image,t).tobytes())/(255*480)
              for c,t in templates.items()}
    best = min(errors,key=errors.get)
    other = 'O' if best == '0' else '0'
    return best if errors[best] < .12 and errors[other]-errors[best] > .06 else None


def resolved(raw, slots, templates):
    if (not isinstance(raw,str) or not raw.isascii() or not raw.isalnum()
            or not raw[0:1].isalpha() or not 2 <= len(raw) <= 12
            or not isinstance(slots,list) or len(slots) != sum(c in '0O' for c in raw)):
        return None
    chars = list(raw)
    for slot,index in zip(slots,(i for i,c in enumerate(raw) if c in '0O')):
        if type(slot['index']) is not int or slot['index'] != index:return None
        value = classify(patch(slot['pixels']), templates)
        if value is None:return None
        chars[index] = value
    name = ''.join(chars)
    return name if name != raw else None


def validated(raw, evidence):
    """Recheck bounded shape evidence before it can supply an automatic identity vote."""
    calibration = bank()
    if calibration is None or not isinstance(evidence,dict):return None
    sha,templates = calibration
    try:
        if (evidence.get('policy') != POLICY or evidence.get('bank_sha256') != sha
                or evidence.get('raw_name') != raw):return None
        return resolved(raw,evidence['slots'],templates)
    except (ValueError, KeyError, TypeError):
        return None


def refine(crop, raw):
    calibration = bank()
    if (calibration is None or not isinstance(raw,str) or not any(c in raw for c in '0O')
            or not raw.isascii() or not raw.isalnum() or not raw[0:1].isalpha()
            or not 2 <= len(raw) <= 12 or not 8 < crop.width <= 1024 or not 5 < crop.height <= 256):
        return None
    # shortcut: calibrated status-panel font only; unmatched geometry keeps the original OCR.
    image = crop.convert('L').crop((0,3,crop.width-8,crop.height-2))
    mask = image.point(lambda v:255 if v > 140 else 0)
    glyphs = []; start = None
    for x in range(mask.width+1):
        on = x < mask.width and mask.crop((x,0,x+1,mask.height)).getbbox() is not None
        if on and start is None:start = x
        if not on and start is not None:
            glyph = mask.crop((start,0,x,mask.height));glyphs.append(glyph.crop(glyph.getbbox()));start = None
    if len(glyphs) != len(raw):return None
    slots = []
    for index,c in enumerate(raw):
        if c not in '0O':continue
        glyph = glyphs[index];width = round(glyph.width*16/glyph.height)
        if not 2 <= width <= 20:return None
        image = Image.new('L',(24,20))
        image.paste(glyph.resize((width,16),Image.Resampling.BILINEAR),((24-width)//2,2))
        slots.append(dict(index=index,pixels=image.tobytes().hex()))
    sha,templates = calibration
    if resolved(raw,slots,templates) is None:return None
    return dict(policy=POLICY,bank_sha256=sha,raw_name=raw,slots=slots)
