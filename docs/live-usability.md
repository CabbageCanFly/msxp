# Last-known levels and early pace

This update changes the experimental product projection and presentation, not
trusted accounting. SQLite schema, source events, character assignments, EXP
requirements, OCR and numerical quarantine policies remain unchanged.

## What the player sees

- A supported level survives weak/conflicting readers and unavailable attempts.
  `†` and **last known** distinguish carried information; the tooltip and character
  page give its original age, timestamp and evidence source. An individual 55 does
  not replace previously supported 65. The raw reader evidence stays in Advanced.
- **Early pace** uses the existing current same-level segment: at least three
  eligible readings spanning 30 seconds. It reports reading count and actual local
  receipt span. Where supported, the provisional requirement converts pp/hour to
  approximate EXP/hour. Otherwise the section shows pp/hour.
- The selected 5/10/15/30-minute comparisons and rankings still require their
  existing 90% uninterrupted coverage. An early rate never supplies those fields.
- A broken, quarantined or stale segment pauses early pace. Its previous value,
  source span and bounds remain inspectable in the section tooltip/API; it is not
  presented as a current estimate. API failures also hide the active rate locally.
- Unknown-level chart indicators are short ticks; actual known level changes retain
  full-height boundaries. Points and missing samples remain separate, unconnected.

`display_level` is a separate read-time property selected only from reader agreement
or already-confirmed provisional neural evidence within the selected session's
bounded history. Its original event ID/time are retained; missing/recent-context
frames do not refresh it. It is **never passed into** EXP consistency, percentage
progress, estimated EXP, quarantine, pace or window eligibility. A newly corroborated
level replaces it; selecting another session/character does not inherit it.
This remains OCR support, not character authentication or independent verification.
The product uses at most the existing 640 rows; older support outside that bounded
history is not loaded merely to fill a badge.

## Trial evidence

Source: ignored `private/multi-alpha/runs/20261017T232522Z-d1ee1838/`.
Both streams have 25 acquired frames and 23 uniquely localized HUDs. All attempts
are retained. These are familiar development captures, not a new blinded benchmark.

| Result | Telfer1 | Shiphtur |
|---|---:|---:|
| Strict full pairs (unchanged) | 0 | 23 |
| Strict percentage-only (unchanged) | 16 | 0 |
| Grammar percentage proposals, before → after | 3 → 4 | 0 → 0 |
| Usable public percentage updates, before → after | 19 → 20 | 23 → 23 |
| First eligible early estimate | #8: 3 readings / 39.95s | #4: 3 readings / 39.22s |
| First early numerical estimate | approximately 157K EXP/h | approximately 123K EXP/h |
| Eligible five-minute comparison | none | none |

Telfer1's eligible segments remain 5 readings / 79.93s and 6 / 99.93s;
Shiphtur's remain 3 / 39.22s, 10 / 181.57s and 7 / 119.39s.
The recovery does not artificially extend them: #14 has no qualifying level context.
Telfer1 finishes with last-known level 65 from #19, about 120 seconds old at #25;
the latest percentage's actual level evidence remains unavailable. No numerical
EXP estimate is supplied from that carried badge. Shiphtur finishes with supported
57 and an eligible short segment; these become stale naturally when served now.

### `P[90.78%]`

Nearest-neighbor inspection of native #13–15 crops shows the left edge of #14
contains a label-tail `P`, followed by a complete `[90.78%]` field. Recorded x is
about 1017 rather than the usual 1023–1024. This is AI-assisted visual inspection,
not independent human adjudication. There is no need to change crop geometry.

Grammar policy **bounded_exp_v3** adds exactly a single uppercase `P` immediately
before an otherwise unchanged, strictly valid bracketed percentage. It records the
removed character/position and emits only an unverified percentage hypothesis.
`PP[...]`, `EXP[...]`, lowercase `p`, missing brackets, decimal-comma variants,
damaged digits and extra suffix text are not accepted by this new rule. Neither
strict parser nor the frozen legacy full-EXP policy changes.

Already recovered: #2 `[89.90%1`, #19 `[91.12%1`, #23 `[91.42%1`.
Still unavailable: #1 `89.82%1`, #21 `91.27%1` (missing openers), #24
`[91,53%)` (unsupported closer), #11/#25 (no OCR). No neighboring value, table
or level is used to choose percentage digits. Syntax cannot establish numerical
identity: known wrong `74,050` and damaged/truncated digit controls remain relevant.

The same bounded rule also exposes the older 55-attempt run's #26 `P[75.24%]`.
That run has 40 public updates instead of 39; suspicious #10, #17 and #42 remain
withheld. The earlier 41-frame Shiphtur trial retains all 41 public updates.
No newly proven numerical correctness is claimed from any grammar proposal.

### Scheduling status

Recorded maximum start delay: Telfer1 0.007s, Shiphtur 5.536s. Longest actual receipt
interval: 20.006s / 21.694s, with zero skipped deadlines. Waiting status now tolerates
half a requested interval, bounded to 2–15s (10s at this cadence). Beyond that it
still reports delayed capture. Running-job timeouts and capture failures remain
separate and unchanged. No fresh reading is used to imply an active coordinator.

## Validation and reproduction

Private evidence: `private/live-usability/trial-evaluation.json`, input log hashes,
native-crop sheets, quarantine regression replay and Chrome verification outputs.
Thirty projections per stream had median adapter cost about 0.41/0.48ms on this
workstation. Additive level/history metadata increased each final player JSON by
about 5.8KB; no additional SQL history query or capture/model process is introduced.
These are local projection measurements, not VPS or capture throughput claims.

The Chrome replay harness commits unchanged saved events while the homepage,
character page and transparent 500×160 overlay stay open. It uses an explicitly
**as-of review clock**, never rewrites timestamps or claims a live broadcast.
It verifies early pace, incomplete windows, final last-known level, rate suspension,
both streams and polling without page navigation. Screenshots are under
`private/live-usability/browser-trial-04/`. A separate quarantine Chrome regression
checks pending decrease, confirmation and recovery using clearly synthetic controls.

```powershell
# View the real saved database; no capture begins. Old readings are correctly stale.
.\.venv\Scripts\python -m exp_tracker.server --db private/multi-alpha/live-telfer-shiphtur.sqlite3 --diagnostic-dashboard --port 8766
Start-Process 'http://127.0.0.1:8766/'
Start-Process 'http://127.0.0.1:8766/stream/telfer1'
Start-Process 'http://127.0.0.1:8766/live/overlay/telfer1'
Start-Process 'http://127.0.0.1:8766/dashboard/telfer1'

# Reproduce the private as-of replay; choose a NEW output directory each time.
node tools/product.browser.mjs http://127.0.0.1:8778 private/live-usability/review-new --verify-usability telfer1
node --test tools/*.test.mjs
.\.venv\Scripts\python -m pytest -q -rs
```

Validation: **1,241 Python tests passed, zero skipped**, including the existing
numerical/quarantine controls; **57 Node tests passed**. The initial sandboxed
suite had 1,240 passes and one loopback-socket environmental skip; the final run
with loopback access passed all tests. Focused Python checks passed 115 tests.
Chrome saved-trial checks captured 12 screenshots; the separate quarantine/update
check captured 11. Both passed without console exceptions or external requests.
The first sandboxed Chrome launch was blocked by its environment; the permitted
local-browser run succeeded. `git diff --check` passed.

Changed files: `README.md`; this guide; `src/exp_tracker/product.py`,
`diagnostics.py`, `shadow_grammar.py`; `src/exp_tracker/web/player.html`,
`product.css`, `product.js`, `shadow.js`; `tests/test_live_usability.py`;
`tools/product.test.mjs`, `product.browser.mjs`, `product_updates_fixture.py`.

No new Twitch capture or OCR inference was needed. Future authorized live use should
check that early estimates appear, disappear after interruptions, and never become
fixed-window rankings prematurely. OCR correlation, wrong digits and provisional
community requirements still prevent authoritative numerical accounting.
