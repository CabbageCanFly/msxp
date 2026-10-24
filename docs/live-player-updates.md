# Live player updates and percentage-derived EXP

Player pages now keep the existing two-second polling schedule in background
tabs as well as foreground tabs. (The homepage list later moved to 4 s, and 30 s while
hidden; see [background publishing](background-publishing.md).) Returning to a page requests an immediate refresh;
only one request can run at a time, with the existing five-second timeout and
cached-value/stale safeguards. No full-page navigation is needed. Browsers may
still throttle background timers. API `no-store` headers and SQLite revision-cache
invalidation were already correct and remain unchanged.

`local_alpha.py` previously never populated its HTTP server's in-process runtime
status. That made an owned worker appear stopped. An optional callback around the
existing shadow capture attempt now reports running, waiting or acquisition failure.
The launcher binds that to its committed run UUID and clears activity on completion,
interruption or failure. Fresh readings and unfinished database runs never imply
worker ownership; a separately started HTTP server still cannot authenticate another
process's capture activity. Network failure does not establish Twitch offline status.

## Million-plus investigation

The saved 2026-10-17 21:46 CharB run retains **41/41 fresh strict full pairs and
unique HUDs**. Neural level is 57 throughout; the unchanged read-time policy selects
57 on 40 frames after its first pending baseline. Its first-to-last receipt span is
280.131 seconds; the roughly 287-second interrupted process is not a complete
five-minute comparison. No window rule was relaxed.

The 21:45 Streamer_A run retains **0/5 strict full pairs, 3/5 strict percentages and
5/5 unique HUDs**. Native crops #3–#5 start with a visible opening bracket and leave
unused space after the closing bracket. Compared with earlier six-digit fields,
this supports an actual percentage-only HUD presentation, rather than a right crop
boundary losing a seven-digit suffix. It does not prove the client's responsive
formatting rule or authenticate numerical correctness. No full frames were saved,
so information outside these crops cannot be inspected or recovered.

Attempt #2 also has the earlier right-shift pattern. Replaying its anchors shows
that it **still fails** the existing narrow MP-residual checks. It remains unresolved;
no tolerance was widened just to fit this example. No crop geometry, locator,
recognition model, grammar or level-confidence policy changes were justified here.
CharB's 41 crop geometries, normal six-digit controls and cross-stream localization
therefore remain untouched. Seven-digit grouped integers already parse (tested with
`1,069,917[67.72%]`); the new fallback does not manufacture such an OCR reading.

## Approximate EXP presentation

When observed/recovered absolute EXP is unavailable or arithmetically withheld,
the existing selected experimental visual level and supported provisional requirement
may produce **`reading.estimated_exp`**. This is separate from `reading.exp` and all
SQLite/raw candidates. It never supplies trusted accounting, progress endpoints,
session gains or an inferred level.

The nominal value is the exact rational `displayed_basis_points × requirement / 10000`.
Both nearest-half-up and truncation integer bins come from the existing exact-arithmetic
diagnostic, including within-level limits and empty bins. Neither hypothesis is
selected. If neither has a compatible integer, no estimate is returned. The UI shows
roughly three significant digits, e.g. **≈1.07M**, with both ranges and community-table
provenance in the tooltip. The ranges describe display precision, not OCR/table error.
Direct integers keep their normal full numerical formatting. Stale values retain
their age/status and do not acquire current pace.

**Streamer_A limitation:** its four numeric level-65 predictions score 0.68623–0.84812,
with no accepted Tesseract level or qualifying neural seed. The unchanged policy
leaves level unresolved on all five frames. Therefore this particular run correctly
shows percentages but **no percentage-derived EXP estimate**. The user-observed level
is evaluation context, not a hardcoded substitute. Missing/disputed requirements
also leave derived EXP unavailable.

## Actual HTTP/SQLite/browser verification

The browser regression opens `/`, `/stream/streamer_a` and `/live/overlay/streamer_a` against
a fresh read-only localhost server, with a separate SQLite writer. It inserts the
remaining **unchanged saved** Streamer_A and CharB attempts while pages are open:
Streamer_A moves **67.68 → 67.72%**, and CharB's 41st saved reading becomes visible.
Source timestamps, UUIDs, indices and raw outputs are not retimed/repaired. These
historical readings remain stale. All pages keep one navigation; background polling
works and no console exceptions or external requests occur. One measured update
batch reached all checked DOMs in **about 2.00 seconds**.

A third, explicitly labeled **Synthetic window test** is a distinct regression
control, not capture evidence. Nineteen synthetic same-level observations initially
fail window coverage; two additional committed observations establish **21 readings
over exactly 300 seconds**. The real progress engine/API then populate the five-minute
metric, rate and rank, and the open browser updates without reload. Its separate
overlay verifies the `≈1.07M` presentation. No HTTP responses are replaced with fixtures.
This does not claim a new five-minute real-video/Twitch accuracy benchmark.

Private results: `private/live-updates/audit.json`, `field-comparison.png`, and
`browser-05/{verification.json,after.json,*.png}`. Desktop/mobile screenshots,
percentage-only and estimated overlays, and the populated five-minute control were
inspected. All **96 hash-recorded source logs/crops** remain unchanged. Replay/test
databases contain zero trusted observations. The five-row read-time snapshot measured
about **0.7 ms median** over five local reads, not an OCR/VPS benchmark.

Synthetic tests cover exact bins, direct-integer precedence, invalid integers,
unknown/disputed levels, impossible percentage bins, zero/100% bounds, activity
lifecycle, failing acquisition, background/resume polling, stale/error recovery and
single-request serialization. No schemas, EXP requirements or trusted Store semantics
changed. Final validation: **1,189 Python tests passed, zero skipped; 54 Node tests
passed; actual Chrome/SQLite checks passed**. `git diff --check` passed and the
test-owned HTTP process shut down cleanly.

## Try it

Existing actual Streamer_A data (no capture starts):

```powershell
.\.venv\Scripts\python -m exp_tracker.server --db private/local-alpha/live/streamer_a.sqlite3 --diagnostic-dashboard
# In another terminal:
Start-Process 'http://127.0.0.1:8765/'
Start-Process 'http://127.0.0.1:8765/stream/streamer_a'
Start-Process 'http://127.0.0.1:8765/live/overlay/streamer_a'
```

A fresh actual-data-only combined replay is prepared at
`private/live-updates/saved-review.sqlite3` (46 unchanged attempts; `streamer_a` and
`streamer_b`, separate explicit Main characters/sessions). Serve that database instead
to inspect both saved runs together. The private preparation script refuses overwrite.
Restart the launcher/server and reload old browser assets once after applying code
changes; Python workers do not hot-reload. Later observations update automatically.

```powershell
# Self-contained bounded browser regression; NEW output directory and unused port:
node tools/product.browser.mjs http://127.0.0.1:8787 private/live-updates/browser-new --verify-updates streamer_a
.\.venv\Scripts\python -m pytest tests/test_product.py tests/test_local_alpha.py tests/test_shadow_capture.py -q
node --test tools/*.test.mjs
.\.venv\Scripts\python -m pytest -q
```

Changed implementation: `src/exp_tracker/product.py`,
`src/exp_tracker/web/{product.js,tracker.html,player.html}`,
`tools/{local_alpha,shadow_capture,product_updates_fixture}.py` and
`tools/product.browser.mjs`. Tests: `tests/{test_product,test_local_alpha,test_shadow_capture}.py`
and `tools/product.test.mjs`. Documentation: this note, README, local-alpha and
product-preview guides. The browser fixture is test-only and requires the private
saved logs; public unit tests use synthetic data.

No new capture/inference was needed. Next live check, only after authorization:
restart the one-command launcher, enable saved crops and observe foreground and
background pages during a 6–10 minute bounded trial. Confirm the same printed database/
port is open, check level-evidence availability, and review any shifted/full-field
failures with wider source context before changing crop constraints.
