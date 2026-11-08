"""Synthetic glyph calibration and actual capture/attribution boundaries."""
from copy import deepcopy
import json

from PIL import Image, ImageDraw
import pytest

from exp_tracker import name_glyphs as glyphs
from exp_tracker.character_automation import name_evidence
from tests.test_autonomous_characters import auto, sequence, record, config  # noqa: F401


@pytest.fixture
def calibrated(monkeypatch):
    shapes = {}
    for char,size in [('0',(7,13)),('O',(10,12))]:
        im = Image.new('L',size)
        ImageDraw.Draw(im).rectangle((0,0,size[0]-1,size[1]-1),outline=255,width=2)
        width = round(im.width*16/im.height)
        normalized = Image.new('L',(24,20))
        normalized.paste(im.resize((width,16),Image.Resampling.BILINEAR),((24-width)//2,2))
        shapes[char] = (im,normalized)
    monkeypatch.setattr(glyphs,'bank',lambda:('synthetic',{c:v[1] for c,v in shapes.items()}))
    def crop(text):
        im = Image.new('RGB',(186,25));x = 6
        for c in text:
            patch = shapes[c][0] if c in shapes else Image.new('L',(6,13),255)
            im.paste(patch.convert('RGB'),(x,5));x += patch.width+3
        return im
    return crop


def test_only_zero_letter_slots_change_and_proof_revalidates(calibrated):
    for actual,raw in [('Ax00','AxOO'),('Ax0O','AxO0'),('AxO0','Ax0O')]:
        proof = glyphs.refine(calibrated(actual),raw)
        assert glyphs.validated(raw,proof) == actual
        assert glyphs.validated('BxOO',proof) is None
    assert glyphs.refine(calibrated('AxOO'),'AxOO') is None
    assert glyphs.refine(calibrated('Ax00'),'Ax00') is None
    assert glyphs.refine(calibrated('Ax00'),'AxOOO') is None
    assert glyphs.refine(Image.new('RGB',(186,25)),'AxOO') is None


@pytest.mark.parametrize('score,eligible',[(.74,False),(.75,True),(.83,True),(.99,True)])
def test_raw_score_and_text_are_retained_and_quality_is_guarded(calibrated,score,eligible):
    value = record(1,'AxOO',score=score)
    evidence = value['character_name']['evidence']
    evidence.update(name='Ax00',glyph_refinement=glyphs.refine(calibrated('Ax00'),'AxOO'))
    before = deepcopy(value)
    assert bool(name_evidence(value)) is eligible
    assert value == before and evidence['raw']['raw']['txts'] == ['AxOO'] and evidence['score'] == score


@pytest.mark.parametrize('damage',['pixels','position','bank','missing','other_letter','score','stale','multiple_huds'])
def test_forged_or_unsafe_correction_cannot_vote(calibrated,damage):
    value = record(1,'AxOO',score=.83);e = value['character_name']['evidence']
    e.update(name='Ax00',glyph_refinement=glyphs.refine(calibrated('Ax00'),'AxOO'))
    if damage == 'pixels':e['glyph_refinement']['slots'][0]['pixels'] = '00'*480
    if damage == 'position':e['glyph_refinement']['slots'][0]['index'] = 0
    if damage == 'bank':e['glyph_refinement']['bank_sha256'] = 'other'
    if damage == 'missing':e.pop('glyph_refinement')
    if damage == 'other_letter':e['name'] = 'Bx00'
    if damage == 'score':e['raw']['raw']['scores'] = [.99]
    if damage == 'stale':value['current'] = False
    if damage == 'multiple_huds':value['localization']['count'] = 2
    assert name_evidence(value) is None


def test_missing_bank_keeps_baseline(calibrated,monkeypatch):
    image = calibrated('Ax00');monkeypatch.setattr(glyphs,'bank',lambda:None)
    assert glyphs.refine(image,'AxOO') is None
    assert glyphs.validated('AxOO',{}) is None
    assert name_evidence(record(1,'AxOO',score=.83)) is None
    assert name_evidence(record(1,'AxOO',score=.99))['name'] == 'AxOO'


@pytest.mark.parametrize('reference',[None,'Ax00'])
def test_capture_retains_raw_and_skips_unneeded_known_name_retry(calibrated,monkeypatch,reference):
    import character_identity
    from tests.test_character_identity import make_frame, candidate, response
    monkeypatch.setattr(character_identity,'name_region',lambda *_:dict(box=[10,10,196,35]))
    state = character_identity.IdentityCapture('alpha',confirmed=reference)
    state.job = state.job_seen = 'Cleric'
    frame = make_frame(0);image = frame.image();image.paste(calibrated('Ax00'),(10,10));calls = []
    def read(crop):
        calls.append(crop);result = response('AxOO');result['raw']['scores'] = [.83];return result
    value = state.inspect(dict(current=True),frame,image,candidate(),read,{},max_age=15,clock=lambda:101)
    e = value['evidence']
    assert len(calls) == 1 and e['name'] == 'Ax00' and e['score'] == .83
    assert e['raw']['raw']['txts'] == ['AxOO'] and glyphs.validated('AxOO',e['glyph_refinement']) == 'Ax00'
    assert not value['reading_hold_recommended']


def test_two_corrected_frames_select_exact_name_without_an_ocr_alias(auto,calibrated):
    _,store,policy = auto
    proof = glyphs.refine(calibrated('Ax00'),'AxOO')
    run = 'first';receipts = []
    for i in (1,2):
        value = record(i,'AxOO',score=.83)
        value['character_name']['evidence'].update(name='Ax00',glyph_refinement=proof)
        receipt = policy.append(run,value,f'next{i}',config(f'next{i}'));receipts.append(receipt);run = receipt['run_id']
    assert [r['switched'] for r in receipts] == [False,True]
    assert receipts[-1]['name'] == 'Ax00'
    assert [r[0] for r in store.db.execute('select label from characters order by id')] == ['Alpha','Ax00']
    rows = [json.loads(r[0]) for r in store.db.execute('select payload_json from diagnostic_attempts')]
    assert all(r.get('identity_hold',{}).get('evidence',r)['character_name']['evidence']['raw']['raw']['txts'] == ['AxOO'] for r in rows)
