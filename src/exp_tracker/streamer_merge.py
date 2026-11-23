"""Explicit username merge: preserve archived evidence; never combine live OCR state machines."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time

from .character_automation import PLACEHOLDER_CHARACTER
from . import streamer_aliases, streamer_roster
from .store import Store, utc


def _digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def preview(store, source, destination, mapping):
    if not streamer_roster.ready(store):raise ValueError('database-managed streamers required')
    if any(not re.fullmatch('[a-z0-9_]{1,25}',n) for n in (source,destination)) or source==destination:
        raise ValueError('two distinct Twitch usernames required')
    aliases=streamer_aliases.load(store)
    if source in aliases:
        saved=aliases[source]
        if saved['channel']==destination and all(saved['characters'].get(str(k))==v for k,v in mapping.items()):
            return dict(duplicate=True,source=source,destination=destination)
        raise ValueError('source username already merged; use its current profile')
    if destination in aliases:raise ValueError('destination must be the current username')
    old,new=(dict(store._channel(n)) for n in (source,destination))
    chars=[dict(r) for r in store.db.execute('SELECT * FROM characters WHERE streamer_id=? ORDER BY id',(old['id'],))
        if r['label']!=PLACEHOLDER_CHARACTER]
    targets={r['id']:dict(r) for r in store.db.execute('SELECT * FROM characters WHERE streamer_id=?',(new['id'],))
        if r['label']!=PLACEHOLDER_CHARACTER}
    if store.invalidated_characters(old['id']):raise ValueError('source has invalidated characters; review them before merging')
    if not chars or new['selected_character_id'] not in targets:raise ValueError('both profiles need recognized characters; track the new username first')
    if set(mapping)-{c['id'] for c in chars}:raise ValueError('mapping contains a character outside the old profile')
    if len(set(mapping.values()))!=len(mapping):raise ValueError('duplicate destination character mapping')
    moves=[];duplicates=[]
    for char in chars:
        cid=char['id'];target=mapping.get(cid)
        if target is not None:
            if target not in targets:raise ValueError('mapped character is outside the destination profile')
            # Archived duplicates have no recoverable minute-by-minute evidence to move. Preserve their original audit.
            raw=store.db.execute('''SELECT COUNT(*) FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id
                WHERE r.character_id=?''',(cid,)).fetchone()[0]
            raw+=store.db.execute('SELECT COUNT(*) FROM observations o JOIN sessions s ON s.id=o.session_id WHERE s.character_id=?',(cid,)).fetchone()[0]
            checkpoint=store.db.execute('SELECT cutoff FROM retention_state WHERE character_id=?',(cid,)).fetchone()
            if raw or not checkpoint:raise ValueError('duplicate character still has raw evidence; this merge supports archived duplicates only')
            latest=store.db.execute('SELECT MAX(observed_at) FROM daily_character_exp WHERE character_id=?',(cid,)).fetchone()[0]
            first=store.db.execute('SELECT MIN(started_at) FROM sessions WHERE character_id=?',(target,)).fetchone()[0]
            if not latest or not first or datetime.fromisoformat(latest)>=datetime.fromisoformat(first):
                raise ValueError('duplicate histories overlap or lack dated evidence; review separately')
            levels={r['character_id']:r['level'] for r in store.db.execute(
                'SELECT character_id,level FROM character_level_guard WHERE character_id IN (?,?)',(cid,target))}
            if levels.get(cid) is not None and (levels.get(target) is None or levels[target]<levels[cid]):
                raise ValueError('destination validated level is below the archived character')
            duplicates.append(dict(id=cid,target=target,label=char['label'],daily=store.db.execute(
                'SELECT count(*) FROM daily_character_exp WHERE character_id=?',(cid,)).fetchone()[0]))
        else:
            candidates=[c['id'] for c in targets.values() if c['label'].casefold()==char['label'].casefold()]
            if candidates:
                raise ValueError(f'duplicate character {cid}; review destination IDs {candidates} and supply --map-character {cid}:DESTINATION_ID after verifying identity')
            # These records are append-only ownership evidence; refusing beats rewriting their provenance.
            for table in ('manual_corrections','character_renames','reading_batches','character_invalidations'):
                if store.db.execute(f'SELECT 1 FROM {table} WHERE character_id=? LIMIT 1',(cid,)).fetchone():
                    raise ValueError('character has ownership-bound operator audit; review separately before moving')
            moves.append(dict(id=cid,label=char['label']))
    result=dict(duplicate=False,source=source,destination=destination,source_id=old['id'],destination_id=new['id'],
        source_selected=old['selected_character_id'],destination_selected=new['selected_character_id'],moves=moves,duplicates=duplicates)
    result['fingerprint']=_digest(result)
    return result


def _paused(store, login, *, after=None):
    config=streamer_roster.entry(store,login)
    row=store.db.execute('SELECT * FROM streamer_runtime WHERE streamer_id=?',(config['streamer_id'],)).fetchone()
    now=datetime.now(timezone.utc)
    return (not config['tracking_enabled'] and row and row['state']=='paused' and row['revision']==config['revision']
        and datetime.fromisoformat(row['heartbeat_at'])>=max(after or now-timedelta(seconds=15),now-timedelta(seconds=15)))


def commit(store, plan):
    """Only drained lanes; one atomic, foreign-key-checked operation with an append-only receipt."""
    if plan.get('duplicate'):return plan
    mapping={r['id']:r['target'] for r in plan['duplicates']}
    with store._transaction():
        current=preview(store,plan['source'],plan['destination'],mapping)
        if current.get('duplicate'):return current
        if current!=plan:raise ValueError('merge preview changed; review again')
        if not all(_paused(store,n) for n in (plan['source'],plan['destination'])):
            raise ValueError('both streamer lanes must be paused and confirmed drained by the running tracker')
        for statement in streamer_aliases.DDL:store.db.execute(statement)
        store.db.execute('PRAGMA defer_foreign_keys=ON')
        old,new=plan['source_id'],plan['destination_id']
        moved={r['id'] for r in plan['moves']}
        if plan['source_selected'] in moved:store.db.execute('UPDATE streamers SET selected_character_id=NULL WHERE id=?',(old,))
        for cid in moved:
            store.db.execute('UPDATE sessions SET streamer_id=? WHERE character_id=?',(new,cid))
            store.db.execute('UPDATE diagnostic_runs SET streamer_id=? WHERE character_id=?',(new,cid))
            store.db.execute('UPDATE characters SET streamer_id=? WHERE id=?',(new,cid))
        for duplicate in plan['duplicates']:
            columns='utc_date,observed_at,level,current_exp,percentage_bp,source,level_basis,exp_basis,percentage_basis'
            store.db.execute(f'''INSERT INTO daily_character_exp SELECT ?,{columns} FROM daily_character_exp WHERE character_id=?
                ON CONFLICT(character_id,utc_date) DO UPDATE SET {','.join(c+'=excluded.'+c for c in columns.split(',') if c!='utc_date')}
                WHERE excluded.observed_at>daily_character_exp.observed_at''',(duplicate['target'],duplicate['id']))
        mapping.update({cid:cid for cid in moved})
        # Flatten older aliases when an account changes username again, including its old character links.
        for row in store.db.execute('SELECT * FROM streamer_aliases WHERE streamer_id=?',(old,)).fetchall():
            composed={k:mapping.get(v,v) for k,v in json.loads(row['character_map_json']).items()}
            store.db.execute('UPDATE streamer_aliases SET streamer_id=?,character_map_json=? WHERE source_streamer_id=?',
                (new,json.dumps(composed),row['source_streamer_id']))
        # Retire the invalid login before installing its guard; no unrelated capture settings change.
        change=streamer_roster.preview(store,dict(action='roster_update',channel=plan['source'],tracking_enabled=False,
            public_visible=False,reason='Twitch username merge'))
        streamer_roster.commit(store,change)
        store.db.execute('INSERT INTO streamer_aliases VALUES(?,?,?,?,?)',
            (old,plan['source'],new,json.dumps({str(k):v for k,v in mapping.items()}),utc()))
        store.db.execute('INSERT INTO streamer_merges(source_streamer_id,streamer_id,receipt_json,recorded_at) VALUES(?,?,?,?)',
            (old,new,json.dumps(plan),utc()))
        store.db.execute('UPDATE retention_meta SET revision=revision+1 WHERE id=1')
        if store.db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('merge foreign key check failed')
    return dict(saved=True,**plan)


def _tracking(store,login,enabled):
    if streamer_roster.entry(store,login)['tracking_enabled']==enabled:return
    plan=streamer_roster.preview(store,dict(action='roster_update',channel=login,tracking_enabled=enabled,reason='Twitch username merge lane drain'))
    streamer_roster.commit(store,plan)


def apply(database,source,destination,mapping,backup,*,timeout=180):
    """Backup, drain just these lanes, apply, then restore the surviving lane's tracking setting."""
    database=Path(database).resolve();backup=Path(backup).resolve()
    with Store(database,read_only=True) as store,store._transaction():
        initial=preview(store,source,destination,mapping)
        if initial.get('duplicate'):return initial
        restore={n:streamer_roster.entry(store,n)['tracking_enabled'] for n in (source,destination)}
    if backup==database:raise ValueError('backup must be a new, separate file')
    backup.parent.mkdir(parents=True,exist_ok=True)
    with backup.open('xb'):pass
    os.chmod(backup,0o600)
    with sqlite3.connect(database) as original,sqlite3.connect(backup) as copy:
        original.backup(copy)
        if copy.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('backup validation failed')
    saved=False
    try:
        with Store(database,allow_migration=False) as store:
            since=datetime.now(timezone.utc)
            for login in restore:_tracking(store,login,False)
            deadline=time.monotonic()+timeout
            while not all(_paused(store,n,after=since) for n in restore):
                if time.monotonic()>=deadline:raise ValueError('tracker did not confirm lane drain; merge not applied')
                time.sleep(.25)
            plan=preview(store,source,destination,mapping)
            if any(plan[k]!=initial[k] for k in ('source_id','destination_id','source_selected','destination_selected','moves','duplicates')):
                raise ValueError('characters changed while draining; merge not applied')
            result=commit(store,plan);saved=True
            return dict(result,backup=str(backup))
    finally:
        with Store(database,allow_migration=False) as store:
            for login,enabled in restore.items():
                if saved and login==source:continue
                _tracking(store,login,enabled)
