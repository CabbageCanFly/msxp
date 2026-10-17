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
