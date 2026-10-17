import importlib
from pathlib import Path

import pytest


@pytest.fixture
def answers(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'tools'))
    return importlib.import_module('blinded_answers')


def fixture_text():
    parts=[]
    for stage in (1,2):
        parts.append(f'pass {stage}')
        for page in range(1,5):
            parts.append(f'review-{page:02d}.png')
            parts.extend('lvl 2; 1,234'+('; 12.30%' if stage==2 else '') for _ in range(6))
    return '\n'.join(parts)


def test_exact_page_order_and_lossless_provenance(answers):
    rows=answers.parse_answers(fixture_text())
    assert [r['id'] for r in rows]==[f'H{i:02d}' for i in range(1,25)]
    assert rows[6]['sheet']=='review-02.png' and rows[-1]['row']==6
    assert rows[0]['percentage']=='12.30' and rows[0]['current_exp']==1234
    assert rows[0]['pass1']['raw_line']=='lvl 2; 1,234'


@pytest.mark.parametrize('fault',['missing','extra','sheet_order','duplicate_pass','pass_disagreement',
    'comma','decimal','unknown','level','negative','extra_digit','percentage'])
def test_ambiguous_or_changed_answers_stop(answers,fault):
    text=fixture_text()
    if fault=='missing':text=text.rsplit('\n',1)[0]
    elif fault=='extra':text+='\nlvl 2; 1,234; 12.30%'
    elif fault=='sheet_order':text=text.replace('review-01.png','review-02.png',1)
    elif fault=='duplicate_pass':text=text.replace('pass 2','pass 1')
    elif fault=='pass_disagreement':text=text.replace('lvl 2; 1,234; 12.30%','lvl 2; 1,235; 12.30%',1)
    elif fault=='comma':text=text.replace('1,234','12,34')
    elif fault=='decimal':text=text.replace('12.30%','1230%')
    elif fault=='unknown':text=text.replace('1,234','uncertain',1)
    elif fault=='level':text=text.replace('lvl 2','lvl 301',1)
    elif fault=='negative':text=text.replace('1,234','-1234',1)
    elif fault=='extra_digit':text=text.replace('1,234','99999999999999999999999',1)
    else:text=text.replace('12.30%','100.00%')
    with pytest.raises(ValueError):answers.parse_answers(text)
