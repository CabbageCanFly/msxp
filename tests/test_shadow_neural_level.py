"""Synthetic IPC/diagnostic safety tests; no neural environment or private images."""
from io import BytesIO
import importlib
import json
from pathlib import Path
import struct
from types import SimpleNamespace

from PIL import Image
import pytest

from exp_tracker.models import Region
from exp_tracker.shadow_view import observation
from exp_tracker.video import CaptureError, Frame


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'tools'))
    return (importlib.import_module('shadow_neural'),importlib.import_module('shadow_rapidocr'),
            importlib.import_module('shadow_capture'))


def level(protocol,text='51'):
    return protocol.level_result(dict(txts=[text],scores=[.99],boxes=None),.02,.001)


def output(text):
    return SimpleNamespace(txts=[text],scores=[.99],boxes=None,elapse=.01,elapse_list=None)


def test_pair_transport_exact_source_pixels_and_missing_level(modules):
    protocol,_,_=modules
    a,b=Image.new('RGB',(50,15),'orange'),Image.new('RGB',(52,33),'white')
    packet=protocol.pack(a,b)
    left,right=protocol.unpack(packet)
    assert protocol.load_crop(left,protocol.EXP_SIZE).tobytes()==a.tobytes()
    assert protocol.load_crop(right,protocol.LEVEL_SIZE).tobytes()==b.tobytes()
    assert protocol.unpack(protocol.pack(a,None))[1]==b''


@pytest.mark.parametrize('bad',[b'',b'123',struct.pack('!I',0)+struct.pack('!I',0),
    struct.pack('!I',1048577),struct.pack('!I',10)+b'png'])
def test_invalid_packet_boundaries_rejected(modules,bad):
    with pytest.raises(ValueError):
        modules[0].unpack(bad)


def test_extra_bytes_and_unsafe_crop_dimensions_rejected(modules):
    protocol,_,_=modules
    image=Image.new('RGB',(10,10))
    with pytest.raises(ValueError):
        protocol.unpack(protocol.pack(image,None)+b'extra')
    with pytest.raises(ValueError):
        protocol.pack(image,Image.new('RGB',(257,10)))
    with pytest.raises((OSError,ValueError)):
        protocol.load_crop(b'not PNG',protocol.LEVEL_SIZE)


@pytest.mark.parametrize('background',[(240,120,20),(80,80,80)])
def test_one_engine_exp_first_and_exact_frozen_neutral4(modules,background):
    protocol,worker,_=modules
    preprocessor=importlib.import_module('benchmark_rapidocr_levels').preprocess
    exp=Image.new('RGB',(50,15),'black'); crop=Image.new('RGB',(52,33),background)
    crop.putpixel((10,10),(200,210,220))
    calls=[]
    def engine(image,**kwargs):
        calls.append(image.copy())
        assert kwargs==dict(use_det=False,use_cls=False,use_rec=True)
        return output('17[50.00%]' if len(calls)==1 else '51')
    result=worker.recognize_fields(engine,exp,protocol.png_bytes(crop,protocol.LEVEL_SIZE),experimental=True)
    assert len(calls)==2 and calls[0].size==(100,30)
    assert calls[1].tobytes()==preprocessor(crop,'neutral4').tobytes()
    assert result['text']=='17[50.00%]' and result['neural_level']['level']==51
    assert result['neural_level']['source_complete'] is None and not result['neural_level']['trusted']


def test_neural_level_uses_same_tiles_despite_surrounding_hud_pixels(modules):
    from exp_tracker.diagnostic_geometry import level_tile_box
    protocol,worker,_=modules
    preprocessor=importlib.import_module('benchmark_rapidocr_levels').preprocess
    tiles=Image.new('RGB',(23,13),(240,120,20))
    tiles.putpixel((5,5),(255,255,255))
    tiles.putpixel((17,5),(255,255,255))
    expected=preprocessor(tiles,'neutral4')
    for offset in ((2,5),(11,6)):
        crop=Image.new('RGB',(37,24),(80,80,80))
        crop.paste(tiles,offset)
        assert level_tile_box(crop)==(*offset,offset[0]+23,offset[1]+13)
        calls=[]
        def engine(image,**kwargs):
            calls.append(image.copy())
            return output('17[50.00%]' if len(calls)==1 else '71')
        result=worker.recognize_fields(engine,Image.new('RGB',(50,15)),
                                      protocol.png_bytes(crop,protocol.LEVEL_SIZE),experimental=True)
        assert len(calls)==2
        assert calls[1].size==expected.size and calls[1].tobytes()==expected.tobytes()
        assert result['neural_level']['level']==71
        assert result['neural_level']['source_complete'] is None


@pytest.mark.parametrize('text',['S 1','S1','B3','5I','5 1','0','201','051','日',''])
def test_nonnumeric_or_invalid_numbers_never_repaired(modules,text):
    result=level(modules[0],text)
    assert result['level'] is None and result['text']==text and not result['trusted']


def test_clipped_tile_can_still_yield_numeric_candidate_not_complete_source_proof(modules):
    protocol,worker,_=modules
    crop=Image.new('RGB',(30,30),'orange')  # Represents a partial source with one tile left.
    calls=[]
    def engine(image,**kwargs):
        calls.append(image)
        return output('17[50.00%]' if len(calls)==1 else '1')
    result=worker.recognize_fields(engine,crop,protocol.png_bytes(crop,protocol.LEVEL_SIZE),experimental=True)
    assert result['neural_level']['level']==1
    assert result['neural_level']['source_complete'] is None and not result['neural_level']['trusted']


@pytest.mark.parametrize('payload,status',[(None,'missing_crop'),(b'broken PNG','invalid_crop')])
def test_optional_level_missing_or_invalid_preserves_exp(modules,payload,status):
    result=modules[1].recognize_fields(lambda *a,**kw:output('17[50.00%]'),Image.new('RGB',(30,15)),payload,experimental=True)
    assert result['text']=='17[50.00%]' and result['neural_level']['status']==status


def test_optional_level_inference_failure_preserves_exp(modules):
    protocol,worker,_=modules
    calls=[]
    def engine(*args,**kwargs):
        calls.append(1)
        if len(calls)==2: raise RuntimeError('private failure detail')
        return output('17[50.00%]')
    image=Image.new('RGB',(30,15))
    result=worker.recognize_fields(engine,image,protocol.png_bytes(image,protocol.LEVEL_SIZE),experimental=True)
    assert result['text']=='17[50.00%]' and result['neural_level']['status']=='failed'
    assert 'private failure' not in str(result)


def test_legacy_worker_runs_only_exp_and_returns_legacy_shape(modules):
    calls=[]
    def engine(*a,**kw): calls.append(1); return output('17[50.00%]')
    result=modules[1].recognize_fields(engine,Image.new('RGB',(30,15)))
    assert calls==[1] and 'neural_level' not in result and result['text']=='17[50.00%]'


@pytest.mark.parametrize('change',[{'text':'S1'},{'level':50},{'level':True},{'trusted':True},
    {'status':'accepted'},{'raw':{'txts':'51','scores':[.99]}},{'inference_seconds':float('nan')},
    {'raw':{'txts':['51'],'scores':[True]}}])
def test_inconsistent_level_response_is_not_trusted_or_promoted(modules,change):
    protocol,_,_=modules
    result=protocol.checked_level({**level(protocol),**change})
    assert result['status']=='invalid_response' and result['level'] is None and not result['trusted']


def test_bridge_legacy_and_dual_use_one_process_and_preserve_exp(modules,monkeypatch):
    protocol,_,shadow=modules
    invocations=[]
    def run(command,**kwargs):
        invocations.append(command)
        response=dict(text='17[50.00%]',raw={'txts':['17[50.00%]'],'scores':[.99]})
        if '--experimental-neural-level' in command:
            assert len(protocol.unpack(kwargs['input']))==2
            response['neural_level']=level(protocol)
        else:
            assert kwargs['input'].startswith(b'\x89PNG')
        return SimpleNamespace(returncode=0,stdout=json.dumps(response).encode())
    monkeypatch.setattr(shadow.subprocess,'run',run)
    image=Image.new('RGB',(30,15))
    old=shadow.neural_line(image,Path('unused'),3)
    new=shadow.neural_line(image,Path('unused'),3,image,experimental_neural_level=True)
    assert len(invocations)==2 and 'neural_level' not in old
    assert old['raw']==new['raw'] and new['neural_level']['level']==51


def test_oversized_optional_crop_does_not_discard_safe_exp(modules,monkeypatch):
    protocol,_,shadow=modules
    def run(command,**kwargs):
        assert protocol.unpack(kwargs['input'])[1]==b''
        return SimpleNamespace(returncode=0,stdout=json.dumps(dict(text='17[50.00%]',neural_level=protocol.empty_level('missing_crop'))).encode())
    monkeypatch.setattr(shadow.subprocess,'run',run)
    result=shadow.neural_line(Image.new('RGB',(30,15)),Path('unused'),3,Image.new('RGB',(257,10)),experimental_neural_level=True)
    assert result['text']=='17[50.00%]' and result['neural_level']['status']=='invalid_crop'


@pytest.mark.parametrize('payload',[b'[]',b'null',b'{}',b'{"text":51}',b'{"text":null,"score":NaN}'])
def test_invalid_worker_json_shapes_fail_safely(modules,monkeypatch,payload):
    shadow=modules[2]
    monkeypatch.setattr(shadow.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=payload))
    with pytest.raises(CaptureError,match='invalid_neural_response'):
        shadow.neural_line(Image.new('RGB',(30,15)),Path('unused'),3)


def test_invalid_optional_response_preserves_exp_and_timeout_never_retries(modules,monkeypatch):
    shadow=modules[2]
    monkeypatch.setattr(shadow.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=b'{"text":"17[50.00%]","neural_level":{"level":51}}'))
    image=Image.new('RGB',(30,15))
    result=shadow.neural_line(image,Path('unused'),3,image,experimental_neural_level=True)
    assert result['text']=='17[50.00%]' and result['neural_level']['status']=='invalid_response'
    calls=[]
    def timeout(*args,**kwargs):
        calls.append(1); assert kwargs['timeout']==3
        raise shadow.subprocess.TimeoutExpired(args[0],3)
    monkeypatch.setattr(shadow.subprocess,'run',timeout)
    with pytest.raises(CaptureError,match='neural_timeout'):
        shadow.neural_line(image,Path('unused'),3,image,experimental_neural_level=True)
    assert calls==[1]


def test_pipeline_keeps_visual_arithmetic_freshness_and_pace_separate(modules):
    protocol,_,shadow=modules
    encoded=BytesIO(); Image.new('RGB',(100,100)).save(encoded,format='PNG')
    frame=Frame(encoded.getvalue(),1,100,'2026-01-01T00:00:00Z')
    roi=dict(regions={'exp':Region(.1,.1,.8,.4),'level':Region(.1,.5,.4,.8)})
    now=[101]
    def reader(crop,level_crop):
        return dict(text='17[50.00%]',neural_level=level(protocol))
    args=dict(locator=lambda image:[roi],read_level=lambda image:(2,[]),clock=lambda:now[0])
    result=shadow.analyze(frame,{1:15,2:34},reader,experimental_neural_level=True,**args)
    assert result['visual_level']==2 and result['neural_level']['level']==51
    assert result['level_evidence']['relation']=='agreement_not_verification'
    assert result['level_evidence']['hypotheses']['nearest_half_up']['unique_level']==2
    assert result['candidate']==[17,50.0] and result['current'] and not result['trusted']
    view=observation(result)
    assert view['neural_level']['comparison']=='conflict'
    def slow(crop,level_crop): now[0]=120; return reader(crop,level_crop)
    stale=shadow.analyze(frame,{1:15,2:34},slow,experimental_neural_level=True,**args)
    assert not stale['current'] and stale['status']=='stale_local_frame' and stale['neural_level']['level']==51
    from percentage_progress import strict_point
    row={**result,'index':1,'source':{'channel':'synthetic'},'visual_level':None,'visual_status':'unavailable'}
    assert strict_point(row)[1]=='visual_level_unavailable'


def test_missing_huds_never_launch_optional_recognition_and_flag_defaults_off(modules):
    protocol,_,shadow=modules
    args=shadow.parser().parse_args(['--channel','example','--output','private/unused.jsonl'])
    assert args.experimental_neural_level is False
    args=shadow.parser().parse_args(['--channel','example','--output','private/unused.jsonl','--experimental-neural-level'])
    assert args.experimental_neural_level is True
    encoded=BytesIO(); Image.new('RGB',(100,100)).save(encoded,format='PNG')
    frame=Frame(encoded.getvalue(),1,100,'2026-01-01T00:00:00Z')
    def forbidden(*a): pytest.fail('No HUD must not reach recognition')
    result=shadow.analyze(frame,{1:15},forbidden,experimental_neural_level=True,clock=lambda:101,locator=lambda image:[])
    assert result['neural_level']['status']=='not_run' and result['neural'] is None


def test_viewer_sanitizes_new_fields_and_keeps_tesseract_primary(modules):
    protocol,_,_=modules
    result=observation(dict(visual_level=None,neural_level={**level(protocol),'secret':'https://host?token=secret'}))
    assert result['visual_level'] is None and result['neural_level']['level']==51
    assert 'secret' not in json.dumps(result) and not result['neural_level']['trusted']
    bad=observation(dict(neural_level={**level(protocol),'text':'S1','level':51}))
    assert bad['neural_level']['status']=='invalid_response' and bad['neural_level']['level'] is None
