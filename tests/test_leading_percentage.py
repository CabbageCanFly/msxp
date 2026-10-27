"""Bracket recovery needs a valid current capture, not prior clean percentages."""
from copy import deepcopy
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path

import pytest

from exp_tracker.diagnostic_evidence import project
from exp_tracker.diagnostic_percentage import review
from exp_tracker.diagnostic_progress import percentage_point
from exp_tracker.product import reading,history
from exp_tracker.shadow_grammar import interpret_exp,propose_full_exp
from exp_tracker.shadow_types import parse_percentage_only
from exp_tracker.store import Store
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.retention import dumps,loads
from tests.test_diagnostic_progress import row,NOW
from tests.test_numerical_windows import false_pair
from private_data import recorded


def strict(index,pct):
    return row(index,pct,visual_level=67,frame_sha256=f'{index:064x}')


def hypothesis(index,text):
    value=strict(index,'94.55')
    value.update(raw_text=text,percentage_only_candidate=None,status='malformed_or_unavailable')
    return value


def evaluate(rows,now=None):
    values=project(rows)
    now=now or datetime.fromisoformat(values[-1]['received_at'])
    decisions=review(values,[percentage_point(r) for r in values],now=now)
    for r,d in zip(values,decisions):r['percentage_review']=d
    return values


@pytest.mark.parametrize('raw,pct,edits',[
    ('155.64%1','55.64',2),('155.67%1','55.67',2),('155.84%1','55.84',2),
    ('194.55%]','94.55',1),('195.11%1','95.11',2),('158.09%I','58.09',2),
])
def test_bracket_repair_is_an_ordinary_percentage_proposal_on_the_first_capture(raw,pct,edits):
    parsed=interpret_exp(raw)
    assert parse_percentage_only(raw) is None and propose_full_exp(raw)['classification']=='rejected'
    assert not parsed['full_exp']['proposals'] and parsed['strict_percentage_only'] is None
    assert parsed['percentage']['classification']=='unique_proposal'
    proposal,=parsed['percentage']['proposals']
    assert proposal==parsed['percentage_hypotheses'][0]  # Existing crop-retry compatibility.
    assert proposal['interpretation']==f'[{pct}%]' and len(proposal['edits'])==edits
    assert 'required_context' not in proposal and parsed['raw']==raw
    rebuilt=list(raw)
    for edit in proposal['edits']:
        assert raw[edit['index']]==edit['old']
        rebuilt[edit['index']]=edit['new']
    assert ''.join(rebuilt)==proposal['interpretation']
    value=evaluate([hypothesis(1,raw)])[0]
    accepted=reading(value)
    assert accepted['percentage']==pct and accepted['exp'] is None
    assert accepted['evidence']=='grammar_recovered' and accepted['grammar_policy']=='bounded_exp_v13'
    assert value['percentage_review']['current_capture']==dict(
        policy='leading_one_percentage_v4',supported=True,required_prior_readings=0)
    assert not accepted['trusted'] and value['raw_text']==raw
    assert percentage_point(value)[0]['comparison_eligible']
    assert not interpret_exp(raw,source_complete=False)['percentage']['proposals']


@pytest.mark.parametrize('raw',[
    '0.85%1','170 57%1','1194.55%1','194,55%1','194.5%1',
    '194.55%','194.55%|','I94.55%]','100.00%1','100.00%]','194.55%1[95.00%]',
    'prefix194.55%]','1158.09%I','1,158.09%I','158.09%II','158.09%l','158.O9%I',
    'I58.09%I','158.09%I[59.00%]','1[58.09%]','158[58.09%]','1,158[58.09%]',
])
def test_bracket_rule_does_not_strip_other_numeric_prefixes_or_fill_missing_digits(raw):
    assert interpret_exp(raw)['percentage']['reason']!='leading_one_bracket_recovery'


def test_long_malformed_streak_needs_no_clean_support_and_incremental_results_match():
    rows=[hypothesis(i,f'177.{10+i:02d}%1') for i in range(1,13)]
    values=evaluate(rows)
    assert all(reading(r) is not None for r in values)
    for split in range(1,len(rows)):
        projected=project(rows);state={};now=datetime.fromisoformat(rows[-1]['received_at'])
        decisions=review(projected[:split],[percentage_point(r) for r in projected[:split]],now=now,state=state)
        state=loads(dumps(state))
        decisions+=review(projected[split:],[percentage_point(r) for r in projected[split:]],now=now,state=state)
        assert decisions==[r['percentage_review'] for r in values]


@pytest.mark.parametrize('prior',[
    dict(raw_text=None,percentage_only_candidate=None,status='unavailable',hud_count=0,fresh_at_capture=False),
    dict(raw_text='[94.47%1',percentage_only_candidate=None,status='malformed_or_unavailable'),
    dict(session_id=2),dict(source_identity='other'),dict(run_id='old-run'),
])
def test_unreadable_or_different_prior_context_does_not_block_a_valid_current_capture(prior):
    rows=[strict(1,'94.47'),hypothesis(2,'194.55%1')]
    rows[0].update(prior)
    assert reading(evaluate(rows)[-1])['percentage']=='94.55'
    rows[-1]['received_at']=(NOW+timedelta(seconds=181)).isoformat()
    assert reading(evaluate(rows)[-1])['percentage']=='94.55'


@pytest.mark.parametrize('changes',[
    dict(fresh_at_capture=False,status='stale_local_frame'),dict(capture_acquired=False),
    dict(hud_count=2),dict(crop_suspect=True),dict(local_age_seconds=16),
    dict(reading_invalidated=True),dict(timestamp_ordered=False),dict(frame_sha256=None),
    dict(character_id=None),dict(session_id=None),dict(candidate_invalid=True),
    dict(percentage_only_invalid=True),
    dict(neural_level=dict(status='numeric_candidate',text='57',level=57,score=.99,preprocessing='neutral4')),
    dict(neural_level=dict(status='numeric_candidate',text='67',level=67,score=.99,
        preprocessing='neutral4',source_complete=False)),
    dict(visual_level=None,neural_level=None),
])
def test_current_capture_safeguards_still_block_bad_evidence(changes):
    current=hypothesis(1,'194.55%1');current.update(changes)
    assert reading(evaluate([current])[-1]) is None


@pytest.mark.parametrize('duplicate',['frame','event'])
def test_duplicate_captures_are_not_accepted_as_new_percentage_evidence(duplicate):
    rows=[hypothesis(1,'194.47%1'),hypothesis(2,'194.55%1')]
    if duplicate=='frame':rows[-1]['frame_sha256']=rows[0]['frame_sha256']
    else:rows[-1]['event_id']=rows[0]['event_id']
    assert reading(evaluate(rows)[-1]) is None


def test_future_capture_is_not_accepted():
    current=hypothesis(1,'194.55%1')
    assert reading(evaluate([current],now=NOW-timedelta(seconds=1))[-1]) is None


@pytest.mark.parametrize('raw,level,allowed_level',[('118.15%1',5,70),('195.11%1',6,70),('150.00%1',70,1)])
def test_arithmetically_plausible_small_exp_prefix_is_a_real_ambiguity(raw,level,allowed_level):
    current=hypothesis(1,raw);current['visual_level']=level
    value=evaluate([current])[0]
    assert reading(value) is None
    assert value['percentage_review']['reason']=='ambiguous_exp_percentage_prefix'
    current['visual_level']=allowed_level
    assert reading(evaluate([current])[0])['percentage']==raw[1:-2]


@pytest.mark.parametrize('raw',['194.22%1','177.00%1'])
def test_bracket_recovery_does_not_bypass_decrease_or_large_jump_quarantine(raw):
    rows=[strict(1,'94.39'),strict(2,'94.47'),hypothesis(3,raw)]
    assert reading(evaluate(rows)[-1]) is None
    bad=project(false_pair())[-1]
    assert percentage_point(bad)==(None,'arithmetic_pair_veto')


def test_saved_interrupted_run_preserves_raw_evidence_and_causal_results():
    from exp_tracker.shadow_view import observation
    path=recorded('private/test-fixtures/runs/20261020T214039Z-1781b4bb/streamer_a/01f9f3a2328e42128e182408ffae84ff/capture.jsonl')
    if not path.exists():pytest.skip('Private saved source unavailable')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    records=[json.loads(line) for line in path.read_text().splitlines()];config=records[0]
    rows=[];previous=None
    for record in records[1:]:
        if record['type']!='attempt':continue
        r=observation(record);when=r['received_at'] or r['attempted_at']
        r.update(event_id=f'{config["run_id"]}:{r["index"]}',run_id=config['run_id'],
            interval_seconds=config['interval'],source_identity=config['source_identity'],
            coordinator_instance=config['coordinator_instance'],assigned_channel='streamer_a',character_id=1,session_id=1,
            hud_count=(record.get('localization') or {}).get('count'),
            capture_acquired=r['status']!='capture_failed' and r['received_at'] is not None,
            timestamp_ordered=previous is None or when>previous)
        previous=max(previous,when) if previous else when
        rows.append(r)
    values=evaluate(rows)
    assert len(values)==60 and sum(reading(r) is not None for r in values)>=51
    candidate=reading(values[36])
    assert candidate['percentage']=='59.36' and candidate['exp'] is None and not candidate['trusted']
    assert candidate['evidence']=='grammar_recovered' and values[36]['raw_text']=='159.36%1'
    assert reading(evaluate(rows[:37])[-1])==candidate
    assert values[24]['experimental_level']['value'] is None and reading(values[24]) is None
    for index,pct in ((33,'58.90'),(35,'59.14'),(38,'59.46'),(39,'59.56')):
        assert reading(values[index-1])['percentage']==pct
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest


def test_saved_run_public_availability_and_causal_prefixes(tmp_path):
    path=recorded('private/test-fixtures/runs/20261019T000710Z-bda4f628/streamer_a/capture.jsonl')
    if not path.exists():pytest.skip('Private saved source unavailable')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    with Store(tmp_path/'review.sqlite3') as store:
        store.add_channel('streamer_a');c=store.add_character('streamer_a','Saved review');store.select_character('streamer_a',c);store.start_session('streamer_a')
        d=Diagnostics(store);d.replay('streamer_a',path)
        records=[json.loads(s) for s in path.read_text().splitlines()]
        now=max(datetime.fromisoformat(r['received_at']) for r in records if r['type']=='attempt')
        snap=d.snapshot('streamer_a',now=now)
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
