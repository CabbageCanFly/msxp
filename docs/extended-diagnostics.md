# Extended diagnostic EXP coverage

The local alpha now exposes versioned punctuation interpretations, an independent
percentage-recovery path, optional chart layers and a coverage summary. These are
**EXPERIMENTAL / UNVERIFIED**. Strict parsing, source completeness, numeric accuracy
and trusted accounting remain different claims. No new capture or OCR inference
was needed for this milestone.

## Levels and published requirements

Recognized levels already support **1–200**, independently of any EXP table. A
missing requirement must not invalidate a recognized level. Table values describe
EXP to advance **from** a level, not cumulative EXP or confirmed gains.

All requested sources were accessible on 2026-10-17:

| Source | Published coverage | Finding |
|---|---|---|
| [NiaMeowDB guide](https://meowdb.com/msclassic/guides/exp-table-level-1-to-100) and [leveling page](https://meowdb.com/msclassic/formulas/leveling) | 1–99, reaching 100 | Same publisher; matching tables are not independent confirmation |
| [Maplestory.quest](https://maplestory.quest/exp-table) | 1–119 | Agrees through 89; disagrees from 90 onward |
| [MapleClassic Wiki, revision 89094](https://mapleclassic.wiki/index.php?title=Experience&oldid=89094) | 1–49 | Declines to confirm higher requirements |

The separate public resource `src/exp_tracker/data/community-exp-v2.json`, version
`community-exp-v2-2026-10-17`, retains agreed values in `to_next`, conflicting
published alternatives in `disputed_to_next`, and explicit missing levels 100–200.
All 49 overlapping historical entries agree; the frozen private table/hash remains
unchanged. No formulas were used to generate missing entries.

| Levels | Diagnostic lookup |
|---|---|
| 1–89 | Community-sourced/provisional requirement; 50: 709,716; 64: **1,497,832** |
| 90–99 | Both published values retained, **no selected requirement** |
| 100–200 | Missing requirement; still valid recognized levels |

For example, at 90 the publications give 11,938,059 versus 5,996,316; at 99,
9,482,161,548 versus 9,692,044. Thus the dataset includes published requirements
through 99 (reaching 100), but does not pretend those ten disputed requirements
have a confirmed common value. This is not a level-89 or level-49 game cap.
Maplestory.quest also publishes 100+ values; they are outside the chosen dataset
extent and are not used to fill future requirements automatically.

Underlying extraction independence, recording-build applicability and official
confirmation are unresolved. The sites' differing build/cap claims are not resolved
by popularity or agreement. The dashboard shows provisional requirement status
separately from both visual levels and **archived arithmetic evidence**. An old
`unsupported_visual_level` relation refers to the supplied old table, not rejection
of the recognized level. Saved hashes/results are never recomputed in place.

Future shadow runs default to this public, agreeing 1–89 table, with its hash and
provenance in the existing configuration record. Historical reproduction remains
available with `--requirements private/exp-consistency/requirements.json`.

## Fixed grammar v2

`exp_tracker.shadow_grammar.interpret_exp` retains the original text and emits
separate `strict_full`, `strict_percentage_only`, `full_exp` and `percentage`
evidence under policy `bounded_exp_v2`. Both original strict parsers and
`propose_full_exp` / `bounded_full_exp_v1` remain unchanged.

- Whole input is bounded to 160 characters. An actual `%`, present opening/closing
  boundary symbols and exactly two fractional digits are required. No missing
  boundary, number, decimal point, digit or EXP group is inserted.
- Potential boundaries are only `[`, `1`, `|` and terminal `]`, `1`, `|`. A numeral-1
  opener needs a valid grouped EXP prefix; an actual bracket/pipe can bound a
  percentage independently. No global `|`, `I`, `l`, S/5 or digit substitution.
- Percentage comma-to-point is allowed only in a uniquely bounded one/two-digit
  (or 100) percentage token. Spaces, extra punctuation, missing fractional digits,
  unknown prefix text, multiple fields and absent boundaries abstain.
- EXP dots become grouping commas only inside valid three-digit groups. Completed
  full proposals pass unchanged `parse_exp` and strict pair eligibility/ranges.
- Percentage-decimal repair **never establishes a complete EXP prefix**: that path
  deliberately emits percentage-only evidence, even if the prefix looks grammatical.
  This conservative restriction avoids claiming clipped EXP on text evidence alone.
- Four substitutions maximum, two retained interpretations per field. Multiple
  interpretations abstain; no arbitrary winner. Every proposal records original
  edit positions/types, field span, unverified flags and required image verification.
  A source-completeness veto blocks full proposals but does not discard an explicitly
  bounded percentage suffix solely because EXP was clipped.

Source completeness is otherwise unknown. Text cannot detect all clipping or
distinguish an actual numeral 1/pipe from a misrecognized bracket. Missing boundary
cases remain unavailable rather than being reconstructed from neighbors.

## Saved Streamer_A replay: every attempt retained

The maintainer captured 30 attempts seven seconds apart. Native crop review/labels are
Codex-assisted provisional evidence after OCR exposure, not blinded accuracy;
The maintainer supplied clipping findings and reported level 64. Existing frozen sidecars,
logs, crops, operator output and original SQLite payloads were preserved.

| Evidence / 30 attempts | Before (v1) | Now (v2) |
|---|---:|---:|
| Acquired frames / unique located HUDs | 30 / 30 | 30 / 30 |
| Original strict full pairs | 7 | **7 unchanged** |
| Additional unique full-EXP proposals | 19 | **21** |
| Original strict percentage-only | 0 | **0 unchanged** |
| Independent recovered percentage proposals | Not exposed | **23**, overlapping the 21 full proposals |
| Percentage recovery without a full proposal | 0 | **2** |
| Full EXP still unavailable even with proposals | 4 | **2 clipped fields** |
| No strict/proposed percentage at all | 4 | **0 syntactically** |
| Ambiguous text interpretations | 0 | 0 |

There are **20 provisional full-proposal agreements and one unknown**, and **22
provisional percentage agreements and one unknown**. Zero text ambiguities does
not mean zero ambiguous pixels. No independently verified correctness gain or
single accuracy score is claimed. The 23 malformed strict results stay malformed.

| Attempt / unchanged raw text | Full proposal | Separate percentage proposal / limitations |
|---|---|---|
| 21: `3,862[32,97%]` | None | `32.97%`; comma→point; leading EXP clipping preserved |
| 23: `494,697\|33.03%\|` | `494,697[33.03%]` | `33.03%`; two contextual pipe boundaries; provisionally matches crop review |
| 24: `5,031[33,05%]` | None | `33.05%`; comma→point; absolute EXP unavailable |
| 27: `496,738\|33.18%1` | `496,738[33.18%]` | `33.18%` remains numerically unverified; crop's final digit is ambiguous/6-like |

The fourth case is **not corrected to 33.16%**. Its frozen reference leaves the
percentage unknown. Neither neighbors nor table arithmetic choose a digit.
All seven strict pairs retain their original numerical values and parser semantics.

### Level-64 arithmetic (separate hypotheses)

Published level 64 was fixed at 1,497,832 before comparison; reported level 64 is an
explicit external assumption, not selected to fit OCR. Reused exact integer
`assess` arithmetic, with no tolerance or universal display rule selection:

| Inputs | Nearest-half-up | Truncation |
|---|---:|---:|
| Seven original strict pairs | **7 consistent / 0 inconsistent** | **2 / 5** |
| Twenty-one grammar full proposals, exploratory | **20 / 1** | **11 / 10** |

Strict truncation disagreements: attempts **1, 6, 9, 22, 29**, each one displayed
hundredth above truncation. Attempts 15/25 match both. This supports nearest rounding
for these observations conditional on the table/level, but does not establish build
identity, ties, hidden fractional EXP or universal client semantics. The earlier
test-shadow trial had different rounding evidence; it is not overwritten.

Grammar attempt 27 is inconsistent under **both** hypotheses: its EXP would display
33.16%, not 33.18%. This is a warning, not digit reconstruction, rejection-based
winner selection or independent confirmation of other proposals. Neural level
misreads **54 at 16/23/27 and 84 at 28** remain visible; they are never replaced by 64.

### Negative evidence remains important

Replayed all 14 saved controls. Known wrong `74,050` and clipped `4,059` full
proposals still survive text-only grammar without a completeness veto; genuine
`2345[92.74%]` leading-digit contamination remains an unchanged strict value.
The historical `99.82` substitution stays `99.82`, not a repaired `99.92`.
Malformed/damaged punctuation and actual numeral-like boundaries can also yield
proposals. A percentage surviving a bad EXP prefix does not verify those digits.

## Persistence, charts and coverage

No migration or historical row update: the immutable raw event is authoritative.
SQLite snapshots deterministically derive additive `interpretations` with policy
ID, reasons and proposals; the old `grammar_recovery` v1 field remains compatible.
`requirements` and `requirements_table` describe separate provisional lookup data.
Restart/replay yields the same interpretations from the same raw events/policy.
Future policy versions must retain their IDs; export the versioned snapshot/report
when a frozen comparison is required. Re-deriving avoids another mutable table but
means future software policies can change the current derived view, not old evidence.

Both charts are points only. Original strict full points, strict percentage-only
squares, stale diamonds, failure crosses and sampling-gap shading remain. Optional
hollow amber full-EXP triangles / purple percentage diamonds are **off by default**.
Original failure crosses remain underneath the recovered layer: those marks refer
to the same attempt, not independent observations. Stale recovered points are dashed.
The percentage axis explicitly zooms to the displayed range. No curves, interpolation,
cross-level gains, fabricated EXP or continuity through unverified values are drawn.
The selected open session/character remains isolated; visual-level changes are
marked on the percentage timeline and unknown levels do not establish continuity.
Each point retains its own run's capture interval. Gap shading no longer applies
the newest run's cadence to all older history; a mixed 30s/7s regression covers it.

The compact coverage panel uses the **latest 120 attempts in the selected session**,
with exact total session attempts and the analyzed-window size explicitly shown.
Categories overlap; e.g. 21 full proposals are included in the 23 percentage
proposals. Missing acquisition/HUD evidence is unknown, not assumed successful.
Seven Tesseract levels are unavailable and four neural misreads have no simultaneous
accepted Tesseract level, so the zero direct visual/neural conflict count is **not**
evidence of correct levels. No overall numerical accuracy score is presented.

`candidate`, `percentage_only_candidate`, `latest_reading`, original arithmetic,
launcher success counts, strict percentage pace, trusted Store/state/statistics,
OBS overlay and leaderboard calculations do not consume proposals. Trusted gains,
EXP/hour, ETA, ranks and automatic level-ups remain unavailable for these diagnostics.

## Run locally, without a new capture

```powershell
# View the EXISTING saved live database. HTTP does not start capture.
.\.venv\Scripts\python -m exp_tracker.server --db private/local-alpha/live/streamer_a.sqlite3 --diagnostic-dashboard --port 8766
# Another terminal:
Start-Process 'http://127.0.0.1:8766/dashboard/streamer_a'
# Enable the optional recovered chart layer to inspect proposals.

# Reproduce the offline evaluation; always use a NEW output directory.
.\.venv\Scripts\python tools/evaluate_extended_grammar.py --log private/local-alpha/runs/streamer_a-20261017T073930Z-986495bd/capture.jsonl --reviews private/live-grammar-review-01/visual-review.json --reported-level 64 --output private/extended-coverage-repeat-01
.\.venv\Scripts\python -m pytest tests/test_extended_diagnostics.py tests/test_shadow_grammar.py tests/test_diagnostics.py tests/test_shadow_capture.py tests/test_server.py -q
.\.venv\Scripts\python -m pytest -q
node --test tools/shadow.test.mjs tools/overlay.test.mjs tools/leaderboard.test.mjs
node tools/shadow.browser.mjs http://127.0.0.1:8766/dashboard/streamer_a private/extended-browser-repeat-01
```

Private evidence: `private/extended-coverage-02/report.json` and
`changed-cases.png`; a fresh replay/restart/idempotence database is
`private/extended-coverage-01/replay.sqlite3`. Original live data is not overwritten.
The evaluator refuses existing outputs and validates all log/crop/reference hashes.

Text-only v2, 100 warm repeats: median **0.245ms per 30 fields**, p95 **0.286ms**,
about **0.0082ms wall / field**; CPU about 0.0104ms/field (coarse Windows timer).
Retained Python allocations: **55,461 bytes**, peak **56,912**, excluding imports,
models, images and process RSS. This is additional grammar cost, not capture/OCR cost.

Warm complete read-only SQLite snapshot (30 attempts, 30 repeats): median **3.77ms**,
p95 **4.12ms**, serialized JSON **111,630 bytes**, retained Python allocations
**218,863 bytes**, peak **411,018**. Chrome API requests measured **12.8/9.6ms**;
used V8 heap approximately **1.48 MiB**, not whole-browser RAM. No Linux/VPS claim
follows from these workstation timings. The API remains bounded to 120 history
rows; the exact session total is a separate indexed database count.

Validation: **193 focused Python tests; 1,061 full-suite passes, zero skips; 33 Node
tests**. Nine Chrome screenshots/checks cover 30 original values, chart-layer separation,
polling, desktop/mobile, cached errors and gaps. Screenshots were visually inspected.
Initial browser validation caught a raw-text
card bug, corrected with a regression. No new inference/model download or Twitch
capture occurred. Detailed browser measurements/screenshots remain private at
`private/extended-coverage-02/browser-final-02/`. `operational-validation-final.json` records
**67 unchanged input hashes** including the original live database and all 60 saved
field crops; the fresh replay has **zero trusted observations**. The full suite
took 97.55s on the final run. Initial sandbox-only pytest temp-directory permission errors were
environmental; normal-permission focused/full runs passed without skips.

Changed files:

- `src/exp_tracker/data/community-exp-v2.json`, `src/exp_tracker/exp_requirements.py`,
  `pyproject.toml`: separate versioned, packaged provisional lookup data.
- `src/exp_tracker/shadow_grammar.py`: additive v2 interpretation; v1 unchanged.
- `src/exp_tracker/diagnostics.py`: read-only interpretations, requirements and
  explicitly bounded coverage summary; no schema change.
- `src/exp_tracker/web/shadow.html`, `shadow.css`, `shadow.js`: diagnostic controls,
  distinct markers, zoomed percentage axis, coverage and percentage-only cards.
- `tools/shadow_capture.py`: only the default diagnostic requirements path/help;
  recognition, acquisition and guards unchanged.
- `tools/evaluate_extended_grammar.py`: non-overwriting offline evaluator/review sheet.
- `tests/test_extended_diagnostics.py`, `tests/test_diagnostics.py`,
  `tools/shadow.test.mjs`, `tools/shadow.browser.mjs`: focused and browser regressions.
- `README.md`, `docs/local-alpha.md`, `docs/shadow-capture.md`,
  `docs/live-grammar-recovery.md`, `docs/exp-consistency.md`, this document:
  current defaults, historical-policy distinction and reproduction.

The [multi-stream alpha](multi-alpha.md) now implements bounded sequential capture,
a shared database/directory and separately gated experimental percentage progress.
Grammar proposals may contribute there; they still contribute no trusted accounting.
Before any
trusted neural ingestion, independently review source completeness/numeric errors
and resolve build/table semantics; more punctuation coverage alone is insufficient.
