# Cheaper player cards: exact reuse, not new numerical policy

Follow-up to [incremental history](incremental-history.md). `Diagnostics.card()` is the
per-channel computation shared by the homepage and character API. This change removes
repeated work inside it. Every public value is unchanged: optimized output must equal an
unoptimized full-replay reference.

## Profile (one full-day synthetic channel, warm history checkpoints)

A card rebuild was a fresh `snapshot(limit=640)` (decode, from-scratch `project()`,
percentage `progress()`) plus `player()`. One rebuild parsed the same ≈640–835 OCR texts
≈10,000 times. It projected the 640 rows twice: `observed_sequence()` re-projected the
snapshot's already-projected rows. It collected recent intervals twice, once per
`recent_windows()` scope. It also computed `level_events` for the snapshot only to
overwrite it with the recent rows' events.

## Changes

| File | Change | Why it is exact |
|---|---|---|
| `shadow_grammar.py` | `interpret_exp` memoized (`lru_cache`, 4,096 entries) for str/None text and bool/None completeness; other inputs bypass the cache | Pure function of its arguments; every consumer reads the result and builds new dicts |
| `diagnostic_evidence.py` | `project()` returns a `Projected` list when run from scratch with context | `project()` never reads `experimental_level`/`exp_validity`, the only fields it writes, so re-projecting returns equal rows |
| `product.py` | `observed_sequence()` reuses a `Projected` list instead of projecting again; `player()` shares one `collect()` between the all-level and current-level windows and skips the overwritten `level_events` | Same rows, clock and interval limit; `responsive_pace` only builds local lists |
| `tests/test_card_projection.py` | Parity against a reference mode with all three optimizations disabled and no checkpoints | — |

A slice or a stateful (checkpointed) projection is a plain list and is still re-projected.

## Parity

The whole `card()` entry is compared: the card with its player, plus chart history and
lifecycle extras, and `refresh()` of the player. That covers displayed EXP and level,
last-known state, recent-window gains, EXP/hour and ETA for both scopes, complete-window
comparisons, early and responsive pace, level-up events, quarantine state and the chart.

- Synthetic: after **every** append across rotation, manual restart, duplicate frame,
  loss and recovery, level-up and source change, then +1 s, 11 s, 5 min, 1 h, 65 min and
  24 h without new captures. Exact.
- Saved Emmies, Niru and Telfer1 logs: every 80 streamed records and at +0 s, 11 s,
  65 min and 25 h. Exact. (A 40-record stride was also run once, exact.)
- The grammar memo equals the parser for strict, recovered, symbol, empty, None, over-long
  and unhashable inputs under every completeness value.

## Measured

Full-day fixture (4,321 attempts), CPU time per card rebuild, median of 7, memo cleared:

| Rebuild | Before | After |
|---|---:|---:|
| New capture | 531 ms | 344 ms |
| Time-only (10-second expiry) | 500 ms | 344 ms |

Short homepage run (`benchmark_homepage.py --channels 1 5 10 --repeat 3 --viewers 20
--seconds 20`). The previous run predates both this change and the
`feat/exp-level-inference` merge, so only steady-state rows compare cleanly:

| Channels | Homepage, one new capture | Homepage, all new | Character, new capture | 20 viewers (completed / timed out), previous → now |
|---:|---:|---:|---:|---|
| 1 | 584 → 602 ms | 614 → 567 ms | 657 → 654 ms | 297 / 0 → 187 / 0 (20 s instead of 30 s) |
| 5 | 754 → 500 ms | 2,385 → 2,320 ms | 667 → 498 ms | 191 / 0 → 163 / 0, p95 3.7 → 2.1 s |
| 10 | 694 → 1,541 ms | 3,058 → 2,692 ms | 593 → 455 ms | 82 / 39 → 92 / 15 |

The one-new-capture row includes 10-second expiry rebuilds of other channels, so it is
noisy. The card CPU measurement above is the controlled comparison.

### Cold start regression from the EXP-level inference merge (not this change)

Resolved by [exact interval search](exp-inference-performance.md); cold replay is back to pre-merge cost.

Cold replays became ≈3–7× slower after `feat/exp-level-inference`. On the same fixture,
CPU best of 3: 24h replay 0.8 → 2.2 s, recent 0.5–0.6 → 3.6 s. This change is neutral:
reference ≈ optimized. `project()` calls `_exp_derived(exp, percentage)` per row; a cache
miss runs `infer_levels`, ≈1 ms and ≈185 `assess` calls per row. Every capture has a new
pair, and the 4,096-entry LRU is smaller than one day (4,321 rows). A second sequential
replay of the same rows therefore misses every time. Steady state is barely affected
(≈1 ms per new capture). Cold start and invalidation rebuilds are: 10 channels now take
≈102 s cold instead of ≈37 s. Options for that feature's owner: a cheaper exact
`infer_levels` (only levels whose requirement can match the displayed percentage), or a
cache sized to the replay working set.

Memory: the grammar memo holds ≤4.9 MiB process-wide when full; no per-channel state
was added.

## Remaining cost and next step

What remains (≈340 ms CPU per rebuild) is real numerical work: decoding and projecting
the 640-row window from scratch (≈40%), interval collection and pace over both views
(≈27%), percentage segments (≈19%) and complete-window comparisons (≈11%).

Making these incremental is not a cache. The 640-row window is projected from scratch
and slides by one row per capture, so an early row's level context can change. Progress,
pace and window comparisons each depend on the clock. Each would need its own
checkpointed state and parity proof, like `rolling_history.replay()`.

Higher leverage first:

1. **Background publishing.** One refresher thread rebuilds each due card once
   (revision or 10-second expiry), cheapest first, and publishes immutable snapshots.
   Requests only read the latest snapshot, `refresh()` it and serialize it. The homepage
   body can be serialized once per publish for every viewer. This caps rebuild CPU
   independently of viewer count and removes request-side rebuild budgets and lock waits.
2. **Then decide on incremental pipelines**, using measured refresher utilization. At
   ≈0.34 s per rebuild and roughly two rebuilds per 20-second capture cycle, one core
   supports ≈30 active channels before the refresher falls behind.

For a later dedicated run (≈30–40 min):
`PYTHONPATH="src;tools" python tools/benchmark_homepage.py --directory private/<new> --channels 1 5 10 25 --viewers 20 --seconds 30`
