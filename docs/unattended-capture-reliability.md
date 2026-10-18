# Unattended capture failure and recovery

This is an offline fault-injection audit, not a new live-stream reliability or
OCR-accuracy benchmark. No Twitch connections, recognition rules, trusted
accounting, schema, source evidence or historical observations were changed.

## What already worked

| Failure | Existing behavior, retained |
| --- | --- |
| Source unavailable, decoder exit, network/access error | Persist a failed attempt with a safe reason; retry on the next scheduled capture. Unavailability does not establish Twitch offline status. |
| Acquisition hangs | `frame(timeout=...)` expires; the session terminates, waits for and if necessary kills its Streamlink/FFmpeg children. Connections close before OCR. |
| Neural worker hangs/exits/returns malformed JSON | Existing subprocess timeout/response checks reject it; retain visual evidence where available. No candidate is invented. |
| Missing or competing HUDs | Abstain; no cached region or arbitrary target selection. |
| Source returns | A new connection is made for the next scheduled attempt. No persistent failed connection needs resetting. |
| Slow/failing stream | One sequential worker, fair due-time scheduling and missed-slot skipping; other lanes continue without a backlog. A slow job can still delay them. |
| Attempt persistence fails or selection changes | Stop that lane; preserve its log and committed history. Other lanes continue. Replay stays explicit/idempotent. |
| Ctrl+C/restart | Close active capture resources, preserve committed attempts, release OS ownership lock; restart uses new run IDs without claiming continuity. |

There is no new retry loop or backoff option. At a typical 15–30s cadence the
existing scheduled retry is proportionate; a failed job is never immediately
retried. Acquisition/neural timeout settings remain unchanged. Tesseract has a
10s limit **per invocation**, and localization/level reading can use multiple
passes. These are stage bounds, not a hard whole-attempt deadline; OS process
creation/termination and filesystem stalls are not covered by such a deadline.

## Reproduced weaknesses and targeted fixes

1. **Rotation failure:** injected SQLite failure during successor creation rolled
   back the transaction, but left the lane pointing at the uncommitted successor,
   with no immediate rotation-failure operator event. It could retain old live
   activity while another channel kept running. Restore the original lane/log/
   output identity, stop that lane immediately, and record a safe
   `rotation_failed` event and concise terminal explanation. Do not append a
   contradictory shutdown summary after the already-written rotation intent.
2. **Stopped worker advertised active:** an attempt INSERT failure stopped capture
   but left the run in the HTTP live-worker set. A direct snapshot during the next
   channel's job returned `active`. Both persistence-failure paths now remove the
   run immediately; its database history remains explicitly unfinished.
3. **Monitor growth:** after 200 distinct exited children, the CPU monitor retained
   201 PID/creation-time entries. It now rolls retired CPU into a scalar total,
   retaining only currently sampled processes. The same deterministic workload
   retains two entries, then one after the last child exits, with the same
   219.9 sampled CPU seconds. Metrics are still sampled approximations.

Operator attempt entries now also contain run ID, status, safe reasons and stage
timings alongside the SQLite commit result. Raw subprocess stderr is not exposed;
there are no repeated exception traces or signed playback URLs. The existing
capture JSONL retains the richer immutable observation.

A rotation intent in JSONL is **not proof of a committed SQLite rotation**. After
a failed transaction, the old DB run remains unfinished and the prepared successor
file is retained privately. Preserve both files and investigate/replay explicitly;
do not blindly append or assume a clean rotation. Restart preserves the evidence
and creates a new identity, rather than automatically repairing the failure.

## Offline evidence

- **Virtual-clock, real SQLite:** 67 attempts/channel at each of 15s and 30s
  requested cadence. The second lane fails seven consecutive captures (58–64),
  spanning old run 60 and successor 1–4; each timeout costs 20 simulated seconds.
  Both lanes reach 67 attempts with alternating jobs; all seven failures commit,
  attempt 65 recovers, ownership is unchanged and both rotations complete.
  The outage costs 140 simulated worker-seconds. No simulated timestamp produces
  real percentage pace or trusted observations.
- **Real child-process tests:** sleeping Python stand-ins for decoder alone and
  Streamlink+decoder expire at a 0.15s frame deadline; processes are reaped and all
  reader threads stop within the test's 6s bound. A real sleeping neural stand-in
  hits its 0.5s timeout and its PID disappears within 5s. An immediate decoder exit
  is unavailable, never a fresh frame. These test lifecycle behavior, not network
  behavior or model accuracy.
- **Actual FFmpeg + unchanged RapidOCR/Tesseract + HTTP + SQLite:** six attempts
  across two local videos, requested 8s intervals. The returning source is
  deliberately pointed at a missing file twice, then restored. All six attempts
  commit: four frames acquired, three unique HUDs/strict pairs, one missing HUD,
  two `source_ended` failures. Missing-file attempts cost 0.037s / 0.032s; recovery
  acquires and recognizes a new source frame (8.258s work). No child PIDs remain
  and no trusted observations are inserted. Total wall 31.242s; sampled CPU
  9.797s, peak process-tree RSS 196.20 MiB. Healthy source start spacing averages
  8.000s, returning source 7.875s; one skipped deadline is counted on its final
  completion. This short local workload does not establish remote/VPS capacity.

Private evidence: `private/unattended-reliability/actual-4d132b82/summary.json`,
`console.txt`, fresh SQLite DB; detailed acquisition logs at
`private/multi-alpha/runs/20261018T065534Z-98326c7c/`. The private
`integration.py` repeats the bounded local test in a new output directory.
Synthetic failures, lifecycle assertions, real child tests, clean rotations,
restart/selection checks, historical summaries and numerical gap/quarantine
regressions are covered by the commands below.

The real SQLite-backed Chrome historical check also passed: two saved streamers,
polling new committed observations, all four windows, desktop/mobile pages and
500×160 OBS overlay. Screenshots/results are in
`private/unattended-reliability/browser-02/`. The initial sandboxed Chrome launch
failed; the check succeeded with normal local process permissions.

## Storage and operational limits

Nothing deletes evidence. The actual six-attempt DB is 131,072 bytes; its payloads
average 2,760.5 bytes, including two small failures. Operator JSONL is 2,881 bytes
for eight records. This tiny mixed workload is not a reliable linear database-size
prediction. At two channels/20s there are 8,640 attempts/day; at 25 channels/15s,
144,000/day. DB payloads, duplicated JSONL, WAL, optional crops and backups all
accumulate; actual successful OCR payloads can be larger. Review free disk space
and use the existing verified SQLite backup command before unattended operation.
See [continuous-alpha.md](continuous-alpha.md) for backup/recovery and measured
larger-history growth. Retention remains a future explicit maintenance policy.

Failure recovery restores acquisition, not verified continuity. Failed, stale,
missing-HUD and ambiguous observations still break comparable progress; clean
rotation alone cannot erase an outage. No missing gains are filled in. There is
no general watchdog for a stuck OS/filesystem or detached third-party descendants,
and sampling can miss short-lived CPU usage. Do not claim every possible process
failure is covered by these controlled cases.

## Reproduction and next operational trial

Validation: **195 focused Python tests passed** in 21.23s; **1,323 full-suite
tests passed**, zero skips, in 96.45s; **68 Node tests passed**; SQLite-backed
Chrome checks passed with 14 private screenshots. The first restricted full run
had one loopback-policy skip; the final run used normal loopback permissions.
`git diff --check` passed.

Changed public files: `tools/multi_alpha.py`, `src/exp_tracker/metrics.py`,
`tests/test_multi_alpha.py`, `tests/test_metrics.py`, `tests/test_video.py`,
`tests/test_shadow_capture.py`, `docs/continuous-alpha.md` and this document.
No public frontend, Store, recognition, progress or historical-query code changed.

Use new private output/base-temp names:

```powershell
.\.venv\Scripts\python -m pytest tests/test_multi_alpha.py tests/test_metrics.py tests/test_video.py tests/test_shadow_capture.py tests/test_shadow_neural_level.py tests/test_diagnostic_progress.py tests/test_diagnostic_history.py tests/test_rolling_history.py tests/test_historical_product.py -q --basetemp private/unattended-reliability/focused-new
.\.venv\Scripts\python private/unattended-reliability/integration.py
.\.venv\Scripts\python -m pytest -q -rs --basetemp private/unattended-reliability/full-new
node --test tools/*.test.mjs
node tools/product.browser.mjs http://127.0.0.1:8788 private/unattended-reliability/browser-new --verify-historical shiphtur
```

Next: a manually authorized, bounded two-channel trial at 20–30s with saved crops.
Inspect an actual unavailable-to-returning source if one naturally occurs; do not
create rapid reconnect traffic. Check operator commit results, actual cadence,
child-process count, disk growth and stopped/recovered website status. Keep all
OCR candidates diagnostic. Existing frozen successful captures are unchanged.
