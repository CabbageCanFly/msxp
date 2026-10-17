"""Private blinded shadow review: prepare pixels, freeze human answers, then score saved outputs."""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import re

from PIL import Image, ImageDraw

from blinded_answers import NUMBER

MAX_LOG_BYTES = 4 * 1024 * 1024
FIELDS = ('exp', 'percentage', 'level')
METHODS = ('human_transcription', 'human_chatgpt_assisted', 'independent_human_review', 'practice_mechanics')
ROOT = Path(__file__).resolve().parents[1]
SCORING_FILES = ('tools/shadow_review.py', 'tools/analyze_temporal_ocr.py',
                 'tools/benchmark_rapidocr.py', 'src/exp_tracker/parsing.py')


def private(path):
    path = Path(path).resolve()
    root = Path.cwd().resolve()
    if not any(path.is_relative_to(root / name) for name in ('private', 'artifacts')):
        raise ValueError('All inputs/outputs must stay under the working directory private/ or artifacts/')
    return path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump_new(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write('\n')


def seal(path):
    path.with_suffix('.sha256').write_text(digest(path)+'\n', encoding='ascii')


def read_sealed(path):
    if digest(path) != path.with_suffix('.sha256').read_text(encoding='ascii').strip():
        raise ValueError(f'Frozen artifact changed: {path.name}')
    return json.loads(path.read_text(encoding='utf-8'))


def read_run(path):
    if path.stat().st_size > MAX_LOG_BYTES:
        raise ValueError('Shadow log exceeds 4 MiB limit')
    payload = path.read_bytes()
    if not payload.endswith(b'\n'):
        raise ValueError('Incomplete log tail; wait for a completed capture, never discard it')
    rows = [json.loads(line) for line in payload.decode('utf-8').splitlines() if line.strip()]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError('Expected shadow JSONL objects')
    attempts = [row for row in rows if row.get('type') == 'attempt']
    if (rows[0].get('type') != 'configuration' or rows[-1].get('type') != 'summary'
            or rows[-1].get('interrupted') is not False or not 1 <= len(attempts) <= 60
            or rows[0].get('count') != len(attempts) or rows[-1].get('attempts') != len(attempts)
            or [row.get('index') for row in attempts] != list(range(1, len(attempts)+1))
            or len(rows) != len(attempts)+2):
        raise ValueError('Use a completed run with every scheduled attempt, including failures, in order')
    return rows[0], attempts


def shuffled(entries, seed):
    return sorted(entries, key=lambda row: hashlib.sha256(
        f'{seed}:{row["stream"]}:{row["index"]}'.encode()).digest())


def relative(path, directory):
    import os
    return Path(os.path.relpath(path, directory)).as_posix()


def make_sheets(directory, entries):
    review = directory / 'review'
    native = review / 'pixels'
    native.mkdir(parents=True)
    for start in range(0, len(entries), 6):
        page = Image.new('RGB', (1440, 65+220*len(entries[start:start+6])), '#172238')
        draw = ImageDraw.Draw(page)
        draw.text((20, 15), 'PIXELS ONLY | Do not use OCR predictions, tables or neighboring values. Unknown/ambiguous is valid.', fill='white', font_size=18)
        for position, row in enumerate(entries[start:start+6]):
            top = 65+position*220
            draw.line((15, top, 1425, top), fill='#53647c')
            draw.text((20, top+8), row['id'], fill='#ffdb92', font_size=20)
            for field, left, width in [('exp', 20, 1040), ('level', 1100, 320)]:
                source = row[f'{field}_crop']
                if source is None:
                    draw.text((left, top+55), f'{field.upper()}: no saved pixels; mark unknown', fill='#d5dce8', font_size=16)
                    continue
                path = private(directory / source)
                with Image.open(path) as opened:
                    image = opened.convert('RGB')
                Image.frombytes('RGB', image.size, image.tobytes()).save(native / f'{row["id"]}-{field}.png')
                scale = min(6, width//image.width, 110//image.height)
                draw.text((left, top+35), f'{field.upper()} native {image.width}x{image.height}', fill='white', font_size=14)
                if image.width <= width and image.height <= 65:
                    page.paste(image, (left, top+56))
                else:
                    draw.text((left, top+56), 'See the anonymous pixels/ file for the full native crop', fill='white')
                if scale >= 1:
                    page.paste(image.resize((image.width*scale, image.height*scale), Image.Resampling.NEAREST), (left, top+105))
        page.save(review / f'sheet-{start//6+1:02d}.png')


def prepare(runs, directory, seed=17, practice=False):
    directory = private(directory)
    if directory.exists() or not 1 <= len(runs) <= 4:
        raise ValueError('Use a NEW output directory and 1..4 runs')
    entries, inputs, streams = [], {}, []
    def record(path):
        inputs[relative(path, directory)] = digest(path)
    seen = set()
    for run_index, (log, crops) in enumerate(runs, 1):
        log, crops = private(log), private(crops)
        if log in seen:
            raise ValueError('A log may not be selected twice')
        seen.add(log)
        configuration, attempts = read_run(log)
        record(log)
        stream = f'S{run_index:02d}'
        streams.append(dict(id=stream, log=relative(log, directory), interval=configuration.get('interval'),
                            attempts=len(attempts)))
        for row in attempts:
            item = dict(stream=stream, index=row['index'], frame_sha256=row.get('frame_sha256'),
                        identity_verified=False, main_hud_verified=False, pixel_hashes={})
            for field in ('exp', 'level'):
                path = private(crops / f'{row["index"]:04d}' / f'{field}.png')
                item[f'{field}_crop'] = None
                if path.exists():
                    if path.stat().st_size > 1024*1024:
                        raise ValueError('Crop exceeds 1 MiB')
                    with Image.open(path) as image:
                        if image.width*image.height > 1024*256:
                            raise ValueError('Crop exceeds pixel limit')
                        rgb = image.convert('RGB')
                        item['pixel_hashes'][field] = hashlib.sha256(str(rgb.size).encode()+rgb.tobytes()).hexdigest()
                    item[f'{field}_crop'] = relative(path, directory)
                    record(path)
            entries.append(item)
    directory.mkdir(parents=True)
    entries = shuffled(entries, seed)
    entries = [dict(row, id=f'R{i:03d}') for i, row in enumerate(entries, 1)]
    make_sheets(directory, entries)
    review = directory / 'review'
    with (review / 'answers-template.csv').open('x', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['id', *FIELDS, 'note'])
        writer.writerows([[row['id'], '', '', '', ''] for row in entries])
    dump_new(review / 'provenance-template.json', dict(reviewer='', method='', saved_predictions_seen=None,
        arithmetic_or_neighbor_values_used=None, prior_material_seen=None, independently_reviewed=None,
        independent_reviewer='', notes=''))
    (review / 'README.txt').write_text(
        'Review only this folder; do not open admin manifests, shadow logs, viewers or earlier predictions.\n'
        'Transcribe EXP, percentage (two decimals, no % sign), level; never use the EXP table or neighbors.\n'
        'Copy the templates to a separate completed CSV and provenance JSON. Do not edit the templates.\n'
        'Every field needs a value, unknown, or ambiguous; empty cells mean unfinished, not zero.\n'
        'No saved crop: mark unknown/ambiguous. Native pixels/ files have anonymous IDs only.\n'
        'Crops alone cannot establish main-game/character identity or exclude a secondary HUD.\n'
        'Report prior exposure, ChatGPT assistance and any arithmetic honestly. No AI-prefilled labels.\n', encoding='utf-8')
    for path in sorted(review.rglob('*')):
        if path.is_file():
            record(path)
    manifest = dict(version=1, created_at=datetime.now(timezone.utc).isoformat(), seed=seed,
                    ordering='sha256(seed:stream:index); no output-dependent selection', practice_only=practice,
                    streams=streams, entries=entries, inputs=inputs,
                    scoring_code={name:digest(ROOT/name) for name in SCORING_FILES},
                    source_identity='unverified; cropped pixels cannot authenticate main HUD or character')
    dump_new(directory / 'manifest.json', manifest)
    seal(directory / 'manifest.json')
    return manifest


def checked_manifest(directory):
    directory = private(directory)
    manifest = read_sealed(directory / 'manifest.json')
    for path, expected in manifest['inputs'].items():
        if digest(private(directory / path)) != expected:
            raise ValueError('Prepared input changed; preserve the existing evaluation')
    if any(digest(ROOT/name) != expected for name, expected in manifest['scoring_code'].items()):
        raise ValueError('Scoring software changed since preparation; start a separate evaluation')
    return manifest


def reference(value, field):
    if value in ('unknown', 'ambiguous'):
        return dict(status=value, value=None, raw=value)
    if not value:
        raise ValueError('Incomplete answers: use unknown or ambiguous explicitly')
    if field == 'exp' and re.fullmatch(NUMBER, value):
        number = int(value.replace(',', ''))
        if number <= 2**63-1:
            return dict(status='known', value=number, raw=value)
    if field == 'level' and re.fullmatch(r'[1-9][0-9]{0,2}', value) and int(value) <= 200:
        return dict(status='known', value=int(value), raw=value)
    if field == 'percentage' and re.fullmatch(r'[0-9]{1,3}\.[0-9]{2}', value) and Decimal(value) <= 100:
        return dict(status='known', value=value, raw=value)
    raise ValueError(f'Malformed {field} answer; no repair or rounding is permitted')


def freeze(directory, answers, provenance):
    directory = private(directory)
    if (directory / 'references.json').exists() or (directory / 'references.sha256').exists():
        raise ValueError('References already frozen; never overwrite')
    manifest = checked_manifest(directory)
    answers, provenance = private(answers), private(provenance)
    text = answers.read_text(encoding='utf-8-sig')
    records = list(csv.DictReader(io.StringIO(text)))
    ids = [row['id'] for row in manifest['entries']]
    if not records or list(records[0]) != ['id', *FIELDS, 'note'] or [row.get('id') for row in records] != ids:
        raise ValueError('Submission IDs/order/columns must exactly match the frozen review template')
    reviewed = []
    for row, entry in zip(records, manifest['entries']):
        if None in row or any(value is None for value in row.values()):
            raise ValueError('Incomplete CSV row or extra fields')
        values = {field: reference(row[field], field) for field in FIELDS}
        for field in FIELDS:
            crop = entry['level_crop' if field == 'level' else 'exp_crop']
            if crop is None and values[field]['status'] == 'known':
                raise ValueError('Cannot label unavailable crop pixels as known in this crop-only review')
        reviewed.append(dict(id=row['id'], fields=values, note=row['note']))
    meta = json.loads(provenance.read_text(encoding='utf-8-sig'))
    flags = ('saved_predictions_seen', 'arithmetic_or_neighbor_values_used', 'prior_material_seen', 'independently_reviewed')
    if (not isinstance(meta, dict) or not isinstance(meta.get('reviewer'), str) or not meta['reviewer'].strip()
            or meta.get('method') not in METHODS or any(type(meta.get(key)) is not bool for key in flags)
            or meta['independently_reviewed'] and (not isinstance(meta.get('independent_reviewer'), str)
                or not meta['independent_reviewer'].strip() or meta['independent_reviewer'] == meta['reviewer'])):
        raise ValueError('Complete explicit reviewer/method/provenance flags; independent review needs a second reviewer')
    frozen = dict(version=1, frozen_at=datetime.now(timezone.utc).isoformat(),
                  manifest_sha256=digest(directory / 'manifest.json'), input_hashes=manifest['inputs'],
                  answers_sha256=digest(answers), answers_text=text, provenance_sha256=digest(provenance),
                  provenance=meta, provenance_text=provenance.read_text(encoding='utf-8-sig'),
                  provenance_verification='reviewer-reported, not authenticated',
                  practice_only=manifest['practice_only'], references=reviewed)
    dump_new(directory / 'references.json', frozen)
    seal(directory / 'references.json')
    return frozen


def comparison(predicted, expected):
    if any(value is None for value in expected):
        return 'unknown_truth'
    if predicted is None:
        return 'unavailable'
    return 'agreement' if tuple(predicted) == tuple(expected) else 'disagreement'


def duplicate_groups(rows, key):
    groups = defaultdict(list)
    for row in rows:
        if row.get(key):
            groups[row[key]].append(row['id'])
    return [values for values in groups.values() if len(values) > 1]


def evaluate(directory, output):
    # Saved outputs are interpreted only after frozen references and input receipts verify.
    directory, output = private(directory), private(output)
    if output.exists():
        raise ValueError('Evaluation output already exists')
    frozen = read_sealed(directory / 'references.json')
    manifest = checked_manifest(directory)
    if frozen['manifest_sha256'] != digest(directory / 'manifest.json') or frozen['input_hashes'] != manifest['inputs']:
        raise ValueError('Frozen references and prepared inputs disagree')
    from analyze_temporal_ocr import complete_pair
    from benchmark_rapidocr import interpret
    sources = {stream['id']: read_run(private(directory / stream['log']))[1] for stream in manifest['streams']}
    truth = {row['id']: row for row in frozen['references']}
    results = []
    for entry in manifest['entries']:
        row = sources[entry['stream']][entry['index']-1]
        fields = truth[entry['id']]['fields']
        exp, pct, level = (fields[key]['value'] for key in FIELDS)
        pct = float(pct) if pct is not None else None
        neural = row.get('neural') or {}
        text = neural.get('text')
        parsed, pair = interpret(text), complete_pair(text)
        visual = row.get('visual_level')
        triple = [*pair, visual] if pair is not None and visual is not None else None
        expected = dict(exp=[exp], percentage=[pct], visual_level=[level], pair=[exp,pct], triple=[exp,pct,level])
        predictions = dict(exp=[parsed['exp']] if parsed['exp'] is not None else None,
                           percentage=[parsed['percentage']] if parsed['percentage'] is not None else None,
                           visual_level=[visual] if visual is not None else None, pair=pair, triple=triple)
        arithmetic = {}
        for mode in ('nearest_half_up', 'truncate'):
            hypothesis = (row.get('level_evidence') or {}).get('hypotheses', {}).get(mode) or {}
            levels = hypothesis.get('levels', [])
            status = ('unavailable_pair' if pair is None else 'unavailable' if hypothesis.get('status') in (None,'unavailable','invalid_input')
                      else 'incompatible' if not levels else 'ambiguous' if len(levels)>1 else 'unknown_truth' if level is None
                      else 'unique_agreement' if levels[0]==level else 'unique_disagreement')
            arithmetic[mode] = dict(outcome=status, saved_status=hypothesis.get('status'), levels=levels,
                                     reference_in_set=level in levels if level is not None else None)
        location = row.get('localization')
        count = location.get('count') if isinstance(location, dict) else None
        localization = 'not_run' if count is None else 'missing' if count==0 else 'ambiguous' if count>1 else 'unique_target_unverified'
        contradictions = [key for key in ('exp','percentage','visual_level') if predictions[key] is not None
                          and expected[key][0] is not None and predictions[key][0] != expected[key][0]]
        results.append(dict(id=entry['id'], stream=entry['stream'], index=entry['index'],
            capture='available' if row.get('frame_sha256') else 'failed' if row.get('status')=='capture_failed' else 'unknown',
            localization=localization, missing_crops=[key for key in ('exp','level') if entry[f'{key}_crop'] is None],
            raw_text=text, raw_scores=(neural.get('raw') or {}).get('scores'), saved_candidate=row.get('candidate'),
            saved_candidate_disagreement=row.get('candidate') != pair,
            predictions=predictions, expected=expected, truth_status={key:fields[key]['status'] for key in FIELDS},
            scores={key:comparison(value,expected[key]) for key,value in predictions.items()},
            arithmetic=arithmetic, known_component_contradictions=contradictions,
            wrong_complete_pair=pair is not None and any(key in contradictions for key in ('exp','percentage')),
            wrong_complete_triple=triple is not None and bool(contradictions),
            malformed_text=text is not None and pair is None, status=row.get('status'),
            frame_sha256=entry['frame_sha256'], exp_pixel_hash=entry['pixel_hashes'].get('exp'),
            attempted_at=row.get('attempted_at'), received_at=row.get('received_at'), current_at_capture=row.get('current'),
            identity_verified=False, main_hud_verified=False))
    streams = {}
    for stream in manifest['streams']:
        rows = sorted((row for row in results if row['stream']==stream['id']), key=lambda row:row['index'])
        streams[stream['id']] = dict(denominator=len(rows), capture=dict(Counter(row['capture'] for row in rows)),
            source_log=stream['log'],
            localization=dict(Counter(row['localization'] for row in rows)),
            metrics={key:dict(total=len(rows), **{outcome:sum(row['scores'][key]==outcome for row in rows)
                for outcome in ('agreement','disagreement','unavailable','unknown_truth')},
                output_available=sum(row['predictions'][key] is not None for row in rows),
                known_truth=sum(all(v is not None for v in row['expected'][key]) for row in rows)) for key in ('exp','percentage','visual_level','pair','triple')},
            arithmetic={mode:dict(Counter(row['arithmetic'][mode]['outcome'] for row in rows)) for mode in ('nearest_half_up','truncate')},
            wrong_complete_pairs=[row['id'] for row in rows if row['wrong_complete_pair']],
            wrong_complete_triples=[row['id'] for row in rows if row['wrong_complete_triple']],
            strict_pair_abstentions=sum(row['predictions']['pair'] is None for row in rows),
            strict_triple_abstentions=sum(row['predictions']['triple'] is None for row in rows),
            visual_level_abstentions=sum(row['predictions']['visual_level'] is None for row in rows),
            capture_local_freshness=dict(Counter('fresh' if row['current_at_capture'] is True else
                'not_fresh' if row['current_at_capture'] is False else 'unknown' for row in rows)),
            fresh_complete_pairs=sum(row['predictions']['pair'] is not None and row['current_at_capture'] is True for row in rows),
            saved_candidate_disagreements=[row['id'] for row in rows if row['saved_candidate_disagreement']],
            malformed_outputs=[row['id'] for row in rows if row['malformed_text']],
            duplicate_full_frames=duplicate_groups(rows,'frame_sha256'), duplicate_exp_pixels=duplicate_groups(rows,'exp_pixel_hash'),
            interval_seconds=stream['interval'], timestamps=[row['received_at'] or row['attempted_at'] for row in rows],
            caveats=['Cropped fields cannot authenticate main HUD, streamer or character identity.',
                     'Adjacent/repeated HUD frames are correlated, not independent correctness evidence.'])
    result = dict(trusted=False, practice_only=frozen['practice_only'], independently_validated=False,
                  provenance=frozen['provenance'], references_sha256=digest(directory/'references.json'),
                  manifest_sha256=frozen['manifest_sha256'], streams=streams, results=results)
    dump_new(output, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--run', nargs=2, action='append', required=True, metavar=('JSONL','CROPS'))
    prep.add_argument('--output', type=Path, required=True)
    prep.add_argument('--seed', type=int, default=17)
    prep.add_argument('--practice', action='store_true')
    freeze_cli = commands.add_parser('freeze')
    freeze_cli.add_argument('--prepared', type=Path, required=True)
    freeze_cli.add_argument('--answers', type=Path, required=True)
    freeze_cli.add_argument('--provenance', type=Path, required=True)
    evaluation = commands.add_parser('evaluate')
    evaluation.add_argument('--prepared', type=Path, required=True)
    evaluation.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            result = prepare(args.run, args.output, args.seed, args.practice)
            print(f'Prepared {len(result["entries"])} anonymous attempts; no labels or accuracy scores generated')
        elif args.command == 'freeze':
            result = freeze(args.prepared, args.answers, args.provenance)
            print(f'Frozen {len(result["references"])} submissions; no predictions evaluated')
        else:
            result = evaluate(args.prepared, args.output)
            print(json.dumps(dict(practice_only=result['practice_only'], streams=result['streams']), indent=2))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'Review workflow stopped: {error}\n')


if __name__ == '__main__':
    main()
