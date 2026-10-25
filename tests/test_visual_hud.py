"""The visual fast path must use current pixels and fall back without weakening OCR guards."""
from io import BytesIO
import json
from pathlib import Path
import sys

from PIL import Image,ImageDraw,ImageFont
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import visual_hud as visual
from exp_tracker.models import Region
from exp_tracker.video import CaptureError
from shadow_capture import ResidentNeural,analyze
from exp_tracker.video import Frame
from tests.test_multi_alpha import multi,main as run_main,record  # noqa: F401


def candidate(level=True):
    return dict(regions=dict(exp=Region(.5,.5,.8,.6),level=Region(.1,.5,.2,.8) if level else None),
        anchor_step=40.,anchors=dict(exp=dict(text='EXP',x=90.,y=45.,width=25.,height=12.,confidence=.9)))


@pytest.fixture
def setup(monkeypatch):
    image=Image.new('RGB',(200,100),(60,90,120));buffer=BytesIO();image.save(buffer,'PNG')
    requests=[];reads=[]
    response=dict(version=1,size=list(image.size),cpu_seconds=.01,full=False,reason='matched',boxes=[[40,40,190,95]])
    def resident(command,payload,timeout):
        metadata,png=payload.split(b'\n',1);requests.append(json.loads(metadata))
        assert png==buffer.getvalue() and command[-1].endswith('visual_hud_proposals.py')
        return json.dumps(response if requests[-1]['op']=='detect' else dict(version=1,size=list(image.size),cpu_seconds=.01,trained=True)).encode()
    def reader(*crops):reads.append(crops);return dict(text='1,234[12.34%]')
    monkeypatch.setattr(visual,'locate',lambda _: [candidate()])
    locator=visual.VisualLocator(buffer.getvalue(),'ocr-python',resident,reader)
    return image,locator,response,requests,reads


def test_fast_path_reuses_one_response_for_the_exact_current_original_crop(setup):
    image,locator,_,requests,reads=setup
    found=locator(image);crop=image.crop((98,48,162,62))
    assert locator.info['path']=='masked' and found==[candidate()] and len(reads)==1
    assert reads[0][0].tobytes()==crop.tobytes()
    assert locator.read(crop)==dict(text='1,234[12.34%]') and len(reads)==1
    locator.read(crop)
    assert len(reads)==2 and [r['op'] for r in requests]==['detect']


def test_same_size_different_pixels_cannot_use_the_prefetched_response(setup):
    image,locator,_,_,reads=setup;locator(image)
    locator.read(Image.new('RGB',(64,14),'red'))
    assert len(reads)==2


def test_neural_level_mode_reuses_the_same_pair_of_original_crops(setup):
    image,locator,_,_,reads=setup;locator.experimental=True
    locator(image)
    exp=image.crop((98,48,162,62));level=image.crop(candidate()['regions']['level'].pixels(*image.size))
    assert len(reads)==1 and len(reads[0])==2 and reads[0][1].tobytes()==level.tobytes()
    assert locator.read(exp,level)['text']=='1,234[12.34%]' and len(reads)==1


@pytest.mark.parametrize('text',['[65.30%]','[100.00%]'])
def test_percentage_only_readings_do_not_require_a_numeric_pair(setup,text):
    image,locator,_,_,reads=setup
    locator.reader=lambda *_:dict(text=text)
    assert locator(image)==[candidate()] and locator.info['path']=='masked'


def test_grammar_readings_retry_full_detection_and_keep_the_original_text(setup):
    image,locator,_,requests,_=setup
    locator.reader=lambda *_:dict(text='[6S.30%]')
    assert locator(image)==[candidate()] and locator.info['reason']=='exp_unreadable'
    assert locator.read(image.crop((98,48,162,62)))['text']=='[6S.30%]'
    assert requests[-1]['op']=='learn'


def test_unreadable_exp_retries_original_localization_before_reading_again(setup):
    image,locator,_,requests,_=setup;answers=iter([dict(text='broken'),dict(text='1,234[12.34%]')])
    locator.reader=lambda *_:next(answers)
    assert locator(image)==[candidate()] and locator.info['reason']=='exp_unreadable'
    assert locator.read(image.crop((98,48,162,62)))['text']=='1,234[12.34%]'
    assert [r['op'] for r in requests]==['detect','learn']


@pytest.mark.parametrize('masked',[[],[candidate(),candidate()],[candidate(False)]])
def test_incomplete_or_ambiguous_mask_uses_original_detector(setup,monkeypatch,masked):
    image,locator,_,_,reads=setup
    monkeypatch.setattr(visual,'locate',lambda pixels:masked if pixels.getpixel((0,0))==(0,0,0) else [candidate()])
    assert locator(image)==[candidate()] and not reads and locator.info['reason']=='ocr_incomplete'


@pytest.mark.parametrize('boxes',[[[-1,0,10,10]],[[0,0,201,100]],[[0,0,True,10]],[[0,0,0,10]],[],None])
def test_invalid_worker_regions_fall_back_without_using_them(setup,boxes):
    image,locator,response,_,reads=setup;response['boxes']=boxes
    assert locator(image)==[candidate()] and not reads and locator.info['reason']=='worker_unavailable'


def test_worker_failure_cannot_expose_library_messages_or_prevent_full_ocr(setup):
    image,locator,_,_,reads=setup
    def fail(*_):raise CaptureError('neural_timeout')
    locator.resident=fail
    assert locator(image)==[candidate()] and not reads and locator.info['reason']=='worker_unavailable'


def test_prefetched_reading_cannot_bypass_the_existing_freshness_check(setup):
    image,locator,_,_,_=setup;now=[1.]
    def reader(*_):now[0]=20.;return dict(text='1,234[12.34%]')
    locator.reader=reader
    frame=Frame(locator.png,0,0.,'2026-10-25T00:00:00+00:00')
    result=analyze(frame,{1:15},locator.read,locator=locator,clock=lambda:now[0],max_age=15)
    assert result['candidate'] is None and not result['current']
    assert 'local_receipt_age_exceeded' in result['reasons']


def test_untrained_worker_learns_only_the_label_from_a_unique_full_read(setup):
    image,locator,response,requests,reads=setup;response.update(full=True,reason='untrained',boxes=[])
    assert locator(image)==[candidate()] and not reads
    assert requests==[dict(op='detect'),dict(op='learn',box=[90,45,115,57],step=40.)]


def test_real_worker_bounds_requests_and_keeps_only_in_memory_calibration():
    root=Path(__file__).resolve().parents[1]
    python=root/'private/rapidocr/.venv'/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
    if not python.is_file():pytest.skip('Existing isolated OCR environment absent')
    visual.check(python)
    image=Image.new('RGB',(320,200),(35,35,35))
    ImageDraw.Draw(image).text((200,130),'EXP',fill='white',font=ImageFont.load_default(size=14))
    buffer=BytesIO();image.save(buffer,'PNG')
    resident=ResidentNeural()
    try:
        locator=visual.VisualLocator(buffer.getvalue(),python,resident,lambda *_:None)
        assert locator.request(image,'detect')['reason']=='untrained'
        assert locator.request(image,'learn',box=[198,128,235,149],step=60.)['trained']
        assert locator.request(image,'detect')['reason']=='no_meters'
        locator.png=b'not a PNG'
        with pytest.raises(CaptureError):locator.request(image,'detect')
        assert all(p.poll() is not None for p,_ in resident.processes.values())
    finally:resident.close()


def test_real_worker_detects_a_partial_second_hud_outside_the_meter_mask():
    root=Path(__file__).resolve().parents[1]
    python=root/'private/rapidocr/.venv'/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
    if not python.is_file():pytest.skip('Existing isolated OCR environment absent')
    image=Image.new('RGB',(1200,700),(45,45,45));draw=ImageDraw.Draw(image)
    font=ImageFont.load_default(size=20)
    def labels(y):
        draw.text((158,y),'LV',font=font,fill='white')
        for x,text in zip((500,680,860),('HP','MP','EXP')):draw.text((x,y),text,font=font,fill='white')
    labels(576)
    for x in (500,680,860):draw.rectangle((x,600,x+168,618),outline=(170,170,170),width=2)
    resident=ResidentNeural()
    def locator():
        buffer=BytesIO();image.save(buffer,'PNG')
        return visual.VisualLocator(buffer.getvalue(),python,resident,lambda *_:None)
    try:
        worker=locator();box=list(draw.textbbox((860,576),'EXP',font=font))
        worker.request(image,'learn',box=box,step=180.)
        result=worker.request(image,'detect')
        assert result['full'] is False
        labels(200);worker=locator()
        assert worker.request(image,'detect')['reason']=='unexplained_label'
    finally:resident.close()


def test_coordinator_visual_flag_is_opt_in_and_preflight_precedes_writes(multi,monkeypatch):
    module,path,_,_,_=multi;checks=[];seen=[]
    monkeypatch.setattr(visual,'check',lambda python:checks.append(python))
    def capture(args,source,requirements,index,**kwargs):
        assert args.resident_neural
        seen.append((args.visual_hud,kwargs.get('resident')));return record(index)
    monkeypatch.setattr(module.shadow,'capture_attempt',capture)
    assert run_main(multi,'--visual-hud')==0 and checks and all(flag and worker is not None for flag,worker in seen)


def test_missing_visual_dependencies_fail_before_database_creation(multi,monkeypatch):
    _,path,_,_,_=multi
    def fail(_):raise ValueError('visual preflight unavailable')
    monkeypatch.setattr(visual,'check',fail)
    assert run_main(multi,'--visual-hud','--check')==1 and not (path.parent/'shared.sqlite3').exists()
