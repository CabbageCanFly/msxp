"""Synthetic safety checks for the isolated experiment; no game assets or profiles."""

import gc
import importlib.util
import json
from pathlib import Path
import weakref

from PIL import Image
import pytest

from exp_tracker.models import Region

SPEC=importlib.util.spec_from_file_location('adaptive_hud',Path(__file__).parents[1]/'tools/adaptive_hud.py')
hud=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hud)


def anchors(x=100,y=40,step=20):
    return [dict(text=name,x=x+dx*step,y=y+dy*step,width=3,height=2,confidence=.8)
            for name,dx,dy in [('HP',0,0),('MP',1,0),('EXP',2,0),('LV.',-1.9,.07)]]


def hidden_lv_anchors(x=300,y=100):
    return [{**t,'width':20,'height':10} for t in anchors(x,y,100)[:3]]


@pytest.mark.parametrize('x,y,step',[(100,40,20),(300,300,45),(600,900,80)])
def test_layout_is_relative_to_anchors(x,y,step):
    result=hud.layouts(anchors(x,y,step),(1920,1080))
    assert len(result)==1
    assert result[0]['anchor_step']==step
    assert result[0]['regions']['exp'].x0==pytest.approx((x+2.26*step)/1920)


def test_hidden_lv_label_can_use_visible_native_badge_without_moving_exp_or_inventing_lv(monkeypatch):
    tokens=hidden_lv_anchors()
    image=Image.new('RGB',(700,200))
    image.paste((240,120,20),(143,107,167,119))
    monkeypatch.setattr(hud,'scan',lambda *args,**kwargs:[tokens,tokens])
    before=hud.layouts(tokens,image.size)[0]
    found=hud.locate(image)
    assert len(found)==1 and found[0]['regions']['level'] is not None
    assert found[0]['regions']['exp']==before['regions']['exp']
    assert found[0]['anchors']['lv'] is None
    assert found[0]['level_region_source']=='hp_mp_exp_orange_badge'
    assert hud.locate(image,batched=True)==found


@pytest.mark.parametrize('badge',[
    None, (0,0,35,20), (139,107,167,119), (143,103,167,119),
    (143,107,172,119), (143,107,167,124), (143,107,145,109),
    (140,105,171,122),
])
def test_hidden_lv_recovery_rejects_absent_misplaced_clipped_tiny_or_oversized_badges(monkeypatch,badge):
    image=Image.new('RGB',(700,200))
    if badge:image.paste((240,120,20),badge)
    monkeypatch.setattr(hud,'scan',lambda *args,**kwargs:[hidden_lv_anchors()])
    assert hud.locate(image)[0]['regions']['level'] is None


def test_hidden_lv_recovery_never_overrides_multiple_huds_disputed_levels_or_a_visible_lv(monkeypatch):
    image=Image.new('RGB',(700,400))
    image.paste((240,120,20),(143,107,167,119))
    monkeypatch.setattr(hud,'scan',lambda *args,**kwargs:[hidden_lv_anchors()+hidden_lv_anchors(y=250)])
    assert len(hud.locate(image))==2
    assert all(c['regions']['level'] is None for c in hud.locate(image))
    base=hud.layouts(hidden_lv_anchors(),image.size)[0]
    monkeypatch.setattr(hud,'merge_layouts',lambda *args:[{**base,'level_ambiguous':True}])
    assert hud.locate(image)[0]['regions']['level'] is None
    visible=hud.layouts(anchors(300,100,100),image.size)[0]
    monkeypatch.setattr(hud,'merge_layouts',lambda *args:[visible])
    assert hud.locate(image)==[visible]


def test_hidden_lv_recovery_rejects_source_bounds_instead_of_padded_pixels(monkeypatch):
    monkeypatch.setattr(hud,'scan',lambda *args,**kwargs:[hidden_lv_anchors(x=150)])
    found=hud.locate(Image.new('RGB',(700,200)))
    assert len(found)==1 and found[0]['regions']['level'] is None


def test_numeric_token_bounds_do_not_move_exp_region():
    tokens=anchors()
    expected=hud.layouts(tokens,(500,200))[0]['regions']
    tokens[2].update(x=tokens[2]['x']+2,width=50,text='EXP123')
    assert hud.layouts(tokens,(500,200))[0]['regions']==expected


def test_hp_anchor_outlier_uses_two_other_spacing_constraints():
    tokens=anchors(780,1050,109)
    tokens[3]['x']=573
    expected=hud.layouts(tokens,(1920,1080))[0]['regions']['exp']
    tokens[0].update(x=769,y=1044)
    corrected=hud.layouts(tokens,(1920,1080))[0]
    assert corrected['anchor_correction']=='hp_outlier_mp_exp_lv_consensus'
    assert abs(corrected['regions']['exp'].x0-expected.x0)*1920<2
    assert corrected['regions']['exp'].y0*1080==pytest.approx(1050+.015*corrected['anchor_step'])
    # A disputed EXP or LV anchor cannot justify silently overriding HP.
    tokens[2]['x']+=5
    assert 'anchor_correction' not in hud.layouts(tokens,(1920,1080))[0]


@pytest.mark.parametrize('exp_x,mp_width,exp_y',[(998.5,16.5,1047),(998.5,22.5,1046)])
def test_bare_label_outer_span_handles_small_mp_displacement(exp_x,mp_width,exp_y):
    # Geometry regression from saved anchors, not expected EXP digits.
    tokens=[dict(text=name,x=x,y=y,width=w,height=h,confidence=.8) for name,x,y,w,h in (
        ('HP',768.5,1044,25.5,15),('MP',886.5,1047.5,mp_width,16.5),
        ('EXP',exp_x,exp_y,20.5,17.5),('LV.',573,1054,20,26))]
    result=hud.layouts(tokens,(1920,1080))[0]
    assert result['anchor_correction']=='hp_outlier_lv_exp_span_mp_residual'
    box=result['regions']['exp'].pixels(1920,1080)
    assert 1025<=box[0]<=1027 and 1048<=box[1]<=1050
    # Source-coordinate check: the leading pixels at x1026 survive this crop.
    image=Image.new('RGB',(1920,1080));image.putpixel((1027,1051),(255,255,255))
    assert image.crop(box).getbbox() is not None
    for index,change in [(1,dict(x=882)),(1,dict(y=1035)),(2,dict(text='EXP123')),(3,dict(x=565))]:
        alternative=[dict(t) for t in tokens];alternative[index].update(change)
        candidates=hud.layouts(alternative,image.size)
        assert not candidates or candidates[0].get('anchor_correction')!='hp_outlier_lv_exp_span_mp_residual'


def test_native_good_geometry_does_not_need_outer_span_override():
    tokens=[dict(text=name,x=x,y=y,width=w,height=h,confidence=.8) for name,x,y,w,h in (
        ('HP',779.5,1049.5,15.5,9.5),('MP',888.5,1049.5,17.5,9.5),
        ('EXP',998.5,1047,20.5,17.5),('LV.',573,1056,20,13))]
    assert 'anchor_correction' not in hud.layouts(tokens,(1920,1080))[0]


def test_vertical_hp_box_contamination_uses_bare_exp_mp_and_lv_without_moving_horizontal_bounds():
    tokens=[dict(text=name,x=x,y=y,width=w,height=h,confidence=.8) for name,x,y,w,h in (
        ('HP.',779.5,1044,15,15),('MP',888.5,1049.5,17.5,9.5),
        ('EXP',1000.5,1049.5,22.5,10),('LV.',573,1056,20,13))]
    corrected=hud.layouts(tokens,(1920,1080))[0]
    assert corrected['anchor_correction']=='hp_vertical_outlier'
    box=corrected['regions']['exp'].pixels(1920,1080)
    assert box[0]==1025 and box[1]==1051 and box[3]>=1061
    for index,changes in [(2,dict(text='EXP123')),(1,dict(y=1030)),(3,dict(y=1070)),(0,dict(height=10))]:
        other=[dict(t) for t in tokens];other[index].update(changes)
        assert all('hp_vertical_outlier' not in c.get('anchor_correction','') for c in hud.layouts(other,(1920,1080)))


@pytest.mark.parametrize('broken',[
    lambda t:t[:2]+t[3:],
    lambda t:[{**a,'y':a['y']+50} if a['text']=='MP' else a for a in t],
    lambda t:[{**a,'x':a['x']+50} if a['text']=='EXP' else a for a in t],
])
def test_missing_or_inconsistent_anchors_reject(broken):
    assert not hud.layouts(broken(anchors()),(500,200))


def test_multiple_huds_are_preserved_as_ambiguity():
    assert len(hud.layouts(anchors()+anchors(100,200),(500,400)))==2


def test_alternate_layouts_sharing_hp_anchor_are_not_silently_collapsed():
    tokens=anchors()
    tokens.append({**tokens[1],'x':tokens[1]['x']+2})
    assert len(hud.layouts(tokens,(500,200)))==2


def test_outside_frame_is_not_clamped_into_plausible_crop():
    assert not hud.layouts(anchors(10,10),(500,200))


@pytest.mark.parametrize('text,expected',[('HP:','HP'),('MP5/5','MP'),('EXP123','EXP'),
                                          ('LV.','LV'),('EXPERIENCE',None),('MPOWER',None)])
def test_anchor_prefix_is_bounded(text,expected):
    assert hud.label({'text':text})==expected


def test_empty_localization_searches_both_scales(monkeypatch):
    monkeypatch.setattr(hud,'configure_tesseract',lambda:None)
    calls=[]
    def ocr(image,*args):
        calls.append(image.size)
        return []
    monkeypatch.setattr(hud,'_ocr',ocr)
    assert not hud.locate(Image.new('RGB',(100,100)))
    assert calls==[(200,200),(300,300)]


def test_three_anchor_hud_keeps_exp_geometry_without_inventing_level():
    full=hud.layouts(anchors(),(500,400))[0]
    partial=hud.layouts(anchors()[:3],(500,400))[0]
    assert partial['regions']['exp']==full['regions']['exp']
    assert partial['regions']['level'] is None and partial['anchors']['lv'] is None
    assert partial['anchor_mode']=='hp_mp_exp' and 'anchor_mode' not in full


@pytest.mark.parametrize('index,change',[(0,dict(confidence=.39)),(1,dict(text='MP5/5')),
    (2,dict(text='EXP123')),(2,dict(x=142)),(2,dict(y=42)),(0,dict(width=1)),
    (2,dict(height=4))])
def test_three_anchor_layout_requires_confident_bare_aligned_labels(index,change):
    tokens=anchors()[:3];tokens[index].update(change)
    assert not hud.layouts(tokens,(500,400))


@pytest.mark.parametrize('x,y',[(460,40),(100,199)])
def test_exp_only_field_outside_frame_is_rejected(x,y):
    assert not hud.layouts(anchors(x,y)[:3],(500,200))


def test_overlapping_duplicate_tokens_merge_but_other_huds_remain():
    tokens=anchors()[:3]
    duplicate={**tokens[1],'x':tokens[1]['x']+.2}
    assert len(hud.layouts(tokens+[duplicate],(500,400)))==1
    mixed=hud.layouts(anchors()+anchors(100,200)[:3],(500,400))
    assert len(mixed)==2 and sum(c['regions']['level'] is None for c in mixed)==1


def test_disputed_exp_anchors_are_not_collapsed_into_one_choice():
    tokens=anchors()
    tokens[2]['x']-=3
    tokens.append({**tokens[2],'x':tokens[2]['x']+6})
    assert len(hud.layouts(tokens,(500,400)))==2


def test_cross_scale_candidates_merge_without_hiding_second_hud(monkeypatch):
    monkeypatch.setattr(hud,'configure_tesseract',lambda:None)
    calls=[]
    def ocr(image,*args):
        scale=image.width/500
        calls.append(scale)
        tokens=anchors() if scale==2 else anchors()+anchors(100,200)[:3]
        return [{**t,**{k:t[k]*scale for k in ('x','y','width','height')}} for t in tokens]
    monkeypatch.setattr(hud,'_ocr',ocr)
    result=hud.locate(Image.new('RGB',(500,400)))
    assert calls==[2,3] and len(result)==2


def test_cross_scale_complete_hud_supplies_level_for_same_exp_only_group(monkeypatch):
    monkeypatch.setattr(hud,'configure_tesseract',lambda:None)
    def ocr(image,*args):
        scale=image.width/500
        tokens=anchors()[:3] if scale==2 else anchors()
        return [{**t,**{k:t[k]*scale for k in ('x','y','width','height')}} for t in tokens]
    monkeypatch.setattr(hud,'_ocr',ocr)
    result=hud.locate(Image.new('RGB',(500,400)))
    assert len(result)==1 and result[0]['regions']['level'] is not None


def candidate():
    return dict(anchor_step=20,regions={'level':Region(0,0,.4,1),'exp':Region(.4,0,1,1)})


def test_level_needs_agreement_and_rejects_conflict(monkeypatch):
    image=Image.new('RGB',(12,12),(250,140,40))
    answers=iter(['8','8','9'])
    monkeypatch.setattr(hud,'_ocr',lambda *args:[dict(text=next(answers),confidence=.95)])
    assert hud.level_reading(image)[0] is None


def scripted_level_passes(monkeypatch,neutral):
    """Neutral passes answer in order 160, 180, 200, then the last-resort 140, 120 as a word and then as a line;
    luma passes and unscripted calls read nothing."""
    answers=iter(neutral);calls=[]
    def ocr(image,psm,whitelist):
        calls.append(psm)
        text,confidence=next(answers,('',0))
        return [dict(text=text,confidence=confidence)] if text else []
    monkeypatch.setattr(hud,'_ocr',ocr)
    monkeypatch.setattr(hud,'_read_field',lambda *args:[dict(variant='luma',text='',confidence=0)]*3)
    return calls


# A compressed 7 loses its thin bar at 160+, so those passes read '1' (or nothing) without confidence.
@pytest.mark.parametrize('last_resort,expected,psms',[
    ([('71',.67),('71',.87)],71,[8,8]),  # two agreeing confident word reads
    ([('',0),('',0),('72',.9),('72',.8)],72,[8,8,7,7]),  # word reads fail, line reads agree
    ([('71',.67),('',0)],None,[8,8,7,7]),  # one confident read is not consensus
    ([('71',.67),('',0),('7',.9)],None,[8,8,7,7]),  # a confident disagreement still vetoes
])
def test_dim_strokes_use_lower_thresholds_only_as_a_consensus_last_resort(monkeypatch,last_resort,expected,psms):
    calls=scripted_level_passes(monkeypatch,[('1',0),('1',0),('',0),*last_resort])
    assert hud.level_reading(Image.new('RGB',(12,12),(250,140,40)))[0]==expected
    assert calls==[7,7,7,*psms]


def test_existing_consensus_never_runs_the_lower_thresholds(monkeypatch):
    calls=scripted_level_passes(monkeypatch,[('63',.9),('63',.9),('',0)])
    level,attempts=hud.level_reading(Image.new('RGB',(12,12),(250,140,40)))
    assert level==63 and len(calls)==3
    assert [a['variant'] for a in attempts]==['neutral160','neutral180','neutral200']


def test_monster_level_tags_and_damage_numbers_do_not_become_the_level_anchor():
    status_bar=anchors(700,1040,150)
    # Monster name tags, damage numbers and a small picture-in-picture feed's label share the frame.
    clutter=[dict(text=text,x=x,y=y,width=30,height=12,confidence=.9) for text,x,y in
             [('Lv.63',950,780),('Lv.57',600,790),('1592',1030,520),('71',1000,700),('LV.',150,990)]]
    alone=hud.layouts(status_bar,(1920,1080))
    found=hud.layouts(status_bar+clutter,(1920,1080))
    assert len(found)==1 and found[0]['regions']==alone[0]['regions']
    assert found[0]['anchors']['lv'] is status_bar[3]
    # Another Lv. tag inside the status bar's own LV window disputes the level: no level crop, never a choice.
    disputed=hud.layouts(status_bar+[dict(text='Lv.',x=435,y=1052,width=20,height=10,confidence=.9)],(1920,1080))
    assert len(disputed)==1 and disputed[0]['regions']['level'] is None and disputed[0]['level_ambiguous']
    assert disputed[0]['regions']['exp']==alone[0]['regions']['exp']


@pytest.mark.samples
@pytest.mark.parametrize('name,level',[('1.png',71),('2.png',71),('10.png',71),('23.png',72),('25.png',72)])
def test_private_two_feed_frame_reads_only_the_main_status_bar(name,level):
    """A percentage-only EXP field; a second, smaller gameplay feed, monster Lv. tags and damage numbers share
    the frame. 71's 7 is too dim for the 160+ passes; 72's clean 7 is missed by line reads at every threshold."""
    path=Path(__file__).parents[1]/'samples/two-feed'/name
    if not path.is_file():pytest.skip('Private two-feed frames are absent; see docs/private-test-data.md')
    image=Image.open(path).convert('RGB')
    found=hud.locate(image)
    assert len(found)==1
    box=found[0]['regions']['level'].pixels(*image.size)
    hp,step=found[0]['anchors']['hp'],found[0]['anchor_step']
    # The main status bar's own LV tiles: left of its HP label, on its row.
    assert hp['x']-2.2*step<box[0]<box[2]<hp['x'] and abs(box[1]-hp['y'])<.1*step
    assert hud.level_reading(image.crop(box))[0]==level


def test_missing_profile_or_failed_match_never_uses_tesseract_exp(monkeypatch):
    monkeypatch.setattr(hud,'level_reading',lambda crop:(10,[]))
    image=Image.new('RGB',(50,10))
    assert hud.recognize_fields(image,candidate(),[]).status=='unreadable'
    monkeypatch.setattr(hud,'match_exp',lambda *a,**kw:dict(variant='pixel',text='',confidence=0))
    bank=[dict(id='synthetic',anchor_step=20,profile=object())]
    result=hud.recognize_fields(image,candidate(),bank)
    assert result.status=='unreadable' and result.reading is None


def test_disagreeing_profiles_are_a_veto(monkeypatch):
    monkeypatch.setattr(hud,'level_reading',lambda crop:(10,[]))
    monkeypatch.setattr(hud,'match_exp',lambda crop,profile,**kw:dict(variant='pixel',text=profile,confidence=.99))
    bank=[dict(id=str(i),anchor_step=20,profile=text) for i,text in enumerate(['100[1.00%]','200[2.00%]'])]
    result=hud.recognize_fields(Image.new('RGB',(50,10)),candidate(),bank)
    assert result.status=='ambiguous' and result.reading is None


def test_existing_guard_still_receives_matched_profile(monkeypatch):
    monkeypatch.setattr(hud,'level_reading',lambda crop:(10,[]))
    monkeypatch.setattr(hud,'match_exp',lambda *a,**kw:dict(variant='pixel',text='100[1.00%]',confidence=.99))
    bank=[dict(id='synthetic',anchor_step=20,profile=object())]
    calls=[]
    def guard(result,profile):
        calls.append(profile)
        result.status='low_confidence'
        return result
    monkeypatch.setattr(hud,'guard_unverified_exp',guard)
    assert hud.recognize_fields(Image.new('RGB',(50,10)),candidate(),bank).status=='low_confidence'
    assert calls==[bank[0]['profile']]


def test_bank_requires_bounded_finite_geometry(tmp_path):
    path=tmp_path/'bank.json'
    for entries in ([],[{}]*5,[dict(anchor_step=-1,path='missing.json')]):
        path.write_text(json.dumps(dict(profiles=entries)))
        with pytest.raises(ValueError):hud.load_bank(path)


@pytest.fixture
def evaluation(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'tools'))
    spec=importlib.util.spec_from_file_location('evaluate_adaptive_hud',Path(__file__).parents[1]/'tools/evaluate_adaptive_hud.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_evaluation_distinguishes_location_from_complete_field_coverage(evaluation):
    expected=dict(complete=True,level=10,current_exp=100,percentage=1.00)
    output=dict(candidates=1,result=dict(status='accepted',reading=dict(level=10,current_exp=100,percentage=1.),
                regions={'level':dict(x0=0,y0=0,x1=.4,y1=1),'exp':dict(x0=.4,y0=0,x1=1,y1=1)},raw={}))
    truth={'level':(0,0,20,10),'exp':(19,0,50,10)}
    result=evaluation.score(output,expected,truth,(50,10))
    assert result['category']=='accepted_correct' and result['location_correct']
    assert result['fields_contained']==dict(level=True,exp=False)


@pytest.mark.parametrize('status,reading,category',[
    ('accepted',dict(level=11,current_exp=100,percentage=1.),'accepted_incorrect'),
    ('low_confidence',dict(level=10,current_exp=100,percentage=1.),'rejected_complete'),
    ('unreadable',None,'incomplete'),
])
def test_evaluation_does_not_call_correct_rejections_acceptance(evaluation,status,reading,category):
    expected=dict(complete=True,level=10,current_exp=100,percentage=1.)
    result=evaluation.score(dict(candidates=0,result=dict(status=status,reading=reading,regions={},raw={})),
                            expected,None,(50,10))
    assert result['category']==category


def test_evaluation_ink_boxes_include_green_punctuation(evaluation):
    image=Image.new('RGB',(20,10))
    image.putpixel((3,4),(255,255,255))
    image.putpixel((8,4),(40,100,40))
    boxes=evaluation.field_truth(image,{'exp':(0,0,20,10)})
    assert boxes=={'exp':(3,4,9,5)}


def tesseract_data(pages):
    """pytesseract DICT output for a multi-image run: a level-1 page row, then each page's words."""
    data={key:[] for key in ('level','page_num','text','conf','left','top','width','height')}
    for number,tokens in enumerate(pages,1):
        for level,token in [(1,dict(text='',confidence=-.01,x=0,y=0,width=0,height=0))]+[(5,t) for t in tokens]:
            for key,value in dict(level=level,page_num=number,text=token['text'],conf=token['confidence']*100,
                                  left=token['x'],top=token['y'],width=token['width'],height=token['height']).items():
                data[key].append(value)
    return data


def crop_tokens(width,crop_width):
    """Two HUDs (one EXP-only) as Tesseract would report them on an image of this width."""
    scale=width/crop_width
    return [{**t,**{k:t[k]*scale for k in ('x','y','width','height')}} for t in anchors()+anchors(100,200)[:3]]


@pytest.mark.parametrize('box',[None,(20,10,480,390)])
def test_batched_scan_returns_the_same_tokens_and_huds_as_separate_ocr(monkeypatch,box):
    crop_width=box[2]-box[0] if box else 500
    monkeypatch.setattr(hud,'configure_tesseract',lambda:None)
    monkeypatch.setattr(hud,'_ocr',lambda image,psm:crop_tokens(image.width,crop_width))
    def image_to_data(listing,**kwargs):
        assert kwargs['config']=='--psm 11'
        widths=[]
        for path in Path(listing).read_text(encoding='utf-8').splitlines():
            with Image.open(path) as page:widths.append(page.width)
        return tesseract_data([crop_tokens(width,crop_width) for width in widths])
    monkeypatch.setattr(hud.pytesseract,'image_to_data',image_to_data)
    image=Image.new('RGB',(500,400))
    pages=hud.scan(image,box)
    assert len(pages)==2 and hud.scan(image,box,batched=True)==pages
    found=hud.locate(image,box,batched=True)
    assert found==hud.locate(image,box) and len(found)==2


def test_default_scan_releases_each_scale_before_building_the_next(monkeypatch):
    monkeypatch.setattr(hud,'configure_tesseract',lambda:None)
    previous=[]
    def ocr(image,psm):
        gc.collect()
        assert all(ref() is None for ref in previous)
        previous.append(weakref.ref(image))
        return []
    monkeypatch.setattr(hud,'_ocr',ocr)
    assert hud.scan(Image.new('RGB',(100,100)))==[[],[]] and len(previous)==2


@pytest.mark.parametrize('data',[
    tesseract_data([anchors()]),                                         # second page missing
    {**tesseract_data([[],anchors()]),'page_num':[2]*6},            # first page missing
    tesseract_data([anchors(),[],[]]),                                    # unexpected extra page
    {},                                                                   # malformed output
])
def test_batched_scan_fails_instead_of_dropping_a_page(monkeypatch,data):
    monkeypatch.setattr(hud,'configure_tesseract',lambda:None)
    monkeypatch.setattr(hud.pytesseract,'image_to_data',lambda *a,**kw:data)
    with pytest.raises(RuntimeError,match='pages'):
        hud.scan(Image.new('RGB',(500,400)),batched=True)


@pytest.mark.ocr
def test_batched_scan_is_token_identical_with_real_tesseract():
    from PIL import ImageDraw, ImageFont
    try:
        hud.configure_tesseract()
    except RuntimeError:
        pytest.skip('Tesseract is not installed')
    image=Image.new('RGB',(960,540),(20,30,60))
    draw=ImageDraw.Draw(image)
    font=ImageFont.load_default(size=14)
    for y in (60,470):
        draw.text((80,y),'LV. 42',fill='white',font=font)
        for x,text in ((300,'HP 120/120'),(450,'MP 80/80'),(600,'EXP 12,345[6.78%]')):
            draw.text((x,y),text,fill='white',font=font)
    pages=hud.scan(image)
    assert any(hud.label(t) for t in pages[1])
    assert hud.scan(image,batched=True)==pages


def test_locate_benchmark_reports_any_token_difference(monkeypatch,tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'tools'))
    spec=importlib.util.spec_from_file_location('benchmark_hud_locate',Path(__file__).parents[1]/'tools/benchmark_hud_locate.py')
    tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)
    frame=tmp_path/'frame.png';Image.new('RGB',(500,400)).save(frame)
    monkeypatch.setattr(tool,'scan',lambda image,batched:[anchors(),anchors()[:3 if batched else 4]])
    output=tmp_path/'result.json'
    assert tool.main([str(frame),'--output',str(output)])==1
    result=json.loads(output.read_text())
    assert result['summary']['mismatches']==[str(frame)] and result['rows'][0]['candidates']==1
    with pytest.raises(FileExistsError):
        tool.main([str(frame),'--output',str(output)])
