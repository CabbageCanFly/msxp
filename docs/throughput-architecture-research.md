# Throughput architecture research

> **Archived research.** Its first experiment shipped as the opt-in `--stagger-capture` flag; see
> [staggered capture and resident Tesseract](performance-integration.md). The model `tools/simulate_throughput.py`
> and its test were not kept, so "Model" figures below are a record, not reproducible from main.

> This is a snapshot of the baseline and constraints below, not a statement of
> current capacity or deployment status. Proposed architectures, remaining work
> and commands are historical; the integration guide covers the changes that
> subsequently shipped. Keep workstation measurements, VPS measurements and model
> estimates separate when citing these results.

Baseline: `b894081` (main, including character-name OCR and automatic attribution).
Goal: ~15 MapleStory Classic channels at a 20–30 s capture interval on the fixed
4 vCPU / 8 GB VPS. Everything here is offline. Nothing was deployed, committed or pushed,
and no SSH, Twitch or production database was used.

Every figure is labelled with where it comes from:

- **VPS**: the operator's 2026-10-20 benchmark transcripts. That code predates the name-OCR merge.
- **WS**: this workstation (i7-13700K, Windows 11, Tesseract 5.4.0).
- **Model**: `tools/simulate_throughput.py`, calibrated to the VPS runs.
- **Estimate**: arithmetic from the above. Not observed.

## Answer first

1. **The ceiling is CPU, and the gap at 30 s is mostly scheduling.** One attempt costs
   ≈6.0 CPU-s on the VPS. About 5.4 CPU-s of that is the OCR stage, and two full-frame
   Tesseract passes are most of it. Calibrated against the three VPS runs, the OCR stage
   effectively gets **≈3 cores, not 4**. That puts the offline floor for 15 lanes at
   **≈27 s** (15 × 5.4 / 3), whatever the capture/OCR architecture. The 8-worker run
   reached only 35.5 s at a requested 30 s because every lane shares one due-time grid.
   Attempts arrive in bursts, the bursts cause contention, and late lanes then skip
   whole slots.
2. **A full capture/OCR split pipeline is not the best first move.** Processor sharing
   in today's workers is already work-conserving: CPU per attempt was flat from 4 to 8
   workers. A split cannot raise the CPU ceiling. Its real benefits are lower frame age,
   less memory and a small reduction in oversubscription (−4–7 % throughput measured on
   WS at 6–8 threads). The safe minimal form of it, bounding Tesseract concurrency only,
   falls out of recommendation 2.
3. **Top three, in order:**
   1. **Stagger lane phases.** About one line of code. Model: 30.0 s at a requested 30 s
      with 8 workers, with no skips, against 34.9 s today (35.5 s measured).
   2. **Resident Tesseract through the libtesseract C API, in a bounded worker-process
      pool.** Measured token-identical on 42/42 calls (WS). Estimated −24 % OCR-stage CPU.
      This is the only change that moves the ceiling, from ≈27 s to ≈20.5 s.
   3. **Bound OCR concurrency to the core count, with capture workers above it.** This
      is the minimal split. It lowers frame age and memory, and is mostly free once (2)
      has a pool.
4. **20 s for 15 always-live Twitch channels is not credible** without a localization
   algorithm change (label-seeded 3×, unprototyped). Twitch adds an estimated ≈1.3 CPU-s
   per attempt just to start Streamlink.

## 1. One frame, end to end

`multi_alpha.schedule()` runs on the coordinator thread. It runs at most `--workers`
attempts at once, one per lane. Each worker thread calls `shadow_capture.capture_attempt()`:

| Stage | Where | Kind | Cost |
|---|---|---|---|
| Due-time selection | Coordinator thread | Scheduling | Every lane starts with `due=started` and keeps the grid `started + k·interval`, so **all lanes fall due at the same instants**. Measured scheduler delays: up to 29.4 s (VPS w4), 29.9 s (w6), 28.7 s (WS 3 workers at 60 s). |
| Streamlink (Twitch only) | New Python process per attempt | Subprocess start, then network wait | Interpreter plus Streamlink 8.6.2 and Twitch plugin import: **0.70 s WS** (bare Python 0.05 s). Estimate ≈1.3 CPU-s VPS (×1.9). Then TLS and HLS waits. |
| FFmpeg | New process per attempt | Mostly waiting; decode and encode are CPU | Keyframe decode plus PNG encode: **0.10–0.22 CPU-s WS** (`-benchmark`). Offline capture is dominated by the `-re` real-time wait to the next keyframe (WS 1.8–5.7 s; VPS mean 6.06 s). One VPS Twitch channel took 2.75 s. |
| Frame transfer | Pipe, bounded `read_png` | Serialization | 2.5–2.7 MB PNG per 1080p frame. |
| Decode and provenance | Worker thread | Python (GIL mostly released) | PNG decode to RGB 34 ms, PNG SHA-256 4 ms, name pixel digest 15 ms (WS). |
| HUD localization | Worker thread plus **2 Tesseract processes** (8.3 MP and 18.7 MP) | CPU | WS ≈2.4 s per frame: resize and threshold 0.09 s, temp PNG writes 0.21 s, Tesseract ≈2.0 s. VPS 4.47 s (w4), 5.84 s (w6), 7.75 s (w8). |
| EXP neural | One resident RapidOCR process, behind a lock | CPU, serialized | 0.06 s WS; 0.14 / 0.21 / 0.30 s VPS. |
| Visual level | **3–6 Tesseract processes** on tiny crops | Mostly subprocess start and model load | 0.11 s per call WS, of which the API path needs 0.002 s (§3C). 0.48 s WS; 0.81 / 1.06 / 1.30 s VPS. |
| Character name | The same resident neural process | CPU, serialized | 0.043 s WS. Queue wait < 0.01 ms in the 15-lane run; 108–149 ms in an earlier burst test. |
| Identity and level guards, `emit`, SQLite | Coordinator thread | Python, single writer | Not separately timed (a gap). About 0.5 appends/s at 15 × 30 s. |
| Publisher, HTTP | Same process | Python and GIL | Saturates the GIL at 10+ channels and 100 viewers ([VPS readiness](vps-readiness.md)). Idle in these benchmarks. |
| `ResourceMonitor` | Coordinator process, every 50 ms | Python and psutil | **9.7 ms CPU per sample with 12 children (WS) ≈ 19 % of one core.** Linux cost unmeasured. |

Memory is not the limit. Sampled peaks were 0.91 / 1.30 / 1.72 GiB at 4 / 6 / 8 workers
(systemd: 1.0 / 1.4 GiB) out of 8 GiB.

The time a worker spends inside one attempt (VPS w4, 11.47 s) splits into:

- 53 % waiting for video;
- 47 % OCR-stage CPU, of which localization is 83 %;
- a negligible share of Python.

## 2. Throughput model

### Measured (VPS, 15 local-video lanes, 5 attempts, requested 30 s, resident neural, cache off)

| Workers | Mean interval | Max | Skips | Mean work | CPU-stage wall | Sampled CPU | systemd CPU |
|---|---:|---:|---:|---:|---:|---:|---:|
| 4 | 43.57 s | 49.7 | 33 | 11.47 | 5.41 | 1.93 cores | — |
| 6 | 36.77 s | 44.8 | 18 | 13.71 | 7.11 | 2.24 cores | 447 s / 75 = 5.96 CPU-s per attempt |
| 8 | 35.51 s | 59.9 | 13 | 15.49 | 9.34 | 2.49 cores | 454 s / 75 = 6.05 CPU-s per attempt |

What the table shows:

- **CPU per attempt is flat** from 4 to 8 workers (sampled 5.66 → 5.52 CPU-s).
  Oversubscription stretches wall time but wastes little CPU.
- **With 4 workers the run is worker-bound.** 15 × 11.47 / 4 = 43.0 s, against 43.57 s
  measured.
- **With 8 workers the run is not worker-bound.** That formula predicts 29.0 s, but 35.5 s
  was measured. The workers sat idle while lanes waited for their next grid slot.

### Calibrated model

The model is a discrete-event copy of `schedule()`:

- earliest due first, with rotating ties;
- one attempt per lane;
- elapsed slots are skipped;
- a capture wait, then an OCR-stage CPU job, with processor sharing over K cores.

Stage shapes are resampled from the 30 per-attempt timings of the 15-lane name-OCR run.
Two free parameters fit the VPS runs: **K = 3 effective cores, P = 5.4 CPU-s.**

| Workers | Model interval / max / skips | Measured | Model CPU-stage wall | Measured |
|---|---|---|---:|---:|
| 4 | 43.6 / 65 / 34 | 43.6 / 50 / 33 | 5.6 | 5.4 |
| 6 | 35.8 / 64 / 15 | 36.8 / 45 / 18 | 7.1 | 7.1 |
| 8 | 34.9 / 60 / 13 | 35.5 / 60 / 13 | 9.3 | 9.3 |

With K = 4 the model underpredicts contention (w8 CPU wall 7.2 against 9.3 measured).
So about one vCPU's worth of capacity is not available to OCR. The candidates are:

- **ruled out on WS: GIL.** `locate()` in threads reached **3.59 effective cores on 4
  pinned P-cores** at 4 threads. At 6 and 8 threads it fell to 3.45 and 3.35.
- hypervisor steal, or vCPUs that are SMT siblings;
- background load: FFmpeg, Streamlink, the 50 ms monitor (§1) and the coordinator;
- a modest oversubscription penalty.

**This split is the most important unknown** (§7).

### Lower bounds

| Bound | Offline today | Resident Tesseract (est. P = 4.1) |
|---|---:|---:|
| CPU floor, K = 3 (15 × P / K) | **27.0 s** | **20.5 s** |
| CPU floor, K = 4 | 20.3 s | 15.4 s |
| Model, best practical (staggered, 8 workers, 3 OCR slots, requested below the floor) | 27.0 s mean, max 34 s | 22.5 s at requested 22.5, no skips |

The model also gives a worker-occupancy bound, `interval ≥ 15 × (capture + P) / workers`.
It binds only at four or fewer workers.

**Live Twitch (estimate).** Capture is shorter (2.75 s against 6 s), so worker
occupancy matters less. But Streamlink start-up adds about 1.3 CPU-s per attempt
outside the OCR stage. Total CPU per attempt becomes ≈7.3 CPU-s. Treating P = 6.4 as an
upper case, the model gives 31.9 s at a requested 30 s with staggering. **15
always-live Twitch channels at 30 s is at or past today's capacity.** Offline channels
cost only a failed Streamlink start, so real load depends on how many channels are live
at once. That fraction is unknown.

### Bottleneck verdict

It is a combination, in this order:

1. **CPU capacity** sets the floor: ≈27 s offline, worse on Twitch.
2. **Scheduling** wastes what remains at 30 s. The shared grid causes bursts, the bursts
   cause contention and slot skips. This, not video waiting, explains the 8-worker
   shortfall.
3. **OCR subprocess design.** Tesseract process starts, model loads and temporary PNGs
   are ≈20–25 % of the OCR stage, and Streamlink start-up is ≈18 % of a Twitch attempt.
4. **Recognition algorithm.** OCR'ing 27 MP of text-like content to find four labels is
   the deepest lever and the riskiest.
5. **Workers occupied while waiting for video** matter only at four or fewer workers.

## 3. Candidates

### A. Separate capture and OCR pools

- **Mechanism:** more capture slots than CPU slots, so FFmpeg waits do not hold CPU
  capacity.
- **Model, staggered, 8 capture workers:**

  | Requested | Shared CPU (today's design) | 3 OCR slots |
  |---|---|---|
  | 30 s | 30.0 s, frame-age p95 10.5 s | 30.0 s, frame-age p95 9.3 s |
  | 25 s, no skip | 28.2 s, max 37.6 s | 27.1 s, max 33.5 s, age p95 11.7 s against 13.4 s |

  Throughput gains are ≈0–4 %, plus the measured 4–7 % oversubscription penalty on WS.
  The main gain is frame age. Aligned w8 today reaches a modelled maximum frame age of
  ≈15–16 s, at the 15 s `max_age` limit, so it risks discarding completed work as stale.
- **Does FFmpeg waiting waste scheduling opportunities?** At 4 workers, yes: 53 % of
  worker time. At 8 workers, no: workers already idle on the grid. Adding workers is
  the cheaper fix.
- **Resident neural under a split:** two requests per attempt, ≈0.25 s VPS at
  0.5 attempts/s, is ≈12 % utilization. The expected M/D/1 wait is ≈8 ms. Neither the
  neural worker nor shared name recognition becomes a bottleneck. Keep recording
  `queue_wait_seconds`, since the timeout starts after the lock.
- **Safety cost of a real split:** every rule in the brief must be re-proven across a
  queue. That covers:
  - per-lane ordering and frame provenance;
  - stale rejection;
  - identity streaks across failed frames;
  - level-floor transactions;
  - shutdown with frames still queued;
  - rotation while a frame is queued.
- **Verdict:** no scheduler redesign. Keep one attempt per worker thread, so ordering,
  provenance, identity and SQLite flow are unchanged. Bound only the Tesseract calls,
  with a semaphore or the pool from C. Queue time already counts against `max_age`,
  because `fresh()` measures from `frame.arrived_monotonic`. A frame that waited too
  long becomes `stale_local_frame` and is never read as current.

### B. Faster HUD discovery

Tesseract's cost tracks text-like content, not pixel count ([HUD localization
performance](hud-localization-performance.md): blank 0.15–0.26 s against 0.8–1.2 s for a
real frame). Downscaling saves little.

- **Visual pre-screens** (template matching on labels, bar-colour geometry, multiscale
  NCC) save CPU only if they **skip** OCR somewhere. Skipping silently drops any
  competing HUD the screen misses. The corpus (89 frames) cannot establish the
  near-perfect recall that would need.
- **Safe use of a pre-screen:** only to add vetoes. For example, flag half-size second
  games, which the full scan misses today. That is the secondary-HUD branch's territory
  and is left alone here.
- **Label-seeded 3×:** the only structural saving. Every HUD seen in one pass had a
  label seen by the other pass. It is unprototyped, the size of its seed box is unknown,
  and one unseen label would blind both passes.
- **Verdict:** evaluate label-seeded 3× only if 20–22 s is still required after
  recommendations 1–2. Keep the full-frame two-scale scan as the authority. No cache.

### C. Tesseract execution (measured)

`exp_resident_tesseract.py` (scratch, not committed) calls `libtesseract-5.dll` through
ctypes: `TessBaseAPISetImage` on the same 8-bit images, then `TessBaseAPIGetTsvText`,
parsed by pytesseract's own `file_to_dict` and `_tokens`. Same `eng.traineddata`,
psm and whitelist, one pinned core:

| Calls (9 frames, 3 recordings) | Token-identical | pytesseract CLI | C API |
|---|---:|---:|---:|
| Full-frame psm 11 (2× and 3×) | **18/18** (188–543 words each) | 1.195 s | 1.062 s (−11 %) |
| Level crops, psm 7, digit whitelist | **24/24** | 0.109 s | **0.002 s** |

- **Projected OCR stage, VPS (estimate):** localization 4.47 → ≈3.97 s, visual level
  0.81 → ≈0.02 s. P falls from 5.4 to ≈4.1 CPU-s (−24 %).
- **Supersedes** the batched-Tesseract prototype (−6 %), which only saved one process
  start and some PNG encoding.
- **No new Python package.** Ubuntu's `tesseract-ocr` already installs `libtesseract.so.5`.
- **Isolation and timeouts:** run the engine in resident worker processes, as
  `ResidentNeural` does, so a native crash or hang is killed rather than taking down the
  single SQLite writer.
- **Thread safety:** one handle per process. Reset the whitelist on every call.
- **Untested on Linux:** parity there is the gating experiment.

Other Tesseract settings were already rejected on evidence: no-invert, 1-bit input,
dropping a scale. Check that the VPS model is the 4 MB fast model and that SIMD is
present (`tesseract --version`, hash of `eng.traineddata`).

### D. FFmpeg and frame transfer (measured on WS)

- **FFmpeg CPU is small:** 0.10–0.22 CPU-s per capture.
- **PNG to raw RGB:** saves ≈0.1 CPU-s in FFmpeg and 34 ms of decode (≈3 % per attempt).
  It changes the `frame_sha256` provenance definition and the bounded reader.
- **PNG `compression_level 1`:** saves ≈0.06 s.
- Neither change affects network bytes. **Low value.**
- **The real start-up cost is Streamlink** (0.7 s WS, est. ≈1.3 CPU-s VPS), which is
  larger than all FFmpeg costs combined. Pre-importing it in a fork server or a resident
  helper would keep a new HLS session per capture, which "no persistent video sessions"
  allows. This is Twitch-only and unmeasured on Linux. It is a good fourth candidate.

### E. Scheduling and concurrency (model)

| Requested 30 s, 8 workers | Mean | Max | Skips |
|---|---:|---:|---:|
| Today (shared grid) | 34.9 s | 59.6 s | 13 |
| **Staggered phases** (lane *i* first due at `i·interval/lanes`) | **30.0 s** | **31.5 s** | **0** |
| Staggered, 6 workers | 32.2 s | 40.4 s | 0.9 |

- **No skip.** A late lane falls due at once instead of waiting for its next grid point.
  It never runs early and never queues more than one attempt. Under overload this cuts
  the maximum interval (25 s requested: 52 → 38 s), not the mean.
- **Back off persistently unavailable channels** (offline, missing HUD). This saves
  Streamlink starts and full scans without inventing observations, because gaps stay
  gaps. The value depends on the unknown fraction of channels that are live.
- **More than 8 workers adds nothing** in the model at these loads, and costs memory and
  Twitch connections.

### F. Other ideas

| Idea | Verdict |
|---|---|
| `ResourceMonitor` at 50 ms | Measure on the VPS. If it is significant, sample every 0.5–1 s and use `getrusage(RUSAGE_CHILDREN)` for exact reaped-child CPU. Cheap, no behaviour change. |
| `nice` the OCR workers | Protects publisher and HTTP latency. An ops change, not throughput. |
| Lower Twitch rendition | Saves decode and bandwidth, but shrinks HUD text. A recognition-accuracy risk. Not without a labelled evaluation. |
| RapidOCR text detection as the localizer | A new algorithm needing full competing-HUD re-validation. A research project, not an optimization. |
| HUD cache, region search | Excluded by the no-blind-spot constraint. Stays off. |
| More hardware, GPU, persistent streams | Excluded by constraints. |

## 4. Ranked opportunities

| # | Change | Basis | Predicted effect | Effort | Correctness risk |
|---|---|---|---|---|---|
| 1 | Stagger lane phases | Model calibrated to VPS; bursts directly measured | 30 s target met at 8 workers on today's CPU (35.5 s now) | ≈1 line plus tests | None to recognition. The first capture is delayed by up to one interval. |
| 2 | Resident libtesseract worker pool | **Measured parity 42/42 (WS)**; CPU saving estimated | OCR stage −24 %; ceiling ≈27 → ≈20.5 s | Medium: worker protocol, timeouts, parity tests | Low **if** parity holds on Linux; a native crash is contained by the process |
| 3 | Bound OCR concurrency to cores, capture workers above it | Model; WS oversubscription measurement | Frame-age p95 −1–2 s; throughput +0–7 %; less memory | Small with #2 | Low. Queue wait counts toward `max_age`. |
| 4 | Pre-imported Streamlink (fork server or helper) | WS start-up measurement | Twitch about −1.3 CPU-s per attempt (≈18 %) | Medium; Linux only | Low. Still a new session per capture. |
| 5 | Back off unavailable channels; 50 ms monitor | Reasoning; WS monitor cost | Depends on the live fraction and the Linux monitor cost | Small | None |
| 6 | Label-seeded 3× localization | Prior token analysis | Up to ≈−40 % localization (unproven) | Large | **High:** a competing-HUD blind spot if a label is missed |

Rejected or deferred: a full split-pipeline scheduler redesign (cost far exceeds the
gain over #3); raw-RGB transfer (≈3 %); batched Tesseract (superseded by #2); HUD cache;
visual pre-screen as a skip.

## 5. Safety notes for the top three

- **Staggering:**
  - It changes only each lane's first due time. Per-lane order, one attempt in flight
    per lane, skipping, rotation, identity confirmation (two frames ≤ 120 s apart) and
    the single writer are untouched.
  - Lanes still finish on their own schedules, so `emit` load spreads out rather than
    arriving in bursts.
  - Startup coverage is delayed by up to `interval × (lanes−1)/lanes`.
- **Resident Tesseract:**
  - Ship only with a platform parity test that fails on any token difference.
  - Kill the worker on a timeout and start a fresh one, as `ResidentNeural` does.
  - Never fall back silently to a different engine version. Same package, same model
    hash.
  - Bound request size, as the neural worker does.
  - Keep competing-HUD and page checks unchanged.
- **OCR slots:**
  - A FIFO queue bounded by the worker count, so it is never unbounded.
  - Record the wait as its own timing.
  - Keep the existing `fresh()` checks after the wait.
  - Ctrl+C keeps today's behaviour: in-flight attempts are recorded `operator_interrupted`.

## 6. Recommended experiments (the two most promising)

**Experiment 1: staggered phases (VPS, operator-run, offline video).** Implemented as
the opt-in `--stagger-capture`. Real-scheduler checks, exact operator commands and
acceptance criteria are in [staggered capture experiment](staggered-capture-experiment.md).
Not yet measured on the VPS.

- **Change:** in `schedule()`, set lane *i*'s first `due` to
  `started + i·interval/len(lanes)`, behind a test.
- **Run:** the 2026-10-20 sustain30 configuration at 6 and 8 workers, with and without
  the change. Also run `mpstat 5` or `vmstat 5` to capture steal.
- **Continue if** at 8 workers the mean is ≤ 31 s, the maximum ≤ 35 s and there are ≤ 2
  skips (model: 30.0 / 31.5 / 0), with no new failures or stale frames.
- **Reject if** the mean stays above 33 s. Then the missing core, not bursts, dominates.
  Go to §7, question 1.

**Experiment 2: resident Tesseract parity on Linux (VPS bench checkout or any Ubuntu with
the same `tesseract-ocr` package).**

- **Run:** port the scratch script to `ctypes.util.find_library('tesseract')`. Run it
  over ≥ 50 frames from the offline recordings, plus the 12 adversarial composites from
  [HUD localization performance](hud-localization-performance.md).
- **Continue if** there are **zero** token differences across both scales and all level
  crops, CPU per `locate()` falls ≥ 8 % and level time falls ≥ 90 %.
- **Then:** prototype the pool behind a flag and rerun sustain30 at 8 workers. The model
  predicts 25 s requested is met with 0 skips (P = 4.1).

**Measurement-only, the same session:**

- `locate()` scaling on 1, 2, 3 and 4 concurrent processes on the VPS (the effective-core
  question);
- one run with `ResourceMonitor` at 1 s.

## 7. Open questions

1. **Why does OCR get only ≈3 of 4 vCPUs on the VPS?** Steal, SMT siblings, background
   load and the 50 ms monitor are all candidates. If it is removable, every floor in §2
   improves by up to 25 %.
2. Real Twitch capture time and CPU at 15 channels: Streamlink start-up, TLS, segment
   latency tails, and how many channels are offline.
3. VPS Tesseract version, SIMD and model hash; Linux parity of the C API.
4. Coordinator `emit` and SQLite time per attempt with automatic characters (not timed).
5. Publisher and viewer load sharing those cores in production.

## Files

- `tools/simulate_throughput.py`: the model (no I/O, deterministic seeds).
  Example: `python tools/simulate_throughput.py --workers 8 --cores 3 --stagger`.
- `tests/test_simulate_throughput.py`: model invariants (bursts skip, staggering holds
  cadence, OCR slots queue instead of time-slicing, late lanes never run early).
- Scratch experiments, not committed: `exp_thread_scaling.py` and
  `exp_resident_tesseract.py`. Frames were decoded in memory from the local sample
  videos, and nothing private was written to the repository.
