# Conditional level inference from EXP and percentage

**Promising as cheap provisional level evidence; insufficient as the only level
source or as numerical verification.** On the frozen 24-frame review set, unique
nearest-rounded inference recovers all five missing OCR levels wherever a strict
neural EXP pair exists: complete diagnostic triples increase **18→23/24**. H07
stays malformed. Zeros, unsupported levels, stale/mixed fields and self-consistent
wrong numbers prevent unconditional replacement of independent level evidence.

## Pure diagnostic and fixed policies

`tools/infer_exp_level.py:infer_levels` enumerates **every supplied table level**
using unchanged `check_exp_consistency.assess`. It receives no OCR level. It returns
the full compatible set, `unique_level` only for a singleton, and status `unique`,
`ambiguous`, `incompatible`, `unavailable` or `invalid_input`. Every result has
`trusted:false`, `authoritative:false` and table-only exhaustiveness. No table is
embedded in public code, inferred from OCR, extrapolated or modified.

The existing externally sourced private table covers **levels 1–49**. Its
[community provenance and recording-build limitations](exp-consistency.md) remain
unchanged; neither underlying source independence nor client percentage semantics
has been authenticated. A singleton is unique only within this supplied table.

For EXP `E` and requirement `T`, the primary hypothesis computes integer displayed
hundredths as `(20000*E + T)//(2*T)`; alternative truncation separately computes
`10000*E//T`. Both require `0 <= E < T`. The primary hypothesis was fixed before
evaluation; there is no rule switching, union or tolerance chosen from answers.
String percentages require exactly two decimal places; typed numerical inputs
must represent exact hundredths without rounding. Missing/invalid inputs are not
repaired. Percentage range 0–100 follows the prior diagnostic: rounded 100.00
can be mathematically compatible just below a requirement, but is not promoted
through production recognition guards.

Strategies were declared before scoring:

| Strategy | Diagnostic behavior |
|---|---|
| A | Existing Tesseract level when available |
| B | Arithmetic singleton only; ambiguity abstains |
| C | Tesseract when present, otherwise arithmetic singleton. **Does not veto contradictions.** |
| D | Both sources present, arithmetic singleton, exact agreement required; all other cases abstain |

D never narrows an ambiguous arithmetic set using the OCR level. C does not choose
the arithmetic answer merely because it matches a reference. All policy results
are hypothetical; no tracking or trusted-ingestion path is called.

## Frozen human versus saved neural inputs

Sources are the unchanged `private/blinded-ocr-evaluation/user-review.json`, raw
RapidOCR 2×/+2px results and saved automatic Tesseract levels. Human provenance is
explicit user transcription plus ChatGPT visual review, not independently timed
or expert-adjudicated review. These are familiar recordings, not unseen streams.

| Inputs, all 24 frames | Unique correct | Unique incorrect | Ambiguous | Incompatible | Unavailable pair |
|---|---:|---:|---:|---:|---:|
| Human EXP/percentage, nearest | **24** | 0 | 0 | 0 | 0 |
| Strict neural pairs, nearest | **23** | 0 | 0 | 0 | **1** |
| Human pairs, truncation | 10 | 0 | 0 | **14** | 0 |
| Strict neural pairs, truncation | 9 | 0 | 0 | **14** | **1** |

Nearest agrees with Tesseract in **19 human-input cases** and **18 neural-input
cases**, with zero singleton contradictions. Five cases lack Tesseract, and the
neural case H07 additionally lacks a complete pair. H07's raw
`117,571[39.96%1` is not repaired or inferred from its correct partial tokens.

Cells below are **correct / incorrect / unavailable**. A level can be available
without a complete EXP pair; diagnostic triple counts require both.

| Nearest strategy | Human-input levels = triples | Neural-input levels | Neural-input triples |
|---|---|---|---|
| A | 19 / 0 / 5 | 19 / 0 / 5 | **18 / 0 / 6** |
| B | 24 / 0 / 0 | 23 / 0 / 1 | **23 / 0 / 1** |
| C | 24 / 0 / 0 | 24 / 0 / 0 | **23 / 0 / 1** |
| D | 19 / 0 / 5 | 18 / 0 / 6 | **18 / 0 / 6** |

B/C add five correct diagnostic triples at **H03, H10, H15, H21 and H24**.
For strict neural pairs, B/C yield **6/6 original, 6/6 Stream 2, 6/6 Stream 3
windowed and 5/6 large-HUD triples**, versus A's 4/6, 3/6, 6/6 and 5/6. C's H07
level comes from Tesseract; it does not create a 24th complete neural triple.
Truncation policy results are retained separately in the private results; its
poorer agreement is not independent proof of the nearest client rule.

## Saved failures, ambiguity and numerical safety

No new neural inference, character templates or thresholds were evaluated.
Known saved outputs and explicit mathematical controls remain distinct:

| Input/evidence | Nearest-compatible table levels | Implication |
|---|---|---|
| Actual 599s raw `010.00%]`, true level 8, OCR 3 | Unavailable pair | B/D abstain; A/C retain the wrong level. No missing opener repair. |
| Actual 1061.75s `1[0.08%]`, true level 9, OCR 8 | **{9}** | B recovers 9; C retains 8; D rejects the contradiction. |
| `0[0.00%]`, including actual transition frames | **All 49 levels** | No arithmetic level identity, even if an OCR level lies in the set. |
| Explicit near-zero `1[0.00%]` | **Levels 20–49** | Two-decimal precision also causes ambiguity for nonzero EXP. |
| Actual +4px contamination `2345[92.74%]`, source level 6 / 345 EXP | **None** | Gross error rejected by B/D, but no digit is repaired; C still retains OCR 6. |
| Controlled damaged `74,050[25.17%]` versus source `74,059[25.17%]` | **{40} for both** | Correct unique level does not distinguish the wrong last digit. D agrees with image level 40 and still admits a numerically wrong triple. |
| Explicit `1241[99.82%]` probe | **None** | Inconsistent under both rules. Actual saved `1,241199.82%]` stays malformed/unavailable, not repaired into this probe. |
| Genuine screenshot tuple level 60 / 71,441 / 5.90 | **None within 1–49** | No match can mean unsupported level, not an invalid reading. OCR 60 is not disproved by a table that omits it. |

Five existing saved failure cases (the two wrong-level frames, contaminated EXP,
damaged-digit control, and malformed original percentage output) give these
nearest policy outcomes. This selected negative set mixes real and controlled
cases; it is not an error-rate sample:

| Strategy | Level correct / wrong / unavailable | Full triple correct / wrong / unavailable |
|---|---|---|
| A | 2 / 2 / 1 | 0 / **3** / 2 |
| B | 2 / 0 / 3 | 1 / **1** / 3 |
| C | 2 / 2 / 1 | 0 / **3** / 2 |
| D | 1 / 0 / 4 | 0 / **1** / 4 |

**A wrong pair can also yield a wrong unique level.** A fixed synthetic source
at level 2 with `17[50.00%]`, corrupted to `280[50.00%]`, uniquely suggests
**level 7**. With missing OCR, B/C return the wrong 7. Correct OCR 2 lets D abstain;
wrong OCR 7 lets **D also return the wrong 7**. These are constructed mathematical
counterexamples, not newly observed model predictions. Three OCR variants of this
one corrupted pair are correlated controls, not three independent failure events.

Across all eleven explicit positive/negative/unsupported/mixed synthetic probes,
A/B/C/D level outcomes are respectively **6/3/2, 3/4/4, 6/4/1 and 2/1/8**
(correct/wrong/unavailable). Full-triple outcomes are **3/6/2, 3/4/4, 3/7/1 and
2/1/8**. Their purpose is to expose logic limits, not compare deployment accuracy.

C provides no independent visual confirmation exactly when it uses arithmetic
fallback. D can veto contradictory levels, but not small EXP errors within a
percentage bin, matching wrong fields, or a coherent secondary character's HUD.
Neither policy verifies the same neural numbers from which the arithmetic level
was calculated. No arithmetic result establishes streamer/character identity.

## Transitions and mixed evidence

Reused only **83 existing boundary/subsecond samples** across all nine original
level changes, selecting the already saved 2× line-recognition variant. These
references are prior Codex-only provisional labels, separate from the human 24.

Nearest inference produces **60 correct singletons, zero wrong singletons, three
ambiguous zeros and 20 unavailable pairs**. Truncation gives 33 correct singletons,
27 incompatible pairs, the same three ambiguities and 20 unavailable pairs.
The actual zeros at **142.5, 142.75 and 144s** match all table levels.

| Nearest strategy, 83 boundary samples | Level correct / wrong / unavailable | Triple correct / wrong / unavailable |
|---|---|---|
| A | 47 / **2** / 34 | 39 / **1** / 43 |
| B | 60 / 0 / 23 | 60 / 0 / 23 |
| C | 70 / **2** / 11 | 62 / **1** / 20 |
| D | 36 / 0 / 47 | 36 / 0 / 47 |

The nine labeled before/after endpoints are retained individually in `results.json`.
Of nine first after-level endpoints, three yield unique new levels, one has
ambiguous zero, and five are malformed. Only the 6→7 endpoint pair has unique
levels on both sides. This sparse evidence does not establish continuous transition
confirmation or any cross-level EXP amount.

No saved frame is independently authenticated here as a client mixed-update
artifact rather than OCR error. Two **explicit synthetic desynchronization controls**
use the existing 1→2 endpoint values: new OCR level 2 with old `9[60.00%]`
arithmetically suggests 1; old OCR level 1 with new `4[11.76%]` suggests 2. D
abstains on each conflict, while C keeps the OCR value. No new transition frame
was invented or labeled as observed evidence, and no boundary gains were computed.

## Measured cost and recommendation

On this Windows workstation, 2,400 warmed arithmetic calls over the 24 human pairs
and 49 requirements take **.216s wall / .203s process CPU**. Per-call wall mean /
median / p95 is **.0898 / .0881 / .0962ms**, process CPU **.0846ms per call**.
Process RSS is about **30 MiB before and after**, not an incremental allocation
or minimum-memory claim. No heavy OCR framework is needed by this function.

A separate **timing-only replay** of the unchanged Tesseract helper on the same
24 saved automatic level crops takes **10.469s wall**, **9.453s sampled process-tree
CPU**, **62.59 MiB peak sampled tree RSS**. Per-call mean / median / p95 is
**431.55 / 507.73 / 529.43ms**; sampled CPU is **393.88ms per call**. All 24 replayed
levels/abstentions match saved outputs; replay results never replace frozen scoring.
Tesseract startup and its existing multiple preprocessing attempts are included.
CPU sampling can miss short subprocess tails; the approximate multi-thousandfold
cost difference is not a controlled Linux VPS throughput guarantee. No localization
or new video capture is included in either timing stage.

**Retain a dedicated visual level source, but investigate arithmetic as fast
provisional/fallback evidence rather than running expensive OCR on every future
capture.** Visual level confirmation is still necessary for zeros/near-zeros,
levels outside the verified table, contradictions and independence from EXP errors.
The present data do not justify making an arithmetic singleton authoritative.
The next prerequisite is validating table/build coverage and client display
semantics on independently reviewed material, including zero/transition cases.
Production level sourcing and explicit session/character assignment remain unchanged.

## Reproduce and preserve

```powershell
.\.venv\Scripts\python tools/infer_exp_level.py --requirements private/exp-consistency/requirements.json --exp 74059 --percentage 25.17
# Replay saved-input diagnostic only, writing to a NEW directory; no OCR:
.\.venv\Scripts\python private/exp-derived-level/evaluate.py private/exp-derived-level/repeat
# Optional timing replay only: invokes the unchanged level OCR on existing crops.
.\.venv\Scripts\python private/exp-derived-level/benchmark.py private/exp-derived-level/repeat-cost
.\.venv\Scripts\python -m pytest tests/test_exp_derived_level.py tests/test_exp_consistency.py -q -rs --basetemp private/exp-derived-level/pytest-targeted-repeat
.\.venv\Scripts\python -m pytest -q -rs --basetemp private/exp-derived-level/pytest-full-repeat
```

Private `results.json` and `per-frame.csv` retain both rounding sets, all four
strategies, ambiguity, correctness/availability and input provenance for every
case. `cost.json` holds timing-only replay details; `plan.json` declares policies;
`input-hashes.json` records **1,159 preserved prior inputs**, including frozen user
answers, prior raw model results, requirements and model weights. No annotations,
profiles, thresholds, model files or prior outputs were changed. Public additions
are this report, the standalone diagnostic and synthetic tests. No production,
tracking, accounting, SQLite, overlay, identity or level-up changes; no commits/pushes.

Validation: **57 focused tests passed; full suite 682 passed, zero skipped**
(80.97s, including localhost HTTP tests). Thirty-five new synthetic tests cover
ambiguity, missing/invalid inputs, exact halfway rounding, separate truncation,
unsupported table coverage, contradiction policies and self-consistent wrong pairs.
`git diff --check` and prior-input hash checks pass. No neural OCR was rerun;
the optional saved pixel-level baseline was not expanded or recalibrated.
