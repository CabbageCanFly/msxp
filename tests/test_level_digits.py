"""Synthetic geometrical digits plus optional private regression crops."""

from copy import deepcopy
import importlib
import json
from pathlib import Path

from PIL import Image,ImageChops,ImageDraw,ImageOps
import pytest


@pytest.fixture
def levels(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'tools'))
    return importlib.import_module('level_digits')


def tile(digit):
    image=Image.new('RGB',(14,20),(250,140,20))
    draw=ImageDraw.Draw(image)
    rectangles=dict(a=(3,3,9,4),b=(9,4,10,9),c=(9,10,10,15),d=(3,15,9,16),
                    e=(2,10,3,15),f=(2,4,3,9),g=(3,9,9,10))
    segments=['abcdef','bc','abged','abgcd','fbgc','afgcd','afegcd','abc','abcdefg','abcfgd']
    for part in segments[int(digit)]:
        draw.rectangle(rectangles[part],fill='white')
    return image


def field(text):
    image=Image.new('RGB',(len(text)*18+8,28))
    for i,digit in enumerate(text):image.paste(tile(digit),(4+i*18,4))
    return image


@pytest.fixture
def profile(levels):
    digits={}
    for digit in '0123456789':
        image=ImageOps.expand(tile(digit),1,fill='black')
        digits[digit]=[dict(size=list(image.size),masks={str(t):levels.bits(levels.ink(image,t))
                                                      for t in levels.THRESHOLDS})]
    return dict(version=1,families=[dict(id='synthetic-seven-segment',digits=digits)])


@pytest.mark.parametrize('number',[1,2,3,4,5,6,7,8,9,10,56,60,100,200])
def test_exact_levels_without_font_assets(levels,profile,number):
    assert levels.read_level(field(str(number)),profile)['level']==number


@pytest.mark.parametrize('text',['0','01','201','999'])
def test_invalid_levels_and_leading_zero_are_rejected(levels,profile,text):
    assert levels.read_level(field(text),profile)['level'] is None


def test_native_alignment_preserves_all_pixels(levels,profile):
    image=field('8')
    glyph=levels.ink(tile('8'),180)
    moved=Image.new('RGB',(14,20),(250,140,20));moved.paste('white',(0,0,14,20),ImageChops.offset(glyph,1,0))
    image.paste(moved,(4,4))
    assert levels.read_level(image,profile)['level']==8


def test_blank_unknown_and_degraded_glyphs_never_choose_nearest(levels,profile):
    images=[Image.new('RGB',(40,28)),field('8')]
    ImageDraw.Draw(images[1]).rectangle((9,9,12,12),fill='white')
    orange=Image.new('RGB',(40,28));orange.paste(Image.new('RGB',(14,20),(250,140,20)),(4,4));images.append(orange)
    for image in images:assert levels.read_level(image,profile)['level'] is None


def test_clipping_and_extra_orange_fragments_reject(levels,profile):
    image=field('8')
    assert levels.read_level(image.crop((4,0,image.width,image.height)),profile)['reason']=='clipped_tile'
    ImageDraw.Draw(image).rectangle((23,4,23,5),fill=(250,140,20))
    assert levels.read_level(image,profile)['level'] is None


def test_close_digit_classes_are_ambiguous(levels,profile):
    profile=deepcopy(profile)
    profile['families'][0]['digits']['3']=deepcopy(profile['families'][0]['digits']['8'])
    assert levels.read_level(field('8'),profile)['status']=='ambiguous'


def test_threshold_disagreement_vetoes_even_a_two_vote_majority(levels,profile,monkeypatch):
    original=levels.ink
    monkeypatch.setattr(levels,'ink',lambda image,t:original(ImageOps.expand(tile('3' if t==180 else '8'),1,fill='black'),t))
    assert levels.read_level(field('8'),profile)['status']=='ambiguous'


def test_missing_competing_geometry_cannot_create_false_certainty(levels,profile):
    profile=deepcopy(profile)
    profile['families'][0]['digits']['8'][0]['size']=[32,32]
    assert levels.read_level(field('1'),profile)['level'] is None


def test_unknown_scale_is_unavailable(levels,profile):
    image=field('8').resize((52,56),Image.Resampling.NEAREST)
    assert levels.read_level(image,profile)['level'] is None


def test_complete_native_family_supports_another_raster_size(levels,profile):
    def scaled(text):
        image=Image.new('RGB',(len(text)*25+8,38))
        for i,digit in enumerate(text):
            image.paste(tile(digit).resize((21,30),Image.Resampling.NEAREST),(4+i*25,4))
        return image
    digits={}
    for digit in '0123456789':
        tiles,reason=levels.segment_tiles(scaled(digit))
        assert reason is None and len(tiles)==1
        image=tiles[0]
        digits[digit]=[dict(size=list(image.size),masks={str(t):levels.bits(levels.ink(image,t))
                                                      for t in levels.THRESHOLDS})]
    image=scaled('56')
    assert levels.read_level(image,profile)['level'] is None
    profile=deepcopy(profile)
    profile['families'].append(dict(id='synthetic-larger-native-raster',digits=digits))
    assert levels.read_level(image,profile)['level']==56
    assert levels.read_level(field('56'),profile)['level']==56


def test_touching_dark_borders_do_not_merge_bright_tile_cores(levels,profile):
    image=field('10')
    ImageDraw.Draw(image).rectangle((18,12,21,13),fill=(170,100,10))
    assert levels.read_level(image,profile)['level']==10


def test_profile_load_requires_complete_alphabet(levels,profile,tmp_path):
    path=tmp_path/'profile.json';path.write_text(json.dumps(profile))
    assert levels.load_profile(path)['version']==1
    del profile['families'][0]['digits']['8'];path.write_text(json.dumps(profile))
    with pytest.raises(ValueError,match='every digit'):levels.load_profile(path)


def test_calibration_is_manual_complete_and_deterministic(levels,monkeypatch,tmp_path):
    train=importlib.import_module('train_level_digits').train
    examples=[]
    for number in list(range(1,10))+[10]:
        path=tmp_path/f'{number}.png';field(str(number)).save(path)
        examples.append(dict(id=str(number),image=path.name,box=[0,0,*field(str(number)).size],level=number,
                             split='development',family='synthetic'))
    annotation=tmp_path/'training.json';output=tmp_path/'profile.json'
    annotation.write_text(json.dumps(dict(examples=examples)));train(annotation,output);first=output.read_bytes()
    train(annotation,output);assert output.read_bytes()==first
    assert levels.read_level(field('10'),levels.load_profile(output))['level']==10
    examples[0]['split']='heldout';annotation.write_text(json.dumps(dict(examples=examples)))
    with pytest.raises(ValueError,match='development'):train(annotation,output)
    assert output.read_bytes()==first


def test_level_only_scoring_does_not_consult_exp_guards(levels):
    classify=importlib.import_module('evaluate_level_digits').classify
    expected=dict(complete=True,level=8)
    assert classify(8,expected)=='correct'
    assert classify(3,expected)=='incorrect'
    assert classify(None,expected)=='unavailable'
    assert classify(8,dict(complete=False,level=None))=='incorrect'


def test_inspection_cli_uses_only_explicit_profile(levels,profile,tmp_path,capsys):
    image=tmp_path/'level.png';field('10').save(image)
    path=tmp_path/'profile.json';path.write_text(json.dumps(profile))
    levels.main([str(image),'--profile',str(path)])
    assert json.loads(capsys.readouterr().out)['level']==10


@pytest.mark.samples
@pytest.mark.parametrize('seconds,expected',[(384.25,6),(599,8),(1061.75,9),(1064,9),(1065,9)])
def test_known_incorrect_level_cases_are_correct_or_rejected(levels,seconds,expected):
    root=Path(__file__).parents[1]
    path=root/'private/level-digits/profile.json'
    crop=root/f'private/levelup-evaluation/evaluation-crops/recording-crops/{round(seconds*1000):04d}/level-crop.png'
    if not path.exists() or not crop.exists():pytest.skip('Private level calibration/crop is intentionally excluded')
    with Image.open(crop) as image:result=levels.read_level(image,levels.load_profile(path))
    assert result['level'] in (None,expected)
