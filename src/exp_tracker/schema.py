"""SQLite base schema and additive migrations, applied in one transaction."""

VERSION = 2
STATEMENTS = (
    """CREATE TABLE streamers (
        id INTEGER PRIMARY KEY, login TEXT NOT NULL UNIQUE,
        selected_character_id INTEGER,
        FOREIGN KEY(selected_character_id, id) REFERENCES characters(id, streamer_id)
    )""",
    """CREATE TABLE characters (
        id INTEGER PRIMARY KEY, streamer_id INTEGER NOT NULL REFERENCES streamers(id),
        label TEXT NOT NULL, UNIQUE(streamer_id, label), UNIQUE(id, streamer_id)
    )""",
    """CREATE TABLE sessions (
        id INTEGER PRIMARY KEY, streamer_id INTEGER NOT NULL, character_id INTEGER NOT NULL,
        started_at TEXT NOT NULL, ended_at TEXT, end_reason TEXT,
        CHECK(ended_at IS NULL OR ended_at >= started_at),
        FOREIGN KEY(character_id, streamer_id) REFERENCES characters(id, streamer_id),
        UNIQUE(id, character_id, streamer_id)
    )""",
    "CREATE UNIQUE INDEX one_open_session ON sessions(streamer_id) WHERE ended_at IS NULL",
    """CREATE TABLE observations (
        id INTEGER PRIMARY KEY, event_id TEXT NOT NULL, streamer_id INTEGER NOT NULL REFERENCES streamers(id),
        session_id INTEGER, character_id INTEGER, observed_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
        source TEXT NOT NULL, profile_hash TEXT, diagnostic_json TEXT NOT NULL,
        outcome TEXT NOT NULL CHECK(outcome IN ('baseline','accepted','rejected','ambiguous')),
        reason TEXT NOT NULL, level INTEGER CHECK(level BETWEEN 1 AND 200),
        current_exp INTEGER CHECK(current_exp >= 0), percentage_bp INTEGER CHECK(percentage_bp BETWEEN 0 AND 9999),
        gained_exp INTEGER CHECK(gained_exp >= 0),
        CHECK(outcome NOT IN ('baseline','accepted') OR
            (profile_hash IS NOT NULL AND session_id IS NOT NULL AND character_id IS NOT NULL
             AND level IS NOT NULL AND current_exp IS NOT NULL AND percentage_bp IS NOT NULL)),
        CHECK(outcome = 'accepted' OR gained_exp IS NULL),
        FOREIGN KEY(character_id, streamer_id) REFERENCES characters(id, streamer_id),
        FOREIGN KEY(session_id, character_id, streamer_id) REFERENCES sessions(id, character_id, streamer_id),
        UNIQUE(streamer_id, event_id), UNIQUE(id, character_id)
    )""",
    "CREATE INDEX character_history ON observations(character_id, observed_at, id)",
    """CREATE TABLE tracking_state (
        character_id INTEGER PRIMARY KEY REFERENCES characters(id),
        last_trusted_observation_id INTEGER, last_event_at TEXT,
        status TEXT NOT NULL DEFAULT 'waiting', reason TEXT NOT NULL DEFAULT 'no_observation',
        FOREIGN KEY(last_trusted_observation_id, character_id) REFERENCES observations(id, character_id)
    )""",
)

MIGRATION_2 = (
    """ALTER TABLE observations ADD COLUMN interval_start_observation_id INTEGER REFERENCES observations(id)
       CHECK(interval_start_observation_id IS NULL OR outcome='accepted')""",
    """ALTER TABLE observations ADD COLUMN missing_observations INTEGER NOT NULL DEFAULT 0
       CHECK(missing_observations >= 0 AND (missing_observations=0 OR interval_start_observation_id IS NOT NULL))""",
    """ALTER TABLE tracking_state ADD COLUMN continuity_broken INTEGER NOT NULL DEFAULT 0
       CHECK(continuity_broken IN (0,1))""",
    """ALTER TABLE tracking_state ADD COLUMN pending_missing_observations INTEGER NOT NULL DEFAULT 0
       CHECK(pending_missing_observations >= 0)""",
    # Version 1 pauses had no soft/hard distinction; never reinterpret their gains.
    "UPDATE tracking_state SET continuity_broken=1 WHERE status != 'tracking'",
)
