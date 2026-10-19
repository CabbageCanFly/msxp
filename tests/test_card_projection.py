"""Optimized player cards must equal the unoptimized full-replay reference exactly."""
from contextlib import contextmanager
from datetime import datetime,timedelta
import json
from pathlib import Path

import pytest

from exp_tracker import product,shadow_grammar
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.product import refresh
from exp_tracker.store import Store
from tests.test_product import tracking,NOW
from tests.test_incremental_history import build
from tests.test_cross_level_product import SAVED


@contextmanager
def reference(monkeypatch):
    """Uncached grammar, forced re-projection and one interval collection per scope."""
    with monkeypatch.context() as m:
        m.setattr(shadow_grammar,'_interpret_memo',lambda text,complete:shadow_grammar._interpret_exp(text,source_complete=complete))
        m.setattr(product,'Projected',type('NeverReused',(list,),{}))
        original=product.recent_windows
        m.setattr(product,'recent_windows',lambda *args,collected=None,**kwargs:original(*args,**kwargs))
        yield


def same_card(d,channel,now,checkpoints,monkeypatch):
    with d.store._transaction():
        head=d.heads(channel)[0]
        fast=d.card({},head,now=now,checkpoints=checkpoints)
        with reference(monkeypatch):expected=d.card({},head,now=now)
    assert fast==expected
    assert refresh(fast[1]['player'],now=now)==refresh(expected[1]['player'],now=now)
    return fast


def test_grammar_memo_matches_the_parser_for_every_input_kind():
    for text in ('1,234[12.34%]','12.34X1','1[12.34%]1','',None,'9'*300):
        for complete in (None,True,False):
            assert shadow_grammar.interpret_exp(text,source_complete=complete)==shadow_grammar._interpret_exp(text,source_complete=complete)
    assert shadow_grammar.interpret_exp(['unhashable'])['full_exp']['classification']=='unavailable'


def test_cards_match_reference_after_every_append_and_as_windows_expire(tracking,monkeypatch):
    _,store,d=tracking;checkpoints={}
    appended=[]
    original=d.append
    def append(run,record):
        result=original(run,record)
        if record.get('type')=='attempt':
            now=datetime.fromisoformat(record.get('received_at') or record['attempted_at']);appended.append(now)
            same_card(d,'alpha',now,checkpoints,monkeypatch)
        return result
    d.append=append
    last=build(store,d,{},compare=False)
    assert len(appended)>100
    for delta in (1,11,301,3601,3901,86401):same_card(d,'alpha',last+timedelta(seconds=delta),checkpoints,monkeypatch)


@pytest.mark.parametrize('channel',['emmies','niru','telfer1'])
def test_saved_cards_match_reference(tmp_path,monkeypatch,channel):
    """Missing/malformed OCR, level-ups, quarantine, rotation, restarts and inactivity."""
    paths=sorted(Path(SAVED).glob(f'*/{channel}/**/capture.jsonl'),key=lambda p:json.loads(p.read_text().splitlines()[1])['attempted_at'])
    if not paths:pytest.skip('private saved capture unavailable')
    checkpoints={};steps=0;now=None;levels=set()
    with Store(tmp_path/'saved.sqlite3') as store:
        store.add_channel(channel);cid=store.add_character(channel,'Saved review');store.select_character(channel,cid)
        store.start_session(channel,at=datetime.fromisoformat(json.loads(paths[0].read_text().splitlines()[1])['attempted_at']))
        d=Diagnostics(store)
        for path in paths:
            records=[json.loads(s) for s in path.read_text().splitlines()];rid=records[0]['run_id'];d.begin(rid,channel,records[0])
            for r in records[1:]:
                d.append(rid,r);steps+=1
                if r['type']=='attempt':now=datetime.fromisoformat(r.get('received_at') or r['attempted_at'])
                if steps%80==0:
                    card=same_card(d,channel,now,checkpoints,monkeypatch)[1]['player']
                    levels.add((card['display_level'] or {}).get('value'))
        for delta in (0,11,3901,90001):same_card(d,channel,now+timedelta(seconds=delta),checkpoints,monkeypatch)
    assert len(levels-{None})>=1
