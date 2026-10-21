# Capture throughput and HUD localization

Follows the [VPS deployment](vps-deployment.md) measurements (4 vCPU / 8 GB Ubuntu):
15 offline channels needed **13.43 s** of sequential work per attempt (capture 6.78,
HUD localization 4.58, neural 1.25, visual level 0.83). A requested 180 s cadence was
achieved at ≈202 s. One real Twitch channel needed 9.35 s and ≈9.8 sampled CPU-seconds.
This milestone asks what it takes to run **15 channels at ≈60 s** on that VPS.

Nothing was deployed, committed or pushed. No Twitch capture was started and no
production database was opened. All figures below are **workstation** measurements
(i7-13700K, Windows 11, Tesseract 5, RapidOCR 3.10.0) unless marked VPS.

## Three opt-in changes

All default to today's behaviour: `--workers 1` (the unchanged serial path, run inline
on the coordinator thread), no cache and one neural process per attempt. Without these
flags, `capture_attempt` receives exactly the arguments it did before; a test asserts
that. `deploy/msxp-tracker.service` is unchanged, so production changes only when flags
are added to its `ExecStart`. **HUD caching stays disabled** until separately approved.

| Flag (`tools/multi_alpha.py`) | Effect | Accuracy |
|---|---|---|
| `--resident-neural` | One long-lived RapidOCR process (`shadow_rapidocr.py --serve`) replaces one process per attempt. Requests are serialized; a timeout, crash or oversized reply kills it and the next request starts a fresh one. | Identical: 22/22 crops gave the same text, raw scores and level fields as the one-shot worker. |
| `--hud-cache-seconds N` | Per channel, search a small box around the last **unique full-frame** HUD for up to N seconds, then rescan the full frame. Any doubt (0 or ≥2 candidates, different anchor spacing, EXP/level box moved more than 5 % of the spacing, level present/absent changed, frame size changed) rescans the full frame at once. | A **policy change**, see below. Off by default. |
| `--workers N` (1–8) | Up to N channels' attempts run at once, never two for one channel. 5–8 are accepted for experiments but **not yet performance-validated on the VPS**; see below. Due-time selection, deadline skipping, rotation, log writes, the single SQLite writer and status updates stay on the coordinator thread. | No OCR change. |

Records from the region search carry `localization.candidates[0].search =
"cached_region"` and `full_frame_age_seconds`, so they can be separated in SQLite.

## Where HUD localization time goes

`adaptive_hud.locate()` runs Tesseract `--psm 11` twice over the whole frame, at
3840×2160 and 5760×3240 for a 1080p stream. Per frame on the workstation:

| Stage | 2× pass | 3× pass |
|---|---:|---:|
| Grayscale + bicubic resize + threshold | 0.03 s | 0.06 s |
| pytesseract temporary PNG write | 0.02–0.04 s | 0.05–0.08 s |
| Tesseract recognition | 0.44–0.90 s | 0.73–1.25 s |

Preprocessing is under 5 % of the cost; Tesseract on 27 megapixels is the rest
(mean full `locate()` **2.33 s** over 78 frames here, 4.6 s on the VPS). Rejected:

- BMP/PBM instead of PNG temporary files: saves ≤0.07 s and changes Tesseract's TSV.
- `-c tessedit_do_invert=0`: 16 % faster but changed tokens in 24 of 26 full-frame scans.
- Dropping the 3× pass: `locate()` documents that both scales are needed for uniqueness;
  not evaluated.

So the only large lever is giving Tesseract fewer pixels.

## Region search accuracy

Corpus: 78 private full frames, ignored and not committed. 55 frames from the three
sample recordings at 120–300 s spacing; the 12 adaptive-OCR challenge frames
(relocated, resized 0.5/0.75/1.25, two panels, hidden HUD, blank, embedded in a larger
stream); 5 sample screenshots; 4 cached-HUD synthetic negatives.

- **Full-frame refactor:** `locate(image)` output is byte-identical to HEAD on 78/78.
- **Same-frame region search** (seeded by that frame's own unique result): 53/61
  accepted, **0.354 s vs 2.395 s** for the full scan. In the 8 others the box finds 0, 2
  or a level-less candidate where the full frame found one, so it falls back. 44/53
  accepted boxes are pixel-identical; the rest differ by ≤4 px, the same jitter the
  full scan shows between consecutive Stream 2 frames.
- **Moved, resized, hidden, blank, two panels:** 23/24 seeded negative pairs fall back to
  the full frame and agree with it.
- **Sequential seeding** (previous recording frame seeds the next, 120–300 s apart):
  41/48 accepted. Neural EXP text and visual level were then read from both crops:
  - 36 frames where the full scan was also unique: 33 identical. 3 differ only in
    availability, never in value: the region crop read `2[3.51%]` where the full crop
    read malformed `2[3.51%1`; one level was read only from the region crop, and one
    only from the full crop.
  - **5 frames change decision from reject to accept.** On four Stream 2 frames the full
    scan finds no HUD although one Classic HUD is clearly visible (e.g. `173[46.51%]`,
    level 6, matching the visible panel). On Stream 3 at 1265 s the full scan reports
    two HUDs that are one panel split by a 10 px EXP-token offset (identical EXP box).
    The region readings look correct, but they **override what the full scan decided**.

**The counterexample from [cached HUD evaluation](cached-hud-evaluation.md) still
holds.** With a HUD added elsewhere in the frame (`synthetic-secondary`), the full scan
reports two HUDs, but the region search accepts the original. Within N seconds of the
last full scan, a competing HUD that appears elsewhere is **not detected**. The
mitigation is only the bound: every N seconds, and on any doubt, the full frame decides
again, and an ambiguous full scan clears the cache. The region keeps reading the HUD at
the validated position and scale. That HUD could only be swapped for another
character's at exactly the same place and scale, and full-frame scanning cannot detect
that swap either (identity is never verified).

Decide before enabling it: is a bounded blind spot for a newly appearing second HUD
acceptable? If not, leave `--hud-cache-seconds` at 0 and rely on workers.

## Neural worker startup

One-shot `shadow_rapidocr.py` per attempt: **1.03–1.15 s** wall, of which 0.6 s is
import and model load, 0.16–0.20 s a cold first inference, and the rest interpreter
start and hashing 31 MB of models. The resident worker takes **0.057 s** (EXP only) /
**0.070 s** (with experimental level) per request after a ≈1.0 s first request. It holds
≈160 MiB resident ([cached HUD evaluation](cached-hud-evaluation.md)). Visual level OCR
(three to six Tesseract processes on small crops, 0.3 s here / 0.7–0.8 s on the VPS) is
unchanged; a resident Tesseract would need a new dependency.

## Coordinator matrix (workstation, 4 pinned P-cores)

15 local-video lanes (the three sample recordings, distinct start offsets), requested
60 s, 3 attempts each, `--continuous --max-attempts 3`. The process tree was pinned to
4 distinct P-cores. Each run used a new private database; 45/45 attempts were committed
in every run. Status mixes differ because each run seeks to different video times; they
are not an accuracy comparison. Local-video capture includes FFmpeg's real-time `-re`
wait after a seek, so it is not Twitch capture time.

| Run | Mean work | Capture | Localization (cached) | Neural | Level | Achieved / max interval | Skipped | CPU-s / attempt | Peak RSS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| a. baseline (serial) | 7.61 s | 3.54 | 2.60 | 1.14 | 0.48 | **115.2** / 116.7 s | 35 | 5.06 | 201 MiB |
| b. cache 300 s + resident | 4.74 s | 3.09 | 1.17 (0.39, 29/45) | 0.05 | 0.46 | 71.1 / 96.2 s | 11 | 2.41 | 328 MiB |
| c. b + 2 workers | 5.41 s | 3.56 | 1.37 (0.40, 25/45) | 0.05 | 0.45 | **57.6** / 64.0 s | 0 | 2.38 | 459 MiB |
| d. b + 4 workers | 5.51 s | 3.35 | 1.64 (0.42, 21/45) | 0.07 | 0.48 | 58.8 / 62.3 s | 0 | 2.59 | 648 MiB |
| e. resident + 4 workers, no cache | 6.71 s | 3.53 | 2.65 | 0.08 | 0.50 | 59.8 / 61.9 s | 0 | 3.60 | 654 MiB |
| f. resident + 2 workers, no cache | 6.53 s | 3.55 | 2.55 | 0.06 | 0.44 | 60.2 / 62.3 s | 0 | 3.48 | 467 MiB |

The first interval of a run is counted from its start, so mean intervals slightly below
60 s are an artefact of that. With only 3 attempts per lane, the first attempt of every
lane is a full scan, which understates cache reuse; a long run approaches 4 of every 5
attempts with a 300 s refresh. CPU-seconds are 50 ms-sampled for the whole process
tree, so short-lived children are undercounted.

Readings:

- **Serial cannot reach 60 s for 15 channels**, even with both single-attempt
  optimizations (b: 71 s mean, gaps up to 96 s).
- **Two workers are enough here** with or without the cache (c, f). Four workers add
  memory and contention (localization slows from 2.55 to 2.65 s without the cache, and
  cached attempts from 0.40 to 0.42 s) for no cadence gain at this load.
- The cache roughly **halves CPU per attempt with the resident worker** (3.48 → 2.38).
  The resident worker alone saves ≈1.1 s wall and ≈1 CPU-s per attempt.

## Projected VPS capacity

The VPS was ≈1.9× slower per attempt in CPU (9.8 vs 5.06 CPU-s) and ≈1.6× slower in
non-capture work (6.65 vs 4.07 s). Applying those factors and keeping the VPS's measured
2.75 s Twitch capture gives estimates, **not measurements**:

| Configuration | Est. work / attempt | Est. busy time per worker per 60 s, 15 channels | Est. CPU, 15 channels @ 60 s |
|---|---:|---:|---:|
| Today (serial) | 9.4 s (measured) | 140 s, one worker: **fails** | ≈2.5 cores |
| Resident + 2 workers | ≈8.3 s | ≈62 s: **no headroom** | ≈1.7 cores |
| Resident + 3 workers | ≈8.3 s | ≈42 s | ≈1.7 cores |
| Cache 300 s + resident + 2 workers | ≈5.8 s | ≈44 s | ≈1.2 cores |
| Cache 300 s + resident + 3 workers | ≈5.8 s | ≈29 s | ≈1.2 cores |

Headroom matters more than the mean. A single skipped deadline at 60 s makes a 120 s
gap, which is the progress engine's continuity ceiling
([continuous alpha](continuous-alpha.md)). Workers should stay well under ≈70 % busy.

What is required for 15 channels at ≈60 s on the 4 vCPU VPS:

1. **Bounded parallelism is required in every configuration**, because Twitch capture
   alone is 15 × 2.75 s ≈ 41 s of mostly network waiting per minute. Benchmark
   `--workers 2` and `3` first; the cache stays disabled for that benchmark.
2. **`--resident-neural`**: no accuracy change, ≈1 CPU-s saved per attempt.
3. **`--hud-cache-seconds 300`** is a later, separate decision, only if the
   competing-HUD blind window is acceptable.
   It cuts total capture CPU by roughly a third, leaving room for the publisher.
   [VPS readiness](vps-readiness.md) shows the publisher saturating the GIL at 10+
   channels and 100 viewers. Capture adds 0.25 appends per second at 15 × 60 s, half the
   10 × 20 s load measured there.

Memory stays far below 8 GB (≈650 MiB peak with 4 workers here; VPS peaks run higher
than the workstation, single-channel 308 MiB).

## Shutdown, failures and integrity with workers

- Only the coordinator thread writes logs and SQLite, so the single-writer and
  run-rotation transactions are unchanged. Each channel has at most one attempt in
  flight, so attempt indices stay consecutive.
- A failed, timed-out or unavailable source occupies one worker for at most its
  existing timeouts. Other channels keep being scheduled.
- An unexpected exception in a worker is re-raised on the coordinator thread, as in
  the serial path.
- **Ctrl+C / SIGINT:** in-flight attempts are recorded as `operator_interrupted`, as a
  serial interrupt records the attempt it cuts short. Their late results are discarded
  without waiting. That keeps shutdown inside `TimeoutStopSec=60`, which must also
  cover the publisher's 30 s join. Their FFmpeg/Streamlink/Tesseract children end with
  the console Ctrl+C or with systemd's `KillMode=mixed` cleanup after the main process
  exits. The resident neural process is closed on exit.

## Worker counts above 4 (opt-in, not validated)

`--workers` accepts 1–8; the default stays 1. Counts 5–8 use the same scheduler, with
no other change. They are **not yet performance-validated on the VPS**, and nothing
here shows that 6 or 8 are faster, or safe for sustained real Twitch capture.

Reported VPS offline runs (4 vCPU / 8 GB, 15 channels reading one local video, 5
attempts each, `--workers 4`): the mean start-to-start was 59.8 s (max 60.5 s, 0 skips)
at a requested 60 s. It was 49.6 s (max 55.8 s, some skips) at 45 s, and 42.9 s
(max 50.0 s, 34 skips) at 30 s. All 75 attempts in the 30 s run succeeded at ≈1.9
cores mean, so the four worker slots, not the CPU, looked like the limit.

Expected costs at 6–8 workers, unmeasured:

- Up to N concurrent FFmpeg/Streamlink sessions (N Twitch connections at once) and N
  Tesseract processes.
- More memory.
- With `--resident-neural`, longer queues on the one serialized RapidOCR process. A
  request's neural timeout starts only when it reaches the process, so time spent
  waiting behind other workers is not counted.

## VPS benchmark commands

Run as **root** (`sudo -i`), from a **separate benchmark checkout**, never the production
`/opt/msxp/app`. It follows the production ownership model from
`deploy/install-ubuntu.sh`:

- code is root-owned and read-only to the service;
- only `private/` is `msxp:msxp 0750`;
- everything that runs or writes does so as `msxp`, so every database, log and summary
  is `msxp`-owned;
- `/opt/msxp` itself is not writable by `msxp`.

The installed venvs are reused read-only. Every benchmark gets a new database under the
benchmark checkout's `private/bench/`. Nothing here touches `private/vps/tracker.sqlite3`.

The configuration rewrite **refuses any non-`file` source**, so no Twitch connection is
possible. Relative video paths are resolved against `BASE`, the directory the original
offline configuration was written for, and are written out as absolute paths. Each
video must be a regular file readable by `msxp`. Production capture shares the same
4 vCPUs: stop `msxp-tracker` for clean numbers, or record that it was running.

```sh
# --- Once, as root. On Windows, after a commit is approved:
#   git bundle create msxp-perf.bundle feat/capture-performance   (then scp it to /root/)
git clone --branch feat/capture-performance /root/msxp-perf.bundle /opt/msxp/bench  # root:root code
cd /opt/msxp/bench
install -d -o msxp -g msxp -m 0750 private private/bench private/videos
sudo -u msxp ln -s /opt/msxp/app/private/rapidocr private/rapidocr  # Pinned neural venv, read-only reuse.
# The 15-channel offline config behind the 202 s measurement, and its videos if msxp
# cannot already read them where they are:
install -o msxp -g msxp -m 0640 /path/to/offline15.json private/bench/offline15.json
# install -o msxp -g msxp -m 0640 /path/to/*.mp4 private/videos/

# --- Each session, as root, in /opt/msxp/bench.
PY=/opt/msxp/app/.venv/bin/python
SRC=private/bench/offline15.json
BASE=/opt/msxp/app   # Relative "file" paths in SRC were written against this directory.
as_msxp() { sudo -u msxp env HOME=/opt/msxp PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1 OMP_THREAD_LIMIT=1 "$@"; }

bench() {  # bench NAME [multi_alpha flags...]: new DB, 60 s cadence, 5 attempts per channel
  name=$1; shift
  as_msxp "$PY" - "$SRC" "$BASE" "$name" <<'EOF' || return 1
import json, os, sys
from pathlib import Path
source, base, name = sys.argv[1:]
config = json.load(open(source, encoding='utf-8-sig'))
config.update(database=f'private/bench/{name}.sqlite3', port=0)
for stream in config['streams']:
    if stream.get('source') != 'file':
        sys.exit(f"{stream.get('channel')}: only local-video sources may be benchmarked")
    path = Path(stream['file'])
    path = (path if path.is_absolute() else Path(base) / path).resolve()
    if not path.is_file() or not os.access(path, os.R_OK):
        sys.exit(f'{path}: missing or not readable by msxp')
    stream.update(file=str(path), interval=60)
with open(f'private/bench/{name}.json', 'x', encoding='utf-8') as handle:  # Never overwrite.
    json.dump(config, handle, indent=1)
EOF
  as_msxp "$PY" tools/multi_alpha.py --config "private/bench/$name.json" --continuous       --max-attempts 5 --exit-after-capture --public-only "$@" 2>&1 | as_msxp tee "private/bench/$name.log"
  run=$(sed -n 's/^Private capture logs: //p' "private/bench/$name.log")
  [ -n "$run" ] || { echo "$name: no run directory; read private/bench/$name.log" >&2; return 1; }
  as_msxp "$PY" tools/summarize_capture_run.py "$run" | as_msxp tee "private/bench/$name.summary.json"
}

# Cache stays off. Serial baseline first, then the resident worker with 2 and 3 workers.
# Repeat the best one with --retention-24h added. Its first prune runs at startup on the new, small DB;
# prune cost on a full-day database is not measured by this benchmark.
bench vps-a-serial
bench vps-b-resident    --resident-neural
bench vps-c-w2-resident --workers 2 --resident-neural
bench vps-d-w3-resident --workers 3 --resident-neural
# Separately, while vps-d runs:  uptime; top -b -n1 | head -20
```

Each run takes about 5–12 minutes: 5 rounds of 15 channels at 60 s, longer when serial.
Compare `mean_actual_interval_seconds`, `max_actual_interval_seconds`, the per-lane
`skipped deadlines=` lines in each `.log`, and the final `Resources:` line (sampled CPU,
peak RSS). Choose the smallest worker count with zero skipped deadlines and a maximum
interval well under 120 s. A rejected configuration writes nothing; fix it and rerun
the same NAME.
Afterwards, `rm -r /opt/msxp/bench` removes everything the benchmark created.

To adopt a result later, append the chosen flags to `ExecStart` in
`deploy/msxp-tracker.service` and change the channels' `interval` in
`private/vps/config.json`. Then use the normal controlled restart.

## Integration with 24-hour retention

Main at `ef53811` (retention merged, including `8ea4611`) was merged into this branch.
Git auto-merged everything except six hunks in `tools/multi_alpha.py`; nothing in the
later retention commits touches the coordinator. The resolution keeps both features:

- `schedule(..., maintain=None, workers=1)`, with `if maintain:maintain()` first in
  every pass of the scheduler loop. That is before the first dispatch and again after
  each completion or due-time wake.
- Both argument checks (`--workers`/`--hud-cache-seconds` and
  `--retention-24h requires continuous capture`), retention's `own(directory, database)`
  and `OperatorLog`, the N-worker monitor scope and message, and `maintain=maintain`
  together with `workers=args.workers` and the per-lane options.

Invariants, each covered by a test in `tests/test_capture_performance.py`:

- **Retention maintenance runs only on the coordinator thread.** `prune()` works inside
  the coordinator's SQLite connection and transaction. It temporarily rewrites
  `streamers.selected_character_id` there. Workers never touch the store.
- **Maintenance may overlap in-flight attempts.** Those runs remain in
  `httpd.active_run_ids`, which `prune(active_runs=...)` protects, and their logs are in
  `active_logs`. Only the coordinator rotates `lane['args'].output`. A forced mid-run
  prune with one attempt in flight leaves every attempt committed and every run
  finalized, and a restart on the same database works.
- **Ctrl+C during a prune** rolls back that transaction. In-flight attempts are recorded
  as `operator_interrupted` without waiting for them.

A long prune delays result collection and dispatch, not the in-flight work.
`coordinator_attempt_seconds` is measured in the worker. Scheduler delay and skipped
deadlines can grow for channels that fall due during a prune. Benchmark once with
`--retention-24h` on a realistically sized database copy.
Retention's `guard()` in `Diagnostics.append` rejects expired timestamps. Workers emit
seconds after capture, so it should not trigger; if it did, the lane would stop with
`persistence_failed`, as in the serial path.

`deploy/msxp-tracker.service` keeps main's `--retention-24h` and adds **no** performance
flags.

## Not done

- No real Twitch measurement of these changes. The only VPS figures are the
  offline 4-worker runs above; 5–8 workers are unmeasured.
- The region search was evaluated on 78 frames from three recordings, not on live
  stream cuts, overlays or long sequences at 60 s spacing.
- Twitch access-token and playlist request rates at 15 channels per minute are untested.
