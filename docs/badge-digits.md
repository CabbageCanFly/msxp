# Level badge digits

The tracker reads the level from the orange badge with a small learned digit model
(`src/exp_tracker/badge_digits.py`, weights in `src/exp_tracker/data/badge-digits.json`).
Tesseract runs only when the model is unsure. The result fills the same fields as before
(`visual_level`, and one `visual_attempts` entry with variant `badge_digits`), so the level
guard, history and admin views are unchanged.

## Why

Tesseract handled the tiny badge font poorly. On the 1,589 readable badges below it read 911
(57%) and accepted 21 wrong levels (25 as 23, 58 as 38, 72 as 22, 91 as 31, 8 as 3, 9 as 8).
1,198 of those frames also had a stray attempt naming another level, which resets the level
guard's vote chains. On Windows it cost about 0.9 s per frame. Percentage-only HUDs, which
can only confirm a level from the badge, waited for five neural votes. Measured case
2026-11-26: Streamer_B stayed held at an old level for hours.

## How it reads

1. The orange tiles' bounding box (`level_tile_box`) is split into equal cells. The cell
   count is the one (1-3) whose cells are near-square. A box touching the crop edge
   (`clipped`), tiles under 10 px tall (`too_small`) and other widths (`tile_count`) are refused.
2. Each cell's white ink (RGB minimum, so the orange goes dark) is cropped to the ink's own
   box. Edge rows and columns with fewer than 2 ink pixels are tile-border specks and are
   dropped. The ink is scaled to 12 px tall, centred in a 12x12 grid and normalised. Scaling
   each digit to its own height makes 720p, 1080p and resized game windows look alike.
3. A linear softmax over the 144 values gives each digit's probability. Every tile's top
   digit must reach 0.9; the level must be 1-200 without a leading zero.

Reading a badge takes about 0.4 ms in pure Python (Pillow only).

## Data

`private/badge-digits/` holds 1,903 badge crops, each checked by eye, from 178 sources:
frames from 90 roster streamers' public VODs at 720p (production captures the best rendition, usually 1080p, so VOD badges are the harder, smaller case), plus the
private recordings, live captures and investigation frames. 28 are labelled "x" (blends
during a level change, or too small to read by eye). Tesseract's and the model's reads were
only proposals. Retrain with:

```
python tools/train_badge_digits.py private/badge-digits --output src/exp_tracker/data/badge-digits.json
python tools/train_badge_digits.py private/badge-digits --folds 10   # cross-stream check
```

## Measured accuracy

| Check (gate 0.9) | Badge model read | Wrong | Tesseract read | Wrong |
| --- | ---: | ---: | ---: | ---: |
| 10-fold cross-stream (whole streams held out), 1,875 readable badges | 1,788 (95%) | 0 | | |
| First 1,589 of them | | | 911 (57%) | 21 |
| Older VODs (3rd-4th most recent), 286 badges, 72 streamers | 267 (93%) | 0 | | |
| Older VODs (5th-6th), 295 badges, 67 streamers, final model | 282 (96%) | 0 | 131 (44%) | 5 |

The first held-out VODs found one stream whose small, sharpened tiles made the first model
read 36 as 76 and 39 as 79 (3 of 286, confidence 0.93-0.97). Bright tile-border pixels were
stretching the ink box; dropping edge rows/columns with a single bright pixel fixed all three
without losing reads elsewhere (the 267 above). Those badges were then added to training, and
the final model was checked on the second, untouched set.

Blends during a level change can read as either level. The reader cannot see a tile the
crop cut off entirely (a crop starting between two tiles would read 89 as 9); Tesseract had
the same exposure, and the guard holds a level below the floor as a regression.

## Live A/B (2026-11-26)

Two fresh local trackers captured the same six live streams at the same time, one on the
previous code and one with the badge model:

| About 27 minutes, 5 HUD streams | Previous | Badge model |
| --- | ---: | ---: |
| HUD frames with a level read | 220 / 364 | 355 / 377 |
| Level read disagreeing with the neural read | 28 | 2 |
| Frames held by the level guard | 82 | 1 |
| Streamer_B frames accepted (percentage-only HUD) | 1 | 74 |
| Mean level-read time per frame | 0.6-1.5 s | 1-230 ms |

All five saved levels matched production's. Streamer_B never got a saved level under the
previous code; Tesseract read its 89 as 85, 99 or 893. Both disagreements and the one hold
under the model came from the Tesseract fallback (83 and 893 for 89) on frames the model
was unsure of. Over the same two minutes the two trackers' process trees used 61.0 and
50.8 CPU seconds; short-lived Tesseract processes between samples make the first figure a
lower bound.

Where the model is unsure, Tesseract still reads about half of the badges, so it stays as
the fallback. Across the cross-stream folds it was right on 45 and wrong on 2 of those badges.

## What changes for tracking

With a reliable badge read on almost every frame, percentage-only HUDs get two independent
readers again: a badge read and a neural read that agree qualify a frame, and two such frames
within 120 s confirm the next level (skips still need the character name). The five-vote
neural path stays for frames the model cannot read. A wrong badge read disagrees with the
neural read and holds that frame, as a Tesseract misread did.
