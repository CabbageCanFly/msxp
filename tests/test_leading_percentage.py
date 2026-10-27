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
from private_data import recorded


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


@pytest.mark.parametrize('raw,pct,edits',[('194.55%]','94.55',1),('195.11%1','95.11',2),('196.00%]','96.00',1),
    ('159.36%1','59.36',2),('158.09%I','58.09',2)])
def test_unique_but_review_only_hypothesis_does_not_replace_a_strict_parser(raw,pct,edits):
    parsed=interpret_exp(raw)
    assert parse_percentage_only(raw) is None and propose_full_exp(raw)['classification']=='rejected'
    assert not parsed['full_exp']['proposals'] and not parsed['percentage']['proposals']
    assert parsed['percentage']['classification']=='review_only'
    proposal=parsed['percentage_hypotheses'][0]
    assert proposal['interpretation']==f'[{pct}%]' and len(proposal['edits'])==edits
    assert parsed['raw']==raw
    rebuilt=list(raw)
    for edit in proposal['edits']:
        assert raw[edit['index']]==edit['old']
        rebuilt[edit['index']]=edit['new']
    assert ''.join(rebuilt)==proposal['interpretation']
    assert proposal['required_context']=='two_prior_strict_percentage_only' and not proposal['trusted']
    assert not proposal['numerical_identity_verified']
    assert reading(project([hypothesis(1,raw)])[0]) is None
    assert not interpret_exp(raw,source_complete=False)['percentage_hypotheses']


@pytest.mark.parametrize('raw',['0.85%1','170 57%1','1194.55%1','194,55%1','194.5%1',
    '194.55%','194.55%|','I94.55%]','100.00%1','100.00%]','194.55%1[95.00%]', 'prefix194.55%]',
    '1158.09%I','1,158.09%I','158.09%II','158.09%l','158.O9%I','I58.09%I','158.09%I[59.00%]',
    '1[58.09%]','158[58.09%]','1,158[58.09%]'])
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
    assert not value['trusted'] and value['grammar_policy']=='bounded_exp_v12'
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
    elif kind=='expired':rows[2]['received_at']=(NOW+timedelta(seconds=181)).isoformat()
    else:rows[2]['index']=4
    last=evaluate(rows)[-1]
    assert not last['percentage_review']['public_eligible'] and reading(last) is None


def test_recoveries_reuse_original_strict_support_without_self_seeding_or_overriding_quarantine():
    rows=[strict(1,'94.39'),strict(2,'94.47'),hypothesis(3,'194.55%]'),hypothesis(4,'194.62%]')]
    values=evaluate(rows)
    assert reading(values[2]) and reading(values[3])
    assert values[3]['percentage_review']['percentage_only_context']['support_event_ids']==['run:1','run:2']
    assert reading(evaluate([hypothesis(1,'194.55%]'),hypothesis(2,'194.62%]')])[-1]) is None
    rows[-2]=hypothesis(3,'194.22%1')
    values=evaluate(rows[:3])
    assert values[-1]['percentage_review']['status']=='pending_exp_decrease' and reading(values[-1]) is None
    # Syntax/context are not independent proof of numerical identity.
    rows[-2]=hypothesis(3,'194.56%1')
    value=reading(evaluate(rows[:3])[-1])
    assert value['percentage']=='94.56' and not value['trusted']
    bad=project(false_pair())[-1]
    assert percentage_point(bad)==(None,'arithmetic_pair_veto')


def test_consecutive_recovery_retains_original_expiry_and_incremental_results():
    rows=[strict(1,'77.10'),strict(2,'77.10')]+[hypothesis(i,f'177.{10+i}%1') for i in range(3,7)]
    values=evaluate(rows)
    assert [reading(r) is not None for r in values]==[True]*5+[False]
    for value in values[2:5]:
        assert value['percentage_review']['percentage_only_context']['support_event_ids']==['run:1','run:2']
    for split in range(1,len(rows)):
        projected=project(rows);state={};now=datetime.fromisoformat(rows[-1]['received_at'])
        decisions=review(projected[:split],[percentage_point(r) for r in projected[:split]],now=now,state=state)
        decisions+=review(projected[split:],[percentage_point(r) for r in projected[split:]],now=now,state=state)
        assert decisions==[r['percentage_review'] for r in values]
    rows=rows[:4]
    rows[-1]['received_at']=(NOW+timedelta(seconds=181)).isoformat()
    assert reading(evaluate(rows)[-1]) is None


@pytest.mark.parametrize('closing',['1','|',')'])
def test_literal_opening_bracket_recovery_preserves_original_support_without_renewing_it(closing):
    rows=[strict(1,'77.10'),strict(2,'77.11'),hypothesis(3,f'[77.12%{closing}'),
        hypothesis(4,'177.13%1'),hypothesis(5,'177.14%1'),hypothesis(6,'177.15%1')]
    values=evaluate(rows)
    assert [reading(r) is not None for r in values]==[True]*5+[False]
    for r in values[3:5]:
        assert r['percentage_review']['percentage_only_context']['support_event_ids']==['run:1','run:2']
        assert r['percentage_review']['percentage_only_context']['policy']=='leading_one_percentage_v3'
    for split in range(1,len(rows)):
        projected=project(rows);state={};now=datetime.fromisoformat(rows[-1]['received_at'])
        decisions=review(projected[:split],[percentage_point(r) for r in projected[:split]],now=now,state=state)
        decisions+=review(projected[split:],[percentage_point(r) for r in projected[split:]],now=now,state=state)
        assert decisions==[r['percentage_review'] for r in values]
    expired=deepcopy(rows[:4]);expired[-1]['received_at']=(NOW+timedelta(seconds=181)).isoformat()
    assert reading(evaluate(expired)[-1]) is None


@pytest.mark.parametrize('supports',[0,1])
def test_closing_bracket_recovery_cannot_supply_missing_strict_support(supports):
    rows=[strict(1,'77.10')] if supports else [hypothesis(1,'[77.10%1')]
    rows += [hypothesis(2,'[77.11%1'),hypothesis(3,'177.12%1')]
    assert reading(evaluate(rows)[-1]) is None


@pytest.mark.parametrize('change',[
    dict(session_id=2),dict(character_id=2),dict(source_identity='other'),dict(visual_level=68),
    dict(crop_suspect=True),dict(local_age_seconds=16),dict(hud_count=2),
    dict(frame_sha256=f'{2:064x}'),dict(reading_invalidated=True),
    dict(raw_text='[77.00%1'),dict(raw_text='[97.00%1'),dict(raw_text='77.12%1'),
    dict(raw_text='P[77.12%]'),dict(raw_text='[77.1S%]'),
])
def test_closing_bracket_recovery_cannot_preserve_support_through_unsafe_or_other_formats(change):
    rows=[strict(1,'77.10'),strict(2,'77.11'),hypothesis(3,'[77.12%1'),hypothesis(4,'177.13%1')]
    rows[2].update(change)
    assert reading(evaluate(rows)[-1]) is None


@pytest.mark.parametrize('change',[
    dict(session_id=2),dict(character_id=2),dict(source_identity='other'),dict(visual_level=68),
    dict(crop_suspect=True),dict(local_age_seconds=16),dict(hud_count=2),
    dict(frame_sha256=f'{3:064x}'),dict(reading_invalidated=True),
    dict(raw_text='177.00%1'),dict(raw_text='197.00%1'),
])
def test_recovery_sequence_cannot_bridge_conflicts_or_unsafe_frames(change):
    rows=[strict(1,'77.10'),strict(2,'77.11'),hypothesis(3,'177.12%1'),
        hypothesis(4,'177.13%1'),hypothesis(5,'177.14%1')]
    rows[3].update(change)
    values=evaluate(rows)
    assert reading(values[2]) is not None and reading(values[-1]) is None


def interrupted_context():
    rows=[strict(1,'58.90'),hypothesis(2,'[59.02%\u3011'),strict(3,'59.14'),
        hypothesis(4,None),hypothesis(5,'159.36%1')]
    rows[3].update(status='unavailable',reasons=['missing_hud'],hud_count=0,
        fresh_at_capture=False,visual_level=None)
    for r,seconds in zip(rows,(0,37.796404,78.086715,121.753101,156.765062)):
        r['received_at']=(NOW+timedelta(seconds=seconds)).isoformat()
    return rows


@pytest.mark.parametrize('malformed',[None,'[59.02%\u3011'])
def test_two_strict_supports_survive_two_bounded_unreadable_attempts(malformed):
    rows=interrupted_context();rows[1]['raw_text']=malformed;original=deepcopy(rows)
    values=evaluate(rows);last=values[-1]
    assert last['percentage_review']['percentage_only_context']['support_event_ids']==['run:1','run:3']
    assert reading(last)['percentage']=='59.36' and reading(last)['exp'] is None
    assert reading(last)['evidence']=='grammar_recovered' and not reading(last)['trusted']
    assert not values[1]['percentage_review']['public_eligible'] and not values[3]['percentage_review']['public_eligible']
    assert last['raw_text']=='159.36%1' and rows==original
    # A page can end on either unreadable capture without losing the causal guards.
    for split in range(1,len(rows)):
        projected=project(rows);state={};now=datetime.fromisoformat(rows[-1]['received_at'])
        decisions=review(projected[:split],[percentage_point(r) for r in projected[:split]],now=now,state=state)
        decisions+=review(projected[split:],[percentage_point(r) for r in projected[split:]],now=now,state=state)
        assert decisions==[r['percentage_review'] for r in values]


@pytest.mark.parametrize('seconds,eligible',[(180,True),(180.000001,False)])
def test_interrupted_context_time_limit(seconds,eligible):
    rows=interrupted_context();rows[-1]['received_at']=(NOW+timedelta(seconds=seconds)).isoformat()
    assert (reading(evaluate(rows)[-1]) is not None) is eligible


def test_three_unreadable_attempts_exceed_the_attempt_window():
    rows=interrupted_context()
    extra=hypothesis(5,None);extra['received_at']=(NOW+timedelta(seconds=140)).isoformat()
    rows.insert(4,extra);rows[-1].update(index=6,event_id='run:6',frame_sha256=f'{6:064x}')
    assert reading(evaluate(rows)[-1]) is None


@pytest.mark.parametrize('change',[
    dict(session_id=2),dict(character_id=2),dict(source_identity='different'),dict(channel='other'),
    dict(source_kind='file'),dict(run_id='other'),dict(manual_epoch=1),dict(visual_level=68),
    dict(neural_level=dict(status='numeric_candidate',text='68',level=68,score=.99,preprocessing='neutral4')),
    dict(status='stale_local_frame',fresh_at_capture=False),dict(fresh_at_capture=False),
    dict(capture_acquired=False),dict(frame_sha256=None),dict(frame_sha256=f'{1:064x}'),
    dict(crop_suspect=True),dict(hud_count=2),dict(timestamp_ordered=False),dict(local_age_seconds=16),
    dict(received_at=None),dict(received_at=(NOW-timedelta(seconds=1)).isoformat()),
    dict(received_at=(NOW+timedelta(seconds=200)).isoformat()),dict(timing_mode='simulated'),
    dict(candidate_invalid=True),dict(percentage_only_invalid=True),dict(reading_invalidated=True),
    dict(neural_level=dict(source_complete=False)),dict(index=8),dict(event_id='run:1'),
])
def test_unsafe_intervening_capture_cannot_be_skipped(change):
    rows=interrupted_context();rows[1].update(change)
    assert reading(evaluate(rows)[-1]) is None


@pytest.mark.parametrize('text',['159.00%1','169.36%1','149.36%1','1,234[59.36%]','1159.36%1'])
def test_interrupted_recovery_cannot_override_progression_or_strip_numeric_prefixes(text):
    rows=interrupted_context();rows[-1]['raw_text']=text
    assert reading(evaluate(rows)[-1]) is None


@pytest.mark.parametrize('percentage',['59.40','79.00','58.00'])
def test_intervening_valid_contradictory_reading_resets_support(percentage):
    rows=interrupted_context();rows[1]=strict(2,percentage)
    assert reading(evaluate(rows)[-1]) is None


def test_intervening_whole_pair_arithmetic_conflict_is_not_an_unreadable_gap():
    rows=interrupted_context()
    for r in rows:r.update(index=r['index']+1,event_id=f'run:{r["index"]+1}',frame_sha256=f'{r["index"]+1:064x}')
    rows.insert(0,strict(1,'58.80'))
    rows[0]['received_at']=(NOW-timedelta(seconds=15)).isoformat()
    for r in rows[:2]:
        r['neural_level']=dict(status='numeric_candidate',text='67',level=67,score=.99,preprocessing='neutral4')
    rows[2].update(raw_text='100[59.02%]',candidate=dict(exp='100',percentage='59.02'),
        status='diagnostic_pair')
    assert percentage_point(project(rows)[2])[1]=='arithmetic_pair_veto'
    assert reading(evaluate(rows)[-1]) is None


def test_terminal_capital_i_requires_the_same_supported_level_and_strict_context():
    rows=[strict(1,'57.89'),strict(2,'57.98'),hypothesis(3,'158.09%I')]
    assert reading(evaluate(rows)[-1])['percentage']=='58.09'
    for prefix in (rows[1:],rows[2:]):assert reading(evaluate(prefix)[-1]) is None
    rows[-1]['visual_level']=None
    last=evaluate(rows)[-1]
    assert last['experimental_level']['value'] is None and reading(last) is None


@pytest.mark.parametrize('index',[1,3])
def test_hypothesis_cannot_reuse_an_intervening_unreadable_frame(index):
    rows=interrupted_context();rows[-1]['frame_sha256']=rows[index]['frame_sha256']
    assert reading(evaluate(rows)[-1]) is None


@pytest.mark.parametrize('change',[
    dict(session_id=2),dict(source_identity='other'),dict(visual_level=68),dict(crop_suspect=True),
    dict(frame_sha256=f'{3:064x}'),dict(status='stale_local_frame'),dict(local_age_seconds=16),
    dict(reasons=['stale_local_frame']),dict(hud_count=2),dict(reading_invalidated=True),
])
def test_missing_hud_gap_after_both_supports_still_checks_capture_safety(change):
    rows=interrupted_context();rows[3].update(change)
    assert reading(evaluate(rows)[-1]) is None


def test_saved_interrupted_run_read_only_projection_and_causal_prefixes():
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
    assert len(values)==60 and sum(reading(r) is not None for r in values)==50
    last=values[36];candidate=reading(last)
    assert candidate['percentage']=='59.36' and candidate['exp'] is None and not candidate['trusted']
    assert candidate['evidence']=='grammar_recovered' and last['raw_text']=='159.36%1'
    assert last['percentage_review']['percentage_only_context']['support_event_ids']==[
        f'{config["run_id"]}:33',f'{config["run_id"]}:35']
    assert reading(evaluate(rows[:37])[-1])==candidate
    earlier=values[24]
    assert interpret_exp(earlier['raw_text'])['percentage_hypotheses'][0]['reading']['percentage']=='58.09'
    assert earlier['experimental_level']['value'] is None and reading(earlier) is None
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
