# 100-viewer load and Linux VPS readiness

Follows [background publishing](background-publishing.md) and its
[review](background-publishing-review.md). This milestone measures the public server
under 100 simulated viewers and judges whether a controlled trial on one
4-vCPU / 8-GB Linux VPS is reasonable. Nothing was provisioned, no Twitch capture was
started, and the live database was only read (read-only URI) for disk-growth figures.

## Verdict

**Ready for a controlled Linux trial at the current scale (≈5–6 channels).** That
assumes the reverse-proxy allowlist and compression below, and a repeat of this
benchmark on the VPS itself first.
**Not ready for 10+ full-day channels at 100 viewers** in one process: the refresher
saturates the Python GIL there. Requests still succeed, but publications lag up to
≈10 s and p95 latency exceeds 1 s.

## Method

`tools/benchmark_homepage.py` (synthetic only, never Twitch or OCR). One full-day,
20-second-cadence channel (4,321 attempts) is written through the normal append and
rotation path, then cloned per channel. The in-process server runs with
`background=True`.

Changes this milestone:

- **Viewers run in separate client processes** (25 threads each). Before, 100 client
  threads parsed JSON inside the server process and competed for its GIL, which
  inflated latency and CPU.
- Browser-like clients: 5 s timeout, next poll 2 s after each response. Even-numbered
  viewers poll the homepage; odd-numbered viewers poll a character and also fetch its
  `/history` every ≈30 s, as `product.js` does.
- Reported p50/p95/p99/max, timeouts, errors by reason, server-only CPU, and peak RSS
  sampled during load. Publication freshness is also sampled every 100 ms: the time
  from each appended capture to its appearance in a published entry, and the age of
  the oldest published entry.

**Cost estimate made beforehand** from earlier runs: template ≈2 s, cold publication
≈20 s (5 channels) / ≈42 s (10 channels), plus ≈10 s of visibility checks and a 30 s
load phase. Estimated ≈1.3 + ≈2 min wall, mostly one core. Actual: 74 s and 122 s
per run. Four full runs in total (two 5-channel diagnoses, the 5-channel rerun and
the 10-channel run).

Windows 11 workstation (24 logical CPUs), Python 3.14.7, one server process, loopback
HTTP. **A VPS vCPU is typically slower per thread; these are not VPS numbers.**

## Results (100 viewers, ≈30 s load)

| | 5 ch, backlog 5 (before fix) | **5 ch, backlog 128** | **10 ch, backlog 128** |
|---|---|---|---|
| Requests (home / character / history) | 681 / 661 / 50 | 700 / 687 / 50 | 625 / 619 / 50 |
| Timeouts / errors | 0 / **4 refused** (12 in first run) | **0 / 0** | **0 / 0** |
| Homepage p50 / p95 / p99 / max ms | 44 / 1,024 / 1,547 / 2,065 | **65 / 388 / 491 / 553** | 260 / 1,110 / 1,302 / 1,457 |
| Character p50 / p95 / p99 / max ms | 43 / 1,070 / 1,664 / 2,210 | **81 / 425 / 485 / 539** | 259 / 1,145 / 1,318 / 1,449 |
| History p50 / p95 / p99 ms | 31 / 1,117 / 1,672 | 139 / 269 / 327 | 160 / 961 / 969 |
| Server CPU (s/s) | 0.62 | 0.63 | **0.92** |
| Refresher busy / presentation busy | 49% / 14% | 51% / 17% | **96%** / 31% |
| Builds in load / max build | 21 / 1,066 ms | 21 / 1,072 ms | 36 / 1,588 ms |
| Capture → published p50 / p95 / max | 2.2 / 2.8 / 4.9 s | 1.7 / 4.1 / 4.8 s | **4.5 / 9.0 / 9.8 s** (2 still pending at end) |
| Oldest published entry p50 / p95 / max | 8.8 / 11.3 / 11.9 s | 9.0 / 11.8 / 12.7 s | 11.6 / 13.3 / 13.9 s |
| Peak RSS | 198 MiB | 198 MiB | 324 MiB |
| Cold: first response / fully published / CPU | 13 ms / 20.0 s / 19 s | 13 ms / 20.5 s / 20 s | 15 ms / 43.1 s / 42 s |

Busy fractions are wall time inside builds or presentations, including GIL waits. They
can sum past 100%; CPU s/s is the real ceiling, ≈1.0 for one Python process.

### Findings

1. **Fixed: connection refusals.** `ThreadingHTTPServer` inherits socketserver's
   listen backlog of **5**. With ≈45 requests/s, any moment the accept loop waited
   for the GIL filled the backlog. Windows then refused connections after its
   internal connect retries, which most likely caused the ≈1 s p95 tail. On Linux a full
   backlog drops SYNs, so clients or the proxy retry after ≥1 s. `TrackerHTTPServer`
   now sets `request_queue_size = 128` (Linux caps it at `net.core.somaxconn`). Same
   load afterwards: 0 errors, p95 1,024 → 388 ms, p99 1,547 → 491 ms.
2. **10 channels saturate one process.** The refresher runs ≈1.1 builds/s: a revision
   every 20 s per channel plus 10-second rolling-window expiry. Builds stretch from
   ≈0.35 s of isolated CPU to 0.93 s mean under contention. Presentation (≈200 ms per
   homepage at 10 channels) shares the same core. No request failed, but freshness
   degrades first, as designed. On a slower vCPU the knee moves below 10 channels.
3. **Response bodies are large.** Uncompressed / gzip-6, 5 channels:

   | Endpoint | Body | gzip |
   |---|---:|---:|
   | `/api/players` | 634 KiB (≈127 KiB per player) | 42 KiB |
   | `/api/players/{ch}` | 1,012 KiB, of which `history` is 746 KiB | 34 KiB |
   | `/api/players/{ch}/history` | 129 KiB | 4 KiB |

   Each `recent_windows` / `current_level_windows` entry is ≈8.5 KiB. At 100 viewers
   that is **≈40 MiB/s (≈330 Mbit/s) uncompressed**, or ≈2 MiB/s (≈16 Mbit/s) gzipped.
   The character poll resent the unchanged 746 KiB chart every 2 s. **Addressed** for
   character pages and overlays ([conditional history](#conditional-character-history));
   the homepage and per-window detail are unchanged. Proxy compression is still mandatory.
4. **One flag exposes per-request developer endpoints.** The public product requires
   `--diagnostic-dashboard`, which also serves `/dev/api/streams` (5.7 s cold on
   5 full-day channels, then cached), `/dev/api/streams/{ch}/diagnostics`
   (≈60 ms and 744 KiB per request, uncached, arbitrary session/run queries),
   `/dashboard/*` and `/dev/*`. They are cheap to request repeatedly and expensive to
   serve, so they must not be publicly reachable. **Addressed** by `--public-only`
   ([below](#public-only-mode)).
5. **Capture and serving are coupled.** `operation()` trusts only the in-process
   coordinator for live activity. A standalone `python -m exp_tracker.server` shows
   live channels as `coordinator_stopped` / `previous_unfinished_run`. The trial must
   therefore run `tools/multi_alpha.py` (capture + server in one process), and capture's
   in-process work shares the GIL that this benchmark measured without it.

## Public-only mode

`--public-only` (server and `tools/multi_alpha.py`; `create_server(public_only=True)`)
serves only the public product and refuses everything else with
`404 {"error": "not_found"}`, before any database access. This does not depend on
proxy configuration.

| Served | Routes |
|---|---|
| Homepage | `/`, `/streams`, `/api/players` |
| Character page | `/stream/{ch}`, `/api/players/{ch}`, `/api/players/{ch}/history` |
| Experimental OBS overlay | `/live/overlay/{ch}` (uses `/api/players/{ch}`) |
| Assets | `/static/product.js`, `/static/product.css`, `/static/leaderboard.css`, `/static/leaderboard.svg`, `/static/overlay.css` |

**Refused (404):** `/dev/*`, `/dashboard/*`, the shadow viewer and its assets, the
directory script, the trusted-state API `/api/streams/{ch}/state` and its legacy
`/overlay/{ch}` page, the fictional `/demo/leaderboard` and its script, and anything
unlisted. Non-GET methods still return `405`.

The background publisher, Twitch status and coordinator activity run as in developer
mode. Public pages carry `data-site="public"`, which hides their Advanced, Design demo
and detailed-history links. `--public-only` cannot be combined with
`--diagnostic-dashboard` or `--shadow-log`: startup fails instead of silently choosing
one. Without the flag, every launcher and test behaves as before.

Public-only coordinator for the trial (Linux, from the checkout; the port comes from
the config's `port`):

```sh
.venv/bin/python tools/multi_alpha.py --config private/multi-alpha/config.json --check --twitch-status
.venv/bin/python tools/multi_alpha.py --config private/multi-alpha/config.json --continuous --twitch-status --public-only
```

The startup log prints `Public-only: developer diagnostics are disabled (404).`
For operator diagnostics, use a separate developer server on another loopback port
against the config's `database` (`DATABASE` below), reached through an SSH tunnel:
`.venv/bin/python -m exp_tracker.server --db DATABASE --port 8766 --diagnostic-dashboard`.
It shows live channels as not running (finding 5); its routes still compute per request.

`tools/local_alpha.py` (single channel) and the standalone server without the flag
keep developer mode.

## Linux VPS plan (4 vCPU / 8 GB), untested

**Processes.** For the trial, keep one `multi_alpha --public-only` process (capture
coordinator, refresher, HTTP on `127.0.0.1`). Streamlink, FFmpeg, Tesseract and the neural worker
are already subprocesses and can use the other cores. Add Caddy (or nginx) as the only
public listener. The workstation measured ≈6–16% of one core and ≈200 MiB peak tree
RSS per capture channel ([live capture](live-capture.md)). Six channels plus a
≈200–350 MiB server fit 8 GB on paper; concurrent Linux capture is unmeasured.

**Reverse proxy.** TLS, compression and the same path allowlist as defence in depth.
The fictional demo and the generic `/static/*` prefix are removed: no public page needs
them. Untested Caddy sketch:

```caddy
tracker.example.org {
    encode zstd gzip
    @public {
        path / /streams /stream/* /live/overlay/* /api/players /api/players/*
        path /static/product.js /static/product.css /static/leaderboard.css /static/leaderboard.svg /static/overlay.css
    }
    handle @public {
        reverse_proxy 127.0.0.1:8765
    }
    respond 404
}
```

Option (untested): an nginx 1 s micro-cache (`proxy_cache_valid 200 1s`,
`proxy_cache_lock on`, ignoring the app's `no-store` for the cache only) matches
`PRESENT_SECONDS`. It would cut Python request handling from ≈45/s to ≈1 per URL per
second. Never cache `503 warming_up`.

**SQLite.** Writers already enable WAL; the server opens read-only (`mode=ro`). Keep the
database on local disk, never network storage, and run reader and writer as the same
user. A read-only WAL reader still needs write access to `-shm`. Capture is the only
writer.

**Supervision.** A systemd unit with `Restart=on-failure`, a dedicated unprivileged
user, `ProtectSystem=strict`, `ReadWritePaths=` for the data directory only, and
`NoNewPrivileges=yes`. Twitch credentials go in an `EnvironmentFile` readable only by
that user (OBS credentials stay on the streamer's machine, per AGENTS.md).
`server_close()` joins the refresher for up to 30 s, so keep `TimeoutStopSec` above
that. After a restart, the homepage answers immediately with `warming` and channels
publish progressively: ≈20 s for 5 channels, ≈43 s for 10 on this workstation.

**Security.** Bind the app to `127.0.0.1` (already hardcoded); firewall everything but
22/80/443; SSH keys only. Public paths are allowlisted by `--public-only` and again
at the proxy.
`ThreadingHTTPServer` has no request timeout or thread cap, so let the proxy buffer and
time out slow clients. Unknown channels are bounded (404, no presentation state).

**Disk.** The live multi-channel database grew to 75 MiB for 21,112 attempts
(≈3.7 KB each, 2.9 KB payload). Run logs under `runs/` added another 140 MiB. A
20 s cadence is ≈16 MB of database per channel per streamed day, or ≈35 GB/year for
six channels streaming 24 h; real streams are shorter. There is no retention policy
yet: monitor disk and rotate run logs.

**Backups.** `tools/backup_database.py` takes a consistent online backup including
WAL, then runs `integrity_check` and `foreign_key_check`. It refuses destinations
outside `private/` or `artifacts/`, so run it from the checkout, e.g. daily via a
systemd timer, then copy the verified file off the VPS. Test a restore before relying
on it.

## Prioritized next steps

1. **Before any public trial:** proxy with TLS, compression and the allowlist; systemd
   unit; daily verified off-host backup; run this benchmark on the VPS against a copy:
   `python tools/benchmark_homepage.py --directory private/vps-01 --channels 5 --viewers 100 --seconds 30`.
2. ~~Separate public product from developer diagnostics~~: done, `--public-only`.
3. **Shrink polled payloads:** ~~send the chart only when it changes~~ (done,
   [conditional history](#conditional-character-history)). Remaining: the homepage
   (≈100–220 KiB per player) and per-window detail the pages do not render.
4. **Measure capture + server together on the VPS** with the real channel count. If
   process CPU nears 0.8 s/s, publish coordinator activity across processes (a
   heartbeat row or status file). Capture and the public server can then run
   separately.
5. **Beyond ≈6–8 full-day channels:** move the refresher into its own process that
   writes published bodies for the HTTP process, as recorded in background publishing.
   Persisting checkpoints would shorten cold start.
6. Retention for run logs and old attempts.

## Conditional character history

`/api/players/{ch}` now carries `history_revision` and `tracked_revision`: 16-hex content
hashes of the published chart rows and tracked-EXP packet, computed once per build by the
refresher. `product.js` (character page and OBS overlay) names the revisions it holds:
`/api/players/{ch}?history=…&tracked=…`. The server omits `history` / `tracked_history`
only when the presented entry still has exactly that revision, so an omitted section is
always the viewer's own copy of the current publication. A changed section, a new
character or session, a first load, a reconnect after a newer publication, or any
missing or invalid value gets the section in full. Requests without parameters (tests,
older pages, scripts) get the unchanged full body.

- **Consistency:** equal content gives an equal revision, so a time-only rebuild that
  changes only the tracked `as_of` resends only the tracked packet. If a publication
  lands between the decision and the presentation, the section is sent in full. Warming
  clears the page's copy, so a character change always starts from a full body. A body
  that omits a section the page cannot match is never merged; the next poll asks for
  everything.
- **Bounded state:** at most four presentation keys per channel (section held or not).
  The held revisions are part of the cache's runtime match, so a body is reused only for
  the same ones.
- Unchanged: the homepage, `/api/players/{ch}/history`, publisher scheduling, EXP
  eligibility, level inference, stored history and trusted accounting.

Measurements: Windows workstation, single process, loopback. "Before" is HEAD's `src`
on the same data, measured back to back.

| Character body | Before | Unchanged poll now | Full body now |
|---|---:|---:|---:|
| Synthetic full day, 132 chart rows | 747 KiB (26 KiB gzip) | **117 KiB (8 KiB gzip)** | 747 KiB |
| Real Shiphtur (live DB, read-only), 110 rows | 785 KiB (35 KiB gzip) | **179 KiB (14 KiB gzip)** | 786 KiB |
| Presentation, median (synthetic / real) | 6.6 / 12.2 ms | **3.3 / 7.1 ms** | 6.2 / 11.7 ms |

The refresher adds 3.8 ms per build for both hashes (a cold full-day build is ≈2 s).
Bounded load (`benchmark_homepage.py --channels 2 --viewers 40 --seconds 20`; the
benchmark's character viewers now echo revisions like the page): mean character response
**1,053 → 341 KiB**. This includes the full bodies sent after each capture and refresh.
Server CPU was 0.24 → 0.23 s/s; character p50/p95 17/136 → 10/106 ms. Latency and CPU
differences at this load are within noise.

Public-field audit (public-only bodies from the live 10-channel database, read-only):
no file paths, URLs, capture or OBS credentials, Twitch tokens or stream playlists.
Values present but unused by the pages, all low sensitivity:

- `source_identity`: a SHA-256 of the source kind and Twitch login, of an HLS input
  URL, or of the local video's absolute path. It reveals a URL or path only if that
  value can be guessed.
- run, session and character IDs.
- coordinator activity timings: run ID, next due time, requested and actual intervals,
  skipped deadlines.
- OCR diagnostic reason codes and neural-reader level fields.
- the public requirement-table SHA-256.

Removing them needs a public serializer for the nested pace/window structures. That is
deferred, because exact-parity tests compare those structures.

## Not measured

Real Linux or VPS hardware; capture CPU alongside the server; cold start *under*
viewer load; the proxy configs above; TLS cost; the shutdown join under load; more
than 100 viewers; and real (non-synthetic) histories under this load. Output is in
ignored `private/vps-bench-05`, `-05b`, `-05c` and `-10`.

Validation: `pytest tests/test_server.py tests/test_publisher.py -k "not saved_publications"`
**77 passed, 0 skipped**. The full suite was not rerun for this one-line server change.
