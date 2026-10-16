# Conditional EXP / percentage consistency experiment

**Useful independent arithmetic evidence, not an authoritative OCR validator yet.**
No OCR inference, training, production changes or candidate promotion occurred.

## Requirements and unresolved UI semantics

[MapleClassic Wiki's published table, revision 71641](https://mapleclassic.wiki/index.php?title=Module:ExperienceCurve&oldid=71641)
and [NiaMeowDB's leveling table/formulas](https://meowdb.com/msclassic/formulas/leveling)
agree on the first 49 requirements. The relevant rows include level 6: 372,
level 9: 1,242, and level 40: 294,216 EXP to advance **from** that level.
These external publications, not OCR or annotation ratios, supply the private
`requirements.json`. Its literal rows were also cross-checked against the
published formula before evaluating candidates. No third-party implementation
code was copied. Requirements above the shared confirmed extent were omitted.

These are community publications: their underlying extraction independence and
the exact builds of our recordings were not authenticated. The wiki leaves
50+ unverified, while NiaMeowDB publishes more levels. No official client rule
for the two-decimal HUD percentage was found in the checked sources. The wiki's
Lua percentage-formatting helper formats its website, not the game's HUD.

Therefore two **predeclared, separate hypotheses** are reported: exact-rational
nearest-half-up rounding and truncation. Neither is selected by fitting our
labels, and there is no per-frame union, tolerance or automatic acceptance rule.
Hidden fractional EXP, client floating-point boundaries and half-way tie behavior
remain unverified. Every output explicitly has `authoritative: false` and
`trusted: false`, including arithmetic matches.

## Exact arithmetic and precision

For integer current EXP `E`, requirement `T`, and displayed percentage in integer
hundredths `B`, compare:

- Truncation: `B = (10000 * E) // T`.
- Nearest-half-up: `B = (20000 * E + T) // (2 * T)`.

No binary floating-point division is used. Decimal input is parsed exactly;
missing digits/decimals are not supplied. Feasible integer EXP bins are computed
with ceiling division and intersected with `0 <= E < T`. A bin count of zero means
no integer EXP fits that display under the hypothesis; a count above one exposes
unresolvable numerical precision. The bin is diagnostic, never a repaired reading.

Each 0.01% spans roughly `T / 10000` EXP. At level 40, nearest-rounded **25.17%**
allows **74,040 through 74,068: 29 different integers**. Both 74,050 and 74,059 fit.
Truncation instead allows 74,055 through 74,083; choosing that rule merely because
it catches the nine-EXP error would be unjustified. Larger requirements produce
wider bins. Small supported levels can have a unique compatible integer, but
uniqueness assumes the level, table and display rule are correct.

## Saved-candidate results

Reused unchanged RapidOCR direct-line **2x inputs**, cached level predictions and
the existing strict bracketed parser. Two-pixel padding refers only to the saved
Stream 2/3 context experiment; the original recording uses its saved manual ROI.
Malformed punctuation is not repaired. No annotation level is substituted for a
missing OCR level. Level caches use the existing `readings` format.

Cells are **arithmetic consistent / inconsistent / unavailable level**, among
previously complete numeric candidates. All 45/117 source frames remain in result
files; incomplete EXP pairs are separately `unavailable_pair`, outside these sums.

| Input | Complete candidates | Nearest, Tesseract level | Truncation, Tesseract level |
|---|---:|---:|---:|
| Stream 2, automatic 0 px | 31 / 45 | 22 / 0 / 9 | 13 / 9 / 9 |
| Stream 2, automatic 2 px | 35 / 45 | **25 / 0 / 10** | 16 / 9 / 10 |
| Stream 3, automatic 0 px | 28 / 45 | 28 / 0 / 0 | 17 / 11 / 0 |
| Stream 3, automatic 2 px | 39 / 45 | **39 / 0 / 0** | 21 / 18 / 0 |
| Original, manual ROI | 95 / 117 | **60 / 1 / 34** | 34 / 27 / 34 |

Manual-ROI controls: Stream 2 has 45 complete candidates, with nearest 32/0/13
and truncation 21/11/13; Stream 3 has 19, with 19/0/0 and 13/6/0.
Pixel-level predictions are unavailable for both new layouts, so cannot assess
any of their complete candidates. On the original, pixel levels give nearest
56/0/39 and truncation 32/24/39 among the 95 complete pairs.

All nearest-consistent low-level cases have unique integer bins. All 39 Stream 3
2-px matches are precision-ambiguous: 24 bins contain 29 EXP values and 15 contain
30. Provisional annotation agreement is not independently verified accuracy, and
the greater nearest agreement is not independent confirmation of the UI rule.
Descriptively, 16 Stream 2 and 21 Stream 3 padded candidates agree with **both**
hypotheses; nine and eighteen depend on rounding. This is not an acceptance policy.

## Important failures and transitions

- **345 versus 2345 / 92.74%, level 6:** 345 fits both hypotheses; 2345 exceeds
  the 372 requirement. The actual saved 4-px `2345[92.74%]` candidate is flagged
  under both rules. No replacement digit is inferred.
- **74,050 versus 74,059 / 25.17%, level 40:** both pass nearest rounding. The
  saved damaged-digit negative `74,050[25.17%]` therefore survives this check.
- **99.92 versus 99.82%, level 9 / 1,241 EXP:** nearest yields 99.92; truncation
  yields 99.91. The explicit 99.82 probe is inconsistent with both. The actual
  saved raw `1,241199.82%]` already has unavailable punctuation and Tesseract level OCR;
  it is not repaired or counted as an additional rejected complete candidate.
- **1061.75 s, level 9 misread as 8:** saved `1[0.08%]` fails both rules with
  level 8; this is the single original nearest inconsistency. The checker flags
  disagreement, not which field is wrong. At **599 s**, the 8-to-3 level error
  has no complete EXP pair. Hypothetical explicit `0[0.00%]` passes at both
  levels 3 and 8, so even improved EXP OCR would not disambiguate that level.

The 83 original boundary/subsecond samples around all nine labeled transitions
have nearest/Tesseract outcomes: **39 consistent, 1 inconsistent, 23 unavailable
level, 20 unavailable pair**. Individual windows/endpoints are in the private
`nine-transition-windows.json`; labels group results only after checking.
This establishes no automatic level-up evidence or cross-level EXP total.
Mixed-update frames can disagree temporarily; no session/state action is taken.

Wrong-level zeros, self-consistent wrong numerical pairs and the wrong character's
HUD can all pass. Percentage evidence cannot verify character identity, glyph
shape, punctuation, or last digits inside a quantization bin. Pixel verification
and repeated/temporal evidence remain necessary.

## Reproduce and scope

```powershell
.\.venv\Scripts\python tools/check_exp_consistency.py private/rapidocr-context/stream3-pad2.json --levels private/exp-consistency/stream3-automatic-levels.json --requirements private/exp-consistency/requirements.json --rounding nearest_half_up --output private/exp-consistency/repeat-stream3-nearest.json
# Repeat with --rounding truncate and a different output filename; pixel levels
# can be evaluated separately with --level-engine pixel. Existing outputs refuse overwrite.
.\.venv\Scripts\python -m pytest tests/test_exp_consistency.py -q --basetemp private/exp-consistency/pytest-targeted
.\.venv\Scripts\python -m pytest -q -rs --basetemp private/exp-consistency/pytest-full
git diff --check
```

Private `summary.json`, `hypothesis-overlap.json`, `actual-failure-cases.json` and
`counterexamples.json` retain separate rule/level-source outcomes. `run.py` records
the fixed table and jobs; it refuses an existing table to preserve the initial
experiment. Use new output names with the standalone evaluator for reruns.
No neural inference or model downloads are needed for this arithmetic diagnostic.

**22 focused tests pass; full suite 583 passed, zero skips** (82.39 s with local
loopback access). All 131 snapshotted prior JSON/JSONL/CSV artifacts and ONNX
weights are byte-identical, including frozen labels, banks and raw OCR results.
Public changes: the standalone tool, synthetic tests, this report and a link from
the RapidOCR report. New data remain ignored. No commits or pushes.

Next: independently verify the recording-build table and HUD formatting behavior
before considering a conditional veto. Do not use this arithmetic check to repair
OCR, infer missing levels, select characters or promote observations. It offers
strong coarse-error evidence at low levels but cannot replace numerical pixel
verification at higher levels.
