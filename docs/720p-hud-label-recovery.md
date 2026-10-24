# Merged HP/MP labels in small HUDs

A low-resolution HUD could be visible and readable while localization returned
`missing_hud`. Tesseract sometimes merged the HP/MP label and its value, reading
the opening bracket as `I` or `R`. The label recognizer accepted `MP123/456`, but
rejected tokens such as `MPi123/456]`.

`adaptive_hud.label()` now recognizes this bounded HP/MP token form. After the
bracket lookalike, a nonempty suffix must contain a digit or end in a closing
bracket. Ordinary words without those markers remain rejected. This only
identifies a label: the raw token and its numbers are not rewritten. EXP and LV
label rules, full-frame scanning, both existing OCR scales, layout geometry,
competing-HUD rejection and numerical/identity safeguards remain in force. The
stricter bare-label fallback for a missing LV does not accept merged HP/MP words.
There are no additional OCR requests, streamer-specific coordinates or expected
EXP values in the reader.

## Offline check

Extracted original 1280x720 frames from a public archive covering the reported
failures, rather than reducing desktop screenshots. Numbers were visually
checked using enlarged original HUD pixels; labels are provisional, one reviewer.

| Same frames, before/after | Before | After |
| --- | --- | --- |
| Initial ten frames, used to diagnose the label problem | 8/10 | 10/10 |
| Eight additional later frames, checked after the change | 5/8 | 8/8 |
| Total correct recovered EXP/percentage readings | 13/18 | 18/18 |

The fixed readings also passed the existing autonomous level guard, persistence
and public player projection in a fresh disposable SQLite database. This uses
the existing grammar recovery; it does not claim all raw strings are strict OCR
pairs. Synthetic regressions cover the new token form, bounded negatives,
unchanged crop geometry, missing-LV rejection and competing HUDs. An additional
non-game frame remained rejected as a missing HUD. Four other live frames located
their HUD before and after the change; one still misread the final EXP digit.
That independent digit-recognition failure is not fixed by a label-only change.

These are frames from one stream, not a general 720p accuracy benchmark. Desktop
Tesseract 5.4.0 and the existing RapidOCR 3.10.0/ONNX Runtime 1.31.0 were used.
The change was not deployed to the VPS. Individual digit misreads, compressed or
hidden fields and processing-age timeouts can still withhold readings.

Frames, raw diagnostic outputs, enlarged review and the disposable replay stay
in ignored `private/`; they are not committed.

## Operator log follow-up

The original journal summary only displayed strict raw OCR candidates and aged
the latest strict candidate. This could report unavailable EXP and a long stale
age while the public player had a fresh grammar-recovered reading. Held evidence
was also hidden, so a level or identity hold could incorrectly look like OCR had
not run at all.

Capture reporting now uses the existing eligible-reading projection for recovered
values and freshness, labels recovered values explicitly, and shows original HUD
and level diagnostics with `HELD` and the hold reason when appropriate. Startup's
saved-history age uses the same display projection. Stored raw OCR, numerical
checks, holds, capture behavior and public tracking calculations are unchanged.
Logging itself never repairs letters. Future, out-of-order and rejected readings
do not refresh the logged reading age. The grammar recovery below can supply a
numeric interpretation before the normal display and progress checks run.

## Single numeric glyph recovery

`bounded_exp_v10` can interpret one uppercase `S` → `5`, `O` → `0` or `B` → `8`
inside either numeric field of a complete EXP/percentage pair, or a complete
percentage-only field. The limit is one glyph across the whole reading. Existing
bounded punctuation recovery may accompany it. The corrected text must satisfy
the existing whole-field grammar, including percentage range, decimal precision,
EXP grouping and a literal `%`. No missing digit or decimal position is guessed.
Multiple letter repairs, unknown letters, extra words and reviewed clipped
sources abstain. Malformed EXP grouping cannot supply a full EXP pair; an
independently bounded percentage may remain available.

This revision replaces the initial requirement for numerical EXP plus two prior
supported full readings. `[6S.30%]` can now propose `65.30%` without either. The
EXP table may convert that percentage to estimated EXP, but cannot independently
verify it when numerical EXP is absent. When both fields are available, existing
level/EXP arithmetic vetoes remain in force. Existing character assignment,
freshness, duplicate/crop, level confirmation and numerical-continuity policies
still decide whether a proposal can update a display or contribute progress.
A level conflict may leave a percentage visible without a usable level or gain.

One exception requires positive arithmetic confirmation: when the captured text
starts with `S` or `B` as the first EXP digit, the repaired EXP must match the
displayed percentage at an independently read or supported level. Missing or
unsupported levels and mismatches hide the numerical EXP, including on a first
capture without history. These repairs cannot infer a level to verify themselves.
The independently readable percentage remains eligible under normal rules.
Labels or other text before the initial letter do not establish a complete EXP field.

Eligible values use the existing `grammar_recovered` label and journal output.
Raw OCR, saved strict candidates and trusted accounting remain unchanged. No
additional OCR pass, dependency or separate display/graph recovery path is needed.

For Streamer_G's saved level-39 captures, `174.13216S.30%1` proposes
`174,132[65.30%]`, and `175,30516S.74%1` proposes `175,305[65.74%]`. Both rounded
percentages agree with the current 266,682-EXP requirement. Replaying 45 saved VPS
attempts in a fresh local database adds those two public graph readings, loses no
previously readable graph points and leaves trusted observations empty. Synthetic
tests cover all three letters in both fields, percentage-only recovery without
prior history, malformed grouping, multiple repairs, arithmetic contradictions,
normal endpoint exclusions, API restart, chart presentation, logs and unchanged
SQLite payloads. This is not an empirical false-positive rate: a letter can still
be misinterpreted, and percentage-only text has no independent arithmetic check.

## Small EXP after a level-up

On this stream the opener is always read as `1`. Grouped EXP proves that `1` is the
opener (`266.109199.79%1` → `266,109[99.79%]`), but right after a level-up the EXP has
no comma: `19210.07%]` reads as `192[0.07%]` or as `192` + `10.07%` behind a lost opener.
`bounded_exp_v11` proposes the first only for an EXP of at most three digits and tags it
`ungrouped_exp_opener`; two possible openers (`11110.07%]`) still abstain. `)` is now
accepted as the closing bracket after a literal `%`, as the strict parser already does.

The text cannot choose between the readings; the EXP table can. `project()` keeps the
pair only if it is consistent with a level read independently of it: the selected
reader level or a supported anchor, as for leading `S`/`B` repairs. Otherwise the frame
abstains exactly as before (`exp_opener_unverified`, no reading, no percentage, not an
arithmetic contradiction), and the pair cannot vouch for a neural-only level in the
level guard. Level 40 needs 294,216 EXP, so 192 EXP rounds to 0.07%; 10.07% would be
about 29,600 EXP.

Replaying the 102 stored VPS attempts (05:40–06:46 UTC on 2026-10-24) in a fresh local
database: 15 frames gain `192[0.07%]` at level 40, from the 06:34:53 level confirmation
on; no other reading changes, and the level-up interval adds exactly 765 EXP. Before,
the page showed the confirmed Lv. 40 beside the last Lv. 39 reading, 99.79%.

While a newer confirmed level has no reading yet, the page shows that level's start
(0 EXP, 0.00%, with a hover note) instead of the old level's percentage. This is display
only: the API still returns the last real reading, and gains and rates use it. The level
sort uses the shown value, so the character ranks at the start of the new level.

Untested: other streams and levels, and the VPS (this change is not deployed). The
13-minute wait for level confirmation is unchanged.
