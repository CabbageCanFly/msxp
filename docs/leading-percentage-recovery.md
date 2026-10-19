# Leading `1` in percentage-only fields

The saved 35-attempt Telfer1 run `20261019T000710Z-bda4f628` contains three
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

`bounded_exp_v6` records a **review-only hypothesis** for precisely
`1DD.DD%]` or `1DD.DD%1`, where the remaining percentage is 10.00–99.99.
It substitutes position-zero `1` with `[` and, if necessary, terminal `1` with
`]`. It changes no numerical digit, decimal or percent sign and supplies no EXP
integer. The ordinary percentage-proposals list remains empty: syntax alone
cannot promote it. Strict parsers and the frozen full-EXP v1 policy are unchanged.

Read-time percentage review admits the hypothesis only with two immediately
preceding eligible **strict percentage-only** observations, not full pairs or
grammar recoveries. All three frames must have distinct hashes, matching supported
level, explicit channel/character/session/source/run context, ordered timestamps
within 120 seconds and no intervening failure, quarantine or unsafe boundary.
These are distinct captures, not independent statistical proof of correctness.
Recovered hypotheses cannot seed further recoveries.

The existing level, freshness, HUD, whole-pair arithmetic veto and percentage
quarantine still run. A decrease remains pending; a missing/conflicting level or
insufficient format context leaves the candidate review-only and unavailable to
the public reading decoder. `100.00%1`, one-digit/truncated `0.85%1`,
`170 57%1`, extra prefixes, multiple percentage tokens, decimal repairs and
unsupported closing glyphs are outside this new rule. Previously rejected
`156.97%1` receives no ordinary proposal or public point without the causal gate.

## Replay result

| Evidence / 35 attempts | Before | After |
|---|---:|---:|
| Original strict percentage-only readings | 31 | 31 |
| Existing bare-token recovery (#18) | 1 | 1 |
| Newly eligible leading-bracket hypotheses | 0 | 3 |
| Public/chart and progress points | 32 | 35 |
| Original strict full EXP pairs | 0 | 0 |

Prefix-only replay at attempts 4, 12 and 24 gives the same decision as the full
run; later percentages are never consulted. Telfer1's earlier wrong whole pair
at #21 remains vetoed. Existing Shiphtur stale-frame/reacquisition and numerical
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
