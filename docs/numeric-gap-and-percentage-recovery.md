# Supported numeric gaps and independent percentage recovery

The newer [rolling-window policy](rolling-window-gaps.md) supersedes the earliest/latest
net subtraction and elapsed-time rate denominator below. Recognition and conditional
percentage-recovery rules remain in effect; the following records the earlier milestone.

## Current public endpoint policy

`public_endpoint_window_v1` uses one formula for every 5/10/15/30/60-minute
card, API response and rolling summary. Select the earliest and latest usable
public observations with timestamps inside the inclusive lookback. Gain is:

`last_EXP - first_EXP + sum(requirements from first_level through last_level - 1)`

Use numeric EXP when available. Otherwise convert the displayed percentage using
that observation's level requirement and round each endpoint to whole EXP
(nearest, half up), matching the displayed graph estimate. These remain estimates,
never OCR integers. The actual endpoint elapsed time supplies both the observed
duration and the denominator for EXP/hour (`gain * 3600 / elapsed_seconds`).
Shorter observed spans are partial history, not full-window rates. There is no
additional minimum duration or maximum gap. No interpolation at a lookback boundary
and no reconstructed intermediate observations are used.

Current level only selects observations at the publicly displayed level before
applying that same formula. Known level-ups include the level requirements;
an unknown transition requirement is an explicit limitation. Numeric endpoints
within a level work even if that level's requirement is missing. Percentage-only
EXP requires its level and requirement. Two distinct observation times are needed.
A negative net or decreasing endpoint level is reported explicitly rather than
turned into positive earned EXP. Actual losses inside a longer window reduce its
net gain; consequently nested totals need not increase through a genuine loss.

Removed public gain restrictions: capture failure reasons, HUD failures, graph
connections, run/coordinator IDs, source/session changes within the existing selected
character association, restart links, short-gap limits, `progress_eligible`, and
strict-versus-grammar classifications. Ordinary usable public percentage-only
readings participate alongside numeric readings. Existing conditional-symbol
recovery still requires its original independent arithmetic/context checks; the
strict collector supplies those recovered observations, never interval approvals.

The mathematical necessities are usable EXP coordinates, known reset requirements,
actual ordered timestamps, and the selected-character association. Freshness,
non-simulated acquisition, crop validity and the existing public-reading validation
remain observation checks. Unusable intermediate rows never erase endpoints.
Unknown-level percentage points may remain visible as percentages, but cannot
serve as EXP endpoints. Original provenance, inference, diagnostic intervals,
trusted accounting and visibly disconnected raw graph lines remain intact.

Public bars put each observed difference at its later observation, including
negative differences where observed; they do not spread it uniformly through a
capture gap. Their sum agrees with endpoint net gain when the required coordinates
are known. The shared 24-hour summary also uses this formula. Existing bounded
history query/replay limits still report unavailability instead of truncated totals.

### Saved-log validation

At **2026-10-19 14:42:43.515014 UTC**, the exact uncommitted pre-change code
reproduced **5,476.1 EXP** (displayed 5,476). Percentage-only progress remained
dependent on diagnostic intervals, and a process restart cleared its baseline.
The first resumed percentage was public-eligible but not progress-eligible.

The new projection uses level 69 (requirement 1,955,750): **65.45% at
14:38:07.930824 -> 66.27% at 14:42:43.515014**, or rounded EXP coordinates
**1,280,038 -> 1,296,076 = 16,038 EXP** across **275.58419 seconds**, about
**209,507 EXP/hour**. The unrounded percentage difference is 16,037.15 EXP;
whole-endpoint rounding explains the sub-one-EXP difference. No EXP digits were
added to the saved percentage-only observations.

The earlier numeric cases remain **16,977 EXP** at 11:28:56.524233 UTC and
**17,175 EXP** at 10:40:56.881611 UTC. Integration regressions verify these three
exact saved histories through player/home APIs, rolling history and selected chart
interval sums, with unchanged raw records and no trusted observations written.
Private fixtures can be skipped when absent; synthetic tests cover their policy
independently. Before/after packets and browser artifacts are under ignored
`private/public-window-simplification/`; older numeric investigation evidence is
under `private/endpoint-window-review/`.

No live database or coordinator is modified. Restart the serving Python process
and refresh the browser to load the calculation and JavaScript. No migration,
re-ingestion or capture restart is needed unless the server shares that process.
This policy trusts the existing selected-character assignment; detecting an
unobserved character switch is outside scope.

### Verification of the simplification

- Full Python run: 2,133 passed, five initial failures, one Windows symlink skip,
  zero private-sample skips. Four failures were old positive-interval/unknown-reset
  expectations, now updated to endpoint net arithmetic. The fifth was the existing
  synthetic worker-timeout cleanup check; it passed alone without capture changes.
- Final affected regression group: **130 passed**, including all five initial
  failures, the three exact CharA windows, multi-level resets, current-level
  filtering, loss handling and incremental/full replay parity. The complete suite
  was not repeated after these test-only expectation updates.
- Frontend Node suite: **90 passed**. Four existing localhost browser checks passed:
  the exact percentage-only replay, saved cross-level/current-level history, saved
  nested totals, and saved level-up progression. Their 46 screenshots and JSON
  verification packets remain private. No remote acquisition was started.

The intermittent worker-cleanup failure is separate from the public gain formula;
no OCR, grammar or acquisition implementation was changed in this task.

## Earlier diagnostic extension (retained)

2026-10-19 MVP follow-up. This extends the existing endpoint collector and bounded
grammar. HUD deduplication, acquisition, level-inference rules, strict parsers,
trusted accounting and UI layout are unchanged.

## Reproduced CharA discrepancy

Inputs are the CharA logs under `private/multi-alpha/runs/`:

- `20261019T095936Z-ef8a3750/streamer_a/8ef13934cb28485ab432854b161f2a4c/capture.jsonl`
- `20261019T103818Z-62816188/streamer_a/capture.jsonl`
- The first run's finalized predecessor supplies its existing rotation context.

Input bytes were frozen under ignored `private/streamer_a-gap-followup/`, with SHA-256
recorded. The replay uses a new isolated store, explicit character/session
assignment and original receipt times, stopping at **10:40:56.881611 UTC**.

The original code returns exactly **9,769 EXP** for the five-minute card, despite
numeric endpoints 371,476 at 10:36:13.027796 and 388,651 at 10:40:56.881611,
both at level 69. The new shared projection returns exactly **17,175 EXP**.

| Previously excluded interval (UTC) | Endpoint-supported gain | Original exclusion |
| --- | ---: | --- |
| 10:36:13.027796 -> 10:36:59.757415 | 1,703 | `multiple_huds` cleared the numeric baseline |
| 10:37:53.329870 -> 10:38:20.326103 | 2,284 | Every unscheduled run boundary was a hard break |
| 10:38:45.166430 -> 10:39:37.332930 | 3,419 | `multiple_huds` cleared the numeric baseline |

**9,769 + 1,703 + 2,284 + 3,419 = 17,175 = 388,651 - 371,476.**

A bounded **read-only SELECT** of the two persisted run bindings confirmed
character ID 1, session ID 1 and the same CharA source identity in
`private/multi-alpha/live-local.sqlite3`. No SQL writes, migrations or
administrative actions were performed. Saved JSONL headers do not contain these
database IDs; matching values were not inferred from level/EXP. The ordinary
configuration pointed to another database containing neither run, so the check
also examined the existing two-stream database. The numerical replay and browser
viewer remain entirely isolated from both databases.
The persisted lifecycle metadata also confirms the prior finalized operator
interruption and the new process start, rather than only a matching source name.

## Narrow accounting extension

`endpoint_pace_v2` / `tracked_endpoint_exp_v4` keeps the existing collector,
nonnegative arithmetic, 300-second inclusive interval limit and whole-interval
lookback membership. The five-minute cutoff is still 10:35:56.881611; no old
endpoint is clamped to that cutoff and no gain is prorated into a window.

A failed `multiple_huds` frame may be treated as a **missed numeric observation**
when saved candidates describe one narrowly overlapping anchor group:

- Two to eight proposals, valid in-frame EXP rectangles and finite geometry.
- HP/MP/EXP anchor coordinates and spacing agree within 5% of the smaller step.
- EXP crops overlap and their edges disagree by at most 10% of that step.
- The record contains no field OCR, numeric candidate or claimed level. It retains
  its failed status, `hud_count > 1` and `current=false`.
- It has a delivered frame/hash, ordered receipt and local age within 15 seconds.

The wider crop tolerance is **only for skipping an unreadable frame**. It does not
choose a crop or declare localization unique. The second CharA failure still
has conflicting EXP rectangles and remains rejected by the active locator.
Separate HUDs, disjoint crops, displaced anchors, missing geometry, invalid
records and stale frames remain barriers. Each candidate pair is checked.

Only independently eligible, same-level **numeric** endpoints may bridge this
new class of gap. Strict or uniquely grammar-recovered arithmetic support is
eligible under the existing MVP policy. Percentage-only endpoints cannot use this
extension. Ordinary existing acquisition/missing-HUD gaps keep their prior policy.

A short interrupted restart may connect only when all of these hold:

- The prior run is explicitly finalized as interrupted, with a final failed
  `operator_interrupted` attempt.
- The new run explicitly starts with `process_start`, at attempt 1, and has a
  different, present coordinator-instance ID.
- Source kind is Twitch, source identity is present and equal, and persisted
  channel, character and session bindings match.
- Both numerical endpoints independently pass the existing freshness, unique-HUD,
  level, grammar, numerical-consistency and duplicate checks.
- Their levels match, EXP does not decrease, percentage progression passes the
  existing continuity gate, and elapsed time is positive and at most 300 seconds.
  The new receipt must also follow the prior interruption timestamp.

This does not make arbitrary restarts, abrupt unfinalized exits, file seeks,
different sessions or unknown identities continuous. Inference and percentage
review still reset at an unscheduled restart; no reader/level confidence is carried
across it. Only the endpoint collector can admit the independently supported net
interval. Its internal evidence records `restart=interrupted_same_assignment`.

The same intervals feed recent totals, pace, rolling history and chart bars.
5/10/15/30/60-minute totals stay nested; strict completed-window/ranking eligibility
is unchanged. All elapsed gap time belongs in the pace denominator: this CharA
example spans 283.853815 eligible seconds. No synthetic intermediate observations
are added. Existing chart allocation within a supported interval is an explicitly
estimated visualization; missing-frame points and percentage-line gaps stay missing.
Hidden loss/recovery inside a gap can only produce observed net movement, not gross
earned EXP or independently established gain timing.
The five-minute rate changes from 222,639.11 to 217,823.39 EXP/hour because its
eligible elapsed time increases from 157.961463 to 283.853815 seconds. More
supported total EXP need not imply a higher rate when missing time is restored too.

One earlier Streamer_F regression now retains an additional **698 EXP**:
31,271 -> 31,969 over 42.447188 seconds, across the same explicitly interrupted
restart pattern. Its 60-minute total becomes 41,926 rather than 41,228; shorter
windows are unchanged. Those source numbers and bindings were checked in the
isolated replay before updating the test expectation.

## Label-tail recovery and independent percentage

Raw `P384,812119.68%1`, run `b607401ffc2948b4b54f612e04dab645:5`, was previously
rejected because the leading `P` prevented numeric-prefix parsing. Existing
`P[90.78%]` handling covered only an entire percentage-only field.

`bounded_exp_v8` removes exactly one uppercase `P` before a numeric field and
reuses the existing bounded interpreter. The example becomes
`384,812[19.68%]`: **384,812 EXP / 19.68%**, compatible with level 69 and the
383,748 / 19.62% and 386,552 / 19.76% neighbors. The original saved EXP crop was
visually inspected and supports these digits and the leading EXP-label remnant;
no OCR model or expected-level digit inference was used.

The recovered 383,748 -> 384,812 -> 386,552 intervals are 1,064 + 1,740 EXP.
Previously the existing collector already bridged the unreadable middle text for
2,804 EXP. Adding this actual reading improves observation coverage without
double-counting or independently increasing that interval's net gain.

Full and percentage hypotheses remain independent. Invalid EXP grouping/range
or an explicit completeness veto can leave only the percentage. A literal `[` can
also preserve a clear percentage after an unreadable EXP token, e.g.
`P384,8SS[19.68%1` yields **19.68%**, with no absolute EXP claim. Without a literal
opener, an uncertain numeric prefix cannot authorize interpreting a digit as the
bracket. Multiple fields, missing percent/decimal digits, arbitrary prefixes,
lowercase `p`, extra label remnants and competing interpretations still abstain.

The original raw text remains intact; label-tail deletion and bracket edits retain
their positions/categories, with the existing four-edit bound. Recovered data
remains unverified and `trusted=false`. Mathematical contradiction and identity
boundaries retain their existing vetoes. Neither strict parser nor legacy v1
proposal behavior was changed.

## Validation and operation

New regression tests cover the exact saved 17,175 versus 9,769 discrepancy,
homepage/player/history API parity, chart interval sums, nested windows, raw-record
immutability, numerical gap streaming parity, wrong source/session/character,
unfinalized/unknown restarts, backwards time, excessive gaps, actual level changes,
EXP loss, stale/duplicate captures, distinct HUDs, malformed geometry, full label
recovery and independent public percentage fallback.

Artifacts, frozen inputs, replay JSON, read-only binding evidence, test logs and
seven localhost browser screenshots are under `private/streamer_a-gap-followup/`.
The existing browser tool used only a new private replay database, with remote
capture disabled. It confirmed the homepage, character page, transparent OBS
overlay and chart render coherently. No existing database or capture archive was
used as a writable replay target.

Restart the website-serving Python process to load the read-time policy and
rebuild in-memory publications/checkpoints. If the coordinator hosts that server,
restart that process; no acquisition setting or OCR environment change is needed.
Existing archived numeric observations can benefit without recapturing the missing
frames. No service was restarted during this work.

Final checks: **2,100 Python tests passed, one OS symlink-permission skip**, with
zero private-sample skips. All **88 Node tests** passed; the new regression module
passes **58 tests**. The existing localhost browser check passed with seven PNGs,
and `git diff --check` passed. The restricted sandbox initially blocked two
loopback tests and Chrome startup; the browser and full suite passed outside that
restriction using only new private replay/test databases. No production behavior
was changed to bypass those test-environment permissions.

Suggested commit:
`fix(tracking): bridge numeric gaps and recover EXP label tails`.
