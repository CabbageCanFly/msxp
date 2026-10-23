"""One bounded attempt, one CPU recognizer. Legacy PNG or opt-in framed PNG pair."""

import contextlib
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import struct
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
                    from exp_tracker.diagnostic_geometry import level_tile_box
                    from exp_tracker.diagnostic_evidence import NEURAL_SEED_SCORE
                    started=time.perf_counter()
                    source=level
                    box=level_tile_box(level)
                    if box is not None: level=level.crop(box)
                    level=preprocess(level,'neutral4')
                    prep=time.perf_counter()-started
                    output=recognize(engine,level)
                    result['neural_level']=level_result(output['raw'],output['inference_seconds'],prep)
                    result['neural_level']['input_size']=level.size
                    tile=result['neural_level']
                    if (box is not None and 0<box[0]<box[2]<source.width and 0<box[1]<box[3]<source.height
                            and tile['level'] is not None
                            and tile['score'] is not None and tile['score']<NEURAL_SEED_SCORE):
                        # Crop agreement improves one frame's evidence; it is not temporal confirmation.
                        try:
                            started=time.perf_counter()
                            wider=preprocess(source,'neutral4')
                            retry_prep=time.perf_counter()-started
                            retry_output=recognize(engine,wider)
                            retry=level_result(retry_output['raw'],retry_output['inference_seconds'],retry_prep)
                        except Exception:
                            pass
                        else:
                            if retry['level']==tile['level'] and retry['score'] is not None and retry['score']>=NEURAL_SEED_SCORE:
                                result['neural_level']={**retry, 'tile_attempt':tile, 'input_size':wider.size,
                                    'inference_seconds':tile['inference_seconds']+retry['inference_seconds'],
                                    'preprocess_seconds':tile['preprocess_seconds']+retry['preprocess_seconds']}
                except Exception:
                    result['neural_level']=empty_level('failed')
    return result


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experimental-neural-level',action='store_true')
    parser.add_argument('--serve',action='store_true',help='Resident: !I-length-prefixed requests on stdin, one JSON line each; any error exits')
    args=parser.parse_args()
    out=sys.stdout
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
        engine = RapidOCR(params={
            'Global.use_cls': False,
            'EngineConfig.onnxruntime.intra_op_num_threads': 1,
            'EngineConfig.onnxruntime.inter_op_num_threads': 1,
            **{f'{kind.title()}.model_path': str(path) for kind, path in paths.items()},
        })
        initialization = time.perf_counter() - started
        versions={name: version(name) for name in ('rapidocr', 'onnxruntime')}
        hashes={kind: hashlib.sha256(path.read_bytes()).hexdigest() for kind, path in paths.items()}

        def answer(payload, **extra):
            exp_payload,level_payload=unpack(payload) if args.experimental_neural_level else (payload,None)
            image=load_crop(exp_payload,EXP_SIZE)
            result = dict(**recognize_fields(engine,image,level_payload,experimental=args.experimental_neural_level),
                          versions=versions, model_sha256=hashes, **extra)
            serialized = json.dumps(result, allow_nan=False)
            if len(serialized.encode()) > 65536:
                raise ValueError('Result exceeds byte limit')
            out.write(serialized+'\n'); out.flush()

        if not args.serve:
            payload = sys.stdin.buffer.read(limit + 1)
            if len(payload) > limit:
                raise ValueError('Crop exceeds byte limit')
            answer(payload, initialization_seconds=initialization)
            return
        request=0
        while header := sys.stdin.buffer.read(4):
            length=struct.unpack('!I',header)[0] if len(header)==4 else limit+1
            payload=sys.stdin.buffer.read(length) if length<=limit else b''
            if len(payload)!=length:
                raise ValueError('Incomplete or oversized request')
            request+=1
            # Initialization is paid once; later requests report zero rather than repeating it.
            answer(payload, initialization_seconds=initialization if request==1 else 0.0, worker_request=request)


if __name__ == '__main__':
    main()
