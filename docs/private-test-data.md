# Test data: public, private and recreatable

## Two kinds of tests

- **Public tests (about 2,950):** generated fonts, synthetic HUDs and made-up channels. They need nothing
  outside Git and cover the logic: tracking, accounting, history, the website, msxp. Anyone runs them
  with `msxp test`.
- **Private regression tests:** real game footage. Frames show Nexon's artwork and real streamers, so
  recordings, screenshots and crops never go into Git (see [AGENTS.md](../AGENTS.md)). These tests skip
  when their files are absent, so a public checkout stays green. Only the maintainer runs them.

## What the private data is, and how to recreate it

| Data | Where | Recreatable from |
| --- | --- | --- |
| **Golden frames: the 206 labelled frames, lossless (292 MB)** | `samples/frames/*.webp` | `python tools/extract_test_frames.py` (needs the recordings); **back these up** |
| Three stream recordings (8.7 GB) | `samples/sample-stream.mp4`, `-stream2.mp4`, `-stream3.mp4` | Nothing. Only needed to cut new examples or rebuild the crop sets: cold storage is fine |
| Labelled frames: timestamps and HUD values | committed in [`tests/data/recorded_frames.json`](../tests/data/recorded_frames.json), and the private manifests below | The labels are in Git |
| Level-up crop set (234 crops, recording 1) | `private/levelup-evaluation/` | `python tools/rebuild_fixture_crops.py private/levelup-evaluation/manifest.json` |
| Cross-stream crop sets (2 × 90 crops, recordings 2 and 3) | `private/cross-stream/stream2/`, `stream3/` | the same tool with each `manifest.json` |
| Two-feed screenshots (percentage-only HUD, second gameplay feed): 1–21 at level 71, 23–29 at level 72 after a feed swap (70 MB) | `samples/two-feed/` | Nothing; copy `two-feed/` back from the private test-data repository |
| Saved capture logs for replay tests | `private/test-fixtures/runs/` | A frozen copy of tracker logs. Tests read an anonymized copy built from it using the private `names.json` |

`tools/rebuild_fixture_crops.py --check` regenerates every crop from its recording and compares pixels
without writing. On 2026-10-23 all 414 crops above came back identical.

## The live reader on real footage

`tests/test_recorded_streams.py` runs the reader the tracker actually uses (`shadow_capture.analyze`:
HUD localization, Tesseract and the RapidOCR worker) on the golden frames, or on frames decoded from the
recordings when those are absent. `extract_test_frames.py --check` proves the two are pixel-identical. It checks two things: the reader never accepts a wrong EXP pair, and frames
it read correctly before still read correctly. By default every 5th frame runs (about 30 s);
`MSXP_ALL_FRAMES=1` runs all 206.

Measured on 2026-10-23 (labels are provisional visual transcriptions by one reviewer):

| Recording | Read correctly | Rejected | Wrong |
| --- | --- | --- | --- |
| 1 (levels 1–9) | 87 / 116 | 28 | 1 |
| 2 (levels 1–8, smaller HUD) | 36 / 45 | 9 | 0 |
| 3 (level 40) | 41 / 45 | 4 | 0 |

The one wrong pair is a 9 read as an 8: `1,241 [99.82%]` for `1,241 [99.92%]` at level 9. The EXP
table contradicts it (1,241 / 1,242 = 99.92%), so later consistency checks can reject it once the level
is known. The test marks it as a known misread; it fails loudly if the reader starts reading it right.

This test also catches a broken OCR environment. Every frame would come back rejected, as happened
locally on 2026-10-23 when the RapidOCR environment lost `pip` and `certifi`. `msxp doctor` now runs the
OCR worker once, and `msxp install` repairs such an environment (it restores pip first, then reinstalls).

## Backing up, and why other people can't run these

**Back up `samples/frames/` (292 MB)**, plus `private/` if you want the crop sets and capture logs. A cloud
folder is plenty. Keep the recordings only while you plan to label new examples.

Other people cannot have this data, at any size. A stream frame shows the streamer's webcam, overlays and
chat, other players' names and Nexon's artwork, and redistributing it needs their permission. Keeping
only the HUD bar (name masked) was measured on 2026-10-23: alone it read 61 of 206 frames, and even pasted
back into a black frame of the original size 103 instead of 164, twice accepting a wrong pair. The reader
judges the HUD against the whole frame, so a cut-down frame is not a faithful test.

What anyone can run instead:

- the public suite: about 2,960 tests, 94% of `src/exp_tracker` (95% with the private tests);
- their own real-world check: record a stream they have permission to use, label frames in
  `tests/data/recorded_frames.json` style, and run `tools/extract_test_frames.py` and this test.

A shareable real-world set would need permission from the streamers in it, or a recording of your own
gameplay. That is the one way to publish real frames.

## Adding new private test data

1. **Where it goes.** Lossless frames (PNG or WebP) in `samples/<neutral-name>/`, crop sets under
   `private/`. Folder and file names describe the layout, not the person: `samples/two-feed/`, not a
   streamer's login. Both locations are ignored by Git.
2. **Where labels go.** Expected values live in the test itself or in a committed label file such as
   `tests/data/recorded_frames.json`, never in folder or file names. Code and docs use placeholders
   (`streamer_a`, `CharA`); real names stay in the private `names.json`.
3. **Back it up.** Copy every new private fixture into your private test-data repository and add a row
   to the table above saying where it lives and how to recreate it.
4. **Check before committing.** Search the staged diff for real names, including any new ones not yet in
   `names.json`:

   ```sh
   python -c "import json,re,subprocess;n=[v for k,v in json.load(open('private/test-fixtures/names.json')).items() if not k.startswith('_')];d=subprocess.run(['git','diff','--cached'],capture_output=True,text=True,encoding='utf-8').stdout;print([x for x in n if re.search(re.escape(x),d,re.I)] or 'no real names')"
   git diff --cached | grep -i "<any new name>"
   ```

## Lost on 2026-10-23

An artifacts cleanup deleted `artifacts/live-benchmark/` and `artifacts/green-test-20261015-215403/`,
crops of an Oct 15 live capture. They were the calibration and regression data of the **glyph-profile
OCR experiment** (`private/ocr-evaluation/*glyph-profile*`, half of `private/exp-digits/bank.json`). The
live tracker does not use that path. Those 68 tests now skip, saying which folders are missing.
Restoring them needs a new authorized live capture at that HUD scale: the remaining recordings use
other scales, which those profiles reject by design.
