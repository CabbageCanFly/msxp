"""Invented HUD patterns: cache safety, not numerical recognition accuracy."""

import importlib
from pathlib import Path

from PIL import Image,ImageChops
import pytest


@pytest.fixture
def probe(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'tools'))
    return importlib.import_module('cached_hud_probe')


def fixture():
    image=Image.new('RGB',(200,100),(30,30,30))
    anchors={}
    for name,x in zip(('lv','hp','mp','exp'),(20,50,80,110)):
        anchors[name]=dict(x=x,y=60,width=10,height=10)
        for y in range(60,70):
            for a in range(x,x+10):
                if (a+y)%3==0:image.putpixel((a,y),(240,240,240))
    for y in range(60,70):
        for x in range(140,190):
            if (x+y)%3==0:image.putpixel((x,y),(240,240,240))
    candidate=dict(anchors=anchors,regions=dict(level=dict(x0=.15,y0=.6,x1=.2,y1=.7),
                                             exp=dict(x0=.7,y0=.6,x1=.95,y1=.7)))
    return image,candidate


def run(probe,image,cache,seconds=1,**kwargs):
    return probe.recover(image,cache,seconds,candidate_count=kwargs.get('count',0),
                         scene_context=kwargs.get('scene','single_hud_reviewed'))


def test_current_frame_only_and_no_expiry_extension(probe):
    image,candidate=fixture();cache=probe.seed(image,candidate,0)
    current=image.copy();current.putpixel((145,64),(210,210,210))
    for seconds in (1,2):
        result=run(probe,current,cache,seconds)
        assert result['status']=='cached_candidate' and result['trusted'] is False
    assert cache['seconds']==0
    assert run(probe,current,cache,3)['reason']=='expired_or_out_of_order'


def test_shifted_hud_abstains(probe):
    image,candidate=fixture();cache=probe.seed(image,candidate,0)
    assert run(probe,ImageChops.offset(image,2,0),cache)['reason']=='anchor_changed_or_moved'


def test_hidden_hud_abstains(probe):
    image,candidate=fixture();cache=probe.seed(image,candidate,0)
    image.paste((30,30,30),(10,55,195,75))
    assert run(probe,image,cache)['status']=='abstain'


def test_hidden_numeric_field_abstains_even_with_intact_anchors(probe):
    image,candidate=fixture();cache=probe.seed(image,candidate,0)
    image.paste((30,30,30),(140,60,190,70))
    assert run(probe,image,cache)['reason']=='missing_field_evidence'


def test_secondary_hud_requires_review_veto_not_a_claim_of_pixel_detection(probe):
    image,candidate=fixture();cache=probe.seed(image,candidate,0)
    image.paste(image.crop((10,55,195,75)),(10,5))
    result=run(probe,image,cache,scene='multiple_huds')
    assert result['reason']=='multiple_or_unreviewed_huds'
    assert result['trusted'] is False


def test_unknown_scene_cannot_reuse_cache(probe):
    image,candidate=fixture();cache=probe.seed(image,candidate,0)
    assert run(probe,image,cache,scene='unknown')['status']=='abstain'


def test_visual_checks_do_not_replace_an_independent_competitor_gate(probe):
    image,candidate=fixture();cache=probe.seed(image,candidate,0)
    image.paste(image.crop((10,55,195,75)),(10,5))
    result=run(probe,image,cache,scene='single_hud_reviewed')  # Deliberately stale review.
    assert result['status']=='cached_candidate' and result['trusted'] is False
    assert run(probe,image,cache,scene='unknown')['status']=='abstain'


def test_scene_cut_with_unchanged_hud_abstains(probe):
    image,candidate=fixture();cache=probe.seed(image,candidate,0)
    image.paste('white',(0,0,200,50))
    assert run(probe,image,cache)['reason']=='scene_change'


@pytest.mark.parametrize('seconds',[0,-1,2.001,float('nan')])
def test_stale_duplicate_and_invalid_times_abstain(probe,seconds):
    image,candidate=fixture();cache=probe.seed(image,candidate,0)
    assert run(probe,image,cache,seconds)['reason']=='expired_or_out_of_order'


@pytest.mark.parametrize('count',[1,2])
def test_current_detection_never_replaced_by_cache(probe,count):
    image,candidate=fixture();cache=probe.seed(image,candidate,0)
    assert run(probe,image,cache,count=count)['reason']=='fresh_or_ambiguous_detection'


def test_frame_resizing_and_bad_seed_are_rejected(probe):
    image,candidate=fixture();cache=probe.seed(image,candidate,0)
    assert run(probe,image.resize((400,200)),cache)['reason']=='frame_geometry_changed'
    with pytest.raises(ValueError):probe.seed(Image.new('RGB',image.size),candidate,0)
