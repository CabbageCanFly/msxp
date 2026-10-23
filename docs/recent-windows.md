# Recent windows and remaining crop shift

The real homepage and character page now offer **5 / 10 / 15 / 30 min** selections.
They use persisted observations and the existing experimental continuity engine;
trusted ingestion/accounting, level policy, grammar rules and EXP tables are unchanged.
The OBS overlay keeps its existing short-segment estimates.

## Comparison policy

Each window ends at that channel's latest actual local capture/attempt timestamp.
This endpoint is explicit: an old saved run does not become fresh when HTTP starts.
Only observations inside the window and in the **current eligible uninterrupted
segment** contribute. At least three readings spanning 30 seconds, **90% window
coverage**, and a first reading no more than one recorded capture interval after
the boundary are required. No interval crossing the boundary is split or estimated.
For example, 288 seconds observed in a five-minute window is reported as 288 seconds;
the rate uses 288, not an invented 300 seconds.

Displayed percentage change uses integer basis points. Percentage-points/hour uses
the actual endpoint duration. Provisional EXP/hour multiplies that rate by the
existing supported community requirement / 100, retaining separate nearest-half-up
and truncation bounds. A missing/disputed requirement permits percentage comparison
but leaves EXP/hour unavailable. No formatting hypothesis is selected.

Failures, missing attempts, excessive gaps, level uncertainty/changes, character or
session boundaries and interrupted/restarted runs still break comparisons. Only the
existing validated scheduled-rotation exception can preserve continuity across run
UUIDs. Short histories show **Building history**; interruptions/staleness suppress
rates and ranking. Zero displayed change remains distinct from unavailable data.
None of these values are exact earned EXP or trusted session totals.

The product API adds a `windows` map without removing existing fields. It reads at
most 640 attempts per selected session (30 minutes at the explicit 3-second offline
floor plus context). Directory cards cache their compact projection by committed
revision; ages still advance. Advanced pages retain their 120-row pagination.

Changed files: `tools/adaptive_hud.py`; `src/exp_tracker/{product,diagnostics,server}.py`;
`src/exp_tracker/web/{tracker.html,player.html,product.css,product.js,shadow.html,shadow.js}`;
`tests/{test_adaptive_hud,test_recent_windows}.py`;
`tools/{product.test,shadow.test,product.browser,shadow.browser}.mjs`;
`README.md`, `docs/product-preview.md` and this report. No schema/data migration.

## Graphs

Player graphs default to the selected recent window ending at the latest capture,
then expand its actual sampled time span across the plot. UTC labels include seconds;
mobile uses three labels and desktop five. There is no chart horizontal scrolling
or continuous line. Strict/recovered points, unavailable readings, sampling gaps
and level uncertainty remain visible. Older evidence stays in **Advanced**.

Advanced EXP/percentage charts default to five recent minutes independently of
their unchanged raw table. Their range selector also offers 10/15/30 minutes and
**All loaded history**. Session/run/time filters and earlier-attempt pagination remain.

## Saved crop investigation

Native crops from `streamer_a-20261017T210323Z-6ef8ae46` visibly clip leading EXP in
attempts 9, 10 and 29. HP's detected left edge moves about 11 pixels, while LV/EXP
remain stable and MP shifts about two pixels. The previous independent spacing
comparison misses its 3% agreement test; this is geometry evidence, not a new OCR label.

A narrow fallback uses the existing LV–EXP layout span only for bare LV/MP/EXP
labels. It requires an HP outlier of 5–15%, MP within both 3% of the span-derived
spacing and one-quarter of its token width, and MP/EXP vertical agreement within
4%. Original layout validation, multiple-HUD ambiguity and frame bounds still apply.
Existing tolerances are not widened.

| Saved examples | Original padded EXP box | New geometry replay |
|---|---|---|
| 9, 10, 29 | (1033,1043)–(1139,1059) | (1024,1047)–(1123,1061) |
| Good 4 | (1023,1049)–(1122,1063) | Unchanged |
| Good 11 | (1024,1049)–(1122,1064) | Unchanged |

Only those three boxes change in this 30-attempt run. All six boxes in the subsequent
interrupted run are unchanged. Replaying saved anchors from the 44-frame temporal
set and both 45-frame cross-stream sets changes **zero of 116 available anchor
sets** (39 + 36 + 41). This checks recorded geometry, not a fresh locator/OCR run;
frames without anchors cannot test the fallback. Synthetic controls cover displaced
anchors, merged labels, source coordinates, bounds and competing HUDs.

There are **no original full frames** in these live run folders, only already
clipped field crops. The lost pixels cannot be regenerated. Thus three geometries
are corrected for future acquisition, but **zero new real OCR recoveries are claimed**.
Attempts 9/10 retain recovered 58.73% / 58.74% with absolute EXP unavailable.
Attempt 29's `$9,22` remains unavailable; no numerical substitution is introduced.
Existing contradictory-integer vetoes remain tested.

## Offline validation

| Saved run | Attempts | Original strict pairs | Usable strict/recovered percentages | Fixed windows |
|---|---:|---:|---:|---|
| Latest 30 | 30 | 9 | 27 | Building history at original final receipt |
| Subsequent interrupted run | 6 | 5 | 6 | Unavailable: level evidence/interruption |

Counts are availability, **not independently verified accuracy**. Unavailable
percentages in the first run are #2, #16 and #29. Its longest eligible segment spans
83.924 seconds, followed by 42.102 seconds and one baseline; none covers five minutes.
The interrupted log's summary says seven attempts, but only **six attempt records**
exist and are persisted. No seventh observation is invented. Its visual level context
does not establish a comparable level under the unchanged policy.

The actual shared Streamer_A database contains 66 attempts. Default five-minute graphs
now show nine attempts from **21:06:34 to 21:11:27 UTC**, with one real sampling gap,
instead of stretching back to the morning capture. Fifteen/thirty-minute views and
All loaded history deliberately retain older points and gaps. Saved timestamps are
never retimed; the live website correctly marks these saved readings stale.

Saved two-video controls (`offline_low`, `offline_window`) still show 5.83% and
25.71% independently, with stale rates withheld. Synthetic SQLite history spanning
clean rotations verifies all four populated windows, HTTP consistency, restart
breaks, boundary handling and no trusted writes.

Full Python suite: **1,181 passed, zero skips**. Node suites: **51 passed**.
Chrome checks use real localhost APIs/SQLite: desktop/mobile window controls,
recent axes, no product-chart overflow, repeated polling, historical navigation,
recovered layers and unchanged transparent 500×160 overlay. Screenshots were inspected.
Private evidence: `private/recent-windows/` (`audit.json`, `crop-review.png`,
`browser-product-04/`, `browser-advanced-03/`, `browser-offline-01/`). No new capture
or inference was performed. All 62 hash-recorded source inputs remain unchanged.
The saved database still has zero trusted observations.

On this workstation, the 66-row snapshot took about **11 ms median** over five reads;
Advanced Chrome API requests took **43–51 ms**, with about **1.55 MiB JS heap** sampled.
These are small saved-history measurements, not capture throughput or VPS forecasts.

## Run locally

From the repository root, using the existing private database:

```powershell
.\.venv\Scripts\python -m exp_tracker.server --db private/local-alpha/live/streamer_a.sqlite3 --diagnostic-dashboard
Start-Process 'http://127.0.0.1:8765/'
Start-Process 'http://127.0.0.1:8765/stream/streamer_a'
Start-Process 'http://127.0.0.1:8765/dashboard/streamer_a'
```

Serving the database is read-only and does not start Twitch capture. Stop another
server first if its port is occupied, or use `--port 8784` and adjust URLs.

```powershell
.\.venv\Scripts\python private/recent-windows/audit.py
.\.venv\Scripts\python -m pytest tests/test_recent_windows.py tests/test_product.py tests/test_adaptive_hud.py -q
node --test tools/*.test.mjs
# Existing server; choose new private output directories:
node tools/product.browser.mjs http://127.0.0.1:8765 private/recent-windows/browser-new - streamer_a
node tools/shadow.browser.mjs http://127.0.0.1:8765/dashboard/streamer_a private/recent-windows/advanced-new
.\.venv\Scripts\python -m pytest -q
```

The audit script and imagery are private workstation evidence, not public fixtures.
Public tests use synthetic data. Next practical check: a separately authorized run
long enough for five uninterrupted minutes, with crops enabled, to validate future
corrected acquisition geometry and observe real window estimates. No such trial
was initiated here.
