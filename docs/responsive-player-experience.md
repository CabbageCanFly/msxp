# Responsive player estimates and level-aware history

Public UI follows the [player experience principles](product-experience-principles.md):
useful approximate information first; raw evidence and caveats remain in Advanced.
The website and experimental 500×160 OBS overlay keep their existing routes/design.

## Pace and uncertainty

`product.responsive_pace` is an additive read-only presentation, not a change to
trusted statistics, the strict diagnostic engine or fixed-window rankings.

- At least **two accepted same-level readings spanning five real seconds** can
  seed a first estimate. Five seconds prevents near-simultaneous rate calculations;
  it is a presentation floor, not an empirical guarantee of OCR correctness.
- As readings accumulate, use the earliest and latest actual endpoints within
  the last **120 seconds of that connected segment**. No boundary interpolation,
  voting, reconstructed values or averaging across interruptions.
- Prefer differences of original strict numerical EXP endpoints when both pass
  the existing level/percentage consistency check and are nondecreasing. Otherwise
  use displayed percentage differences and the selected provisional requirement.
  With a missing/disputed requirement, only pp/hour can be shown.
- Exact Fractions and existing separate half-up/truncation quantization bounds
  remain in metadata. Those display-precision bounds exclude OCR and table errors.
  When numerical EXP endpoints supply the central rate, the percentage-derived
  hypothesis ranges remain a separate diagnostic, not calibrated error bars.
- Two readings, or a span below 30s, remain a **first estimate**. ETA still requires
  at least three readings over 30s and positive lower pace bounds under both
  hypotheses. Inactive estimates never supply ETA.
- Failed/missing/stale/ambiguous observations, quarantine, losses, unknown levels,
  excessive gaps, source/session/character changes and restarts retain their existing
  segment breaks. Old estimates remain visible as **last estimated X ago**, with
  original endpoints, level, age and evidence. New endpoints start a separate trend.
- Do not display a previous level's historical rate as the new level's rate.
  A fresh level starts building again. Historical values remain in Advanced.

The current rate has one primary place on the character page; completed-window
comparisons are separate. Ranking still requires unchanged 90% contiguous window
coverage. There are no new gains, session totals, maximum gain-rate limits or
trusted neural promotions. Zero displayed movement is not proof of zero actual EXP.

## Level-up presentation and chart

Existing level selection is unchanged. A presentation event requires a previously
supported level followed by **two adjacent supported readings one level higher**,
both below the prior level's displayed percentage. Context must match channel,
source, character, session and run; the previous supported context is at most 120s
old. New readings must pass existing freshness/continuity/public eligibility checks
and have distinct known source-frame hashes. Missing/duplicate hashes abstain.
No event is inferred just from falling percentage. Multi-level jumps and unclear
context can update supported display evidence without earning this event banner.

The marker uses the second reading's confirmation timestamp and retains the first
new-level reading's timestamp separately. It does not establish the precise instant
of leveling, prove character identity or account cross-level EXP. Shared model errors
can still fool this corroboration; it remains an experimental presentation event.

The public chart defaults to **the latest supported level within the selected
5/10/15/30-minute window**. It uses a labeled local percentage scale, small dots
and trend lines only where the existing progress engine explicitly permits an edge.
Unknown-level points and excluded observations leave gaps. No line crosses a loss,
quarantine, run restart, level change or missing observation. Trend lines do not
claim to observe the timing of intermediate gains. Earlier levels remain in Advanced.

Levels use plain `Lv. 66`. Last-known age/provenance remains in a tooltip and small
secondary detail; repeated stars, daggers and warning banners are removed. A small
information line explains approximate stream readings. Raw evidence is unchanged.

## Actual trial replay

Source: ignored `private/multi-alpha/runs/20261018T001050Z-b970792e/`.
Native RGB/nearest-neighbor review supports 65 at #13, then 66 at #14/#15;
this is AI-assisted inspection of familiar material, not new blinded ground truth.
All 42 attempts per stream and original log hashes are preserved.

| As-of each committed attempt, before final interruption | Streamer_A | CharB |
|---|---:|---:|
| First old ≥3 / ≥30s active pace | #18 | #13 |
| First responsive pace | #15 | #4 |
| First responsive span / readings | 8.7764s / 2 | 10.320735s / 2 |
| First approximate numerical rate | 136,183 EXP/h | 138,130 EXP/h |
| Attempts with old active pace | 5 / 42 | 15 / 42 |
| Attempts with responsive active pace | 18 / 42 | 26 / 42 |

These are causal availability comparisons, not OCR accuracy or independent samples.
Interrupted historical values remain available when no rate is active. The final
interruption suppresses active pace; it does not erase the last estimate.

Streamer_A #14 contains `103[0.01%]`, #15 `435[0.03%]`. The badge shows 66 at #14;
the level event is confirmed at #15. Their strict consistent integer difference
supplies the first rate. By #18, five eligible endpoints span about 37.6s and support
a recent trend around 220K EXP/h. Short estimates remain noisy: #42's two-reading
value is about 278K/h, explicitly historical after shutdown. No 65→66 gain is counted.
Contradictory integers such as the later `6.222[0.41%]` stay withheld; percentages
remain separate evidence. No numeric correction or new accuracy claim is made.

Requested cadence was **7s per stream**. Attempt-start intervals averaged
**9.732s / 9.716s**, maxima **12.048s / 12.217s**. Each final cumulative skipped
deadline counter is **16** (do not sum the cumulative per-event counters).
At this cadence, the existing 1.5× interval gap boundary is 10.5s; overload repeatedly
breaks segments. The application does not turn seven requested seconds into seven
observed seconds. Existing owned-coordinator delay warnings remain; this is sustained
overload, not harmless jitter. Use **15–20s** initially for two real streams. No
coordinator parallelization, timeout or scheduling changes were needed.

Median adapter cost over the 42 causal prefixes was about **0.91ms / 0.80ms** on
this workstation. No new SQL query, capture process, model or dependency is added.

## Reproduce and inspect

```powershell
# Existing actual database, read-only. Serving does not initiate capture.
.\.venv\Scripts\python -m exp_tracker.server --db private/multi-alpha/live-local.sqlite3 --diagnostic-dashboard --port 8766
Start-Process 'http://127.0.0.1:8766/'
Start-Process 'http://127.0.0.1:8766/stream/streamer_a'
Start-Process 'http://127.0.0.1:8766/live/overlay/streamer_a'

# Unchanged saved events, fresh private DB, explicit as-of clock, no OCR or Twitch.
# Choose a NEW output directory for each run.
node tools/product.browser.mjs http://127.0.0.1:8778 private/player-experience/review-new --verify-level-up streamer_a
node tools/product.browser.mjs http://127.0.0.1:8779 private/player-experience/quarantine-new --verify-quarantine streamer_a
.\.venv\Scripts\python -m pytest -q -rs
node --test tools/*.test.mjs
```

Private comparisons: `private/player-experience/timeline-results.json`, immutable
input log hashes and `level-up-source.png`. Chrome's `browser-level-up-03/` includes
desktop/mobile homepage, first-estimate character page, current-level history and
transparent overlay screenshots; `browser-quarantine-01/` retains the existing loss
confirmation/update checks. Both use real SQLite/HTTP polling without navigation.
The test server's clock is explicitly as-of; source timestamps are not rewritten.

Validation: **1,253 Python tests passed, zero skipped**; **59 Node tests passed**.
Focused Python checks passed 94 tests. Chrome level-up checks passed with 13
screenshots, and the separate quarantine/update checks passed with 11 screenshots.
They checked desktop/mobile overflow, the 500×160 transparent overlay, polling
without navigation, first estimates, fixed-window separation, paused values and
loss recovery. No browser console exceptions or external requests were observed.
`git diff --check` passed. Actual OBS and a new live stream were not tested here.

Changed files: `src/exp_tracker/product.py`; `web/product.js`, `product.css`,
`tracker.html`, `player.html`, `live-overlay.html`; `tests/test_responsive_product.py`;
`tools/product.test.mjs`, `product.browser.mjs`, `product_updates_fixture.py`;
`README.md`, this guide and `docs/product-experience-principles.md`.

The next practical check is a manually authorized two-stream trial at 15–20s,
reviewing early-rate stability and pauses rather than relaxing continuity to make
charts look continuous. New independent numeric review is still necessary before
trusted ingestion. No new capture, model tuning, schema or requirement change,
commit, push or deployment was performed here.
