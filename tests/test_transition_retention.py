"""Bounded, conservative wrap evidence using disposable synthetic observations."""
from collections import deque
from copy import deepcopy
from datetime import timedelta
import sys

import pytest

from exp_tracker.diagnostic_evidence import (TRANSITION_SAMPLES,_chain,_established,_wrap,
    _transition_step,_reader_step,level_context,project)
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.product import player
from exp_tracker.retention import checkpoint,dumps,loads,prune
from exp_tracker.store import Store
from tests.test_product import NOW,tracking
from tests.test_exp_level_inference import wrapped,only
from tests.test_diagnostic_history import config
from tests.test_retention import metrics
from tests.test_tracked_exp_totals import save


def sample(index,bp=1,exp=None,frame=None):
    return dict(event_id=f'run:{index}',timestamp=(NOW+timedelta(seconds=index*20)).isoformat(),
        frame_sha256=frame or f'{index:064x}',bp=bp,exp=exp)


def transition():
    seed=sample(0,9990,356559);before=_established(42,seed,seed['timestamp'],'exp_derived')
    wrap=sample(1)
    return dict(before,bp=1,exp=None,last_at=wrap['timestamp'],transition=_wrap(42,before,wrap,wrap['timestamp']))


def step(state,index,bp=1,**changes):
    value=sample(index,bp,**changes)
    return _transition_step(state,value,None,None,value['timestamp'])


def memory_size(value,seen=None):
    """Retained Python heap, counting shared objects once; excludes interpreter/caches."""
    if seen is None:seen=set()
    if id(value) in seen:return 0
    seen.add(id(value));size=sys.getsizeof(value)
    if isinstance(value,dict):return size+sum(memory_size(k,seen)+memory_size(v,seen) for k,v in value.items())
    if isinstance(value,(list,tuple,deque,set)):return size+sum(memory_size(v,seen) for v in value)
    return size


@pytest.mark.parametrize('provisional',[False,True])
def test_ten_thousand_unresolved_observations_bound_full_level_state(provisional,record_property):
    state={};project(wrapped() if provisional else wrapped()[:7],state=state)
    sizes=[];start=11 if provisional else 8
    for index in range(start,start+10000):
        row=only(index,'1.16' if provisional else '0.18')
        project([row],state=state)
        if index in (start+999,start+9999):
            sizes.append((len(dumps(state)),memory_size(state)))
            state=loads(dumps(state))
    tr=state['derived']['transition']
    assert tr['phase']==('provisional' if provisional else 'possible')
    assert tr['evidence_exhausted'] and len(tr['samples'])==TRANSITION_SAMPLES
    assert state['previous']['experimental_level']['level_context']['reason']=='transition_evidence_limit'
    assert len(level_context(state['derived'],row['received_at'])['transition']['samples'])==3
    assert sizes[-1][0]<25_000 and sizes[-1][1]<75_000
    assert abs(sizes[-1][0]-sizes[0][0])<200
    assert abs(sizes[-1][1]-sizes[0][1])<2000
    record_property('bytes_at_1000_and_10000',sizes)


def test_normal_flat_then_progress_and_duplicate_independence():
    state=transition()
    for index in range(2,34):
        state,value,status,_=step(state,index)
        assert value is None and status=='possible_level_up'
    state,value,status,_=step(state,34,2)
    assert (value,status)==(43,'provisional_level_up')
    assert _chain(state['transition']['samples'])
    # Reusing any earlier frame cannot supply the third independent sample, even with changed OCR.
    state=transition()
    for index in range(2,10002):
        state,value,_,_=step(state,index,2 if index>3 else 1,frame=f'{2+(index%2):064x}')
        assert value is None
    assert len(state['transition']['samples'])==2
    assert state['transition']['phase']=='possible'


def test_budget_exhaustion_withholds_progress_instead_of_recycling_evidence():
    state=transition()
    for index in range(2,TRANSITION_SAMPLES+2):state,*_=step(state,index)
    state,value,status,reason=step(state,TRANSITION_SAMPLES+2,2)
    assert value is None and status=='unavailable' and reason=='transition_evidence_limit'
    assert state['transition']['phase']=='possible' and state['transition']['evidence_exhausted']
    state=loads(dumps(state))
    state,value,_,_=step(state,TRANSITION_SAMPLES+3,3)
    assert value is None and state['transition']['phase']=='possible'
    state,value,status,reason=step(state,TRANSITION_SAMPLES+4,None)
    assert value is None and status=='unavailable' and reason=='transition_evidence_limit'


@pytest.mark.parametrize('resolution',['pair','reader','contradiction'])
def test_exhausted_transition_still_resolves_and_bounds_provenance(resolution):
    state=transition()
    for index in range(2,1002):state,*_=step(state,index)
    current=sample(1002,100,3911)
    if resolution=='reader':
        state,_=_reader_step(state,43,'agreement',current,current['timestamp'])
    elif resolution=='pair':
        state,value,_,_=_transition_step(state,current,dict(levels=[43]),43,current['timestamp'])
        assert value==43
    else:
        state,value,_,_=step(state,1002,9991)
        assert value==42
    assert state['transition'] is None
    assert state['level']==(42 if resolution=='contradiction' else 43)
    last=state['last_transition']
    assert last['phase']==('abandoned' if resolution=='contradiction' else 'corroborated')
    assert len(last['samples'])==3 and last['sample_count']==TRANSITION_SAMPLES
    assert len(dumps(state))<4000 and memory_size(state)<10_000
    assert len(level_context(state,current['timestamp'])['last_transition']['samples'])==3


def test_legacy_compaction_cannot_remove_a_numeric_veto_or_promote():
    state=transition()
    samples=[sample(i,1 if i<1000 else 2,100 if i<100 else 99 if i==100 else 101) for i in range(2,1001)]
    assert not _chain(samples)
    state['transition']['samples']=samples
    original=deepcopy(state)
    state=loads(dumps(state))
    assert len(original['transition']['samples'])==999
    # The discarded numeric decrease would make a naive shortened chain falsely pass.
    assert _chain(state['transition']['samples'])
    assert state['transition']['evidence_exhausted']
    state,value,status,_=step(state,1001,3,exp=102)
    assert value is None and status=='unavailable' and state['transition']['phase']=='possible'


def test_legacy_resolved_and_display_copies_compact_without_new_observations():
    state=transition();tr=state['transition']
    tr['samples']=[sample(i) for i in range(2,10002)]
    resolved={k:v for k,v in dict(tr,phase='corroborated').items() if k!='before'}
    saved=dict(tracked=dict(level_state=dict(derived=state)),display=dict(level_context=dict(last_transition=resolved),
        reading=dict(level=dict(evidence=dict(transition=resolved)))))
    original_size=len(dumps(saved));bounded=loads(dumps(saved))
    assert bounded['tracked']['level_state']['derived']['transition']['evidence_exhausted']
    assert len(bounded['display']['level_context']['last_transition']['samples'])==3
    assert len(dumps(bounded))<25_000 and memory_size(bounded)<100_000
    assert original_size>1_000_000
    assert len(level_context(state,sample(10002)['timestamp'])['transition']['samples'])==3
    assert loads(dumps(bounded))==bounded


def test_daily_pruning_and_cold_restarts_keep_level_exp_and_checkpoint_size(tracking,tmp_path,record_property):
    path,store,d=tracking;sizes=[]
    d.append('run',dict(type='summary',trusted=False,attempts=0,interrupted=True))
    with Store(tmp_path/'reference.sqlite3') as reference:
        store.db.backup(reference.db);golden=Diagnostics(reference)
        for day in range(4):
            with Store(path) as cold:
                current=Diagnostics(cold)
                for number in range(day*12,(day+1)*12):
                    rid=f'wrap{number}';previous=f'wrap{number-1}'
                    for target in (current,golden):
                        if number==0:target.begin(rid,'alpha',config(rid,interval=120))
                        else:target.rotate(previous,rid,'alpha',dict(type='summary',trusted=False,attempts=60,
                            interrupted=False,completion_reason='scheduled_rotation',next_run_id=rid),config(rid,previous,interval=120))
                        for i in range(1,61):
                            index=number*60+i-1;corroborate=index>=2878
                            bp=9990 if index==0 else 1000+index-2878 if corroborate else min(4,index)
                            save(target,rid,i,index*120,bp,level=43 if corroborate else 42,
                                full=index==0 or corroborate,visual_level=None)
                now=NOW+timedelta(seconds=((day+1)*720-1)*120)
                expected=metrics(golden,now)
                expected_level=golden.recent_snapshot('alpha',now=now)['observations'][-1]['experimental_level']
                if day==3:expected_player=golden.directory({},now=now)['streams'][0]['player']
                prune(cold,now=now,dry_run=False)
                with Store(path,read_only=True) as restarted:
                    resumed=Diagnostics(restarted)
                    assert metrics(resumed,now)==expected
                    assert resumed.recent_snapshot('alpha',now=now)['observations'][-1]['experimental_level']==expected_level
                    if day==3:
                        actual=resumed.directory({},now=now)['streams'][0]['player']
                        assert actual['reading']==expected_player['reading']
                        assert actual['display_level']==expected_player['display_level']
                    else:
                        assert expected_level['value'] is None and expected_level['status']=='unavailable'
                saved=checkpoint(cold,1)
                if saved.get('tracked',{}).get('level_state',{}).get('derived'):
                    tr=saved['tracked']['level_state']['derived']['transition']
                    assert tr['phase']=='provisional' and tr['evidence_exhausted']
                    sizes.append((len(dumps(saved)),memory_size(saved)))
                    assert sizes[-1][0]<300_000 and sizes[-1][1]<700_000
                assert not cold.db.execute('PRAGMA foreign_key_check').fetchall()
        assert actual['reading']['level']['value']==43 and actual['reading']['exp'] is not None
        assert expected_level['level_context']['last_transition']['phase']=='corroborated'
    # The first prefix still warms up the separate 24h fingerprint window.
    assert len(sizes)==3 and sizes[-1]==sizes[-2]
    record_property('checkpoint_serialized_and_heap_bytes',sizes)


@pytest.mark.parametrize('provisional',[False,True])
@pytest.mark.parametrize('resolution',['pair','reader'])
def test_public_and_tracked_current_level_filters_respect_exhaustion(tracking,provisional,resolution):
    _,_,d=tracking
    d.append('run',dict(type='summary',trusted=False,attempts=0,interrupted=True))

    def append(index,bp,*,level=42,full=False,reader=False):
        number=index//60;rid=f'filter{number}'
        if index==0:d.begin(rid,'alpha',config(rid,interval=20))
        elif index%60==0:
            previous=f'filter{number-1}'
            d.rotate(previous,rid,'alpha',dict(type='summary',trusted=False,attempts=60,
                interrupted=False,completion_reason='scheduled_rotation',next_run_id=rid),config(rid,previous,interval=20))
        changes=dict(visual_level=level if reader else None)
        if reader:changes['neural_level']=dict(level=level,text=str(level),status='numeric_candidate',score=.99)
        save(d,rid,index%60+1,index*20,bp,level=level,full=full,**changes)

    def output(index):
        now=NOW+timedelta(seconds=index*20)
        shown=player(d.snapshot('alpha',now=now,limit=640),now=now,recent_snapshot=d.recent_snapshot('alpha',now=now))
        return shown,d.rolling_history('alpha',now=now)

    for index in range(3):append(index,9900+5*index,full=True)
    append(3,1)
    for index in range(4,68):append(index,min(3,index-3) if provisional else 1)
    shown,before=output(67)
    phase='provisional' if provisional else 'possible'
    assert shown['level_context']['transition']['phase']==phase
    assert not shown['level_context']['transition'].get('evidence_exhausted')
    assert before['current_level']==43  # Preserve the ordinary possible-candidate filter.
    if not provisional:
        assert shown['display_level']['value']==42
        assert shown['current_level_windows']['30']['gain'] is None
        assert before['current_level_windows']['30']['gain'] is None

    append(68,3 if provisional else 1)
    shown,exhausted=output(68)
    assert shown['level_context']['transition']['phase']==phase
    assert shown['level_context']['transition']['evidence_exhausted']
    selected=43 if provisional else 42
    assert shown['display_level']['value']==selected
    assert exhausted['current_level']==selected
    assert exhausted['tracked_exp']==before['tracked_exp']
    for windows in (shown['current_level_windows'],exhausted['current_level_windows']):
        assert windows['30']['gain'] is not None
    assert shown['current_level_windows']['30']['pace']['level']==selected
    assert exhausted['current_level_windows']['30']['level']==selected
    for minutes in ('5','10','15','30','60'):
        assert shown['current_level_windows'][minutes]['gain']==exhausted['current_level_windows'][minutes]['gain']
    assert {g['level'] for g in exhausted['current_level_chart_intervals']}=={selected}

    for index in (69,70):append(index,100+index-69,level=43,full=resolution=='pair',reader=resolution=='reader')
    shown,corroborated=output(70)
    assert shown['level_context']['transition'] is None
    assert shown['level_context']['last_transition']['phase']=='corroborated'
    assert shown['display_level']['value']==corroborated['current_level']==43
    for minutes in ('5','10','15','30','60'):
        public_window=shown['current_level_windows'][minutes]
        tracked_window=corroborated['current_level_windows'][minutes]
        assert public_window['gain']==tracked_window['gain']
        assert public_window['gain']['approximate']>0
        assert public_window['pace']['level']==tracked_window['level']==43
    assert {g['level'] for g in corroborated['current_level_chart_intervals']}=={43}
