"""Small grayscale example classifier; private manual labels, no third-party models.

Features are native padded 4-bit ink intensities. Classes use nearest examples,
but acceptance needs two distinct labeled source frames and a calibrated margin.
Synthetic variants never count as independent source evidence.
"""

import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageFilter

from exp_tracker.glyphs import GlyphProfile
import exp_digits


def feature(image, threshold, size):
    low, high = threshold - 65, threshold + 65
    ink = image.convert('L').point(lambda p: max(0, min(15, round((p-low)*15/(high-low)))))
    canvas = Image.new('L', size)
    canvas.paste(ink, (2, 2))
    return canvas


def variants(image, threshold, size):
    # Bounded rendering variations of verified samples, not new labels.
    forms = [image, image.filter(ImageFilter.GaussianBlur(.35)),
             ImageEnhance.Contrast(image).enhance(.9), ImageEnhance.Contrast(image).enhance(1.1)]
    result = {}
    for form in forms:
        native = feature(form, threshold, size)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                shifted = Image.new('L', size)
                shifted.paste(native, (dx, dy))
                result[shifted.tobytes()] = shifted
    return [(im, sum(im.tobytes())) for im in result.values()]


class Classifier:
    def __init__(self, family):
        self.height = family['height']
        self.advance = family['advance']
        self.threshold = family['threshold']
        self.size = (self.advance + 5, self.height + 4)
        self.max_error = family.get('max_error', .25)
        self.min_margin = family.get('min_margin', .06)
        if not (3<=self.height<=32 and 1<=self.advance<=32 and 0<=self.threshold<=255
                and 0<=self.max_error<=.25 and .06<=self.min_margin<=1
                and 1<=len(family['examples'])<=512):
            raise ValueError('invalid classifier bounds')
        self.examples = []
        for row in family['examples']:
            if (row['char'] not in '0123456789' or len(row['char'])!=1 or not row['source']
                    or row['size'][1]!=self.height or not 1<=row['size'][0]<=self.advance+1):
                raise ValueError('invalid labeled character geometry')
            image = Image.frombytes('L', tuple(row['size']), bytes.fromhex(row['gray']))
            self.examples.append((row['char'], row['source'], variants(image, self.threshold, self.size)))
        if {row[0] for row in self.examples} != set('0123456789'):
            raise ValueError('classifier must retain every competing digit class')

    def rank(self, image, exclude_source=None):
        query = feature(image, self.threshold, self.size)
        mass = sum(query.tobytes())
        sources = {c: {} for c in '0123456789'}
        for char, source, examples in self.examples:
            if source == exclude_source:
                continue
            error = min(sum(i*n for i, n in enumerate(ImageChops.difference(query, ref).histogram()[:16]))
                        / max(1, mass+other_mass) for ref, other_mass in examples)
            sources[char][source] = min(error, sources[char].get(source, 1.0))
        ranked = sorted((min(values.values(), default=1.0), char) for char, values in sources.items())
        best, char = ranked[0]
        corroboration = sorted(sources[char].values())
        return dict(char=char, error=best, margin=ranked[1][0]-best,
                    support_error=corroboration[1] if len(corroboration)>=2 else None)

    @lru_cache(maxsize=512)
    def predict(self, size, raw):
        image = Image.frombytes('L', size, raw)
        binary = image.point(lambda p: 255 if p>self.threshold else 0)
        box = binary.getbbox()
        if (size[1] != self.height or size[0]>self.advance+1 or box is None
                or box[3]-box[1]<.55*self.height or sum(bool(p) for p in binary.tobytes())<4):
            return None, dict(reason='unknown_geometry_or_insufficient_ink')
        detail = self.rank(image)
        accepted = (detail['support_error'] is not None and detail['support_error']<=self.max_error
                    and detail['margin']>=self.min_margin)
        return detail['char'] if accepted else None, dict(reason='gray_match' if accepted else 'gray_abstention', **detail)


def train(bank_path, output):
    data = json.loads(bank_path.read_text(encoding='utf-8'))
    families, reports = [], []
    source_hashes = {}
    for family in data['families']:
        profile = GlyphProfile.load(exp_digits.bank_source(bank_path, family['profile']))
        examples = []
        negatives = []
        for row in family['characters']:
            if row['split'] != 'development':
                raise ValueError('Only manually verified development labels may train')
            source_path = exp_digits.bank_source(bank_path, row['image']).resolve()
            if source_path not in source_hashes:
                source_hashes[source_path] = hashlib.sha256(source_path.read_bytes()).hexdigest()
            with Image.open(source_path) as original:
                left, top, right, bottom = row['box']
                if not (0<=left<right<=original.width and 0<=top<bottom<=original.height
                        and bottom-top==profile.height):
                    raise ValueError('invalid manually verified character box')
                image = original.crop(tuple(row['box'])).convert('L')
            if row['char'] not in '0123456789':
                negatives.append(image)
                continue
            examples.append(dict(char=row['char'], source=source_hashes[source_path],
                                 size=list(image.size), gray=image.tobytes().hex()))
        if {r['char'] for r in examples} != set('0123456789'):
            raise ValueError('Every digit must have a verified development example')
        payload = dict(height=profile.height, advance=profile.widths['0'], threshold=profile.digit_threshold,
                       examples=examples)
        model = Classifier(payload)
        holdouts = []
        for row in examples:
            im = Image.frombytes('L', tuple(row['size']), bytes.fromhex(row['gray']))
            holdouts.append(dict(expected=row['char'], source=row['source'], **model.rank(im, row['source'])))
        positives = sorted(r['support_error'] for r in holdouts if r['char']==r['expected'] and r['support_error'] is not None)
        limit = min(.25, positives[min(len(positives)-1, int(.9*len(positives)))]) if positives else 0
        risks = [r['margin'] for r in holdouts if r['char']!=r['expected'] and
                 r['support_error'] is not None and r['support_error']<=limit]
        negative_results = []
        for image in negatives:
            if image.width>model.advance+1:
                continue
            detail = model.rank(image)
            negative_results.append(detail)
            if detail['support_error'] is not None and detail['support_error']<=limit:
                risks.append(detail['margin'])
        margin = max(.06, max(risks, default=0)+.02)
        payload.update(max_error=limit, min_margin=margin)
        Classifier(payload)  # Validate before replacing any existing model file.
        families.append(payload)
        accepted = [r for r in holdouts if r['support_error'] is not None and r['support_error']<=limit and r['margin']>=margin]
        reports.append(dict(source_counts={c:len({r['source'] for r in examples if r['char']==c}) for c in '0123456789'},
            leave_source_out_correct=sum(r['char']==r['expected'] for r in accepted),
            leave_source_out_wrong=sum(r['char']!=r['expected'] for r in accepted),
            leave_source_out_unavailable=len(holdouts)-len(accepted),max_error=limit,min_margin=margin,
            holdouts=holdouts,negative_results=negative_results))
    result = dict(version=1, source_grouping='image-sha256', bank_sha256=hashlib.sha256(bank_path.read_bytes()).hexdigest(),
                  families=families, calibration=reports)
    output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result


def load(path, bank_path):
    if path.stat().st_size>1024*1024:
        raise ValueError('classifier exceeds 1 MiB')
    data = json.loads(path.read_text(encoding='utf-8'))
    if (data['version']!=1 or data.get('source_grouping')!='image-sha256' or not 1<=len(data['families'])<=4
            or data['bank_sha256']!=hashlib.sha256(bank_path.read_bytes()).hexdigest()):
        raise ValueError('classifier calibration does not match the explicit bank')
    return [Classifier(family) for family in data['families']]


def recognize(image, bank, models):
    baseline = exp_digits.recognize(image, bank, grammar_suffix=True, localized=True)
    if baseline['status'] in ('candidate', 'ambiguous'):
        return {**baseline, 'classifier_used': False}
    if len(models)!=len(bank):
        raise ValueError('classifier family count mismatch')
    def alternative(index, binary, gray):
        return models[index].predict(gray.size, gray.tobytes())
    result = exp_digits.recognize(image, bank, grammar_suffix=True, localized=True, alternative=alternative)
    if any(baseline[k] is not None and result[k] is not None and baseline[k]!=result[k] for k in ('exp','percentage')):
        return {**baseline, 'classifier_used': True, 'classifier_rejection': 'conflict_with_pixel_field'}
    return {**result, 'classifier_used': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bank', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args(argv)
    result = train(args.bank, args.output)
    print(json.dumps([{k:v for k,v in r.items() if k not in ('holdouts','negative_results')}
                      for r in result['calibration']], indent=2))


if __name__=='__main__':
    main()
