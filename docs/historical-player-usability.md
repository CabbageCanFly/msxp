# Completed captures, historical statistics and chart inspection

This is a presentation update using the existing read-only diagnostics. No OCR,
requirements, schema, capture evidence or trusted accounting changed.

## Why Shiphtur showed dashes

The 90-attempt two-stream capture under
`private/multi-alpha/runs/20261018T043432Z-c0b93f52/` completed a clean 60-attempt
rotation. It did not fail acquisition. However, recognition/level evidence still
has gaps: the final Shiphtur attempt has no numeric reading, and attempt 27 of
the second run has no supported level. The latest observed sequence therefore
contains only attempts 28–29: **two readings / 20.622s**, insufficient for the
existing three-reading / 30s observed-window summary. Staleness was not the
original cause. The former 49,579 EXP/hour value came from that short tail.

For completed/interrupted captures, the projection now retains the latest earlier
eligible sequence **inside the selected capture-relative window**, from the same
validated rotation chain and supported level. It never joins pieces across the
reset. API metadata marks the result historical/paused and retains exact endpoints,
reading counts and actual span. The public card says **Saved 30 min**, with the
actual duration and age below it. These are saved comparisons within that selected
period, never complete measurements of the entire selected period.

At capture completion, +5m and +78m:

| Channel | Selected period | Saved comparison | Actual span |
|---|---|---|---|
| Shiphtur | 5/10/15/30 min | ~3,506 EXP, 8 readings | 139.684s |
| Telfer1 | 5 min | ~17,998 EXP | 280.203s |
| Telfer1 | 10 min | ~37,829 EXP | 580.045s |
| Telfer1 | 15/30 min | ~40,162 EXP | 639.955s |

Shiphtur's retained interval is **05:00:18.250966–05:02:37.934711 UTC**.
All four selections show that same latest eligible piece; there is no supported
longer comparison across the late resets. None of these completed captures gains
strict full-window/ranking eligibility. It is not a new accuracy benchmark.

When the final completed-capture tail is too short, saved pace likewise retains
the latest earlier eligible trend within five minutes, from the same supported
level and rotation chain. It uses the existing captured-interval mathematics,
excluding missing intervals from gain and time. Shiphtur now shows approximately
**88,864 EXP/hour / 8 readings / 139.684s**, dated at 05:02:37 UTC. This is a
broader saved sample, not a claim of improved numerical correctness or a live rate.
Telfer1 retains its existing ~230,833 EXP/hour trend over 200.124 captured seconds
within 280.203s. Completed/interrupted trends are inactive and expose no live ETA.

Standalone HTTP can report **Capture finished** from a recorded completion summary,
**Capture stopped** from interruption, or **Last tracked … ago** for old evidence
without current worker activity. In-process worker state still takes precedence;
connection errors and real active delays remain visible. None implies Twitch is
offline. Raw level/percentage decisions remain unchanged in Advanced.

## Numbers and tooltips

Player values and roomy homepage bars show full comma-separated integers where
they fit. Actual measured element width determines fallback to compact K/M/B.
Resize/polling reevaluates the fit; compact tooltips retain the full available
value. Cards use whole EXP units rather than arithmetic fractional digits.
Observed integers remain direct values; computed values keep their approximation
cue and requirement/quantization provenance. More digits do not make OCR exact.
The 500×160 OBS panel retains compact formatting.

Both chart modes have small custom, text-only tooltips outside the clipping
container. They show local date/time **with timezone**, original percentage
precision and available/approximate EXP. Buckets show duration and complete/partial
coverage. Missing buckets/points say **No reading**/**Reading unavailable**, not
zero. Supported interactions: hover, keyboard focus/Escape and touch tap/dismiss.
Polling preserves focus, refreshes an open tooltip's value by stable event/bucket
key, and closes it if that target disappears. Escape dismissal survives redraw.
The existing native SVG titles/aria descriptions remain available.

## Verification and reproduction

Private `private/historical-usability/audit.json` compares the committed pre-task
projection with the new one at completion, +5m and +78m, asserting unchanged strict
eligibility. All six input hashes are preserved. Projection cost was ~32–33ms for
Shiphtur and ~55–59ms for Telfer1 on this workstation. Ten measured 30-bar redraws
were ~1.3–3.4ms in the final browser check; not an estimate of device/VPS capacity.

SQLite-backed Chrome checks replay all 180 original attempts into a fresh private
database, commit the last attempts while pages are open, then age the review clock
78 minutes. They check all four selections, actual polling without navigation,
open-tooltip numeric refresh, covered/partial/missing buckets, available/unavailable
dots, keyboard/Escape across polling, mobile touch, viewport bounds, responsive
numbers and the transparent OBS overlay. Source times/payloads are never retimed.
The offline fixture's explicit character label is “Saved review”.

```powershell
# Serve existing real data; does not start Twitch capture.
.\.venv\Scripts\python -m exp_tracker.server --db private/multi-alpha/live-telfer-shiphtur.sqlite3 --diagnostic-dashboard --port 8766
Start-Process 'http://127.0.0.1:8766/stream/shiphtur'
Start-Process 'http://127.0.0.1:8766/stream/telfer1'

# Choose a NEW private output directory.
node tools/product.browser.mjs http://127.0.0.1:8781 private/historical-usability/review-new --verify-historical shiphtur
.\.venv\Scripts\python -m pytest -q -rs
node --test tools/*.test.mjs
```

Screenshots are private under `private/historical-usability/browser-validated/`:
`historical-desktop.png`, `historical-mobile.png`, `historical-homepage.png`,
`bar-tooltip-desktop.png`, `bar-tooltip-mobile.png`, `point-tooltip-desktop.png`,
`telfer-historical-desktop.png` and `historical-overlay.png`.

Changed files: `src/exp_tracker/product.py`, `diagnostics.py`,
`web/product.js`, `web/product.css`; `tests/test_historical_product.py`;
`tools/product.test.mjs`, `product.browser.mjs`, `product_updates_fixture.py`;
`README.md`, `docs/product-experience-principles.md` and this guide.
No new dependencies. Fresh live capture, physical touch devices and screen-reader
adjudication were not tested. Unobserved gains, complete historical windows and
current pace cannot be manufactured from the retained samples.

Validation: **1,315 Python tests passed, zero skipped**; **68 Node tests passed**;
**62 focused Python tests passed**; actual SQLite-backed Chrome checks passed.
`git diff --check` passed. No commits or external captures were made.
