"""Parser/scoring tests need no neural dependencies, models, or private examples."""

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def bench(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'tools'))
    return importlib.import_module('benchmark_rapidocr')


@pytest.mark.parametrize('text', ['12,345[67.89%]', '12345[67.89%]', '12.345(67.89%)'])
def test_separator_changes_preserve_numeric_value_without_trust(bench, text):
    parsed = bench.interpret(text)
    assert parsed['pair'] == [12345, 67.89]
    assert parsed['bracketed_syntax'] is True
    assert parsed['trusted'] is False


@pytest.mark.parametrize('text', ['12345[67.89%', '12345 67.89%', '12345[67.89]'])
def test_missing_punctuation_is_explicitly_diagnostic(bench, text):
    parsed = bench.interpret(text)
    assert parsed['pair'] == [12345, 67.89]
    assert parsed['reason'] == 'insufficient_punctuation'
    assert parsed['bracketed_syntax'] is False
    assert parsed['trusted'] is False


@pytest.mark.parametrize('text', ['1234567.89%', '12345[67.89%1', '12345[6.789%]',
                                  '12345[6789%]', '12345[?][67.89%]',
                                  '12O45[67.89%]', '12345[100.00%]'])
def test_unknown_digits_suffixes_and_ambiguous_splits_never_make_pair(bench, text):
    assert bench.interpret(text)['pair'] is None


def test_correct_tokens_with_extra_suffix_digit_are_not_accepted(bench):
    result = bench.score_text('12345[67.89%1', dict(current_exp=12345, percentage=67.89))
    assert result['metrics']['pair'] == 'unavailable'
    assert result['metrics']['token_pair'] == 'label_match'
    assert result['parsed']['tokens']['suffix'] == '1'
    assert result['parsed']['trusted'] is False


def test_plausible_substituted_numeric_value_is_a_mismatch(bench):
    result = bench.score_text('12346[67.89%]', dict(current_exp=12345, percentage=67.89))
    assert result['metrics']['pair'] == 'label_mismatch'
    assert result['digit_edits']['exp']['substituted'] == 1


def test_raw_canonical_accuracy_is_distinct_from_numeric_accuracy(bench):
    result = bench.score_text('12345[67.89%]', dict(current_exp=12345, percentage=67.89))
    assert result['metrics']['pair'] == 'label_match'
    assert result['literal_canonical_match'] is False


def test_missing_decimal_is_not_reconstructed(bench):
    result = bench.score_text('12345[6789%]', dict(current_exp=12345, percentage=67.89))
    assert result['metrics']['pair'] == 'unavailable'
    assert result['percentage_format_valid'] is False
    assert not any(result['digit_edits']['percentage'].values())


def test_added_and_missing_digits_are_reported(bench):
    assert bench.digit_edits('10234', '1234')['added'] == 1
    assert bench.digit_edits('134', '1234')['missing'] == 1


def test_partial_numeric_fields_are_not_combined_across_extra_brackets(bench):
    parsed = bench.interpret('12345[?][67.89%]')
    assert parsed['exp'] == 12345 and parsed['percentage'] == 67.89
    assert parsed['pair'] is None


def test_unknown_labels_are_not_counted_as_model_errors(bench):
    result = bench.score_text('12345[67.89%]', dict(current_exp=None, percentage=None))
    assert all(v == 'unscored' for v in result['metrics'].values())


def test_missing_or_multiple_lines_cannot_be_reconstructed(bench):
    result = bench.score_text(None, dict(current_exp=12345, percentage=67.89))
    assert result['metrics']['pair'] == 'unavailable'


def test_cached_automatic_inputs_keep_missing_unavailable_without_filtering_by_labels(bench, tmp_path):
    items = [dict(id=f'stream2/{i}', seconds=i, level=8, current_exp=175, percentage=20.83)
             for i in range(4)]
    rows = [dict(**item, expected=item, candidates=[{}], location=location)
            for item, location in zip(items, ('main', 'missing', 'wrong_secondary', 'main'))]
    rows[1]['candidates'] = []
    rows[3]['candidates'] *= 2
    result = bench.automatic_crops(tmp_path/'manifest.json', dict(examples=items), dict(records=rows))
    assert result['stream2/0'] == tmp_path/'automatic-crops/0/exp.png'
    assert result['stream2/2'] == tmp_path/'automatic-crops/2/exp.png'
    assert all(result[f'stream2/{i}'] is None for i in (1, 3))
    rows[0]['expected'] = {**items[0], 'percentage': 20.84}
    with pytest.raises(ValueError, match='disagree'):
        bench.automatic_crops(tmp_path/'manifest.json', dict(examples=items), dict(records=rows))


def test_missing_crops_have_no_inference_time(bench):
    assert bench.timing([]) is None


@pytest.mark.parametrize('padding,expected', [(0,(2,2,6,5)), (2,(0,0,8,7)), (4,(0,0,10,8))])
def test_context_uses_original_floor_ceil_pixels_and_clamps_edges(bench, padding, expected):
    from exp_tracker.models import Region
    from PIL import Image
    region = Region(.21,.26,.51,.61)
    assert bench.context_box(region,(10,8),padding) == expected
    frame = Image.new('RGB',(10,8))
    for y in range(8):
        for x in range(10): frame.putpixel((x,y),(x,y,0))
    crop = frame.crop(bench.context_box(region,frame.size,padding))
    assert crop.getpixel((0,0)) == (expected[0],expected[1],0)
    assert crop.getpixel((crop.width-1,crop.height-1)) == (expected[2]-1,expected[3]-1,0)
    assert crop.size == (expected[2]-expected[0],expected[3]-expected[1])


@pytest.mark.parametrize('padding,size', [(-2,(10,8)),(3,(10,8)),(8,(10,8)),(True,(10,8)),(2,(0,8))])
def test_context_rejects_unplanned_padding_and_empty_frames(bench, padding, size):
    from exp_tracker.models import Region
    with pytest.raises(ValueError):
        bench.context_box(Region(0,0,1,1),size,padding)


@pytest.mark.parametrize('padding,expected', [(2,(3,3,17,17)),(4,(1,1,19,19))])
def test_context_expands_an_interior_region_exactly(bench, padding, expected):
    from exp_tracker.models import Region
    assert bench.context_box(Region(.25,.25,.75,.75),(20,20),padding) == expected


def test_padding_cannot_invent_automatic_regions_for_manual_inputs(bench):
    with pytest.raises(SystemExit) as error:
        bench.main(['missing.json','--plan','missing.json','--padding','2','--output','unused.json'])
    assert error.value.code == 2


@pytest.mark.parametrize('raw', ['XP 123[45.67%]', 'HP 5 123[45.67%]', '123[45.67%]9',
                                 '123[45.67%1', '12?3[45.67%]', '123[?][45.67%]'])
def test_extra_context_and_unknown_glyphs_cannot_be_trimmed_to_make_pair(bench, raw):
    assert bench.interpret(raw)['pair'] is None


def test_clipped_but_plausible_number_is_diagnostic_mismatch(bench):
    result = bench.score_text('23[45.67%]',dict(current_exp=123,percentage=45.67))
    assert result['metrics']['pair'] == 'label_mismatch'
    assert result['parsed']['trusted'] is False
