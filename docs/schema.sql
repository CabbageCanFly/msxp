-- Design sketch, not an application migration. All timestamps are UTC epoch seconds.
PRAGMA foreign_keys = ON;

CREATE TABLE streamers (
    id INTEGER PRIMARY KEY,
    twitch_user_id TEXT NOT NULL UNIQUE,
    twitch_login TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE characters (
    id INTEGER PRIMARY KEY,
    streamer_id INTEGER NOT NULL REFERENCES streamers(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    world TEXT,
    ruleset_version TEXT, -- identifies a future verified EXP table, not guessed from HUD
    archived_at INTEGER,
    UNIQUE (streamer_id, label),
    UNIQUE (id, streamer_id)
);

CREATE TABLE sessions (
    id INTEGER PRIMARY KEY,
    streamer_id INTEGER NOT NULL,
    character_id INTEGER NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    end_reason TEXT,
    CHECK (ended_at IS NULL OR ended_at >= started_at),
    FOREIGN KEY (character_id, streamer_id) REFERENCES characters(id, streamer_id) ON DELETE CASCADE,
    UNIQUE (id, character_id),
    UNIQUE (id, character_id, streamer_id)
);
CREATE UNIQUE INDEX one_open_session_per_streamer ON sessions(streamer_id) WHERE ended_at IS NULL;

CREATE TABLE observations (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    character_id INTEGER NOT NULL,
    received_at INTEGER NOT NULL,
    captured_at INTEGER, -- NULL for thumbnail timestamps that cannot be established
    acquisition TEXT NOT NULL CHECK (acquisition IN ('thumbnail', 'obs', 'local')),
    frame_hash TEXT,
    level INTEGER CHECK (level BETWEEN 1 AND 200),
    current_exp INTEGER CHECK (current_exp >= 0),
    percentage_bp INTEGER CHECK (percentage_bp BETWEEN 0 AND 9999),
    confidence REAL CHECK (confidence BETWEEN 0 AND 1),
    status TEXT NOT NULL CHECK (status IN ('accepted', 'rejected', 'ambiguous', 'unreadable', 'baseline')),
    reason TEXT,
    CHECK (status NOT IN ('accepted', 'baseline') OR
           (level IS NOT NULL AND current_exp IS NOT NULL AND percentage_bp IS NOT NULL)),
    FOREIGN KEY (session_id, character_id) REFERENCES sessions(id, character_id) ON DELETE CASCADE,
    UNIQUE (id, session_id, character_id)
);
CREATE INDEX observations_history ON observations(character_id, received_at, id);

CREATE TABLE tracking_state (
    streamer_id INTEGER PRIMARY KEY REFERENCES streamers(id) ON DELETE CASCADE,
    active_character_id INTEGER,
    active_session_id INTEGER,
    last_accepted_observation_id INTEGER,
    last_successful_read_at INTEGER,
    last_frame_change_at INTEGER,
    state TEXT NOT NULL DEFAULT 'unconfigured' CHECK
        (state IN ('unconfigured', 'waiting', 'tracking', 'paused', 'ambiguous', 'offline')),
    reason TEXT,
    acquisition TEXT CHECK (acquisition IN ('thumbnail', 'obs', 'local')),
    poll_seconds INTEGER NOT NULL DEFAULT 60 CHECK (poll_seconds >= 30),
    roi_json TEXT, -- versioned normalized field ROIs; application validates JSON/shape
    updated_at INTEGER NOT NULL,
    CHECK (active_session_id IS NULL OR active_character_id IS NOT NULL),
    CHECK (last_accepted_observation_id IS NULL OR active_session_id IS NOT NULL),
    FOREIGN KEY (active_character_id, streamer_id) REFERENCES characters(id, streamer_id),
    FOREIGN KEY (active_session_id, active_character_id, streamer_id)
        REFERENCES sessions(id, character_id, streamer_id),
    FOREIGN KEY (last_accepted_observation_id, active_session_id, active_character_id)
        REFERENCES observations(id, session_id, character_id)
);

-- A future service must also verify that last_accepted_observation_id points to
-- an accepted/baseline row, atomically update state and close/open sessions, and
-- clear state pointers before deleting history. Credentials do not belong here.
