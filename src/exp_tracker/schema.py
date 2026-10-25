"""SQLite base schema and additive migrations, applied in one transaction."""

VERSION = 11
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

# Neural evidence has no trusted EXP/gain columns and never changes tracking_state.
MIGRATION_3 = (
    """CREATE TABLE diagnostic_runs (
        run_id TEXT PRIMARY KEY, streamer_id INTEGER NOT NULL,
        character_id INTEGER NOT NULL, session_id INTEGER NOT NULL,
        created_at TEXT NOT NULL, configuration_json TEXT NOT NULL, summary_json TEXT,
        FOREIGN KEY(session_id, character_id, streamer_id)
            REFERENCES sessions(id, character_id, streamer_id)
    )""",
    """CREATE TABLE diagnostic_attempts (
        id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES diagnostic_runs(run_id),
        attempt_index INTEGER NOT NULL CHECK(attempt_index BETWEEN 1 AND 60),
        attempted_at TEXT NOT NULL, received_at TEXT, recorded_at TEXT NOT NULL,
        payload_json TEXT NOT NULL, UNIQUE(run_id, attempt_index)
    )""",
    "CREATE INDEX diagnostic_session ON diagnostic_runs(session_id, created_at)",
)

# Indexed diagnostic ownership is derived from the immutable run binding, not OCR.
MIGRATION_4 = (
    'ALTER TABLE diagnostic_attempts ADD COLUMN session_id INTEGER REFERENCES sessions(id)',
    'UPDATE diagnostic_attempts SET session_id=(SELECT session_id FROM diagnostic_runs WHERE run_id=diagnostic_attempts.run_id)',
    'CREATE INDEX diagnostic_recent ON diagnostic_attempts(session_id,id)',
    'CREATE INDEX diagnostic_time ON diagnostic_attempts(session_id,attempted_at,id)',
    'CREATE INDEX diagnostic_run_order ON diagnostic_runs(session_id)',
    'CREATE INDEX session_listing ON sessions(streamer_id,id)',
)

MIGRATION_5 = (
    """CREATE TABLE manual_corrections (
        id INTEGER PRIMARY KEY, event_id TEXT NOT NULL,
        streamer_id INTEGER NOT NULL REFERENCES streamers(id),
        character_id INTEGER NOT NULL, session_id INTEGER,
        effective_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
        provenance TEXT NOT NULL DEFAULT 'manual_admin' CHECK(provenance='manual_admin'),
        action TEXT NOT NULL CHECK(action IN ('set','clear')),
        level INTEGER CHECK(level BETWEEN 1 AND 200),
        current_exp INTEGER CHECK(current_exp >= 0),
        percentage_bp INTEGER CHECK(percentage_bp BETWEEN 0 AND 9999), reason TEXT,
        CHECK((action='set' AND (level IS NOT NULL OR current_exp IS NOT NULL OR percentage_bp IS NOT NULL))
            OR (action='clear' AND level IS NULL AND current_exp IS NULL AND percentage_bp IS NULL)),
        FOREIGN KEY(character_id,streamer_id) REFERENCES characters(id,streamer_id),
        FOREIGN KEY(session_id,character_id,streamer_id) REFERENCES sessions(id,character_id,streamer_id),
        UNIQUE(streamer_id,event_id)
    )""",
    'CREATE INDEX manual_character_history ON manual_corrections(character_id,effective_at,id)',
    """CREATE TRIGGER manual_no_update BEFORE UPDATE ON manual_corrections
        BEGIN SELECT RAISE(ABORT,'manual corrections are append-only'); END""",
    """CREATE TRIGGER manual_no_delete BEFORE DELETE ON manual_corrections
        BEGIN SELECT RAISE(ABORT,'manual corrections are append-only'); END""",
)

MIGRATION_6 = (
    "ALTER TABLE manual_corrections ADD COLUMN kind TEXT NOT NULL DEFAULT 'baseline' CHECK(kind IN ('baseline','point'))",
    "ALTER TABLE manual_corrections ADD COLUMN operation TEXT NOT NULL DEFAULT 'apply' CHECK(operation IN ('apply','retract'))",
    'ALTER TABLE manual_corrections ADD COLUMN replaces_id INTEGER REFERENCES manual_corrections(id)',
    "ALTER TABLE manual_corrections ADD COLUMN target_kind TEXT CHECK(target_kind IN ('diagnostic','observation'))",
    'ALTER TABLE manual_corrections ADD COLUMN target_event_id TEXT',
    'CREATE UNIQUE INDEX manual_successor ON manual_corrections(replaces_id) WHERE replaces_id IS NOT NULL',
    """CREATE TRIGGER manual_required_fields BEFORE INSERT ON manual_corrections
        WHEN NEW.action='set' AND (NEW.level IS NULL OR (NEW.current_exp IS NULL AND NEW.percentage_bp IS NULL))
        BEGIN SELECT RAISE(ABORT,'new corrections require level and EXP or percentage'); END""",
    """CREATE TABLE character_renames (
        id INTEGER PRIMARY KEY, streamer_id INTEGER NOT NULL REFERENCES streamers(id),
        character_id INTEGER NOT NULL, previous_label TEXT NOT NULL, label TEXT NOT NULL,
        recorded_at TEXT NOT NULL, reason TEXT,
        FOREIGN KEY(character_id,streamer_id) REFERENCES characters(id,streamer_id)
    )""",
    """CREATE TRIGGER rename_no_update BEFORE UPDATE ON character_renames
        BEGIN SELECT RAISE(ABORT,'character renames are append-only'); END""",
    """CREATE TRIGGER rename_no_delete BEFORE DELETE ON character_renames
        BEGIN SELECT RAISE(ABORT,'character renames are append-only'); END""",
)

# Membership is staged in small transactions. Only an append-only commit publishes a batch.
MIGRATION_7 = (
    """CREATE INDEX diagnostic_receipt ON diagnostic_attempts(
        CASE WHEN LENGTH(COALESCE(received_at,attempted_at))=25
            THEN SUBSTR(COALESCE(received_at,attempted_at),1,19)||'.000000+00:00'
            ELSE COALESCE(received_at,attempted_at) END,run_id,id)""",
    """CREATE TABLE reading_batches (
        id INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, streamer_id INTEGER NOT NULL REFERENCES streamers(id),
        character_id INTEGER NOT NULL, action TEXT NOT NULL CHECK(action IN ('invalidate','restore')),
        selection_json TEXT NOT NULL, fingerprint TEXT NOT NULL, recorded_at TEXT NOT NULL, reason TEXT,
        expected_count INTEGER NOT NULL CHECK(expected_count BETWEEN 1 AND 20000),
        provenance TEXT NOT NULL DEFAULT 'manual_admin' CHECK(provenance='manual_admin'),
        FOREIGN KEY(character_id,streamer_id) REFERENCES characters(id,streamer_id)
    )""",
    """CREATE TABLE reading_events (
        id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES reading_batches(id),
        kind TEXT NOT NULL CHECK(kind IN ('diagnostic','observation')), source_id INTEGER NOT NULL,
        target_event_id TEXT NOT NULL, session_id INTEGER NOT NULL REFERENCES sessions(id), original_at TEXT NOT NULL,
        UNIQUE(batch_id,kind,source_id)
    )""",
    'CREATE INDEX reading_event_target ON reading_events(kind,source_id,id DESC)',
    """CREATE TABLE reading_commits (
        id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL UNIQUE REFERENCES reading_batches(id), recorded_at TEXT NOT NULL
    )""",
    """CREATE VIEW reading_validity AS SELECT e.*,b.action,b.streamer_id,b.character_id,b.reason,c.recorded_at
        FROM reading_events e JOIN reading_batches b ON b.id=e.batch_id JOIN reading_commits c ON c.batch_id=b.id
        WHERE e.id=(SELECT MAX(n.id) FROM reading_events n JOIN reading_commits nc ON nc.batch_id=n.batch_id
                    WHERE n.kind=e.kind AND n.source_id=e.source_id)""",
    """CREATE TRIGGER reading_membership_sealed BEFORE INSERT ON reading_events
        WHEN EXISTS(SELECT 1 FROM reading_commits WHERE batch_id=NEW.batch_id)
        BEGIN SELECT RAISE(ABORT,'batch already committed'); END""",
    """CREATE TRIGGER reading_membership_owner BEFORE INSERT ON reading_events
        WHEN NOT EXISTS(SELECT 1 FROM sessions s JOIN reading_batches b ON b.id=NEW.batch_id
            WHERE s.id=NEW.session_id AND s.streamer_id=b.streamer_id AND s.character_id=b.character_id)
        BEGIN SELECT RAISE(ABORT,'reading batch ownership mismatch'); END""",
    """CREATE TRIGGER reading_batch_complete BEFORE INSERT ON reading_commits
        WHEN (SELECT COUNT(*) FROM reading_events WHERE batch_id=NEW.batch_id) !=
             (SELECT expected_count FROM reading_batches WHERE id=NEW.batch_id)
        BEGIN SELECT RAISE(ABORT,'reading batch is incomplete'); END""",
    *tuple(f"""CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table}
        BEGIN SELECT RAISE(ABORT,'reading validity audit is append-only'); END"""
        for table in ('reading_batches','reading_events','reading_commits') for action in ('UPDATE','DELETE')),
)

# Raw evidence expires; these checkpoints and the administration audit do not.
MIGRATION_8 = (
    """CREATE TABLE retention_state (
        character_id INTEGER PRIMARY KEY REFERENCES characters(id),
        cutoff TEXT NOT NULL, checkpoint_json TEXT NOT NULL
    )""",
    """CREATE TABLE trusted_checkpoints (
        session_id INTEGER PRIMARY KEY REFERENCES sessions(id),
        through_id INTEGER NOT NULL, checkpoint_json TEXT NOT NULL,
        original_gain INTEGER NOT NULL, original_bridged INTEGER NOT NULL
    )""",
    """CREATE TABLE retention_meta (
        id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL DEFAULT 0,
        attempt_id INTEGER NOT NULL DEFAULT 0, observation_id INTEGER NOT NULL DEFAULT 0,
        run_id INTEGER NOT NULL DEFAULT 0
    )""",
    'INSERT INTO retention_meta(id) VALUES(1)',
)

MIGRATION_9 = (
    """CREATE TABLE daily_character_exp (
        character_id INTEGER NOT NULL REFERENCES characters(id),
        utc_date TEXT NOT NULL, observed_at TEXT NOT NULL,
        level INTEGER CHECK(level BETWEEN 1 AND 200),
        current_exp INTEGER CHECK(current_exp >= 0),
        percentage_bp INTEGER CHECK(percentage_bp BETWEEN 0 AND 9999),
        source TEXT NOT NULL CHECK(source IN ('diagnostic','trusted_ocr','manual_correction')),
        level_basis TEXT, exp_basis TEXT, percentage_basis TEXT,
        CHECK(current_exp IS NOT NULL OR percentage_bp IS NOT NULL),
        CHECK(utc_date=substr(observed_at,1,10)),
        PRIMARY KEY(character_id,utc_date)
    ) WITHOUT ROWID""",
)

# Independent of expiring capture evidence and sessions; never erased by retention.
MIGRATION_10 = (
    """CREATE TABLE character_level_guard (
        character_id INTEGER PRIMARY KEY REFERENCES characters(id),
        level INTEGER CHECK(level BETWEEN 1 AND 200), proof_json TEXT,
        pending_json TEXT, updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE automatic_character_events (
        event_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
        streamer_id INTEGER NOT NULL REFERENCES streamers(id),
        character_id INTEGER NOT NULL REFERENCES characters(id),
        run_id TEXT NOT NULL, receipt_json TEXT NOT NULL, recorded_at TEXT NOT NULL
    )""",
    """CREATE TRIGGER character_level_no_regression BEFORE UPDATE ON character_level_guard
        WHEN OLD.level IS NOT NULL AND (NEW.level IS NULL OR NEW.level < OLD.level)
        BEGIN SELECT RAISE(ABORT,'validated character level cannot regress'); END""",
)

# Operator decisions that a detected character is not the streamer's own (e.g. another player's video), and restores.
# Additive and independent of the versioned capture tables: writable stores create it at schema 10 and later.
CHARACTER_INVALIDATIONS = '''CREATE TABLE IF NOT EXISTS character_invalidations (
    id INTEGER PRIMARY KEY, streamer_id INTEGER NOT NULL, character_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('invalidate','restore')), label TEXT NOT NULL,
    reason TEXT NOT NULL, recorded_at TEXT NOT NULL,
    FOREIGN KEY(character_id, streamer_id) REFERENCES characters(id, streamer_id)
)'''

# Each character's job, read from the status panel or set by the operator. Append-only and
# additive like character_invalidations; the latest row is the job (NULL clears an entry).
CHARACTER_JOBS = '''CREATE TABLE IF NOT EXISTS character_jobs (
    id INTEGER PRIMARY KEY, character_id INTEGER NOT NULL REFERENCES characters(id), job TEXT,
    source TEXT NOT NULL CHECK(source IN ('ocr','manual_admin')), evidence_json TEXT, recorded_at TEXT NOT NULL
)'''

# Desired settings are separate from immutable capture ownership and operational status.
MIGRATION_11 = (
    '''CREATE TABLE streamer_capture (
        streamer_id INTEGER PRIMARY KEY REFERENCES streamers(id),
        authorized INTEGER NOT NULL CHECK(authorized IN (0,1)),
        tracking_enabled INTEGER NOT NULL CHECK(tracking_enabled IN (0,1)),
        public_visible INTEGER NOT NULL CHECK(public_visible IN (0,1)),
        automatic_characters INTEGER NOT NULL CHECK(automatic_characters IN (0,1)),
        settings_json TEXT NOT NULL, origin TEXT NOT NULL CHECK(origin IN ('existing','discovered')),
        revision INTEGER NOT NULL CHECK(revision>0), updated_at TEXT NOT NULL,
        identity_json TEXT
    )''',
    '''CREATE TABLE streamer_roster_events (
        event_id TEXT PRIMARY KEY, streamer_id INTEGER NOT NULL REFERENCES streamers(id),
        fingerprint TEXT NOT NULL, before_json TEXT, after_json TEXT NOT NULL,
        reason TEXT NOT NULL, recorded_at TEXT NOT NULL
    )''',
    '''CREATE TABLE streamer_roster_bootstrap (
        id INTEGER PRIMARY KEY CHECK(id=1), fingerprint TEXT NOT NULL, recorded_at TEXT NOT NULL
    )''',
    '''CREATE TABLE streamer_runtime (
        streamer_id INTEGER PRIMARY KEY REFERENCES streamers(id),
        revision INTEGER NOT NULL, state TEXT NOT NULL, run_id TEXT,
        error TEXT, last_attempt_at TEXT, heartbeat_at TEXT NOT NULL
    )''',
)
