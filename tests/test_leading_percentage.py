"""Leading-one hypotheses require causal, independent percentage-only context."""
from copy import deepcopy
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path

import pytest

from exp_tracker.diagnostic_evidence import project
from exp_tracker.diagnostic_percentage import review
from exp_tracker.diagnostic_progress import progress,percentage_point
from exp_tracker.product import reading,history
from exp_tracker.shadow_grammar import interpret_exp,propose_full_exp
from exp_tracker.shadow_types import parse_percentage_only
from exp_tracker.store import Store
from exp_tracker.diagnostics import Diagnostics
from tests.test_diagnostic_progress import row,NOW
from tests.test_numerical_windows import false_pair


def strict(index,pct):
    return row(index,pct,visual_level=67,frame_sha256=f'{index:064x}')


def hypothesis(index,text):
    value=strict(index,'94.55')
    value.update(raw_text=text,percentage_only_candidate=None,status='malformed_or_unavailable')
    return value


def evaluate(rows):
    values=project(rows);now=datetime.fromisoformat(values[-1]['received_at'])
    decisions=review(values,[percentage_point(r) for r in values],now=now)
    for r,d in zip(values,decisions):r['percentage_review']=d
    return values


@pytest.mark.parametrize('raw,pct,edits',[('194.55%]','94.55',1),('195.11%1','95.11',2),('196.00%]','96.00',1)])
def test_unique_but_review_only_hypothesis_does_not_replace_a_strict_parser(raw,pct,edits):
    parsed=interpret_exp(raw)
    assert parse_percentage_only(raw) is None and propose_full_exp(raw)['classification']=='rejected'
    assert not parsed['full_exp']['proposals'] and not parsed['percentage']['proposals']
    assert parsed['percentage']['classification']=='review_only'
    proposal=parsed['percentage_hypotheses'][0]
    assert proposal['interpretation']==f'[{pct}%]' and len(proposal['edits'])==edits
    assert proposal['required_context']=='two_prior_strict_percentage_only' and not proposal['trusted']
    assert not proposal['numerical_identity_verified']
    assert reading(project([hypothesis(1,raw)])[0]) is None
    assert not interpret_exp(raw,source_complete=False)['percentage_hypotheses']


@pytest.mark.parametrize('raw',['0.85%1','170 57%1','1194.55%1','194,55%1','194.5%1',
    '194.55%','194.55%|','I94.55%]','100.00%1','100.00%]','194.55%1[95.00%]', 'prefix194.55%]'])
def test_no_unrestricted_numeric_prefix_stripping_or_extra_punctuation_repairs(raw):
    assert not interpret_exp(raw)['percentage_hypotheses']


def test_two_prior_strict_percentage_fields_make_a_causal_experimental_point():
    rows=[strict(1,'94.39'),strict(2,'94.47'),hypothesis(3,'194.55%]')];original=deepcopy(rows)
    values=evaluate(rows);last=values[-1]
    assert last['percentage_review']['public_eligible'] and last['percentage_review']['progress_eligible']
    assert last['percentage_review']['percentage_only_context']['support_event_ids']==['run:1','run:2']
    value=reading(last)
    assert value['percentage']=='94.55' and value['exp'] is None and value['evidence']=='grammar_recovered'
    assert last['raw_text']=='194.55%]' and rows==original
    assert not value['trusted'] and value['grammar_policy']=='bounded_exp_v6'
    assert percentage_point(last)[0]['comparison_eligible']
    # Streaming history pages preserve exactly the same causal format context.
    state={};projected=project(rows)
    first=review(projected[:2],[percentage_point(r) for r in projected[:2]],now=NOW+timedelta(seconds=30),state=state)
    second=review(projected[2:],[percentage_point(projected[2])],now=NOW+timedelta(seconds=30),state=state)
    assert first+second==[r['percentage_review'] for r in values]


@pytest.mark.parametrize('kind',['none','one','full_pair','recovered','missing','duplicate','stale','conflict',
    'level_change','session','source','restart','expired','missing_index'])
def test_missing_or_unsafe_mode_context_remains_review_only(kind):
    rows=[strict(1,'94.39'),strict(2,'94.47'),hypothesis(3,'194.55%]')]
    if kind=='none':rows=rows[2:]
    elif kind=='one':rows=rows[1:]
    elif kind=='full_pair':rows[1].update(raw_text='1,660,000[94.47%]',candidate=dict(exp='1660000',percentage='94.47'),percentage_only_candidate=None,status='diagnostic_pair')
    elif kind=='recovered':rows[1].update(raw_text='94.47%1',percentage_only_candidate=None,status='malformed_or_unavailable')
    elif kind=='missing':rows[1].update(raw_text=None,percentage_only_candidate=None,status='unavailable',hud_count=0,fresh_at_capture=False)
    elif kind=='duplicate':rows[2]['frame_sha256']=rows[1]['frame_sha256']
    elif kind=='stale':rows[2].update(status='stale_local_frame',fresh_at_capture=False)
    elif kind=='conflict':rows[2]['neural_level']=dict(status='numeric_candidate',text='57',level=57,score=.99,preprocessing='neutral4')
    elif kind=='level_change':rows[2]['visual_level']=68
    elif kind=='session':rows[2]['session_id']=2
    elif kind=='source':rows[2]['source_identity']='new-source'
    elif kind=='restart':rows[2].update(run_id='new',index=1,event_id='new:1')
    elif kind=='expired':rows[2]['received_at']=(NOW+timedelta(seconds=150)).isoformat()
    else:rows[2]['index']=4
    last=evaluate(rows)[-1]
    assert not last['percentage_review']['public_eligible'] and reading(last) is None


def test_hypotheses_cannot_self_seed_or_override_percentage_quarantine():
    rows=[strict(1,'94.39'),strict(2,'94.47'),hypothesis(3,'194.55%]'),hypothesis(4,'194.62%]')]
    values=evaluate(rows)
    assert reading(values[2]) and reading(values[3]) is None
    rows[-2]=hypothesis(3,'194.22%1')
    values=evaluate(rows[:3])
    assert values[-1]['percentage_review']['status']=='pending_exp_decrease' and reading(values[-1]) is None
    # Syntax/context are not independent proof of numerical identity.
    rows[-2]=hypothesis(3,'194.56%1')
    value=reading(evaluate(rows[:3])[-1])
    assert value['percentage']=='94.56' and not value['trusted']
    bad=project(false_pair())[-1]
    assert percentage_point(bad)==(None,'arithmetic_pair_veto')


def test_saved_run_public_availability_and_causal_prefixes(tmp_path):
    path=Path('private/multi-alpha/runs/20261019T000710Z-bda4f628/telfer1/capture.jsonl')
    if not path.exists():pytest.skip('Private saved source unavailable')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    with Store(tmp_path/'review.sqlite3') as store:
        store.add_channel('telfer1');c=store.add_character('telfer1','Saved review');store.select_character('telfer1',c);store.start_session('telfer1')
        d=Diagnostics(store);d.replay('telfer1',path)
        records=[json.loads(s) for s in path.read_text().splitlines()]
        now=max(datetime.fromisoformat(r['received_at']) for r in records if r['type']=='attempt')
        snap=d.snapshot('telfer1',now=now)
        assert len(snap['observations'])==35
        assert sum(bool(r['percentage_only_candidate']) for r in snap['observations'])==31
        assert sum(reading(r) is not None for r in snap['observations'])==35
        assert sum(r['percentage_review']['progress_eligible'] for r in snap['observations'])==35
        assert sum(p['reading'] is not None for p in history(snap))==35
        for index,pct in ((4,'94.55'),(12,'95.11'),(24,'96.00')):
            current=snap['observations'][index-1]
            assert reading(current)['percentage']==pct and reading(current)['exp'] is None
            prefix=evaluate(snap['observations'][:index])
            assert reading(prefix[-1])==reading(current)  # No later captures used.
        assert not store.db.execute('select 1 from observations').fetchone()
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
