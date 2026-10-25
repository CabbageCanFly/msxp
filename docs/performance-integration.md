# Staggered capture and resident Tesseract

**Current update:** resident Tesseract now enables
[layout-first HUD recognition](layout-first-hud.md) by default. The older detector
description below is retained for the original integration; use
`--no-layout-first-hud` to run it for comparison.

Integration of two researched, opt-in throughput changes into the schema-11 tracker
(`tools/multi_alpha.py`), for both legacy JSON configs and `--db-roster` mode. Both flags
are **off by default**. Without them, `capture_attempt` receives exactly the arguments it
did before, every Tesseract call runs the CLI through pytesseract, and run headers are
unchanged. `deploy/msxp-tracker.service` is unchanged.

Evidence comes from the archived research notes below. Nothing below was re-measured as a
whole-tracker capacity gain; that comparison happens separately on the VPS.

- [Throughput architecture research](throughput-architecture-research.md) and
  [staggered capture experiment](staggered-capture-experiment.md), originally
  `research/throughput-architecture` (`1db3c1e`), cover the scheduler model, validation
  against the real `schedule()` and the historical VPS A/B proposal.
- [Resident Tesseract evaluation](resident-tesseract-evaluation.md), originally
  `research/resident-tesseract` (`b619cd6`). On
  the Windows workstation, 535/535 OCR calls gave identical TSV. The operator-run Ubuntu
  parity run then gave 0 mismatches over 63 frames and 486 calls, and the isolated worker
  used 27.1 % less Tesseract CPU per frame. That figure covers HUD localization and level
  OCR only, not the whole attempt.

The notes preserve the original measurements and proposals; their old benchmark
commands and missing tools are not current runbooks. For retention, use the
[separate retention service](24h-retention.md), not the removed coordinator flag.

## `--stagger-capture`

Only first due times move. After its first slot, each channel keeps its own grid and all
existing scheduler rules apply unchanged:

- earliest due first, with rotating ties, and one attempt in flight per channel;
- whole elapsed slots are skipped and counted, never replayed as a backlog;
- 60-attempt rotation, `--stop-after-seconds`, retention maintenance, and pause and drain;
- `emit`, the single SQLite writer, status and identity switches stay on the coordinator
  thread.

Placement:

| Situation | First due time |
|---|---|
| Startup (JSON lanes, or the first DB-roster reconcile) | Lane *i* of *n* at `now + i × interval_i / n`, as validated in research. For 15 lanes at 30 s, that is 2 s apart. |
| Roster add, resume or setting change while other lanes run | The middle of the widest gap among the other active lanes' upcoming slots. Their slots are folded over the longest interval onto the new lane's own period, so its *later* slots avoid them too. Among equally wide gaps, the soonest wins. |
| Every lane paused, then one resumed | Immediately, as there is nothing to avoid. |

Active lanes are never moved. A changed channel is replaced only once its in-flight
attempt has drained, which `Reconciler` already enforces. With even spacing, the slot it
vacates is the widest gap, so it usually returns to its old phase. The cost is that a
lane's first capture can be delayed by up to one interval, once at startup, and once
after an add or resume. Without the flag, an added or resumed lane still starts at once.

Run headers record `stagger_capture: true` only when the flag is on, including rotated
and automatically switched runs. `tools/summarize_capture_run.py` now also reports:

- `skipped_deadlines`, taken from the final summaries and not double counted;
- `p95_actual_interval_seconds` and `mean_scheduler_delay_seconds`;
- local frame age and stale frames;
- `identity_held_attempts`.

**`--ocr-python` fix.** The supplied path is made absolute but no longer passed through
`resolve()`. A Linux virtualenv's `bin/python` is a symlink to the base interpreter, and
following it lost the venv's RapidOCR packages.

## `--resident-tesseract`

### Architecture

- **Worker pool.** `tools/resident_tesseract.py` provides a `TesseractPool` of at most
  `min(--workers, 4)` worker processes. Each is `resident_tesseract.py --serve` with one
  libtesseract handle, and the library, tessdata and version come from the configured
  `tesseract` CLI. No engine runs in the tracker process.
- **Lazy, LIFO reuse.** Workers start on first use. Last-in, first-out reuse keeps warm
  workers busy, so another worker starts only when OCR calls actually overlap. Callers
  wait for a free worker. Four was chosen for the 4-vCPU VPS, since more concurrent
  Tesseract processes would only contend for the same cores.
- **Injection without monkeypatching.** `exp_tracker.recognition._ocr` checks a
  `ContextVar`, `ocr_engine`. `capture_attempt(..., tesseract=pool)` sets it around that
  attempt's `analyze` on the attempt's own thread and resets it afterwards. HUD
  localization (`scan` at 2× and 3×), `level_reading` and its `_read_field` fallback all
  pass through `_ocr`, so their preprocessing, token parsing (`_tokens`), multi-HUD merge
  and ambiguity rules are the same code. Nothing patches `pytesseract.image_to_data`.
- **Isolation.** Each `_ocr` call is one complete request and reply on one exclusively
  held worker. Concurrent captures therefore cannot receive each other's TSV. The page
  segmentation mode and the whitelist (even when empty) are set on every request. Results
  and the adaptive classifier are cleared after each one.
- **Bounds.** Requests carry 8-bit grayscale images of at most 20 M pixels; mode and size
  are checked before sending. A reply is limited to 8 MiB.
- **Timeouts.** A worker has 30 s to start and 10 s per request (pytesseract's own
  `timeout=10`).
- **Failure and recovery.**
  - A timeout, crash, EOF or oversized reply kills that worker and raises `CaptureError`.
  - The attempt then fails exactly as a CLI failure would: `localization_failed`, or
    `recognition_failed` with a `tesseract_worker_*` reason. It is never trusted.
  - The next call starts a fresh worker. No result is retried or substituted.
- **Shutdown.** `close()` kills every worker. A closed client refuses to restart, so an
  abandoned in-flight attempt cannot start a new process after shutdown. Workers also exit
  on EOF if the coordinator dies.
- **Thread limit.** Workers run with `OMP_THREAD_LIMIT=1`, as the CLI does under the
  coordinator.

### Startup and diagnostics

- **Preflight.** Before any database work, and also under `--check`, one worker starts
  and reports its identity. A missing library, a CLI/library version mismatch or a failed
  `Init3` stops the run with a clear message, for example: `Resident Tesseract unavailable
  (tesseract_worker_unavailable): RuntimeError: libtesseract not found; set
  MSXP_LIBTESSERACT ...`.
- **No system changes.** Nothing is installed or changed. On Ubuntu the library is
  `libtesseract.so.5`, which is part of `libtesseract5`, the dependency of
  `tesseract-ocr`. `MSXP_LIBTESSERACT` can name it explicitly.
- **Run headers** carry `resident_tesseract: {version, model_sha256, workers}`.
- **Attempt `timings`** add `tesseract_calls` and `tesseract_queue_wait_seconds`.
- **At shutdown** the coordinator prints `Resident Tesseract: {...}`: calls, total and
  maximum queue wait, and each worker's pid, starts, requests and failures.

### Unchanged

- The CLI path stays the default.
- `--resident-neural`, which reuses a RapidOCR process, is a separate option. The two
  combine freely, and DB-roster mode still always uses its resident neural worker.
- HUD caching stays off (`--hud-cache-seconds 0`), and every attempt still makes both
  full-frame passes.
- Character-name reading, identity holds, EXP trust and accounting, and level floors are
  not touched.
- The experimental batched scan (`_ocr_pages`), which no capture path uses, still calls
  the CLI.
- Connect → capture → disconnect is unchanged.

**Memory (Windows measurement):** about 74 MiB steady and 140 MiB peak per worker, so
roughly 0.3 GiB steady at 4 workers. These are persistent processes, replacing
CLI processes of about 104 MiB that previously lived only during each call.

## Measured and untested

- **Measured here:**
  - automated tests of the real scheduler and coordinator in both modes, with worker
    counts 1, 4, 6 and 8;
  - real Tesseract 5.4.0 parity on Windows for synthetic one- and two-HUD frames, in
    `scan` tokens, `locate` candidates and level readings.
- **Measured in research:** see the branches above.
- **Not measured:**
  - the resident pool under the full tracker on Ubuntu;
  - whole-attempt CPU and capacity gains;
  - queue waits with 6–8 capture workers sharing 4 Tesseract workers;
  - combined effects of both flags on the VPS.

## Examples

Legacy JSON config:

```sh
python tools/multi_alpha.py --config private/multi-alpha/config.json --ocr-python "$OCR" \
  --workers 4 --stagger-capture --resident-tesseract --resident-neural --continuous
```

Database roster, preflight first, then the run:

```sh
python tools/multi_alpha.py --db-roster private/multi-alpha/tracking.sqlite3 --port 8766 --continuous \
  --ocr-python "$OCR" --workers 4 --stagger-capture --resident-tesseract --check
python tools/multi_alpha.py --db-roster private/multi-alpha/tracking.sqlite3 --port 8766 --continuous \
  --ocr-python "$OCR" --workers 4 --stagger-capture --resident-tesseract
```

Either flag can be used alone. With `--resident-tesseract`, `--check` starts one local
Tesseract worker. It makes no network connection and no database change.

## Controlled offline smoke test

Run this from a bench checkout, never `/opt/msxp/app`, with production stopped through
its normal procedure. Use an existing local recording and NEW disposable databases.

1. Write `private/perf-smoke/a.json`. List 4 channels, `smoke1` to `smoke4`, each with
   `"source": "file"`, the same local recording, `"interval": 30` and an explicit
   `"character"`. Use `"database": "private/perf-smoke/a.sqlite3"` and port `8881`.
   Copy it to `b.json`, changing only the database to `b.sqlite3`.
2. Run the baseline, then both flags, under identical conditions:

   ```sh
   python tools/multi_alpha.py --config private/perf-smoke/a.json --ocr-python "$OCR" --workers 4 \
     --continuous --max-attempts 6 --exit-after-capture --log-root private/perf-smoke/runs-a
   python tools/multi_alpha.py --config private/perf-smoke/b.json --ocr-python "$OCR" --workers 4 \
     --continuous --max-attempts 6 --exit-after-capture --log-root private/perf-smoke/runs-b \
     --stagger-capture --resident-tesseract
   ```

3. Check the B run:
   - its startup printed the `Resident Tesseract:` identity line, with the expected
     library version and model hash;
   - its shutdown line shows at most 4 workers, `failures` 0 and small queue waits.
4. Summarize each run directory printed as `Private capture logs`, then compare
   `localization_seconds`, `visual_level_seconds`, `skipped_deadlines`,
   `p95_actual_interval_seconds` and the resources:

   ```sh
   python tools/summarize_capture_run.py private/perf-smoke/runs-a/<run>
   python tools/summarize_capture_run.py private/perf-smoke/runs-b/<run>
   ```

5. With the same frames, HUD counts (`localization.count`) and level readings should
   match between A and B. Local-video seek follows real elapsed time, though, so A and B
   may decode different frames. Use the research parity tool from `b619cd6` for exact
   frame-by-frame parity.
6. Delete only the `private/perf-smoke/` files this test created.
