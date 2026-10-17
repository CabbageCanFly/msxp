import importlib
from decimal import Decimal
from pathlib import Path

import pytest


@pytest.fixture
def diagnostic(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'tools'))
    return importlib.import_module('infer_exp_level')


def test_unique_inference_never_uses_ocr_level(diagnostic):
    table={2:34,7:560}
    result=diagnostic.infer_levels(17,'50.00',table)
    assert result['levels']==[2] and result['unique_level']==2
    assert not result['trusted'] and not result['authoritative']
    assert diagnostic.strategies(7,result)==dict(A=7,B=2,C=7,D=None)


def test_zero_and_near_zero_remain_ambiguous(diagnostic):
    table={1:15,2:34,3:655200,4:604416}
    assert diagnostic.infer_levels(0,'0.00',table)['levels']==[1,2,3,4]
    assert diagnostic.infer_levels(1,'0.00',table)['levels']==[3,4]
    result=diagnostic.infer_levels(0,'0.00',table)
    assert diagnostic.strategies(2,result)==dict(A=2,B=None,C=2,D=None)


def test_all_matches_included_even_when_totals_repeat(diagnostic):
    result=diagnostic.infer_levels(1,'50.00',{9:2,3:2})
    assert result['status']=='ambiguous' and result['levels']==[3,9]


def test_truncation_kept_separate_and_ties_are_exact(diagnostic):
    table={1:20000}
    assert diagnostic.infer_levels(1,'0.01',table)['unique_level']==1
    assert diagnostic.infer_levels(1,'0.01',table,'truncate')['status']=='incompatible'


def test_end_of_level_diagnostic_allows_rounded_100_without_reset_inference(diagnostic):
    assert diagnostic.infer_levels(655199,'100.00',{49:655200})['levels']==[49]
    assert diagnostic.infer_levels(655200,'100.00',{49:655200})['status']=='incompatible'


@pytest.mark.parametrize('exp,percent',[(True,'1.00'),(1.0,'1.00'),(-1,'1.00'),('1','1.00'),
    (2**63,'1.00'),(1,True),(1,'NaN'),(1,float('inf')),(1,Decimal('NaN')),
    (1,'25.17%'),(1,'2.517e1'),(1,' 25.17'),(1,'25.170'),(1,'25.1'),(1,'-0.01'),
    (1,'100.01'),(1,0.001),(1,[])])
def test_invalid_inputs_not_repaired(diagnostic,exp,percent):
    assert diagnostic.infer_levels(exp,percent,{1:15})['status']=='invalid_input'


@pytest.mark.parametrize('exp,percent',[(None,'1.00'),(1,None),(None,None)])
def test_missing_inputs_are_unavailable(diagnostic,exp,percent):
    assert diagnostic.infer_levels(exp,percent,{1:15})['status']=='unavailable'


@pytest.mark.parametrize('table',[{}, {0:15},{True:15},{1:0},{1:True},{'1':15}])
def test_invalid_table_is_not_silently_ignored(diagnostic,table):
    with pytest.raises(ValueError):diagnostic.infer_levels(1,'1.00',table)


def test_fallback_is_not_independent_numeric_verification(diagnostic):
    # Synthetic source level 2 shows 17 EXP at 50%; corrupt pair 280/50 suggests 7.
    result=diagnostic.infer_levels(280,'50.00',{2:34,7:560})
    assert result['levels']==[7]
    assert diagnostic.strategies(None,result)==dict(A=None,B=7,C=7,D=None)
    assert diagnostic.strategies(7,result)==dict(A=7,B=7,C=7,D=7)
    assert diagnostic.strategies(2,result)==dict(A=2,B=7,C=2,D=None)


def test_wrong_exp_can_retain_correct_unique_level(diagnostic):
    for exp in (74050,74059):
        assert diagnostic.infer_levels(exp,'25.17',{39:266682,40:294216,41:324240})['levels']==[40]


def test_no_extrapolation_outside_supplied_table(diagnostic):
    result=diagnostic.infer_levels(345,'92.74',{2:34,7:560})
    assert result['status']=='incompatible' and result['levels']==[]
    with pytest.raises(ValueError):diagnostic.infer_levels(1,'1.00',{1:15},'choose_best')
