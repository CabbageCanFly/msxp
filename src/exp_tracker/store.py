"""Local SQLite state. Writers validate under a write lock; readers use snapshots."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .glyphs import GlyphProfile
from .models import Reading, Recognition, PLACEHOLDER_CHARACTER
from .schema import CHARACTER_INVALIDATIONS, CHARACTER_JOBS, MIGRATION_2, MIGRATION_3, MIGRATION_4, MIGRATION_5, MIGRATION_6, MIGRATION_7, MIGRATION_8, MIGRATION_9, MIGRATION_10, MIGRATION_11, STATEMENTS, VERSION
from .statistics import tracking_statistics
from .trust import guard_unverified_exp
from .validation import Observation, Transition, validate_transition


OCR_INTERRUPTION_STATUSES = {"unreadable", "missing_hud", "low_confidence", "invalid", "ambiguous"}
STALE_AFTER_SECONDS = 120


def utc(value=None):
    value = value if value is not None else datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


class Store:
    def __init__(self, path: str | Path, *, read_only=False, allow_migration=True):
        self.read_only = read_only
        target = Path(path).resolve().as_uri() + "?mode=ro" if read_only else path
        self.db = sqlite3.connect(target, uri=read_only, timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA foreign_keys=ON")
            with self._transaction():
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
                new_database = version==0
                if read_only:
                    if version not in (3,4,5,6,7,8,9,10,VERSION):
                        raise ValueError(f"unsupported schema version {version}; initialize/migrate with the tracking CLI first")
                    self.schema_version=version
                    return
                if not allow_migration and version not in (0,10,VERSION):
                    raise ValueError('automatic migration disabled; use a new trial database')
                if version == 0:
                    if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                        raise ValueError("unversioned existing database; refusing to adopt it")
                    for statement in STATEMENTS:
                        self.db.execute(statement)
                    version = 1
                if version == 1:
                    for statement in MIGRATION_2:
                        self.db.execute(statement)
                    version = 2
                if version == 2:
                    for statement in MIGRATION_3:
                        self.db.execute(statement)
                    version = 3
                if version == 3:
                    for statement in MIGRATION_4:
                        self.db.execute(statement)
                    version = 4
                if version == 4:
                    for statement in MIGRATION_5:
                        self.db.execute(statement)
                    version = 5
                if version == 5:
                    for statement in MIGRATION_6:
                        self.db.execute(statement)
                    version = 6
                if version == 6:
                    for statement in MIGRATION_7:
                        self.db.execute(statement)
                    version = 7
                if version == 7:
                    for statement in MIGRATION_8:
                        self.db.execute(statement)
                    version = 8
                if version == 8:
                    for statement in MIGRATION_9:
                        self.db.execute(statement)
                    version = 9
                if version == 9:
                    for statement in MIGRATION_10:
                        self.db.execute(statement)
                    version = 10
                # Existing databases cross this boundary only through reviewed roster bootstrap.
                if version == 10 and new_database:
                    for statement in MIGRATION_11:
                        self.db.execute(statement)
                    version = 11
                if version not in (10,VERSION):
                    raise ValueError(f"unsupported schema version {version}")
                self.db.execute(CHARACTER_INVALIDATIONS);self.db.execute(CHARACTER_JOBS)
                self.db.execute(f"PRAGMA user_version={version}")
                self.schema_version=version
            self.db.execute("PRAGMA journal_mode=WAL")
        except Exception:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    @contextmanager
    def _transaction(self):
        nested = self.db.in_transaction
        self.db.execute('SAVEPOINT store_nested' if nested else "BEGIN" if self.read_only else "BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute('RELEASE store_nested' if nested else "COMMIT")
        except BaseException:
            self.db.execute('ROLLBACK TO store_nested' if nested else "ROLLBACK")
            if nested: self.db.execute('RELEASE store_nested')
            raise

    def _channel(self, login):
        row = self.db.execute("SELECT * FROM streamers WHERE login=?", (login.lower(),)).fetchone()
        if row is None:
            raise ValueError("unknown channel")
        return row

    def add_channel(self, login):
        if not re.fullmatch(r"[a-zA-Z0-9_]{1,25}", login):
            raise ValueError("invalid channel login")
        with self._transaction():
            self.db.execute("INSERT INTO streamers(login) VALUES (?) ON CONFLICT(login) DO NOTHING", (login.lower(),))
            return self._channel(login)["id"]

    def add_character(self, login, label):
        if not label.strip() or len(label) > 100:
            raise ValueError("character label must contain 1..100 characters")
        with self._transaction():
            streamer = self._channel(login)
            self.db.execute("INSERT INTO characters(streamer_id,label) VALUES (?,?) ON CONFLICT DO NOTHING",
                            (streamer["id"], label))
            char = self.db.execute("SELECT id FROM characters WHERE streamer_id=? AND label=?",
                                   (streamer["id"], label)).fetchone()[0]
            self.db.execute("INSERT INTO tracking_state(character_id) VALUES (?) ON CONFLICT DO NOTHING", (char,))
            return char

    def _open_session(self, streamer_id):
        return self.db.execute("SELECT * FROM sessions WHERE streamer_id=? AND ended_at IS NULL",
                               (streamer_id,)).fetchone()

    def _pending_character(self, character_id):
        return bool(self.db.execute('SELECT 1 FROM characters WHERE id=? AND label=?',
                                   (character_id,PLACEHOLDER_CHARACTER)).fetchone())

    def _end(self, session, when, reason):
        state = self.db.execute("SELECT * FROM tracking_state WHERE character_id=?", (session["character_id"],)).fetchone()
        if when < session["started_at"] or state["last_event_at"] and when < state["last_event_at"]:
            raise ValueError("session end precedes recorded activity")
        self.db.execute("UPDATE sessions SET ended_at=?,end_reason=? WHERE id=?", (when, reason, session["id"]))
        self.db.execute("""UPDATE tracking_state SET status='stopped',reason=?,
                        continuity_broken=1,pending_missing_observations=0 WHERE character_id=?""",
                        (reason, session["character_id"]))

    def select_character(self, login, character_id, *, at=None, only_if_unselected=False):
        when = utc(at)
        with self._transaction():
            streamer = self._channel(login)
            if only_if_unselected and streamer['selected_character_id'] not in (None, character_id):
                raise ValueError('character selection changed; refusing automatic switch')
            if not self.db.execute("SELECT 1 FROM characters WHERE id=? AND streamer_id=?",
                                   (character_id, streamer["id"])).fetchone():
                raise ValueError("character does not belong to channel")
            if streamer["selected_character_id"] != character_id:
                session = self._open_session(streamer["id"])
                if session:
                    self._end(session, when, "character_switch")
                self.db.execute("UPDATE streamers SET selected_character_id=? WHERE id=?", (character_id, streamer["id"]))

    def start_session(self, login, *, at=None, expected_character_id=None):
        when = utc(at)
        with self._transaction():
            streamer = self._channel(login)
            char = streamer["selected_character_id"]
            if expected_character_id is not None and char != expected_character_id:
                raise ValueError('character selection changed; refusing session reassignment')
            if char is None:
                raise ValueError("select a character first")
            session = self._open_session(streamer["id"])
            if session:
                return session["id"]
            state = self.db.execute("SELECT * FROM tracking_state WHERE character_id=?", (char,)).fetchone()
            ended = self.db.execute("SELECT MAX(ended_at) FROM sessions WHERE streamer_id=?", (streamer["id"],)).fetchone()[0]
            if (state["last_event_at"] and when < state["last_event_at"]) or (ended and when < ended):
                raise ValueError("session start precedes recorded activity")
            session_id = self.db.execute("INSERT INTO sessions(streamer_id,character_id,started_at) VALUES (?,?,?)",
                                         (streamer["id"], char, when)).lastrowid
            self.db.execute("""UPDATE tracking_state SET status='waiting',reason='new_session',
                            continuity_broken=1,pending_missing_observations=0 WHERE character_id=?""", (char,))
            return session_id

    def end_session(self, login, *, at=None):
        with self._transaction():
            session = self._open_session(self._channel(login)["id"])
            if session:
                self._end(session, utc(at), "explicit_end")

    def manual_history(self, login, *, character_id=None, as_of=None, active_only=False):
        """Current audit resolution, filtered by effective time, never by recording order."""
        streamer = self._channel(login)
        if self.schema_version < 5:
            return []
        rows=[dict(kind='baseline',operation='apply',replaces_id=None,target_kind=None,target_event_id=None,**dict(r))
              if self.schema_version<6 else dict(r) for r in self.db.execute(
            'SELECT * FROM manual_corrections WHERE streamer_id=? ORDER BY effective_at,id',(streamer['id'],))]
        replaced={r['replaces_id']:r['id'] for r in rows if r['replaces_id'] is not None}
        cutoff=utc(as_of) if as_of is not None else None
        for row in rows:
            row['superseded_by']=replaced.get(row['id'])
            row['active']=row['id'] not in replaced and row['operation']!='retract'
        # Resolve across the whole channel first: an amendment can move to another character/time.
        return [r for r in rows if (character_id is None or r['character_id']==character_id)
                and (cutoff is None or r['effective_at']<=cutoff) and (not active_only or r['active'])]

    def _manual_session(self, streamer_id, character_id, when, session_id):
        if session_id is not None and (type(session_id) is not int or session_id<1):
            raise ValueError('session must be a positive integer')
        sessions=list(self.db.execute('SELECT * FROM sessions WHERE streamer_id=? AND character_id=?'+
            (' AND id=?' if session_id is not None else ''),
            (streamer_id,character_id,session_id) if session_id is not None else (streamer_id,character_id)))
        matches=[s for s in sessions if utc(datetime.fromisoformat(s['started_at']))<=when and
                 (s['ended_at'] is None or when<=utc(datetime.fromisoformat(s['ended_at']))) ]
        if len(matches)>1:raise ValueError('ambiguous session at timestamp; specify --session')
        if not matches and (sessions or session_id is not None):
            raise ValueError('timestamp is outside the character/session scope')
        return matches[0]['id'] if matches else None

    def _manual_target(self, streamer_id, character_id, session_id, when, target_kind, target_event_id):
        """Resolve one immutable OCR identity, using an exact timestamp when no ID is given."""
        if session_id is None:raise ValueError('a historical reading needs an existing session')
        if target_kind not in (None,'diagnostic','observation'):
            raise ValueError('target kind must be diagnostic or observation')
        matches=[]
        if target_kind in (None,'diagnostic'):
            for row in self.db.execute('''SELECT a.run_id,a.attempt_index,a.attempted_at,a.received_at
                FROM diagnostic_attempts a JOIN diagnostic_runs r ON a.run_id=r.run_id
                WHERE r.streamer_id=? AND r.character_id=? AND r.session_id=?''',
                (streamer_id,character_id,session_id)):
                identity=f"{row['run_id']}:{row['attempt_index']}"
                stamp=row['received_at'] or row['attempted_at']
                if (target_event_id is None or str(target_event_id)==identity) and utc(datetime.fromisoformat(stamp))==when:
                    matches.append(('diagnostic',identity))
        if target_kind in (None,'observation'):
            for row in self.db.execute('SELECT id,observed_at FROM observations WHERE streamer_id=? AND character_id=? AND session_id=?',
                                       (streamer_id,character_id,session_id)):
                if (target_event_id is None or str(target_event_id)==str(row['id'])) and row['observed_at']==when:
                    matches.append(('observation',str(row['id'])))
        if len(matches)!=1:
            raise ValueError('ambiguous reading; specify --reading or --observation-id' if matches else
                             'no reading matches character, session, identity and exact effective timestamp')
        return matches[0]

    def correct_manual(self, login, event_id, character_id, *, level=None, current_exp=None,
                       percentage_bp=None, effective_at=None, now=False, reason=None, clear=False,
                       session_id=None, no_session=False, kind='baseline', target_kind=None, target_event_id=None, replaces_id=None):
        """Append a fully specified baseline/point, optionally replacing an active audit revision."""
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 200:
            raise ValueError('event_id must contain 1..200 characters')
        if type(character_id) is not int or character_id < 1 or type(clear) is not bool or type(now) is not bool:
            raise ValueError('invalid character or clear flag')
        if type(no_session) is not bool or no_session and session_id is not None:
            raise ValueError('choose session_id or no_session, exclusively')
        for name, value, low, high in (('level',level,1,200), ('current_exp',current_exp,0,2**63-1),
                                      ('percentage_bp',percentage_bp,0,9999)):
            if value is not None and (type(value) is not int or not low <= value <= high):
                raise ValueError(f'{name} must be an integer in {low}..{high}')
        if kind not in ('baseline','point') or clear and kind!='baseline':raise ValueError('invalid correction kind')
        if clear and any(v is not None for v in (level,current_exp,percentage_bp)):
            raise ValueError('clear cannot supply level or EXP')
        if not clear and (level is None or current_exp is None and percentage_bp is None):
            raise ValueError('level and at least one of current_exp or percentage_bp are required')
        if reason is not None and (not isinstance(reason,str) or not reason.strip() or len(reason)>1000
                                   or any(ord(c)<32 for c in reason)):
            raise ValueError('reason must contain 1..1000 characters without controls')
        if effective_at is not None and not isinstance(effective_at,datetime):
            raise ValueError('effective timestamp must be a timezone-aware datetime')
        if (effective_at is not None)==now:
            raise ValueError('supply exactly one explicit effective timestamp or now=True')
        recorded = utc(); when = recorded if now else utc(effective_at)
        if when > recorded:
            raise ValueError('effective timestamp cannot be in the future')
        with self._transaction():
            streamer = self._channel(login)
            existing = self.db.execute('SELECT * FROM manual_corrections WHERE streamer_id=? AND event_id=?',
                                       (streamer['id'],event_id)).fetchone()
            action = 'clear' if clear else 'set'
            if existing:
                keys=('character_id','action','level','current_exp','percentage_bp','reason','kind','replaces_id')
                expected=(character_id,action,level,current_exp,percentage_bp,reason,kind,replaces_id)
                if tuple(existing[k] for k in keys)!=expected or existing['operation']!='apply' or (
                        not now and existing['effective_at']!=when) or (session_id is not None and existing['session_id']!=session_id) or (
                        target_kind is not None and existing['target_kind']!=target_kind) or (
                        target_event_id is not None and existing['target_event_id']!=str(target_event_id)) or (
                        no_session and existing['session_id'] is not None):
                    raise ValueError('event_id reused with different contents')
                return dict(existing,duplicate=True)
            if not self.db.execute('SELECT 1 FROM characters WHERE id=? AND streamer_id=?',(character_id,streamer['id'])).fetchone():
                raise ValueError('character does not belong to channel')
            if self._pending_character(character_id):raise ValueError('PendingOCR cannot receive manual EXP assertions')
            if self.schema_version>=10 and level is not None:
                floor=self.db.execute('SELECT level,proof_json FROM character_level_guard WHERE character_id=?',(character_id,)).fetchone()
                if (floor and floor['level'] is not None and level<floor['level']
                        and (kind=='baseline' or datetime.fromisoformat(when)>=datetime.fromisoformat(json.loads(floor['proof_json'])['received_at']))):
                    raise ValueError('current correction cannot regress the validated character level; historical corrections remain available')
            from .retention import guard
            guard(self,character_id,when)
            if replaces_id is not None:
                self._manual_revision(login,replaces_id)
                if not reason:raise ValueError('amending a correction requires a reason')
            session_id=None if no_session else self._manual_session(streamer['id'],character_id,when,session_id)
            if kind=='point':
                target_kind,target_event_id=self._manual_target(streamer['id'],character_id,session_id,when,target_kind,target_event_id)
                from .invalidations import Invalidations,states
                target=Invalidations(self).source(login,character_id,target_kind,str(target_event_id))
                validity=states(self,character_id,target_kind).get((target_kind,target['source_id']))
                if validity and validity['action']=='invalidate':
                    raise ValueError('reading is invalidated; restore it before applying a manual correction')
                conflict=next((e for e in self.manual_history(login,active_only=True) if e['kind']=='point'
                    and (e['target_kind'],e['target_event_id'])==(target_kind,target_event_id) and e['id']!=replaces_id),None)
                if conflict:raise ValueError(f"reading already corrected by {conflict['id']}; amend or undo that correction")
            elif target_kind is not None or target_event_id is not None:
                raise ValueError('a baseline cannot target a reading identity')
            row_id = self.db.execute('''INSERT INTO manual_corrections(event_id,streamer_id,character_id,session_id,
                effective_at,recorded_at,action,level,current_exp,percentage_bp,reason,kind,target_kind,target_event_id,replaces_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (event_id,streamer['id'],character_id,session_id,when,recorded,action,level,current_exp,percentage_bp,reason,
                 kind,target_kind,target_event_id,replaces_id)).lastrowid
            if self.schema_version>=10 and level is not None and floor and (floor['level'] is None or level>floor['level']):
                proof=dict(level=level,received_at=when,basis='manual_admin',event_id=event_id)
                self.db.execute('UPDATE character_level_guard SET level=?,proof_json=?,pending_json=NULL,updated_at=? WHERE character_id=?',
                                (level,json.dumps(proof),recorded,character_id))
            return dict(self.db.execute('SELECT * FROM manual_corrections WHERE id=?',(row_id,)).fetchone(),duplicate=False)

    def _manual_revision(self, login, correction_id):
        if type(correction_id) is not int or correction_id<1:raise ValueError('invalid correction ID')
        event=next((e for e in self.manual_history(login) if e['id']==correction_id),None)
        if event is None:raise ValueError('correction does not belong to channel')
        if not event['active']:
            raise ValueError(f"correction is inactive; inspect successor {event['superseded_by']}" if event['superseded_by'] else
                             'retractions are audit records; submit a new set/correct to restore operator information')
        from .retention import guard
        guard(self,event['character_id'],event['effective_at'])
        return event

    def retract_manual(self, login, event_id, correction_id, *, reason):
        if not isinstance(event_id,str) or not 1<=len(event_id)<=200:raise ValueError('invalid event_id')
        if not isinstance(reason,str) or not reason.strip() or len(reason)>1000 or any(ord(c)<32 for c in reason):
            raise ValueError('undo requires a reason of 1..1000 characters without controls')
        with self._transaction():
            streamer=self._channel(login)
            existing=self.db.execute('SELECT * FROM manual_corrections WHERE streamer_id=? AND event_id=?',
                                     (streamer['id'],event_id)).fetchone()
            if existing:
                if existing['operation']!='retract' or existing['replaces_id']!=correction_id or existing['reason']!=reason:
                    raise ValueError('event_id reused with different contents')
                return dict(existing,duplicate=True)
            event=self._manual_revision(login,correction_id)
            row_id=self.db.execute('''INSERT INTO manual_corrections(event_id,streamer_id,character_id,session_id,
                effective_at,recorded_at,action,reason,kind,operation,replaces_id,target_kind,target_event_id)
                VALUES(?,?,?,?,?,?,'clear',?,?,'retract',?,?,?)''',
                (event_id,streamer['id'],event['character_id'],event['session_id'],event['effective_at'],utc(),reason,
                 event['kind'],correction_id,event['target_kind'],event['target_event_id'])).lastrowid
            return dict(self.db.execute('SELECT * FROM manual_corrections WHERE id=?',(row_id,)).fetchone(),duplicate=False)

    def rename_character(self, login, character_id, label, *, reason=None):
        if type(character_id) is not int or character_id<1:raise ValueError('invalid character ID')
        if not isinstance(label,str) or label!=label.strip() or not 1<=len(label)<=100 or any(ord(c)<32 for c in label):
            raise ValueError('new character name must contain 1..100 characters without controls or outer whitespace')
        if reason is not None and (not isinstance(reason,str) or not reason.strip() or len(reason)>1000 or any(ord(c)<32 for c in reason)):
            raise ValueError('invalid rename reason')
        with self._transaction():
            streamer=self._channel(login)
            character=self.db.execute('SELECT * FROM characters WHERE id=? AND streamer_id=?',(character_id,streamer['id'])).fetchone()
            if character is None:raise ValueError('character does not belong to channel')
            if character['label']==PLACEHOLDER_CHARACTER or label==PLACEHOLDER_CHARACTER:
                raise ValueError('PendingOCR is reserved for internal discovery and cannot be renamed')
            if character['label']==label:raise ValueError('character already has that name')
            if self.db.execute('SELECT 1 FROM characters WHERE streamer_id=? AND label=?',(streamer['id'],label)).fetchone():
                raise ValueError('character name already exists in this channel')
            self.db.execute('UPDATE characters SET label=? WHERE id=?',(label,character_id))
            row_id=self.db.execute('''INSERT INTO character_renames(streamer_id,character_id,previous_label,label,recorded_at,reason)
                VALUES(?,?,?,?,?,?)''',(streamer['id'],character_id,character['label'],label,utc(),reason)).lastrowid
            return dict(self.db.execute('SELECT * FROM character_renames WHERE id=?',(row_id,)).fetchone())

    def invalidated_characters(self, streamer_id):
        """Characters an operator marked as not this streamer's own: each character's latest decision."""
        # Read-only stores of a database no writer has opened since this feature have no table yet.
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='character_invalidations'").fetchone():return set()
        return {r[0] for r in self.db.execute('''SELECT character_id FROM character_invalidations c WHERE streamer_id=? AND action='invalidate'
            AND id=(SELECT MAX(id) FROM character_invalidations WHERE character_id=c.character_id)''',(streamer_id,))}

    def invalidate_character(self, login, character_id, *, reason, restore=False):
        """Mark a detected character as not the streamer's own (restore=True undoes it); its readings are kept."""
        if type(character_id) is not int or character_id<1:raise ValueError('invalid character ID')
        if not isinstance(reason,str) or not reason.strip() or len(reason)>1000 or any(ord(c)<32 for c in reason):
            raise ValueError('a reason of 1..1000 characters without controls is required')
        with self._transaction():
            streamer=self._channel(login)
            character=self.db.execute('SELECT * FROM characters WHERE id=? AND streamer_id=?',(character_id,streamer['id'])).fetchone()
            if character is None:raise ValueError('character does not belong to channel')
            if character['label']==PLACEHOLDER_CHARACTER:raise ValueError('PendingOCR is internal and cannot be invalidated')
            invalid=character_id in self.invalidated_characters(streamer['id'])
            if restore and not invalid:raise ValueError('character is not invalidated')
            if not restore and invalid:raise ValueError('character is already invalidated')
            row_id=self.db.execute('''INSERT INTO character_invalidations(streamer_id,character_id,action,label,reason,recorded_at)
                VALUES(?,?,?,?,?,?)''',(streamer['id'],character_id,'restore' if restore else 'invalidate',character['label'],reason,utc())).lastrowid
            if not restore and streamer['selected_character_id']==character_id:
                from .diagnostics import Diagnostics
                candidates=[c for c in Diagnostics(self).roster(login) if c['label']!=PLACEHOLDER_CHARACTER]
                target=max(candidates,key=lambda c:(c['last_seen_at'] or '',c['id']))['id'] if candidates else self.add_character(login,PLACEHOLDER_CHARACTER)
                self.select_character(login,target)
                if self.schema_version>=10:
                    from .automatic_adoption import state,save_state
                    from .streamer_roster import discovery_state,save_identity
                    adopted=state(self,streamer['id'])
                    identity=adopted or discovery_state(self,streamer['id'])
                    if identity:
                        identity.update(verified=False,verification=None,started=True,risk='character_invalidated')
                        (save_state if adopted else save_identity)(self,streamer['id'],identity)
                if self.schema_version>=11:
                    from . import streamer_roster as roster
                    settings=roster.entry(self,login)
                    if settings and settings['tracking_enabled'] and not settings['automatic_characters']:
                        roster.commit(self,roster.preview(self,dict(action='roster_update',channel=login,
                            tracking_enabled=False,reason='Selected character invalidated; verify identity before resuming manual capture')))
            return dict(self.db.execute('SELECT * FROM character_invalidations WHERE id=?',(row_id,)).fetchone())

    def character_job(self, character_id):
        """The character's job with its source and time, or None. Read-only stores may predate the table."""
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='character_jobs'").fetchone():return None
        row=self.db.execute('SELECT job,source,recorded_at FROM character_jobs WHERE character_id=? ORDER BY id DESC LIMIT 1',(character_id,)).fetchone()
        return dict(row) if row and row['job'] else None

    def set_character_job(self, character_id, job, *, source, evidence=None):
        """Record the character's job (None clears it); only jobs in the job list are accepted."""
        from .jobs import table
        if job is not None and job not in table()['jobs']:raise ValueError('unknown job')
        if source not in ('ocr','manual_admin'):raise ValueError('invalid job source')
        with self._transaction():
            if self.db.execute('SELECT 1 FROM characters WHERE id=?',(character_id,)).fetchone() is None:raise ValueError('unknown character')
            self.db.execute('INSERT INTO character_jobs(character_id,job,source,evidence_json,recorded_at) VALUES(?,?,?,?,?)',
                (character_id,job,source,json.dumps(evidence) if evidence else None,utc()))

    def character_invalidation_history(self, character_id):
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='character_invalidations'").fetchone():return []
        return [dict(r) for r in self.db.execute('SELECT * FROM character_invalidations WHERE character_id=? ORDER BY id DESC',(character_id,))]

    def ingest(self, login, event_id, observed_at, result: Recognition, *, profile=None,
               session_id=None, source="local"):
        """In-process evidence, not an authentication API. Caller supplies a stable event ID.

        Validation is recomputed against the DB, never a caller's cached baseline.
        No-profile results are diagnostic even when legacy OCR calls them accepted.
        Recognition("paused") records an explicit hard pause; OCR failures are soft.
        """
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 200:
            raise ValueError("event_id must contain 1..200 characters")
        when = utc(observed_at)
        if profile is not None and not isinstance(profile, GlyphProfile):
            raise ValueError("profile must be a calibrated GlyphProfile")
        result = guard_unverified_exp(deepcopy(result), profile)
        diagnostic = json.dumps(asdict(result), sort_keys=True, allow_nan=False)
        fingerprint = hashlib.sha256(json.dumps(asdict(profile), sort_keys=True).encode()).hexdigest() if profile else None
        with self._transaction():
            streamer = self._channel(login)
            existing = self.db.execute("SELECT * FROM observations WHERE streamer_id=? AND event_id=?",
                                       (streamer["id"], event_id)).fetchone()
            if existing:
                if (existing["session_id"], existing["observed_at"], existing["diagnostic_json"], existing["profile_hash"], existing["source"]) != (
                        session_id, when, diagnostic, fingerprint, source):
                    raise ValueError("event_id reused with different contents")
                return {**dict(existing), "duplicate": True}
            session = self.db.execute("SELECT * FROM sessions WHERE id=? AND streamer_id=?",
                                      (session_id, streamer["id"])).fetchone() if session_id is not None else None
            if session_id is not None and session is None:
                raise ValueError("session does not belong to channel")
            char = session["character_id"] if session else None
            from .retention import guard, next_id
            guard(self,char,when)
            state = self.db.execute("SELECT * FROM tracking_state WHERE character_id=?", (char,)).fetchone()
            from .trusted_replay import replay as replay_trusted
            revised=replay_trusted(self,session_id)
            if revised is not None:
                if revised['unavailable']:raise ValueError('trusted accounting history limit; start a new recording')
                state=dict(state,last_trusted_observation_id=revised['last']['id'] if revised['last'] else None,
                    last_event_at=revised['last_event_at'],continuity_broken=revised['broken'],pending_missing_observations=revised['pending'])
            active = bool(session and session["ended_at"] is None and streamer["selected_character_id"] == char)
            ordered = bool(active and when >= session["started_at"] and
                           (state["last_event_at"] is None or when > state["last_event_at"]))
            transition = Transition("rejected", "no_active_session" if not active else "out_of_order")
            interval_start = None
            missing = 0
            if ordered:
                if char in self.invalidated_characters(streamer['id']):
                    transition = Transition('rejected','character_invalidated')
                elif self._pending_character(char):
                    transition = Transition('rejected','character_discovery_pending')
                elif result.status in {"offline", "paused"}:
                    transition = Transition("rejected", ";".join(result.reasons) or result.status)
                elif profile is None:
                    transition = Transition("rejected", "glyph_profile_required")
                elif result.status != "accepted" or result.reading is None:
                    transition = Transition("rejected", ";".join(result.reasons) or result.status)
                else:
                    previous = self.db.execute("SELECT * FROM observations WHERE id=?", (state["last_trusted_observation_id"],)).fetchone()
                    boundaries=[e['effective_at'] for e in self.manual_history(login,character_id=char,active_only=True)
                                if e['session_id']==session_id and e['effective_at']<when]
                    if boundaries and previous and previous['observed_at'] <= max(boundaries):
                        previous = None
                    observation = Observation(str(char), datetime.fromisoformat(when), result.reading)
                    prior = Observation(str(char), datetime.fromisoformat(previous["observed_at"]),
                                        Reading(previous["level"], previous["current_exp"], previous["percentage_bp"] / 100)) if previous and previous["session_id"] == session_id else None
                    transition = validate_transition(prior, observation)
                    if self.schema_version>=10:
                        floor=self.db.execute('SELECT level FROM character_level_guard WHERE character_id=?',(char,)).fetchone()
                        if floor and floor['level'] is not None and result.reading.level<floor['level']:
                            transition=Transition('rejected','validated_character_level_regression')
                        elif floor and floor['level'] is not None and result.reading.level>floor['level']:
                            transition=Transition('ambiguous','validated_character_level_confirmation_required')
                    if transition.status == "accepted" and state["continuity_broken"]:
                        transition = Transition("baseline", "continuity_resumed")
                    if transition.status == "accepted":
                        interval_start = previous["id"]
                        missing = state["pending_missing_observations"]
            trusted = transition.status in {"accepted", "baseline"}
            reading = result.reading if trusted else None
            row_id = self.db.execute("""INSERT INTO observations(
                id,event_id,streamer_id,session_id,character_id,observed_at,recorded_at,source,profile_hash,diagnostic_json,
                outcome,reason,level,current_exp,percentage_bp,gained_exp,interval_start_observation_id,
                missing_observations) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (next_id(self,'observations','observation_id'),event_id, streamer["id"], session_id, char, when, utc(), source, fingerprint, diagnostic,
                 transition.status, transition.reason, reading.level if reading else None,
                 reading.current_exp if reading else None, round(reading.percentage * 100) if reading else None,
                 transition.gained_exp, interval_start, missing)).lastrowid
            if ordered:
                status = "tracking" if trusted else "ambiguous" if transition.status == "ambiguous" else "offline" if result.status == "offline" else "paused"
                soft_failure = profile is not None and result.status in OCR_INTERRUPTION_STATUSES
                broken = False if trusted else bool(state["continuity_broken"] or not soft_failure)
                pending = state["pending_missing_observations"] + 1 if soft_failure else 0
                self.db.execute("""UPDATE tracking_state SET last_event_at=?,status=?,reason=?,
                    continuity_broken=?,pending_missing_observations=?,
                    last_trusted_observation_id=CASE WHEN ? THEN ? ELSE last_trusted_observation_id END
                    WHERE character_id=?""", (when, status, transition.reason, broken, pending, trusted, row_id, char))
            return {**dict(self.db.execute("SELECT * FROM observations WHERE id=?", (row_id,)).fetchone()), "duplicate": False}

    def state(self, login, *, as_of=None):
        with self._transaction():
            return self._state(login, as_of=as_of)

    def _state(self, login, *, as_of=None):
        now = datetime.fromisoformat(utc(as_of))
        streamer = self._channel(login)
        chars = [dict(row) for row in self.db.execute("SELECT id,label FROM characters WHERE streamer_id=? ORDER BY id", (streamer["id"],))]
        session = self._open_session(streamer["id"])
        state = self.db.execute("SELECT * FROM tracking_state WHERE character_id=?", (streamer["selected_character_id"],)).fetchone()
        last = self.db.execute("SELECT id,session_id,observed_at,level,current_exp,percentage_bp FROM observations WHERE id=?",
                               (state["last_trusted_observation_id"],)).fetchone() if state else None
        age = max(0, (now - datetime.fromisoformat(last["observed_at"])).total_seconds()) if last else None
        stale = age is None or age > STALE_AFTER_SECONDS
        status = state["status"] if state else "unconfigured"
        if session and stale and status == "tracking":
            status = "paused"
        gained = self.db.execute("SELECT COALESCE(SUM(gained_exp),0) FROM observations WHERE session_id=?", (session["id"],)).fetchone()[0] if session else 0
        bridged = self.db.execute("""SELECT COALESCE(SUM(gained_exp),0) FROM observations
                                  WHERE session_id=? AND missing_observations>0""", (session["id"],)).fetchone()[0] if session else 0
        if self.schema_version>=8 and session:
            totals=self.db.execute('SELECT original_gain,original_bridged FROM trusted_checkpoints WHERE session_id=?',(session['id'],)).fetchone()
            if totals:gained+=totals[0];bridged+=totals[1]
        snapshot = dict(channel=streamer["login"], selected_character_id=streamer["selected_character_id"],
                    characters=chars, session=dict(session) if session else None, status=status,
                    reason="stale" if state and status == "paused" and state["status"] == "tracking" else state["reason"] if state else "select_character",
                    last_trusted=dict(last) if last else None, last_event_at=state["last_event_at"] if state else None,
                    age_seconds=age, stale=stale, observed_session_exp=gained, bridged_session_exp=bridged,
                    continuity_broken=bool(state["continuity_broken"]) if state else True,
                    pending_missing_observations=state["pending_missing_observations"] if state else 0)
        snapshot["statistics"] = tracking_statistics(self.db, snapshot, now)
        from .trusted_replay import present as present_trusted
        return present_trusted(self,snapshot,now)
