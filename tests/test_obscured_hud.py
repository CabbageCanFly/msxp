"""Synthetic EXP-only localization through capture, diagnostics and public projection."""

from datetime import timedelta
import hashlib
import importlib
from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest

from exp_tracker.video import Frame
from tests.test_adaptive_hud import anchors
from tests.test_exp_level_inference import display
from tests.test_product import tracking, NOW, get  # noqa: F401 (pytest fixture)


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'tools'))
    return importlib.import_module('adaptive_hud'),importlib.import_module('shadow_capture')


def frame(index=1):
    image=Image.new('RGB',(500,400))
    image.putpixel((0,0),(index,0,0))
    data=BytesIO();image.save(data,format='PNG')
    stamp=(NOW+timedelta(seconds=15*(index-1))).isoformat()
    return Frame(data.getvalue(),index,100,stamp)


def forbidden(*args):
    pytest.fail('Unavailable level crop must never run level OCR')


def analyze(modules,text,index=1,**kwargs):
    hud,shadow=modules
    def reader(exp,level):
        assert exp.size[0]>0 and level is None
        # Even a misbehaving reader must not invent a level from an absent crop.
        return dict(text=text,raw=dict(txts=[text],scores=[.99]),
            neural_level=dict(status='numeric_candidate',text='51',level=51,score=.99))
    options=dict(clock=lambda:101,locator=lambda image:hud.layouts(anchors()[:3],image.size),
                 read_level=forbidden,experimental_neural_level=True)
    options.update(kwargs)
    return shadow.analyze(frame(index),{42:356916},reader,**options)


def test_absent_level_is_serialized_and_only_exp_crop_is_saved(modules,tmp_path):
    result=analyze(modules,'278,125[77.92%]',crop_dir=tmp_path/'crops')
    assert result['candidate']==[278125,77.92] and result['current']
    assert result['visual_level'] is None and result['visual_status']=='unavailable'
    assert result['visual_attempts']==[] and result['neural_level']['status']=='missing_crop'
    assert result['neural_level']['level'] is None and not result['trusted']
    assert result['localization']['candidates'][0]['regions']['level'] is None
    assert [p.name for p in (tmp_path/'crops').iterdir()]==['exp.png']


def persist(d,result,index):
    captured=frame(index)
    record=dict(result,type='attempt',trusted=False,index=index,
        attempted_at=captured.received_at,received_at=captured.received_at,
        frame_sha256=hashlib.sha256(captured.png).hexdigest(),source=dict(kind='twitch',channel='alpha'))
    d.append('run',record)


def test_exp_only_capture_can_establish_and_retain_public_inferred_level(modules,tracking):
    _,store,d=tracking
    before=store.state('alpha',as_of=NOW)
    for index,exp in enumerate((278125,278525,278925),1):
        result=analyze(modules,f'{exp:,}[{display(exp)}%]',index)
        persist(d,result,index)
    p=get(d,30)
    assert p['display_level']['value']==42
    assert p['display_level']['evidence']['status']=='exp_derived'
    assert p['reading']['level']['status']=='exp_derived'
    assert not p['level_context']['verified'] and p['level_context']['source']=='exp_derived'
    result=analyze(modules,'[78.20%]',4)
    assert result['candidate'] is None and result['diagnostic_type']=='percentage_only'
    persist(d,result,4)
    p=get(d,45)
    assert p['display_level']['value']==42 and p['reading']['percentage']=='78.20'
    assert p['display_level']['evidence']['status']=='retained_level'
    assert store.state('alpha',as_of=NOW)==before
    assert not store.db.execute('SELECT 1 FROM observations').fetchone()
    rows=d.snapshot('alpha',now=NOW+timedelta(seconds=45))['observations']
    assert all(r['visual_level'] is None and r['neural_level']['level'] is None for r in rows)
    assert all(not r['experimental_level'].get('strict_window_eligible') for r in rows)


def test_percentage_only_without_level_context_does_not_invent_level(modules,tracking):
    _,_,d=tracking
    for index,text in enumerate(('[12.00%]','[12.05%]','[12.10%]'),1):
        persist(d,analyze(modules,text,index),index)
    assert get(d,30)['display_level'] is None


@pytest.mark.parametrize('tokens,count',[(anchors()[:2],0),
    (anchors()+anchors(100,200)[:3],2),(anchors()[:3]+anchors(100,200)[:3],2)])
def test_missing_exp_and_competing_huds_never_run_field_ocr(modules,tokens,count):
    hud,shadow=modules
    result=shadow.analyze(frame(),{42:356916},forbidden,clock=lambda:101,
        locator=lambda image:hud.layouts(tokens,image.size),read_level=forbidden)
    assert result['localization']['count']==count and result['candidate'] is None
    assert result['reasons']==['missing_hud' if count==0 else 'multiple_huds']


def test_exp_only_stale_frame_and_expired_result_are_ineligible(modules):
    hud,shadow=modules
    stale=shadow.analyze(frame(),{42:356916},forbidden,clock=lambda:116,locator=forbidden)
    assert stale['status']=='stale_local_frame' and not stale['current']
    now=[101]
    def slow(exp,level):
        assert level is None
        now[0]=116
        return dict(text='278,125[77.92%]')
    result=shadow.analyze(frame(),{42:356916},slow,clock=lambda:now[0],
        locator=lambda image:hud.layouts(anchors()[:3],image.size),read_level=forbidden,
        experimental_neural_level=True)
    assert result['status']=='stale_local_frame' and not result['current']


def test_malformed_realistic_suffix_is_not_promoted_to_strict_pair(modules):
    result=analyze(modules,'1,234[12.34%1')
    assert result['candidate'] is None and result['percentage_only_candidate'] is None
    assert result['status']=='malformed_or_unavailable'
    assert result['neural']['text']=='1,234[12.34%1'


def test_optional_visual_evaluator_abstains_without_level_crop(modules,monkeypatch):
    hud,_=modules
    candidate=hud.layouts(anchors()[:3],(500,400))[0]
    monkeypatch.setattr(hud,'level_reading',forbidden)
    result=hud.recognize_fields(frame().image(),candidate,[])
    assert result.status=='unreadable' and result.reading is None


def test_cached_four_anchor_experiment_rejects_exp_only_candidate(modules):
    hud,_=modules
    cached=importlib.import_module('cached_hud_probe')
    with pytest.raises(ValueError,match='four locator anchors'):
        cached.seed(frame().image(),hud.layouts(anchors()[:3],(500,400))[0],100)
