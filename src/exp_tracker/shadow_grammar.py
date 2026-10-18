"""Bounded full-EXP text hypotheses for display/review only. Never observations."""

import re

from .parsing import parse_exp
from .shadow_types import parse_percentage_only

MAX_TEXT = 160
MAX_EDITS = 3
MAX_PROPOSALS = 2
GROUPED = r'[0-9]{1,3}(?:[,.][0-9]{3})+'


def _full_reading(text):
    pair = parse_exp(text)
    # Same full-pair eligibility as the unchanged experimental strict parser.
    if pair is None or pair[0] > 2**63 - 1 or not 0 <= pair[1] < 100 or (pair[0] == 0 and pair[1] != 0):
        return None
    return dict(kind='full_exp_pair', exp=str(pair[0]), percentage=f'{pair[1]:.2f}')


def propose_full_exp(text, *, source_complete=None):
    """No decimal/numeric inference, image classification, neighbors or level inputs."""
    result = dict(policy='bounded_full_exp_v1', raw=text if isinstance(text, str) and len(text) <= MAX_TEXT else None,
                  classification='rejected', strict=None, proposals=[], trusted=False,
                  numerical_identity_verified=False, source_complete=source_complete)
    if not isinstance(text, str) or not text or len(text) > MAX_TEXT:
        return {**result, 'classification': 'unavailable', 'reason': 'missing_or_unbounded_text'}
    strict = _full_reading(text)
    only = parse_percentage_only(text)
    if strict or only:
        return {**result, 'classification': 'raw_strict', 'strict': strict or only,
                'reason': 'original_strict_result_unchanged'}
    if source_complete is False:
        return {**result, 'classification': 'incomplete_or_clipped_field', 'reason': 'source_review_veto'}
    if any(c in text for c in '|Il'):
        return {**result, 'reason': 'unsupported_lookalike_not_substituted'}
    if not text.endswith(('%]', '%1')):
        return {**result, 'reason': 'explicit_percent_and_bounded_suffix_required'}
    # At most 160 native character positions, two retained hypotheses, three edits.
    # A substituted opener requires grouping; ungrouped concatenated numbers abstain.
    for index, char in enumerate(text):
        if char not in '[1':
            continue
        exp, percentage = text[:index], text[index+1:-2]
        if not re.fullmatch(r'[0-9]{1,2}\.[0-9]{2}', percentage):
            continue
        if not re.fullmatch(GROUPED if char == '1' else rf'(?:{GROUPED}|[0-9]+)', exp):
            continue
        edits = [dict(index=i, old='.', new=',', category='exp_grouping') for i, c in enumerate(exp) if c == '.']
        if char == '1':
            edits.append(dict(index=index, old='1', new='[', category='opening_bracket'))
        if text[-1] == '1':
            edits.append(dict(index=len(text)-1, old='1', new=']', category='closing_bracket'))
        if not edits or len(edits) > MAX_EDITS:
            continue
        interpretation = list(text)
        for edit in edits:
            interpretation[edit['index']] = edit['new']
        interpretation = ''.join(interpretation)
        reading = _full_reading(interpretation)
        if reading is None:
            continue
        result['proposals'].append(dict(interpretation=interpretation, reading=reading, edits=edits,
            trusted=False, numerical_identity_verified=False, image_verification='required'))
        if len(result['proposals']) == MAX_PROPOSALS:
            break  # Two possibilities already require abstention, never a winner.
    count = len(result['proposals'])
    result['classification'] = 'unique_proposal' if count == 1 else 'ambiguous' if count else 'rejected'
    result['reason'] = 'hypothesis_only_not_an_observation' if count == 1 else (
        'multiple_interpretations_abstain' if count else 'no_bounded_full_pair_interpretation')
    return result


def interpret_exp(text, *, source_complete=None):
    """Versioned diagnostic interpretations; v1 and both strict parsers stay frozen.

    Both boundary symbols must exist. Only punctuation is interpreted, never a
    missing digit. Decimal-comma recovery deliberately makes no full-EXP claim.
    """
    base = dict(classification='rejected', proposals=[], trusted=False,
                numerical_identity_verified=False, reason='no_bounded_interpretation')
    result = dict(policy='bounded_exp_v4', raw=text if isinstance(text, str) and len(text) <= MAX_TEXT else None,
                  strict_full=None, strict_percentage_only=None, full_exp={**base}, percentage={**base},
                  symbol_hypotheses=[], source_complete=source_complete, trusted=False)
    if not isinstance(text, str) or not text or len(text) > MAX_TEXT:
        for field in ('full_exp', 'percentage'):
            result[field] = {**base, 'classification': 'unavailable', 'reason': 'missing_or_unbounded_text'}
        return result
    strict, only = _full_reading(text), parse_percentage_only(text)
    if strict or only:
        result.update(strict_full=strict, strict_percentage_only=only)
        for field in ('full_exp', 'percentage'):
            result[field] = {**base, 'classification': 'raw_strict', 'reason': 'original_strict_result_unchanged'}
        return result
    # A single EXP-label tail before an otherwise complete bracketed percentage.
    # This never establishes the completeness of an absolute EXP field.
    if text.startswith('P[') and parse_percentage_only(text[1:]) is not None:
        result['percentage']={**base, 'classification':'unique_proposal',
            'reason':'exp_label_tail_hypothesis_only', 'proposals':[dict(
                interpretation=text[1:],reading=parse_percentage_only(text[1:]),
                edits=[dict(index=0,old='P',new='',category='exp_label_tail')],
                field_span=[1,len(text)],image_verification='required',
                source_completeness_verified=False,trusted=False,numerical_identity_verified=False)]}
        return result
    if not text.endswith(('%]', '%1', '%|')):
        # Missing '%' is not ordinary recovery evidence. Keep a bounded review
        # hypothesis separate; no consumer may use it as a percentage endpoint.
        if source_complete is not False and re.search(r'[0-9]{1,2}\.[0-9]{2}X1$',text):
            repaired=interpret_exp(text[:-2]+'%1',source_complete=source_complete)['full_exp']
            if repaired['classification']=='unique_proposal':
                proposal=repaired['proposals'][0]
                edits=[dict(index=len(text)-2,old='X',new='%',category='percent_symbol_hypothesis')]+proposal['edits']
                if len(edits)<=4:
                    result['symbol_hypotheses']=[dict(proposal,edits=edits,
                        classification='unsupported_symbol_hypothesis',usable_as_observation=False,
                        reason='literal_percent_missing_requires_source_pixel_review')]
        for field in ('full_exp', 'percentage'):
            result[field] = {**base, 'reason': 'explicit_percent_and_two_present_boundaries_required'}
        return result
    full, percentages = [], []
    decimal_repaired = False
    for index, char in enumerate(text):
        if char not in '[1|':
            continue
        prefix, token = text[:index], text[index+1:-2]
        if not re.fullmatch(r'(?:[0-9]{1,2}|100)[.,][0-9]{2}', token):
            continue
        # A numeral-like opener needs a grouped prefix. An explicit bracket can
        # anchor a percentage even when the numeric EXP prefix is unusable.
        if char == '1' and not re.fullmatch(GROUPED, prefix):
            continue
        if prefix and not re.fullmatch(r'[0-9.,]+', prefix):
            continue
        edits = []
        if char != '[':
            edits.append(dict(index=index, old=char, new='[', category='opening_bracket'))
        if ',' in token:
            position = index + 1 + token.index(',')
            edits.append(dict(index=position, old=',', new='.', category='percentage_decimal'))
            decimal_repaired = True
        if text[-1] != ']':
            edits.append(dict(index=len(text)-1, old=text[-1], new=']', category='closing_bracket'))
        normalized = token.replace(',', '.')
        only = parse_percentage_only(f'[{normalized}%]')
        if only is None:
            continue
        common = dict(edits=edits, trusted=False, numerical_identity_verified=False,
                      image_verification='required', field_span=[index, len(text)],
                      source_completeness_verified=False)
        percentages.append(dict(**common, interpretation=f'[{normalized}%]', reading=only))
        grouped = re.fullmatch(rf'(?:{GROUPED}|[0-9]+)', prefix)
        if source_complete is not False and grouped and ',' not in token:
            full_edits = [dict(index=i, old='.', new=',', category='exp_grouping')
                          for i, c in enumerate(prefix) if c == '.'] + edits
            if len(full_edits) <= 4:
                interpretation = list(text)
                for edit in full_edits:
                    interpretation[edit['index']] = edit['new']
                interpretation = ''.join(interpretation)
                reading = _full_reading(interpretation)
                if reading:
                    full.append(dict(**{**common, 'edits': full_edits}, interpretation=interpretation, reading=reading))
        if len(full) >= MAX_PROPOSALS or len(percentages) >= MAX_PROPOSALS:
            break
    for field, proposals in (('full_exp', full), ('percentage', percentages)):
        count = len(proposals)
        result[field] = {**base, 'proposals': proposals,
            'classification': 'unique_proposal' if count == 1 else 'ambiguous' if count else 'rejected',
            'reason': 'hypothesis_only_not_an_observation' if count == 1 else
                      'multiple_interpretations_abstain' if count else 'no_bounded_interpretation'}
    if not full and source_complete is False:
        result['full_exp'].update(classification='incomplete_or_clipped_field', reason='source_review_veto')
    elif not full and decimal_repaired:
        result['full_exp']['reason'] = 'percentage_decimal_repair_does_not_establish_exp_completeness'
    return result
