# Minimal durable tracking

Diagnostic-only follow-up: [continuous history and backup](continuous-alpha.md).
Schema 4 adds indexed diagnostic session lookup without changing trusted tables,
gains or validation. Writer initialization migrates transactionally; HTTP can
still read schema 3 without modifying frozen databases.

Follow-up: [real OCR integration verification](ocr-sqlite-verification.md) covers
private-crop replay, local capture and profile setup. The later
[short OCR interruption policy](accounting.md) recovers endpoint gains while
retaining evidence of missing observations; see its before/after replay results.

`Store` uses built-in `sqlite3`; no new dependency or service is needed. The OCR
matcher/thresholds are unchanged. The existing capture trust guard moved to
`trust.py`; `capture._guard_unverified_exp` remains an alias for existing callers.
`validate_transition` remains the sole numeric/character/level transition gate.

## Schema and transactions

The actual schema is [schema.py](../src/exp_tracker/schema.py), version 3:

| Table | Stores |
| --- | --- |
| `streamers` | Normalized channel login and explicitly selected character |
| `characters` | Channel-owned character labels; separate histories |
| `sessions` | Character/session boundaries, explicit end reasons; one open session per channel |
| `observations` | Stable event ID, session/character, timestamps, profile fingerprint, diagnostics, outcome, endpoint gain and missing-observation metadata |
| `tracking_state` | Per-character last trusted observation, last event time, status, pause reason, hard continuity break and pending OCR interruptions |
| `diagnostic_runs`, `diagnostic_attempts` | Separate unverified shadow evidence linked to existing entities; never contributes trusted EXP or gains ([local alpha](local-alpha.md)) |

Foreign keys enforce channel/character/session ownership and state pointer
ownership. Trusted rows (`baseline`/`accepted`) require a profile fingerprint,
session and complete reading. Rejected candidates stay in `diagnostic_json`;
their trusted numeric columns are NULL. Percent is stored as integer hundredths
(`percentage_bp`); timestamps are canonical UTC ISO strings with microseconds.
`observed_at` is the producer's timestamp, `recorded_at` is database receipt time.
Capture currently uses local decoder receipt, not an established broadcast time.

Each connection enables foreign keys, WAL and a five-second busy timeout.
Initialization creates all tables and `PRAGMA user_version=3` atomically. Existing
version 1 databases receive additive columns in the same transaction. Historical
observations/gains are not recalculated; legacy non-tracking states are treated
as hard breaks because their pause causes were not distinguished. Unknown
versions and nonempty unversioned databases are refused, never overwritten.
Version 2 working databases receive only the separate diagnostic tables/index;
trusted history/state is unchanged. Migrate working copies with a writable CLI
before serving HTTP. Copy frozen evidence databases before migrating.
The old `docs/schema.sql` remains a historical design sketch, not initialization
SQL. Unversioned prototype databases are not adopted automatically.

The shared guard checks the producer's evidence first. Each ingestion then takes
`BEGIN IMMEDIATE`, reloads selection/session/state, applies the existing transition
validator, inserts the attempt and updates state in one
transaction. Errors roll everything back. Current-state inspection also reads a
consistent transaction. Writable connections serialize local writers; there is
no cached baseline to become authoritative after restart. The
[local read-only HTTP server](overlay.md) uses `Store(path, read_only=True)`:
SQLite `mode=ro`, deferred `BEGIN` snapshots, no initialization/migration and no
journal-mode changes. Its readers can inspect committed state during WAL writes.

## Trusted ingestion and continuity

- A valid calibrated `GlyphProfile` and matching pixel EXP/percentage evidence
  are required. No-profile/Tesseract-only candidates remain diagnostic.
- Selection and an explicit open session are required. Bind each event to the
  session selected **before** capture; an in-flight old-session result cannot
  become the new character's reading after a switch.
- `(channel, event_id)` is idempotent. An identical replay returns the saved row
  with `duplicate: true`, without changing state or gain. Reusing the ID with
  different time/session/evidence is an error. Frame hashes are not event IDs:
  two different attempts may legitimately show identical pixels.
- Older/equal timestamps are recorded as rejected and cannot change current
  reading, status or event watermark. A newer failure pauses tracking without
  changing the trusted reading/time. Confirmed offline can be recorded as
  `Recognition("offline")`; acquisition failure alone is not proof of offline.
- Same-level gains use the existing validator, with **no rate limit**. Within
  120 seconds between trusted endpoints, temporary OCR rejections may be bridged
  in the same explicitly assigned character/session. The gain belongs to that
  endpoint interval, with its missing-attempt count; nothing is interpolated.
- Confirmed offline, explicit hard pauses, capture/processing failures and
  contradictory validated transitions break continuity. A later OCR failure
  cannot erase a hard break. The next compatible reading establishes a new
  baseline with no gain. Gaps over 120 seconds also rebaseline. Last trusted
  age/staleness is visible even if no worker runs.
- Level changes and decreases remain auditable ambiguous attempts with no gain
  and no automatic character reassignment. End/start a session explicitly to
  accept a new baseline after confirming the character. No cross-level totals
  or EXP table are invented.

`observed_session_exp` retains its existing name for compatibility: it sums
validated endpoint net changes, including eligible short OCR interruptions. It
does **not** imply continuous observation or gross EXP earned. `bridged_session_exp`
identifies the portion counted across missing observations. Hard breaks, long
gaps and new sessions contribute no cross-boundary gain. The additive
[`statistics` state field](statistics.md) provides rolling endpoint gains, a
covered-span pace and percentage-based ETA. These read-only calculations use
the same snapshot and stored interval links; persistence and schema are unchanged.
The per-character last trusted reading survives end/switch/restart, but a new
session always starts its own baseline. Restarting an open session reuses its
persisted state; calling `start_session` again does not create another session.

This is an in-process producer contract, not authentication: supplied Python
objects are not cryptographic proof that OCR actually ran. There is no public
JSON ingestion API. The synthetic demo deliberately supplies synthetic evidence
and must not be used to write live game history.

## Local demo and administration

After the README's normal development installation, run from the project root:

```powershell
# Requires a new path; refuses to overwrite an existing database.
.\.venv\Scripts\python tools/demo_tracking.py artifacts/sqlite-demo.sqlite3
# A new process restores the selected character/session and EXP 1500, gain 500.
.\.venv\Scripts\python -m exp_tracker.tracking --db artifacts/sqlite-demo.sqlite3 --channel demo state
```

If the demo database already exists (including the one created during this
milestone's verification), inspect it with `state` or choose a fresh demo path.
The demo never deletes existing history.

Create a separate real local tracking database:

```powershell
.\.venv\Scripts\python -m exp_tracker.tracking --db data/tracker.sqlite3 --channel streamer_a init
.\.venv\Scripts\python -m exp_tracker.tracking --db data/tracker.sqlite3 --channel streamer_a character "Main character"
# Use the character_id returned above, not an assumed ID in an existing database.
.\.venv\Scripts\python -m exp_tracker.tracking --db data/tracker.sqlite3 --channel streamer_a select 1
.\.venv\Scripts\python -m exp_tracker.tracking --db data/tracker.sqlite3 --channel streamer_a start
.\.venv\Scripts\python -m exp_tracker.tracking --db data/tracker.sqlite3 --channel streamer_a state
# End explicitly; restarting a worker alone leaves the session open.
.\.venv\Scripts\python -m exp_tracker.tracking --db data/tracker.sqlite3 --channel streamer_a end
```

On Linux use `.venv/bin/python`. Linux execution has not been checked here.
Select another character to close the old session, then explicitly start the new
one. Selection alone does not start tracking or infer identity from the HUD.

The optional capture integration adds `--database data/tracker.sqlite3` to the
existing capture command, with a calibrated `--glyph-profile`. It requires a
previously selected character/open session and restores those on restart. For
file/HLS inputs, supply `--tracking-channel streamer_a`; Twitch defaults to `--channel`.
`--character` belongs to the old in-memory mode; database mode uses its persisted
selection. Each printed record includes its stable `event_id`, bound session and
`tracking` outcome. Trust `tracking.outcome`, not raw recognition status. On a
database error the worker stops with exit 1; it never substitutes memory state.
No Twitch trial was run for this integration.

Programmatic producer entry point:

```python
with Store("data/tracker.sqlite3") as store:
    snapshot = store.state("streamer_a")
    session_id = snapshot["session"]["id"]  # bind before capture/OCR
    attempt = store.ingest("streamer_a", stable_event_id, aware_receipt_time,
                           ocr_result, profile=loaded_profile,
                           session_id=session_id, source="twitch")
```

Import `Store` from `exp_tracker.store`. Do not pass a caller-computed transition:
the transaction computes it against persisted state. Retries must retain the same
event ID, timestamp, session and evidence. Capture/processing failures can use
`Recognition("capture_failed", reasons=[...])` with the same session binding.
An explicit hard pause can use `Recognition("paused", reasons=["explicit_pause"])`
with a stable event ID and the active session. It requires no profile, remains
diagnostic and never changes trusted values. A subsequent compatible trusted
reading resumes with a new baseline; end/start a session to confirm a level reset.

Databases, WAL/SHM journals, private profiles, raw OCR diagnostics and captures
remain under ignored `data/`, `private/` or `artifacts/`. No screenshots, source
URLs, tokens or profile assets are stored in SQLite. Database files themselves
contain private character/OCR history; do not publish them.

## Validation and limits

Tests cover trust/fallbacks, large gains, duplicates/conflicts, ownership,
character switching, gaps/pauses, level changes/decreases, ordering, rollback,
schema refusal, restart and real capture-loop wiring with synthetic input.
At the original SQLite milestone's completion: **31 targeted tests passed; full suite 240 passed, zero
skipped**, including all 71 private-sample tests. Dependency, compilation and
whitespace checks passed. The demo and separate-process state CLI both ran.

```powershell
.\.venv\Scripts\python -m pytest -q --basetemp=artifacts/pytest-sqlite
```

No new footage, frontend, API, deployment, authentication or scheduler was added.
Automatic level-up confirmation, game EXP tables, channel renames, backups,
retention/deletion commands and Linux load testing remain future work.
See [accounting verification](accounting.md) for the current policy's test results.
