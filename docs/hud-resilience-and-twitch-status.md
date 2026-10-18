# Unreadable HUDs, recent pace and Twitch status

The public tracker now keeps a steadier recent trend through unreadable HUDs,
with a separate aging presentation estimate. Twitch broadcast status is optional
official API evidence, independent of the capture worker. No OCR, grammar,
requirements, schema, trusted accounting or frozen captures changed.

## Pace behavior

`responsive_pace_v3` can pool eligible captured intervals within the latest five
minutes across bounded unreadable periods (at most 300s / 100 missing attempts).
The missing interval contributes **neither gain nor captured coverage**. Each
contributing edge must still satisfy the original connected comparison checks.
This exception affects presentation pace only: observed-window endpoint rules,
strict 5/10/15/30-minute eligibility, ranking and chart connections stay unchanged.

Source/character/session/restart boundaries, unsupported or conflicting level
evidence on readable endpoints, unsafe crops, quarantine, confirmed losses and
level changes are not smoothing opportunities. Validated scheduled rotation can
continue the same context; a fresh UUID alone cannot. No line or gain bar is
created over a missing interval. The first resumed reading supplies no gain
comparison; the next eligible edge updates the pooled rate promptly.

The API preserves the actual sampled rate in `responsive_pace.estimates` and adds
`responsive_pace.presentation` for display. While capture is running but the HUD
is unreadable, retain the rate for 20 seconds, then display:

```text
displayed rate = sampled rate × covered seconds
                / (covered seconds + max(0, age since last comparable interval − 20))
```

This assumes **no new gain since that interval**, for presentation only. It is not
an assertion about gameplay. No zero observations, gain rows, missing coverage or
trusted totals are inserted. Both display-quantization hypotheses scale separately;
their bounds still exclude OCR/table errors and are not confidence intervals.
ETA is withheld during aging. At five minutes without a new supported interval,
the current displayed rate pauses; the original dated trend remains in the API.
Client-side aging continues between polls and never jumps back to the higher
sampled rate merely because an HTTP request fails.

Completed/stopped capture, a read-only server restart and a fresh official offline
status show the dated historical trend instead of implying active decay/current
measurement. Stationary comparable EXP can produce an actual sampled zero rate;
an unreadable period cannot. A new level starts its own estimate.

Fresh captured frames with unreadable HUDs say **HUD unreadable**, even if the last
usable percentage has become old. Missing acquisition, delayed acquisition and
intentional completion retain their own states. The public UI keeps its single
tilde and existing desktop/mobile/500×160 overlay layout.

## Saved-data results

Replayed all 38 attempts from `20261018T070644Z-33a2d9e1`, plus all 180 attempts
and rotations from `20261018T043432Z-c0b93f52`. Six source-log SHA-256 hashes were
checked unchanged. These are comparisons of existing experimental outputs, not
new human accuracy labels or verified earned-EXP rates.

| Telfer1 checkpoint | Previous presentation | New presentation |
| --- | --- | --- |
| 10 | ~187,115 EXP/h, 10 readings / 180s | Same sampled trend |
| 11–13, unreadable percentage strings | Held ~187,115 as a dated value | Gradual no-new-gain aging; ~152,859 at frame 13's timestamp |
| 14, first resumed percentage | Held previous rate | Still aging; no gain assigned to the hole |
| 15 | ~119,699, two readings / 20s | ~180,343, 12 readings / 200 captured seconds |
| 16 | ~134,916, three readings / 40s | ~177,601, 13 readings / 220 captured seconds |
| 19 | ~155,884, six readings / 100s | ~174,520, 13 readings / 220 captured seconds within 300s |

The latest saved trial is marked **interrupted** in its original summary, not
normally completed. That provenance is preserved. Shiphtur's 19 failed captures
remain failed; the saved `offline_or_unavailable` / `source_ended` reasons cannot
independently establish its historical Twitch status.

The earlier 90-attempt browser replay retains identical historical window objects
and Shiphtur's ~88,864 EXP/h saved trend, including its completed-capture label.
The causal audit made 224 checkpoint projections in 3.946s, sampled 3.656 CPU
seconds and 38.38 MiB peak tree RSS. This measures local replay, not capture/model
cost or low-end server capacity.

Private audit: `private/hud-resilience/audit-56fb1fb0/audit.json`; baseline:
`private/hud-resilience/before.json`. Original logs/databases were not rewritten.

## Official availability

Enable `--twitch-status` on the HTTP server, `tools/local_alpha.py` or
`tools/multi_alpha.py`. It reuses `twitch_probe.helix` and the existing server-side
`TWITCH_CLIENT_ID` / `TWITCH_ACCESS_TOKEN` environment convention. Without the
flag or credentials, capture/tracking still works and broadcast status is unknown.
No token is stored in SQLite, diagnostic configuration, public JSON or the browser.

[Twitch Get Streams](https://dev.twitch.tv/docs/api/reference/#get-streams) accepts
an app or user access token and repeated `user_login` filters. The server batches
up to 25 configured Twitch sources, explicitly requests `first=100` (the API
default is only 20), and caches results for 60s. Local test-video assignments are
not probed. Checks are demand-driven by public API polling, not another scheduler.

One shared lock prevents concurrent refreshes. Pagination follows `after`, with
at most three requests per refresh, a 3s transport timeout and 256 KiB JSON limit
per page. All requested channels confirmed live stops pagination early. Repeated
or invalid cursors, the page limit and later-page failures retain confirmed live
channels but leave unresolved channels **unknown**. Only reaching a terminal page
allows an absent channel to be reported offline. Worst-case request time can now
approach 9s; this affects an HTTP refresh, not capture scheduling. Missing credentials,
HTTP errors, rejected tokens and expired cached results never establish offline
status. This is not authentication of account/character identity.
429 retries respect a bounded 60–900s Retry-After. Tokens are not automatically
renewed; correct the server environment and restart when rejected.
Backoff does not extend a confirmed live result's 60s freshness; it becomes unknown
if it expires before another request is permitted.

The public `twitch` metadata includes check/expiry times, safe reason and any
recent-capture disagreement. UI examples include **Twitch live · Capture
unavailable**, **Twitch offline**, and **Live status unknown · Capture unavailable**.
Recent decoder pixels may temporarily disagree with Helix; neither is silently
rewritten to agree. Current broadcast status does not describe when old history
was captured, and does not suppress/retry capture or change ranking rules.
An expiring cached status never becomes a claim that Twitch remains live forever.

## Restart and configuration

Reopening the same DB restores the selected character, last supported level,
saved pace, percentages and chart data immediately, within the existing bounded
640-attempt/session query. Older history remains accessible through existing
historical/24-hour APIs. Levels keep their actual evidence age; historical pace
does not become fresh just because the server restarted. No new restoration
database or migration was needed.

A new coordinator process creates new run identities. Old pace remains inspectable;
the first new reading does not join old endpoints, and a new comparable pair can
seed current pace. Clean scheduled rotation remains a separate validated case.

For the current 2–25-source prototype, editing private JSON and performing a
controlled Ctrl+C/restart is sufficient. Existing character-selection mismatches
still fail explicitly. Safe hot configuration would require validation and
reconciliation between jobs, explicit session/character actions, lifecycle/status
updates and continuity breaks while preserving removed-source history. It is not
implemented here.

## Commands and validation

```powershell
# Existing read-only data; this command starts no capture. Optional Helix needs
# TWITCH_CLIENT_ID / TWITCH_ACCESS_TOKEN set locally, never committed or shared.
.\.venv\Scripts\python -m exp_tracker.server --db private/multi-alpha/live-telfer-shiphtur.sqlite3 --diagnostic-dashboard --twitch-status
Start-Process 'http://127.0.0.1:8765/stream/telfer1'
Start-Process 'http://127.0.0.1:8765/live/overlay/telfer1'

# A preflight does not contact Twitch. Only start capture later with permission.
.\.venv\Scripts\python tools/multi_alpha.py --config private/multi-alpha/config.json --check --twitch-status

# New output directories; browser fixture uses saved outputs and mocked
# Helix/simulated worker activity, never a real Twitch request or new capture.
node tools/product.browser.mjs http://127.0.0.1:8789 private/hud-resilience/browser-new --verify-resilience telfer1
node tools/product.browser.mjs http://127.0.0.1:8790 private/hud-resilience/historical-new --verify-historical shiphtur
.\.venv\Scripts\python -m pytest -q -rs --basetemp private/hud-resilience/tests-new
node --test tools/*.test.mjs
```

Tests cover 20s/1m/3m/5+ minute holes and recovery, stationary EXP, loss/quarantine,
level-ups, rotations, session/restart boundaries, strict ranking isolation,
credential/error/rate-limit handling and batched cache behavior. Desktop/mobile/
OBS polling was checked through gap/recovery/pause/restart/interruption. Screenshots
are private in `private/hud-resilience/browser-final/`; the older completed trial
is in `private/hud-resilience/historical-browser-01/`. Helix responses and live
worker activity in the new browser fixture are explicitly mocked, not official
historical status evidence.

Validation: **1,338 Python tests passed**, zero skipped, in 123.78s; **70 Node
tests passed**. Both real-SQLite Chrome checks passed without console errors or
page reloads. `git diff --check` passed (Git notes existing CRLF-to-LF normalization
for the edited replay fixture).

Changed files: presentation/API in `src/exp_tracker/product.py`, `server.py`,
`twitch_probe.py`, `web/product.js`; opt-in flags in `tools/local_alpha.py` and
`multi_alpha.py`; tests in `tests/test_hud_resilience.py`, `test_twitch_probe.py`,
`test_companion_statistics.py`, `tools/product.test.mjs`, `product.browser.mjs`,
`product_updates_fixture.py`; documentation in `README.md`,
`docs/product-experience-principles.md`, `gaming-companion-statistics.md` and this
guide. No changes to the trusted Store, diagnostic persistence, scheduler,
recognizers, models or requirement data. Nothing was committed or pushed.

Next manual trial: two permitted streams at 20–30s for roughly ten minutes, with
saved crops and optional valid Helix credentials. Check natural HUD obstruction,
recovery, stopped capture and a known offline channel separately. No new remote
capture or live Helix request was made during this work. This presentation policy
cannot establish numerical accuracy or determine what EXP was gained while blind.
