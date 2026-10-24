# Background snapshot publishing

Follows [incremental history](incremental-history.md),
[card projection](card-projection.md) and
[EXP-level search](exp-inference-performance.md). Public HTTP requests no longer compute
cards, replay history or call Twitch. Every statistic keeps its meaning; only *when* and
*where* it is computed changed.

## Architecture

`src/exp_tracker/publisher.py`: one `Publisher` per server process.

The optional [restart recovery integration](restart-recovery.md) restores dated
publications and validated replay checkpoints from a separate disposable cache.
Its capture-only service also lets this API/publisher keep running across capture
restarts. Without those opt-in options, the cold-start behavior below is unchanged.

**Refresher.** `python -m exp_tracker.server` runs a single daemon thread. Each step:

1. reads channel heads (selection, open session, latest run and attempt) and the latest
   source kind, in one read transaction;
2. refreshes Twitch status through the existing `StreamAvailability` cache (network at
   most once a minute, now never inside a request);
3. builds **at most one** due channel, then loops while work remains; idle, it waits
   ≤1 s or until woken.

A channel's card (`Diagnostics.card`: 640-row snapshot, recent view, `player()`) and its
tracked-EXP packet (`rolling_history`, checkpoint resumed) are built **in one read
transaction at one clock** and published together as one immutable entry:
`key` (head revision), `built_at`, `card`, `extras` (chart history, lifecycle) and
`tracked`. Entries are swapped under a lock and never mutated afterwards. The checkpoint
store, card cache and historical-ETA cache are now used only by the refresher.

**Priority and fairness.** Due channels are ranked:

1. cold channels a viewer is waiting for;
2. other cold channels;
3. changed revisions, and entries at least 30 s old, together, oldest publication first;
4. other time-only expiries, oldest publication first.

An entry expires on the unchanged `Diagnostics.due` rule: rolling windows that can still
age, rebuilt after 10 s. Tracked windows are refreshed every 30 s, as the former request
cache did. With many live channels something is always expiring. Ranking new captures
ahead of those 10 s expiries keeps a new reading from queueing behind them; before, viewers
received two or three captures at once. An expired entry joins the new captures once it is
30 s old, so a continuously changing channel cannot repeatedly outrank an older due
publication. Cold-start work grows with the visible roster; there is no fixed
channel-count publication limit.

**Shared window work.** One `recent_windows` pass (5 min to 24 h, current and basis
clocks) used to re-sort and re-evaluate every pair of the day's endpoints for each window.
`window_endpoints(memo=)` keeps one sorted order and each pair's interval for calls over the
same unchanged points; results are identical (`tests/test_window_endpoints_memo.py`).

Measured 2026-10-24, Windows workstation, synthetic full-day channels
(`tools/benchmark_homepage.py --channels 10 20 --viewers 40 --seconds 90`), capture to
published entry:

| Channels | p50 / p95 / max, before → after | Captures still unpublished at end | Mean build |
|---:|---|---|---:|
| 10 | 6.3 / 12.4 / 13.5 s → **1.6 / 3.6 / 6.2 s** | 3 → 0 | 1.09 → 0.75 s |
| 20 | 25.4 / 41.2 / 42.2 s → **22.6 / 24.8 / 25.7 s** | 19 → 10 | 1.69 → 1.47 s |

At 20 channels the refresher is still saturated (≈88 % busy): one capture per channel per
20 s needs more builds than one process completes. Oldest-entry age p95 at 10 channels rose
13.9 → 27.9 s, as intended, because time-only refreshes now wait up to 30 s; ages are still
presented honestly. Untested on the VPS.

**Presentation.** Requests only time-present published entries:

- `refresh()` for ages, staleness and activity;
- `present_card()` (the homepage card presentation, now shared with `/dev/api/streams`);
- `tracked_statistics()`;
- the Twitch status merge;
- JSON encoding.

The encoded body is reused for every viewer while the publication generation, the
coordinator runtime (activity, active runs) and the clock (< `PRESENT_SECONDS` = 1 s)
are unchanged. One lock per body key means simultaneous viewers wait for one encoding
instead of repeating it.

| Endpoint | Request work now |
|---|---|
| `/api/players` | Cached bytes, or one presentation of all published entries per second |
| `/api/players/{ch}` | Cached bytes, or one presentation of that entry per second; chart history and tracked packet omitted while the page holds their [revisions](vps-readiness.md#conditional-character-history) |
| `/api/players/{ch}/history` | Cached bytes of the published tracked packet |

All three present the entry's [public projection](vps-readiness.md#public-projection),
made once per build.

**Streamers list projection.** `/api/players` then keeps only what the list reads
(`publisher.board()`): the reading and level, the 5–30 min pace, ETA and eligibility, the
24 h total and mini chart, and Twitch status. Estimates carry their values without the
evidence behind them. Profiles and overlays still get everything from `/api/players/{ch}`.
Measured 2026-10-24 on the live 36-channel reply: 1,883 KB → 165 KB raw, 131.5 → 15.8 KB
gzipped. Rendering the board from the full and the projected reply gave identical output in
all 36 sort, window and online-filter combinations. The list now polls every 4 s, or every
30 s while its tab is hidden; profiles and overlays keep 2 s.

Moved out of requests: card rebuilds, 24h/recent history replay (cold or resumed), the
Twitch Helix lookup, and the latest-source query.

**Inline mode.** `create_server(..., background=False)`, the default for tests and replay
fixtures, settles all due work on each request through the same code. Results are
deterministic under pinned clocks. `main()` uses `background=True`.

## Consistency and freshness rules

- A published entry's card and tracked packet come from one database snapshot. If a
  capture commits between the head query and the build, both include it and the next
  step republishes with the new key.
- Card timestamps (`recent_as_of`, reading and attempt times), tracked `as_of` and
  `served_at` stay distinct. `pace_as_of` is now the card's computation time instead of
  the serving time; nothing consumed the old value.
- A body is reused for at most 1 s of as-of clock. Ages are presented at the body's
  `served_at`, never later, and an old reading is never shown as freshly observed.
- New capture to visible API: ≈1–1.5 s for one channel (idle poll plus one build).
- **Cold start:** the first homepage lists ready players plus `warming: [channels]`.
  Character requests for an unpublished channel return `503 {"error": "warming_up"}`
  with `Retry-After: 2`, and that channel moves to the front. The page says "Preparing
  saved history…" instead of "Tracker unavailable". An unknown channel is still 404.
- **Failures:** a failed channel build keeps the last entry, served with its real ages.
  It retries after 5 s, then 10, 20 and 40 s, capped at 60 s, with no queue. A failed
  step (database unavailable) keeps all entries and retries after 1 s.
- **Character/session change:** once the head query sees a different ownership scope,
  the old entry is withheld immediately, before Twitch lookup or rebuilding. Failed
  builds return warming rather than exposing the previous character's statistics.
  Ordinary failures within the same scope still keep the last good entry.
- **New or removed channel:** the head key changes and the entry is rebuilt. A removed
  channel loses its entry, card, failure and presentation state. Presentation-cache
  registration and cleanup share a lock; an in-flight old generation cannot restore
  a removed cache entry. Unknown-channel requests allocate no presentation locks.
- **Shutdown:** `server_close()` asks the refresher to stop and joins it for up to 30 s.
  An unusually long in-flight build can outlive that join; the daemon thread exits
  after the current step, and cannot hold process exit open.

## Tests

`tests/test_publisher.py`. The reference is a full replay without checkpoints, at the
published entry's own as-of clocks (card time, tracked time), presented at the request
clock. It is composed exactly as the removed request path did.

- **Background thread, synthetic scenario:** rotation, restart, loss/recovery, level-up
  (attempts 44–46), source change, then time-only expiry at +11 s, 31 s, 65 min and
  25 h. The card is rebuilt while windows can age and reused once they cannot. Exact,
  >20 comparisons.
- **Saved Streamer_F, CharE and Streamer_A logs**, streamed with publications every 60 records:
  exact every 240 records and after +0 s, 11 s, 65 min and 25 h, with nested totals
  checked.
- **Concurrency:** 40 HTTP requests from 20 simultaneous clients during a deliberately
  slow first build give exactly one card projection, at most four presentations, and
  only 200 or `warming_up` responses.
- **Cold start:** `warming` list, `503` with `Retry-After`, 404 for unknown channels,
  and the requested channel built before another cold one.
- **Failures:** last entry kept with real ages; no retry inside the backoff; recovery
  publishes the new revision.
- **Presentation cache:** reused within 1 s; new body after 1 s, after a publication, or
  after a coordinator activity change; presentation never mutates an entry.
- **Character change** rebuilds; **shutdown** stops the thread.
- **Frontend:** the warming text on the character page and homepage (Node).

Existing HTTP suites run unchanged through inline mode. Two cache tests now assert
publisher reuse instead of the removed request caches. The time-budget test was removed
with the budget.

## Measurements

Bounded synthetic run (`tools/benchmark_homepage.py --channels 1 5 10 --repeat 5
--viewers 20 --seconds 20`): full-day 20-second channels, Windows desktop, one process.
20 browser-like clients (5 s timeout, 2 s between polls) while one capture per channel
is appended every 20 s. "Before" is the previous milestone's run with the same load
shape (`private/bench-card-01`).

| Channels | Homepage p50 / p95, before → now | Character p50 / p95, before → now | Completed / timed out, before → now | CPU s/s, before → now |
|---:|---|---|---|---|
| 1 | 44 / 331 → **3 / 28 ms** | 51 / 357 → **13 / 74 ms** | 187 / 0 → 199 / 0 | 0.25 → 0.15 |
| 5 | 201 / 2,149 → **29 / 195 ms** | 142 / 1,743 → **39 / 150 ms** | 163 / 0 → 194 / 0 | 0.56 → 0.46 |
| 10 | 1,417 / 2,603 → **126 / 554 ms** | 813 / 2,583 → **86 / 437 ms** | 92 / 15 → **188 / 0** | 0.82 → 0.73 |

| Channels | First response (cold) | Fully published | New capture visible (1 channel / all) | Refresher busy under load | Homepage presentation | RSS |
|---:|---:|---:|---|---:|---:|---:|
| 1 | 14 ms (`warming: 1`) | 3.2 s | 1.35–1.51 s / 1.4 s | 6% | 7.5 ms | 109 MiB |
| 5 | 3 ms (`warming: 5`) | 19 s | 0.54–0.95 s / 2.8 s | 33% | 59 ms | 183 MiB |
| 10 | 2 ms (`warming: 10`) | 42 s | 1.13–1.32 s / 6.8 s | 67% | 123 ms | 261 MiB |

Before, the first homepage request *was* the cold build: 9.7 s, 48 s and 102 s, beyond
the browser timeout from 5 channels. Now the first response takes milliseconds, and the
tracker becomes fully available as the refresher catches up. Refresher builds averaged
446–524 ms each, card plus tracked packet, under concurrent load. The remaining request
latency at 10 channels is GIL sharing with that refresher and the one-per-second
homepage presentation. Presentation scales with channel count: ≈12 ms per published
player, which is the next thing to make shared if many channels are active.

## Limits and next step

- **One refresher in one process.** Card builds (≈0.35 s CPU) and request presentation
  share the GIL. Refresher busy time grows with active channels: a revision every 20 s
  plus the 10-second rolling-window expiry is ≈2 builds per channel per 20 s. Beyond
  ≈25–30 active full-day channels it can no longer keep every card within 10 s. Entries
  then age, honestly timestamped, instead of requests timing out.
- **Cold start** is still ≈1–2 s of refresher CPU per full-day channel (two cold
  replays plus a card). Pages are usable progressively, but full availability at
  25 channels takes ≈1 minute.
- **Memory:** per channel, ≈9.5 MiB of checkpoints for a full day plus one published
  entry (card, chart history, tracked packet), and at most two cached bodies; homepage
  bytes are shared.
- **All visible roster channels are published.** Newly configured channels warm
  progressively; unknown channels still return 404. Twitch status requests are
  split into batches of at most 100 logins. History work and cache bounds remain.
- **Unchanged:** the developer diagnostics (`/dev/api/streams`, `/dashboard/*`) and the
  trusted `/api/streams/{ch}/state` overlay still compute per request.

**Ready for a VPS load-test milestone:** yes, as a single process. Request cost no
longer depends on history or on how many viewers watch a channel. Next:

1. Serve it behind a production reverse proxy (TLS, compression of the shared bodies,
   connection limits).
2. Load-test 100 viewers on the 4-vCPU target.
3. If the refresher saturates, persist checkpoints for fast restarts, or move the
   refresher into its own process that writes published bodies for several HTTP worker
   processes. Do not run multiple workers that each replay history.

## Independent correctness review

The single-stream and multi-stream launchers now explicitly enable background mode,
like the standalone server. Previously they inherited the inline test/replay default,
so requests during actual capture still performed synchronous builds. Inline mode
remains available to deterministic tests and replay fixtures. Servers without the
public diagnostic opt-in do not start public history rebuilding.

The refresher invalidates changed ownership before any network lookup and takes a
new build clock afterward. A delayed Helix lookup no longer postpones identity
invalidation or makes a newly built packet use the pre-network timestamp.

See [review findings and validation](background-publishing-review.md). Numerical
eligibility, tracked-EXP policy, history checkpoints and historical ETA are unchanged.
