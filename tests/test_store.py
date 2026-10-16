from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest

from exp_tracker.glyphs import GlyphProfile, SYMBOLS
from exp_tracker.models import Reading, Recognition
from exp_tracker.schema import STATEMENTS, VERSION
from exp_tracker.store import Store


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def at(seconds):
    return START + timedelta(seconds=seconds)


def reading(exp=1000, percent=10, level=60):
    return Recognition("accepted", Reading(level, exp, percent), .99,
                       raw={"exp": [dict(variant="pixel", text=f"{exp:,}[{percent:.2f}%]", confidence=.99)]})


@pytest.fixture
def profile():
    return GlyphProfile(9, {c: 6 for c in SYMBOLS}, {c: (1 << i,) for i, c in enumerate(SYMBOLS)})


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "tracker.sqlite3") as db:
        db.add_channel("alice")
        char = db.add_character("alice", "Mage")
        db.select_character("alice", char, at=at(0))
        db.start_session("alice", at=at(0))
        yield db


def ingest(store, profile, event="one", seconds=1, result=None, **kwargs):
    session = store.state("alice", as_of=at(seconds))["session"]
    return store.ingest("alice", event, at(seconds), result if result is not None else reading(),
                        profile=profile, session_id=session["id"] if session else None, **kwargs)


def test_schema_version_foreign_keys_and_ownership(store, profile):
    assert store.db.execute("PRAGMA user_version").fetchone()[0] == VERSION
    assert store.db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    store.add_channel("bob")
    other = store.add_character("bob", "Warrior")
    with pytest.raises(ValueError, match="belong"):
        store.select_character("alice", other)
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute("UPDATE streamers SET selected_character_id=? WHERE login='alice'", (other,))
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute("INSERT INTO sessions(streamer_id,character_id,started_at) VALUES (1,?,'2026')", (other,))
    trusted = ingest(store, profile)
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute("UPDATE tracking_state SET last_trusted_observation_id=? WHERE character_id=?",
                         (trusted["id"], other))


@pytest.mark.parametrize("version", [0, VERSION + 1])
def test_refuse_unknown_or_unversioned_existing_database(tmp_path, version):
    path = tmp_path / "existing.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE existing(value)")
        db.execute(f"PRAGMA user_version={version}")
    with pytest.raises(ValueError):
        Store(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM existing").fetchone()[0] == 0


def test_same_level_large_gains_and_event_idempotency(store, profile):
    first = ingest(store, profile)
    assert first["outcome"] == "baseline" and first["gained_exp"] is None
    large = ingest(store, profile, "large", 2, reading(999999, 82.64))
    assert (large["outcome"], large["gained_exp"]) == ("accepted", 998999)
    replay = ingest(store, profile, "large", 2, reading(999999, 82.64))
    assert replay["duplicate"] and replay["id"] == large["id"]
    assert store.state("alice", as_of=at(2))["observed_session_exp"] == 998999
    assert store.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 2
    with pytest.raises(ValueError, match="different contents"):
        ingest(store, profile, "large", 3, reading(1000000, 82.65))
    assert store.state("alice")["last_trusted"]["id"] == large["id"]


@pytest.mark.parametrize("evidence", ["unprofiled", "fallback", "mismatch", "invalid"])
def test_diagnostics_never_become_trusted(store, profile, evidence):
    first = ingest(store, profile)
    candidate = reading(1500, 15)
    supplied = profile
    if evidence == "unprofiled":
        supplied = None
    elif evidence == "fallback":
        candidate.raw = {"exp": [dict(variant="unrestricted-line", text="1,500[15.00%]", confidence=.99)]}
    elif evidence == "mismatch":
        candidate.raw["exp"][0]["text"] = "1,500[15.01%]"
    else:
        candidate = reading(1500, 15, level=201)
    outcome = ingest(store, supplied, evidence, 2, candidate)
    assert outcome["outcome"] == "rejected"
    assert outcome["current_exp"] is None
    assert json.loads(outcome["diagnostic_json"])["reading"]["current_exp"] == 1500
    assert store.state("alice")["last_trusted"]["id"] == first["id"]


@pytest.mark.parametrize("status", ["unreadable", "missing_hud", "low_confidence", "invalid", "ambiguous",
                                   "capture_failed", "processing_failed", "offline", "paused", "unknown_failure"])
def test_failures_preserve_reading_and_distinguish_continuity(store, profile, status):
    first = ingest(store, profile)
    ingest(store, profile, "failed", 2, Recognition(status))
    state = store.state("alice", as_of=at(2))
    assert state["last_trusted"]["id"] == first["id"]
    assert state["last_trusted"]["observed_at"] == at(1).isoformat(timespec="microseconds")
    assert state["status"] == ("offline" if status == "offline" else "paused")
    soft = status in {"unreadable", "missing_hud", "low_confidence", "invalid", "ambiguous"}
    assert state["continuity_broken"] is not soft
    resumed = ingest(store, profile, "resumed", 3, reading(2000, 20))
    assert resumed["outcome"] == ("accepted" if soft else "baseline")
    assert resumed["gained_exp"] == (1000 if soft else None)
    assert resumed["interval_start_observation_id"] == (first["id"] if soft else None)
    assert resumed["missing_observations"] == int(soft)
    ingest(store, profile, "after", 4, reading(2500, 25))
    assert store.state("alice", as_of=at(4))["observed_session_exp"] == (1500 if soft else 500)


def test_out_of_order_readings_and_failures_cannot_replace_state(store, profile):
    first = ingest(store, profile, seconds=10)
    for i, candidate in enumerate((reading(2000, 20), Recognition("offline"))):
        rejected = ingest(store, profile, f"late-{i}", 5, candidate)
        assert rejected["reason"] == "out_of_order"
    assert ingest(store, profile, "same-time", 10)["reason"] == "out_of_order"
    state = store.state("alice", as_of=at(11))
    assert state["last_trusted"]["id"] == first["id"] and state["status"] == "tracking"
    assert state["last_event_at"] == at(10).isoformat(timespec="microseconds")
    current = ingest(store, profile, "current", 11, reading(1500, 15))
    assert current["gained_exp"] == 500 and current["missing_observations"] == 0


def test_gap_and_staleness_do_not_count_unobserved_gain(store, profile):
    ingest(store, profile)
    assert store.state("alice", as_of=at(122))["status"] == "paused"
    gap = ingest(store, profile, "gap", 200, reading(5000, 50))
    assert gap["outcome"] == "baseline" and gap["gained_exp"] is None
    assert store.state("alice", as_of=at(200))["observed_session_exp"] == 0
    assert not store.state("alice", as_of=at(200))["stale"]


@pytest.mark.parametrize("candidate,reason", [
    (reading(0, 0, level=61), "level_change_requires_confirmation"),
    (reading(900, 9), "reset_loss_or_character_switch"),
    (reading(1000, 9), "reset_loss_or_character_switch"),
    (reading(1000, 11), "unchanged_exp_with_changed_percentage"),
])
def test_ambiguous_transitions_preserve_evidence_and_baseline(store, profile, candidate, reason):
    first = ingest(store, profile)
    outcome = ingest(store, profile, "change", 2, candidate)
    assert outcome["reason"] == reason and outcome["gained_exp"] is None
    assert json.loads(outcome["diagnostic_json"])["reading"]["level"] == candidate.reading.level
    assert store.state("alice")["last_trusted"]["id"] == first["id"]


def test_explicit_new_session_can_rebaseline_after_level_change(store, profile):
    ingest(store, profile)
    ingest(store, profile, "level-up", 2, reading(0, 0, level=61))
    ingest(store, profile, "unreadable", 2.5, Recognition("unreadable"))
    store.end_session("alice", at=at(3))
    old_session = store.db.execute("SELECT id FROM sessions").fetchone()[0]
    new_session = store.start_session("alice", at=at(4))
    assert old_session != new_session
    new = ingest(store, profile, "confirmed", 5, reading(100, 1, level=61))
    assert new["outcome"] == "baseline" and new["gained_exp"] is None
    assert store.state("alice", as_of=at(5))["last_trusted"]["level"] == 61


def test_explicit_selection_sessions_and_separate_histories(store, profile):
    a = store.state("alice")["selected_character_id"]
    first = ingest(store, profile)
    ingest(store, profile, "unreadable-a", 1.5, Recognition("unreadable"))
    b = store.add_character("alice", "Bowman")
    store.select_character("alice", b, at=at(2))
    assert store.state("alice")["session"] is None
    assert store.state("alice")["last_trusted"] is None
    old = store.ingest("alice", "old-inflight", at(3), reading(2000, 20), profile=profile, session_id=first["session_id"])
    assert old["outcome"] == "rejected"
    store.start_session("alice", at=at(3))
    b_reading = ingest(store, profile, "b-first", 4, reading(500, 5))
    assert b_reading["outcome"] == "baseline"
    assert b_reading["missing_observations"] == 0
    # A replay remains assigned to A even after B became active.
    replay = store.ingest("alice", "one", at(1), reading(), profile=profile, session_id=first["session_id"])
    assert replay["duplicate"] and replay["character_id"] == a
    store.select_character("alice", a, at=at(5))
    assert store.state("alice")["last_trusted"]["id"] == first["id"]
    store.start_session("alice", at=at(6))
    assert ingest(store, profile, "a-return", 7, reading(3000, 30))["outcome"] == "baseline"
    assert store.state("alice")["observed_session_exp"] == 0


def test_no_implicit_character_or_session(tmp_path, profile):
    with Store(tmp_path / "new.sqlite3") as db:
        db.add_channel("alice")
        db.add_character("alice", "Mage")
        with pytest.raises(ValueError, match="select"):
            db.start_session("alice", at=at(0))
        outcome = db.ingest("alice", "unassigned", at(1), reading(), profile=profile)
        assert outcome["outcome"] == "rejected" and outcome["character_id"] is None
        assert db.state("alice")["last_trusted"] is None


def test_atomic_rollback_and_retry(store, profile):
    first = ingest(store, profile)
    store.db.execute("""CREATE TRIGGER fail_state BEFORE UPDATE ON tracking_state
                      BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        ingest(store, profile, "retry", 2, reading(2000, 20))
    assert store.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    assert store.state("alice")["last_trusted"]["id"] == first["id"]
    store.db.execute("DROP TRIGGER fail_state")
    assert ingest(store, profile, "retry", 2, reading(2000, 20))["gained_exp"] == 1000


def test_restart_restores_state_and_replay_does_not_start_new_session(tmp_path, profile):
    path = tmp_path / "restart.sqlite3"
    with Store(path) as db:
        db.add_channel("alice")
        char = db.add_character("alice", "Mage")
        db.select_character("alice", char, at=at(0))
        session = db.start_session("alice", at=at(0))
        first = ingest(db, profile)
    with Store(path) as restarted:
        assert restarted.state("alice", as_of=at(2))["selected_character_id"] == char
        assert restarted.start_session("alice", at=at(2)) == session
        assert restarted.state("alice", as_of=at(2))["last_trusted"]["id"] == first["id"]
        assert ingest(restarted, profile)["duplicate"]
        assert ingest(restarted, profile, "next", 2, reading(2000, 20))["gained_exp"] == 1000
        with Store(path) as second_worker:
            assert ingest(second_worker, profile, "third", 3, reading(2500, 25))["gained_exp"] == 500
        assert restarted.state("alice", as_of=at(3))["observed_session_exp"] == 1500


def test_timestamp_validation_and_utc_normalization(store, profile):
    with pytest.raises(ValueError, match="timezone"):
        store.ingest("alice", "naive", START.replace(tzinfo=None), reading(), profile=profile, session_id=1)
    offset = at(1).astimezone(timezone(timedelta(hours=-5)))
    outcome = store.ingest("alice", "offset", offset, reading(), profile=profile, session_id=1)
    assert outcome["observed_at"] == at(1).isoformat(timespec="microseconds")


def test_end_start_idempotency_and_control_ordering(store, profile):
    ingest(store, profile)
    session = store.start_session("alice", at=at(2))
    assert session == store.start_session("alice", at=at(3))
    with pytest.raises(ValueError):
        store.end_session("alice", at=at(0))
    store.end_session("alice", at=at(10))
    store.end_session("alice", at=at(11))
    assert store.state("alice")["status"] == "stopped"
    with pytest.raises(ValueError):
        store.start_session("alice", at=at(5))


@pytest.mark.parametrize("end,expected", [(30, 1000), (121, 1000), (122, None), (300, None)])
def test_multiple_ocr_rejections_use_trusted_endpoint_gap(store, profile, end, expected):
    first = ingest(store, profile)
    for second in (2, 3, end - 1):
        ingest(store, profile, f"failure-{second}", second, Recognition("unreadable"))
    assert store.state("alice", as_of=at(end - 1))["pending_missing_observations"] == 3
    resumed = ingest(store, profile, "resumed", end, reading(2000, 20))
    assert resumed["gained_exp"] == expected
    assert resumed["missing_observations"] == (3 if expected else 0)
    assert resumed["interval_start_observation_id"] == (first["id"] if expected else None)
    state = store.state("alice", as_of=at(end))
    assert state["observed_session_exp"] == state["bridged_session_exp"] == (expected or 0)
    assert state["pending_missing_observations"] == 0


@pytest.mark.parametrize("exp,percent,gain", [(1000, 10, 0), (999999, 82.64, 998999)])
def test_bridge_unchanged_or_large_gain_without_rate_cap(store, profile, exp, percent, gain):
    ingest(store, profile)
    ingest(store, profile, "failed", 2, Recognition("unreadable"))
    resumed = ingest(store, profile, "resumed", 3, reading(exp, percent))
    assert resumed["outcome"] == "accepted" and resumed["gained_exp"] == gain
    assert resumed["missing_observations"] == 1


@pytest.mark.parametrize("hard", [Recognition("offline"), Recognition("paused", reasons=["explicit_pause"]),
                                 reading(900, 9), reading(0, 0, level=61), reading(1000, 11)])
def test_ocr_failure_cannot_erase_hard_break_even_after_restart(store, profile, hard):
    first = ingest(store, profile)
    ingest(store, profile, "hard-break", 2, hard)
    ingest(store, profile, "unreadable-after-break", 3, Recognition("unreadable"))
    path = store.db.execute("PRAGMA database_list").fetchone()[2]
    with Store(path) as restarted:
        state = restarted.state("alice", as_of=at(3))
        assert state["continuity_broken"]
        assert state["last_trusted"]["id"] == first["id"]
        resumed = ingest(restarted, profile, "resumed", 4, reading(2000, 20))
        assert resumed["outcome"] == "baseline" and resumed["gained_exp"] is None
        assert resumed["missing_observations"] == 0
        assert restarted.state("alice", as_of=at(4))["observed_session_exp"] == 0


def test_explicit_unprofiled_pause_is_hard(store, profile):
    ingest(store, profile)
    paused = ingest(store, None, "pause", 2, Recognition("paused", reasons=["explicit_pause"]))
    assert paused["reason"] == "explicit_pause"
    assert store.state("alice")["continuity_broken"]
    assert ingest(store, profile, "resumed", 3, reading(2000, 20))["gained_exp"] is None


def test_unverified_fallback_is_only_missing_evidence_not_trusted_exp(store, profile):
    first = ingest(store, profile)
    fallback = reading(999999, 82.64)
    fallback.raw = {"exp": [dict(variant="unrestricted-line", text="999,999[82.64%]", confidence=.99)]}
    rejected = ingest(store, profile, "fallback", 2, fallback)
    assert rejected["reason"] == "unverified_tesseract_exp" and rejected["current_exp"] is None
    assert store.state("alice")["last_trusted"]["id"] == first["id"]
    resumed = ingest(store, profile, "resumed", 3, reading(1500, 15))
    assert resumed["gained_exp"] == 500 and resumed["missing_observations"] == 1


def test_bridge_restart_replay_and_rollback_are_atomic(store, profile):
    first = ingest(store, profile)
    failure = Recognition("unreadable")
    ingest(store, profile, "failure", 2, failure)
    path = store.db.execute("PRAGMA database_list").fetchone()[2]
    with Store(path) as restarted:
        assert ingest(restarted, profile, "failure", 2, failure)["duplicate"]
        assert restarted.state("alice")["pending_missing_observations"] == 1
        restarted.db.execute("""CREATE TRIGGER fail_bridge BEFORE UPDATE ON tracking_state
                                BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
        with pytest.raises(sqlite3.IntegrityError, match="injected"):
            ingest(restarted, profile, "resumed", 3, reading(2000, 20))
        assert restarted.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 2
        state = restarted.state("alice")
        assert state["last_trusted"]["id"] == first["id"]
        assert state["pending_missing_observations"] == 1 and state["observed_session_exp"] == 0
        restarted.db.execute("DROP TRIGGER fail_bridge")
        resumed = ingest(restarted, profile, "resumed", 3, reading(2000, 20))
        assert resumed["gained_exp"] == 1000 and resumed["missing_observations"] == 1
    with Store(path) as restarted:
        replay = ingest(restarted, profile, "resumed", 3, reading(2000, 20))
        assert replay["duplicate"] and replay["interval_start_observation_id"] == first["id"]
        state = restarted.state("alice", as_of=at(4))
        assert state["observed_session_exp"] == state["bridged_session_exp"] == 1000
        assert state["pending_missing_observations"] == 0


@pytest.mark.parametrize("status", ["tracking", "paused", "offline", "ambiguous"])
def test_version_one_migration_preserves_history_and_conservative_pauses(store, profile, tmp_path, status):
    ingest(store, profile)
    ingest(store, profile, "gain", 2, reading(1500, 15))
    store.db.execute("UPDATE tracking_state SET status=?", (status,))
    path = tmp_path / "version-one.sqlite3"
    with sqlite3.connect(path) as legacy:
        for statement in STATEMENTS:
            legacy.execute(statement)
        for table in ("streamers", "characters", "sessions", "observations", "tracking_state"):
            columns = ",".join(row[1] for row in legacy.execute(f"PRAGMA table_info({table})"))
            rows = store.db.execute(f"SELECT {columns} FROM {table}").fetchall()
            marks = ",".join("?" for _ in rows[0])
            legacy.executemany(f"INSERT INTO {table}({columns}) VALUES ({marks})", rows)
        legacy.execute("PRAGMA user_version=1")
    with Store(path) as migrated:
        assert migrated.db.execute("PRAGMA user_version").fetchone()[0] == VERSION
        assert not migrated.db.execute("PRAGMA foreign_key_check").fetchall()
        state = migrated.state("alice", as_of=at(3))
        assert state["observed_session_exp"] == 500 and state["bridged_session_exp"] == 0
        assert state["continuity_broken"] == (status != "tracking")
        assert ingest(migrated, profile, "gain", 2, reading(1500, 15))["duplicate"]
        resumed = ingest(migrated, profile, "new", 3, reading(2000, 20))
        assert resumed["gained_exp"] == (500 if status == "tracking" else None)
