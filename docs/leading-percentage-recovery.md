# Leading `1` in percentage-only fields

The saved 35-attempt Streamer_A run `20261019T000710Z-bda4f628` contains three
instances of the same punctuation confusion:

| Attempt | Original OCR | Provisional crop inspection | Prior strict context |
|---|---|---|---|
| 4 | `194.55%]` | `[94.55%]` | 2, 3 |
| 12 | `195.11%1` | `[95.11%]` | 10, 11 |
| 24 | `196.00%]` | `[96.00%]` | 22, 23 |

Native RGB and 8× nearest-neighbor inspection show the complete percentage and
green opening bracket. Attempts 4/12 start at x=1020/1019, versus x=1023–1024
on neighboring controls, and include a white fragment of the EXP label. Their
percentage digits are not clipped. Attempt 24 has normal x=1023 geometry but
the same confusion, so displacement alone does not explain it. No crop geometry,
model, preprocessing or confidence threshold was changed.

Inspection was AI-assisted after exposure to OCR, not independent blinded human
adjudication. Images, hashes and complete per-attempt decisions are ignored under
`private/leading-percent-review/`. Original captures are unchanged.

## Bounded interpretation

`bounded_exp_v9` records a **review-only hypothesis** for precisely
`1DD.DD%]`, `1DD.DD%1` or `1DD.DD%I`, where the remaining percentage is 10.00–99.99.
It substitutes position-zero `1` with `[` and, if necessary, terminal `1` with
`]` (terminal capital `I` has the same bounded closing-bracket interpretation).
It changes no numerical digit, decimal or percent sign and supplies no EXP
integer. The ordinary percentage-proposals list remains empty: syntax alone
cannot promote it. Strict parsers and the frozen full-EXP v1 policy are unchanged.

Read-time `leading_one_percentage_v2` admits the hypothesis only with two earlier
eligible **strict percentage-only** observations, not full pairs or grammar
recoveries. Both supports must fall within **180 seconds and four attempt steps**
of the hypothesis, permitting at most two intervening unreadable captures. Every
attempt must be present, ordered, have a distinct known frame hash and retain the
same explicit channel/character/session/source/run/manual-correction context.
Supported levels must match; any competing visual/neural level clears support.
Fresh, unique-HUD malformed text and ordinary `missing_hud` captures may preserve
context, but never supply it. Stale, duplicate, suspect, contradictory, invalidated
or arithmetically rejected observations and quarantine still clear support.
These are distinct captures, not independent statistical proof of correctness.
Recovered hypotheses cannot seed further recoveries.

The existing level, freshness, HUD, whole-pair arithmetic veto and percentage
quarantine still run. A decrease remains pending; a missing/conflicting level or
insufficient format context leaves the candidate review-only and unavailable to
the public reading decoder. `100.00%1`, one-digit/truncated `0.85%1`,
`170 57%1`, extra prefixes, multiple percentage tokens, decimal repairs and
unsupported closing glyphs are outside this rule. Capital `I` is interpreted only
as the terminal character of this exact leading-one hypothesis, with the same
causal gate; there is no general `I`/digit substitution. Previously rejected
`156.97%1` receives no ordinary proposal or public point without the causal gate.

## Replay result

### Interrupted 2026-10-20 run

Read-only projection of the complete 60-attempt saved Streamer_A log under
`20261020T214039Z-1781b4bb/streamer_a/01f9f3a2328e42128e182408ffae84ff/`:

| Attempt | UTC receipt | Evidence / result |
|---|---|---|
| 33 | 22:33:15.461051 | Strict `[58.90%]`, first support |
| 34 | 22:33:53.257455 | Malformed `[59.02%】`, redacted by the unchanged HTTP allowlist |
| 35 | 22:34:33.547766 | Strict `[59.14%]`, second support |
| 36 | 22:35:17.214152 | Ordinary missing HUD, no percentage or level supplied |
| 37 | 22:35:52.226113 | `159.36%1` → experimental **59.36%**, no numerical EXP |

The first support is **156.765062 seconds** old at #37; the second is
**78.678347 seconds** old. The previous immediate-predecessor/120-second gate
lost both supports. The new 180-second/four-step bound covers this measured
sequence without widening the general progression or level policy.

Public readings increase **49 → 50**. Only #37 changes public/progress
eligibility. All other percentages, numerical EXP values and selected levels stay
equal; surrounding #33/#35/#38/#39 remain 58.90/59.14/59.46/59.56%. Causal prefix
replay ending at #37 yields the same result, without consulting #38 or #39.

**#25 stays withheld.** `158.09%I` now supplies a review-only 58.09% hypothesis;
#23/#24 are strict supports 68.826719/35.907507 seconds earlier. Neither reader
supplies a usable level at #25, so the strong context gate fails. Prior percentages
do not invent its level or character identity.

The original JSONL SHA-256 remains
`ad26f91a6b0ab06e0874f44fff73186d594cdd65829345b365476929e91430d2`.
Projection used the existing sanitized observation decoder, an explicit isolated
character/session association and no database connection. Original raw OCR remains
in the capture; the unchanged decoder redacts unsupported Unicode such as #34's
closing glyph. No capture process, live database, trusted accounting or saved
attempt payload was changed. Replay reports remain ignored under `artifacts/`.

Synthetic regressions cover both example strings, missing support/level, 180-second
and four-step bounds, contradictory valid readings, large changes, numeric prefixes,
unsafe intervening metadata, repeated frames and incremental review pages.
This is measured syntactic recovery, not independently verified OCR accuracy;
no new model inference or pixel adjudication was performed.

Validation: **381 focused Python tests passed, zero skips**, including the saved
35- and 60-attempt replays and synthetic checkpoint/retention tests. The full suite,
broad live-directory saved-log sweeps and 4,096-row cold-restore case were excluded
from this focused run. A final narrow run passed **100 tests, zero skips**, including
additional explicit numeric-prefix and raw edit-provenance assertions.
Use `python -m pytest tests/test_leading_percentage.py -n 0`
for the narrow grammar/continuity regressions; private-log cases skip when absent.

### Original 35-attempt run

| Evidence / 35 attempts | Before | After |
|---|---:|---:|
| Original strict percentage-only readings | 31 | 31 |
| Existing bare-token recovery (#18) | 1 | 1 |
| Newly eligible leading-bracket hypotheses | 0 | 3 |
| Public/chart and progress points | 32 | 35 |
| Original strict full EXP pairs | 0 | 0 |

Prefix-only replay at attempts 4, 12 and 24 gives the same decision as the full
run; later percentages are never consulted. Streamer_A's earlier wrong whole pair
at #21 remains vetoed. Existing CharB stale-frame/reacquisition and numerical
replay assertions remain unchanged. No trusted observations were inserted.

Syntactic coverage is not verified accuracy. A plausible wrong percentage can
still satisfy this context and ordinary temporal checks. Broader prefix stripping
or OCR/model changes are not justified; test the fixed rule on independently
reviewed future evidence before expanding it.

Validation: **177 focused Python tests, 1,579 full Python tests and 77 Node tests
passed; zero skips.** The only new public points in this run are 4, 12 and 24.

```powershell
.\.venv\Scripts\python -m pytest tests/test_leading_percentage.py tests/test_extended_diagnostics.py tests/test_eta_followup.py tests/test_percentage_quarantine.py tests/test_numerical_windows.py -q
.\.venv\Scripts\python -m pytest
node --test tools/*.test.mjs
```

The private `replay.py before|after` records immutable-input hashes and public
decisions in a new named replay database; use a fresh output label when repeating.
No new OCR inference, Twitch capture, active-database writes, ETA/layout changes,
scheduler changes or trusted-ingestion changes were made.

Changed files: `src/exp_tracker/shadow_grammar.py`, `diagnostic_progress.py`,
`diagnostic_percentage.py`, and the public reading guard in `product.py`;
`tests/test_leading_percentage.py`, policy-version assertions in
`tests/test_eta_followup.py` / `test_live_usability.py`, and this note.
