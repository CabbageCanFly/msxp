# Parallel Python test audit

2026-10-19, Windows, Python 3.14.7, pytest 9.1.1, pytest-xdist 3.8.0.
The machine reports 16 physical / 24 logical CPUs and 31.7 GiB RAM. Start with
**two workers and `--dist=load`**, not `-n auto`. Parallel execution remains opt-in;
normal `python -m pytest` is still sequential.

## Static findings

| Area | Finding and consequence |
| --- | --- |
| SQLite | Store/server/product fixtures create databases under function-scoped `tmp_path`. Reused names such as `tracker.sqlite3` are separate files. WAL/locking tests deliberately share a database only inside their own test. No test opens a production database for mutation. |
| Files and cleanup | Synthetic inputs, generated video, review sheets and JSONL outputs use `tmp_path`, or `monkeypatch.chdir(tmp_path)` plus a patched tool `ROOT`. The `private/shared.sqlite3` name in `test_multi_alpha.py` is isolated this way. Its `unlink()` targets that synthetic database. No suite-wide recursive cleanup was found. |
| HTTP ports | Real test servers use `port=0` and the assigned `server_port`. The port-conflict test in `test_local_alpha.py` holds its own OS-assigned socket. Port 8788 in `test_video_preview.py` is a fake server, not a listener. |
| Temporary roots | xdist creates separate `popen-gw0` / `popen-gw1` directories under the invocation's base temp. Separate pytest invocations must also have different base temp directories: pytest clears a supplied `--basetemp`. Never point it at saved evidence. Use separate cache directories for benchmark invocations too. |
| Globals, environment, order | Changes to cwd, clocks, environment, import paths and module attributes use `monkeypatch` or explicit restoration. Workers are separate processes and run one test at a time. Imported fixtures remain function-scoped. The only explicit broader-scoped project fixtures are two read-only module-scoped sample datasets (`test_live_ocr.py`, `test_ocr_store.py`). No collection-time output creation, dynamically changing parametrization, session-wide writable fixture or deliberate cross-test ordering dependency was found. Static review cannot prove absence of order-dependent bugs. |
| Credentials and external resources | Twitch requests/authentication are mocked; auth fixtures use synthetic credentials and absent temporary `.env` paths. No live Twitch source is needed. Tesseract uses unique temporary-file prefixes; model/bank loads are read-only and caches are worker-local. |
| Saved evidence | Tests read saved screenshots/logs but do not overwrite the original fixtures. However, the four broad saved-log sweeps below can encounter an actively appended JSONL tail. That is an existing reader/writer race, independent of xdist; use stable evidence for a full regression run. |
| CPU/RAM and timing | Private OCR/classifier cases and saved-history parity sweeps are expensive. Native engines may use extra threads, and each worker has its own model/cache memory. Two workers are a measured starting point, not a claim that four or sixteen will help. The `samples`/`ocr` markers do not cover all expensive saved-log replays. |

The broad live-directory readers are:

- `tests/test_exp_inference_parity.py::test_exp_derived_outputs_match_for_saved_readings_and_synthetic_pairs`
- `tests/test_card_projection.py::test_saved_cards_match_reference`
- `tests/test_incremental_history.py::test_saved_logs_match_full_replay_while_streamed`
- `tests/test_publisher.py::test_saved_publications_match_reference`

Do not mutate or stop live tracking to make this audit pass. If those inputs are
still changing, defer these sweeps or explicitly deselect them for a development
run; do not describe such a run as the complete regression suite. Other tests
using specifically named old runs also require those inputs to remain stable.

## Timing-sensitive cases

Keep these two node prefixes (three parametrized cases) in a separate sequential
invocation for the initial rollout:

- `tests/test_shadow_capture.py::test_real_neural_timeout_reaps_worker`: 0.5-second
  worker timeout and a five-second call-duration bound. Its standalone Windows
  exit-ordering race is diagnosed below; it now waits at most two seconds for
  cleanup, checking PID plus creation time. Defensive `finally` cleanup also
  checks the command line before killing/waiting for this test's child. Keeping
  it sequential for the initial rollout is a precaution, not a fix for or an
  explanation of its previously intermittent assertion.
- `tests/test_video.py::test_real_hung_capture_children_timeout_and_are_reaped`:
  synthetic child processes, 0.15-second acquisition timeout and a six-second
  wall-clock bound. Files/processes are owned and isolated; CPU pressure is the
  reason to separate this test initially, not a discovered worker collision.

Also watch `test_server.py::test_api_reads_committed_snapshot_while_guarded_observation_is_written`
(two-second synchronization waits), the local launcher's released-port rebind
check, and `test_publisher.py` background-thread waits under load. They already
isolate their databases/ports and do not currently warrant blanket serialization.

`--dist=load` balances independent functions and parametrized cases. `loadscope`
or `loadfile` would pin expensive files to one worker without fixing external
resource races. `xdist_group` assigns tests to one worker; it does **not** stop
other workers, so it is not a replacement for a separate sequential command.
See the [official distribution guide](https://pytest-xdist.readthedocs.io/en/stable/distribution.html)
and [worker/fixture isolation notes](https://pytest-xdist.readthedocs.io/en/stable/how-to.html).

## Standalone Windows worker-timeout follow-up

The operator reproduced two passes followed by a failure in three independent,
single-test pytest invocations, with the timeout exception and five-second bound
both correct. This is not evidence of an xdist or CPU-contention defect.

Inspection of the installed CPython 3.14.7 `subprocess.run()` confirms that it
kills the launched process, calls `communicate()` again on Windows, and waits
before propagating `TimeoutExpired`. However, `.venv/Scripts/python.exe` is a
Windows venv redirector: the launched PID differs from the Python worker's PID.
The [matching CPython launcher source](https://github.com/python/cpython/blob/v3.14.7/PC/venvlauncher.c#L360)
assigns that worker to a job with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Killing
the launcher initiates job-child termination, but waiting for the launcher does
not mean the worker's process object is already signaled at that exact instant.

Eight immediate-state probes recorded worker identity before timeout to avoid
post-timeout filesystem observation delays. All eight showed a different launcher
and worker PID. At roughly 0.15-0.18 ms after `run()` raised, the original worker
identity was still present and `WaitForSingleObject(handle, 0)` returned
`WAIT_TIMEOUT` (258). Seven were gone or signaled at the next check around
1-1.5 ms; the eighth was gone/signaled by the 5 ms check. These are exit-state
measurements, not a measurement of the original pytest failure frequency.

This reproduced a briefly unfinished job-child exit, not PID reuse or an observed
long-lived orphan. Other snapshots could still open an already-signaled process
object even after `pid_exists()` became false: kernel-object lifetime, PID-list
presence and execution state are different observations. The historical reported
PID alone cannot establish which state that particular process was in.
[Windows documents the signaled exit state and retained process objects](https://learn.microsoft.com/en-us/windows/win32/procthread/terminating-a-process).

The test now has the synthetic worker record PID and creation time. It uses
`psutil.Process.wait(timeout=2)`, whose installed Windows implementation waits on
the process and additionally polls for PID disappearance. If this times out, the
test still fails when the same process identity is running. A changed creation
time means the original worker is gone; the replacement is not waited on or
killed. The 0.5-second subprocess timeout, expected `neural_timeout`, original
five-second call bound and guarded failure-path cleanup remain enforced.

Verification after the fix:

- **25/25 consecutive independent single-test invocations passed**, with xdist
  disabled, no retries and fresh temporary roots: 0.62-0.68 seconds each as
  reported by pytest. No skips occurred.
- A deliberately surviving synthetic worker failed the new assertion after
  **2.102 seconds**, then was killed/reaped by defensive test cleanup.
- A simulated reused PID with a different creation time was neither waited on
  nor killed.

Lifecycle JSON, probe scripts, negative controls and all repeated-run output are
ignored under `private/windows-worker-timeout-20261019/`. Only the test and this
audit document changed. No production subprocess/OCR cleanup defect was
demonstrated, and none was modified. No full-suite or parallel rerun was needed.

## Niru publisher parity follow-up

The reported sequential failure retained 66 runs and 3,055 attempts, ending at
replay step 3,120 (`7bb8ee75528c4a2899ea7cfb21607a0a:10`,
2026-10-19 14:44:51.807948 UTC). An immutable reconstruction initially passed;
the captured attempt payloads and character/session association matched exactly.
A later unforced replay failed on `player.twitch.checked_at`, not EXP/history.

The publisher fixture pinned UTC but left `StreamAvailability` on real monotonic
time. After 60 real seconds, the reference's separate status-cache lookup could
expire between publication and comparison. The two sides then described different
status-check batches. Forcing that expiry reproduced the failure at step 3,120:
`checked_at` was `2026-10-18T09:45:03.531676+00:00` in the publication and
`2026-10-19T14:44:51.807948+00:00` in the reference. Only `checked_at` and
`valid_until` differed; publisher errors were zero and EXP/checkpoint output matched.

The fixture now injects a status-cache clock driven by replay time. A small
regression simulates a slow comparison crossing the real TTL, then checks that
advancing replay time still expires the cache. Production publishing, inference,
public endpoint calculations and trusted accounting are unchanged. Saved publisher
tests read each JSONL once at the start and retain the full comparison; failures
write the first differing path/values, replay context, revision keys and publisher
error status to `publication-mismatch.json` under that test's temporary directory.
Private snapshots, hashes and detailed results stay under
`private/niru-publisher-parity/`.

Verification: the forced-expiry retained-prefix replay failed before the clock fix
and passed afterward in 78.59 s, with all 17 comparisons equal. The normal Niru
publisher test passed in 98.16 s. The focused publisher, checkpoint, ETA and mocked
Twitch-status run passed 95 tests (six saved-log sweep cases deselected). No skips
occurred. Retained input/database hashes stayed unchanged. No full-suite rerun or
repeat of the already-passing expensive Niru incremental replay was needed.

A global 120-second pytest-timeout is too short for some legitimate saved-history
replays: the operator measured the passing Niru incremental replay at 265.54 s.
Use `--timeout=0` for these parity investigations; no timeout configuration or
passing incremental-history test was changed.

## Limited verification

Eight representative files exercised SQLite, actual HTTP sockets and viewer
threads, mocked launcher lifecycles, generated FFmpeg video, subprocesses,
synthetic authentication and preview filesystem writes. No OCR or private-sample
tests were run. The two benchmark runs were sequential, not competing processes.

| Invocation | Result | pytest elapsed | Whole command elapsed |
| --- | --- | ---: | ---: |
| `-n 0` | 204 passed, 4 deselected | 32.55 s | 33.04 s |
| `-n 2 --dist=load` | Same 204 tests passed | 17.59 s | 18.08 s |
| Separate real timeout/reaping tests, `-n 0` | 3 passed | 1.00 s | Not benchmarked |

No skips occurred; private-image/OCR tests were excluded, not validated. A forced
assertion-failure probe also confirmed the new defensive cleanup reaped its
synthetic child. Test output and timing JSON are ignored under
`private/pytest-xdist-audit-20261019/`.

This single comparison is about **1.83x faster (45% less wall time)**. It does not
predict full-suite speedup, peak memory or reliability at four workers. No full
parallel suite was run, and no production/acquisition/OCR/public-statistics code
was changed.

## PowerShell commands

Run from the repository root. Install only the new development plugin if the
environment already exists:

```powershell
.\.venv\Scripts\python.exe -m pip install "pytest-xdist>=3.8,<4"
```

Repeat the same limited comparison, with fresh temporary roots. Run the two
commands one after the other, keep the workload/permissions identical, and check
both outputs passed the same tests. Repeating in reverse order helps assess
cache/startup noise.

```powershell
$py = '.\.venv\Scripts\python.exe'
$files = @(
    'tests/test_store.py', 'tests/test_server.py', 'tests/test_video.py',
    'tests/test_capture.py', 'tests/test_twitch_auth.py',
    'tests/test_local_alpha.py', 'tests/test_multi_alpha.py',
    'tests/test_video_preview.py'
)
$omitVideoTiming = '--deselect=tests/test_video.py::test_real_hung_capture_children_timeout_and_are_reaped'
$root = "private/pytest-bench-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $root -ErrorAction Stop | Out-Null

Measure-Command {
    & $py -m pytest -q -ra -n 0 @files -m 'not ocr and not samples' $omitVideoTiming --basetemp "$root/seq" -o "cache_dir=$root/seq-cache" *> "$root/sequential.txt"
}
Get-Content "$root/sequential.txt" -Tail 5

Measure-Command {
    & $py -m pytest -q -ra -n 2 --dist=load @files -m 'not ocr and not samples' $omitVideoTiming --basetemp "$root/par" -o "cache_dir=$root/par-cache" *> "$root/parallel.txt"
}
Get-Content "$root/parallel.txt" -Tail 5
```

For fast development, use the parallel command above or narrow `$files` to the
modules being changed. For the next **full regression trial**, only when the saved
inputs are stable, run all other tests with two workers and the three process
cases separately. These commands are recommendations, not an already-run result:

```powershell
$py = '.\.venv\Scripts\python.exe'
$serial = @(
    'tests/test_shadow_capture.py::test_real_neural_timeout_reaps_worker',
    'tests/test_video.py::test_real_hung_capture_children_timeout_and_are_reaped'
)
$omit = $serial | ForEach-Object { "--deselect=$_" }
$root = "private/pytest-full-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $root -ErrorAction Stop | Out-Null

& $py -m pytest -q -ra -n 2 --dist=load @omit --basetemp "$root/parallel" -o "cache_dir=$root/parallel-cache"
$parallelExit = $LASTEXITCODE
& $py -m pytest -q -ra -n 0 @serial --basetemp "$root/serial" -o "cache_dir=$root/serial-cache"
if ($parallelExit -ne 0 -or $LASTEXITCODE -ne 0) { throw 'Regression tests failed' }
```

The existing fully sequential reference remains `python -m pytest -q -ra -n 0`.
Try four workers only after a stable-input two-worker regression run passes and
its timing/memory results justify another limited comparison. Do not add a global
parallel `addopts`, locking service or worker-specific database framework.
