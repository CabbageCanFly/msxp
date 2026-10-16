"""Grammar may corroborate visible suffix strokes, never manufacture numbers."""

from dataclasses import replace
from pathlib import Path

from PIL import Image
import pytest

from test_exp_digits import exp
from test_glyphs import synthetic_profile, render


@pytest.fixture
def suffix_profile(synthetic_profile):
    templates = dict(synthetic_profile.templates)
    # An independently invented bold test font gives suffixes >16 stroke pixels.
    for char in '%[]':
        value = templates[char][0]
        coords = {(i % 6, i // 6) for i in range(54) if value >> i & 1}
        coords |= {(x+1, y) for x, y in coords if x < 5}
        templates[char] = (sum(1 << (y*6+x) for x, y in coords),)
    return replace(synthetic_profile, templates=templates, bracket_mode='green_excess', punctuation_threshold=11)


def damage(profile, image, symbol, count):
    text = '123[45.67%]'
    x = 3 + sum(profile.widths[c] for c in text[:text.index(symbol)])
    value = profile.templates[symbol][0]
    # Keep the outer box; remove internal stroke pixels only.
    positions = [i for i in range(54) if value >> i & 1 and 0 < i//6 < 8]
    for i in positions[:count]:
        image.putpixel((x+i%6, 2+i//6), (30, 30, 30))


def grammar(exp, image, profile):
    return exp.recognize(image, [exp.prepare(profile)], grammar_suffix=True, localized=True)


def test_mode_requires_independent_localization(exp, suffix_profile):
    with pytest.raises(ValueError, match='localized'):
        exp.recognize(render(suffix_profile, '123[45.67%]'), [exp.prepare(suffix_profile)], grammar_suffix=True)


def test_numerical_checks_survive_percent_inference(exp, suffix_profile):
    image = render(suffix_profile, '123[45.67%]')
    damage(suffix_profile, image, '%', 4)
    assert exp.recognize(image, [exp.prepare(suffix_profile)])['percentage'] is None
    result = grammar(exp, image, suffix_profile)
    assert (result['exp'], result['percentage'], result['status']) == (123, 45.67, 'candidate')
    assert any(a['percentage_detail'].get('inferred_percent') for a in result['attempts'])


def test_closing_inference_requires_strokes_and_verified_numbers(exp, suffix_profile):
    image = render(suffix_profile, '123[45.67%]')
    damage(suffix_profile, image, ']', 5)
    assert exp.recognize(image, [exp.prepare(suffix_profile)])['status'] != 'candidate'
    result = grammar(exp, image, suffix_profile)
    assert result['status'] == 'candidate' and result['percentage'] == 45.67
    assert any(a['percentage_detail'].get('inferred_closing') for a in result['attempts'])


@pytest.mark.parametrize('digit', list('0123456789'))
def test_extra_digit_cannot_be_inferred_as_percent(exp, suffix_profile, digit):
    # The extra digit is genuine visible evidence, not an ignorable suffix blob.
    image = render(suffix_profile, '123[45.67' + digit + ']')
    assert grammar(exp, image, suffix_profile)['status'] != 'candidate'


@pytest.mark.parametrize('digit', list('0123456789'))
@pytest.mark.parametrize('color', [(240, 240, 240), (140, 190, 60)])
def test_digit_cannot_be_hidden_as_inferred_closing_bracket(exp, suffix_profile, digit, color):
    image = render(suffix_profile, '123[45.67%]')
    x = 3 + 10*6
    image.paste((30, 30, 30), (x, 2, x+6, 11))
    for i in range(54):
        if suffix_profile.templates[digit][0] >> i & 1:
            image.putpixel((x+i%6, 2+i//6), color)
    assert grammar(exp, image, suffix_profile)['status'] != 'candidate'


@pytest.mark.parametrize('symbol', ['%', ']', '[', '.'])
def test_absent_punctuation_is_not_supplied(exp, suffix_profile, symbol):
    text = '123[45.67%]'
    image = render(suffix_profile, text)
    x = 3 + sum(suffix_profile.widths[c] for c in text[:text.index(symbol)])
    image.paste((30, 30, 30), (x, 2, x+6, 11))
    assert grammar(exp, image, suffix_profile)['status'] != 'candidate'


def test_two_arbitrary_blobs_are_not_a_suffix(exp, suffix_profile):
    text = '123[45.67%]'
    image = render(suffix_profile, text)
    start = 3 + sum(suffix_profile.widths[c] for c in text[:text.index('%')])
    image.paste((240, 240, 240), (start, 2, start+6, 11))
    image.paste((140, 190, 60), (start+6, 2, start+12, 11))
    assert grammar(exp, image, suffix_profile)['status'] != 'candidate'


def test_unknown_numerical_glyph_is_not_rescued(exp, suffix_profile):
    image = render(suffix_profile, '123[45.67%]')
    damage(suffix_profile, image, '%', 4)
    # Fill the final numerical character into an unknown shape.
    image.paste((240, 240, 240), (3+8*6, 2, 3+9*6, 11))
    assert grammar(exp, image, suffix_profile)['percentage'] is None


def test_bad_decimal_structure_is_not_rescued(exp, suffix_profile):
    for text in ('123[45.6%]', '123[45.678%]', '123[4567%]'):
        assert grammar(exp, render(suffix_profile, text), suffix_profile)['status'] != 'candidate'


@pytest.mark.samples
@pytest.mark.parametrize('milliseconds,percentage,status', [
    (142500, 0.00, 'candidate'), (1770000, 0.06, 'candidate'), (599000, None, 'unavailable')])
def test_private_percent_recoveries_do_not_rescue_bad_numbers(exp, milliseconds, percentage, status):
    root = Path(__file__).parents[1]
    bank = root/'private/exp-digits/bank.json'
    crop = root/f'private/levelup-evaluation/evaluation-crops/recording-crops/{milliseconds:04d}/exp-crop.png'
    if not bank.exists() or not crop.exists():
        pytest.skip('Private calibration and recording crops are intentionally excluded')
    with Image.open(crop) as image:
        result = exp.recognize(image, exp.load_bank(bank), grammar_suffix=True, localized=True)
    assert (result['percentage'], result['status']) == (percentage, status)
