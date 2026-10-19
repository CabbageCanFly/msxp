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
from .models import Reading, Recognition
from .schema import MIGRATION_2, MIGRATION_3, MIGRATION_4, MIGRATION_5, STATEMENTS, VERSION
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
    def __init__(self, path: str | Path, *, read_only=False):
        self.read_only = read_only
        target = Path(path).resolve().as_uri() + "?mode=ro" if read_only else path
        self.db = sqlite3.connect(target, uri=read_only, timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA foreign_keys=ON")
            with self._transaction():
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
                if read_only:
                    if version not in (3,4,VERSION):
                        raise ValueError(f"unsupported schema version {version}; initialize/migrate with the tracking CLI first")
                    self.schema_version=version
                    return
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
                if version != VERSION:
                    raise ValueError(f"unsupported schema version {version}")
                self.db.execute(f"PRAGMA user_version={VERSION}")
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
        self.db.execute("BEGIN" if self.read_only else "BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
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

    def manual_history(self, login, *, character_id=None, as_of=None):
        """Operator events, separate from OCR evidence and trusted accounting."""
        streamer = self._channel(login)
        if self.schema_version < 5:
            return []
        where = 'streamer_id=?'; args = [streamer['id']]
        if character_id is not None:
            where += ' AND character_id=?'; args.append(character_id)
        if as_of is not None:
            where += ' AND effective_at<=?'; args.append(utc(as_of))
        return [dict(r) for r in self.db.execute(
            'SELECT * FROM manual_corrections WHERE '+where+' ORDER BY effective_at,id', args)]

    def correct_manual(self, login, event_id, character_id, *, level=None, current_exp=None,
                       percentage_bp=None, effective_at=None, reason=None, clear=False):
        """Append a selected-character baseline adjustment; duplicate IDs are idempotent."""
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 200:
            raise ValueError('event_id must contain 1..200 characters')
        if type(character_id) is not int or character_id < 1 or type(clear) is not bool:
            raise ValueError('invalid character or clear flag')
        for name, value, low, high in (('level',level,1,200), ('current_exp',current_exp,0,2**63-1),
                                      ('percentage_bp',percentage_bp,0,9999)):
            if value is not None and (type(value) is not int or not low <= value <= high):
                raise ValueError(f'{name} must be an integer in {low}..{high}')
        supplied = any(v is not None for v in (level,current_exp,percentage_bp))
        if clear == supplied:
            raise ValueError('supply values or clear, exclusively')
        if reason is not None and (not isinstance(reason,str) or not reason.strip() or len(reason)>1000
                                   or any(ord(c)<32 for c in reason)):
            raise ValueError('reason must contain 1..1000 characters without controls')
        if effective_at is not None and not isinstance(effective_at,datetime):
            raise ValueError('effective timestamp must be a timezone-aware datetime')
        recorded = utc(); when = utc(effective_at) if effective_at is not None else recorded
        if when > recorded:
            raise ValueError('effective timestamp cannot be in the future')
        with self._transaction():
            streamer = self._channel(login)
            existing = self.db.execute('SELECT * FROM manual_corrections WHERE streamer_id=? AND event_id=?',
                                       (streamer['id'],event_id)).fetchone()
            action = 'clear' if clear else 'set'
            if existing:
                expected = (character_id,action,level,current_exp,percentage_bp,reason)
                if tuple(existing[k] for k in ('character_id','action','level','current_exp','percentage_bp','reason')) != expected or (
                        effective_at is not None and existing['effective_at'] != when):
                    raise ValueError('event_id reused with different contents')
                return dict(existing,duplicate=True)
            if streamer['selected_character_id'] != character_id:
                raise ValueError('character must be the channel selected character')
            session = self._open_session(streamer['id'])
            session_id = session['id'] if session else None
            if session and when < session['started_at']:
                raise ValueError('effective timestamp precedes current session')
            previous = self.db.execute('SELECT effective_at FROM manual_corrections WHERE character_id=? '
                'AND session_id IS ? ORDER BY effective_at DESC,id DESC LIMIT 1',(character_id,session_id)).fetchone()
            if previous and when <= previous['effective_at']:
                raise ValueError('effective timestamps must strictly increase within the correction scope')
            row_id = self.db.execute('''INSERT INTO manual_corrections(event_id,streamer_id,character_id,session_id,
                effective_at,recorded_at,action,level,current_exp,percentage_bp,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                (event_id,streamer['id'],character_id,session_id,when,recorded,action,level,current_exp,percentage_bp,reason)).lastrowid
            return dict(self.db.execute('SELECT * FROM manual_corrections WHERE id=?',(row_id,)).fetchone(),duplicate=False)

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
            state = self.db.execute("SELECT * FROM tracking_state WHERE character_id=?", (char,)).fetchone()
            active = bool(session and session["ended_at"] is None and streamer["selected_character_id"] == char)
            ordered = bool(active and when >= session["started_at"] and
                           (state["last_event_at"] is None or when > state["last_event_at"]))
            transition = Transition("rejected", "no_active_session" if not active else "out_of_order")
            interval_start = None
            missing = 0
            if ordered:
                if result.status in {"offline", "paused"}:
                    transition = Transition("rejected", ";".join(result.reasons) or result.status)
                elif profile is None:
                    transition = Transition("rejected", "glyph_profile_required")
                elif result.status != "accepted" or result.reading is None:
                    transition = Transition("rejected", ";".join(result.reasons) or result.status)
                else:
                    previous = self.db.execute("SELECT * FROM observations WHERE id=?", (state["last_trusted_observation_id"],)).fetchone()
                    correction = self.db.execute('SELECT effective_at FROM manual_corrections WHERE session_id=? '
                        'AND effective_at<? ORDER BY effective_at DESC,id DESC LIMIT 1',(session_id,when)).fetchone()
                    if correction and previous and previous['observed_at'] <= correction['effective_at']:
                        previous = None
                    observation = Observation(str(char), datetime.fromisoformat(when), result.reading)
                    prior = Observation(str(char), datetime.fromisoformat(previous["observed_at"]),
                                        Reading(previous["level"], previous["current_exp"], previous["percentage_bp"] / 100)) if previous and previous["session_id"] == session_id else None
                    transition = validate_transition(prior, observation)
                    if transition.status == "accepted" and state["continuity_broken"]:
                        transition = Transition("baseline", "continuity_resumed")
                    if transition.status == "accepted":
                        interval_start = previous["id"]
                        missing = state["pending_missing_observations"]
            trusted = transition.status in {"accepted", "baseline"}
            reading = result.reading if trusted else None
            row_id = self.db.execute("""INSERT INTO observations(
                event_id,streamer_id,session_id,character_id,observed_at,recorded_at,source,profile_hash,diagnostic_json,
                outcome,reason,level,current_exp,percentage_bp,gained_exp,interval_start_observation_id,
                missing_observations) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event_id, streamer["id"], session_id, char, when, utc(), source, fingerprint, diagnostic,
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
        snapshot = dict(channel=streamer["login"], selected_character_id=streamer["selected_character_id"],
                    characters=chars, session=dict(session) if session else None, status=status,
                    reason="stale" if state and status == "paused" and state["status"] == "tracking" else state["reason"] if state else "select_character",
                    last_trusted=dict(last) if last else None, last_event_at=state["last_event_at"] if state else None,
                    age_seconds=age, stale=stale, observed_session_exp=gained, bridged_session_exp=bridged,
                    continuity_broken=bool(state["continuity_broken"]) if state else True,
                    pending_missing_observations=state["pending_missing_observations"] if state else 0)
        snapshot["statistics"] = tracking_statistics(self.db, snapshot, now)
        return snapshot
