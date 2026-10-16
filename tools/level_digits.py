"""Experimental native-raster level tiles. No OCR fallback or production integration.

Templates must be manually labeled development data, kept outside Git. Different
native tile sizes need complete digit families; this never stretches unknown glyphs.
"""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageChops


THRESHOLDS = (160, 180, 200)
MAX_DISTANCE = 3
MIN_MARGIN = 2


def segment_tiles(image):
    """Separate orange columns; never discard a small run that might be a digit."""
    if image.width > 256 or image.height > 96:
        return [], 'level_roi_too_large'
    r, g, b = image.convert('RGB').split()
    # Bright cores separate neighboring tiles whose darker borders touch.
    orange = ImageChops.darker(r.point(lambda p: 255 if p > 200 else 0),
        ImageChops.darker(ImageChops.subtract(r,g).point(lambda p:255 if p>50 else 0),
                          ImageChops.subtract(g,b).point(lambda p:255 if p>40 else 0)))
    runs = []
    start = None
    for x in range(image.width + 1):
        present = x < image.width and orange.crop((x,0,x+1,image.height)).getbbox() is not None
        if present and start is None:
            start = x
        if not present and start is not None:
            box = orange.crop((start,0,x,image.height)).getbbox()
            box = (start+box[0]-1,box[1]-1,start+box[2]+1,box[3]+1)
            runs.append(box)
            start = None
    if not 1 <= len(runs) <= 3:
        return [], 'missing_or_extra_tiles'
    for x0,y0,x1,y1 in runs:
        width, height = x1-x0, y1-y0
        if not (4 <= width <= 32 and 8 <= height <= 32 and .3 <= width/height <= 1):
            return [], 'degraded_or_joined_tile'
        if x0 < 0 or y0 < 0 or x1 > image.width or y1 > image.height:
            return [], 'clipped_tile'
    return [image.crop(box).convert('RGB') for box in runs], None


def ink(image, threshold):
    r,g,b = image.convert('RGB').split()
    gray = ImageChops.darker(ImageChops.darker(r,g),b)
    return gray.point(lambda p:255 if p>threshold else 0)


def bits(image):
    return sum(1 << i for i,v in enumerate(image.tobytes()) if v)


def distance(current, template):
    """Preserve native pixels and tile position, allowing at most one-pixel shifts."""
    width = max(current.width,template.width) + 4
    height = max(current.height,template.height) + 4
    a = Image.new('L',(width,height)); a.paste(current,(2,2))
    b = Image.new('L',(width,height)); b.paste(template,(2,2))
    av, bv = bits(a),bits(b)
    return min((av ^ (bv << shift if shift >= 0 else bv >> -shift)).bit_count()
               for shift in (dx+dy*width for dy in (-1,0,1) for dx in (-1,0,1)))


def load_profile(path):
    if path.stat().st_size > 1024*1024:
        raise ValueError('level profile exceeds 1 MiB')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not 1 <= len(data['families']) <= 4:
        raise ValueError('unsupported level profile')
    for family in data['families']:
        if set(family['digits']) != set('0123456789'):
            raise ValueError('each native family must contain every digit')
        for templates in family['digits'].values():
            if not 1 <= len(templates) <= 32:
                raise ValueError('invalid template count')
            for entry in templates:
                w,h = entry['size']
                if type(w) is not int or type(h) is not int or not 4<=w<=32 or not 8<=h<=32:
                    raise ValueError('invalid tile geometry')
                if set(entry['masks']) != {str(t) for t in THRESHOLDS}:
                    raise ValueError('missing threshold templates')
                for value in entry['masks'].values():
                    if type(value) is not int or not 0<value<1<<(w*h):
                        raise ValueError('invalid or empty digit mask')
    return data


def _image(entry, threshold):
    w,h = entry['size']
    value = entry['masks'][str(threshold)]
    image = Image.new('L',(w,h))
    image.putdata([255 if value >> i & 1 else 0 for i in range(w*h)])
    return image


def match_digit(tile, profile, *, mode='consensus'):
    attempts = []
    for threshold in ((180,) if mode == 'single' else THRESHOLDS):
        current = ink(tile,threshold)
        if bits(current).bit_count() < 4:
            attempts.append(dict(threshold=threshold,digit=None,reason='insufficient_ink',ranked=[]))
            continue
        scores = {}
        for family in profile['families']:
            for digit,templates in family['digits'].items():
                for entry in templates:
                    w,h = entry['size']
                    if abs(w-tile.width)>1 or abs(h-tile.height)>1:
                        continue
                    value = distance(current,_image(entry,threshold))
                    scores[digit] = min(value,scores.get(digit,10**9))
        ranked = sorted((score,digit) for digit,score in scores.items())
        digit = None
        reason = 'unknown_geometry_or_shape'
        if len(ranked) == 10 and ranked[0][0] <= MAX_DISTANCE:
            if ranked[1][0]-ranked[0][0] >= MIN_MARGIN:
                digit = ranked[0][1]
                reason = 'native_pixel_match'
            else:
                reason = 'ambiguous_digit'
        attempts.append(dict(threshold=threshold,digit=digit,reason=reason,ranked=ranked))
    values = {a['digit'] for a in attempts if a['digit'] is not None}
    if len(values)>1 or any(a['reason']=='ambiguous_digit' for a in attempts):
        return None, 'ambiguous_digit', attempts
    required = 1 if mode == 'single' else 2
    if len(values)==1 and sum(a['digit'] is not None for a in attempts)>=required:
        return values.pop(), None, attempts
    return None, 'unverified_digit', attempts


def read_level(image, profile, *, mode='consensus'):
    if mode not in ('single','consensus'):
        raise ValueError('mode must be single or consensus')
    tiles,reason = segment_tiles(image)
    digits = []
    diagnostics = []
    if reason is None:
        for tile in tiles:
            digit,error,attempts = match_digit(tile,profile,mode=mode)
            diagnostics.append(dict(size=tile.size,digit=digit,reason=error,attempts=attempts))
            if error:
                reason = error
                break
            digits.append(digit)
    text = ''.join(digits)
    level = int(text) if reason is None and text and not text.startswith('0') else None
    if reason is None and (level is None or not 1<=level<=200):
        reason = 'invalid_level'
    return dict(status='accepted' if reason is None else 'ambiguous' if reason=='ambiguous_digit' else 'unreadable',
                level=level if reason is None else None,reason=reason,digits=diagnostics)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image',type=Path)
    parser.add_argument('--profile',type=Path,required=True)
    parser.add_argument('--mode',choices=('single','consensus'),default='consensus')
    args = parser.parse_args(argv)
    profile = load_profile(args.profile)
    with Image.open(args.image) as image:
        print(json.dumps(read_level(image,profile,mode=args.mode),indent=2))


if __name__=='__main__':main()
