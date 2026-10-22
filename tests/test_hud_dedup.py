"""Saved Telfer anchor coordinates and synthetic competing-geometry controls."""
from copy import deepcopy
from datetime import timedelta
import hashlib
from io import BytesIO
from itertools import permutations
import json
from pathlib import Path

from PIL import Image
import pytest

from exp_tracker.models import Region
from exp_tracker.video import Frame
from tests.test_adaptive_hud import hud,anchors
from tests.test_obscured_hud import modules,forbidden  # noqa: F401 (pytest fixture)
from tests.test_product import tracking,NOW,get  # noqa: F401 (pytest fixture)

SIZE=(1920,1080)


def telfer_tokens():
    # Native coordinates from 20261019T095936Z-ef8a3750, Telfer attempt 2, 2x/3x OCR.
    return [[dict(text=text,confidence=c,x=x,y=y,width=w,height=h) for text,c,x,y,w,h in probe]
        for probe in [
            [('HP:',.32,779.5,1049.5,15.5,9.5),('MP:',0,888.5,1049.5,17.5,9.5),
             ('EXP',.63,998.5,1047.5,21.5,17),('LV.',.7,574,1056,19,13)],
            [('HP:',.49,779+2/3,1049+2/3,15,9+1/3),('MP',.95,888+2/3,1049+2/3,17+1/3,9+1/3),
             ('EXP',.94,999,1048+1/3,21,14),('LV.',.54,563+1/3,1054+2/3,29+2/3,25+1/3)]]]


def candidates():
    return [hud.layouts(tokens,SIZE)[0] for tokens in telfer_tokens()]


@pytest.mark.parametrize('reverse',[False,True])
def test_saved_telfer_exp_is_unique_while_displaced_level_is_unavailable(reverse):
    group=candidates()[::(-1 if reverse else 1)];original=deepcopy(group)
    merged=hud.merge_layouts(group,SIZE)
    assert len(merged)==1 and merged[0]['level_ambiguous']
    assert merged[0]['regions']['level'] is None and merged[0]['anchors']['lv'] is None
    assert merged[0]['regions']['exp'] in [c['regions']['exp'] for c in group]
    assert group==original
    # Repeated merging or another complete proposal cannot revive a disputed level.
    again=hud.merge_layouts(merged+[group[0]],SIZE)
    assert len(again)==1 and again[0]['regions']['level'] is None


def test_close_level_jitter_and_exact_duplicates_keep_the_complete_path():
    a=candidates()[0];b=deepcopy(a);region=b['regions']['level']
    b['regions']['level']=Region(region.x0+2/1920,region.y0,region.x1+2/1920,region.y1)
    assert hud.merge_layouts([a,a,b],SIZE)==[a]


@pytest.mark.parametrize('conflict',['exp_box','exp_anchor','mp_anchor','step'])
def test_exp_disagreements_remain_multiple_even_when_levels_also_disagree(conflict):
    a,b=candidates()
    if conflict=='exp_box':
        r=b['regions']['exp'];b['regions']['exp']=Region(r.x0+6/1920,r.y0,r.x1+6/1920,r.y1)
    elif conflict=='step':b['anchor_step']+=6
    else:b['anchors']['exp' if conflict=='exp_anchor' else 'mp']['x']+=6
    assert len(hud.merge_layouts([a,b],SIZE))==2


def test_real_distinct_hud_rows_survive_duplicate_level_interpretations():
    tokens=telfer_tokens()[0]
    second=[{**t,'y':t['y']-200} for t in tokens]
    merged=hud.merge_layouts(candidates()+hud.layouts(second,SIZE),SIZE)
    assert len(merged)==2
    assert sum(c['regions']['level'] is None for c in merged)==1


def test_near_duplicate_chains_cannot_hide_disputed_exp_geometry():
    a,b=candidates();c=deepcopy(a)
    for candidate,shift in ((b,4),(c,-4)):
        for name in ('hp','mp','exp'):candidate['anchors'][name]['x']=a['anchors'][name]['x']+shift
        r=a['regions']['exp'];candidate['regions']['exp']=Region(r.x0+shift/1920,r.y0,r.x1+shift/1920,r.y1)
    for order in permutations([a,b,c]):assert len(hud.merge_layouts(order,SIZE))==2


def test_live_locator_merges_once_after_collecting_both_scales(monkeypatch):
    monkeypatch.setattr(hud,'configure_tesseract',lambda:None)
    calls=[];real_layouts=hud.layouts
    def layouts(tokens,size,**options):
        calls.append(options)
        return real_layouts(tokens,size,**options)
    monkeypatch.setattr(hud,'layouts',layouts)
    def ocr(image,*args):
        scale=image.width/500;tokens=anchors()
        if scale==3:tokens[-1]['x']-=3  # Same EXP, conflicting level at this smaller scale.
        return [{**t,**{k:t[k]*scale for k in ('x','y','width','height')}} for t in tokens]
    monkeypatch.setattr(hud,'_ocr',ocr)
    found=hud.locate(Image.new('RGB',(500,400)))
    assert calls==[dict(deduplicate=False)]*2
    assert len(found)==1 and found[0]['regions']['level'] is None


def test_deduplicated_telfer_geometry_flows_to_existing_inference_without_level_ocr(modules,tracking,tmp_path):
    _,shadow=modules;_,store,d=tracking
    geometry=hud.merge_layouts(candidates(),SIZE)
    texts=('82,330[21.05%]','82,338[21.05%]','[21.06%]')  # Synthetic EXP; no saved pixels/digits reused.
    for index,text in enumerate(texts,1):
        image=Image.new('RGB',SIZE);image.putpixel((0,0),(index,0,0))
        stream=BytesIO();image.save(stream,format='PNG');stamp=(NOW+timedelta(seconds=15*(index-1))).isoformat()
        frame=Frame(stream.getvalue(),index,100,stamp)
        def reader(exp,level):
            assert exp.size[0]>0 and level is None
            return dict(text=text,neural_level=dict(status='numeric_candidate',text='99',level=99,score=.99))
        result=shadow.analyze(frame,{43:391160},reader,clock=lambda:101,
            locator=lambda image:geometry,read_level=forbidden,experimental_neural_level=True,
            crop_dir=tmp_path/f'crop-{index}')
        assert result['current'] and result['visual_level'] is None
        assert result['neural_level']['status']=='missing_crop'
        assert [p.name for p in (tmp_path/f'crop-{index}').iterdir()]==['exp.png']
        d.append('run',dict(result,type='attempt',index=index,attempted_at=stamp,received_at=stamp,
            frame_sha256=hashlib.sha256(frame.png).hexdigest(),source=dict(kind='twitch',channel='alpha')))
    p=get(d,30)
    assert p['display_level']['value']==43 and p['reading']['percentage']=='21.06'
    assert p['display_level']['evidence']['status']=='retained_level'
    assert not store.db.execute('select 1 from observations').fetchone()


@pytest.mark.parametrize('stale',[False,True])
def test_competing_or_stale_geometry_never_runs_field_ocr(modules,stale):
    _,shadow=modules
    stream=BytesIO();Image.new('RGB',SIZE).save(stream,format='PNG')
    frame=Frame(stream.getvalue(),1,100,NOW.isoformat())
    a,b=candidates();r=b['regions']['exp']
    b['regions']['exp']=Region(r.x0+.01,r.y0,r.x1+.01,r.y1)
    result=shadow.analyze(frame,{43:391160},forbidden,clock=lambda:116 if stale else 101,
        locator=forbidden if stale else lambda image:hud.merge_layouts([a,b],SIZE),read_level=forbidden)
    assert result['candidate'] is None and not result['current']
    assert result['reasons']==['local_receipt_age_exceeded' if stale else 'multiple_huds']


@pytest.mark.parametrize('folder,suffix,count,before,after',[
    ('20261019T092547Z-0e1bd0f9','',60,43,54),
    ('20261019T092547Z-0e1bd0f9','b84401fd96444d2582dc724ee8310584',11,9,11),
    ('20261019T095936Z-ef8a3750','',36,23,35)])
def test_private_saved_candidate_replay_keeps_exp_disagreements_rejected(folder,suffix,count,before,after):
    path=Path('private/test-fixtures/runs')/folder/'telfer1'/suffix/'capture.jsonl'
    if not path.is_file():pytest.skip('private Telfer capture unavailable')
    rows=[json.loads(s) for s in path.read_text().splitlines() if json.loads(s).get('type')=='attempt'][:count]
    original_counts=[];merged_counts=[]
    for row in rows:
        candidates=[{**c,'regions':{k:Region(**v) if v else None for k,v in c['regions'].items()}}
            for c in row['localization']['candidates']]
        frozen=deepcopy(candidates);merged=hud.merge_layouts(candidates,row['frame_size'])
        assert candidates==frozen
        if len(candidates)==1:assert merged==candidates
        if len(candidates)>1 and len(merged)==1:
            assert merged[0]['regions']['level'] is None and merged[0]['level_ambiguous']
            assert merged[0]['regions']['exp'] in [c['regions']['exp'] for c in candidates]
        original_counts.append(len(candidates));merged_counts.append(len(merged))
    assert len(rows)==count and original_counts.count(1)==before and merged_counts.count(1)==after
