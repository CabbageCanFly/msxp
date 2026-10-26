# Experiment 1: opt-in staggered capture scheduling

> **Archived research.** Shipped as the opt-in `--stagger-capture` flag; see
> [staggered capture and resident Tesseract](performance-integration.md). `tools/simulate_throughput.py` and
> `tools/validate_throughput_model.py` were not kept, so "Model" and "Harness" figures below are a record.

> The scheduling details and proposed commands below describe the original
> experiment. The integration guide covers current behavior, including dynamic
> roster changes. The historical runbook uses removed tools, branches and
> `--retention-24h`; use [separate retention](24h-retention.md) for current operation.
> Do not run the archived stop/start or benchmark commands as deployment guidance.

Follows [throughput architecture research](throughput-architecture-research.md), §6.
**Historical status: implemented and tested, with a VPS A/B benchmark proposed.**
The predicted 30 s result at 8 workers is a model output. It has not been measured on
the VPS. Nothing was deployed, committed or pushed, and no Twitch, SSH or production
database was used.

Labels used below:

- **Test**: an automated test of the real code.
- **Harness**: the real `schedule()` with synthetic service times on this workstation.
- **Model**: `tools/simulate_throughput.py`.
- **Expected**: not yet measured.

## What changed

`tools/multi_alpha.py --stagger-capture` is off by default. When it is on, lane *i* of
*n* enabled lanes gets its first due time at `started + i × interval_i / n`.

- **Equal intervals** spread evenly. For 15 lanes at 30 s, first captures are 2 s apart.
- **Mixed intervals:** each lane is offset by the same fraction of **its own** interval.
  Every lane therefore starts inside its first period (`offset < interval`) and is never
  skipped at startup. Fractions are spread evenly across lanes, but the absolute phases
  of lanes with different intervals still drift relative to one another, as they do today.
- **Disabled lanes** are removed by `load_config` before scheduling and take no phase.
- **Unchanged:** after the first deadline, each lane keeps its own grid, and every
  existing rule applies exactly as before:
  - earliest due first, with rotating ties;
  - one attempt in flight per lane;
  - whole elapsed slots skipped;
  - `stop_after_seconds`, rotation every 60 attempts, retention maintenance;
  - coordinator-only `emit` and SQLite writes;
  - interrupt handling.
- The coordinator status `next_due_at` shows each lane's offset.
- Run headers record `stagger_capture: true` only when the flag is on, including the
  header of an automatically switched run. The startup line says the first captures are
  staggered. Default headers are byte-for-byte unchanged.

The flag adds no workers, HUD cache, batching, resident process or capture option.
`capture_attempt` receives the same arguments, and local-video `seek` is still the
actual elapsed time, so no older frame is requested. Freshness checks, character-name
votes, level floors, identity holds and attribution code are untouched.

**Cost:** each lane's first capture is delayed by up to `interval × (n−1)/n`. For 15 lanes
at 30 s that is 28 s, once, at process start.

`tools/summarize_capture_run.py` now also reports:

- `p95_actual_interval_seconds`;
- `skipped_deadlines`. The scheduler's counter is cumulative per channel for the whole
  process, so this takes each channel's maximum over its attempt records **and** its
  final summary record, then sums the channels. The final summary matters because
  `finish()` can skip further slots after an attempt record was written, and only the
  end-of-run summary carries that total. Rotation and automatic-switch summaries carry no
  counter, and nested run directories map to their channel, so nothing is double counted;
- `mean_scheduler_delay_seconds`;
- `p95_local_age_seconds`, `max_local_age_seconds` and `stale_local_frames`, read from
  `identity_hold.evidence` when an attempt was held;
- `identity_held_attempts`.

On the 15-lane name-OCR run from the earlier character-OCR review it reports a
**14.0 s mean scheduler delay** at a requested 60 s with 3 workers. That is the
shared-deadline burst this experiment targets.

## Tests

`tests/test_staggered_schedule.py` drives the real `schedule()` and `main()`. Single-worker
cases run on a fake clock and are exact. Multi-worker cases use real threads with
millisecond intervals.

| Requirement | Test |
|---|---|
| 1. Default unchanged | `test_default_keeps_one_shared_first_deadline`: exact start and due times. `test_coordinator_default_is_unchanged_and_unrecorded`: no header key, same `capture_attempt` arguments. Existing capture-performance and multi-alpha suites pass unchanged. |
| 2. Phases distributed | `test_stagger_spreads_first_deadlines_and_never_starts_early`: 0, 3, 6 s at a 9 s interval. Coordinator: alpha 0 s, beta 7.5 s at 15 s. |
| 3. Never early | The same test (start ≥ due, fake clock), plus the threaded test (6 and 8 workers). |
| 4. Workers bounded | `test_stagger_keeps_workers_bounded_order_rotation_and_coordinator_writes`: peak ≤ N, at most one attempt per lane. |
| 5. Per-lane order | The same test: indices 1–60 then 1, 2 after rotation, for every lane. |
| 6. Skip accounting | `test_stagger_skips_whole_slots_on_each_lane_grid`: due times stay on each lane's own phase, and the final due equals `offset + interval × (attempts + skipped)`. |
| 7. Rotation and persistence | The threaded test: rotation and `emit` on the coordinator thread. Coordinator test: 4 committed SQLite attempts and recorded headers. |
| 8. Failures and interrupts | `test_stagger_failures_and_interrupts_keep_existing_records`: `capture_process_failed` and `operator_interrupted` records; lanes not yet due are marked interrupted with 0 attempts. |
| 9. Mixed intervals | `test_mixed_intervals_each_start_inside_their_own_first_period`: offsets 0, 20/3 and 20 s for intervals 10, 20 and 30 s. |
| 10. No new stale-frame or attribution risk | `seek` equals the actual elapsed time. `capture_attempt` arguments are identical with the flag. A disabled lane takes no phase (coordinator test, both variants). |
| `stop_after_seconds` | `test_stagger_stop_after_seconds_never_starts_a_later_phase` |
| Summary metrics | `test_run_summary_reports_cadence_freshness_and_held_evidence`; `test_run_summary_takes_final_skips_from_the_end_of_run_summary_without_double_counting` (rotation, switch and end-of-run records); `test_final_summary_skip_count_can_exceed_the_last_attempt_record` (the real scheduler: last attempt record 2, final total 4) |

## Does the model predict the real scheduler? (harness, workstation)

`tools/validate_throughput_model.py` runs the **real** `schedule()` with real worker
threads and the real clock. Each `perform()` sleeps for a capture wait, then consumes CPU
on a shared processor-sharing virtual CPU (K = 3). Draws come from the same distributions
as the model, with durations scaled ×0.1 and reported unscaled. Each configuration ran 4
seeds; the model averages 20. Settings: 15 lanes, 5 attempts, requested 30 s,
capture 6.06 s, P = 5.4.

| Workers, stagger | Real scheduler: mean / max (range over seeds) / skips | Model: mean / max / skips | VPS measured (stagger off) |
|---|---|---|---|
| 4, off | 43.9 / 61.4 (50.6–72.8) / 34 | 43.6 / 65.1 / 34.4 | 43.6 / 49.7 / 33 |
| 4, on | 44.2 / 52.1 (48.2–55.6) / 30 | 43.9 / 53.1 / 30.0 | |
| 6, off | 35.7 / 63.6 (59.5–68.9) / 14.5 | 35.8 / 63.7 / 15.0 | 36.8 / 44.8 / 18 |
| 6, on | 32.3 / 42.9 (37.6–56.2) / 0.25 | 32.2 / 40.4 / 0.85 | |
| 8, off | 34.5 / 58.4 (45.7–63.8) / 11.5 | 34.9 / 59.6 / 13.2 | 35.5 / 59.9 / 13 |
| 8, on | **30.0 / 31.4 (30.2–32.2) / 0** | 30.0 / 31.5 / 0 | |

What the model gets right:

- **The simulator copies `schedule()` faithfully.** On identical synthetic workloads,
  mean intervals agree within 0.5 s and skip counts within 1.7.
- **The staggering effect comes from the real code.** It is not an artefact of the model.
- **Staggering does not help at 4 workers.** With four workers the run is worker-bound
  (≈44 s either way). Staggering only pays when workers are not the constraint.

Where it is unreliable:

- **Maximum interval is a tail statistic.** One run of 60 intervals varies by up to 23 s
  between seeds. The measured VPS 6-worker maximum (44.8 s) lies below every harness
  seed (59.5–68.9 s). The workload model is the likely cause, not the scheduler: the
  capture and CPU shapes come from three workstation recordings, and VPS durations may
  be less dispersed. Only the staggered 8-worker maximum, which comes from cadence rather
  than skips, is narrow enough to use as an acceptance threshold.
- **CPU-stage wall time** reads 0.15–0.4 s lower in the harness than in the model. That
  comes from polling granularity, and the comparisons above are unaffected.
- **Everything rests on the VPS calibration** (K = 3 effective cores, P = 5.4 CPU-s).
  The harness cannot test that. If staggering removes burst contention, the CPU stage
  should also get faster on the VPS. The calibrated model already predicts 6.7 s against
  9.3 s for 8 workers.

**Unverified expectations for the benchmark below.** The model, unchanged, predicts:

| Run | Mean / max / skips |
|---|---|
| 6 workers, off | ≈35.7 / 64 / 15 |
| 6 workers, on | ≈32.2 / 40 / 1 |
| 8 workers, off | ≈34.9 / 60 / 13 |
| 8 workers, on | ≈30.0 / 31.5 / 0 |

Name OCR adds ≈0.1 CPU-s per attempt over the calibration runs. The model was not
re-tuned for this experiment.

## VPS A/B benchmark (operator-run)

Same isolated checkout and transient-unit sandbox as the 2026-10-20 runs. All four runs
share these settings:

- the 15-lane, one-video, 30 s configuration;
- a new directory and database each;
- `--resident-neural --automatic-characters`, so name OCR and automatic attribution run
  as on main;
- `--retention-24h`;
- 10 attempts per channel.

Only `--workers` and `--stagger-capture` differ. Each run takes ≈6 minutes.

How production and Twitch stay protected:

- **No network:** the unit runs with `PrivateNetwork=yes`, and the config builder rejects
  any non-file or `authorized` source.
- **Read-only outside the bench:** `ProtectSystem=strict` with
  `ReadWritePaths=/opt/msxp/bench/private` only. The production checkout, its database
  and the installed venvs are read-only to the unit.
- **Isolated outputs:** every run gets a new database under `private/bench/NAME/`, port 0
  and `--public-only`.
- **Production must be stopped:** `abrun` refuses to start while `msxp-tracker` is active
  or outside `/opt/msxp/bench`.

The function was syntax-checked with `bash -n`. On Windows Git Bash, with stubbed
`systemd-run`, `sudo` and `journalctl`, it was checked to:

- exit 1 and stop an `&&` chain when the unit fails;
- refuse a reused NAME;
- leave no monitor running after success or failure.

The embedded config validator was run with real Python against a missing video, a Twitch
source, an `authorized` flag, a wrong lane count and an existing output file. Each was
refused before anything was written. The `vmstat` and PSI parsers were checked on a
sample that includes the newer `gu` column. None of it has run on Ubuntu.

**0. Bring the reviewed commit to the bench checkout.** After the commit is approved, on
Windows:

```sh
git bundle create msxp-stagger.bundle research/throughput-architecture   # then copy it to the VPS /root/
```

On the VPS:

```sh
sudo -i                      # Everything below runs in this one root shell.
cd /opt/msxp/bench
git fetch /root/msxp-stagger.bundle research/throughput-architecture
git checkout --detach FETCH_HEAD && git log -1 --oneline     # Record this hash.
grep -q -- '--stagger-capture' tools/multi_alpha.py && echo flag-present
```

**1. Quiet the machine, and record it once.**

```sh
systemctl stop msxp-tracker.service msxp-backup.timer
systemctl is-active msxp-tracker.service msxp-backup.timer || true   # Expect "inactive" twice.
nproc; lscpu | grep -E 'Model name|Thread|Core|Socket|Hypervisor|MHz|NUMA'
cat /proc/loadavg; free -m
tesseract --version 2>&1 | head -6
sha256sum /usr/share/tesseract-ocr/*/tessdata/eng.traineddata
command -v mpstat || echo 'mpstat absent: vmstat is enough (do not install packages for this run)'
```

**2. Define the helpers** by pasting this whole block into the same root shell:

```sh
cd /opt/msxp/bench
PY=/opt/msxp/app/.venv/bin/python                        # Installed app venv, used read-only.
OCR_PY=/opt/msxp/app/private/rapidocr/.venv/bin/python   # Installed RapidOCR worker, passed explicitly.
SRC=private/bench/sustain30-w4.json                      # The 2026-10-20 15-lane local-video configuration.

vmsummary() {  # vmsummary FILE: means by column NAME from vmstat's own header; skips the since-boot row
  awk 'BEGIN { split("us sy id wa st", keys) }
       / us +sy +id / { for (i = 1; i <= NF; i++) col[$i] = i; next }
       ("r" in col) && $1 ~ /^[0-9]+$/ {
         if (!rows++) next
         for (k = 1; k <= 5; k++) sum[keys[k]] += $col[keys[k]]
         if ($col["r"] > rmax) rmax = $col["r"]; n++ }
       END { if (!n || !("st" in col)) { print "vmstat: no samples or no st column" > "/dev/stderr"; exit 1 }
             for (k = 1; k <= 5; k++) printf "%s=%.1f%% ", keys[k], sum[keys[k]] / n
             printf "runnable_max=%d samples=%d\n", rmax, n }' "$1"
}

psi_total() { sed -n 's/^some .*total=\([0-9]*\)$/\1/p' "$1"; }

abrun() (  # abrun NAME WORKERS [--stagger-capture]. A subshell: set/trap never leak into your shell.
  set -euo pipefail -o noclobber
  name=$1; workers=$2; shift 2
  case $name in ''|*[!A-Za-z0-9-]*) echo "NAME must be letters, digits and dashes" >&2; exit 1;; esac
  [ "$(pwd -P)" = /opt/msxp/bench ] || { echo "run from /opt/msxp/bench, never /opt/msxp/app" >&2; exit 1; }
  if systemctl is-active --quiet msxp-tracker.service; then echo "production tracker is running; stop it first" >&2; exit 1; fi
  out=private/bench/$name
  sudo -u msxp mkdir "$out"    # Fails if NAME was used before, so nothing is ever overwritten.
  # A wrong OCR environment would not stop the run, only fail every neural read: verify it first.
  sudo -u msxp "$OCR_PY" -I -c "from importlib.metadata import version as v
assert v('rapidocr') == '3.10.0', 'expected the pinned RapidOCR 3.10.0, found ' + v('rapidocr')
print('RapidOCR', v('rapidocr'), 'onnxruntime', v('onnxruntime'))"
  monitors=
  trap 'kill $monitors 2>/dev/null || true' EXIT   # Also on any failure below.
  sudo -u msxp env PYTHONDONTWRITEBYTECODE=1 "$PY" -I - "$SRC" "$out" <<'EOF'
import json, sys
from pathlib import Path
source, out = sys.argv[1:]
config = json.load(open(source, encoding='utf-8-sig'))
streams = [s for s in config['streams'] if s.get('enabled', True)]
if len(streams) != 15:
    sys.exit(f'Expected 15 enabled lanes, found {len(streams)}')
for stream in config['streams']:
    if stream.get('source') != 'file' or stream.get('authorized'):
        sys.exit(f"{stream.get('channel')}: local video only; no Twitch sources in a benchmark")
    path = Path(stream['file']).resolve()  # Relative paths resolve against /opt/msxp/bench, as multi_alpha does.
    try:
        with open(path, 'rb') as video:   # Run as msxp: proves the service account can read it.
            video.read(1)
    except OSError as error:
        sys.exit(f'{path}: not readable by msxp ({error.strerror})')
    stream.update(file=str(path), interval=30)
config.update(database=f'{out}/tracking.sqlite3', port=0)
with open(f'{out}/config.json', 'x', encoding='utf-8') as handle:  # Never overwrite.
    json.dump(config, handle, indent=1)
print(f'{len(streams)} lanes; videos readable by msxp:', *sorted({s["file"] for s in streams}), sep='\n  ')
EOF
  sudo -u msxp env PYTHONPATH=/opt/msxp/bench/src PYTHONDONTWRITEBYTECODE=1 "$PY" tools/multi_alpha.py \
    --config "$out/config.json" --check --automatic-characters --ocr-python "$OCR_PY"
  cat /proc/pressure/cpu > "$out/psi-before"
  vmstat -n -w -t 5 > "$out/vmstat" & monitors=$!
  if command -v mpstat >/dev/null; then mpstat -P ALL 5 > "$out/mpstat" & monitors="$monitors $!"; fi
  if ! systemd-run --unit="msxp-bench-$name" --wait --collect \
    -p User=msxp -p Group=msxp -p WorkingDirectory=/opt/msxp/bench \
    -p ProtectSystem=strict -p ReadWritePaths=/opt/msxp/bench/private -p PrivateTmp=yes -p PrivateNetwork=yes \
    -p KillSignal=SIGINT -p KillMode=mixed -p TimeoutStopSec=60 -p RuntimeMaxSec=900 -p MemoryAccounting=yes \
    -E HOME=/opt/msxp -E PYTHONPATH=/opt/msxp/bench/src -E PYTHONDONTWRITEBYTECODE=1 \
    -E PYTHONUNBUFFERED=1 -E OMP_THREAD_LIMIT=1 \
    "$PY" tools/multi_alpha.py --config "$out/config.json" --continuous --retention-24h \
      --resident-neural --automatic-characters --ocr-python "$OCR_PY" \
      --max-attempts 10 --exit-after-capture --public-only --workers "$workers" "$@" 2>&1 | tee "$out/unit"
  then
    journalctl -u "msxp-bench-$name.service" -o cat --no-pager > "$out/log" || true
    echo "$name: FAILED (unit or tee exit status); read $out/unit and $out/log" >&2; exit 1
  fi
  kill $monitors 2>/dev/null || true; monitors=
  cat /proc/pressure/cpu > "$out/psi-after"
  journalctl -u "msxp-bench-$name.service" -o cat --no-pager > "$out/log"
  # Also require the service's own clean exit, not only systemd-run's status.
  grep -Eq 'code=exited[,/] *status=0(/SUCCESS)?' "$out/unit" || { echo "$name: FAILED; read $out/unit and $out/log" >&2; exit 1; }
  run=$(sed -n 's/^Private capture logs: //p' "$out/log" | tail -1)
  [ -n "$run" ] || { echo "$name: no run directory in $out/log" >&2; exit 1; }
  echo "run directory: $run" > "$out/run"
  sudo -u msxp env PYTHONPATH=/opt/msxp/bench/src PYTHONDONTWRITEBYTECODE=1 \
    "$PY" tools/summarize_capture_run.py "$run" > "$out/summary.json"
  cat "$out/summary.json"
  grep -E 'Capture RUNNING|frames, .*SQLite attempt commits|Capture stopped' "$out/log"
  echo "vmstat: $(vmsummary "$out/vmstat")"
  echo "CPU pressure (some) stalled: $(( ($(psi_total "$out/psi-after") - $(psi_total "$out/psi-before")) / 1000000 )) s"
)
```

`abrun` is a subshell with `set -euo pipefail -o noclobber`:

- a failure anywhere stops it with a non-zero status, and the `EXIT` trap stops the
  monitors;
- a failed unit is caught twice, through the pipeline status and through the service's
  own `status=0/SUCCESS` line;
- `mkdir` of `private/bench/NAME` fails if NAME was used before, so no earlier output can
  be overwritten;
- before capture it verifies, as `msxp`:
  - the RapidOCR interpreter passed explicitly (`--ocr-python`), not the bench symlink;
  - all 15 videos are readable by `msxp`;
  - the `multi_alpha --check` preflight passes.

**3. Run the four configurations, chained so a failure stops the sequence.** The order
alternates the flag at each worker count, so slow drift does not favour one setting.

```sh
abrun ab30-w6-off 6 &&
abrun ab30-w6-on  6 --stagger-capture &&
abrun ab30-w8-off 8 &&
abrun ab30-w8-on  8 --stagger-capture &&
echo 'ALL FOUR RUNS COMPLETED'
# Recommended if any criterion below is borderline, since the maximum interval is noisy:
# the same four again in reverse order with new names (ab30-w8-on-b, ab30-w8-off-b, ab30-w6-on-b, ab30-w6-off-b).
```

If a run fails, fix the cause and continue from that run under a **new** NAME. Never
reuse or delete a failed run's directory before reading it.

**4. Restore production** with the normal controlled procedure, if it should run again:

```sh
systemctl start msxp-tracker.service msxp-backup.timer
```

**5. Paste back** each run's terminal output: the unit's "CPU time consumed / Memory
peak" lines, `summary.json`, the per-lane lines, the `vmstat:` and CPU-pressure lines.
Also paste the step 0–1 output. Use a scratch folder outside the repository.

Every run directory also keeps the raw `vmstat`, `mpstat`, `psi-*`, `unit`, `log`, `run`
and `config.json`. The `vmstat:` line averages `us`, `sy`, `id`, `wa` and `st` by
**column name**, read from vmstat's own header, and skips the since-boot first row. It
fails if there is no `st` column.

To remove everything afterwards: the `private/bench/ab30-*` directories, plus the run
directory named in each `run` file.

## Acceptance criteria

Correctness gates. Any failure stops the experiment, whatever the cadence result:

- Each `abrun` exits 0; 150/150 attempts committed; every per-lane line shows
  `capture failures=0`.
- `stale_local_frames` = 0 and `max_local_age_seconds` < 15.
- Per-lane `OCR failures` and the `recognition_failed` / `malformed_or_unavailable`
  counts no higher with staggering than without. Frames differ between runs because
  `seek` follows real time, so compare rates, not individual readings.
- `neural_seconds` is present (the verified RapidOCR worker actually ran).

Cadence, 8 workers, staggering on:

- **mean ≤ 31 s, maximum ≤ 35 s, `skipped_deadlines` ≤ 2, against a run without
  staggering that reproduces ≈35 s.** Only then may the docs say 30 s was achieved
  offline on the VPS, and only for this configuration.

How to read the result:

| Result | Meaning |
|---|---|
| Criteria met, CPU-stage wall drops (≈9 → ≈7 s) | Bursts were the main cause of the gap. Keep the flag. Consider making it the default in a separate, reviewed change. |
| Mean improves but stays 31–33 s, with `st` > 5 % or `id` ≈ 0 | Capacity is lower than modelled. Answer the effective-core question (steal, SMT, monitor) before Experiment 2. |
| Mean > 33 s at 8 workers with staggering | The calibrated model is wrong for the VPS. Do not proceed on its predictions; re-measure the stage timings first. |
| 6 workers with staggering ≈ 8 workers without | Supports using fewer workers (less memory, fewer connections) with staggering. |

## Not covered

- Live Twitch: Streamlink start-up, real segment latency, offline channels.
- Publisher and viewer load.
- Retention on a full-day database.
- Mixed per-channel intervals at scale: unit-tested only.
- Making the flag the default in production.
