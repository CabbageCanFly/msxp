import csv
import importlib
import json
from pathlib import Path

from PIL import Image, ImageDraw
import pytest


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'tools'))
    return importlib.import_module('shadow_review')


def run_fixture(root, name='one', texts=None, missing=()):
    texts = texts or ['100[25.00%]', '100[25.00%]', '100[25.00%]']
    base = root/'private'/name
    base.mkdir(parents=True)
    crops = base/'crops'
    rows = [dict(type='configuration', count=len(texts), interval=15)]
    for index, text in enumerate(texts, 1):
        if index not in missing:
            for field in ('exp','level'):
                directory = crops/f'{index:04d}'
                directory.mkdir(parents=True, exist_ok=True)
                image = Image.new('RGB', (100,16) if field=='exp' else (35,20), '#121212')
                ImageDraw.Draw(image).text((2,2), '100[25.00%]' if field=='exp' else '2', fill='white')
                image.save(directory/f'{field}.png')
        rows.append(dict(type='attempt', index=index, status='capture_failed' if index in missing else 'diagnostic_pair',
            frame_sha256=None if index in missing else 'same-frame' if index<=2 else 'different-frame',
            attempted_at=f'2026-01-01T00:00:{index*15:02d}Z',
            localization=None if index in missing else dict(count=1),
            candidate=None if text is None else [100,25.0], visual_level=None if index in missing else 2,
            neural=dict(text=text,raw=dict(scores=[.99])), level_evidence=dict(hypotheses={
                'nearest_half_up':dict(status='unique',levels=[2]),
                'truncate':dict(status='ambiguous',levels=[2,3])})))
    rows.append(dict(type='summary', attempts=len(texts), interrupted=False))
    log = base/'capture.jsonl'
    log.write_text(''.join(json.dumps(row)+'\n' for row in rows), encoding='utf-8')
    return log,crops


def submissions(workflow, directory, manifest, unknown=()):
    answers = directory/'completed.csv'
    with answers.open('w',newline='',encoding='utf-8') as handle:
        writer=csv.writer(handle)
        writer.writerow(['id','exp','percentage','level','note'])
        for entry in manifest['entries']:
            unavailable = entry['exp_crop'] is None or entry['id'] in unknown
            writer.writerow([entry['id'], 'unknown' if unavailable else '100',
                             'ambiguous' if unavailable else '25.00',
                             'unknown' if entry['level_crop'] is None else '2', 'synthetic references'])
    provenance=directory/'provenance.json'
    provenance.write_text(json.dumps(dict(reviewer='Synthetic test',method='practice_mechanics',
        saved_predictions_seen=True,arithmetic_or_neighbor_values_used=False,prior_material_seen=True,
        independently_reviewed=False,independent_reviewer='',notes='test only')))
    return answers,provenance


def test_ordering_repeats_without_predictions_or_paths(workflow,tmp_path):
    first=run_fixture(tmp_path,'one')
    second=run_fixture(tmp_path,'two')
    a=workflow.prepare([first,second],tmp_path/'private/a',seed=7)
    b=workflow.prepare([first,second],tmp_path/'private/b',seed=7)
    assert [(v['stream'],v['index']) for v in a['entries']]==[(v['stream'],v['index']) for v in b['entries']]
    assert [v['id'] for v in a['entries']]==[f'R{i:03d}' for i in range(1,7)]
    c=workflow.shuffled(a['entries'],8)
    assert [v['index'] for v in c]!=[v['index'] for v in a['entries']]
    assert all(not {'candidate','neural','level_evidence'} & row.keys() for row in a['entries'])
    for filename in ['sheet-01.png','pixels/R001-exp.png']:
        assert workflow.digest(tmp_path/'private/a/review'/filename)==workflow.digest(tmp_path/'private/b/review'/filename)


def test_failed_attempt_and_missing_crops_stay_selected(workflow,tmp_path):
    log,crops=run_fixture(tmp_path,missing=(2,))
    manifest=workflow.prepare([(log,crops)],tmp_path/'private/eval')
    assert len(manifest['entries'])==3
    failed=next(row for row in manifest['entries'] if row['index']==2)
    assert failed['exp_crop'] is None and failed['level_crop'] is None
    assert not failed['identity_verified'] and not failed['main_hud_verified']
    assert (tmp_path/'private/eval/review/sheet-01.png').exists()


def test_freeze_before_evaluate_and_never_overwrite(workflow,tmp_path):
    directory=tmp_path/'private/eval'
    manifest=workflow.prepare([run_fixture(tmp_path)],directory,practice=True)
    with pytest.raises(OSError):workflow.evaluate(directory,directory/'before.json')
    answers,meta=submissions(workflow,directory,manifest)
    frozen=workflow.freeze(directory,answers,meta)
    assert frozen['practice_only'] and frozen['answers_sha256']==workflow.digest(answers)
    assert frozen['answers_text']==answers.read_text()
    assert 'not authenticated' in frozen['provenance_verification']
    with pytest.raises(ValueError,match='already frozen'):workflow.freeze(directory,answers,meta)
    result=workflow.evaluate(directory,directory/'result.json')
    assert result['practice_only'] and not result['independently_validated'] and not result['trusted']
    with pytest.raises(ValueError,match='already exists'):workflow.evaluate(directory,directory/'result.json')


@pytest.mark.parametrize('fault',['empty','missing_id','duplicate_id','reordered','bad_comma','bad_percent','negative','level_zero','extra_column'])
def test_incomplete_or_malformed_answers_stop_without_reference_file(workflow,tmp_path,fault):
    directory=tmp_path/'private/eval'
    manifest=workflow.prepare([run_fixture(tmp_path)],directory)
    answers,meta=submissions(workflow,directory,manifest)
    rows=list(csv.reader(answers.read_text().splitlines()))
    if fault=='empty':rows[1][1]=''
    elif fault=='missing_id':rows.pop()
    elif fault=='duplicate_id':rows[2][0]=rows[1][0]
    elif fault=='reordered':rows[1],rows[2]=rows[2],rows[1]
    elif fault=='bad_comma':rows[1][1]='10,0'
    elif fault=='bad_percent':rows[1][2]='25.001'
    elif fault=='negative':rows[1][1]='-1'
    elif fault=='level_zero':rows[1][3]='0'
    else:rows[1].append('extra')
    with answers.open('w',newline='') as handle:csv.writer(handle).writerows(rows)
    with pytest.raises(ValueError):workflow.freeze(directory,answers,meta)
    assert not (directory/'references.json').exists()


@pytest.mark.parametrize('target',['source','crop','sheet','manifest','references'])
def test_changed_frozen_evidence_is_refused(workflow,tmp_path,target):
    directory=tmp_path/'private/eval'
    run=run_fixture(tmp_path)
    manifest=workflow.prepare([run],directory)
    answers,meta=submissions(workflow,directory,manifest)
    workflow.freeze(directory,answers,meta)
    path={'source':run[0],'crop':run[1]/'0001/exp.png','sheet':directory/'review/sheet-01.png',
          'manifest':directory/'manifest.json','references':directory/'references.json'}[target]
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError):workflow.evaluate(directory,directory/'result.json')


def test_denominators_unknowns_malformed_outputs_and_visual_abstention(workflow,tmp_path):
    directory=tmp_path/'private/eval'
    run=run_fixture(tmp_path,texts=['100[25.00%]','100[25.00%1',None],missing=(3,))
    manifest=workflow.prepare([run],directory)
    answers,meta=submissions(workflow,directory,manifest)
    workflow.freeze(directory,answers,meta)
    result=workflow.evaluate(directory,directory/'result.json')
    stream=result['streams']['S01']
    assert stream['denominator']==3 and stream['capture']=={'available':2,'failed':1}
    assert stream['metrics']['pair']['agreement']==1
    assert stream['metrics']['pair']['unavailable']==1 and stream['metrics']['pair']['unknown_truth']==1
    assert stream['metrics']['pair']['output_available']==1 and stream['metrics']['pair']['known_truth']==2
    assert stream['arithmetic']['nearest_half_up']['unique_agreement']==1
    assert stream['arithmetic']['truncate']['ambiguous']==1
    assert len(stream['malformed_outputs'])==1
    assert stream['duplicate_full_frames'] and stream['duplicate_exp_pixels']
    for metric in stream['metrics'].values():
        assert sum(metric[key] for key in ('agreement','disagreement','unavailable','unknown_truth'))==3


def test_wrong_pair_with_partial_truth_is_flagged_not_called_correct(workflow,tmp_path):
    directory=tmp_path/'private/eval'
    manifest=workflow.prepare([run_fixture(tmp_path,texts=['101[25.00%]'])],directory)
    answers,meta=submissions(workflow,directory,manifest)
    # Keep known EXP 100 while percentage is explicitly unresolved.
    answers.write_text(answers.read_text().replace(',100,25.00,',',100,ambiguous,'))
    workflow.freeze(directory,answers,meta)
    result=workflow.evaluate(directory,directory/'result.json')
    assert result['streams']['S01']['metrics']['pair']['unknown_truth']==1
    assert len(result['streams']['S01']['wrong_complete_pairs'])==1
    assert result['results'][0]['raw_text']=='101[25.00%]'
    assert result['results'][0]['saved_candidate']==[100,25.0]
    assert result['results'][0]['saved_candidate_disagreement']


def test_unknown_truth_is_not_agreement_and_duplicate_frames_not_removed(workflow,tmp_path):
    directory=tmp_path/'private/eval'
    manifest=workflow.prepare([run_fixture(tmp_path)],directory)
    answers,meta=submissions(workflow,directory,manifest,unknown=[v['id'] for v in manifest['entries']])
    workflow.freeze(directory,answers,meta)
    stream=workflow.evaluate(directory,directory/'result.json')['streams']['S01']
    assert stream['metrics']['pair']['unknown_truth']==3 and stream['metrics']['pair']['agreement']==0
    assert stream['metrics']['pair']['output_available']==3 and stream['denominator']==3
    assert len(stream['duplicate_full_frames'][0])==2


def test_predicates_are_not_used_to_select_review_frames(workflow,tmp_path):
    run=run_fixture(tmp_path)
    first=workflow.prepare([run],tmp_path/'private/a',seed=9)
    lines=[json.loads(row) for row in run[0].read_text().splitlines()]
    for row in lines[1:-1]:row['neural']['text']='999[99.99%]'
    run[0].write_text(''.join(json.dumps(row)+'\n' for row in lines))
    second=workflow.prepare([run],tmp_path/'private/b',seed=9)
    assert [(r['stream'],r['index']) for r in first['entries']]==[(r['stream'],r['index']) for r in second['entries']]


def test_incomplete_capture_and_public_output_are_rejected(workflow,tmp_path):
    log,crops=run_fixture(tmp_path)
    log.write_bytes(log.read_bytes().rstrip(b'\n'))
    with pytest.raises(ValueError,match='Incomplete log tail'):workflow.prepare([(log,crops)],tmp_path/'private/eval')
    with pytest.raises(ValueError,match='private/ or artifacts/'):workflow.prepare([(log,crops)],tmp_path/'public')


def test_provenance_needs_explicit_flags_and_independent_reviewer(workflow,tmp_path):
    directory=tmp_path/'private/eval'
    manifest=workflow.prepare([run_fixture(tmp_path)],directory)
    answers,meta=submissions(workflow,directory,manifest)
    provenance=json.loads(meta.read_text());provenance['independently_reviewed']=True
    meta.write_text(json.dumps(provenance))
    with pytest.raises(ValueError,match='second reviewer'):workflow.freeze(directory,answers,meta)


def test_explicit_unknowns_and_numeric_grammar(workflow):
    assert workflow.reference('ambiguous','exp')['value'] is None
    assert workflow.reference('unknown','level')['status']=='unknown'
    assert workflow.reference('1,234','exp')['value']==1234
    assert workflow.reference('100.00','percentage')['value']=='100.00'
    for field,value in [('percentage','100.01'),('exp','9223372036854775808'),('exp','100?')]:
        with pytest.raises(ValueError):workflow.reference(value,field)


def test_stream_denominators_and_arithmetic_disagreements_stay_separate(workflow,tmp_path):
    first=run_fixture(tmp_path,'first',texts=['100[25.00%]'])
    second=run_fixture(tmp_path,'second',texts=['100[25.00%]','100[25.00%]'])
    rows=[json.loads(line) for line in first[0].read_text().splitlines()]
    rows[1]['visual_level']=3
    rows[1]['level_evidence']['hypotheses']['nearest_half_up']['levels']=[3]
    first[0].write_text(''.join(json.dumps(row)+'\n' for row in rows))
    directory=tmp_path/'private/eval'
    manifest=workflow.prepare([first,second],directory)
    answers,meta=submissions(workflow,directory,manifest)
    workflow.freeze(directory,answers,meta)
    streams=workflow.evaluate(directory,directory/'result.json')['streams']
    assert streams['S01']['denominator']==1 and streams['S02']['denominator']==2
    assert streams['S01']['metrics']['visual_level']['disagreement']==1
    assert streams['S01']['arithmetic']['nearest_half_up']=={'unique_disagreement':1}
    assert streams['S02']['arithmetic']['nearest_half_up']=={'unique_agreement':2}
