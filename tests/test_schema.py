from pathlib import Path
import sqlite3

import pytest


def test_schema_enforces_character_and_session_ownership():
    schema = Path(__file__).resolve().parents[1] / "docs/schema.sql"
    with sqlite3.connect(":memory:") as db:
        db.executescript(schema.read_text(encoding="utf-8"))
        db.executemany("INSERT INTO streamers VALUES (?, ?, ?, ?)", [(1, "111", "alice", 0), (2, "222", "bob", 0)])
        db.executemany("INSERT INTO characters (id, streamer_id, label) VALUES (?, ?, ?)", [(1, 1, "mage"), (2, 2, "warrior")])
        db.execute("INSERT INTO sessions (id, streamer_id, character_id, started_at) VALUES (1, 1, 1, 0)")
        db.execute("INSERT INTO observations (id, session_id, character_id, received_at, acquisition, level, current_exp, percentage_bp, status) VALUES (1, 1, 1, 0, 'local', 25, 1000, 1000, 'baseline')")
        db.execute("INSERT INTO tracking_state (streamer_id, active_character_id, active_session_id, last_accepted_observation_id, updated_at) VALUES (1, 1, 1, 1, 0)")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO sessions (streamer_id, character_id, started_at) VALUES (1, 2, 0)")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO observations (session_id, character_id, received_at, acquisition, status) VALUES (1, 2, 0, 'local', 'unreadable')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO tracking_state (streamer_id, active_character_id, active_session_id, updated_at) VALUES (2, 2, 1, 0)")
