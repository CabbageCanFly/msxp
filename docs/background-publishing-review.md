# Independent background-publishing review

Reviewed commit `24cb42e` against its callers, recent history/card/inference notes,
publisher tests and saved-log reference comparisons. This is a correctness and
concurrency review of one local process, not a new capture or accuracy benchmark.

## Findings and targeted fixes

| Priority | Reproduced issue | Fix |
|---|---|---|
| High | Selecting another character, then failing its build, indefinitely retained the previous character's public entry. Cached homepage/history responses survived too. | Invalidate the published ownership scope as soon as heads reveal a character **or session** change. Return warming until a matching entry is ready. Same-scope failures still retain the last good entry. |
| High | The character page and OBS overlay kept cached character statistics after `warming_up`, even when the server correctly withheld that identity. | On warming only, clear cached readings/history and show placeholders until the replacement arrives. Ordinary network failures retain last-known values and ETA as before. |
| Medium | Both capture launchers omitted `background=True`, retaining synchronous request-side builds and Twitch checks during actual capture. | Enable the existing background publisher in both launchers; keep the inline factory default for replay/tests. |
| Medium | The standalone trusted-overlay server started public history rebuilding even when public diagnostic pages were disabled. | Start publication only when the existing `diagnostic_dashboard` opt-in is enabled. |
| Medium | A continuously revised channel repeatedly outranked an expired quiet channel. One build per pass did not guarantee fairness. | Rank changed and expired publications together by oldest build, after the bounded cold-start priorities. |
| Medium | Unknown character/history requests created two persistent lock entries per login. Presentation cache access also raced with cleanup, and an in-flight response could restore a removed cache key. | Do not allocate presentation state without an entry. Guard lock registration/cache access with the publication lock; cache a completed body only if its generation still matches. |
| Medium | The 26th configured channel got `warming_up` forever despite never being eligible for publication. | Return explicit `503 publication_limit`, without `Retry-After` or adding an unserviceable request to the wanted set. The existing 25-channel bound remains. |
| Medium | A slow Twitch lookup delayed ownership invalidation and made a subsequent build use the pre-network clock. | Publish heads before the lookup; take a new clock for the build afterward. |

The ownership, fairness, unknown-request growth, in-flight cache restoration and
network-ordering tests failed before their fixes. Launcher tests now assert the
background argument and wait for cold publication before checking live activity.

## Consistency and concurrency checks

- Card, chart and tracked packet still build in one SQLite read transaction, with
  immutable published entries and explicit computation/serving timestamps.
- Character changes with failed builds withhold both character and history bodies;
  the homepage lists that channel as warming instead of showing old statistics.
- Player and overlay Node regressions cover old identity → warming/placeholders →
  replacement identity. This does not alter ordinary connection-failure retention or
  the overlay's separate live ETA calculation.
- Concurrent responses share per-key serialization. Registration, cache reads/writes
  and cleanup now use the same publication lock; expensive presentation stays outside it.
- The existing background rotation/restart/loss/level/source test and exact saved
  Emmies, Niru and Telfer1 reference comparisons remain in the regression suite.
- No numerical policy, inference, quarantine, checkpoint, historical ETA, trusted
  accounting, source evidence or database schema was changed.

## Brief localhost measurement

Command (new ignored directory; no remote connections):

```powershell
.\.venv\Scripts\python tools/benchmark_homepage.py --directory private/publisher-review-01 --attempts 61 --channels 2 --repeat 1 --viewers 20 --seconds 5
```

Synthetic 61-attempt histories per channel, including rotation; 20 browser-like HTTP
clients. The requested five-second load phase took ten seconds including client/writer
drain. It completed 25 homepage and 25 character requests with **zero timeouts**.
Homepage p50/p95: **14/23 ms**; character p50/p95: **15/31 ms**. Cold full availability
was 0.1 s; new captures became visible in 1.01–1.17 s. Mean refresh build: 62 ms;
mean presentation: 13.5 ms; sampled process RSS: 68 MiB. These small histories do not
represent full-day cost or a low-end VPS. Detailed output is ignored under the command's
directory.

## Regression results

- Full Python run: **1,899 passed, 0 skipped**, 553.83 s. This includes exact saved-log
  publisher/card/checkpoint parity and numerical safeguards. Four additional review
  cases were added after that run began; all are covered by the final affected-module
  run: **113 passed, 3 deliberately deselected** (the saved publisher sweeps already
  passed in the full run), 55.52 s. No sample skips in either run.
- Node: **87 passed, 0 skipped**, including both warming/replacement identity cases.
- Actual Chrome/SQLite: `--verify-tracked-exp emmies` passed, **13 screenshots**,
  desktop/mobile, polling and transparent 500×160 OBS, under
  `private/publisher-review-browser-03`. The 20-viewer benchmark uses background mode;
  this browser replay uses the existing deterministic inline fixture.
- The older optional `--verify-updates` script stopped at its expectation of
  `Not complete yet`; the no-coordinator fixture returns historical `Paused` instead.
  No assertion was weakened. That older harness's activity-state assumption remains
  to be reconciled; the current saved-log browser mode above passes. An initial
  invocation also used the wrong fixture channel and was rerun with `telfer1`.
- `git diff --check` passes. No Twitch capture, evidence mutation, commit or push.

Commands:

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m pytest tests/test_publisher.py tests/test_server.py tests/test_local_alpha.py tests/test_multi_alpha.py -q -k "not saved_publications"
node --test tools/*.test.mjs
node tools/product.browser.mjs http://127.0.0.1:8879 private/publisher-review-browser-03 --verify-tracked-exp emmies
```

Use a fresh ignored browser/benchmark output directory when repeating commands.

Changed files:

- Runtime: `src/exp_tracker/publisher.py`, `src/exp_tracker/server.py`,
  `src/exp_tracker/web/product.js`, `tools/local_alpha.py`, `tools/multi_alpha.py`.
- Regressions: `tests/test_publisher.py`, `tests/test_server.py` is exercised but
  unchanged; modified launcher tests are `tests/test_local_alpha.py`,
  `tests/test_multi_alpha.py`; frontend tests are `tools/product.test.mjs`.
- Documentation: `docs/background-publishing.md` and this review.

## Remaining limits and load-test recommendation

- Selection changes become visible when the refresher next reads heads. An already
  in-flight response remains a snapshot of its own read; there is no cross-process
  instantaneous invalidation protocol.
- One refresher still shares the Python GIL with request presentation. Homepage
  presentation copies and refreshes player data more than once; the existing short
  body cache bounds this work, but it remains a load-test measurement target.
- Cached Twitch checks still run on that one refresher. Slow bounded network calls
  can delay all subsequent builds; cached HTTP responses continue to serve. The
  delayed-lookup test uses a mock, not a live Twitch request.
- Shutdown joins the refresher for up to 30 seconds; it cannot forcibly cancel a Python
  build. An exceptionally slow build can outlive that join in a daemon thread until
  its current step finishes. Normal shutdown is regression-tested.
- Only the first 25 configured channels publish. Database/build failures retain old
  same-scope snapshots with honest ages; they cannot guarantee a fixed freshness bound.
- Checkpoints and published entries are process-local and cold after restart.

Suitable for a subsequent **controlled 100-viewer load test**, after applying these
fixes. Measure full-day histories, per-channel publication age, cold warming, request
latency, CPU/RSS and shutdown; do not infer that capacity from this short check.
No public deployment or long 25-channel benchmark was performed.
