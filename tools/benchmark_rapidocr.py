"""Isolated pretrained OCR benchmark on existing private EXP crops, never ingestion.

Optional neural dependencies are imported only by main. No glyph segmentation,
training, expected-answer preprocessing or multi-line text reconstruction.
"""

import argparse
from collections import Counter
import difflib
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import re
import statistics
import sys
import time

# The experiment environment need not install the production project's dependencies.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from exp_tracker.parsing import parse_exp


NUMBER = r'(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{1,3}(?:\.[0-9]{3})+|[0-9]+)'
PERCENT = r'[0-9]{1,2}\.[0-9]{2}'


def interpret(text):
    """Untrusted diagnostics: missing punctuation allowed, missing numbers never filled.

    Two quantities need an opening delimiter or whitespace plus an explicit percent
    sign. Concatenated numbers with a missing opener are deliberately ambiguous.
    """
    result = dict(exp=None, percentage=None, pair=None, bracketed_syntax=False,
                  trusted=False, reason='no_single_line', tokens=None)
    if text is None:
        return result
    strict = parse_exp(text)
    loose = re.fullmatch(rf'\s*(?:EXP[.:]?)?\s*({NUMBER})(\s*[\[(]\s*|\s+)'
                         rf'({PERCENT})\s*(%?)\s*[\])]?\s*', text, re.I)
    complete = strict is not None or bool(loose and (any(c in loose[2] for c in '[(') or loose[4] == '%'))
    if strict is not None:
        result.update(exp=strict[0], percentage=strict[1], bracketed_syntax=True)
    elif loose and (any(c in loose[2] for c in '[(') or loose[4] == '%'):
        result.update(exp=int(loose[1].replace(',', '').replace('.', '')), percentage=float(loose[3]))
    else:
        exp = re.match(rf'\s*(?:EXP[.:]?)?\s*({NUMBER})\s*[\[(]', text, re.I)
        percent = re.search(rf'[\[(]\s*({PERCENT})\s*%\s*[\])]?\s*$', text)
        result.update(exp=int(exp[1].replace(',', '').replace('.', '')) if exp else None,
                      percentage=float(percent[1]) if percent else None)
    tokens = re.fullmatch(r'\s*(?:EXP[.:]?)?\s*([^\[\]()]+)[\[(]([^\[\]()%]+)%?[\])]?\s*', text, re.I)
    if tokens:
        result['tokens'] = dict(exp=tokens[1].strip(), percentage=tokens[2].strip())
    delimited = re.fullmatch(r'\s*(?:EXP[.:]?)?\s*([^\[\(]+)[\[(]([^%]+)%(.*)', text, re.I)
    if delimited:
        # Explicitly retain extra suffix digits; token diagnostics never rescue a pair.
        result['tokens'] = dict(exp=delimited[1].strip(), percentage=delimited[2].strip(),
                                suffix=delimited[3])
    if complete and result['exp'] is not None and result['percentage'] is not None:
        if result['exp'] > 2**63-1 or not 0 <= result['percentage'] < 100:
            result['reason'] = 'out_of_range'
        elif result['exp'] == 0 and result['percentage'] != 0:
            result['reason'] = 'inconsistent_zero'
        else:
            result['pair'] = [result['exp'], result['percentage']]
            result['reason'] = 'bracketed_diagnostic' if result['bracketed_syntax'] else 'insufficient_punctuation'
    else:
        result['reason'] = 'partial_or_unparseable'
    return result


def digit_edits(observed, expected):
    """Descriptive alignment only; never used to change or accept OCR output."""
    if observed is None:
        return None
    observed = re.sub(r'[\s,.]', '', observed)
    edits = Counter()
    for operation, a, b, c, d in difflib.SequenceMatcher(None, expected, observed, autojunk=False).get_opcodes():
        if operation == 'insert': edits['added'] += d-c
        elif operation == 'delete': edits['missing'] += b-a
        elif operation == 'replace':
            edits['substituted'] += min(b-a, d-c)
            edits['missing'] += max(0, (b-a)-(d-c))
            edits['added'] += max(0, (d-c)-(b-a))
    return dict(edits)


def score_text(text, expected):
    parsed = interpret(text)
    targets = dict(exp=expected['current_exp'], percentage=expected['percentage'],
                   pair=[expected['current_exp'], expected['percentage']])
    tokens = parsed['tokens'] or {}
    token_exp = int(tokens['exp'].replace(',', '').replace('.', '')) if re.fullmatch(NUMBER, tokens.get('exp','')) else None
    token_percent = float(tokens['percentage']) if re.fullmatch(PERCENT, tokens.get('percentage','')) else None
    values = {**parsed, 'token_exp':token_exp, 'token_percentage':token_percent,
              'token_pair':[token_exp,token_percent] if token_exp is not None and token_percent is not None else None}
    targets.update(token_exp=targets['exp'], token_percentage=targets['percentage'], token_pair=targets['pair'])
    metrics = {}
    for name, target in targets.items():
        unknown = target is None or isinstance(target, list) and None in target
        value = values[name]
        metrics[name] = ('unscored' if unknown else 'unavailable' if value is None
                         else 'label_match' if value == target else 'label_mismatch')
    canonical = f"{expected['current_exp']:,}[{expected['percentage']:.2f}%]" if all(v is not None for v in targets['pair']) else None
    edits = {key: digit_edits(tokens.get(key), str(target).replace('.', '') if key == 'exp'
                              else f'{target:.2f}'.replace('.', '')) if target is not None else None
             for key,target in list(targets.items())[:2]}
    return dict(parsed=parsed, metrics=metrics, literal_canonical_match=text == canonical if canonical else None,
                compact_canonical_match=re.sub(r'\s+', '', text or '') == canonical if canonical else None,
                digit_edits=edits,
                percentage_format_valid=bool(tokens and re.fullmatch(PERCENT, tokens['percentage'])))


def timing(values):
    values = sorted(values)
    return dict(mean_ms=1000*statistics.mean(values), median_ms=1000*statistics.median(values),
                p95_ms=1000*values[math.ceil(.95*len(values))-1])


def crop_path(manifest, data, item):
    if 'exp_crop' in item:
        return manifest.parent / item['exp_crop']
    run, index = item['id'].split('/')
    return manifest.parent / data['crop_root'] / f'{run}-crops' / f'{int(index):04d}' / 'exp-crop.png'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--all', action='store_true', help='Expand to every saved crop, keeping the same variants')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    plan = json.loads(args.plan.read_text())
    data = json.loads(args.manifest.read_text())
    stream = data['examples'][0]['id'].split('/')[0]
    selected = data['examples'] if args.all else [e for e in data['examples'] if int(e['id'].split('/')[1]) in plan['selection'][stream]]
    files = [args.manifest, args.plan, Path(__file__), Path(__file__).parents[1]/'src/exp_tracker/parsing.py']
    files += [crop_path(args.manifest, data, item) for item in selected]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    import_started = time.perf_counter()
    from PIL import Image, ImageDraw
    import rapidocr
    from rapidocr import RapidOCR
    import onnxruntime
    import psutil
    import_seconds = time.perf_counter()-import_started
    process = psutil.Process()
    rss_before = process.memory_info().rss
    models = Path(rapidocr.__file__).parent/'models'
    params = {'Global.use_cls': False, 'EngineConfig.onnxruntime.intra_op_num_threads': 1,
              'EngineConfig.onnxruntime.inter_op_num_threads': 1,
              'Det.model_path': str(models/'PP-OCRv6_det_small.onnx'),
              'Rec.model_path': str(models/'PP-OCRv6_rec_small.onnx')}
    started = time.perf_counter()
    engine = RapidOCR(params=params)
    constructor_seconds = time.perf_counter()-started
    warmup = Image.new('RGB', (280, 48), 'black')
    ImageDraw.Draw(warmup).text((8, 8), '123[45.67%]', fill='white', font_size=24)
    started = time.perf_counter()
    engine(warmup, use_det='detect_recognize' in plan['modes'], use_cls=False, use_rec=True)
    cold_first_call = time.perf_counter()-started
    engine(warmup, use_det=False, use_cls=False, use_rec=True)
    records = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw_log = args.output.with_suffix('.jsonl')
    raw_log.write_text('', encoding='utf-8')
    cpu_started = time.process_time()
    for item in selected:
        with Image.open(crop_path(args.manifest, data, item)) as source:
            image = source.convert('RGB')
        for scale in plan['scales']:
            resized = image if scale == 1 else image.resize((image.width*scale, image.height*scale), Image.Resampling.BICUBIC)
            for mode in plan['modes']:
                started = time.perf_counter()
                output = engine(resized, use_det=mode == 'detect_recognize', use_cls=False, use_rec=True)
                elapsed = time.perf_counter()-started
                raw = {key: getattr(output, key, None) for key in ('txts','scores','boxes','elapse','elapse_list')}
                raw = {key: value.tolist() if hasattr(value, 'tolist') else value for key,value in raw.items()}
                text = raw['txts'][0] if raw['txts'] is not None and len(raw['txts']) == 1 else None
                row = dict(id=item['id'], seconds=item['seconds'], geometry=item.get('geometry','original'),
                    expected={k:item[k] for k in ('level','current_exp','percentage')},
                    human_verified=item.get('human_verified', False), mode=mode, scale=scale,
                    input_size=resized.size, raw=raw, text=text, seconds_elapsed=elapsed)
                with raw_log.open('a', encoding='utf-8') as handle:
                    handle.write(json.dumps(row)+'\n')
                records.append({**row, **score_text(text, item)})
        print(f'{len(records)//(len(plan["scales"])*len(plan["modes"]))}/{len(selected)} {item["id"]}', flush=True)
    cpu_seconds = time.process_time()-cpu_started
    summaries = {}
    for geometry in ['all', *sorted({r['geometry'] for r in records})]:
        summaries[geometry] = {}
        for scale in plan['scales']:
            for mode in plan['modes']:
                rows = [r for r in records if r['mode']==mode and r['scale']==scale and (geometry=='all' or r['geometry']==geometry)]
                summaries[geometry][f'{mode}_{scale}x'] = dict(count=len(rows),
                    metrics={key:dict(Counter(r['metrics'][key] for r in rows)) for key in
                             ('exp','percentage','pair','token_exp','token_percentage','token_pair')},
                    bracketed_pairs=sum(r['parsed']['bracketed_syntax'] and r['parsed']['pair'] is not None for r in rows),
                    literal_canonical_matches=sum(r['literal_canonical_match'] is True for r in rows),
                    compact_canonical_matches=sum(r['compact_canonical_match'] is True for r in rows),
                    timing=timing([r['seconds_elapsed'] for r in rows]))
    model_info = {p.name:dict(bytes=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in models.glob('*.onnx')}
    providers = {name:getattr(engine, name).session.session.get_providers()
                 for name in ('text_det','text_rec') if getattr(engine, name) is not None}
    environment = dict(python=sys.version, packages={d.metadata['Name']: d.version for d in importlib.metadata.distributions()},
        models=model_info, providers=providers, params=params, import_seconds=import_seconds,
        constructor_seconds=constructor_seconds, cold_first_call_seconds=cold_first_call,
        rss_before_engine_mib=rss_before/1024**2, rss_after_mib=process.memory_info().rss/1024**2,
        peak_process_rss_mib=process.memory_info().peak_wset/1024**2 if hasattr(process.memory_info(),'peak_wset') else None,
        measured_cpu_seconds=cpu_seconds)
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(input_hashes=hashes, environment=environment,
        summary=summaries, records=records), indent=2)+'\n', encoding='utf-8')
    print(json.dumps(summaries['all'], indent=2))


if __name__ == '__main__':
    main()
