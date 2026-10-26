# Local unverified shadow viewer

The [local alpha](local-alpha.md) also reuses this renderer for opt-in
`/dashboard/CHANNEL`, reading separate persisted SQLite diagnostics. The JSONL
viewer described below retains its original behavior and access boundaries.

`/dev/shadow` displays actual saved shadow-capture attempts. It is **off by
default** and separate from the trusted state API, SQLite Store, OBS overlay and
simulated leaderboard. There is no capture implementation or recognition here.
Every row and API payload remains **UNVERIFIED / DIAGNOSTIC**, never trusted.

## Start

Run from the repository root, with the existing environment and a current-schema
database. The existing server still validates its read-only DB at startup; the
viewer requests themselves never open Store or write anything.

```powershell
.\.venv\Scripts\python -m exp_tracker.server --db artifacts/statistics-preview.sqlite3 --shadow-log private/shadow-capture/live-20261016-214554.jsonl
```

In another terminal:

```powershell
Start-Process 'C:\Program Files\Google\Chrome\Application\chrome.exe' 'http://127.0.0.1:8765/dev/shadow'
Invoke-RestMethod 'http://127.0.0.1:8765/dev/api/shadow' | ConvertTo-Json -Depth 8
```

Use your existing current-schema DB if the example is absent; see
[overlay setup](overlay.md) for explicit synthetic DB creation. No OCR engine,
private glyph profile, RapidOCR environment or neural model is needed to view logs.
Stop the server with Ctrl+C. Without `--shadow-log`, the page, endpoint and its
JS/CSS assets return 404. There is no host/public-bind option.

For a future running capture, configure the viewer with that capture's intended
**new** JSONL path under `private/` or `artifacts/` and start the existing
[shadow runner](shadow-capture.md) separately. A missing file is allowed: the
viewer waits, and does not create it. The runner's normal overwrite protections
remain intact. No new live capture was performed for this milestone.

## What the view means

The page shows source channel, completed attempts, raw model text, the saved strict
pair, visual level and raw visual passes, both saved arithmetic candidate sets,
their statuses, disagreement codes and UTC timestamps. Missing visual levels
remain missing; neither arithmetic hypothesis fills them. Saved full pairs and
arithmetic are not reparsed or recomputed. Complete percentage-only raw strings in
legacy logs may be strictly typed for display, explicitly marked as a legacy raw
parse; punctuation is never repaired. See [percentage-only diagnostics](percentage-only-level51.md).
Integer EXP travels as decimal text so the browser can display int64 values exactly.

Opt-in [neural-level diagnostics](shadow-neural-level.md) appear separately in the
existing level column: raw safe text, numeric candidate, score, status and comparison
with Tesseract, always EXPERIMENTAL / UNVERIFIED. Unsupported raw characters are
redacted in HTTP, retained in private JSONL. Neither a neural agreement nor conflict
changes the saved Tesseract level, arithmetic evidence, percentage charts or pace.
Missing visual evidence stays missing; complete source tiles remain unverified.

The timeline uses **points only**, with no lines/interpolation or computed gains.
Candidates, stale/not-fresh-at-capture samples and failed/rejected attempts have
different markers. Receipt gaps over **1.5× the saved nominal interval** are shaded;
these can reflect capture timing variability or missed attempts, not proven gameplay
gaps. Unknown timestamps are not invented or plotted; their count and table rows
remain visible. Missing/malformed completed lines break the readable evidence.
The vertical axis uses approximate compact labels; table values remain exact.

A separate percentage timeline shows full pairs and strictly complete `[70.51%]`
fields, never reconstructed absolute EXP. It uses exact values in tooltips and a
fixed 0–100% axis, with no connecting lines. Visual levels and known adjacent level
changes are identified; missing levels never establish continuity. Existing partial
percentage evidence from malformed fields is table-only and explicitly incomplete.

Recorded `current` means fresh **at local capture**, not fresh now or authenticated
at the broadcaster. The header's current age uses the latest available receipt time,
falling back to attempt time; records without a timestamp do not invent one.
It advances locally even on request failures. A separate viewer-only
delay threshold is **max(45 seconds, 3× saved interval)**, or 45s if cadence is unknown.
Future timestamps also mark the log stale. This is not the production 120s accounting
rule. A completed archived run is labeled completed/old, never Live.

Failed requests retain cached diagnostic rows with an explicit disconnected label.
A successful missing/unavailable-file response clears observations and reports the
absence. Source failure/offline-or-unavailable codes remain diagnostic; stream or
character identity is not inferred. Mixed channels are labeled instead of assigned
to one channel. No session totals, EXP/hour, ETA, ranks or level-up decisions.

## File/privacy and resource bounds

- Explicitly configure **one** `.jsonl` file under the working directory's ignored
  `private/` or `artifacts/`. Resolved paths are checked at startup and on each read;
  escaping paths/symlinks and nonregular files are refused. Run from the repo root.
  There is no HTTP file chooser, query-selected path or directory listing.
- Each request reads at most **512 KiB from the tail plus 64 KiB+1 from the header**;
  parses at most 512 completed tail lines, each up to 64 KiB, and keeps at most
  **120 attempts/break markers**. Omitted earlier history is explicitly indicated.
  Oversized/malformed completed lines become break markers; an incomplete final
  line waits for a newline, even if its JSON text already looks valid.
- Response fields are allowlisted. Paths, playback URLs, model/frame hashes,
  resource metadata, configuration provenance and arbitrary nested log data are
  omitted. Raw numeric-looking OCR strings are retained exactly (including malformed
  punctuation); unexpected characters or text over 160 characters are explicitly
  redacted rather than repaired. Reason/status codes and level arrays are bounded.
  Original local logs remain the complete diagnostic evidence.
- Browser polling is serial: **2s after completion**, a 5s request timeout, and
  no fetch while hidden (10s visibility checks). It keeps one bounded snapshot,
  not an accumulating history. API reads are bounded per request and independent
  of the writer; there is no incremental reader offset to get stuck after rotation.
- Same localhost bind, CSP, no-store/nosniff headers and read-only methods as before.
  No raw JSONL, images, video or crop endpoints. No new dependencies or external
  requests. This local development server is not a public security boundary or a
  hardened multi-client service; there is no OS-enforced aggregate memory quota.

## Verified test-shadow replay

The existing private **test-shadow** file has 12 attempts. A saved-log functional
check compared **all twelve** raw neural strings, exact saved EXP/percentage pairs,
visual levels and both arithmetic candidate sets against the original file.
All matched: **12 pairs, 4 visual levels, 8 unavailable visual levels**. No value was
filled or repaired. The input SHA-256 remained unchanged. This is functionality
verification, not a new accuracy benchmark. See the corrected
[review provenance](test-shadow-diagnostic.md): the maintainer ran capture; later crop
inspection was ChatGPT-assisted, not independently blinded human adjudication.

Private artifacts in `artifacts/shadow-view/`:

- `replay-check.json`, `verify_replay.py`: input fingerprint, exact checks and costs.
- `test-shadow-desktop.png`, `test-shadow-mobile.png`: actual saved data.
- `missing-log.png`, `incomplete-tail.png`, `synthetic-gaps-failures-stale.png`,
  `cached-api-failure.png`: explicit diagnostic/presentation cases.
- `browser-measurements.json`: displayed attempts, polling and local timings.

Warm-cache Windows measurements, 100 sanitized reads of the 46,791-byte log:
**0.854ms mean, 1.104ms p95, 0.781ms process CPU/read**. Response ~9,407 bytes;
one read's traced Python allocation peak ~177 KiB (not total process RSS).
Two real browser API requests in the final screenshot run took **6.7ms / 6.0ms**.
V8 reported ~1.00 MiB used JS
heap for the 12-row view; this excludes the rest of Chrome and is not a memory quota.
These are small workstation measurements, not VPS/load-test claims.

Chrome passed inspection of all twelve rows, repeated real API polling and six
screenshots, including mobile and gap/rejection/stale cases. Desktop and synthetic
gap screenshots were visually inspected. No browser/CSP errors, off-origin page
requests or page-wide horizontal overflow occurred; the mobile table/chart scroll
within their panels. Old log timestamps were retained.

## Reproduce checks

```powershell
.\.venv\Scripts\python -m pytest tests/test_shadow_view.py tests/test_server.py -q -rs --basetemp artifacts/pytest-shadow-view-focused-repeat
node --test tools/shadow.test.mjs
# With the opt-in server running:
node tools/shadow.browser.mjs http://127.0.0.1:8765/dev/shadow
# Private workspace replay checker; not part of the public checkout:
.\.venv\Scripts\python artifacts/shadow-view/verify_replay.py
.\.venv\Scripts\python -m pytest -q -rs --basetemp artifacts/pytest-shadow-view-full-repeat
```

Synthetic checks cover absent logs, partial appends, malformed/oversized lines,
source failures, staleness, path restrictions/revalidation, exact large integers,
redaction, byte/row limits, disabled routes, no Store/file writes, fixed polling,
hidden-page behavior and point/gap/stale/rejection rendering. Real mobile devices,
other browsers, Linux and hostile filesystem mutation races remain untested.
No recognition, numerical trust, tracking, SQLite, statistics, overlay or simulated
leaderboard behavior changed. No commits, pushes, deployment or new footage.

Final validation: **75 focused Python tests passed; full suite 763 passed, zero
skipped** (82.41s). All **7 Node renderer checks** and **6 Chrome screenshot cases**
passed. Compilation and `git diff --check` passed. The original test-shadow JSONL
fingerprint is unchanged. The preview server and browser were stopped afterward.
