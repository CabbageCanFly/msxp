"""Diagnostic two-second ROI reuse. Offline scene review is required, never trust.

No search, character inference, numeric OCR or production integration. Cached
successes never refresh the seed time; only a new unique locator result may seed.
"""

import math

from PIL import Image,ImageChops,ImageStat

from exp_tracker.models import Region


def region(value):
    return Region(**value) if isinstance(value,dict) else value


def seed(image,candidate,seconds):
    if not math.isfinite(seconds) or set(candidate['anchors']) != {'hp','mp','exp','lv'}:
        raise ValueError('Need a finite timestamp and four locator anchors')
    if set(candidate['regions']) != {'level','exp'}:
        raise ValueError('Need both locator regions')
    anchors=[]
    for name,anchor in candidate['anchors'].items():
        box=(math.floor(anchor['x']),math.floor(anchor['y']),
             math.ceil(anchor['x']+anchor['width']),math.ceil(anchor['y']+anchor['height']))
        if not 0<=box[0]<box[2]<=image.width or not 0<=box[1]<box[3]<=image.height:
            raise ValueError('Anchor outside source frame')
        patch=image.crop(box).convert('RGB')
        if max(ImageStat.Stat(patch).stddev)<8:
            raise ValueError('Anchor lacks visible structure')
        anchors.append(dict(name=name,box=box,patch=patch))
    return dict(seconds=seconds,size=image.size,anchors=anchors,
                regions=candidate['regions'],thumbnail=image.convert('RGB').resize((64,36),Image.Resampling.BOX))


def recover(image,cache,seconds,*,candidate_count,scene_context):
    """Gate an unchanged region; reviewed scene metadata is not automatic detection.

    shortcut: global competing-HUD/scene status comes from offline review; keep
    this out of workers until an independent automatic scene gate is validated.
    """
    result=dict(status='abstain',reason=None,regions=None,trusted=False,diagnostics={})
    def reject(reason):
        return {**result,'reason':reason}
    if cache is None:
        return reject('no_cache')
    age=seconds-cache['seconds']
    result['cache_age_seconds']=age
    if not math.isfinite(age) or not 0<age<=2:
        return reject('expired_or_out_of_order')
    if candidate_count != 0:
        return reject('fresh_or_ambiguous_detection')
    if scene_context != 'single_hud_reviewed':
        return reject('multiple_or_unreviewed_huds')
    if image.size != cache['size']:
        return reject('frame_geometry_changed')
    thumbnail=image.convert('RGB').resize((64,36),Image.Resampling.BOX)
    scene=max(ImageStat.Stat(ImageChops.difference(thumbnail,cache['thumbnail'])).mean)
    result['diagnostics']['scene_mae_max_channel']=scene
    if scene>32:
        return reject('scene_change')
    errors={}
    for anchor in cache['anchors']:
        patch=image.crop(anchor['box']).convert('RGB')
        error=max(ImageStat.Stat(ImageChops.difference(patch,anchor['patch'])).mean)
        errors[anchor['name']]=error
    result['diagnostics']['anchor_mae_max_channel']=errors
    if any(error>4 for error in errors.values()):
        return reject('anchor_changed_or_moved')
    box=region(cache['regions']['exp']).pixels(*image.size)
    if not 0<=box[0]<box[2]<=image.width or not 0<=box[1]<box[3]<=image.height:
        return reject('field_out_of_bounds')
    crop=image.crop(box).convert('L')
    bright=sum(p>180 for p in crop.tobytes())
    result['diagnostics']['field_bright_pixels']=bright
    if bright<crop.height or max(ImageStat.Stat(crop).stddev)<8:
        return reject('missing_field_evidence')
    return {**result,'status':'cached_candidate','regions':cache['regions']}
