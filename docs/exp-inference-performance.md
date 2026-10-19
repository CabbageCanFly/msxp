# Exact interval search for EXP-derived levels

Fixes the cold-replay regression from `feat/exp-level-inference` recorded in
[card projection](card-projection.md). Inference policy, outputs, caches and callers are
unchanged; only how compatible levels are found changed.

## Root cause

`project()` calls `_exp_derived(exp, percentage)` once per row. On a cache miss it ran
`infer_levels()` under both rounding hypotheses. Each call validated the table, then ran
`assess()` for all 89 supported levels, re-parsing the percentage every time:
≈186 `assess()` calls and ≈330 µs per pair. Every capture is a new pair, and the
4,096-entry LRU is smaller than one day (4,321 rows). A second sequential replay of the
same rows (24h, then recent) therefore missed on every row. A repeated replay was even
slower than a cold one.

## Exact candidate filtering

With n = 10000·EXP and displayed basis points bp, `assess()` reports *consistent*
exactly when EXP < T and its integer rounding of n/T equals bp. Solved for T:

| Hypothesis | Condition | Integer interval for T |
|---|---|---|
| truncate | bp·T ≤ n < (bp+1)·T | ⌊n/(bp+1)⌋+1 … ⌊n/bp⌋ (no upper bound at bp = 0) |
| nearest half-up | (2bp−1)·T ≤ 2n < (2bp+1)·T | ⌊2n/(2bp+1)⌋+1 … ⌊2n/(2bp−1)⌋ (none at bp = 0) |

The lower bound is then raised to EXP+1. Levels are selected by bisecting a
(requirement, level) index sorted **by requirement value**, then reported in level order.
Requirements need not increase with level, and duplicate requirements stay separate
levels (ambiguous). Integer arithmetic only. `displayed_bp()` is the parse `assess()`
already used, now shared, so invalid, non-terminating and out-of-range percentages behave
identically.

`infer_levels()` keeps its full per-call table validation for public callers.
`_exp_derived()` validates and indexes the community table once
(`requirement_index`) and calls the same core (`infer_indexed`). Coverage
(`outside_supported_coverage`, including every 0.00% and pairs that could need a
disputed 90–99 or missing 100+ requirement), status and unique-level rules are untouched.

## Parity

`tests/test_exp_inference_parity.py` keeps the previous implementation verbatim as the
reference and compares complete outputs:

- Every supported requirement, both hypotheses, EXP at, below and above each truncate
  and half-up boundary for 16 displayed values from 0.00% to 100.00%, plus EXP 0, T−1,
  T, T+1 and 2T. Each requirement alone (>50,000 cases per hypothesis), then the whole
  table at every 8th requirement's boundaries.
- Unsorted non-monotonic, duplicate-requirement, single-level and disputed-extended
  (90–99) tables.
- 210 invalid or unusual input combinations: None, negative and over-long EXP, bool,
  float, Decimal, NaN, infinity, three decimals, comma, empty, over 100%, unhashable.
  Bad tables and modes still raise.
- `_exp_derived()` complete results for every saved Emmies, Niru and Telfer1 pair plus
  synthetic boundary pairs, with the reference patched in (call count asserted). These
  cover unique, ambiguous, incompatible and outside-coverage statuses.

All exact. The existing level-inference, product, cross-level, tracked-EXP, incremental
history and card parity suites also pass.

## Measured (full-day synthetic channel, 4,321 rows, CPU, best of 3, cache cleared)

| | Pre-merge `b139519` | Post-merge | Now |
|---|---:|---:|---:|
| `_exp_derived` cache miss | — | ≈330 µs | 19.5 µs |
| `infer_levels`, both hypotheses (public, validating) | — | 316 µs | 43 µs |
| Cold 24h replay | 812 ms | 2,172 ms | 781 ms |
| Cold recent replay | 594 ms | 3,625 ms | 641 ms |
| Repeated 24h replay | 797 ms | 4,391 ms | 812 ms |

Memory: one cached index per distinct table (≤16 entries; one in practice, ≈90
entries). The `_exp_derived` LRU is unchanged at 4,096 entries. A miss is now cheap, so
its thrashing during sequential replays no longer matters.

## Remaining cold-start limits

Cold replay is back to pre-merge cost, ≈0.8 s per full-day channel per projection. That
is still a whole-session replay per channel after a process restart or checkpoint
invalidation, ≈18 s at 5 channels and ≈37 s at 10 in the earlier homepage measurements.
Avoiding it needs persisted or background-built checkpoints, not numerical changes.
