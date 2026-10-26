"""Compact saved-stream regressions through the real tracker; no network or database."""
from datetime import datetime,timezone
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'samples/live-regression/manifest.json'
OCR=ROOT/'private/rapidocr/.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
pytestmark=[pytest.mark.samples,pytest.mark.ocr]


def cases():
    if not MANIFEST.is_file():
        return [pytest.param(None,id='private-live-captures',marks=pytest.mark.skip(reason='Run msxp test-data to restore private live regressions'))]
    data=json.loads(MANIFEST.read_text(encoding='utf-8'))
    assert data['version']==1 and data['frames']
    return [pytest.param(frame,id=frame['id']) for frame in data['frames']]


@pytest.fixture(scope='module')
def readers():
    if not OCR.is_file():pytest.skip('Private OCR environment absent (msxp install)')
    sys.path.insert(0,str(ROOT/'tools'))
    from resident_tesseract import TesseractPool,worker_command
    from shadow_capture import ResidentNeural
    pool=TesseractPool(worker_command(),1);resident=ResidentNeural()
    try:
        pool.check(layout=True)
        requirements=json.loads((ROOT/'src/exp_tracker/data/community-exp-v2.json').read_text())['to_next']
        yield pool,resident,{int(k):v for k,v in requirements.items()}
    finally:
        resident.close();pool.close()


@pytest.mark.parametrize('case',cases())
def test_saved_stream_recognition_and_rejection(readers,case):
    from character_identity import IdentityCapture
    from exp_tracker.character_automation import name_evidence
    from exp_tracker.shadow_grammar import interpret_exp
    from exp_tracker.video import Frame,Source
    from restore_test_data import inside
    from shadow_capture import capture_attempt
    path=inside(ROOT,case['path'])
    if not path.is_file():pytest.skip('Private frame absent (msxp test-data)')
    with Image.open(path) as image:
        encoded=BytesIO();image.convert('RGB').save(encoded,'PNG',compress_level=1)
    class Session:
        source_bytes=0
        def __init__(self,*a,**kw):pass
        def frame(self,**kw):return Frame(encoded.getvalue(),1,time.monotonic(),datetime.now(timezone.utc).isoformat())
        def close(self):pass
    expected=case['expected'];pool,resident,requirements=readers
    identity=IdentityCapture('streamer_a',confirmed=expected.get('confirmed_name')) if 'name' in expected else None
    args=SimpleNamespace(timeout=10,max_age=600,ocr_timeout=30,ocr_python=OCR,save_crops=False,
        output=ROOT/'private/not-written.jsonl',experimental_neural_level=True,layout_first_hud=True)
    result=capture_attempt(args,Source('file',str(path)),requirements,1,session_factory=Session,
        resident=resident,tesseract=pool,identity=identity)
    if 'reject' in expected:
        assert result['reasons']==[expected['reject']]
        assert result['candidate'] is None and result['percentage_only_candidate'] is None
        count=result['localization']['count']
        assert count==0 if expected['reject']=='missing_hud' else count>=2
        return
    assert result['localization']['count']==1 and result['current']
    if 'percentage' in expected:
        neural=result.get('neural') or {}
        parsed=interpret_exp(neural.get('text'),source_complete=neural.get('source_complete'))
        kind='full_exp' if expected.get('exp') is not None else 'percentage'
        field=parsed['strict_full' if kind=='full_exp' else 'strict_percentage_only']
        if field is None:
            proposal=parsed[kind]
            assert proposal['classification']=='unique_proposal' and len(proposal['proposals'])==1
            assert not proposal['proposals'][0].get('required_context')
            field=proposal['proposals'][0]['reading']
        assert float(field['percentage'])==expected['percentage']
        if kind=='full_exp':assert int(field['exp'])==expected['exp']
    if 'level' in expected:
        assert (result.get('neural_level') or {}).get('level')==expected['level']
    if 'name' in expected:
        evidence=result['character_name']['evidence']
        assert evidence['name']==expected['name']
        if expected.get('discovery_name'):assert name_evidence(result)['name']==expected['name']
        if 'job' in expected:
            assert evidence['job']['job']==expected['job'] and evidence['job']['score']>=.9
