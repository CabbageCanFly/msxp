"""Fixed offline level comparison; no production integration, substitutions or acceptance."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import time

from PIL import Image, ImageChops, ImageOps

from benchmark_rapidocr import timing
from shadow_review import dump_new, private

VARIANTS = ('rgb2', 'rgb4', 'neutral4')


def preprocess(image, variant):
    if variant not in VARIANTS:
        raise ValueError('Only the three predeclared variants are supported')
    image = image.convert('RGB')
    if variant == 'neutral4':
        red, green, blue = image.split()
        image = ImageOps.invert(ImageChops.darker(ImageChops.darker(red, green), blue)).convert('RGB')
    scale = 2 if variant == 'rgb2' else 4
    return image.resize((image.width*scale, image.height*scale), Image.Resampling.BICUBIC)


def numeric_level(text):
    """Whole ASCII numeral, no internal space joining, prefixes, S->5 or zero repair."""
    if not isinstance(text, str) or not re.fullmatch(r'[1-9][0-9]{0,2}', text.strip()):
        return None
    level = int(text.strip())
    return level if 1 <= level <= 200 else None


def score(text, reference, negative=False):
    level = numeric_level(text)
    if text is None or text == '':
        return 'no_output'
    if level is None:
        return 'out_of_range_or_malformed_numeric' if re.fullmatch(r'[0-9]+',text.strip()) else 'nonnumeric'
    if negative:
        return 'unsafe_numeric_on_negative'
    if reference is None:
        return 'unknown_reference'
    return 'correct_numeric' if level == reference else 'incorrect_numeric'


def agreement(texts):
    """Agreement is a correlated diagnostic only, not numerical verification."""
    levels = [numeric_level(text) for text in texts]
    return levels[0] if len(levels) >= 2 and None not in levels and len(set(levels)) == 1 else None


def infer(engine, image):
    started = time.perf_counter()
    output = engine(image, use_det=False, use_cls=False, use_rec=True)
    elapsed = time.perf_counter()-started
    raw = {key:getattr(output,key,None) for key in ('txts','scores','boxes','elapse','elapse_list')}
    raw = {key:value.tolist() if hasattr(value,'tolist') else value for key,value in raw.items()}
    text = raw['txts'][0] if raw['txts'] is not None and len(raw['txts']) == 1 else None
    return dict(raw=raw, text=text, numeric_level=numeric_level(text), inference_seconds=elapsed, trusted=False)


def forbid_download(*args, **kwargs):
    raise RuntimeError('This diagnostic permits existing local models/dictionaries only')


def check_inputs(hashes):
    for name,value in hashes.items():
        path=Path(name).resolve()
        if not path.is_relative_to(Path.cwd().resolve()):
            raise ValueError('Input receipt escapes the working directory')
        if hashlib.sha256(path.read_bytes()).hexdigest() != value:
            raise ValueError('Frozen diagnostic input changed')


def run(manifest, output):
    manifest, output = private(manifest), private(output)
    if output.exists():
        raise ValueError('Use a new output directory')
    plan = json.loads(manifest.read_text(encoding='utf-8'))
    if tuple(plan['variants']) != VARIANTS or not 1 <= len(plan['examples']) <= 60:
        raise ValueError('Expected the fixed three variants and at most 60 examples')
    hashes = {**plan['input_hashes'], str(manifest.relative_to(Path.cwd())):hashlib.sha256(manifest.read_bytes()).hexdigest()}
    check_inputs(hashes)
    output.mkdir(parents=True, exist_ok=False)
    dump_new(output/'input-hashes.json', hashes)
    import psutil
    process = psutil.Process()
    before_import = process.memory_info().rss
    started = time.perf_counter()
    import rapidocr
    from rapidocr import RapidOCR
    from rapidocr.utils.download_file import DownloadFile
    from importlib.metadata import version
    import_seconds = time.perf_counter()-started
    if version('rapidocr') != '3.10.0':
        raise ValueError('Use the existing benchmarked RapidOCR 3.10.0 environment')
    DownloadFile.run = staticmethod(forbid_download)
    model = Path(rapidocr.__file__).parent/'models/PP-OCRv6_rec_small.onnx'
    if not model.is_file() or hashlib.sha256(model.read_bytes()).hexdigest() != plan['recognition_model_sha256']:
        raise ValueError('Existing recognition model does not match the frozen plan')
    params = {'Global.use_det':False, 'Global.use_cls':False,
              'EngineConfig.onnxruntime.intra_op_num_threads':1,
              'EngineConfig.onnxruntime.inter_op_num_threads':1, 'Rec.model_path':str(model)}
    started = time.perf_counter()
    engine = RapidOCR(params=params)
    constructor_seconds = time.perf_counter()-started
    from PIL import ImageDraw
    warmup = Image.new('RGB',(280,48),'black')
    ImageDraw.Draw(warmup).text((8,8),'123[45.67%]',fill='white',font_size=24)
    cold = infer(engine,warmup)
    warm = infer(engine,warmup)
    recognizer = engine.text_rec
    providers = recognizer.session.session.get_providers()
    assert providers == ['CPUExecutionProvider'] and engine.text_det is None and engine.text_cls is None
    rows, agreements = [], []
    started, cpu = time.perf_counter(), time.process_time()
    with (output/'raw.jsonl').open('x',encoding='utf-8') as log:
        for example in plan['examples']:
            image = None
            if example['crop'] is not None:
                with Image.open(private(manifest.parent/example['crop'])) as source:
                    if source.width > 1024 or source.height > 256:
                        raise ValueError('Level crop exceeds diagnostic limits')
                    image = source.convert('RGB')
            values = {}
            for variant in VARIANTS:
                prep_started = time.perf_counter()
                prepared = preprocess(image,variant) if image is not None else None
                prep_seconds = time.perf_counter()-prep_started
                result = infer(engine,prepared) if prepared is not None else dict(text=None,raw=None,numeric_level=None,inference_seconds=None,trusted=False)
                record = dict(id=example['id'],group=example['group'],variant=variant,
                    reference_level=example['reference_level'], reference_provenance=example['reference_provenance'],
                    input_size=prepared.size if prepared is not None else None,preprocess_seconds=prep_seconds,
                    outcome=score(result['text'],example['reference_level'],example.get('negative_control',False)) if image is not None else 'missing_crop', **result)
                log.write(json.dumps(record,allow_nan=False)+'\n'); log.flush()
                rows.append(record); values[variant]=result['text']
            common = agreement([values['rgb2'],values['rgb4']])
            agreements.append(dict(id=example['id'],group=example['group'],level=common,trusted=False,
                outcome=score(str(common) if common is not None else None,example['reference_level'],example.get('negative_control',False))))
    resources = dict(loop_wall_seconds=time.perf_counter()-started,loop_cpu_seconds=time.process_time()-cpu,
        rss_before_import_mib=before_import/1024**2,rss_after_mib=process.memory_info().rss/1024**2,
        peak_process_rss_mib=getattr(process.memory_info(),'peak_wset',process.memory_info().rss)/1024**2,
        import_seconds=import_seconds,constructor_seconds=constructor_seconds,
        cold_first_call_seconds=cold['inference_seconds'],warmup_second_call_seconds=warm['inference_seconds'])
    assert engine.text_rec is recognizer and engine.text_det is None and engine.text_cls is None
    check_inputs(hashes)
    summary = {}
    for group in sorted({row['group'] for row in rows}):
        examples = [row for row in plan['examples'] if row['group']==group]
        summary[group] = dict(denominator=len(examples),variants={variant:dict(
            outcomes=dict(Counter(row['outcome'] for row in rows if row['group']==group and row['variant']==variant)),
            timing=timing([row['inference_seconds'] for row in rows if row['group']==group and row['variant']==variant and row['inference_seconds'] is not None])) for variant in VARIANTS},
            rgb_scale_agreement=dict(Counter(row['outcome'] for row in agreements if row['group']==group)),
            tesseract=dict(Counter('unavailable' if row['tesseract_level'] is None else
                'unsafe_numeric_on_negative' if row.get('negative_control') else
                'correct_numeric' if row['tesseract_level']==row['reference_level'] else 'incorrect_numeric' for row in examples)))
    report = dict(trusted=False,plan_sha256=hashes[str(manifest.relative_to(Path.cwd()))],
        versions={name:version(name) for name in ('rapidocr','onnxruntime')}, providers=providers,
        recognition_model_sha256=plan['recognition_model_sha256'],engine_reused=True,
        resources=resources,summary=summary,records=rows,rgb_scale_agreement=agreements)
    dump_new(output/'report.json',report)
    print(json.dumps(dict(summary=summary,resources=resources),indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run(args.manifest,args.output)


if __name__=='__main__':
    main()
