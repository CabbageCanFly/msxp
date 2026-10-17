"""One bounded crop, one isolated CPU inference. Private PNG stdin; JSON stdout."""

import contextlib
import hashlib
from importlib.metadata import version
from io import BytesIO
import json
from pathlib import Path
import sys
import time


def main():
    # Keep optional neural imports out of the capture/test environment.
    with contextlib.redirect_stdout(sys.stderr):
        started = time.perf_counter()
        import rapidocr
        from rapidocr import RapidOCR
        from PIL import Image

        if version('rapidocr') != '3.10.0':
            raise ValueError('Expected the benchmarked RapidOCR 3.10.0 environment')
        models = Path(rapidocr.__file__).parent / 'models'
        paths = {kind: models / f'PP-OCRv6_{kind}_small.onnx' for kind in ('det', 'rec')}
        if not all(path.is_file() for path in paths.values()):
            raise ValueError('Existing local model files required; no downloads')
        payload = sys.stdin.buffer.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024:
            raise ValueError('Crop exceeds byte limit')
        with Image.open(BytesIO(payload)) as source:
            if source.width > 1024 or source.height > 256 or min(source.size) < 1:
                raise ValueError('Crop exceeds dimension limit')
            image = source.convert('RGB')
        image = image.resize((image.width * 2, image.height * 2), Image.Resampling.BICUBIC)
        engine = RapidOCR(params={
            'Global.use_cls': False,
            'EngineConfig.onnxruntime.intra_op_num_threads': 1,
            'EngineConfig.onnxruntime.inter_op_num_threads': 1,
            **{f'{kind.title()}.model_path': str(path) for kind, path in paths.items()},
        })
        initialization = time.perf_counter() - started
        started = time.perf_counter()
        output = engine(image, use_det=False, use_cls=False, use_rec=True)
        inference = time.perf_counter() - started
        raw = {key: getattr(output, key, None)
               for key in ('txts', 'scores', 'boxes', 'elapse', 'elapse_list')}
        raw = {key: value.tolist() if hasattr(value, 'tolist') else value for key, value in raw.items()}
        text = raw['txts'][0] if raw['txts'] is not None and len(raw['txts']) == 1 else None
        result = dict(text=text, raw=raw, initialization_seconds=initialization,
                      inference_seconds=inference, input_size=image.size,
                      versions={name: version(name) for name in ('rapidocr', 'onnxruntime')},
                      model_sha256={kind: hashlib.sha256(path.read_bytes()).hexdigest()
                                    for kind, path in paths.items()})
    serialized = json.dumps(result, allow_nan=False)
    if len(serialized.encode()) > 65536:
        raise ValueError('Result exceeds byte limit')
    print(serialized)


if __name__ == '__main__':
    main()
