# Fast last-seen summaries for every character

Status: investigation and local implementation, 2026-10-22. No deployment.

## Finding

Every character should have a cheap, dated summary available independently of its
charts and rolling-window calculations. Online/offline status should not determine
whether that summary is cached.

The current delay comes from preparing a complete historical publication before
returning the character's EXP. It does not establish a low SQLite capacity ceiling.
Actual concurrent-viewer capacity on the VPS remains unmeasured for this workload.

## Baseline before this change

| Existing mechanism | Coverage and limitation |
|---|---|
| Lightweight roster | Returns character names, level context and sighting timestamps without building each character's profile. It does not return EXP. |
| Selected-character publications | Background publisher builds and shares cards, history and tracked totals across visitors. |
| Inactive-character publications | Built on demand; eight views fit in memory, idle views stop refreshing after 60 seconds and are retained for 30 minutes. More distinct views can cause eviction and rebuilding. |
| Persistent publication cache | With `--publication-cache`, both channel publications and inactive views can survive API restarts. Compatible entries are restored only within 24 hours of their build time. |
| Replay checkpoints | Recent/24h calculations reuse settled prefixes. Explicit character IDs are already supported. The persistent save/restore path currently targets the selected channel entry's checkpoints. |
| Retention display | Pruning preserves a compact, dated per-character reading, level and last numerical EXP indefinitely. This is already persistent display state, but it is created during retention maintenance. |

Sources: [publisher](../src/exp_tracker/publisher.py),
[publication cache](../src/exp_tracker/publication_cache.py),
[roster and cards](../src/exp_tracker/diagnostics.py),
[replay](../src/exp_tracker/rolling_history.py),
[retention](24h-retention.md), [restart recovery](restart-recovery.md).

The earlier suggestion that inactive characters had no persistent caching was
too broad. The gap is an immediately readable summary maintained for every
character, separate from the lifetime and cost of a complete publication.

## Observed example

In the local database, Jakers' saved reading was available at **68.35%**, with a
percentage-derived estimate of approximately **1.41 million EXP**. A standalone
read-only rolling-history calculation took approximately **0.19 seconds** on this
Windows machine. That measurement excludes publisher queueing, network time and
VPS contention; it is not a production latency benchmark.

The screenshot's name and level came from roster data while the full profile was
still preparing. Cold selected-channel publications currently take priority over
inactive views. The user confirmed the view eventually loaded after a short wait.

## Smallest practical design

1. Persist a compact summary whenever the API publisher successfully projects a
   character's validated state. Preserve it when that character becomes inactive.
   Reuse the existing API-owned, disposable cache database first; keep the tracking
   database read-only in the API process.
2. Return that summary alongside the lightweight roster so the selected character's
   name, level, EXP bar and original reading time can display while history loads.
   Label the history as preparing independently.
3. Keep full history and rolling totals bounded, shared and on demand. Consider
   fairer startup scheduling separately if measured queueing remains a problem.

A summary needs the character ID, a coherent accepted reading with its timestamp
and evidence, separately dated level context, and source/operator revisions.
Reuse the existing projected reading shape, including nullable numerical EXP and
labeled percentage-derived estimates. Do not invent another OCR acceptance path.

Existing characters without a summary need one bounded background build or a
retention-display seed. A brand-new cache cannot promise instant EXP for every
previously unseen character. Eagerly replaying all characters on every startup
would move the same cost into startup.

## Correctness and invalidation

- Failed attempts must not erase the last accepted display or advance its reading
  timestamp. A roster sighting time is not necessarily an accepted EXP timestamp.
- Keep each character's state independent across switches and restarts. Never join
  an older numerical EXP value to a newer percentage or a different level.
- Corrections, clears and invalidations must invalidate affected summaries before
  serving them. Renames must update displayed identity. Use existing revisions and
  compatibility rules; code changes can require rebuilding disposable summaries.
- A summary's observation age alone should not evict it after 24 hours. Chart and
  rolling-total freshness remain separate. Account for retention revisions without
  discarding the only preserved display after source attempts have expired.
- Display summaries never supply new accounting endpoints or imply current pace.
  Missing source data and replay safety limits remain explicit limitations.

## Focused verification before rollout

Use synthetic databases to check character switches, percentage-only readings,
long inactivity, failures, cold cache restoration, pruning, corrections and clears.
After summaries exist, assert that basic-summary requests perform no raw-history
replay. Check that concurrent requests share one build and that cache eviction does
not lose the durable summary. Measure cold/warm latency, replay counts and CPU on
representative offline profiles before claiming a VPS capacity improvement.

No new service or external cache is justified by the evidence gathered so far.

## Implementation (2026-10-22)

The homepage Characters list now shows each character's EXP bar and 24 h chart from an
in-memory summary that the publisher records whenever it builds a character: the
selected character on every channel refresh, and inactive characters as views or as
summary-only builds. A summary keeps the projected reading and 30 min buckets and is
withheld once the channel's manual-correction or invalidation revision changes. A retention
revision change (a fold, which changes no shown value) keeps it on show until it is rebuilt;
restored copies still need every revision to match. When
served, its chart slides forward by whole 30 min buckets since the build (nothing was
tracked meanwhile); the list's "today" total is the sum of the remaining buckets.

Inactive characters without a usable summary, or seen after it was built, are built in
the background at most one per `SUMMARY_SECONDS` (5 s), after cold and requested channels
but before routine refreshes and views, never by requests or in inline mode. They were
once built only when nothing else was due; with 28 channels refreshing every 30 s on a
busy VPS something always was, so those rows showed "Loading EXP…" indefinitely
(`character_demo.py serve --slow 8` reproduces it locally). These builds do not occupy an in-memory view
slot. With `--publication-cache`, their already-computed full reports are saved as
inactive views instead of being discarded, and compact summaries are saved separately
in that same disposable cache database. No tracking schema or writer change is needed.

On API startup, compatible summaries restore with source fingerprints, per-character
attempt revisions and operator/retention revisions checked. Unlike full reports,
their original dated readings do not expire after 24 hours. Their chart buckets do
age out. Code changes or changed source data still require rebuilding; the cache
does not replace retained source/display state or recover deleted observations.

A warming profile response remains HTTP 503 with `error = "warming_up"`, but may
also carry its roster and summary. The page immediately shows that character's
saved EXP bar, original reading date, 24h total and 30-minute bars while detailed
history prepares. Shorter charts, current-level filtering, pace and ETA wait for the
full report. Basic summary responses read publisher memory, never replay history or
read the disk cache on the HTTP thread. The Characters list dates EXP using the
reading timestamp; a newer failed capture cannot make old EXP look freshly read.

Full inactive reports restore on the existing worker after a profile is requested,
including after its memory slot is evicted. They retain the existing 24h age limit,
revision checks and eight-view memory bound. A retention fold alone keeps an open view
on show and only makes it due. Background summary work stays rate-limited; an empty cache
still needs an initial build for each character.

The existing `deploy/msxp-api.service` already supplies `--publication-cache`.
An operator can check the installed command without changing it:

```bash
systemctl show msxp-api -p ExecStart --no-pager
```

After review, this change needs the API code restarted and the updated frontend
published. A split `msxp-tracker` capture process does not need restarting for these
files. No service, production database or deployed website was changed here.

Validated locally with synthetic fixtures: durable summaries, background report
reuse, memory eviction, long inactivity, original reading dates, correction/clear,
invalidation, retention and source/code changes, and frontend loading behavior.
Unmeasured: VPS latency/CPU and concurrent-viewer capacity. A retention-display seed
and broader checkpoint work remain outside this change.

## Missing EXP after long capture failures (2026-10-22)

Janet's VPS response had nonempty 24h totals but no reading, with
`recent_history.eta_status = "history_limit"` after 4,486 attempts. The historical
ETA replay exceeded its 4,096 retained-row limit and returned no compact display.
The publication cache could only preserve that empty result; caching was not the
cause of the missing reading.

Historical replay now drops its oversized ETA/chart row buffer, keeps those
calculations explicitly limited, and continues causal validation to maintain the
compact last accepted display through the complete bounded stream. It does not
guess EXP from gains, promote failed frames, or increase any replay budget. Global
run/event/byte limits still withhold incomplete replay; operator clears and
invalidations still apply to the display.

Roster `last_seen_at` now requires a current, acquired frame with one HUD and no
identity hold. Failed/offline polls do not advance it. After retention, the fallback
comes from the saved reading/level timestamp rather than the last attempted capture.
The independent attempt revision still advances so cache invalidation works normally.

Synthetic regressions cover 4,200 failed attempts after full and percentage-only
readings, valid readings arriving after the ETA limit, operator clear, and sightings
before and after retention. No production database change or migration is needed;
the split deployment needs only the updated API restarted after review.
