# Local read-only API and OBS overlay

`python -m exp_tracker.server --db PATH` serves a static overlay and current state
using the standard library's `ThreadingHTTPServer`. It always binds **127.0.0.1**;
there is no host/public-bind option, write API, authentication or deployment.
The server adds no dependencies. Assets are packaged under `exp_tracker/web/`.

The separate [simulated leaderboard preview](demo-leaderboard.md) is served at
`/demo/leaderboard` by the same server. It uses fictional static data and does not
change this overlay, its polling, the state API or tracking statistics.

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
`http://127.0.0.1:8765/overlay/demo`, width **500**, height **160**. The HTML/body
background is transparent; only the warm cream information panel is drawn.
No custom CSS, WebSocket credentials, plugin or page-refresh setting is needed.
OBS must run on the same computer as this local server for this milestone.

The card is always 490 × 150 pixels, with a five-pixel transparent margin inside
the 500 × 160 canvas. Header, EXP/progress, four statistic columns and update note use fixed
rows; no status adds a line or changes the card size or colour. Resize the source
using OBS's transform rather than changing the Browser Source dimensions.
The header separates `ttv/channel` and the selected character. Both names have
bounded space, ellipsis and full-name tooltips. An optional rank badge is hidden
until authoritative rank data exists; no leaderboard exists today. The small
star uses a symmetric, geometrically centred SVG instead of a font baseline.
Large current EXP numbers use smaller type without abbreviation. Statistic
columns use compact K/M/B/T notation with full session totals in tooltips. The
cream/caramel/sage palette and SVG are original, with no game artwork or fonts.

For meaningful five-/thirty-minute demonstrations, use the
[synthetic history workflow](statistics.md#reproducible-synthetic-history).
The short animation below still exercises value/status changes but correctly
leaves rolling pace/ETA unavailable.

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
reading is stale. The overlay keeps the numbers with an "Updates delayed" note
and the age of the last update.
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
- Additive [`statistics`](statistics.md): five-minute endpoint gains, thirty-minute
  pace, percentage-based ETA and their eligibility/coverage metadata.

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

The player sees the selected character, level, numeric EXP, displayed percentage,
progress bar, **Last 5 min**, **EXP/h · 30m**, **This session**, and **To next level**.
Level sits beside the progress bar, with EXP and percentage inside it. All four
statistic columns have equal widths. Unavailable metrics use a dash; trimmed
five-minute counts, estimated pace and ETA use `~`. See the
[metric definitions and eligibility policy](statistics.md) before interpreting
these as continuously observed values. Session totals keep their original meaning.

| Situation | Player-facing note |
| --- | --- |
| Tracking or brief unreadable frame | No warning; keep values and "Updated Xs ago" |
| Stale (over 120 seconds) or a failed state request with cached values | "Updates delayed" and the actual last-update age |
| Confirmed offline | "Offline" and the actual last-update age, if a reading exists |
| Explicit hard pause/no active session with retained values | "Paused" and the last-update age |
| No reading, unconfigured or unknown channel | "Waiting for EXP"; missing values are em dashes |
| A new session awaits its first reading | "Waiting for EXP"; retain previous values and their original update age |
| Ambiguous numeric transition | "Updates delayed"; retain values and age |

All notes occupy the same reserved footer row. Brief unreadable frames do not
recolour the card or expose warnings/reasons; they do not change the update age.
Cached values never acquire a new timestamp on request failure. The overlay does
not infer stream "Live" status from successful OCR. Diagnostic reason codes,
continuity flags and bridged EXP remain available in the API/logs, not on the
player-facing card. No technical errors or bridged-gain explanations are rendered.

Unknown channels return JSON **404**, malformed channels **400**, unavailable or
incompatible databases **503**. A known unconfigured channel returns **200** with
null selection/session/reading. Non-GET write methods return **405**. Static
assets use a fixed allowlist; there is no directory/file browser or cross-origin
access header. Responses use `Cache-Control: no-store`; character names are
inserted with `textContent`, not HTML. Internal reasons are not rendered.

## Validation and remaining manual check

- At the current statistics milestone: **333 full-suite tests passed, zero skipped**,
  including the real localhost TCP smoke test. **Zero private-sample skips**.
- Current renderer: eleven Node checks passed (also invoked from pytest when Node is present).
  Node is optional test tooling, not a server or browser dependency.
- Real HTTP parsing/serialization is exercised in memory against actual Store
  data, including the private OCR replay. Concurrent WAL reading during a held,
  uncommitted guarded observation verifies old-or-new committed snapshots.
- Read-only writes fail at SQLite, HTTP write methods are refused, old schemas
  remain untouched, and freshness advances without any database mutation.
- The CLI started on 127.0.0.1:8765, and the timed demo appended seven new events
  with the expected totals. No helper server was left running.

The earlier restricted session skipped the real TCP test with Windows error
10013 and could not start headless Edge. Expanded connection/browser permissions
resolved both: actual Edge loaded the served overlay, displayed SQLite-derived
values and completed repeated API polling. No browser security settings were
disabled. In a restricted Codex shell, use the approved expanded connection access
when running the tests; an ordinary local terminal needs no extra setup.

```powershell
.\.venv\Scripts\python -m pytest -q tests/test_server.py --basetemp=artifacts/pytest-overlay-manual -rs
```

## Reproduce the browser sizing and screenshot check

With the local server running against a database containing a reading:

```powershell
node tools/overlay.browser.mjs http://127.0.0.1:8765/overlay/demo
```

This optional tool uses Node's built-in WebSocket (verified with Node 24) and an
installed Chromium browser. It finds Edge/Chrome on common Windows/Linux paths;
set `BROWSER_BIN` to the executable if needed. It opens an isolated headless browser,
checks actual API polling, then injects presentation-only cases into the page.
It never writes to SQLite, changes historical timestamps or collects footage.

All **16 browser cases passed**: tracking, brief OCR failure, stale, offline,
offline without a reading, explicit pause, review-needed, API failure, unconfigured,
waiting, previous-session reading, long name/large values, zero EXP, missing
statistics and two explicitly synthetic rank cases (normal and long names). Every
card measured **490 × 150** at (5,5) on a **500 × 160** page, with no page or metric
overflow and identical background/border styling. The maximum safe JavaScript
integer (9,007,199,254,740,991) fit as current EXP without abbreviation, and 99.99%
fit inside the progress section. All four stat columns had equal widths and
fitting labels/values. The SVG/path centres matched the icon box centre. Twitch
and character names remained separate with full-name tooltips and ellipsis.

The current PNGs and `measurements.json` are under ignored `artifacts/overlay-statistics/`.
Populated, missing-statistic, long-value and synthetic-rank screenshots were visually inspected. All PNGs
were 500 × 160 with zero alpha at the outer corner, verifying transparent page
output. Reference imagery in `samples/` remains private/ignored; no game assets
were copied into the overlay. The browser helper closes its server-independent
browser; profiles and logs stay in the ignored artifact directory for diagnosis.

OBS's actual CEF rendering/compositing still needs a manual check at **500 × 160**;
only Edge was automated. Linux execution and cold wheel installation were not
checked in this milestone. Guarded ingestion, acquisition and accounting are
unchanged; the API adds only read-only statistics from persisted intervals.

The standard-library server is for local use only. No frontend configuration UI,
write API, account system, leaderboard, production scheduler, remote exposure,
new capture or accounting policy change is included. Databases and all preview/
diagnostic artifacts remain ignored. No commits or pushes were made.
