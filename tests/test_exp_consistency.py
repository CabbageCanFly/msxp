"""Arithmetic and diagnostic boundaries; no private data or OCR dependencies."""

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def checker(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'tools'))
    return importlib.import_module('check_exp_consistency')


@pytest.mark.parametrize('mode',['nearest_half_up','truncate'])
def test_large_digit_error_exceeds_requirement(checker, mode):
    assert checker.assess(6,345,'92.74',{6:372},mode)['status']=='consistent'
    result=checker.assess(6,2345,'92.74',{6:372},mode)
    assert result['status']=='inconsistent' and result['reason']=='exp_outside_level_or_transition'
    assert result['trusted'] is False and result['authoritative'] is False


def test_higher_level_quantization_cannot_verify_last_digits(checker):
    for exp in (74050,74059):
        result=checker.assess(40,exp,'25.17',{40:294216},'nearest_half_up')
        assert result['status']=='consistent'
        assert result['exp_bin']==dict(min=74040,max=74068,count=29)
    assert checker.assess(40,74050,'25.17',{40:294216},'truncate')['status']=='inconsistent'


def test_rounding_is_not_chosen_to_fit_candidate(checker):
    assert checker.assess(9,1241,'99.92',{9:1242},'nearest_half_up')['status']=='consistent'
    assert checker.assess(9,1241,'99.92',{9:1242},'truncate')['status']=='inconsistent'
    for mode in ('nearest_half_up','truncate'):
        assert checker.assess(9,1241,'99.82',{9:1242},mode)['status']=='inconsistent'


@pytest.mark.parametrize('level,exp,percentage,status',[
    (None,5,'50.00','unavailable_level'),(50,5,'50.00','unavailable_requirement'),
    (True,5,'50.00','invalid_level'),(0,5,'50.00','invalid_level'),
    (1,None,'0.00','unavailable_numeric'),(1,False,'0.00','unavailable_numeric'),
    (1,0,None,'unavailable_numeric'),(1,1,'1.234','unavailable_numeric'),
    (1,1,'NaN','unavailable_numeric'),(1,1,'Infinity','unavailable_numeric'),
    (1,1,'100.01','unavailable_numeric'),(1,-1,'0.00','unavailable_numeric')])
def test_unavailable_and_invalid_data_are_not_repaired(checker, level, exp, percentage, status):
    assert checker.assess(level,exp,percentage,{1:15},'nearest_half_up')['status']==status


def test_zero_exp_does_not_verify_level_or_character(checker):
    for level in (1,40):
        assert checker.assess(level,0,'0.00',{1:15,40:294216},'nearest_half_up')['status']=='consistent'


def test_halfway_and_upper_boundary_arithmetic_are_explicit(checker):
    tied=checker.assess(1,1,'0.01',{1:20000},'nearest_half_up')
    assert tied['status']=='consistent' and tied['exact_halfway']
    # A rounded 100% can be below a level boundary; this does not change OCR guards.
    assert checker.assess(1,99999,'100.00',{1:100000},'nearest_half_up')['status']=='consistent'
    assert checker.assess(1,100000,'100.00',{1:100000},'nearest_half_up')['status']=='inconsistent'


@pytest.mark.parametrize('mode',['nearest_half_up','truncate'])
def test_integer_bins_match_exhaustive_synthetic_percentages(checker, mode):
    for total in (7,32,101):
        for exp in range(total):
            bp=(10000*exp//total if mode=='truncate' else (20000*exp+total)//(2*total))
            result=checker.assess(1,exp,f'{bp//100}.{bp%100:02}',{1:total},mode)
            compatible=[e for e in range(total) if (10000*e//total if mode=='truncate' else (20000*e+total)//(2*total))==bp]
            assert result['status']=='consistent'
            assert result['exp_bin']==dict(min=min(compatible),max=max(compatible),count=len(compatible))


def test_bad_configuration_fails(checker):
    with pytest.raises(ValueError): checker.assess(1,0,'0.00',{1:0},'truncate')
    with pytest.raises(ValueError): checker.assess(1,0,'0.00',{1:15},'guess')


def test_saved_raw_text_is_not_repaired_or_joined_with_labels(checker):
    records=[dict(id=str(i),seconds=i,scale=2,mode='line_recognize',text=text,expected={'level':1})
             for i,text in enumerate(['1[6.67%]','1[6.67%1','1[6.67%','116.67%]'])]
    levels={str(i):dict(tesseract=None,pixel=1) for i in range(4)}
    missing=checker.evaluate(records,levels,{1:15},'tesseract','nearest_half_up')
    assert missing['summary']['candidate_statuses']==dict(unavailable_level=1)
    pixel=checker.evaluate(records,levels,{1:15},'pixel','nearest_half_up')
    assert pixel['summary']['consistent_unique']==1 and pixel['summary']['unavailable_pairs']==3
    assert [r['raw_text'] for r in pixel['records']]==[r['text'] for r in records]
    assert all(not r['check']['trusted'] for r in pixel['records'])
    with pytest.raises(ValueError): checker.evaluate(records,{}, {1:15},'pixel','truncate')
