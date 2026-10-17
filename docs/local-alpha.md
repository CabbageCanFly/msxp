# Single-stream local alpha

Explicit channel/character/session selection connects existing bounded shadow
capture, SQLite diagnostics and a real-data dashboard. This is local-only,
read-only over HTTP and **experimental/unverified**, not trusted neural tracking.
No new dependency, model, account or scheduler is needed.

## Saved real diagnostics

Run from the repository root. This uses familiar Stream B evidence, including its
original timestamps, malformed output and missing-HUD attempt. It is not a new
accuracy benchmark. Use a **new** database; ID 1 assumes an empty database. The
character label is an explicit assignment, not an identity inferred from pixels.

```powershell
$log = 'private/shadow-neural-level/replay-02/viewer-stream-b.jsonl'
$first = Get-Content $log | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object type -eq 'attempt' | Select-Object -First 1
$channel = $first.source.channel
$db = 'private/local-alpha/my-replay.sqlite3'
if (Test-Path $db) { throw 'Choose a fresh database path' }
.\.venv\Scripts\python -m exp_tracker.tracking --db $db --channel $channel init
.\.venv\Scripts\python -m exp_tracker.tracking --db $db --channel $channel character 'Local review character'
.\.venv\Scripts\python -m exp_tracker.tracking --db $db --channel $channel select 1
.\.venv\Scripts\python -m exp_tracker.tracking --db $db --channel $channel start --at $first.attempted_at
.\.venv\Scripts\python -m exp_tracker.diagnostics --db $db --channel $channel $log
# Repeat: zero inserts, no new session
.\.venv\Scripts\python -m exp_tracker.diagnostics --db $db --channel $channel $log
.\.venv\Scripts\python -m exp_tracker.server --db $db --diagnostic-dashboard
```

Open `http://127.0.0.1:8765/dashboard/CHANNEL_FROM_THE_LOG` in Chrome. Another
terminal can use `Start-Process 'http://127.0.0.1:8765/dashboard/CHANNEL_FROM_THE_LOG'`
to open the default browser. Restart with the same database: selection, session,
attempts and IDs persist. Historical values remain old, never retimed. For the
percentage-only example use `viewer-stream-a.jsonl`, its matching channel and a
separate fresh assigned database. No absolute EXP is reconstructed.

## Later permitted live trial (not started automatically)

```powershell
$channel = 'PERMITTED_CHANNEL'
$db = 'private/local-alpha/live-01.sqlite3'
.\.venv\Scripts\python -m exp_tracker.tracking --db $db --channel $channel init
.\.venv\Scripts\python -m exp_tracker.tracking --db $db --channel $channel character 'YOUR_CHARACTER'
.\.venv\Scripts\python -m exp_tracker.tracking --db $db --channel $channel select 1
.\.venv\Scripts\python -m exp_tracker.tracking --db $db --channel $channel start
.\.venv\Scripts\python -m exp_tracker.server --db $db --diagnostic-dashboard
```

In another terminal set the same `$channel` and `$db`, then:

```powershell
.\.venv\Scripts\python tools/shadow_capture.py --channel $channel --authorized --db $db --experimental-neural-level --interval 15 --count 30 --output private/local-alpha/live-01.jsonl --save-crops
```

Open `/dashboard/CHANNEL`; completed commits appear with two-second polling. Use
fresh output filenames. Existing Streamlink/FFmpeg, Tesseract, private RapidOCR
environment/models and requirement table are still required; see [shadow capture](shadow-capture.md).
Existing serial capture/timeouts/freshness limits remain: at most 60 attempts, no
backlog or streamer installation. No log/image/playback HTTP endpoint is added.

Local video replaces `--channel ... --authorized` with `--file samples/sample-stream3.mp4
--start 1145 --tracking-channel LOCAL_DB_CHANNEL`; configure its local-video
channel/character/session explicitly first. No source identity is inferred.

To switch characters, stop capture, use `tracking character`/`select` with its
returned ID and `start`, then start a new run/output. Mid-run switches or session
ends stop insertion instead of reassigning evidence. Exact replay stays in its
original session. The dashboard shows only the selected **open session**, at most
120 recent attempts across its runs. Archived sessions remain in SQLite.

## Storage and trust

Schema **3** adds two diagnostic tables. `diagnostic_runs` binds immutable run IDs,
configuration/summary and foreign keys to the existing streamer/character/session.
Live UUIDs are recorded in JSONL configuration; completed legacy logs use exact
file SHA-256 identity. Re-encoding a legacy log changes that identity: replay the
unchanged file. `diagnostic_attempts` stores unique `(run_id, attempt_index)`, original
bounded JSON, source/receipt timestamps, database receipt time and capture order.
Failures, full pairs, percentage-only fields, malformed strings, both visual levels
and separate arithmetic hypotheses persist without numeric reconstruction.

Each live insertion is atomic; complete replay is one transaction. Changed duplicate
IDs, channel mismatch, missing assignment, skipped index, completed-run appends and
oversized input fail explicitly. Exact replay is a no-op. Archived assignment is
explicit: evidence can predate the administrative session; the example backdates
only session start. Out-of-order timestamps remain visible, marked noncurrent, and
cannot replace the latest ordered candidate. Duplicate frames remain separate
attempts, not independent verification.

These tables have no trusted outcome/gain columns. Diagnostics never call
`Store.ingest`, alter trusted state, feed statistics/percentage pace or choose a
rounding rule. Existing trusted totals are labeled separately; without trusted
session observations they display as unavailable rather than fabricated zero gains.

Writable Store/CLI opens migrate schema 1/2 working databases atomically without
recalculating trusted history. Back up valuable databases first. HTTP never migrates:
run `python -m exp_tracker.tracking --db WORKING_COPY --channel CHANNEL state`
before serving old working databases. Tests migrate temporary SQLite backups, never
frozen original replay databases. Unsupported schemas still fail closed.

Opt-in HTTP (`--diagnostic-dashboard`) binds only `127.0.0.1`; routes are
`/dashboard/CHANNEL` and `/dev/api/streams/CHANNEL/diagnostics`. It reuses the shadow
view's allowlisted projection, points-only charts and cached-error handling. There
is no arbitrary file/session selection. Read-only snapshot connections coexist
with WAL writers. Last-attempt and last-candidate ages advance without a worker;
failures retain old values with their original age. Local delivery freshness never
establishes broadcast age or character identity.

## Validation and next step

```powershell
.\.venv\Scripts\python -m pytest tests/test_diagnostics.py tests/test_server.py tests/test_shadow_capture.py -q
.\.venv\Scripts\python -m pytest -q
node tools/shadow.browser.mjs http://127.0.0.1:8765/dashboard/CHANNEL private/local-alpha/browser
```

Actual results/changed files are in `.git/codex-output/latest.md`. Trust blockers
remain numerical/crop verification, competing HUDs, character identity, level-tile
completeness, unknown client display/build semantics and level-boundary handling.
Confidence, arithmetic agreement and repeated frames do not resolve those issues.
Next: a bounded permitted live trial with frozen blinded references, inspecting
persisted diagnostics here; no trusted neural gains yet.
