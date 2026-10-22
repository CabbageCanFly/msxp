# Fast last-seen summaries for every character

Status: brief investigation and proposal, 2026-10-22. No implementation or
deployment is included in this note.

## Finding

Every character should have a cheap, dated summary available independently of its
charts and rolling-window calculations. Online/offline status should not determine
whether that summary is cached.

The current delay comes from preparing a complete historical publication before
returning the character's EXP. It does not establish a low SQLite capacity ceiling.
Actual concurrent-viewer capacity on the VPS remains unmeasured for this workload.

## What already exists

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

The earlier suggestion that inactive characters have no persistent caching was
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
