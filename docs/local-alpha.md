# Single-stream local alpha

Explicit channel/character/session selection connects existing bounded shadow
capture, SQLite diagnostics and a real-data dashboard. This is local-only,
read-only over HTTP and **experimental/unverified**, not trusted neural tracking.
No new dependency, model, account or scheduler is needed.

For two to five assignments, use the [multi-stream coordinator and `/streams`
guide](multi-alpha.md). This single-stream launcher remains supported. The persisted
dashboard also derives separately gated experimental percentage progress.

The SQLite dashboard derives [versioned grammar and independent percentage proposals](extended-diagnostics.md)
from malformed raw EXP strings. They are labeled GRAMMAR-RECOVERED / EXPERIMENTAL /
UNVERIFIED, separately from strict candidates. Optional hollow chart layers are
off by default; original strict points and failure markers remain visible.
Original logs/rows, launcher success counts and trusted tracking/pace calculations are unchanged.
Restart the server to inspect existing observations; no recapture or migration.

## Simplest startup: one explicitly configured stream

From the repository root, with the existing capture dependencies/private models:

```powershell
.\.venv\Scripts\python tools/local_alpha.py --channel streamer_a --character "Main" --authorized --experimental-neural-level --count 3 --interval 15 --save-crops
```

Run this only for a permitted trial. Open the **exact dashboard URL printed by the
launcher**, normally `http://127.0.0.1:8765/dashboard/streamer_a`. It initializes
`private/local-alpha/live/streamer_a.sqlite3` when absent, explicitly selects `Main`,
starts/reuses its session, starts localhost HTTP and then requests bounded capture.
No streamer installation or OBS setup is needed. Without the neural-level flag,
that stage remains off; Tesseract and EXP diagnostics still run.

The terminal first shows the database, existing selection, proposed initialization/
reuse, channel, character, session, saved-data age and private log location. Every
attempt reports **frame acquired/failed → HUD unique/missing/ambiguous → strict
EXP/percentage candidate → separate levels → SQLite committed/not committed**.
A committed failure is evidence of an attempt, not a recognized reading. Values
and local ages remain UNVERIFIED; no numerical confidence is implied.

Defaults are three attempts, 15-second spacing and the existing capture/recognition
timeouts. At completion **capture stops**; the dashboard stays open until Ctrl+C,
which closes the owned HTTP server. Its data ages visibly. `--exit-after-capture`
also closes HTTP at completion for offline/automated checks. Ctrl+C during capture
stops both. Restart reuses the selected character/session and preserves history;
it does not silently end a session. Each run gets a new timestamp/UUID directory
under `private/local-alpha/runs/`, containing `capture.jsonl`, concise
`operator.jsonl` and optional crops. Existing outputs are never overwritten.

The launcher now publishes its own running/waiting/failing/completion state to
the existing HTTP runtime status, including the player website and OBS overlay.
An independent `exp_tracker.server` process cannot see another process's worker;
fresh observations alone never prove capture is running. See
[live updates and percentage-derived EXP](live-player-updates.md).

An existing different character selection is **refused**, even with an explicit
different `--character`. Use the existing tracking CLI to end/switch/select/start
deliberately, then relaunch with the matching label. `--db` can choose an existing
working database; if it contains channels but not the requested one, startup
refuses instead of silently adding that channel. Existing old-schema files require
explicit migration of a working copy; the launcher does not migrate saved evidence.

Exit status: **0** = at least one locally fresh strict diagnostic observation,
**2** = completed attempts but none available/fresh, **1** = setup/persistence error,
**130** = interrupted capture. None establishes numerical correctness. When HTTP
stays open, the final status is returned when it closes; a PowerShell wrapper may
map native nonzero exits to 1, so inspect `$LASTEXITCODE` and the actual summary.

## Existing Streamer_A data versus a new live trial

These are different databases; the dashboard URL cannot switch databases:

| File under `private/local-alpha/` | Channel | Evidence at inspection |
| --- | --- | --- |
| `replay-01.sqlite3` | `streamer_e` | 12 saved attempts |
| `replay-a-01.sqlite3` | `streamer_a` | 12 saved attempts |
| `streamer_a-live-01.sqlite3` | `streamer_a` | Configured character/session, zero runs/attempts |

The third file now exists, but contains no capture attempt to diagnose. This does
not show that Twitch was offline or denied access. No new Twitch trial was run
during launcher development.

To view the **saved Streamer_A** example, terminal 1:

```powershell
.\.venv\Scripts\python -m exp_tracker.server --db private/local-alpha/replay-a-01.sqlite3 --diagnostic-dashboard
```

Terminal 2:

```powershell
Start-Process 'http://127.0.0.1:8765/dashboard/streamer_a'
```

This is an old saved recording, visibly stale. **Starting HTTP does not capture
Twitch.** Stop that server with Ctrl+C before running the one-command live trial
above, or add `--port 8766` to the launcher and open its printed URL. For a longer
permitted run, replace `--count 3` with `--count 12`. Do not replace a failed frame
or overwrite logs; retain every attempt for later blinded review.

## Quick troubleshooting

| Symptom | Meaning / next action |
| --- | --- |
| Wrong dashboard/channel | Unknown channels now return 404 with configured channels. Check `--db`; use `replay-a-01.sqlite3` for saved Streamer_A. |
| Only HTTP is running | No capture is implied. Use the launcher or the separate capture command below. |
| Port already occupied | Stop the previous server or choose `--port 8766`. The launcher does not reuse an unidentified server. No capture starts after a bind failure. |
| Character/database mismatch | No reassignment is performed. Use the matching existing selection/database or a fresh live path. |
| Missing FFmpeg/Tesseract/private environment/table | Preflight stops before capture; use the existing installation instructions, `--ocr-python` or `--requirements`. No models are downloaded. |
| Stream offline/not playable | Best-effort Streamlink classification, not confirmed offline status; check the channel manually. |
| Access denied | Twitch refused playback. Stop; no evasion/bypass is attempted. |
| Network failure / timeout | Check local DNS/firewall/connectivity and the saved reason code; the exact upstream cause may remain unknown. |
| Frame acquired, no/competing HUD | Acquisition worked; localization did not select an unambiguous HUD. The attempt remains diagnostic. |
| EXP rejected / levels unavailable | Strict OCR syntax or a separate level stage failed; raw strings remain in private JSONL. No punctuation or digits are repaired. |
| SQLite NOT COMMITTED | Capture stops. Inspect session/character changes or DB errors. A flushed JSONL line alone does not prove a DB commit. |
| Old values after capture stops | Expected: ages continue increasing and become stale; no background scheduler restarts capture. |

Detailed stage timings, safe capture reason codes, raw neural text, Tesseract passes
and model metadata remain private in `capture.jsonl`. Subprocess stderr/signed URLs
are not dumped to the terminal or browser. Some failures can only be classified
coarsely; a timeout does not establish whether the stream was offline.

## Offline launcher check

```powershell
.\.venv\Scripts\python tools/local_alpha.py --channel offline_check --character "Offline Main" --file samples/sample-stream3.mp4 --start 1145 --count 1 --experimental-neural-level --port 8766 --exit-after-capture
```

No Twitch connection/authorization is involved. This checks actual local video →
recognition → SQLite, not accuracy on unseen footage. Omit `--exit-after-capture`
to keep the dashboard open. Repeating the command reuses the character/session,
adds a distinct run and retains prior observations. No EXP gains are computed.

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
