# Merged HP/MP labels in small HUDs

A low-resolution HUD could be visible and readable while localization returned
`missing_hud`. Tesseract sometimes merged the HP/MP label and its value, reading
the opening bracket as `I` or `R`. The label recognizer accepted `MP123/456`, but
rejected tokens such as `MPi123/456]`.

`adaptive_hud.label()` now recognizes this bounded HP/MP token form. After the
bracket lookalike, a nonempty suffix must contain a digit or end in a closing
bracket. Ordinary words without those markers remain rejected. This only
identifies a label: the raw token and its numbers are not rewritten. EXP and LV
label rules, full-frame scanning, both existing OCR scales, layout geometry,
competing-HUD rejection and numerical/identity safeguards remain in force. The
stricter bare-label fallback for a missing LV does not accept merged HP/MP words.
There are no additional OCR requests, streamer-specific coordinates or expected
EXP values in the reader.

## Offline check

Extracted original 1280x720 frames from a public archive covering the reported
failures, rather than reducing desktop screenshots. Numbers were visually
checked using enlarged original HUD pixels; labels are provisional, one reviewer.

| Same frames, before/after | Before | After |
| --- | --- | --- |
| Initial ten frames, used to diagnose the label problem | 8/10 | 10/10 |
| Eight additional later frames, checked after the change | 5/8 | 8/8 |
| Total correct recovered EXP/percentage readings | 13/18 | 18/18 |

The fixed readings also passed the existing autonomous level guard, persistence
and public player projection in a fresh disposable SQLite database. This uses
the existing grammar recovery; it does not claim all raw strings are strict OCR
pairs. Synthetic regressions cover the new token form, bounded negatives,
unchanged crop geometry, missing-LV rejection and competing HUDs. An additional
non-game frame remained rejected as a missing HUD. Four other live frames located
their HUD before and after the change; one still misread the final EXP digit.
That independent digit-recognition failure is not fixed by a label-only change.

These are frames from one stream, not a general 720p accuracy benchmark. Desktop
Tesseract 5.4.0 and the existing RapidOCR 3.10.0/ONNX Runtime 1.31.0 were used.
The change was not deployed to the VPS. Individual digit misreads, compressed or
hidden fields and processing-age timeouts can still withhold readings.

Frames, raw diagnostic outputs, enlarged review and the disposable replay stay
in ignored `private/plaguegms-debug/`; they are not committed.
