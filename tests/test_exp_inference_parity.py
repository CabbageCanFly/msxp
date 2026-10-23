"""Interval-based level inference must equal the per-level assess() enumeration exactly."""
from decimal import Decimal
import json
from pathlib import Path
import re

import pytest

from exp_tracker import diagnostic_evidence
from exp_tracker.exp_consistency import MODES,assess,infer_levels
from exp_tracker.exp_requirements import community_table
from tests.test_cross_level_product import SAVED


def reference(exp, percentage, requirements, mode='nearest_half_up'):
    """The previous implementation, verbatim apart from its name."""
    if mode not in MODES:
        raise ValueError('Unknown rounding hypothesis')
    if not requirements or any(type(level) is not int or level<1 or type(total) is not int or total<=0
                               for level,total in requirements.items()):
        raise ValueError('A nonempty positive integer level/requirement table is required')
    result=dict(levels=[],unique_level=None,rounding=mode,trusted=False,authoritative=False,
                exhaustive_only_within_supplied_table=True)
    if exp is None or percentage is None:
        return {**result,'status':'unavailable'}
    if (type(exp) is not int or exp<0 or exp>2**63-1 or isinstance(percentage,bool)
        or not isinstance(percentage,(int,float,str,Decimal))
        or isinstance(percentage,str) and re.fullmatch(r'[0-9]{1,3}\.[0-9]{2}',percentage) is None):
        return {**result,'status':'invalid_input'}
    levels=[]
    for level in sorted(requirements):
        check=assess(level,exp,percentage,requirements,mode)
        if check['status']=='unavailable_numeric':
            return {**result,'status':'invalid_input'}
        if check['status']=='consistent':levels.append(level)
    return {**result,'status':'unique' if len(levels)==1 else 'ambiguous' if levels else 'incompatible',
            'levels':levels,'unique_level':levels[0] if len(levels)==1 else None}


TABLE={int(k):v for k,v in community_table()[0]['to_next'].items()}
BPS=(0,1,2,49,50,51,99,100,4999,5000,5001,9949,9950,9998,9999,10000)


def boundary_exps(total):
    """EXP values at, below and above every truncate and half-up display boundary."""
    values={0,1,total-1,total,total+1,2*total}
    for bp in BPS:
        for edge in (bp*total//10000,(2*bp-1)*total//20000 if bp else 0,(2*bp+1)*total//20000,(bp+1)*total//10000):
            values.update(edge+d for d in (-1,0,1))
    return sorted(v for v in values if v>=0)


def pct(bp):
    return f'{bp//100}.{bp%100:02}'


@pytest.mark.parametrize('mode',MODES)
def test_every_supported_requirement_and_display_boundary_matches(mode):
    """Each level's membership alone, then complete outputs for the whole table."""
    checked=0
    for total in sorted(set(TABLE.values())):
        for exp in boundary_exps(total):
            for bp in BPS:
                assert infer_levels(exp,pct(bp),{1:total},mode)==reference(exp,pct(bp),{1:total},mode),(total,exp,bp)
                checked+=1
    assert checked>50000
    for total in sorted(set(TABLE.values()))[::8]:
        for exp in boundary_exps(total):
            for bp in BPS:
                assert infer_levels(exp,pct(bp),TABLE,mode)==reference(exp,pct(bp),TABLE,mode),(total,exp,bp)


@pytest.mark.parametrize('percentage',['12.34',12.5,12,Decimal('12.50'),'0.00','100.00','100.01','12.345','1,00',
    '-1.00','abc','',None,True,False,float('nan'),float('inf'),12.345,[12],Decimal('NaN'),'999.99'])
@pytest.mark.parametrize('exp',[None,0,1,1234,-1,2**63-1,2**63,1.0,True,'1234'])
def test_invalid_and_unusual_inputs_match(exp,percentage):
    for mode in MODES:
        try:expected=reference(exp,percentage,TABLE,mode)
        except Exception as error:
            with pytest.raises(type(error)):infer_levels(exp,percentage,TABLE,mode)
        else:assert infer_levels(exp,percentage,TABLE,mode)==expected


@pytest.mark.parametrize('table',[
    {3:500,1:1000,2:200},                       # Unsorted, non-monotonic requirements.
    {1:1000,2:1000,3:1000,7:999},               # Duplicate requirements: ambiguous, never merged.
    {**TABLE,**{90+i:max(TABLE.values())+1000*i for i in range(10)}},  # Disputed levels supplied.
    {5:1}])
def test_unordered_duplicate_and_extended_tables_match(table):
    # Every requirement the supported table lacks, plus a stride of the supported ones.
    totals={t for t in table.values() if t not in TABLE.values()}|set(sorted(set(TABLE.values()))[::16])
    for total in totals&set(table.values()):
        for exp in boundary_exps(total):
            for bp in BPS:
                for mode in MODES:
                    assert infer_levels(exp,pct(bp),table,mode)==reference(exp,pct(bp),table,mode)


def test_bad_tables_and_modes_are_still_rejected():
    for table in ({},{0:5},{1:0},{1:-5},{1:5.0},{'1':5},{True:5}):
        with pytest.raises(ValueError):infer_levels(1,'1.00',table)
    with pytest.raises(ValueError):infer_levels(1,'1.00',TABLE,'round')


def saved_pairs():
    pairs=set()
    for path in Path(SAVED).glob('*/*/**/capture.jsonl'):
        if path.parent.name not in ('streamer_f','streamer_e','streamer_a') and path.parents[1].name not in ('streamer_f','streamer_e','streamer_a'):continue
        for line in path.read_text().splitlines():
            record=json.loads(line);candidate=record.get('candidate')
            if record.get('type')=='attempt' and candidate:
                pairs.add((str(candidate[0]),f'{candidate[1]:.2f}'))
    return pairs


def test_exp_derived_outputs_match_for_saved_readings_and_synthetic_pairs(monkeypatch):
    pairs=saved_pairs()
    if not pairs:pytest.skip('private saved capture unavailable')
    for total in sorted(set(TABLE.values()))[::4]:
        pairs.update((str(exp),pct(bp)) for exp in boundary_exps(total)[::3] for bp in BPS)
    fast={pair:diagnostic_evidence._exp_derived.__wrapped__(*pair) for pair in pairs}
    calls=[]
    monkeypatch.setattr(diagnostic_evidence,'infer_indexed',lambda exp,percentage,index,mode:calls.append(1) or reference(exp,percentage,TABLE,mode))
    assert {pair:diagnostic_evidence._exp_derived.__wrapped__(*pair) for pair in pairs}==fast
    assert len(calls)==2*len(pairs)  # The reference really replaced the optimized path.
    statuses={value['status'] for value in fast.values()}
    assert {'unique','ambiguous','incompatible','outside_supported_coverage'}<=statuses
