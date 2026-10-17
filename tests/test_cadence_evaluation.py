"""Synthetic availability evidence is never trusted observation eligibility."""
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def audit(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'tools'))
    return importlib.import_module('evaluate_cadence')


def rows(count):
    return [dict(seconds=i*15) for i in range(count)]


def test_interruption_uses_elapsed_endpoints_not_missing_count(audit):
    result=audit.coverage(rows(5),[True,False,False,True,True])
    assert result['success_endpoint_gaps_seconds']==[45,15]
    interruption=result['runs'][1]
    assert interruption==dict(available=False,start=15,end=30,samples=2,
                             sample_span_seconds=15,boundary_censored=False)


@pytest.mark.parametrize('count,gaps',[(9,0),(10,1)])
def test_120_seconds_is_timing_only_and_not_automatically_bridgeable(audit,count,gaps):
    result=audit.coverage(rows(count),[True]+[False]*(count-2)+[True])
    assert result['gaps_over_120_seconds']==gaps
    assert 'does not authorize bridging' in result['note']


def test_censored_empty_and_all_missing_windows(audit):
    assert audit.coverage([],[])['longest_success_endpoint_gap_seconds'] is None
    result=audit.coverage(rows(3),[False]*3)
    assert result['runs'][0]['boundary_censored']
    assert result['runs'][0]['sample_span_seconds']==30
    assert result['longest_success_endpoint_gap_seconds'] is None


def test_duplicate_or_irregular_timestamps_are_rejected(audit):
    with pytest.raises(ValueError):audit.coverage([dict(seconds=0)]*2,[True]*2)
    with pytest.raises(ValueError):audit.coverage(rows(2),[True])


def inputs():
    items=[dict(id=f'cadence/{i}',seconds=i*15,window='a' if i<2 else 'b',
        pre_review=i==0,level=6,current_exp=10,percentage=20,image_sha256=str(i)) for i in range(3)]
    locations=[dict(id=e['id'],seconds=e['seconds'],location='main',level=6) for e in items]
    neural=[dict(id=e['id'],seconds=e['seconds'],text='10[20.00%]',missing_crop=False,
                 mode='line_recognize',scale=2,padding_pixels=2) for e in items]
    return dict(examples=items),dict(records=locations),dict(records=neural)


def test_unreviewed_rows_never_become_accuracy_and_windows_stay_separate(audit):
    result=audit.analyze(*inputs())
    assert not result['trusted'] and not result['human_verified_accuracy_available']
    assert result['windows']['a']['provisional_comparisons']['pair']==dict(match=1,unreviewed=1)
    assert result['windows']['b']['temporal']['edges']==[]


def test_wrong_hud_is_not_main_availability(audit):
    manifest,locations,neural=inputs()
    locations['records'][0]['location']='wrong_secondary'
    result=audit.analyze(manifest,locations,neural)['windows']['a']
    assert result['temporal']['complete']==2
    assert result['pair_coverage']['runs'][0]['available'] is False
    assert result['location_counts']['wrong_secondary']==1


def test_malformed_and_missing_level_never_form_triples(audit):
    manifest,locations,neural=inputs()
    neural['records'][0]['text']='10[20.00%1'
    locations['records'][1]['level']=None
    result=audit.analyze(manifest,locations,neural)['windows']['a']
    assert result['temporal']['complete']==1 and result['temporal']['malformed']==1
    assert result['raw_triples']==0


def test_level_changes_and_decreases_are_diagnostics_without_gains(audit):
    manifest,locations,neural=inputs()
    neural['records'][1]['text']='9[19.00%]'
    result=audit.analyze(manifest,locations,neural)['windows']['a']
    assert result['diagnostic_flags'][0]['kind']=='same_level_decrease_unresolved'
    locations['records'][1]['level']=7
    result=audit.analyze(manifest,locations,neural)['windows']['a']
    assert result['diagnostic_flags'][0]['kind']=='level_changed_not_verified_transition'
    assert 'gained_exp' not in str(result)


@pytest.mark.parametrize('fault',['id','duplicate','time','variant'])
def test_incompatible_saved_evidence_is_rejected(audit,fault):
    manifest,locations,neural=inputs()
    if fault=='id':neural['records'].pop()
    elif fault=='duplicate':neural['records'].append(neural['records'][0])
    elif fault=='time':neural['records'][0]['seconds']=1
    else:neural['records'][0]['scale']=1
    with pytest.raises(ValueError):audit.analyze(manifest,locations,neural)
