"""Synthetic labels and rejection tests; no game imagery or downloaded models."""

import importlib
import json
from pathlib import Path

from PIL import Image
import pytest

from test_exp_digits import exp, profile
from test_glyphs import synthetic_profile, render


@pytest.fixture
def gray(exp):
    return importlib.import_module('grayscale_digits')


def examples(profile):
    rows = []
    for char in '0123456789':
        raw = render(profile, char).crop((3, 2, 9, 11)).convert('L')
        box = raw.point(lambda p:255 if p>175 else 0).getbbox()
        raw = raw.crop((box[0], 0, box[2], 9))
        for source, peak in enumerate((225, 240, 250)):
            image = raw.point(lambda p:peak if p>175 else 30)
            rows.append(dict(char=char, source=f'frame-{source}', size=list(image.size), gray=image.tobytes().hex()))
    return rows


@pytest.fixture
def family(profile):
    return dict(height=9, advance=6, threshold=175, examples=examples(profile), max_error=.25, min_margin=.06)


@pytest.mark.parametrize('digit', list('0123456789'))
def test_native_examples_are_classified_with_source_corroboration(gray, family, digit):
    row = next(r for r in family['examples'] if r['char']==digit)
    result, detail = gray.Classifier(family).predict(tuple(row['size']), bytes.fromhex(row['gray']))
    assert result==digit and detail['support_error'] is not None


def test_augmentations_do_not_supply_a_second_source(gray, family):
    for row in family['examples']:
        if row['char']=='8':row['source']='only-one-real-frame'
    row = next(r for r in family['examples'] if r['char']=='8')
    value, detail = gray.Classifier(family).predict(tuple(row['size']), bytes.fromhex(row['gray']))
    assert value is None and detail['support_error'] is None


def test_unknowns_punctuation_merged_glyphs_and_wrong_height_are_rejected(gray, family):
    classifier = gray.Classifier(family)
    for image in [Image.new('L', (6, 9)), Image.new('L', (6, 9), 255),
                  Image.new('L', (8, 9), 240), Image.new('L', (6, 8), 240)]:
        assert classifier.predict(image.size, image.tobytes())[0] is None
    dot = Image.new('L', (2, 9));dot.putpixel((0, 7), 240)
    assert classifier.predict(dot.size, dot.tobytes())[0] is None


def test_confusable_six_eight_midpoint_abstains(gray, family):
    rows = {r['char']:r for r in family['examples'] if r['source']=='frame-0'}
    six, eight = rows['6'], rows['8']
    assert six['size']==eight['size']
    a,b = bytes.fromhex(six['gray']),bytes.fromhex(eight['gray'])
    uncertain = bytes(x if x==y else 167 for x,y in zip(a,b))
    assert gray.Classifier(family).predict(tuple(six['size']), uncertain)[0] is None


def test_training_is_manual_deterministic_and_bound_to_bank(gray, profile, tmp_path):
    bracket = tmp_path/'profile.json'
    bracket.write_text(json.dumps(dict(version=2, bracket_mode='green_excess', height=9,
        widths=profile.widths, templates=profile.templates, digit_threshold=175, punctuation_threshold=11)))
    rows = []
    for i,row in enumerate(examples(profile)):
        path = tmp_path/f'{i}.png'
        im = Image.frombytes('L', tuple(row['size']), bytes.fromhex(row['gray']));im.save(path)
        rows.append(dict(id=row['source'], image=path.name, char=row['char'],
                         box=[0, 0, *im.size], split='development'))
    rows.append({**rows[0], 'id':'another-annotation-of-the-same-image'})
    bank = tmp_path/'bank.json';bank.write_text(json.dumps(dict(families=[dict(profile=bracket.name, characters=rows)])))
    model = tmp_path/'model.json'
    result = gray.train(bank, model);first=model.read_bytes();gray.train(bank, model)
    assert model.read_bytes()==first and result['calibration'][0]['leave_source_out_wrong']==0
    assert result['calibration'][0]['source_counts']['0']==3
    assert len(gray.load(model, bank))==1
    bank.write_text(bank.read_text()+' ')
    with pytest.raises(ValueError, match='does not match'):
        gray.load(model, bank)
    rows[0]['split']='heldout';bank.write_text(json.dumps(dict(families=[dict(profile=bracket.name, characters=rows)])))
    with pytest.raises(ValueError, match='development'):
        gray.train(bank, model)
    assert model.read_bytes()==first


def test_missing_competing_class_is_invalid(gray, family):
    family['examples']=[r for r in family['examples'] if r['char']!='8']
    with pytest.raises(ValueError, match='every competing'):
        gray.Classifier(family)


def test_classifier_conflict_is_a_veto_without_changing_default_pixel_reader(exp, profile):
    bank = exp.prepare(profile)
    image = render(profile, '123[45.67%]')
    white = image.crop((3, 2, 21, 11)).convert('L').point(lambda p:255 if p>175 else 0)
    before = exp.field(white, bank[1], 'exp', 'valleys')
    value, _ = exp.field(white, bank[1], 'exp', 'valleys', gray=white,
                         alternative=lambda binary, raw:('9', {'reason':'test-disagreement'}))
    assert before[0]==123 and value is None
    assert exp.field(white, bank[1], 'exp', 'valleys')==before


def test_hybrid_preserves_complete_pixel_candidate_without_classifier_calls(gray, exp, profile):
    class NeverCalled:
        def predict(self, *args):
            raise AssertionError('complete first-pass result must be retained')
    result = gray.recognize(render(profile, '123[45.67%]'), [exp.prepare(profile)], [NeverCalled()])
    assert result['status']=='candidate' and not result['classifier_used']


@pytest.mark.samples
@pytest.mark.parametrize('milliseconds,number,percent,status', [
    (384250,57,15.32,'candidate'), (780000,280,33.33,'candidate'), (599000,0,None,'unavailable')])
def test_private_hybrid_recoveries_and_unreadable_rejection(gray, exp, milliseconds, number, percent, status):
    root=Path(__file__).parents[1]
    bank=root/'private/exp-digits/bank.json';model=root/'private/numeric-classifier/model.json'
    crop=root/f'private/levelup-evaluation/evaluation-crops/recording-crops/{milliseconds:04d}/exp-crop.png'
    if not all(p.exists() for p in (bank,model,crop)):
        pytest.skip('Private manual calibration, model and crops are intentionally excluded')
    with Image.open(crop) as image:
        result=gray.recognize(image,exp.load_bank(bank),gray.load(model,bank))
    assert (result['exp'],result['percentage'],result['status'])==(number,percent,status)
