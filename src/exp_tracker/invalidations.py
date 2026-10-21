"""Append-only reading exclusions. Source OCR and original stored gains are never edited."""
from datetime import datetime
import hashlib
import json
import re

from .store import utc

PAGE = 50
MAX_SELECTION = 20000
WRITE_CHUNK = 250
DIAGNOSTIC_TIME="CASE WHEN LENGTH(COALESCE(a.received_at,a.attempted_at))=25 THEN SUBSTR(COALESCE(a.received_at,a.attempted_at),1,19)||'.000000+00:00' ELSE COALESCE(a.received_at,a.attempted_at) END"


def validate_reason(reason):
    if reason is not None and (not isinstance(reason,str) or not reason.strip() or len(reason)>1000 or any(ord(c)<32 for c in reason)):
        raise ValueError('reason must contain 1..1000 characters without controls')


def revision(store, login):
    if store.schema_version < 7:return 0
    return store.db.execute('SELECT COALESCE(MAX(c.id),0) FROM reading_commits c JOIN reading_batches b ON b.id=c.batch_id '
                           'WHERE b.streamer_id=?',(store._channel(login)['id'],)).fetchone()[0]


def states(store, character_id, kind=None, *, active_only=False):
    if store.schema_version < 7:return {}
    return {(r['kind'],r['source_id']):dict(r) for r in store.db.execute(
        'SELECT * FROM reading_validity WHERE character_id=?'+(' AND kind=?' if kind else '')+(" AND action='invalidate'" if active_only else ''),
        (character_id,kind) if kind else (character_id,))}


def mask(row, event):
    """No OCR evidence enters inference, but unsafe-source and ownership barriers survive."""
    row['invalidation_barrier']=bool(row.get('crop_suspect') or row.get('candidate_invalid') or row.get('percentage_only_invalid')
        or (row.get('hud_count') or 0)>1 or (row.get('neural_level') or {}).get('source_complete') is False
        or row.get('timing_mode')=='simulated' or row.get('status')=='stale_local_frame'
        or row.get('reasons')==['operator_interrupted'])
    row.update(reading_invalidated=dict(id=event['id'],batch_id=event['batch_id'],reason=event['reason'],
        original_at=event['original_at'],recorded_at=event['recorded_at']),
        raw_text='',candidate=None,percentage_only_candidate=None,visual_level=None,
        neural_level={'source_complete':False} if (row.get('neural_level') or {}).get('source_complete') is False else None,
        fresh_at_capture=False,capture_acquired=False,manual_point=None,grammar_recovery=None)
    from .shadow_grammar import interpret_exp
    row['interpretations']=interpret_exp('')
    if row['status']!='stale_local_frame':row['status']='capture_failed'


def barriers(rows, state=None):
    """An excluded unsafe source remains a barrier even in endpoint-based public totals."""
    if state is None:state={}
    barrier=state.get('barrier');owner=state.get('owner')
    for row in rows:
        key=(row.get('character_id'),row.get('session_id'))
        if owner!=key:barrier=None;owner=key
        if row.get('invalidation_barrier'):barrier=row['reading_invalidated']['id']
        if barrier:
            row['manual_epoch']=f"{row.get('manual_epoch')}:invalid:{barrier}"
            row['invalidation_barrier_id']=barrier
    state.update(barrier=barrier,owner=owner)


class Invalidations:
    def __init__(self, store):
        self.store=store;self.db=store.db

    def owner(self, login, cid):
        if type(cid) is not int or cid<1:raise ValueError('select an existing character')
        sid=self.store._channel(login)['id']
        if not self.db.execute('SELECT 1 FROM characters WHERE id=? AND streamer_id=?',(cid,sid)).fetchone():
            raise ValueError('character does not belong to channel')
        return sid

    def source(self, login, cid, kind, identity, stamp=None):
        sid=self.owner(login,cid)
        if kind=='diagnostic' and isinstance(identity,str):
            run,_,index=identity.rpartition(':')
            if not re.fullmatch(r'[1-9][0-9]?',index):raise ValueError('invalid reading identity')
            row=self.db.execute('''SELECT a.id AS source_id,a.run_id||':'||a.attempt_index AS target_event_id,
                r.session_id,COALESCE(a.received_at,a.attempted_at) AS original_at
                FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id
                WHERE r.streamer_id=? AND r.character_id=? AND a.run_id=? AND a.attempt_index=?''',
                (sid,cid,run,int(index))).fetchone()
        elif kind=='observation' and isinstance(identity,str) and re.fullmatch(r'[1-9][0-9]{0,18}',identity):
            if int(identity)>=2**63:raise ValueError('reading identity is too large')
            row=self.db.execute('SELECT id AS source_id,CAST(id AS TEXT) AS target_event_id,session_id,observed_at AS original_at '
                'FROM observations WHERE streamer_id=? AND character_id=? AND id=?',(sid,cid,int(identity))).fetchone()
        else:raise ValueError('choose a diagnostic reading or SQLite observation')
        if row is None or row['session_id'] is None:raise ValueError('reading does not belong to this character and recording')
        result=dict(row,kind=kind)
        result['original_at']=utc(datetime.fromisoformat(result['original_at']))
        from .retention import guard
        guard(self.store,cid,result['original_at'])
        if stamp is not None and result['original_at']!=utc(datetime.fromisoformat(stamp)):
            raise ValueError('reading timestamp does not match the original')
        return result

    def selection(self, login, cid, spec):
        """Complete selection, with an explicit reject-at-limit rather than silent truncation."""
        sid=self.owner(login,cid);action=spec['action']
        if action not in ('invalidate','restore'):raise ValueError('invalid reading action')
        if 'kind' in spec:
            rows=[self.source(login,cid,spec['kind'],spec['identity'],spec['timestamp'])]
        elif 'batch_id' in spec:
            if self.store.schema_version<7:raise ValueError('unknown invalidation batch')
            batch=self.db.execute('SELECT b.* FROM reading_batches b JOIN reading_commits c ON c.batch_id=b.id '
                'WHERE b.id=? AND b.streamer_id=? AND b.character_id=?',(spec['batch_id'],sid,cid)).fetchone()
            if not batch or batch['action']!='invalidate':raise ValueError('batch does not belong to this character or cannot be restored')
            rows=[dict(r) for r in self.db.execute('SELECT kind,source_id,target_event_id,session_id,original_at '
                                                 'FROM reading_events WHERE batch_id=? ORDER BY kind,source_id',(batch['id'],))]
        else:
            start=utc(datetime.fromisoformat(spec['start']));end=utc(datetime.fromisoformat(spec['end']))
            if action!='invalidate' or start>=end:raise ValueError('choose a start time before the end time')
            from .retention import guard
            guard(self.store,cid,start)
            rows=[dict(r) for r in self.db.execute('''SELECT * FROM (
                SELECT 'diagnostic' AS kind,a.id AS source_id,a.run_id||':'||a.attempt_index AS target_event_id,
                    r.session_id,COALESCE(a.received_at,a.attempted_at) AS original_at
                FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id WHERE r.streamer_id=? AND r.character_id=?
                    AND '''+DIAGNOSTIC_TIME+'''>=? AND '''+DIAGNOSTIC_TIME+'''<?
                UNION ALL SELECT 'observation',id,CAST(id AS TEXT),session_id,observed_at FROM observations
                    WHERE streamer_id=? AND character_id=? AND session_id IS NOT NULL AND observed_at>=? AND observed_at<?)
                ORDER BY kind,source_id LIMIT ?''',(sid,cid,start,end,sid,cid,start,end,MAX_SELECTION+1))]
        if len(rows)>MAX_SELECTION:raise ValueError(f'more than {MAX_SELECTION:,} readings match; choose a smaller range')
        if 'only' in spec:
            only=spec['only']
            if ('kind' in spec or 'batch_id' in spec or not isinstance(only,list) or len(only)>MAX_SELECTION or any(not isinstance(k,list) or len(k)!=2 or
                    k[0] not in ('diagnostic','observation') or not isinstance(k[1],str) for k in only)):
                raise ValueError('invalid explicit reading selection')
            chosen={tuple(k) for k in only}
            rows=[r for r in rows if (r['kind'],r['target_event_id']) in chosen]
            if len(chosen)!=len(only) or chosen!={(r['kind'],r['target_event_id']) for r in rows}:
                raise ValueError('explicit readings are duplicated or outside the reviewed range')
        validity=states(self.store,cid)
        points={(e['target_kind'],e['target_event_id']):e['id'] for e in self.store.manual_history(login,active_only=True)
                if e['kind']=='point' and e['character_id']==cid}
        for row in rows:
            row['original_at']=utc(datetime.fromisoformat(row['original_at']))
            from .retention import guard
            guard(self.store,cid,row['original_at'])
            state=validity.get((row['kind'],row['source_id']))
            excluded=bool(state and state['action']=='invalidate')
            row['state_id']=state['id'] if state else None
            row['invalidated']=excluded
            row['selected']=(not excluded) if action=='invalidate' else bool(excluded and
                ('batch_id' not in spec or state['batch_id']==spec['batch_id']))
            row['conflict']=points.get((row['kind'],row['target_event_id'])) if row['selected'] and action=='invalidate' else None
        if 'kind' in spec and not rows[0]['selected']:
            raise ValueError('reading is already invalidated' if action=='invalidate' else 'reading is not invalidated')
        if any(r['conflict'] for r in rows):raise ValueError('a reading has a manual correction; undo that correction before invalidating it')
        manual_revision=self.db.execute('SELECT MAX(id) FROM manual_corrections WHERE streamer_id=?',(sid,)).fetchone()[0] if self.store.schema_version>=5 else None
        digest=hashlib.sha256(json.dumps([rows,manual_revision],sort_keys=True).encode()).hexdigest()
        return rows,digest

    def original(self, row):
        from .shadow_view import observation
        result=dict(row,identity=row['target_event_id'],timestamp=row['original_at'])
        if row['kind']=='diagnostic':
            raw=self.db.execute('SELECT payload_json FROM diagnostic_attempts WHERE id=?',(row['source_id'],)).fetchone()
            if raw is None:return dict(result,original=None,expired=True)
            value=observation(json.loads(raw[0]));pair=value['candidate'] or value['percentage_only_candidate'] or {}
            result['original']=dict(level=value['visual_level'],current_exp=pair.get('exp'),percentage=pair.get('percentage'))
        else:
            raw=self.db.execute('SELECT level,current_exp,percentage_bp,outcome FROM observations WHERE id=?',(row['source_id'],)).fetchone()
            if raw is None:return dict(result,original=None,expired=True)
            bp=raw['percentage_bp']
            result['original']=dict(level=raw['level'],current_exp=str(raw['current_exp']) if raw['current_exp'] is not None else None,
                                    percentage=f'{bp//100}.{bp%100:02}' if bp is not None else None,outcome=raw['outcome'])
        from .retention import expired
        cid=self.db.execute('SELECT character_id FROM sessions WHERE id=?',(row['session_id'],)).fetchone()[0]
        result['expired']=expired(self.store,cid,row['original_at'])
        return result

    def preview(self, login, cid, spec, page=0):
        if not self.db.in_transaction:
            with self.store._transaction():return self.preview(login,cid,spec,page)
        if type(page) is not int or page<0:raise ValueError('invalid review page')
        rows,digest=self.selection(login,cid,spec)
        selected=sum(r['selected'] for r in rows)
        if not rows or not selected:raise ValueError('no readings need this change')
        if page>=(len(rows)+PAGE-1)//PAGE:raise ValueError('review page is outside the selected readings')
        return dict(fingerprint=digest,count=selected,total=len(rows),already_invalidated=sum(r['invalidated'] for r in rows),
                    page=page,pages=(len(rows)+PAGE-1)//PAGE,readings=[self.original(r) for r in rows[page*PAGE:(page+1)*PAGE]])

    def commit(self, login, cid, event_id, spec, fingerprint, reason=None):
        sid=self.owner(login,cid)
        if not isinstance(event_id,str) or not 1<=len(event_id)<=200:raise ValueError('invalid retry identity')
        validate_reason(reason)
        selection_json=json.dumps(spec,sort_keys=True)
        with self.store._transaction():
            existing=self.db.execute('SELECT * FROM reading_batches WHERE event_id=?',(event_id,)).fetchone()
            if existing and (existing['streamer_id'],existing['character_id'],existing['selection_json'],existing['fingerprint'],existing['reason'])!=(sid,cid,selection_json,fingerprint,reason):
                raise ValueError('retry identity reused with different contents')
            if existing and self.db.execute('SELECT 1 FROM reading_commits WHERE batch_id=?',(existing['id'],)).fetchone():return self.receipt(existing['id'])
            rows,digest=self.selection(login,cid,spec)
            if digest!=fingerprint:raise ValueError('readings changed since review; review the selection again')
            chosen=[r for r in rows if r['selected']]
            if not chosen:raise ValueError('no readings need this change')
            batch=existing['id'] if existing else self.db.execute('''INSERT INTO reading_batches
                (event_id,streamer_id,character_id,action,selection_json,fingerprint,recorded_at,reason,expected_count) VALUES(?,?,?,?,?,?,?,?,?)''',
                (event_id,sid,cid,spec['action'],selection_json,fingerprint,utc(),reason,len(chosen))).lastrowid
        for start in range(0,len(chosen),WRITE_CHUNK):
            with self.store._transaction():
                if self.db.execute('SELECT 1 FROM reading_commits WHERE batch_id=?',(batch,)).fetchone():return self.receipt(batch)
                self.db.executemany('''INSERT OR IGNORE INTO reading_events
                    (batch_id,kind,source_id,target_event_id,session_id,original_at) VALUES(?,?,?,?,?,?)''',
                    [(batch,r['kind'],r['source_id'],r['target_event_id'],r['session_id'],r['original_at']) for r in chosen[start:start+WRITE_CHUNK]])
        with self.store._transaction():
            if self.db.execute('SELECT 1 FROM reading_commits WHERE batch_id=?',(batch,)).fetchone():return self.receipt(batch)
            _,digest=self.selection(login,cid,spec)
            if digest!=fingerprint:raise ValueError('readings changed while saving; nothing was applied. Review again')
            self.db.execute('INSERT INTO reading_commits(batch_id,recorded_at) VALUES(?,?)',(batch,utc()))
        return self.receipt(batch)

    def receipt(self, batch):
        row=dict(self.db.execute('SELECT b.*,c.recorded_at AS committed_at FROM reading_batches b '
             'JOIN reading_commits c ON c.batch_id=b.id WHERE b.id=?',(batch,)).fetchone())
        row['count']=self.db.execute('SELECT COUNT(*) FROM reading_events WHERE batch_id=?',(batch,)).fetchone()[0]
        return row

    def history(self, login, cid, before=None):
        sid=self.owner(login,cid)
        if self.store.schema_version<7:return dict(batches=[],next_before=None)
        expired="""(e.kind='diagnostic' AND NOT EXISTS(SELECT 1 FROM diagnostic_attempts a WHERE a.id=e.source_id))
            OR (e.kind='observation' AND NOT EXISTS(SELECT 1 FROM observations o WHERE o.id=e.source_id))"""
        if self.store.schema_version>=8:
            expired+=' OR EXISTS(SELECT 1 FROM retention_state t WHERE t.character_id=b.character_id AND e.original_at<=t.cutoff)'
        rows=self.db.execute('''SELECT b.*,c.id AS commit_id,c.recorded_at AS committed_at,
            (SELECT COUNT(*) FROM reading_events WHERE batch_id=b.id) AS count,
            (SELECT COUNT(*) FROM reading_events e WHERE e.batch_id=b.id AND ('''+expired+''')) AS expired_count,
            (SELECT COUNT(*) FROM reading_validity WHERE batch_id=b.id AND action='invalidate') AS remaining
            FROM reading_batches b JOIN reading_commits c ON c.batch_id=b.id WHERE b.streamer_id=? AND b.character_id=?
            AND c.id<? ORDER BY c.id DESC LIMIT ?''',(sid,cid,before or 2**63-1,PAGE+1)).fetchall()
        return dict(batches=[dict(r) for r in rows[:PAGE]],next_before=rows[PAGE-1]['commit_id'] if len(rows)>PAGE else None)

    def excluded(self, login, cid, before=None, session=None):
        sid=self.owner(login,cid)
        if self.store.schema_version<7:return dict(readings=[],next_before=None)
        rows=self.db.execute('''SELECT *,id AS state_id FROM reading_validity WHERE streamer_id=? AND character_id=?
            AND action='invalidate' AND id<?'''+(' AND session_id=?' if session is not None else '')+' ORDER BY id DESC LIMIT ?',
            (sid,cid,before or 2**63-1,*((session,) if session is not None else ()),PAGE+1)).fetchall()
        return dict(readings=[self.original(dict(r,invalidated=True,selected=False)) for r in rows[:PAGE]],
                    next_before=rows[PAGE-1]['id'] if len(rows)>PAGE else None)
