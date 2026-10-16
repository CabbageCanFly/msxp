"""Invented glyphs only; no private game assets or model-dependent labels."""

import importlib
from pathlib import Path

from PIL import Image
import pytest


@pytest.fixture
def probe(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'tools'))
    return importlib.import_module('pixel_numeric_probe')


def glyph(digit):
    image=Image.new('L',(8,10))
    # Deliberately invented, well-separated patterns rather than a game font.
    for y in range(2,8):
        image.putpixel((2,y),255)
        image.putpixel((5,y),255)
    for bit in range(4):
        if int(digit) >> bit & 1:
            for x in range(2,6): image.putpixel((x,1+bit*2),255)
    return image


def references():
    return {d:[glyph(d)] for d in '0123456789'}


def test_compares_all_classes_without_a_neural_prediction(probe):
    result=probe.rank_patch(glyph('8'),references())
    assert result['digit']=='8' and result['ranked'][0]==dict(digit='8',distance=0)
    assert len(result['ranked'])==10 and result['margin']>=2


def test_native_alignment_shift_is_bounded(probe):
    image=Image.new('L',(8,10));image.paste(glyph('8'),(1,0))
    assert probe.rank_patch(image,references())['digit']=='8'
    moved=Image.new('L',(8,10));moved.paste(glyph('8'),(3,0))
    assert probe.rank_patch(moved,references())['digit'] is None


def test_ambiguous_shapes_abstain(probe):
    refs=references();refs['9']=[glyph('8')]
    result=probe.rank_patch(glyph('8'),refs)
    assert result['digit'] is None and result['reason']=='ambiguous' and result['margin']==0


def test_unknown_shape_abstains(probe):
    result=probe.rank_patch(Image.new('L',(8,10),255),references())
    assert result['digit'] is None and result['reason']=='distance'


def test_thresholding_can_erase_independent_visual_evidence(probe):
    gray=glyph('9')
    gray.putpixel((0,5),170)  # A visible weak stroke disappears at the fixed threshold.
    binary=gray.point(lambda p:255 if p>180 else 0)
    assert gray.tobytes()!=binary.tobytes()
    assert probe.rank_patch(binary,references())['digit']=='9'


@pytest.mark.parametrize('fault',['missing','geometry'])
def test_missing_native_competitor_cannot_verify_any_digit(probe,fault):
    refs=references()
    if fault=='missing': del refs['6']
    else: refs['6']=[Image.new('L',(8,12),255)]
    assert probe.rank_patch(glyph('8'),refs)['reason']=='missing_native_classes'


def field():
    image=Image.new('RGB',(80,20),(30,30,30))
    for box in [(3,4,9,14),(11,4,17,14),(26,4,32,14),(38,4,44,14)]:
        image.paste('white',box)
    image.paste((120,180,50),(21,4,24,14))
    image.paste((120,180,50),(50,4,53,14))
    image.paste('white',(0,18,80,19))
    return image


def test_color_split_is_independent_of_text_and_keeps_fragments(probe):
    image=field();image.paste((30,30,30),(5,4,6,14))
    result=probe.segment_prefix(image)
    assert result['reason'] is None
    assert result['boxes']==[(3,4,5,14),(6,4,9,14),(11,4,17,14)]
    assert sum(sum(bool(v) for v in p.tobytes()) for p in result['patches'])==110


def test_missing_color_anchor_is_not_inferred(probe):
    image=field();image.paste((30,30,30),(50,4,53,14))
    assert probe.segment_prefix(image)['reason']=='ambiguous_color_regions'


def test_empty_and_oversize_fields_abstain(probe):
    assert probe.segment_prefix(Image.new('RGB',(80,20)))['reason']=='ambiguous_text_band'
    assert probe.segment_prefix(Image.new('RGB',(513,20)))['reason']=='input_bounds'
