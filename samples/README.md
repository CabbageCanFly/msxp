# Private sample fixtures

Place the supplied screenshots here as `maplestory-classic-stream1.png` and
`maplestory-classic-stream2.png`. They are deliberately ignored by Git, as are
all crops and debug outputs. Do not force-add third-party screenshots.

Expected game HUD values (test assertions only):

| Fixture | Level | Current EXP | Percent |
| --- | ---: | ---: | ---: |
| stream1 | 60 | 71,441 | 5.90 |
| stream2 | 56 | 641,122 | 65.59 |

stream1 also has a third-party tracker displaying a different reading. It must
not supply OCR data. Public checkouts run synthetic tests and skip private fixtures.

