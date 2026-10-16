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
