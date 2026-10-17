# Bounded full-EXP grammar proposals

This is **display/review evidence**, not recovered tracking observations. It adds
no model inference, numerical verification or acceptance policy. Original strict
full-pair/percentage-only parsers, capture JSONL, SQLite payloads, trusted Store,
pace, accounting and level-up behavior are unchanged.

## Fixed policy

`exp_tracker.shadow_grammar.propose_full_exp`, also exposed by the existing
`tools/grammar_recovery.py`, is a narrower mode than the historical `propose()`.
The historical decimal/percentage-only/level hypotheses remain unchanged and are
not enabled in the dashboard.

1. Preserve already-strict results. No proposal is emitted for a strict full pair
   or complete percentage-only observation.
2. Require a whole field with an actual `%` and exactly two digits after an actual
   percentage decimal point. No whitespace-to-decimal, decimal insertion or comma
   substitution inside the percentage is allowed.
3. Replace final `%1` with `%]` only in such a complete full-EXP interpretation.
4. A potential opener `1` needs a valid grouped EXP prefix and a uniquely bounded
   one/two-integer-digit percentage. Ungrouped concatenated digits abstain. An
   existing `[` also permits the existing ungrouped integer syntax.
5. Normalize EXP dots to commas only if all integer groups already have unambiguous
   three-digit grouping. No punctuation deletion, leading-group reconstruction,
   numerical digit insertion/substitution, neighboring observation or level input.
6. Check the completed interpretation with existing `parse_exp` and the unchanged
   strict-pair range/zero constraints. Tests compare strict results against the
   existing experimental `complete_pair`; neither parser was changed.

Limits: **160 input characters, at most 160 possible boundary positions, three
substitutions, two retained alternatives**. Two alternatives mean ambiguity and no
selected interpretation. There is no per-frame rule selection using expected answers.
`|`, `I`, `l`, unknown suffixes and missing numerical fields are not repaired.

Each result keeps policy ID, original text, interpretation, numeric fields,
zero-based original edit positions/types and explicit unverified flags. Known
incomplete source review vetoes new proposals; it never rewrites a strict baseline.
Source completeness is otherwise **unknown**, not established by text grammar.

## Saved 30-attempt Telfer1 run

Input: `private/local-alpha/runs/telfer1-20261017T073930Z-986495bd/`.
James acquired 30 frames at seven-second cadence, with 30 unique HUD regions and
30 persisted attempts. No new capture or OCR inference was run here.

| Classification | Count / 30 | Attempts |
| --- | ---: | --- |
| Original strict full pairs | 7 | 1, 6, 9, 15, 22, 25, 29 |
| Unique unverified grammar proposals | 19 | 2–5, 7–8, 10–14, 16–20, 26, 28, 30 |
| Ambiguous grammar proposals | 0 | — |
| Visibly clipped, no proposal | 2 | 21, 24 |
| Other rejected (`|` lookalikes) | 2 | 23, 27 |

Text-only classification rejects four; the separate source review identifies two
as clipped. **Strict availability stays 7/30, not 26/30.** There are 19 additional
viewable hypotheses, not 19 accepted/corroborated observations. Four proposals use
one edit, twelve use two and three use three.

Prediction-free native-RGB/nearest-neighbor sheets were visually transcribed by
Codex after raw OCR exposure, before evaluating the new policy. All seven strict
pairs and nineteen proposals agree with those provisional transcriptions. This is
**not blinded or independently human-verified accuracy**. James supplied the
clipping findings; no full EXP is assigned to attempts 21/24. Native crops alone
cannot establish the intended main-character identity.

Attempt 23 has recognizable bracket-like stems but raw `|` boundaries; it remains
rejected. Attempt 27 also has a `|` opener and an unresolved numeric issue: its last
percentage glyph appears **6-like** in RGB, while OCR says `33.18%`. The sidecar
leaves percentage unknown rather than forcing 33.16/33.18 agreement. Neither field
is recovered. Any future `|` rule needs separate numerical/pixel review, not global
lookalike replacement.

## Safety controls

Replayed the old thirteen saved synthetic mutations and real +4px contamination:
**six proposals, seven rejected, one already-strict value**. Two proposals retain
known wrong source-intent numbers: fragmented `74,050[25.17%1` and clipped
`4,059[25.17%1`. Other proposals include deliberately damaged punctuation/actual
numeral-1 replacements: matching numbers do not prove valid brackets.

The already-strict `2345[92.74%]` contamination remains wrong against its `345`
source. The historical `1,241199.82%]` hypothesis preserves **99.82**, not the
visually reviewed 99.92. Grammar cannot identify either numerical error, authenticate
complete pixels or distinguish a real `1` from a bracket prediction. Manual
`source_complete=false` vetoes proposals; there is no automatic clipping detector.

## Read-only dashboard integration

SQLite snapshots derive additive `grammar_recovery` evidence from the original
sanitized raw OCR on each request. **No migration or row update** is needed. Saved
proposal fields supplied in a log are ignored; current policy is recomputed from
raw text. Original JSONL, event IDs, timestamps, candidates and trusted state remain
authoritative for their existing meanings.

Rows show original → interpretation with
**GRAMMAR-RECOVERED / EXPERIMENTAL / UNVERIFIED**, edits and a source-verification
warning. The last attempt's proposal is shown separately from the latest strict
candidate. Rejected/ambiguous fields have no selected value. Pipe characters may
be displayed safely as raw diagnostic text; they are never substituted.

Neither EXP nor percentage timeline plots proposals. `latest_reading`, freshness,
launcher success counts, original arithmetic hypotheses, percentage pace, trusted
Store and all totals still use their existing strict inputs. This is not a remedy
for missing visual-level verification or observation continuity.

To view existing persisted evidence, restart the local server; no recapture:

```powershell
.\.venv\Scripts\python -m exp_tracker.server --db private/local-alpha/live/telfer1.sqlite3 --diagnostic-dashboard --port 8766
# Another terminal:
Start-Process 'http://127.0.0.1:8766/dashboard/telfer1'
```

## Level/table limitations

The run's frozen requirements hash matches the current **49 entries, levels 1–49**.
The reported/visible level 64 is unsupported. All seven strict pairs have empty
nearest-half-up and truncation sets; this is not a numerical rejection at level 64.
No rule is selected, table extrapolated or EXP requirement derived from OCR.
An extension requires independently sourced build-appropriate requirements and
separate client-display semantics verification.

Tesseract yields 23 level-64 candidates and seven unavailable levels. Neural output
is 64 on 26 frames, **54 at 16/23/27** and **84 at 28**, despite crops consistent with
the reported 64. These genuine failure outputs remain unchanged and untrusted;
grammar does not repair levels. Private `level-failures.png` preserves comparison.

## Reproduction, cost and evidence

```powershell
.\.venv\Scripts\python tools/evaluate_live_grammar.py --log private/local-alpha/runs/telfer1-20261017T073930Z-986495bd/capture.jsonl --reviews private/live-grammar-review-01/visual-review.json --output private/live-grammar-review-01/repeat-02
.\.venv\Scripts\python -m pytest tests/test_shadow_grammar.py tests/test_grammar_progress.py tests/test_diagnostics.py tests/test_shadow_view.py tests/test_server.py -q
.\.venv\Scripts\python -m pytest -q
```

Use a new evaluation output directory. The private sealed review sidecar keeps
uncertainty/provenance and crop/log hashes; frozen originals are not edited. Detailed
per-frame/negative comparisons are in `evaluation-01/report.json`; private sheets
are `visual-01.png` through `visual-04.png`. Browser screenshots, DB backup and memory
measurements are also under `private/live-grammar-review-01/`.

Warm text-only evaluation (100 repeats): median **0.156ms per 30 fields**, about
**0.0052ms per field**, p95 batch 0.284ms. A retained 30-field batch used about
44 KiB Python allocations (45 KiB peak), excluding imports/images/model/process RSS.
API payload grew from 40,894 to 56,641 bytes for this snapshot. No second inference,
image processing, model download or production-state write occurs.
CPU timing was one coarse Windows timer tick across the microbenchmark; the wall
times are more informative. No Linux/VPS or fresh livestream performance is claimed.

Validation: **189 focused Python tests passed; 1,022 full-suite tests passed, zero
skipped** (97.73s). Six actual Chrome cases passed, including thirty raw-value and
proposal comparisons, polling, desktop/mobile, failures/staleness and cached-error
display. API requests measured 11/14.5ms; used V8 heap was about 1.31 MiB (not total
browser RAM). Saved screenshots were inspected. All 62 original log/crop inputs,
30 database attempt payloads and the live DB file remained unchanged; trusted
observation count stays zero. `git diff --check` and private ignore checks passed.

Changed: new `src/exp_tracker/shadow_grammar.py`, `tools/evaluate_live_grammar.py`
and `tests/test_shadow_grammar.py`; additive read-only snapshot metadata in
`diagnostics.py`; raw pipe display in `shadow_view.py`; shadow HTML/JS/CSS and
renderer/browser tests; diagnostic persistence tests; existing grammar tool
re-export and documentation. No capture, model, strict-parser, Store, schema,
percentage-progress or trusted-overlay changes. No commits, pushes or deployment.

Next: James reviews the nineteen hypotheses and ambiguous native percentage at 27,
then obtain genuinely independent punctuation/numeric negatives before considering
an acceptance gate. Do not count grammar agreement as pixel or temporal verification.
