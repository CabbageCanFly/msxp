# Prompt level-up recognition and recent-window gaps

2026-10-19, focused MVP follow-up to [public level evidence](mvp-level-evidence.md).
Acquisition, OCR models, identity assignment and trusted accounting are unchanged.

## Saved CharA level-up

Read-only input is the `streamer_a` directory in
`private/multi-alpha/runs/20261019T080326Z-f4f3d659/`, including preceding
rotations. Target run: `764dc5b622f54861bfb90a43168330c4`.
All 60 target prefixes were projected causally at their original receipt times
in an isolated in-memory store. Input hashes match before/after; no live database,
coordinator or Twitch source was accessed. Artifacts are ignored under
`private/streamer_a-mvp-wrap/`.

Three independent exclusions delayed useful public progress:

1. The established-neural-level conflict check ran before the two-reader agreement
   check. The first agreed 69 was rejected because the retained reader level was 68.
2. `1.,719` failed the grouped-integer grammar, despite retaining every digit.
3. `3,44410.18%` lacked the final closing bracket required by the bounded grammar.

`experimental_level_v8` lets two valid, agreeing readers establish the new level
on that first fresh, unique-HUD frame. A lone changed neural reader still requires
confirmation. Source boundaries, geometry, numerical checks and freshness remain
in force. Arithmetic corroboration from the old level is cleared when reader
evidence moves to another level. The level change begins a new baseline; it never
supplies transition EXP.

`bounded_exp_v7` adds only two punctuation cases to the existing interpreter:
one mixed double grouping separator (`.,` or `,.`) at an otherwise complete
three-digit group, and an absent final bracket after a literal `%` in an otherwise
uniquely interpretable complete pair. Existing misread opening-bracket handling is
reused. At most four edits are allowed. No missing digits, percent symbols or
decimal places are supplied. Explicit source clipping vetoes absolute recovery;
ambiguous fields, bad grouping and trailing extra fields still abstain.

Strict parsers and the legacy v1 proposal function are unchanged. Recovered pairs
retain `grammar_recovered`, raw text and edit provenance, `trusted=false` and
unverified numerical identity. They use the existing public level/EXP inference,
continuity and interval systems, including mathematical compatibility checks.

| Attempt / UTC | Raw text | Before public result | After public result |
| --- | --- | --- | --- |
| 11 / 09:01:12.153428 | `151[0.01%]` | Held level 68 / 99.91%; no current EXP | Level 69 / 151 EXP / 0.01% |
| 12 / 09:01:37.780669 | `1.,71910.09%1` | Level 69; percentage still held at 99.91% | Level 69 / 1,719 EXP / 0.09% |
| 13 / 09:02:06.728610 | `3,44410.18%` | Level 69; percentage still held at 99.91% | Level 69 / 3,444 EXP / 0.18% |
| 14 / 09:02:32.744487 | `5,244[0.27%1` | First usable new-level EXP / 0.27% | Same reading, connected to the new baseline |

The public level arrives 25.627241 seconds sooner; initial new-level EXP arrives
80.591059 seconds sooner. The 68-to-69 reset contributes no gain. Subsequent
numeric gains are 1,568 + 1,725 = **3,293 EXP** by attempt 13, then another 1,800
by attempt 14. The level-up announcement becomes available at attempt 12.

At attempt 13, the five-minute tracked estimate changes from 7,787.4006 to
11,080.4006 EXP: independent old-level percentage-derived intervals plus those
3,293 numeric EXP. Fractional estimates originate in percentage-only evidence,
not invented integer EXP. At target-run end the replayed-context total changes
from 171,977.9375 / 99 intervals to 177,070.9375 / 103 intervals (+5,093 EXP).
The final five-minute total remains 7,072; the early recovered intervals have aged
out. Thirty-minute totals change from 70,000.0725 to 75,093.0725.

These logs establish causal projection, reader agreement and table compatibility.
This task did not independently label source pixels or rerun OCR; recovered
digits are supported by the saved text/sequence, rather than new visual proof.

## Capture gaps: working behavior retained

The exact requested example already works before this change:

| Elapsed | Observation |
| --- | --- |
| 0 seconds | 10,000 EXP |
| 60 seconds | 11,000 EXP |
| 120, 180, 240 seconds | Failed acquisition |
| 300 seconds | 15,000 EXP |

At exactly 300 seconds, all 5/10/15/30/60-minute cards contain **5,000 EXP**.
The existing collector adds 1,000 over 60 seconds and the endpoint-supported
4,000 over 240 seconds, using all 300 seconds in the pace denominator: 60,000
EXP/hour. Missing frames are neither zero-gain samples nor fabricated endpoints.

The retained MVP window policy includes only whole eligible intervals entirely
inside the lookback. One microsecond later, the 0-to-60-second interval crosses
the five-minute cutoff: five-minute gain becomes 4,000, while longer windows
remain 5,000. We cannot determine how much of the first interval's gain happened
after that cutoff. Excluding the whole interval keeps totals additive, nonnegative
and nested, without assigning unknowable timing. No prorating or clamping an old
endpoint to the cutoff is introduced. The public hover explanation now states
this rule and the safe-gap policy explicitly.

An eligible endpoint interval may span at most 300 seconds (inclusive). Longer
gaps are excluded, with the next usable endpoint starting a new baseline.
Character/session/source changes, unrelated run boundaries, competing HUDs,
stale/duplicate frames, contradictory pairs, quarantined observations, EXP loss
and level resets can also interrupt arithmetic. An ordinary acquisition failure
does not itself discard an otherwise safe, same-level net difference.
The existing interval continuity gate also excludes a jump of ten percentage
points or more. These limits were retained; the supplied example does not hit them.

Totals and rates answer different questions: recent EXP sums eligible intervals;
pace divides those gains by their actual eligible elapsed time. Five thousand
EXP over only 60 seconds of observed history is 300,000 EXP/hour, even if the
selected card says five minutes. It is not 60,000 EXP/hour unless the eligible
denominator is 300 seconds. Partial-history durations remain exposed separately;
complete-window comparisons/rankings keep their existing eligibility rules.

For a concrete saved example, CharA prefix 13 shows 11,080.4006 EXP over
172.039297 eligible seconds (eight readings in two sequences): 231,862.3876
EXP/hour. The localhost screenshot's rounded +11,080 and ~231,862/hour are
consistent. Multiplying the five-minute gain by 12 would use an unsupported
300-second denominator. No recent-window arithmetic change was needed.

API cards and rolling-history summaries reuse `tracked_window()`; chart interval
totals share the same eligible evidence. Existing bar placement within an eligible
interval is an explicitly estimated visualization, not observed intermediate
samples. Neither a rate nor a bar should be used to assert exact gain timing
inside a missing period.

## Validation

New synthetic regressions cover the three exact strings, digit-preserving edits,
clipped fields, malformed grouping, missing digits, extra/competing fields, edit
limits, first-frame agreement, single-reader conflicts, capture/identity barriers,
unknown reset gains, public projection and rolling history. Gap regressions cover
the exact timeline, microsecond cutoff, nested windows and the inclusive endpoint
duration limit. A private-fixture test replays the real CharA prefix through
diagnostics, public projection, the background publisher and HTTP API; it skips
when that private log is unavailable.

Existing localhost browser checks passed on saved prefixes 11 and 13, exercising
homepage, character, history and transparent OBS overlay with seven screenshots
per prefix. Only new private replay databases were used. Screenshots and published
payloads are retained beside the replay JSON. These frozen replays prove display
and API consistency, not newly measured stream latency or OCR accuracy.

Final results: 349 focused Python tests passed; the full `python -m pytest` suite
passed 2,026 tests with one OS symlink-permission skip and no private-sample skips.
All 88 focused Node tests passed. Both localhost browser checks passed (14 PNGs
total). `git diff --check` passed. No running service was restarted.
