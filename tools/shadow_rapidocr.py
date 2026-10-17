"""One bounded attempt, one CPU recognizer. Legacy PNG or opt-in framed PNG pair."""

import contextlib
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys
import time

from shadow_neural import MAX_BYTES, MAX_REQUEST, EXP_SIZE, LEVEL_SIZE, load_crop, unpack, empty_level, level_result


def recognize(engine,image):
    started=time.perf_counter()
    output=engine(image,use_det=False,use_cls=False,use_rec=True)
    inference=time.perf_counter()-started
    raw={key:getattr(output,key,None) for key in ('txts','scores','boxes','elapse','elapse_list')}
    raw={key:value.tolist() if hasattr(value,'tolist') else value for key,value in raw.items()}
    text=raw['txts'][0] if raw['txts'] is not None and len(raw['txts'])==1 else None
    return dict(text=text,raw=raw,inference_seconds=inference,input_size=image.size)


def recognize_fields(engine,image,level_payload=None,*,experimental=False):
    from PIL import Image
    image=image.resize((image.width*2,image.height*2),Image.Resampling.BICUBIC)
    result=recognize(engine,image)
    if experimental:
        result['neural_level']=empty_level('missing_crop')
        if level_payload:
            try:
                level=load_crop(level_payload,LEVEL_SIZE)
            except (OSError,ValueError):
                result['neural_level']=empty_level('invalid_crop')
            else:
                try:
                    from benchmark_rapidocr_levels import preprocess
                    started=time.perf_counter()
                    level=preprocess(level,'neutral4')
                    prep=time.perf_counter()-started
                    output=recognize(engine,level)
                    result['neural_level']=level_result(output['raw'],output['inference_seconds'],prep)
                    result['neural_level']['input_size']=level.size
                except Exception:
                    result['neural_level']=empty_level('failed')
    return result


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experimental-neural-level',action='store_true')
    args=parser.parse_args()
    # Keep optional neural imports out of the capture/test environment.
    with contextlib.redirect_stdout(sys.stderr):
        started = time.perf_counter()
        import rapidocr
        from rapidocr import RapidOCR
        from rapidocr.utils.download_file import DownloadFile
        def no_download(*args,**kwargs):
            raise ValueError('Existing local model/dictionary required; no downloads')
        DownloadFile.run=staticmethod(no_download)

        if version('rapidocr') != '3.10.0':
            raise ValueError('Expected the benchmarked RapidOCR 3.10.0 environment')
        models = Path(rapidocr.__file__).parent / 'models'
        paths = {kind: models / f'PP-OCRv6_{kind}_small.onnx' for kind in ('det', 'rec')}
        if not all(path.is_file() for path in paths.values()):
            raise ValueError('Existing local model files required; no downloads')
        limit=MAX_REQUEST if args.experimental_neural_level else MAX_BYTES
        payload = sys.stdin.buffer.read(limit + 1)
        if len(payload) > limit:
            raise ValueError('Crop exceeds byte limit')
        exp_payload,level_payload=unpack(payload) if args.experimental_neural_level else (payload,None)
        image=load_crop(exp_payload,EXP_SIZE)
        engine = RapidOCR(params={
            'Global.use_cls': False,
            'EngineConfig.onnxruntime.intra_op_num_threads': 1,
            'EngineConfig.onnxruntime.inter_op_num_threads': 1,
            **{f'{kind.title()}.model_path': str(path) for kind, path in paths.items()},
        })
        initialization = time.perf_counter() - started
        result = dict(**recognize_fields(engine,image,level_payload,experimental=args.experimental_neural_level),
                      initialization_seconds=initialization,
                      versions={name: version(name) for name in ('rapidocr', 'onnxruntime')},
                      model_sha256={kind: hashlib.sha256(path.read_bytes()).hexdigest()
                                    for kind, path in paths.items()})
    serialized = json.dumps(result, allow_nan=False)
    if len(serialized.encode()) > 65536:
        raise ValueError('Result exceeds byte limit')
    print(serialized)


if __name__ == '__main__':
    main()
