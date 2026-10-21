# Rolling-window EXP across gaps

`public_endpoint_window_v2` replaces earliest/latest net subtraction. The existing
website layout, colours, controls and observation graph points are unchanged. No
broadcast tracking, OCR/identity changes, schema migration or background service was
added. Calculations read existing saved observations; no re-ingestion is needed.

## One rule for gains and rates

For each selected character, use consecutive valid EXP/level endpoints in capture
order. An interval contributes its **whole nonnegative gain** when:

- Its later timestamp is within the selected window (inclusive boundaries).
- Its positive duration is no greater than that window's duration.
- Both endpoints have the same known character ID and compatible manual baseline.
- Existing reading, numerical, level and identity checks allow both endpoints.

The older endpoint may be before the window. There is no interpolation, prorating or
invented intermediate reading. Use numeric EXP when available; otherwise round each
displayed percentage's level-based EXP estimate to whole EXP, as before. Across
levels, add the known requirements from the old level through the new level minus one.
An unknown transition requirement excludes that interval, not independent valid
intervals elsewhere in the window.

**EXP/hour = eligible gain total × 3600 / selected window seconds.**
This applies to 5/10/15/30/60-minute rates and the 24-hour rate exposed in rolling
history's `windows["1440"]`. Observed coverage/span remain actual endpoint durations;
they are not the denominator. Coverage can exceed a window when its first qualifying
interval crosses the boundary. ETA uses the same normalized positive rate; existing
dated historical estimates and pause presentation remain separately marked as before.

| Observations at 10:20 = 30%, 10:50 = 40%, 11:00 = 42%; queried at 11:00 | Gain | Rate |
| --- | ---: | ---: |
| 5m | unavailable: no interval fits 5m | unavailable |
| 10m | 2 percentage points | 12 points/hour |
| 15m | 2 percentage points | 8 points/hour |
| 30m | 12 percentage points | 24 points/hour |
| 60m | 12 percentage points | 12 points/hour |
| 24h | 12 percentage points | .5 points/hour |

For 30m, the 30-minute interval ending at 10:50 counts even though it starts before
10:30. The 10-minute interval ending at 11:00 also counts. Displayed EXP rounding can
cause sub-one-EXP differences from multiplying the percentage-point change directly.

## Identity, losses and invalid evidence

Internal session, run, restart and source identifiers do not themselves erase gain
between reliably associated endpoints of the same character. Character IDs are
Store-global and remain scoped to their streamer. Old persisted `character:session`
accounting scopes are read compatibly; their character component must match. No IDs
or histories are merged. Automatic ownership holds and persistent level floors still
run before attribution; this change cannot release their nested numeric evidence.

Manual corrections remain subtraction barriers: setting a new baseline is not earned
EXP. A same-level EXP decrease contributes no positive gain and starts the next
interval's baseline. For example, 100→90→95 contributes 5, not -5 or 0, when both
intervals otherwise fit. It is **earned positive progress**, not net balance after
losses/death penalties. This is necessary for shorter-window totals never to exceed
longer-window totals. Level decreases remain excluded; character level guards were
not changed.

Absent, stale, ambiguous, simulated, invalidated and unsupported endpoints cannot vote
as valid coordinates. Unusable observations do not erase the last usable endpoint;
the duration test still applies to the resulting gap. Duplicate source captures are
excluded using the existing collector, and late/out-of-order observations cannot move
the subtraction baseline backwards or cause overlapping gains. Observations with
unknown identity cannot establish a cross-session gain.

## Replay, retention and bounded work

24h queries may need an endpoint almost **48h** old: an interval can last 24h and end
near the beginning of the current 24h window. Replay reads a bounded 48h plus context;
recent 60m projections use two hours plus context. Existing run/event/byte ceilings
still return `history_limit` rather than partial totals.

The existing retention checkpoint already retains the last usable endpoint before
the raw prefix is deleted. It is sufficient to calculate the next crossing interval;
no longer footage/raw retention or new daily sampling is introduced. Frozen prefix
endpoints retain their original character and manual provenance. Incremental and cold
replays use the same rules; calculations do not alter the database.

A gap **greater than 24h** contributes nothing even to 24h gain. Exact 24h is eligible.
The latest identity/level/EXP remains available from existing persistent state. Unknown
time is clamped at zero because boundary-crossing coverage can exceed the lookback.
Bars continue to associate eligible gain with its real later observation, without
spreading progress through missing time or adding observation points. The existing
renderer recognizes the new policy and keeps the same bar style; only its eligibility
rule and existing explanatory tooltips changed. No layout or new indicators.

The cache's expiry check now uses the latest endpoint leaving the window; the old
"start before window" condition would continuously rebuild a valid crossing interval.
Other rolling changes still refresh on the existing bounded cache cadence.

## Verification and limitations

The recovery-tool follow-up also corrected remaining player-card help: EXP/hour uses
eligible gain over the selected window duration, and verified same-character gaps
may cross sessions. Complete-window comparison help retains its separate coverage
requirement. These are tooltip-only changes; calculations/layout are unchanged.

`tests/test_rolling_gap_windows.py` covers the requested example, all six duration
boundaries, inclusive window edges, duplicates, missing evidence, monotonic timestamp
handling, character/manual boundaries, losses, known/unknown level transitions,
session changes, restart, a >24h return, retained latest state and a crossing interval
whose old endpoint was actually pruned. A deterministic sparse/loss sequence check
asserts nested totals across 100 sequences. Existing regression expectations now use
selected-duration rates, whole crossing intervals and positive progress after losses.

Final focused run: **73 passed, 4 private-fixture skips**. Broader regression:
**2,481 passed, 120 skipped** (118 unavailable private fixtures, one OS symlink
restriction, one existing loopback restriction). One additional concurrent-viewer
loopback test was excluded because this sandbox forbids client sockets. Frontend:
**57 passed**, zero skips. The earlier affected group passed 468 checks before a
new cache test's timestamp argument was corrected; the final runs include that fix.
`git diff --check` is clean.

```powershell
python -m pytest -q tests/test_rolling_gap_windows.py tests/test_public_window_formula.py tests/test_tracked_exp_totals.py
python -m pytest -q -n 8 -k 'not test_concurrent_viewers_share_one_projection_per_publication'
node --test tools/product.test.mjs
```

In this Windows sandbox TEMP/TMP pointed to an ignored workspace temp directory;
tests and SQLite files remained disposable. No browser automation was needed for
unchanged layout/CSS; frontend unit tests verify later-endpoint bar placement and no
intermediate bars for gaps.

Known limits: identity depends on the existing writer's character association; this
does not detect an unobserved same-level character switch. Requirements remain
provisional. If old raw history was already removed without a usable checkpoint,
missing endpoints cannot be reconstructed. High-volume histories can hit existing
bounded replay limits. No Twitch/VPS/live-database operation was performed.

Suggested commit: `fix(accounting): count validated gaps consistently across rolling windows`.
