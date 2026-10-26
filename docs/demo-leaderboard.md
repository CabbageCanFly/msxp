# Demo previews

Use `msxp demo` for the current interactive site: fictional players, character rosters,
overlays and daily History in **EXP progress**. It runs in the current terminal and
cleans up its temporary database and servers with Ctrl+C. See the
[preview guide](website-background.md#preview-and-tune) for ports, live edits and worktrees.

## Legacy standalone leaderboard

The separate localhost route **`/demo/leaderboard`** is an older
read-only design preview with eight fictional characters. All ranks, channels,
statuses, readings and gains are explicitly **SIMULATED**. The page has no fetch,
polling, external assets, Twitch links or real leaderboard endpoint. It does not
read the shadow JSONL or SQLite state. No production ranking policy is implied.

## Launch and preview in Chrome

From the repository root, terminal 1:

```powershell
# Optional: make a dedicated synthetic DB if you do not already have a current-schema DB.
if (-not (Test-Path artifacts/leaderboard-demo.sqlite3)) {
    .\.venv\Scripts\python tools/demo_tracking.py artifacts/leaderboard-demo.sqlite3
}
.\.venv\Scripts\python -m exp_tracker.server --db artifacts/leaderboard-demo.sqlite3
```

In terminal 2:

```powershell
Start-Process 'C:\Program Files\Google\Chrome\Application\chrome.exe' 'http://127.0.0.1:8765/demo/leaderboard'
```

Substitute Chrome's executable path if installed elsewhere, or open that URL
manually. An existing valid database such as `artifacts/statistics-preview.sqlite3`
also works. The server still requires/validates a current-schema DB at startup for
its existing API; it never creates or migrates one. Demo requests do not open the
Store. Creating the optional synthetic DB is a separate explicit developer action.
Stop with Ctrl+C. There is still no public-bind option or write API.

## Controls and unavailable data

- **EXP / hour:** fixed simulated net window EXP × 60 / window minutes. Select
  **5, 10, 15 or 30 minutes**; both order and score/window labels update. Only
  complete, fresh simulated windows have a value. LittleSprout has five minutes
  of history, so is rankable at 5m and unavailable at longer windows.
- **Today's EXP:** recorded total for the explicitly fixed **16 October 2026 UTC
  demo day**; this is not today's real date or extrapolated whole-day earnings.
  Historical recorded totals can remain visible for offline/stale characters.
  Pace-window controls are disabled and their inapplicability explained.
- **Level:** sort known simulated last-read levels, including labeled last-known
  offline/stale readings. Window controls are disabled. No EXP table or level-up
  calculations are used; EXP/percent fixtures are invented, not game calibrations.
- Descending values, stable identity order for ties, competition ranks (1, 1, 3).
  Unavailable values sort last and have **no rank**. Missing is not zero; an actual
  simulated zero would remain a valid value. No metric is filled from another.
- Offline, delayed, unknown, waiting and building-history states are represented.
  Offline/stale readings retain original labels and snapshot ages; no recent pace
  is shown. Missing readings have no EXP/level/percentage or filled progress bar.

The fixed snapshot does not advance its timestamps or claim live updates. The
SIMULATED banner and fixed-snapshot/day notes remain visible. These static demo
definitions do not replace production [statistics](statistics.md) coverage rules.

## Presentation and security

Navy background, warm brown panel, orange pill controls, gold/silver/bronze rank
medals and lime EXP bars follow the supplied private reference's visual direction.
CSS clouds and a small original SVG emblem replace game art. Desktop rows collapse
to a two-line card on narrow screens; long identities use ellipsis/full tooltips.
Buttons have pressed states, keyboard focus, disabled-window semantics and an
accessible ranking summary. Status is text as well as a colored dot.

Only the exact page and four allowlisted static assets were added to the existing
HTTP handler. Binding remains **127.0.0.1**; content security policy, no-store,
nosniff, no-CORS and method restrictions are unchanged. The existing overlay assets,
state API structure, SQLite accounting, OCR/trust and shadow runner are unchanged.
No framework, dependency, account, authentication, deployment or external call.

## Reproduce validation

With the server running:

```powershell
node --test tools/leaderboard.test.mjs
node tools/leaderboard.browser.mjs http://127.0.0.1:8765/demo/leaderboard
.\.venv\Scripts\python -m pytest tests/test_server.py -q -rs --basetemp artifacts/pytest-leaderboard-repeat
.\.venv\Scripts\python -m pytest -q -rs --basetemp artifacts/pytest-leaderboard-full-repeat
```

The optional browser tool follows the existing dependency-free overlay CDP test
pattern, using installed Chrome/Edge/Chromium and Node's built-in WebSocket. Set
`BROWSER_BIN` if needed. It never disables browser security. It uses an isolated
headless profile and closes its browser; screenshots, profile and measurements
stay ignored under `artifacts/leaderboard-preview/`.

Chrome **155.0.8059.82** passed all metric/window interactions and seven screenshot
cases: desktop 30m/5m/today/level, mobile 390px, small mobile 320px and long names/
large EXP values. Desktop and mobile screenshots were visually inspected. No
horizontal overflow, clipped score/progress text, browser/CSP errors or off-origin
page requests were found. Two missing readings retain absent progress values.

Unit checks cover derived rates, all windows, switching metrics, disabled controls,
missing/zero values, offline/stale exclusions, ties and literal text rendering.
HTTP tests verify exact routes/MIME/security headers, no Store access for the demo,
unchanged database bytes, rejected writes and no arbitrary file serving.

Validation: **40 focused Python tests passed; full suite 728 passed, zero skipped**
(77.69s). All **7 Node frontend checks** and **7 Chrome screenshot cases** passed.
`git diff --check` and new-file whitespace checks passed. An initial browser-test
selector quoting error was corrected before the successful run. Preview server
and test browser were stopped afterward. No commits or pushes.

This is a visual/interaction demonstration. It establishes no real ranking fairness,
stream status, numerical OCR trust, UTC-day accounting or public-service security.
Actual mobile devices, Safari/Firefox and Linux remain untested.
