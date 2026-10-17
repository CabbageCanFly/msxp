# Grammar hypotheses and percentage endpoint diagnostics

Follow-up: [bounded live full-EXP proposals](live-grammar-recovery.md) adds a narrower
read-only dashboard mode. The historical experiment and percentage calculations
documented below retain their original rules and evidence.

No acceptance policy changes. Strict full-pair/percentage-only parsers, models,
thresholds, shadow capture/viewer, production recognition, Store, statistics,
OBS overlay and leaderboard remain unchanged. The two-stream reviewed trial is
exploratory development evidence with James/ChatGPT-assisted references, not a new
independent holdout. Main-HUD/character identity remains unverified.

## Fixed grammar experiment

`tools/grammar_recovery.py` proposes interpretations only. It never returns a
capture `candidate`, accepted level or trusted observation. Every proposal stores
the original text, interpretation, original zero-based edit positions, category,
numerical fields and `trusted: false`. Pixel-review notes are a separate sidecar.
No proposal enters the ordinary percentage timeline or percentage-pace module.

The fixed bounded transformations were selected from the requested confusion
categories before scoring, not fitted to reference answers: terminal `%1`→`%]`,
terminal `DD.DD1]`→`DD.DD%]`, a possible `1` opener immediately before a bounded
percentage token, one internal space→decimal, or an omitted decimal before the
last two digits of an explicitly bracketed three/four-digit token. At most one
pass per category and three EXP-field edits; alternatives must satisfy unchanged
strict field grammar and range. No numerical digit is inserted or repaired.
Inserting a decimal is merely a hypothesis until the source actually supports it.
An explicitly reviewed incomplete crop refuses hypotheses. Missing openers with
no potential source symbol are not inserted. Other confusable glyphs are not mapped.

| Saved example | Proposed interpretation | Edits / pixel evidence |
|---|---|---|
| A7 `[70.63%1` | `[70.63%]` | One suffix substitution; green closing stroke/caps are compatible, not independently authenticated |
| A2 `998,512170.32%1` | `998,512[70.32%]` | Two boundary substitutions; separate green strokes and full band remain visible |
| A3 `999,365170.38%1` | `999,365[70.38%]` | Two boundary substitutions; same limitations |
| A6 `170 57%1` | `[70.57%]` | Three edits: opener, decimal, close. Faint decimal/boundaries and crossing HUD line make this substantially less certain |
| A11 `0.85%1` | None | Left crop edge truncates the field; no complete leading value/opener. No neighbor-based reconstruction |
| B12 `689.,965[92.17%]` | None | No rule deletes punctuation inside the absolute EXP token. Existing partial 92.17 evidence stays partial |

The old native-glyph grammar experiment recovered **four percent signs, not closing
brackets**, after verifying other glyphs. It supplies no validation of these neural
text substitutions. Here, green colour/vertical shape alone cannot distinguish a
bracket from the constructed green-numeral control. No automatic pixel gate is justified.

| All scheduled attempts | Stream A (12) | Stream B (12) |
|---|---:|---:|
| Unchanged raw strict complete types | 6 (1 full + 5 percentage-only) | 10 full |
| Single-symbol hypotheses agreeing with reference | 1 | 0 |
| Multiple-edit/boundary hypotheses agreeing | 3 | 0 |
| Wrong hypotheses against known references | 0 | 0 |
| Unrecoverable text ambiguity | 0 | 1 |
| Clipped/incomplete source field | 1 | 0 |
| Missing region/raw text | 1 | 1 |

Thus four additional **proposals** agree with familiar references; zero additional
observations are accepted. Baseline stays **11/14 full-pair agreement**, **17/21
readable percentage-field agreement** (including existing partial evidence), and
five explicitly complete percentage-only readings. The four proposals are not an
accuracy claim for an automatic correction rule.

## Numeric level context and negative evidence

Reuse only saved unrestricted PSM7 outputs from B1/B7/B12: `S` and `1` tokens,
with S scores .62/.85/.87 and 1 scores .90/.87/.76. `S 1`→`51` is permitted only
when the separately established orange numeric-level-field context is supplied.
These **three proposals agree** with familiar level-51 references, but retain all
token scores and uncertainty. No result replaces the unavailable visual level.
Unrestricted `Sa.`/`Su`, `O1`, `I1` and generic nonnumeric-context `S1` are not rescued.
The existing EXP table still cannot adjudicate levels 51/63.

Thirteen saved 2× synthetic-control outputs were replayed, without new inference:
seven yield grammar proposals. **Two are numerically wrong against recorded source
intent**: fragmented `74,050[25.17%1` and clipped `4,059[25.17%1` become wrong
complete-looking strings after suffix replacement. Five agree numerically, but
include a damaged close, a deliberately missing decimal and actual white/green
numeral-1 replacements: numerical agreement does not make their punctuation valid.
The other six have no bounded proposal. These are controlled mutations with
recorded construction intent, not independent human labels for damaged images.
Known incomplete/missing-punctuation controls are explicitly vetoed by source
review, while their unsafe text-only hypotheses remain visible in the report.

The real +4px `2345[92.74%]` contamination is already strict and wrong relative to
the saved `345` reference; grammar cannot detect it. The original raw
`1,241199.82%]` would allow a boundary hypothesis retaining **99.82**, not the
visually transcribed 99.92. This demonstrates why repairing field structure cannot
authenticate digit identities. Prior disputed 8/9 cases remain unresolved as
documented in [the label audit](ocr-label-audit.md); no old labels were revised.

## Independent percentage computation

`tools/percentage_progress.py` reads original shadow attempts, never grammar
proposals, partial fields or arithmetic-derived levels. Internally percentages are
integer basis points: **100 bp = one percentage point**. Full pairs must match their
saved candidate; legacy whole percentage-only strings retain their strict syntax.
Any conflicting supplied candidate is refused. Explicit visual level and locally
fresh successful capture are mandatory.

Contiguous segments require the same recorded channel, matching available visual
levels, unique returned region, increasing timezone-aware receipt timestamps,
consecutive attempt indices and no failures/contradictions between them. Receipt
gaps above **1.5× configured nominal cadence** also break segments; this is a
conservative missing-sampling diagnostic, not proof of source capture timing.
There is no production 120-second OCR bridging in this experiment. Same channel
and level do **not** authenticate character identity. Local freshness cannot
authenticate broadcaster freshness or distinguish frozen imagery from inactivity.

Zero/positive/negative displayed differences are recorded separately. Decreases
break the segment and establish a new diagnostic baseline; no level-up is inferred.
Level changes, unknown levels and missing comparisons never produce progress.
No values are assigned to missing timestamps. Exact timestamp microseconds and
rational arithmetic avoid rounding intermediate rates.

Pace needs at least **three strict readings spanning 30 seconds**; parameters can
increase these minimums. Displayed difference is `d_bp/100` percentage points;
provisional pace is `36*d_bp/elapsed_seconds` percentage points/hour, always
**EXPERIMENTAL / UNVERIFIED**. No absolute EXP, EXP/hour or ETA is inferred.

For each endpoint, separately model true percentage under nearest-half-up as
`[display−0.005, display+0.005)` and truncation as `[display, display+0.01)`,
clipped to 0–100. Subtract endpoint intervals and divide by elapsed time for outer
quantization bounds. These are **not statistical confidence intervals** and do not
cover OCR errors, timing errors, changing activity or identity mistakes. Neither
display hypothesis is selected. Away from 0/100 both give a difference uncertainty
of up to 0.01 percentage point. Zero displayed change can still hide a small loss
or gain; bounds are not arbitrarily clamped to nonnegative progress.

Example synthetic test: 70.00→70.04→70.10 over 30 seconds gives 0.10 percentage
point difference, provisional 12 pp/hour and quantization bounds 10.8–13.2 pp/hour
under either hypothesis. This is synthetic arithmetic, not a measured game pace.

### Real saved runs: no qualifying pace

Stream A has four isolated segments: attempts **1**, **5**, **8–10**, **12**.
Only 8–10 has three readings: 70.69→70.73→70.79, differences +0.04 and +0.06
percentage points, endpoint net **+0.10** over **29.161433 seconds**. It misses the
30-second requirement; the others lack three readings. A7's grammar hypothesis is
not used to extend it, and A11's clipped field breaks the next comparison.
Stream B has zero eligible points: ten strict full pairs have no accepted visual
level, while the missing-region attempt and malformed B12 have no strict observation.
No pace is emitted for either stream. The reference level 51 and proposed `S`→`5`
levels do not fill that evidence gap.

## Artifacts and reproduction

Private `private/grammar-pace/` contains the fixed `plan.json`, input fingerprints,
`pixel-review.json`, two `boundary-review-*.png` sheets (native and 6× RGB), and
the final `report.json` under `final-report/`. Source/annotation comparisons, exact edits,
all 24 attempts, three saved level comparisons and 14 negative/control cases remain
separate. No new OCR inference or screenshot labels were generated.

```powershell
.\.venv\Scripts\python tools/evaluate_shadow_grammar.py --output private/grammar-pace/repeat-01
.\.venv\Scripts\python -m pytest tests/test_grammar_progress.py -q -rs
.\.venv\Scripts\python -m pytest -q -rs
```

Use a **new output directory**. Evaluation requires existing private reviewed
inputs and pixel-review sidecar; synthetic tests need none. Grammar and pace run
only in these standalone tools; the existing viewer is intentionally unchanged.

Recommendation: keep suffix/boundary hypotheses as human-review aids. Next, obtain
independently reviewed, source-matched punctuation/digit negatives and held-out
numeric level evidence before proposing a recovery gate. Level availability is
currently the direct obstacle to strict percentage pace on B; A also needs a longer
uninterrupted sequence. Neither grammar nor percentage arithmetic supplies numerical
verification for trusted ingestion. No commits, pushes, new models or dependencies.

Validation: **48 focused synthetic tests passed**; **869 full-suite tests passed,
zero skips** (77.63s). `git diff --check` passed. All **125 pre-existing fingerprinted
inputs** remained byte-identical; each replay additionally fingerprints its review
sidecar and inputs before/after. A replay took about 6.76ms wall time, excluding
sheet preparation and manual inspection; process CPU was one 15.625ms timer tick,
too coarse for a meaningful per-reading CPU estimate. No inference was run.
The only added public files are the three standalone tools, synthetic test module
and this report. No existing tracked file was modified. Browser checks are not
applicable: this milestone adds no viewer changes or pace display.
