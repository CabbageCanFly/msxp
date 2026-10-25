"""Offline prototype guards: native fallback parity and frame-local field reads."""
from io import BytesIO
from pathlib import Path
import sys

from PIL import Image,ImageDraw,ImageFont
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import layout_first_hud as layout
from exp_tracker.models import Region
from exp_tracker.video import Frame
from exp_tracker.video import CaptureError
from shadow_capture import analyze


def candidate(level=True):
    return dict(regions=dict(exp=Region(.5,.5,.8,.6),level=Region(.1,.5,.2,.8) if level else None))


@pytest.fixture
def setup(monkeypatch):
    image=Image.new('RGB',(200,100),(60,90,120));calls=[]
    class Engine:
        def __init__(self):self.finished=0;self.cleared=0
        def finish(self):
            self.finished+=1;return [dict(text='full',x=0,y=0,width=1,height=1)]
        def clear(self):self.cleared+=1
    engines=[Engine(),Engine()]
    monkeypatch.setattr(layout,'prepared_pages',lambda _:iter([(Image.new('L',(1,1)),2.),(Image.new('L',(1,1)),3.)]))
    monkeypatch.setattr(layout,'recognize_page',lambda *args:([dict(text='selective',x=0,y=0,width=1,height=1)],dict(fallback=False)))
    monkeypatch.setattr(layout,'locate_from_tokens',lambda *_:[candidate()])
    def reader(*crops):calls.append(crops);return dict(text='1,234[12.34%]')
    locator=layout.LayoutLocator(engines,object(),reader)
    return image,locator,engines,calls


@pytest.mark.parametrize('experimental',[False,True])
def test_selective_path_reads_original_pixels_once_and_clears_native_pages(setup,experimental):
    image,locator,engines,calls=setup;locator.experimental=experimental
    assert locator(image)==[candidate()] and locator.info['path']=='selective'
    crop=image.crop((98,48,162,62));crops=(crop,image.crop((20,50,40,80))) if experimental else (crop,)
    assert calls[0][0].tobytes()==crop.tobytes() and len(calls)==1
    assert locator.read(*crops)['text']=='1,234[12.34%]' and len(calls)==1
    locator.read(*crops)
    assert len(calls)==2 and all(e.cleared==1 and e.finished==0 for e in engines)


@pytest.mark.parametrize('raw',[[],[candidate(),candidate()],[candidate(False)]])
def test_incomplete_or_ambiguous_result_finishes_both_original_pages(setup,monkeypatch,raw):
    image,locator,engines,calls=setup
    monkeypatch.setattr(layout,'locate_from_tokens',lambda image,pages:[candidate()] if pages[0][0]['text']=='full' else raw)
    assert locator(image)==[candidate()] and locator.info['reason']=='incomplete_or_ambiguous'
    assert not calls and all(e.finished==1 and e.cleared==1 for e in engines)


def test_grammar_field_retries_full_read_without_rewriting_the_text(setup):
    image,locator,engines,_=setup
    locator.reader=lambda *_:dict(text='[6S.30%]')
    locator(image)
    assert locator.info['reason']=='imperfect_exp' and all(e.finished==1 for e in engines)
    assert locator.read(image.crop((98,48,162,62)))['text']=='[6S.30%]'


def test_late_fallback_reuses_a_page_already_fully_read(setup,monkeypatch):
    image,locator,engines,_=setup
    def page(engine,*_):
        text='full' if engine is engines[0] else 'selective'
        return [dict(text=text,x=0,y=0,width=1,height=1)],dict(fallback=text=='full')
    monkeypatch.setattr(layout,'recognize_page',page)
    monkeypatch.setattr(layout,'locate_from_tokens',lambda image,pages:[candidate()] if all(p[0]['text']=='full' for p in pages) else [])
    assert locator(image)==[candidate()]
    assert engines[0].finished==0 and engines[1].finished==1


def test_percentage_only_field_does_not_require_numerical_exp(setup):
    image,locator,engines,_=setup;locator.reader=lambda *_:dict(text='[65.30%]')
    locator(image)
    assert locator.info['path']=='selective' and all(e.finished==0 for e in engines)


def test_failed_confirmation_keeps_original_visual_evidence(setup):
    image,locator,engines,_=setup;buffer=BytesIO();image.save(buffer,'PNG')
    def fail(*_):raise CaptureError('neural_timeout')
    locator.reader=fail
    frame=Frame(buffer.getvalue(),0,100.,'2026-10-25T00:00:00+00:00')
    result=analyze(frame,{1:15,2:34},locator.read,locator=locator,clock=lambda:101.,
        read_level=lambda crop:(2,[]))
    assert result['visual_level']==2 and result['neural_status']=='failed'
    assert locator.info['reason']=='field_failed' and all(e.finished==1 for e in engines)


def test_failed_word_crop_finishes_the_original_analyzed_page(monkeypatch):
    words=[(100,50,170,60),(210,50,280,60),(320,50,395,60)]
    class Engine:
        finished=0
        def words(self,image):return words
        def finish(self):self.finished+=1;return [dict(text='full')]
    engine=Engine()
    monkeypatch.setattr(layout,'exp_options',lambda words:{2:{0,1,2}})
    class Broken:
        def tsv(self,*_):raise RuntimeError('private worker detail')
    tokens,details=layout.recognize_page(engine,Broken(),Image.new('L',(400,100)))
    assert tokens[0]['text']=='full' and engine.finished==1
    assert details==dict(fallback=True,reason='crop_failed',probes=0)


def test_pending_prefetch_cannot_make_a_stale_frame_eligible(setup):
    image,locator,_,_=setup;buffer=BytesIO();image.save(buffer,'PNG');now=[1.]
    def reader(*_):now[0]=20.;return dict(text='1,234[12.34%]')
    locator.reader=reader
    result=analyze(Frame(buffer.getvalue(),0,0.,'2026-10-25T00:00:00+00:00'),{1:15},locator.read,
        locator=locator,max_age=15,clock=lambda:now[0])
    assert not result['current'] and result['candidate'] is None and 'local_receipt_age_exceeded' in result['reasons']


def test_new_call_discards_any_unused_field_response(setup):
    image,locator,_,calls=setup;locator(image)
    second=Image.new('RGB',image.size,'red');locator(second)
    assert len(calls)==2 and locator.info['pages']==[dict(fallback=False),dict(fallback=False)]
    locator.read(image.crop((98,48,162,62)))
    assert len(calls)==3


def test_caller_cannot_share_native_handles_between_scales(setup):
    _,_,engines,_=setup
    with pytest.raises(ValueError):layout.LayoutLocator([engines[0],engines[0]],object(),lambda *_:None)
    with pytest.raises(ValueError):layout.LayoutLocator(engines,engines[0],lambda *_:None)


def test_proposals_keep_both_rows_when_secondary_lv_is_hidden():
    words=[(100,50,170,60),(210,50,280,60),(320,50,395,60),
           (100,150,170,160),(210,150,280,160),(320,150,395,160)]
    options=layout.exp_options(words)
    assert {0,1,2}<=options[2] and {3,4,5}<=options[5]
    assert layout.exp_options(words[:2])=={}


@pytest.mark.ocr
def test_real_native_layout_then_recognition_matches_direct_tokens_and_resets():
    import pytesseract
    from exp_tracker.recognition import configure_tesseract,_tokens
    from resident_tesseract import installation,as_data
    try:configure_tesseract();info=installation(pytesseract.pytesseract.tesseract_cmd)
    except (OSError,RuntimeError):pytest.skip('Installed native Tesseract unavailable')
    engine=layout.LayoutEngine(info)
    try:
        image=Image.new('L',(700,100),255)
        ImageDraw.Draw(image).text((20,20),'HP  MP  EXP  LV',fill=0,font=ImageFont.load_default(size=32))
        for source in (image,Image.new('L',image.size,255),image):
            expected=_tokens(as_data(engine.tsv('L',source.size,source.tobytes(),11)))
            engine.words(source)
            assert engine.finish()==expected
        with pytest.raises(ValueError):engine.words(image.convert('RGB'))
    finally:engine.close()


def test_benchmark_refuses_public_output_and_existing_results(tmp_path,monkeypatch):
    import evaluate_layout_hud as benchmark
    monkeypatch.setattr(benchmark,'ROOT',tmp_path)
    with pytest.raises(SystemExit):benchmark.main(['absent.png','--output',str(tmp_path/'public.json')])
    output=tmp_path/'private/results.json';output.parent.mkdir();output.write_text('original')
    with pytest.raises(SystemExit):benchmark.main(['absent.png','--output',str(output)])
    assert output.read_text()=='original'
