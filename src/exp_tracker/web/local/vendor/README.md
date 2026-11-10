# Vendored OCR runtime for /local

Served from this site so the local tracker never contacts a CDN. Files are byte-for-byte copies
from npm; update them together and re-run `node --test tools/local-tracker.test.mjs` and
`python -m pytest tests/test_export_pages.py`, then a live check (docs/local-tracker.md).

| File | Package (npm) | SHA-256 |
| --- | --- | --- |
| `tesseract.esm.min.js` | tesseract.js 7.0.0 `dist/` | `64871d76c75609fd5413b88a8171e2ef40deedd77d5875ba23df104b2d05eb29` |
| `worker.min.js` | tesseract.js 7.0.0 `dist/` | `576b7df7e3393e137e51849357c9adb53fe7ac1bb69bfa06cf3d61520f182c6d` |
| `tesseract-core-simd-lstm.js` | tesseract.js-core 7.0.0 | `e48e2f02ddae3716c8dd24bf41cd290d4efa96892d689cdc4013c2545d63f469` |
| `tesseract-core-simd-lstm.wasm` | tesseract.js-core 7.0.0 | `34e8d50cac216427d86bf397d610fdd9f49492539bbcdfbfccc4eda20c810bea` |
| `eng.traineddata.gz` | @tesseract.js-data/eng 1.0.0 `4.0.0_best_int/` | `45b4cb346724ac1774f1c36f42f182b887bcdb28ebe63e6fff90ac41f3fcff91` |

Only the SIMD + LSTM-only core is shipped (WebAssembly SIMD: Chrome/Edge 91+, Firefox 89+,
Safari 16.4+); it runs on the CPU and needs no GPU. Licences: `LICENSE-tesseract.js.md`,
`LICENSE-tesseract.js-core.txt` (Apache-2.0). The English data is Apache-2.0 (tesseract-ocr/tessdata).
The `sourceMappingURL` comments point at maps that are not shipped; browsers fetch them only with
developer tools open.
