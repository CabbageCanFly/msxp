# Percentage-only diagnostics and level-51 investigation

This milestone changes only experimental shadow diagnostics and their localhost
viewer. No neural value becomes trusted, no EXP is reconstructed, and no production
recognition, confidence threshold, Store, accounting, OBS overlay or leaderboard
behavior changes. The frozen two-stream review is now exploratory development
evidence, not another blind holdout.

## Complete and partial evidence

`exp_tracker.shadow_types.parse_percentage_only` recognizes a **whole field** with
ASCII digits, a decimal point, exactly two decimal places, `%` and both square
brackets. Only surrounding whitespace is ignored. Range is 0.00–100.00 inclusive;
100.00 is diagnostic syntax, not proof of a valid gameplay state.

| Raw text | Diagnostic outcome |
|---|---|
| `[70.51%]` | Percentage-only candidate; absolute EXP unavailable |
| `[0.00%]` | Percentage-only zero, never absolute zero EXP |
| `1,234[70.51%]` | Existing full-pair parser only |
| `0.85%1`, `[70.63%1`, `170 57%1` | Unavailable; no punctuation/digit repair |
| `[7 0.51%]`, `[70.5%]`, `[100.01%]`, `[70.51%]1` | Unavailable |
| `689.,965[92.17%]` | No complete observation; existing parser's partial percentage evidence retained separately |

New shadow attempts have additive fields:

```json
{
  "trusted": false,
  "status": "diagnostic_percentage_only",
  "diagnostic_type": "percentage_only",
  "candidate": null,
  "percentage_only_candidate": {
    "kind": "percentage_only",
    "percentage": "70.51",
    "percentage_bp": 7051,
    "trusted": false
  },
  "partial_percentage_evidence": null
}
```

`candidate` retains its existing strict full-pair meaning. Percentage-only fields
never feed arithmetic level inference. Partial evidence is sourced **only from the
already supported parser diagnostic**, is marked `complete_observation: false`,
and cannot become either complete candidate type. Failed attempts retain null
fields. Stale completed candidates remain diagnostic with `current: false`.

The viewer can project this new strict type from complete raw strings in old logs,
marked `percentage_only_origin: legacy_raw_parse`, without rewriting those files.
Existing saved statuses and all full-pair/arithmetic evidence remain unchanged.
A supplied percentage-only object that contradicts raw syntax is rejected.

## Saved two-stream replay

References: James's transcriptions with ChatGPT assistance; not independently
blinded expert adjudication. All 24 scheduled attempts remain in the denominator.
The original `private/reliability/review-01/evaluation.json` is unchanged.

| Evidence | Stream A (12) | Stream B (12) |
|---|---:|---:|
| Captured / unique located HUD | 12 / 11 | 12 / 11 |
| Unchanged full-pair agreements / readable pair references | 1 / 3 | 10 / 11 |
| Added explicit percentage-only agreements | 5 | 0 |
| New percentage-only mismatches | 0 | 0 |
| Complete typed diagnostics: full + percentage-only | 6 | 10 |
| No complete typed diagnostic | 6 | 2 |

The five typed percentages are A attempts **5, 8, 9, 10, 12**:
70.51, 70.69, 70.73, 70.79 and 70.92. They were already counted by the frozen
evaluator as partial percentage fields. Thus **numerical percentage agreement is
still 17/21 readable references**, and full-pair agreement is still **11/14**.
This is a semantic/display improvement, not five newly recovered numbers.
B attempt 12 retains 92.17 as partial evidence only. No absolute EXP is inferred
for the compact percentage-only HUD. Its apparent change near one million EXP
could be a responsive display behavior; cause and exact switching rule are unverified.

Private replay output: `private/percentage-level51/percentage-results.json`.
It checks unchanged raw strings/full-pair presence and the new type for all 24.

## Level 51: evidence and bounded comparisons

All **11** saved B level crops have six raw Tesseract passes (66 total):
15 return `51`, 31 return `1`, 18 blank, and 2 return `4`.
Every pass is below the existing 0.40 confidence requirement; the best `51` is
0.37. Merely seeing `51` in a raw pass does not satisfy consensus or establish trust.
The existing requirement table covers only levels 1–49: it cannot adjudicate 51
or 63, and an empty arithmetic candidate set here is not proof of bad OCR.

Fixed diagnostic subset: B attempts **1, 7, 12**, plus A attempt 1 as a control.
Unchanged recognition reproduces their saved passes and still abstains on all B
crops. Each B crop is 52×33 pixels with an orange bounding box `(3,6,35,24)`;
both tiles are present with margins. Existing tile segmentation finds two tiles,
approximately 17×19 and 16×19–20. No obvious source crop truncation explains these
three failures; subpixel/raster/threshold effects remain relevant.

Using the *same* existing neutral-180 mask, unrestricted PSM 7 reads **S + 1** on
all three, with S confidence 0.62/0.85/0.87. Restricting to digits returns `51`
at 0.29/0.03, then `1` at 0.00. Unrestricted PSM 8 returns `Sa.`/`Su`/`Su`;
it is not a fix. No `S`→`5` substitution is performed.

The native five survives visually, but thresholding discards weak strokes:
its white-pixel counts at existing 160/180/200 thresholds are 42/34/18,
39/30/14 and 39/32/18. The min-RGB preprocessing yields a thin S-like glyph;
the existing luma fallback yields thicker shapes yet still fails reliable decoding.
This supports a font/raster/preprocessing mismatch, not a justified confidence
threshold reduction. Tesseract's internal confidence mechanism was not reverse
engineered; these observations explain the observed ambiguity, not an exact score formula.

The A control likewise shows S/b-like unrestricted outputs, while two unchanged
luma passes correctly agree on 63 at 0.96. Existing native pixel-consensus profile
also abstains on all three B crops (`unverified_digit`); it was neither altered nor
retrained. All B levels remain untrusted.

Private evidence: `private/percentage-level51/level-diagnostic/comparison.png`,
`results.json`, `native-profile-results.json`. Native and preprocessed crops are
shown separately. These familiar reviewed examples cannot validate a replacement
recognizer. Next level work needs independently reviewed per-digit examples across
native geometries, including confusable 5s/negatives, followed by held-out streams.

## Timeline and future pace limits

`/dev/shadow` has a separate 0–100% point chart for complete full-pair and
percentage-only observations. Exact observed decimals and visual levels are in
tooltips/table; rejected attempts, stale samples and sampling gaps remain visible.
Known adjacent visual-level changes have boundary marks; unknown levels establish
no continuity. There are **no connecting lines**, propagated values or gains.
Malformed partial percentages are shown in the table only.

Two-decimal percentage quantization is 0.01 percentage point. Under a single
consistent rounding or truncation rule, an endpoint difference can carry roughly
one such unit of quantization uncertainty; at short intervals that can dominate
pace. Client semantics are still unverified. Any later pace calculation needs
validated numeric readings, explicit same character/session/level, reliable elapsed
time and gap coverage, a declared display rule and enough progression to exceed
quantization noise. No pace, percentage/hour, ETA or EXP-table reconstruction is
implemented here.

## Reproduce

```powershell
.\.venv\Scripts\python private/percentage-level51/replay.py
.\.venv\Scripts\python -m pytest tests/test_shadow_percentage.py tests/test_shadow_capture.py tests/test_shadow_view.py tests/test_server.py -q -rs
node --test tools/shadow.test.mjs
.\.venv\Scripts\python -m exp_tracker.server --db artifacts/statistics-preview.sqlite3 --shadow-log private/reliability/captures/stream-a.jsonl --port 8878
# Separate terminal, while server runs:
node tools/shadow.browser.mjs http://127.0.0.1:8878/dev/shadow artifacts/percentage-level51-browser-repeat
.\.venv\Scripts\python -m pytest -q -rs
```

The replay script, diagnostic scripts, captures and screenshots are ignored private
workspace material, not public checkout requirements. The isolated level comparison
script refuses to overwrite its existing output; use a new private output directory
before repeating it. No new live trial or recognition tuning was performed.

Validation: **144 focused Python tests**, **821 full-suite tests** (81.58s), all
passed with zero skips; **9 renderer tests** and **6 Chrome screenshot cases**
passed. Desktop/mobile Stream A views contain one EXP point and six complete
percentage points, without page overflow or off-origin requests. Screenshots and
measurements are under `artifacts/percentage-level51-browser/`; the desktop view
was visually inspected. The two sampled API requests took 5.4/4.1ms and V8 reported
about 1.05 MiB used JS heap (not total browser memory or a VPS measurement).
All **107 fingerprinted frozen evidence files** remain byte-identical, as does
the tested native-level profile. No public deployment, commits or pushes.

## Follow-up (2026-10-23): dim level strokes held a whole stream

A stream with a percentage-only EXP field (`EXP. [78.63%]`), level 71, a second smaller
gameplay feed in the corner and monster `Lv.` tags never showed a level or reading.

**Measured** on 21 private screenshots and a local-video replay of them through
`multi_alpha` with automatic characters (the admin default):

- Localization found exactly one HUD, the main status bar, on all 21. The second feed's HUD is
  too small to read and monster `Lv.` tags fall outside the LV anchor window, so neither was bound.
- RapidOCR read 71 (score ≥0.99) and the name OCR read the character on every frame.
- Tesseract read 0/21: after min-RGB the 7's thin top bar is only 119–162, so every
  160/180/200 pass erased it and read `1` without confidence. Same mechanism as the level-51 crops above.
- With no absolute EXP, arithmetic is always indeterminate, so the level guard can only qualify a
  level when Tesseract and RapidOCR agree. Every attempt was held `level_unvalidated` and the
  player card stayed empty. Without the guard (manually assigned character), the evidence layer
  already accepted 71 after three RapidOCR frames.

**Change:** `level_reading` adds min-RGB passes at 140 and 120 only when its six existing passes
have not reached consensus, so readings that already agree are unchanged by construction. They run as a
word read (PSM 8) first, then as a line read (PSM 7) if there is still no consensus. Two agreeing
confident passes are still required and any confident disagreement still vetoes. The guard is
unchanged: Tesseract and RapidOCR must agree on two independent frames. Threshold 100 was rejected:
it produced a confident wrong `7`.

The first version used line reads only. It fixed 71 (19/21) but a later feed swap to another
character at level 72 failed 7/7: there the 7 survives every threshold, yet line reads still
returned only `2`. Word reads of the same images give `72` at 0.80–0.95 on all seven.

| Labeled level crops (correct / wrong / unavailable) | Before | Line reads only | Word, then line |
|---|---|---|---|
| Recording 1 (117) | 68 / 2 / 47 | 86 / 2 / 29 | 87 / 2 / 28 |
| Recording 2, manual / automatic crops (45 / 36) | 32/0/13 · 25/0/11 | 35/0/10 · 28/0/8 | 35/0/10 · 28/0/8 |
| Recording 3, manual / automatic crops (45 / 41) | 45/0/0 · 41/0/0 | unchanged | unchanged |
| Two-feed screenshots, level 71 (21) | 0 / 0 / 21 | 19 / 0 / 2 | 21 / 0 / 0 |
| Two-feed screenshots after the swap, level 72 (7) | 0 / 0 / 7 | 0 / 0 / 7 | 7 / 0 / 0 |

All 46 changed crops went from unavailable to correct; the two wrong readings are the same
pre-existing ones. On the replay, the floor reached 71 on the fourth attempt and every later reading
was public. Each extra pass costs about 0.13 s (Tesseract CLI on Windows); up to four run, and only
when a level read would otherwise abstain.

**Untested:** live Twitch capture on the VPS, resident-Tesseract timing there, other HUD fonts or
scales, and the level-51 crops above (not available locally).
