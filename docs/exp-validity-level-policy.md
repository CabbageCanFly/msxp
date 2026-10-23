# EXP validity and provisional level context

Follow-up: [whole-pair numerical veto and level evidence v3](numerical-windows-eta.md)
supersede the unconditional percentage-retention description below when recent
independently corroborated level evidence contradicts the entire pair. These
earlier saved-run results remain historical.

One read-time projection now supplies the product pages and SQLite diagnostic
dashboard. Raw OCR, saved parser candidates, Tesseract/neural outputs and database
payloads are unchanged. No trusted ingestion, schema migration or level-up handling.

## Policy

`exp_validity` is **consistent**, **invalid** or **indeterminate**. The existing
exact integer `assess` helper moved unchanged into `exp_tracker.exp_consistency`;
the original tool re-exports it. With supported provisional visual-level context,
a full integer is withheld only when **both** nearest-half-up and truncation
contradict its percentage. Either match is conditional consistency, not digit
verification. Missing/disputed requirements and unresolved levels are indeterminate,
not a veto. Neither rule is selected or used to reconstruct EXP.

The percentage remains independently available under ordinary syntax, freshness
and continuity gates. The product integer becomes null; diagnostics retain its
original pair labeled **WITHHELD**, omit the integer from the EXP chart and retain
the percentage point. No immutable event or grammar interpretation is rewritten.

`experimental_level_v1` uses earlier adjacent visual observations only:

- Current reader agreement and existing Tesseract-only evidence remain available.
- A neural-led context needs two matching numeric Neutral4 readings, at least
  one score >=0.90, and a strict full pair conditionally supporting that visual
  level. Alternatively, three matching readings can establish provisional context
  without arithmetic if there is no competing visual or arithmetic contradiction.
  Grammar proposals cannot seed arithmetic corroboration. Zero/0.00% cannot either.
- **0.90 is a conservative seed-quality setting, not calibrated correctness** or
  a fitted cutoff between this run's 55/65 scores. A single .999 prediction cannot
  override a conflict. Lower scores may retain an already corroborated context.
  Known wrong RGB 50 predictions score above .99; confidence/repetition prove neither
  numeric identity nor complete tiles. No RGB fallback or text substitution exists.
- The established same neural level can continue without per-frame Tesseract
  agreement. Overriding conflicting Tesseract needs strict arithmetic support
  within 30 seconds. Both raw readers and decision reasons remain visible.
- At most two missing/nonnumeric level readings, within 30 seconds of actual
  supporting visual evidence, may retain neural-confirmed context. Tesseract-only
  baselines cannot supply this carry. No missing EXP/percentage is filled in.
- A changed neural numeral abstains immediately and needs reconfirmation. Failed,
  stale or ambiguous captures, missing attempts, source/character/session changes,
  excessive gaps and restarts reset context. Only validated clean run rotation can
  cross run IDs. Explicitly incomplete tiles abstain.

Progress uses the provisional selected level while retaining raw `visual_level`.
Negative percentages and uncertain/new levels still break segments. Two agreeing
wrong readers or repeated self-consistent wrong fields can pass this diagnostic
policy. No character identity, automatic level-up or maximum EXP-rate rule is inferred.

## Saved-run results

Input: `private/local-alpha/runs/streamer_a-20261017T195421Z-8fa57aab/capture.jsonl`.
Database: `private/product-preview/streamer_a-manual-01.sqlite3`, containing these 30
attempts plus one earlier failed attempt. User-confirmed level 65 is evaluation
context only. James confirmed no source crops were saved; glyphs cannot be reviewed.

| Specified 30-attempt run | Before | After |
|---|---:|---:|
| Original strict full-pair syntax | 20 | 20 unchanged |
| Usable strict/recovered percentage syntax | 29 | 29 unchanged |
| Displayable full integers | 26 | 24 |
| Progress-eligible attempts | 2 | **26** |
| Pace-qualifying segments | 0 | **2** |

Selected levels match the user's 65 context on 27 attempts; 1, 12 and 13 abstain.
Attempt 14 has level context but no usable percentage. Raw neural **55 (.77774)**
at 12 is preserved, never selected; 13 waits for confirmation. Segments are #2–11
(+0.15 pp / 54.097s) and #15–30 (+0.26 pp / 90.025s), recorded paces 9.98 and
10.40 pp/hour. Nothing bridges #12–14 or claims verified EXP gains.

| Attempt | Raw | Read-time result |
|---|---|---|
| 3 | `2,316[45,09%]` | Existing recovered 45.09%; no complete full-EXP proposal |
| 4 | `2,458[45.09%]` | Integer invalid under both hypotheses; strict percentage retained |
| 5 | `2,802[45.12%]` | Integer invalid under both hypotheses; strict percentage retained |
| 6 | `713,015[45.13%]` | Consistent under both; integer retained, still unverified |

Against unchanged community level-65 requirement **1,579,913**, 18/20 strict pairs
are conditionally consistent and two contradict both rules. This is not proof of
the requirement's recording-build applicability or the client's formatting rule.
Small substitutions remain undetectable: both 74,050 and 74,059 / 25.17% at level
40 survive nearest rounding. Existing 2345/92.74% level-6 and 1241/99.82% level-9
negatives fail both. We cannot claim zero numeric errors without source pixels.

Older unchanged shared-worker replays are familiar James/ChatGPT-assisted evidence:
A/63 goes from 8 to 9 progress-eligible attempts (11 selected correct levels);
B/51 goes from 0 to 8 (8 selected correct, zero selected wrong). B waits after
initial capture, an excessive gap and a missing HUD. Genuine reviewed **level-50**
positive examples are absent. Wrong RGB 51-to-50 outputs remain negative evidence.
The historical Codex-provisional 599s Tesseract-3/neural-8 disagreement abstains.
At 1061.75s, the legacy **Tesseract-only wrong 8** (provisional reference 9)
still survives when neural output is nonnumeric. Its full EXP contradicts the
selected level and is withheld; arithmetic does not invent level 9. This remains
an explicit failure, covered by a synthetic replay of the saved single-frame outputs.

## Crop shift

On #3–5, saved HP x shifts ~779.5 to 768.5 while MP ~888.5, EXP ~998.5 and LV ~573
remain stable. HP/MP scale becomes 120 instead of ~109. A narrow correction requires
MP/EXP and existing layout-family LV/MP spacing to agree within 3%, while HP spacing
deviates 5–15%. It derives the origin from those redundant anchors and records
`anchor_correction`. Competing layouts stay ambiguous; ordinary geometry is unchanged.

Saved-anchor replay changes only #3–5: padded box `[1037,1043,1145,1059]` becomes
`[1023,1049,1122,1063]`, matching neighboring good geometry. **Not pixel-verified**;
no corrected OCR result is claimed. #10, #14 and #18 are not forced through this
rule. Enable `--save-crops` for future manual trials; no new Twitch capture ran here.

## Open the same data

Restart an old server to load the changed code. This command does not start capture:

```powershell
.\.venv\Scripts\python -m exp_tracker.server --db private/product-preview/streamer_a-manual-01.sqlite3 --diagnostic-dashboard --port 8766
Start-Process 'http://127.0.0.1:8766/'
Start-Process 'http://127.0.0.1:8766/stream/streamer_a'
Start-Process 'http://127.0.0.1:8766/live/overlay/streamer_a'
Start-Process 'http://127.0.0.1:8766/dashboard/streamer_a'
```

Saved data age normally; stale rates/ETA remain hidden. The last observed value is
719,494 / 45.54%, provisional level 65, raw Tesseract 63. The dashboard links to the
character page, which links back to diagnostics.

## Reproduce and limitations

Private `private/level-validity/replay-02.json` records every attempt, original
DB/log/table hashes and anchor replay. Its ignored `audit.py` compares the frozen
pre-change progress implementation at commit `cd9f89e3853df9ba5dac335c1bcadd6685876197`
against current code without inference/writes. Original inputs retain their hashes.
Use new output names/directories:

```powershell
.\.venv\Scripts\python private/level-validity/audit.py private/level-validity/replay-new.json
.\.venv\Scripts\python -m pytest tests/test_diagnostic_evidence.py tests/test_diagnostic_progress.py tests/test_product.py tests/test_exp_consistency.py tests/test_adaptive_hud.py tests/test_diagnostics.py -q
node --test tools/shadow.test.mjs tools/product.test.mjs
node tools/product.browser.mjs http://127.0.0.1:8766 private/level-validity/product-browser-new - streamer_a
node tools/shadow.browser.mjs http://127.0.0.1:8766/dashboard/streamer_a private/level-validity/diagnostic-browser-new
.\.venv\Scripts\python -m pytest -q
```

Warm projection: ~0.67ms median / 0.75ms p95 per 30-frame batch, 100 repeats;
Python allocation peak ~111 KiB excluding imports, SQLite and images. Not model
runtime, full process RSS or measured low-end VPS performance. Chrome checks used
the actual SQLite API; screenshots are in `product-browser-01/` and
`diagnostic-browser-02/` under the private evidence directory.

Validation: **142 focused Python tests, 1,162 full-suite Python tests (113.07s),
47 Node tests**, all passing, **zero skips**. Chrome verified the real homepage,
character page and transparent 500×160 overlay, plus 31 original diagnostic rows,
polling, navigation, withheld integer chart exclusions and retained percentages.
Screenshots were inspected. Final Python runs used fresh `--basetemp` directories
under `private/level-validity/` because the default sandbox temporary directory
was inaccessible; no tests were weakened or skipped for that limitation.

Changes: new `src/exp_tracker/diagnostic_evidence.py`, `exp_consistency.py` and
`tests/test_diagnostic_evidence.py`; small integrations in `diagnostic_progress.py`,
`diagnostics.py`, `product.py`, `shadow_view.py`, product/shadow JS and shadow HTML;
narrow `tools/adaptive_hud.py` fix; arithmetic tool re-export; focused Python,
Node/browser regressions and linked docs. Store/schema, production OCR, models,
grammar rules, EXP requirements and trusted accounting remain unchanged.
