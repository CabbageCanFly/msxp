"""Layout-first guards: native fallback parity and frame-local field reads."""
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


def test_ambiguous_grammar_field_retries_full_read_without_rewriting_the_text(setup):
    image,locator,engines,_=setup
    locator.reader=lambda *_:dict(text='165.30%1')
    locator(image)
    assert locator.info['reason']=='imperfect_exp' and all(e.finished==1 for e in engines)
    assert locator.read(image.crop((98,48,162,62)))['text']=='165.30%1'


@pytest.mark.parametrize('text',['416,675[18.15%1','466.586120.33%1','[65.30%1','7.362[0.29%1'])
def test_existing_punctuation_repair_can_confirm_hud_without_rewriting_or_repeating_field_read(setup,text):
    image,locator,engines,calls=setup
    response=dict(text=text,source_complete=None)
    def reader(*crops):calls.append(crops);return response
    locator.reader=reader
    assert locator(image)==[candidate()] and locator.info['path']=='selective'
    assert locator.read(image.crop((98,48,162,62))) is response
    assert len(calls)==1 and all(e.finished==0 and e.cleared==1 for e in engines)
    assert response==dict(text=text,source_complete=None)


@pytest.mark.parametrize('response',[
    dict(text='416,675[18.15%1',source_complete=False),
    dict(text='S16,675[18.15%1'),dict(text='B16,675[18.15%1'),
    dict(text='416,675[18.15%1 trailing'),dict(text='165.30%1'),
    dict(text='416,675[18.15%1 12,345[6.78%]'),
    dict(text='[65.3%1'),dict(text='12,34[56.78%1'),
    dict(text='19210.07%1'),dict(text='416,675[18.15X1'),
    dict(text=None),None])
def test_other_repairs_and_incomplete_or_ambiguous_fields_keep_full_fallback(response):
    assert layout.confirmed_field(response) is False


@pytest.mark.parametrize('text',[
    '[6S.30%1','[65.O0%]','[6B.30%]','416,67S[18.15%1',
    '4,059125.17%1','3,862[32.97%','1.234,567[12.34%1',
    '1.,234[12.34%]','P4,059[25.17%1','P[65.30%]','65.30%1','[65,30%]'])
def test_existing_unique_grammar_families_share_the_fast_path_without_new_substitution_rules(text):
    from exp_tracker.shadow_grammar import interpret_exp
    parsed=interpret_exp(text)
    assert any(parsed[field]['classification']=='unique_proposal' for field in ('full_exp','percentage'))
    assert layout.confirmed_field(dict(text=text)) is True
    assert layout.confirmed_field(dict(text=text,source_complete=False)) is False


def test_new_context_dependent_grammar_metadata_cannot_silently_bypass_fallback(monkeypatch):
    from copy import deepcopy
    parsed=deepcopy(layout.interpret_exp('4,059[25.17%1'))
    for field in ('full_exp','percentage'):
        parsed[field]['proposals'][0]['required_context']='independent_confirmation'
    monkeypatch.setattr(layout,'interpret_exp',lambda text,**kwargs:parsed)
    assert layout.confirmed_field(dict(text='4,059[25.17%1')) is False


def test_repair_never_bypasses_competing_hud_or_missing_level_fallback(setup,monkeypatch):
    image,locator,engines,calls=setup
    locator.reader=lambda *_:dict(text='416,675[18.15%1')
    monkeypatch.setattr(layout,'locate_from_tokens',lambda *_:[candidate(),candidate(False)])
    assert len(locator(image))==2 and locator.info['reason']=='incomplete_or_ambiguous'
    assert not calls and all(e.finished==1 for e in engines)


@pytest.mark.parametrize('clean,repaired,level',[
    ('5[1.34%]','5[1.34%1',6),
    ('76,257[35.21%]','76.257135.21%1',37)])
def test_strict_to_existing_grammar_keeps_normal_numeric_and_percentage_eligibility(clean,repaired,level):
    from exp_tracker.shadow_grammar import interpret_exp
    from exp_tracker.diagnostic_evidence import project,full_reading
    from exp_tracker.diagnostic_progress import percentage_point
    from tests.test_diagnostic_progress import row
    results=[]
    for raw in (clean,repaired):
        parsed=interpret_exp(raw)
        record=row(1,raw_text=raw,candidate=parsed['strict_full'],percentage_only_candidate=None,
            status='diagnostic_pair' if parsed['strict_full'] else 'malformed_or_unavailable',
            visual_level=level)
        projected=project([record])[0];point,reason=percentage_point(projected)
        assert reason is None and point['comparison_eligible'] is True
        results.append((full_reading(projected),projected['experimental_level']['value'],projected['exp_validity']['status'],point['percentage']))
    assert results[0]==results[1] and results[0][2]=='consistent'


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
