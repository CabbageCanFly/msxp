"""Private-data-free EXP experiment checks using the existing invented test font."""

from dataclasses import replace
import importlib
import json
from pathlib import Path

from PIL import Image
import pytest

from test_glyphs import synthetic_profile, render


@pytest.fixture
def exp(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'tools'))
    return importlib.import_module('exp_digits')


@pytest.fixture
def profile(synthetic_profile):
    return replace(synthetic_profile, bracket_mode='green_excess', punctuation_threshold=11)


@pytest.mark.parametrize('text,number,percent', [
    ('1[0.12%]', 1, .12), ('12,345[67.89%]', 12345, 67.89),
    ('987654[32.10%]', 987654, 32.10), ('9,876,543[98.76%]', 9876543, 98.76),
    ('0[0.00%]', 0, 0), ('123456789012[99.99%]', 123456789012, 99.99)])
def test_native_variable_fields(exp, profile, text, number, percent):
    result = exp.recognize(render(profile, text), [exp.prepare(profile)])
    assert (result['status'], result['exp'], result['percentage']) == ('candidate', number, percent)


@pytest.mark.parametrize('symbol', ['[', ']', '.', '%'])
def test_missing_punctuation_cannot_produce_complete_candidate(exp, profile, symbol):
    text = '12,345[67.89%]'
    image = render(profile, text)
    x = 3 + sum(profile.widths[c] for c in text[:text.index(symbol)])
    image.paste((30, 30, 30), (x, 2, x + profile.widths[symbol], 11))
    result = exp.recognize(image, [exp.prepare(profile)])
    assert result['status'] != 'candidate'
    if symbol in '[]':
        assert result['exp'] is None and result['percentage'] is None


@pytest.mark.parametrize('symbol', ['[', ']'])
def test_digit_shaped_bracket_never_becomes_extra_numeric_digit(exp, profile, symbol):
    text = '12,345[67.89%]'
    image = render(profile, text)
    x = 3 + sum(profile.widths[c] for c in text[:text.index(symbol)])
    image.paste((30, 30, 30), (x, 2, x+6, 11))
    for i in range(54):
        if profile.templates['8'][0] >> i & 1:
            image.putpixel((x+i%6, 2+i//6), (140, 190, 60))
    result = exp.recognize(image, [exp.prepare(profile)])
    assert result['status'] != 'candidate' and result['exp'] is None


def test_empty_bracket_mask_is_never_evidence_even_with_a_sparse_template(exp, profile):
    sparse = replace(profile, templates={**profile.templates, '[': (1,), ']': (1,)})
    assert exp.brackets(Image.new('RGB', (80, 9)), sparse) == {'[': [], ']': []}


def test_unknown_and_ambiguous_digit_are_not_dropped(exp, profile):
    image = render(profile, '12346[67.89%]')
    image.putpixel((3+4*6+4, 2+2), (240, 240, 240))  # Halfway between 6 and 8.
    assert exp.recognize(image, [exp.prepare(profile)])['status'] != 'candidate'
    image.paste((240, 240, 240), (3, 2, 9, 11))
    assert exp.recognize(image, [exp.prepare(profile)])['exp'] is None


def test_missing_internal_digit_keeps_its_gap(exp, profile):
    image = render(profile, '12345[67.89%]')
    image.paste((30, 30, 30), (15, 2, 21, 11))
    result = exp.recognize(image, [exp.prepare(profile)])
    assert result['exp'] is None and result['status'] != 'candidate'


def test_valley_split_preserves_bridge_pixels(exp, profile):
    image = render(profile, '70[32.12%]')
    image.putpixel((8, 4), (240, 240, 240))
    bank = [exp.prepare(profile)]
    assert exp.recognize(image, bank, segmentation='columns')['exp'] is None
    result = exp.recognize(image, bank, segmentation='valleys')
    assert (result['exp'], result['percentage'], result['status']) == (70, 32.12, 'candidate')


def test_one_character_may_move_without_moving_the_line(exp, profile):
    image = render(profile, '987[32.10%]')
    first = image.crop((3, 2, 9, 11))
    image.paste((30, 30, 30), (3, 2, 9, 11))
    image.paste(first, (3, 3))
    result = exp.recognize(image, [exp.prepare(profile)])
    assert (result['exp'], result['percentage'], result['status']) == (987, 32.10, 'candidate')


def test_extra_suffix_and_other_baseline_are_not_discarded(exp, profile):
    image = render(profile, '123[45.67%]')
    image.putpixel((image.width-1, 4), (240, 240, 240))
    assert exp.recognize(image, [exp.prepare(profile)])['status'] != 'candidate'
    line = render(profile, '123[45.67%]')
    image = Image.new('RGB', (line.width, line.height*2))
    image.paste(line, (0, 0))
    image.paste(line, (0, line.height))
    assert exp.recognize(image, [exp.prepare(profile)])['status'] != 'candidate'


def test_separate_progress_bar_does_not_change_text_height(exp, profile):
    image = render(profile, '123[45.67%]')
    image.paste((220, 220, 220), (0, image.height-1, image.width, image.height))
    result = exp.recognize(image, [exp.prepare(profile)])
    assert (result['exp'], result['percentage'], result['status']) == (123, 45.67, 'candidate')


@pytest.mark.parametrize('text', ['01[0.12%]', '1,23[45.67%]', '1[01.23%]', '1[100.00%]'])
def test_invalid_grammar_is_rejected(exp, profile, text):
    assert exp.recognize(render(profile, text), [exp.prepare(profile)])['status'] != 'candidate'


def test_blank_oversize_and_unknown_scale(exp, profile):
    bank = [exp.prepare(profile)]
    for image in [Image.new('RGB', (80, 20)), Image.new('RGB', (513, 20)),
                  render(profile, '1[0.12%]').resize((100, 28), Image.Resampling.NEAREST)]:
        assert exp.recognize(image, bank)['status'] != 'candidate'


def test_profile_type_and_calibration_split_are_explicit(exp, synthetic_profile, profile, tmp_path):
    with pytest.raises(ValueError, match='green-excess'):
        exp.prepare(synthetic_profile)
    profile_path = tmp_path/'profile.json'
    profile_path.write_text(json.dumps(dict(version=2, bracket_mode='green_excess', height=9,
        widths=profile.widths, templates=profile.templates, digit_threshold=175, punctuation_threshold=11)))
    path = tmp_path/'bank.json'
    path.write_text(json.dumps(dict(version=1, families=[dict(profile='profile.json',
        characters=[dict(split='heldout', char='1')])])))
    with pytest.raises(ValueError, match='development'):
        exp.load_bank(path)


def test_manual_public_calibration_and_cli(exp, profile, tmp_path, capsys):
    profile_path = tmp_path/'brackets.json'
    profile_path.write_text(json.dumps(dict(version=2, bracket_mode='green_excess', height=9,
        widths=profile.widths, templates=profile.templates, digit_threshold=175, punctuation_threshold=11)))
    characters = []
    for index, char in enumerate(exp.WHITE):
        name = f'{index}.png'
        render(profile, char).save(tmp_path/name)
        characters.append(dict(image=name, char=char, box=[3, 2, 9, 11], split='development'))
    path = tmp_path/'bank.json'
    path.write_text(json.dumps(dict(version=1, families=[dict(profile=profile_path.name, characters=characters)])))
    image = tmp_path/'line.png'
    render(profile, '123[45.67%]').save(image)
    exp.main([str(image), '--bank', str(path)])
    result = json.loads(capsys.readouterr().out)
    assert (result['exp'], result['percentage'], result['status']) == (123, 45.67, 'candidate')
    characters.pop()
    path.write_text(json.dumps(dict(version=1, families=[dict(profile=profile_path.name, characters=characters)])))
    with pytest.raises(ValueError, match='cover all'):
        exp.load_bank(path)


def test_scoring_keeps_partial_fields_and_level_errors_separate(exp):
    score = importlib.import_module('evaluate_exp_digits').score
    expected = dict(level=8, current_exp=123, percentage=45.67)
    partial = dict(exp=123, percentage=45.67, status='unavailable')
    metrics = score(partial, expected, dict(tesseract=3))
    assert metrics['exp'] == metrics['percentage'] == 'correct'
    assert metrics['complete_exp'] == metrics['complete_tesseract'] == 'unavailable'
    metrics = score({**partial, 'status': 'candidate'}, expected, dict(tesseract=3, pixel=8))
    assert metrics['complete_exp'] == metrics['complete_pixel'] == 'correct'
    assert metrics['complete_tesseract'] == 'incorrect'


@pytest.mark.samples
@pytest.mark.parametrize('relative,number,percentage,status', [
    ('private/levelup-evaluation/evaluation-crops/recording-crops/19750/exp-crop.png', 4, 11.76, 'candidate'),
    ('private/levelup-evaluation/evaluation-crops/recording-crops/599000/exp-crop.png', 0, None, 'unavailable'),
    ('artifacts/green-test-20261015-215403/0016/exp-crop.png', 879440, 72.68, 'candidate')])
def test_private_success_and_rejection_regressions(exp, relative, number, percentage, status):
    root = Path(__file__).parents[1]
    bank = root/'private/exp-digits/bank.json'
    image = root/relative
    if not bank.exists() or not image.exists():
        pytest.skip('Private development calibration and evaluation crops are intentionally excluded')
    with Image.open(image) as crop:
        result = exp.recognize(crop, exp.load_bank(bank))
    assert (result['exp'], result['percentage'], result['status']) == (number, percentage, status)
