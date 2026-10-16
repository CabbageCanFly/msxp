# Local read-only API and OBS overlay

`python -m exp_tracker.server --db PATH` serves a static overlay and current state
using the standard library's `ThreadingHTTPServer`. It always binds **127.0.0.1**;
there is no host/public-bind option, write API, authentication or deployment.
The server adds no dependencies. Assets are packaged under `exp_tracker/web/`.

## Start with a synthetic demo

Run from the project root. No Tesseract, private glyphs or capture dependencies
are needed for this workflow. Python dependencies must already be installed as
described in the README.

Terminal 1:

```powershell
# Create only if absent; the demo refuses to overwrite an existing database.
if (-not (Test-Path artifacts/overlay-demo.sqlite3)) {
    .\.venv\Scripts\python tools/demo_tracking.py artifacts/overlay-demo.sqlite3
}
# Explicit writer CLI initializes/migrates schema if needed; no readings are rewritten.
.\.venv\Scripts\python -m exp_tracker.tracking --db artifacts/overlay-demo.sqlite3 --channel demo state
.\.venv\Scripts\python -m exp_tracker.server --db artifacts/overlay-demo.sqlite3
```

Terminal 2:

```powershell
Start-Process 'http://127.0.0.1:8765/overlay/demo'
Invoke-RestMethod 'http://127.0.0.1:8765/api/streams/demo/state' | ConvertTo-Json -Depth 6
```

The original existing `artifacts/sqlite-demo.sqlite3` works too: substitute that
path in the commands above and run the tracking `state` command once to migrate
its version 1 schema if needed. The read-only server deliberately refuses old,
unknown or uninitialized schemas; it never creates a missing database.

The synthetic demo has **level 60 / EXP 1,500 / 15.00% / session net EXP 500**.
It retains its original timestamps and becomes stale after 120 seconds. An old
demo showing stale is expected, not a failed server. Stop the server with Ctrl+C.
On Linux use `.venv/bin/python` and open the same URL manually.

In OBS, add a **Browser Source** with URL
`http://127.0.0.1:8765/overlay/demo`, width **480**, height **260**. The HTML/body
background is transparent; only the compact dark information panel is drawn.
No custom CSS, WebSocket credentials, plugin or page-refresh setting is needed.
OBS must run on the same computer as this local server for this milestone.

## Demonstrate new updates without Twitch

Stop the previous server first to free port 8765. Choose a **new** ignored database
path; this example never appends synthetic readings to real or historical history.

Terminal 1:

```powershell
.\.venv\Scripts\python tools/demo_tracking.py artifacts/overlay-motion.sqlite3 --animate
```

While it runs, terminal 2:

```powershell
.\.venv\Scripts\python -m exp_tracker.server --db artifacts/overlay-motion.sqlite3
```

Terminal 3:

```powershell
Start-Process 'http://127.0.0.1:8765/overlay/demo'
```

The new database appears immediately. Seven real `Store.ingest` calls, five
seconds apart, demonstrate 1,000 → 1,500 → unreadable → 2,100 → offline → 2,600 →
3,100 EXP. The unreadable frame preserves values and the next trusted endpoint
bridges 600 EXP; offline breaks continuity and 2,600 becomes a new baseline.
Final totals are **1,600 session net EXP, including 600 bridged EXP**. The script
then exits, leaving the HTTP process independent; the overlay eventually shows
stale. Each event passes the actual guard/transition/writer with an owned synthetic
glyph profile and explicitly selected synthetic character. This does not claim
that synthetic evidence is a game calibration or real OCR.

Optional `--interval 1` runs the demonstration faster. Intervals must be positive
and at most 60 seconds so the bridged interval stays within the existing limit.
If that path already exists, choose another fresh path. The demo refuses to
overwrite it or change its existing observations.

## Show saved real OCR state

The existing accounting replay database can run alongside the demo on another
port. It is read directly; no new footage or replay is required:

```powershell
.\.venv\Scripts\python -m exp_tracker.server --db artifacts/accounting-bridge.sqlite3 --port 8766
# In another terminal:
Start-Process 'http://127.0.0.1:8766/overlay/telfer1'
Invoke-RestMethod 'http://127.0.0.1:8766/api/streams/telfer1/state' | ConvertTo-Json -Depth 6
```

Expected saved values: **60 / 879,217 / 72.66%**, session net **6,121**, bridged
**1,592**. The final rejected frame leaves tracking paused, and the historical
reading is stale. The overlay keeps the numbers with a stale label and age.
The earlier `artifacts/ocr-integration.sqlite3` can also be explicitly migrated
and served, but keeps its historical **4,529** total; migration does not recalculate
old gains. See [replay instructions](ocr-sqlite-verification.md) if creating a new
private replay database.

Existing capture/replay CLI processes may write to the same database while the
server runs. Continue to bind each attempt to the explicitly selected session
and use the existing calibrated-profile trust gate. There is no ingestion endpoint
in HTTP and no requirement to restart the server after a committed observation.

## State contract and display behaviour

`GET /api/streams/{channel}/state` returns the existing `Store.state()` fields:

- Explicit `selected_character_id`, character list and open session.
- `last_trusted`: observation/session IDs, timestamp, level, integer `current_exp`
  and integer `percentage_bp` (7,266 means 72.66%). No rejected candidate is shown.
- `observed_session_exp`, `bridged_session_exp`, continuity flag and pending
  missing-observation count. These keep the [existing accounting meaning](accounting.md).
- Status/reason, `last_event_at`, last trusted age in seconds and `stale`.

HTTP adds `selected_character` (ID/label or null), UTC `served_at` and
`stale_after_seconds` from the Store's existing 120-second freshness threshold.
Each request opens its own read-only connection and computes current freshness;
there is no state cache and no worker heartbeat dependency. A consistent snapshot
prevents mixing a new observation with an old trusted pointer/session total.
No OCR diagnostics, profile contents, credentials or screenshots are served.

The overlay polls every two seconds, without reloading the page. A separate
one-second display timer ages cached values, including when requests hang or the
worker stops. Fetches time out after four seconds and do not overlap; request
time is included conservatively in displayed age. Poll frequency is **not** a
new OCR observation frequency.

Tracking, OCR interruption, hard pause, stale, offline, unconfigured, waiting,
no-active-session and review-needed states have text labels as well as colours.
An API failure retains cached numbers with an explicit unavailable/cached warning;
it never turns them into fresh observations or zero. Missing readings display
an em dash. Previous-session values retained by the Store are identified while
waiting for the new session's first trusted reading. Stale state remains visible
in the age line even when offline or another status takes label priority.

Unknown channels return JSON **404**, malformed channels **400**, unavailable or
incompatible databases **503**. A known unconfigured channel returns **200** with
null selection/session/reading. Non-GET write methods return **405**. Static
assets use a fixed allowlist; there is no directory/file browser or cross-origin
access header. Responses use `Cache-Control: no-store`; character/reason text is
inserted with `textContent`, not HTML.

## Validation and remaining manual check

- Targeted Python API/Store/CLI checks: **79 passed, 1 skipped**.
- Full suite: **304 passed, 1 skipped**. **Zero private-sample skips**.
- Six Node renderer checks passed (also invoked from pytest when Node is present).
  Node is optional test tooling, not a server or browser dependency.
- Real HTTP parsing/serialization is exercised in memory against actual Store
  data, including the private OCR replay. Concurrent WAL reading during a held,
  uncommitted guarded observation verifies old-or-new committed snapshots.
- Read-only writes fail at SQLite, HTTP write methods are refused, old schemas
  remain untouched, and freshness advances without any database mutation.
- The CLI started on 127.0.0.1:8765, and the timed demo appended seven new events
  with the expected totals. No helper server was left running.

This session blocks loopback client sockets with Windows error **10013**. The
separate real TCP smoke test is the one skip; only that specific permission
error is skipped. Run it outside this session to verify local transport:

```powershell
.\.venv\Scripts\python -m pytest -q tests/test_server.py --basetemp=artifacts/pytest-overlay-manual -rs
```

An offline headless Edge preview was attempted using the actual overlay code and
the database-derived API response, but Edge exited with **0xC0000005** before
creating a screenshot. **Actual visual rendering, browser-to-HTTP polling and OBS
transparency remain unverified here.** Please open the demo and inspect it in OBS,
including paused/offline/stale labels and live updates. Renderer logic and CSS
transparency declarations are tested; they do not establish a visual result.
Linux execution and cold wheel installation were not checked in this milestone.

The standard-library server is for local use only. No frontend configuration UI,
write API, account system, EXP/hour, ETA, production scheduler, remote exposure,
new capture or accounting policy change is included. Databases and all preview/
diagnostic artifacts remain ignored. No commits or pushes were made.
