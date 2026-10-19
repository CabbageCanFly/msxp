# Homepage and character API performance at 1–25 channels

Investigation only; no server, cache or history code was changed. Results are
**synthetic local latency**, not acquisition throughput or a VPS capacity claim.

## Method

`tools/benchmark_homepage.py` writes one 24-hour channel (4,321 attempts every 20s,
73 scheduled-rotation runs, consistent level-64 EXP/percentage pairs) through the
normal `Diagnostics.begin/rotate/append` path, then clones it with SQL into 1, 5,
10 and 25 channels in fresh `private/` databases. An in-process read-only server is
timed over HTTP. New captures are real appends at the current clock; Twitch, OCR
and live databases are never touched. Lock wait/hold time and time inside
`directory`, `recent_snapshot` and `rolling_history` are measured by wrappers.
Every run asserts nested tracked totals for every channel and that recomputed
packets carry the response's `served_at` as `tracked_as_of`.

```powershell
$env:PYTHONPATH='src;tools'
.\.venv\Scripts\python tools/benchmark_homepage.py --directory private/homepage-bench-01
```

## Results (Windows 11 desktop, Python 3.14, one process)

| Channels | Cold `/api/players` | Repeat, no writes | One channel new | All channels new | Character API, no writes | Character, other channel busy |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2.5 s | 17 ms | 3.1 s | 1.6 s | 0.82 s | — |
| 5 | 8.5 s | 31 ms (max 4.2 s) | 1.7 s | 8.4 s | 0.87 s | 1.6 s |
| 10 | 16.8 s | **8.4 s** | 1.7 s | 16.2 s | 0.84 s | 1.6 s |
| 25 | 41.8 s | **60.4 s** | 41.7 s | 42.0 s | 0.84 s | 1.6 s |

Each changed channel costs ≈1.6 s: ≈0.8 s for its 24h `rolling_history` replay and
≈0.8 s for its homepage card (≈0.6 s of that in `recent_snapshot`). The same 65-minute
`recent_snapshot` costs ≈25 ms for a 3-run (181-attempt) chain and ≈590 ms for the full-day
chain. One 24h replay issues ≈1,170 SQL statements, but `sqlite3.execute` is only ≈0.1 s
of it; the rest is Python projection, review and interval collection (profiled).

The nested invariant and `as_of` assertions passed at every channel count. The 25-channel
5/10-minute windows were correctly unavailable by then: the synthetic history had aged
past the 300-second endpoint limit, and only a few new attempts existed.

## Bottlenecks

1. **Replay cost grows with uptime, not with the window.** `run_batches` follows the
   scheduled-rotation chain back to the session start for causal level/quarantine state.
   So both the 65-minute `recent_snapshot` and the 24h aggregate replay the whole
   continuous session on every recompute. The work bound (1,024 runs/65,536 attempts) is
   reached after ≈14 days of continuous 20s rotation; history then becomes unavailable.
2. **Every new capture invalidates a full replay.** `Handler.tracked()` keys on the
   latest attempt ID and the directory cache on each session's latest attempt, plus a
   10 s `history_due` expiry. At 15–30 s cadence an active channel is recomputed on
   nearly every homepage poll; the 30 s TTL never helps.
3. **The homepage is serial and exceeds the browser timeout.** `/api/players` holds
   `directory_lock` while it builds each card and calls `tracked()` for every channel.
   `product.js` aborts that fetch after 5 s and repolls 2 s later. From about 4
   full-day channels changing at once, the homepage never renders. Aborted requests
   keep running and queue on `directory_lock`. At 10+ channels even "warm" repeats
   recompute, because one response outlasts the cache expiry.
4. **Character API is uncached and shares one global lock.** Each 2 s poll rebuilds
   `snapshot` and `recent_snapshot` (≈0.85 s, under the global `history_lock`). An
   unchanged channel's page takes ≈1.6 s while another channel's history replays. The
   wait is mostly GIL CPU sharing with the replay, so a finer lock alone would not fix it.

SQLite isolation itself is not the problem: readers use WAL snapshots and
`history_lock`/`directory_lock` showed no measurable wait in the sequential runs.

## Recommended next milestone: incremental causal checkpoints

This needs review first, because it changes how history is cached.

1. Per (channel, selected character), cache the streaming state already used by
   `project(state=)`, `review(state=)` and `collect(state=)`. Store it with the last
   processed attempt ID, the accepted interval list and the bucket sums. On a new
   revision, process only attempts with a greater ID. Prune intervals by the moving
   24h start. Fall back to a full replay on a character/session change, a non-append
   revision (lower ID, summary rewrite), a clock regression or any limit.
2. Let `recent_snapshot` reuse the same checkpoint instead of replaying the chain.
3. Add a parity test: for every prefix of the saved Emmies/Telfer/Niru replays and the
   rotation/restart/quarantine fixtures, incremental totals, buckets, windows and ETA
   inputs must equal a full replay exactly.
4. Then, if still needed, serve the last completed `/api/players` body with its real
   `served_at` while one refresh runs, instead of queueing requests behind
   `directory_lock`.

Expected effect, untested: a new capture costs one row of processing (≈0.2 ms per row
today) instead of ≈1.6 s. Measure again with this tool before and after.
