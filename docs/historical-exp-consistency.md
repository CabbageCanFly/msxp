# Historical EXP consistency investigation

Investigated on `fix/historical-exp-consistency`, based on `4748006`, using the
existing Windows Python environment and read-only saved captures. No capture,
recognition, EXP requirement, identity or gain policy was changed.

## Stale window expectations: eight total failures

The current [rolling-window policy](rolling-window-gaps.md) includes a whole
nonnegative interval if its **later endpoint** is inside the window and its
duration fits the selected period. All eight failing saved-total assertions
still expected intervals wholly contained inside the period. Recomputing that
older rule from the saved observations reproduces every old expected number.
Each difference is exactly one qualifying boundary-crossing interval; recovered
interior readings and cross-level arithmetic do not explain these discrepancies.

| Saved checkpoint (UTC) | Window | Old expectation | Crossing gain | Correct total |
|---|---:|---:|---:|---:|
| CharE, Oct 19 00:18:17.939131 | 60m | 127,108 | 897 | 128,005 |
| CharA, Oct 19 10:40:56.881611 | 5m | 17,175 | 987 | 18,162 |
| CharA, Oct 19 11:28:56.524233 | 5m | 16,977 | 1,275 | 18,252 |
| CharA, Oct 19 14:42:43.515014 | 5m | 16,038 | 3,716 | 19,754 |
| Streamer_F, Oct 19 01:03:54.273738 | 5m | 4,757 | 455 | 5,212 |
| Same Streamer_F checkpoint | 10m | 9,994 | 307 | 10,301 |
| Same Streamer_F checkpoint | 15m | 14,696 | 427 | 15,123 |
| Same Streamer_F checkpoint | 30m | 27,764 | 528 | 28,292 |

The table expands the Streamer_F assertion into its four affected windows. The
CharA discrepancies are repeated across three test modules, accounting for
six of the eight original total failures. Streamer_F' 60m and 24h totals remain
42,703, including the already-established same-assignment restart gains.

Saved source evidence for the added intervals (dates are in 2026, times UTC):

| Character/run ID, attempt pair | Interval | Endpoints |
|---|---|---|
| CharE `0636d48a2a854e6bb5833677c9379ffa`, 12 to 13 | Oct 18 23:18:04.764680 to 23:18:26.624473 | 64,808 to 65,705 EXP, level 57 |
| CharA `8ef13934cb28485ab432854b161f2a4c`, 23 to 24 | Oct 19 10:35:47.354378 to 10:36:13.027796 | 370,489 to 371,476 EXP, level 69 |
| CharA `93c301aedc5441ddbc867b249103a8ae`, 52 to 53 | Oct 19 11:23:52.202666 to 11:24:14.061278 | 549,538 to 550,813 EXP, level 69 |
| CharA `616ac9fa1377484485c497c6572e9b04`, 2 to 4 | Oct 19 14:37:16.239247 to 14:38:07.930824 | 65.26% to 65.45%, level 69 |
| Streamer_F `1969b5036118431abc9ec42afd171bc5`, 58 to 59 | Oct 19 00:58:29.217401 to 00:58:55.856791 | 55,898 to 56,353 EXP |
| Same Streamer_F run, 47 to 48 | Oct 19 00:53:34.229659 to 00:54:01.156822 | 50,809 to 51,116 EXP |
| Same Streamer_F run, 36 to 37 | Oct 19 00:48:40.697848 to 00:49:08.101914 | 45,987 to 46,414 EXP |
| Same Streamer_F run, 3 to 4 | Oct 19 00:33:35.925214 to 00:34:05.791658 | 32,818 to 33,346 EXP |

For the percentage-only CharA pair, the provisional level-69 requirement is
1,955,750. The displayed coordinates round to 1,276,322 and 1,280,038 EXP:
their difference is 3,716. No digits or intermediate observations were invented.
The later 66.27% endpoint rounds to 1,296,076, giving 19,754 overall.
The numeric CharA final endpoints are respectively 388,651 and 567,790; CharE's
is 192,813. Subtracting the preceding-window coordinates gives the corrected totals.

The numeric-gap test still independently asserts the original contained
17,175 = 9,769 + 1,703 + 2,284 + 3,419, then verifies the additional 987.
Strict diagnostic-collector expectations of 10,375 and 17,175 remain unchanged.
The public card, homepage, chart, SQLite restart and nested-window checks remain.

## Stale rate expectation: one failure

Public rates use `gain * 3600 / selected_window_seconds`, not observed coverage.
At CharE's Oct 18 23:02 checkpoint the 60m gain is 139,849, so the rate is
139,849 EXP/hour. Actual coverage remains 3,601.753099 seconds because the first
interval crosses the boundary. Dividing by that coverage implements the old rule.
Updated this assertion and the equivalent downstream CharA rate/chart assertions
that were previously hidden behind the failing totals. Five-minute chart checks
now select by interval end and enforce the five-minute duration limit.

## Publication inconsistency: one implementation bug

Reproduced the original CharA failure at replay event 1,920, Oct 19
03:52:21.976670 UTC. The published revision and database head matched, publication
had zero build failures, and the first difference was exactly
`tracked_history.exclusion_counts.observed_level_decrease`.

The causal replay includes CharA run `81ad60fc3f674e57bdcc958de442f4e4`, attempts
28 to 29, Oct 18 02:25:49.727273 to 02:26:03.696644. The public endpoints have
levels 66 then 65. That pair is correctly excluded from gain. Once both endpoints
are older than the 24h start, checkpoints prune them. Observation-level exclusions
were already checkpointed, but pair-level exclusions were only recomputed from
remaining rows. A fresh rebuild therefore counted the old decrease while resumed
publication omitted it. This was lost diagnostic state, not an EXP gain difference
or a failed cache invalidation.

`tracked_checkpoint()` now carries forward exclusion counts for exactly the pairs
removed by pruning. Retained pairs are still counted during projection. It copies
the counts without mutating replay state, preserving repeated-read parity without
double counting, retaining extra raw history or changing interval eligibility.

Three synthetic boundary positions verify complete packet parity before and after
repeated resumption and clock advancement. A short two-cohort saved CharA publisher
test compares the entire publication to a cold reference on three publications.
Restoring the old pruning behavior in memory makes this test fail on the original
missing field in 1.22s; the corrected test passes.

## Files changed

- `src/exp_tracker/rolling_history.py`: retain pruned pair exclusion counts.
- `tests/test_incremental_history.py`: synthetic checkpoint parity regression.
- `tests/test_publisher.py`: bounded saved-data publication regression.
- `tests/test_cross_level_product.py`: explain the 897 EXP boundary gain and use the selected-duration rate.
- `tests/test_public_window_formula.py`: explain all three CharA additions; verify chart inclusion and rates.
- `tests/test_observed_endpoint_totals.py`: use the actual preceding-window numeric endpoints; preserve strict diagnostic assertions.
- `tests/test_numeric_gap_followup.py`: preserve the recovered/contained breakdown and assert the crossing interval separately.
- `tests/test_tracked_exp_totals.py`: document Streamer_F' four crossing gains; retain restart and nested-total checks.
- `docs/historical-exp-consistency.md`: this evidence and verification report.

## Verification and limits

The initial five-module reproduction produced **134 passed, 9 failed, 0 skipped**
in 6.64s. The separate original CharA publisher test reproduced the tenth failure
in 34.47s. No private-fixture test silently skipped.

The corrected unabridged CharA publisher sweep was stopped automatically at its
240-second timeout. Its disposable database reached 5,173 attempts (Oct 20
08:36:08.876355), beyond the original failing checkpoint, without another reported
mismatch. This is partial sweep coverage, not a completed pass. The full snapshot
has 171 CharA files and 8,706 replay records; repeated cold reference builds make
the sweep expensive. The bounded saved regression covers the demonstrated defect
in about one second. No production performance change was made here.

An adjacent run passed 122 tests and failed the concurrent-viewer HTTP test because
the sandbox denies client sockets (`WinError 10013`). That test remains unchanged;
the final focused selection excludes it and the six long all-capture sweeps.

Final run: **268 passed, 0 skipped (including 0 sample skips), 7 deselected**, in
127.69s, using `python -m pytest -n 0` with a 240-second subprocess timeout.
Selected modules: cross-level product, public-window formula, observed endpoint
totals, tracked EXP totals, numeric-gap follow-up, rolling-gap windows, rolling
history, incremental history, publisher, retention and transition retention.
The deselection expression was
`not saved_logs_match_full_replay_while_streamed and not saved_publications_match_reference and not test_concurrent_viewers_share_one_projection_per_publication`.
Three warnings concern existing `record_property` usage with JUnit's xunit2 output.
The slowest selected test was the synthetic daily retention/restart test (63.41s).
Machine-readable results are in ignored `artifacts/historical-final.xml`.
`git diff --check` passed. SHA-256 comparison confirms all **1,537 capture logs**
are unchanged from the investigation's initial snapshot.

The full suite and Ubuntu were not rerun. No new OCR accuracy claim is made. The
differences require no fixture drift to explain them; this investigation verifies
current-file preservation, not byte identity with captures used for older reports.
Source hashes and detailed endpoint receipts stay in ignored `artifacts/`.

Restarting the publishing process clears its in-memory checkpoints and applies the
fix; no migration or historical EXP re-ingestion is required. No live database,
capture log, original main worktree, deployment or Git history was modified.
