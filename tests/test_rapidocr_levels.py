import importlib
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest


@pytest.fixture
def levels(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'tools'))
    return importlib.import_module('benchmark_rapidocr_levels')


@pytest.mark.parametrize('text', ['S1','S 1','5 1','LV51','5I','5l','051','0','201','５１','51%','51.0',None,''])
def test_only_whole_numeric_levels_no_repair(levels,text):
    assert levels.numeric_level(text) is None


@pytest.mark.parametrize('text,value',[('51',51),('63',63),('40',40),(' 9 ',9),('200',200)])
def test_numeric_levels_are_candidates_not_proof(levels,text,value):
    assert levels.numeric_level(text)==value
    assert levels.score(text,value)=='correct_numeric'
    assert levels.score(text,value,negative=True)=='unsafe_numeric_on_negative'


def test_wrong_numeric_and_nonnumeric_outcomes_stay_distinct(levels):
    assert levels.score('3',8)=='incorrect_numeric'
    assert levels.score('S1',51)=='nonnumeric'
    assert levels.score(None,51)=='no_output'
    assert levels.score('51',None)=='unknown_reference'
    assert levels.score('201',51)=='out_of_range_or_malformed_numeric'
    assert levels.agreement(['51','S1']) is None
    assert levels.agreement(['51','1']) is None
    assert levels.agreement(['51','51'])==51  # Correlated agreement can still be wrong.


def test_predeclared_geometry_and_min_rgb_preserve_source(levels):
    source=Image.new('RGB',(3,2),(240,140,20)); source.putpixel((1,1),(200,210,220))
    before=source.tobytes()
    assert levels.preprocess(source,'rgb2').size==(6,4)
    assert levels.preprocess(source,'rgb4').size==(12,8)
    expected=Image.new('RGB',source.size,(235,235,235)); expected.putpixel((1,1),(55,55,55))
    assert levels.preprocess(source,'neutral4').tobytes()==expected.resize((12,8),Image.Resampling.BICUBIC).tobytes()
    assert source.tobytes()==before
    with pytest.raises(ValueError):
        levels.preprocess(source,'threshold_sweep')


def test_recognition_only_records_original_text_and_scores(levels):
    calls=[]
    def engine(image,**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(txts=['S 1'],scores=[.99],boxes=None,elapse=.01,elapse_list=None)
    result=levels.infer(engine,Image.new('RGB',(10,10)))
    assert calls==[dict(use_det=False,use_cls=False,use_rec=True)]
    assert result['raw']['txts']==['S 1'] and result['raw']['scores']==[.99]
    assert result['numeric_level'] is None and not result['trusted']
    def ambiguous(image,**kwargs):
        return SimpleNamespace(txts=['5','1'],scores=[.99,.99])
    assert levels.infer(ambiguous,Image.new('RGB',(10,10)))['text'] is None
    with pytest.raises(RuntimeError,match='existing local'):
        levels.forbid_download('not_permitted')


def test_receipts_allow_code_inputs_but_refuse_changes_and_escape(levels,tmp_path,monkeypatch):
    import hashlib
    monkeypatch.chdir(tmp_path)
    code=tmp_path/'tools.py'; code.write_text('synthetic code')
    level_crop=tmp_path/'private'; level_crop.mkdir()
    levels.check_inputs({'tools.py':hashlib.sha256(code.read_bytes()).hexdigest()})
    with pytest.raises(ValueError,match='changed'):
        levels.check_inputs({'tools.py':'incorrect'})
    with pytest.raises(ValueError,match='escapes'):
        levels.check_inputs({'../outside':'not_read'})
