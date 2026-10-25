"""Retained layout pages stay in bounded workers and never cross capture attempts."""
from io import BytesIO
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

from PIL import Image
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import layout_first_hud as layout
import resident_tesseract as native
import shadow_capture as shadow
from exp_tracker.video import CaptureError,Frame,Source
from exp_tracker.recognition import ocr_engine
from tests.test_resident_tesseract import FAKE,hud_frame


LAYOUT_FAKE=FAKE.replace('    # One TSV word', '''    if psm in (100,101,102):
        if os.environ.get('LAYOUT_HANG')==str(psm): time.sleep(30)
        if os.environ.get('LAYOUT_BAD')==str(psm): send(b'[]'); continue
        token=dict(text='HP',x=width,y=pixels[0],width=1,height=1,confidence=.9)
        if psm==100:
            state=width
            reply=dict(pages=[[token],[token]],details=[dict(fallback=False)]*2)
        elif psm==101:
            token['x']=state;reply=dict(pages=[[token],[token]])
        else:reply=dict(cleared=True)
        send(json.dumps(reply).encode()); continue
    # One TSV word''')


@pytest.fixture
def fake_pool(tmp_path):
    path=tmp_path/'layout_worker.py';path.write_text(LAYOUT_FAKE)
    pool=native.TesseractPool([sys.executable,str(path)],2,timeout=.3)
    yield pool
    pool.close()


def test_leased_pages_are_exclusive_and_release_before_field_ocr(fake_pool):
    replies={};errors=[]
    def request(n):
        try:
            with fake_pool.layout_pages() as pages:
                first,_=pages.start(Image.new('L',(n+1,3)))
                full=pages.full()
                replies[n]=(first[0][0]['x'],full[0][0]['x'])
                pages.clear()
                assert pages.released
                # The context remains open during field reads, but holds no worker.
                assert fake_pool(Image.new('L',(1,1)),7)['text']==['none']
        except Exception as error:errors.append(error)
    threads=[threading.Thread(target=request,args=(n,)) for n in range(8)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(10)
    assert not errors and all(not t.is_alive() for t in threads)
    assert replies=={n:(n+1,n+1) for n in range(8)}
    assert fake_pool.idle.qsize()==2 and sum(w.starts for w in fake_pool.workers)==2


@pytest.mark.parametrize('operation',['100','101','102'])
@pytest.mark.parametrize('failure',['LAYOUT_HANG','LAYOUT_BAD'])
def test_bad_or_hung_layout_kills_worker_and_returns_lease(fake_pool,monkeypatch,operation,failure):
    monkeypatch.setenv(failure,operation)
    with pytest.raises(CaptureError):
        with fake_pool.layout_pages() as pages:
            pages.start(Image.new('L',(20,20)))
            pages.full()
    worker=fake_pool.workers[0]
    assert worker.starts==1 and worker.process is None
    assert fake_pool.idle.qsize()==2
    monkeypatch.delenv(failure)
    assert fake_pool(Image.new('L',(1,1)),7)['text']==['none']
    assert worker.starts==2


def test_unused_lease_does_not_start_or_leak_a_worker(fake_pool):
    with fake_pool.layout_pages():pass
    assert fake_pool.idle.qsize()==2 and all(w.starts==0 for w in fake_pool.workers)


def test_capture_that_never_calls_locator_still_releases_lease(fake_pool,tmp_path):
    class Session:
        source_bytes=0
        def __init__(self,*args,**kwargs):pass
        def frame(self,**kwargs):return SimpleNamespace(png=b'unused',received_at='x')
        def close(self):pass
    args=SimpleNamespace(timeout=1,max_age=1,ocr_timeout=1,ocr_python=None,save_crops=False,
        output=tmp_path/'unused.jsonl',layout_first_hud=True)
    result=shadow.capture_attempt(args,Source('file','unused'),{1:15},1,
        session_factory=Session,analyze_frame=lambda *a,**kw:dict(timings={},status='unavailable'),tesseract=fake_pool)
    assert result['status']=='unavailable' and fake_pool.idle.qsize()==2
    assert all(w.starts==0 for w in fake_pool.workers)


@pytest.fixture
def real_pool():
    pool=native.TesseractPool(native.worker_command(),1)
    try:pool.check(layout=True)
    except RuntimeError as error:pool.close();pytest.skip(str(error))
    yield pool
    pool.close()


@pytest.mark.ocr
def test_linux_compatible_worker_protocol_preserves_original_full_page_tokens(real_pool):
    for image in (hud_frame([60]),Image.new('RGB',(960,540),'black'),hud_frame([60,350])):
        with real_pool.layout_pages() as pages:
            selected,details=pages.start(image)
            actual=pages.full()
            assert len(selected)==len(details)==2
            pages.clear()
            assert real_pool.idle.qsize()==1
        expected=[]
        from exp_tracker.recognition import _tokens
        for binary,scale in layout.prepared_pages(image):
            expected.append(layout.mapped(_tokens(real_pool(binary,11)),scale))
        assert actual==expected


@pytest.mark.ocr
def test_capture_attempt_uses_worker_locator_and_keeps_field_reads_outside_lease(real_pool,tmp_path,monkeypatch):
    image=hud_frame([60]);buffer=BytesIO();image.save(buffer,'PNG')
    class Session:
        source_bytes=0
        def __init__(self,*args,**kwargs):pass
        def frame(self,**kwargs):
            import time
            return Frame(buffer.getvalue(),1,time.monotonic(),'2026-10-25T00:00:00+00:00')
        def close(self):pass
    reads=[]
    def neural(crop,*args,**kwargs):
        reads.append(crop.tobytes());return dict(text='12,345[6.78%]')
    monkeypatch.setattr(shadow,'neural_line',neural)
    def analyze(*args,**kwargs):
        def level(crop):
            assert real_pool.idle.qsize()==1
            assert ocr_engine.get() is not None
            return 42,[]
        return shadow.analyze(*args,**kwargs,read_level=level)
    args=SimpleNamespace(timeout=2,max_age=600,ocr_timeout=10,ocr_python=None,save_crops=False,
        output=tmp_path/'capture.jsonl',layout_first_hud=True)
    result=shadow.capture_attempt(args,Source('file','unused'),{42:200000},1,
        session_factory=Session,analyze_frame=analyze,tesseract=real_pool)
    assert result['candidate']==[12345,6.78] and result['visual_level']==42
    assert result['hud_layout']['path'] in ('selective','full') and len(reads)==1
    assert 2<=result['timings']['tesseract_layout_requests']<=3 and ocr_engine.get() is None


from tests.test_resident_tesseract import multi,run_main,fake_pools,headers  # noqa: E402,F401


@pytest.mark.parametrize('disabled',[False,True])
def test_coordinator_default_and_rollback_are_explicit_in_preflight_and_run_headers(multi,monkeypatch,disabled):
    made=fake_pools(monkeypatch);seen=[]
    from tests.test_multi_alpha import record
    def capture(args,*rest,**kwargs):seen.append(args.layout_first_hud);return record(rest[-1])
    monkeypatch.setattr(multi[0].shadow,'capture_attempt',capture)
    extra=['--no-layout-first-hud'] if disabled else []
    assert run_main(multi,'--resident-tesseract',*extra)==0
    assert made[0].layout_checked is (not disabled) and seen==[not disabled]*4
    found=headers(multi[1].parent/'shared.sqlite3')
    assert all(h.get('layout_first_hud',False) is (not disabled) for h in found)


def test_cached_hud_search_keeps_its_existing_locator(multi,monkeypatch):
    made=fake_pools(monkeypatch);seen=[]
    from tests.test_multi_alpha import record
    def capture(args,*rest,**kwargs):
        seen.append(args.layout_first_hud)
        assert 'analyze_frame' in kwargs
        return record(rest[-1])
    monkeypatch.setattr(multi[0].shadow,'capture_attempt',capture)
    assert run_main(multi,'--resident-tesseract','--hud-cache-seconds','60')==0
    assert made[0].layout_checked is False and seen==[False]*4
