# Percentage tokens, short HUD gaps and durable character ETA

This read-time follow-up preserves raw logs, SQLite payloads, strict parsers,
trusted accounting and strict completed-window/ranking rules. No capture, model
inference, schema migration or active-database write was performed.

## Saved cases

| Causal prefix | Before | After |
|---|---|---|
| Telfer1 rotated run `93dd…`, #5, 20:58:08 UTC | `56.97%1` unavailable | 56.97% grammar proposal; no OCR EXP integer |
| Niru run `e45e…`, #4, 21:16:00 UTC | Missing HUD | Still no numerical point |
| Niru #5, 21:16:20 UTC | Level confirmation pending; excluded from progress/chart | Provisional 56, compatible full pair, eligible |

The Niru sequence is neural-only pending at #1, corroborated 56 at #2–3,
unavailable at #4, then supported 56 at #5–7. The new policy preserves the
independent reader anchor through #4; #5 still supplies its own neural 56 and
arithmetically compatible `757,975[77.54%]`. It is not a carried numeric reading.
The chart retains the #4 gap. The responsive estimator may independently use
#3→#5's actual cumulative endpoint difference and elapsed time; it invents no #4
value. The first frame admitted using carried context is marked ineligible for
strict completed-window evidence.

First-seven-attempt comparisons against an isolated copy of the committed
implementation, with unchanged source timestamps:

| Stream | Eligible readings before → after | Sampled elapsed | EXP/hour before = after |
|---|---:|---:|---:|
| Telfer1 | 6 → 7 | 178.304s | ~221,731 |
| Niru | 4 → 5 | 99.954s | ~151,234 |

These rates do not increase merely because a missing interior point becomes
available. This is familiar development evidence, not a new accuracy benchmark
or independent human adjudication.

## Bounded policies

`bounded_exp_v5` recognizes a standalone, whole-string `DD.DD%` token followed
by at most three closing-bracket lookalikes (`]`, `1`, `|`, `I`, `l`). It records
the exact token and ignored suffix positions; it inserts no opening bracket,
EXP integer or digit. Existing explicitly delimited formats retain their rules.
`0.85%1`, `170 57%1`, competing percentage tokens, missing fractional digits and
unsupported prefixes remain rejected. The percentage passes the ordinary public
review, temporal/level gates and numerical quarantine. Strict parsing is unchanged.

`experimental_level_v4` carries only an already corroborated reader anchor through
at most two ordinary missing/failed attempts, for at most 120 seconds from its
last independent support. Missing attempts do not renew that expiry or receive
a level/percentage point. Ownership, source, ordering and distinct-frame guards
still apply. Competing levels, stale/duplicate frames, incomplete level tiles,
ambiguous HUDs, excessive local age and unvalidated run changes clear continuity.
Shiphtur's genuinely stale #33 remains excluded; #34 remains pending and #35–42
remain eligible. Telfer1's wrong whole pair at #21 remains vetoed before either
field can establish a public value, baseline, chart point or gain.

## ETA is a dated duration, not live pace

Each selected 5/10/15/30/60-minute period now exposes a separate `eta` projection:
the original duration and rounding bounds, supporting level/source, sample count,
actual coverage, `estimated_at`, age and window basis. A valid selected-period rate
uses the existing exact arithmetic. When that period ages out, its last supported
estimate remains historical; its recent gain becomes unavailable as before.

Failed/missing OCR, temporary quarantine, stopped/offline capture and failed HTTP
polling cannot erase this character-page duration. Age increases; duration does
not count down or recompute merely because polling ages old rate samples out.
Its selected-period rate is anchored at the supporting observation timestamp;
fresh supported evidence replaces it. The four cards remain present.
The OBS overlay now uses the same validated five-minute window gain and dated ETA
as the character page with five minutes selected. Its progress label is **Last 5 min**.
Missing OCR and failed polls preserve supported totals and the original ETA duration;
they do not invent missing readings or renew its observation timestamp. Backend
level/reset/source guards still decide whether an ETA is available.

After a server/coordinator restart, bounded read-only SQLite replay can restore
the dated estimate for the same selected character/session/source. No endpoint
subtraction crosses an unvalidated restart. If the ordinary 65-minute query has
no eligible intervals, restoration reuses the sanitized causal decoder and the
existing 1,024-run, 65,536-attempt and 128MiB source-work limits; retained rows are
capped at 4,096. The HTTP server caches only compact ETA results for up to eight
channels, invalidating on new attempts or run/lifecycle changes. API metadata
reports `recent_history.eta_status` and work receipts, including explicit limits.
Supported read-only schema-v3 databases restore ETA without a migration. A lone
new reading after a long outage cannot evict the older rate; two new supported
endpoints replace it without subtracting across the outage.

One reading, nonpositive gain, missing/disputed requirements, a known level
conflict, confirmed loss awaiting new supported gain, a new session or changed
source can legitimately leave ETA unavailable. Arithmetic cannot identify every
wrong but internally consistent digit pair; estimates remain untrusted.

## Validation and reproduction

Private evidence is under `private/eta-followup/`: source-hash receipts,
`before-v2.json`, `after-final.json`, `checkpoint-baseline.json`,
`checkpoint-final.json`, measurements and isolated replay databases. The final
browser checks use real saved JSONL values; their as-of clock and restart lifecycle
are explicitly simulated. They do not claim a new live-capture evaluation.

```powershell
.\.venv\Scripts\python -m pytest
node --test tools/*.test.mjs
node tools/product.browser.mjs http://127.0.0.1:8874 private/eta-followup/browser-new --verify-eta-followup niru
node tools/product.browser.mjs http://127.0.0.1:8875 private/eta-followup/veto-new --verify-numerical-windows telfer1
```

Use new output-directory names. Chrome checks polling without navigation, all five
selectors, missing-HUD recovery, numerical veto/recovery, restart, two-hour expiry,
another hour without database revisions, cached HTTP failure, desktop/mobile
layout and the 500×160 overlay. Screenshots were inspected for wrapping/overflow.

Final validation: **1,547 Python tests passed; 77 Node tests passed; zero skips**.
Both real SQLite-backed Chrome workflows passed without console errors, with
16 ETA/recovery screenshots and 19 numerical-veto/recovery screenshots.

On the isolated saved sessions, two-hour-old cold restoration plus full player
projection took ~41ms for 60 Niru attempts and ~105ms for 161 Telfer1 attempts.
Cached medians were ~21ms/~61ms; Python allocation peaks were ~1.35/~3.76MiB.
These are small local workloads, not capacity measurements for 25 long-running
channels. No additional Twitch requests were made.

Changed files: `shadow_grammar.py`, `diagnostic_evidence.py`, `product.py`,
`rolling_history.py`, `diagnostics.py`, `server.py` and `web/product.js` under
`src/exp_tracker/`; `tests/test_eta_followup.py`, `test_extended_diagnostics.py`,
`test_live_usability.py`, `test_numerical_windows.py`, `test_pace_reacquisition.py`;
`tools/product.browser.mjs`, `product.test.mjs`, `product_updates_fixture.py`;
this note, `docs/product-experience-principles.md` and `README.md`.
