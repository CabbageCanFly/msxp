"""Offline grammar hypotheses, never recognition, repaired observations or trust."""

import re

from analyze_temporal_ocr import complete_pair
from exp_tracker.parsing import parse_level
from exp_tracker.shadow_types import parse_percentage_only


def strict_field(text):
    if not isinstance(text, str) or len(text) > 160:
        return None
    pair = complete_pair(text)
    if pair is not None:
        return dict(kind='full_exp_pair', exp=pair[0], percentage=f'{pair[1]:.2f}')
    only = parse_percentage_only(text)
    return dict(kind='percentage_only', percentage=only['percentage']) if only else None


def propose(text, *, field='exp', numeric_level_context=False, source_complete=None):
    """Fixed edits independent of references; image completeness is explicit review, not OCR."""
    result = dict(raw=text, trusted=False, numerical_identity_verified=False,
                  classification='unrecoverable_ambiguity', strict=None, proposals=[])
    if not isinstance(text, str) or not text or len(text) > 160:
        return {**result, 'classification': 'unavailable', 'reason': 'missing_or_unbounded_text'}
    if field not in ('exp', 'level'):
        raise ValueError('Expected exp or level field')
    if field == 'level':
        if not numeric_level_context:
            return {**result, 'reason': 'numeric_level_context_not_established'}
        if re.fullmatch(r'[0-9]{1,3}', text) and 1 <= int(text) <= 200:
            result['strict'] = dict(kind='level_text', level=int(text))
        variants = []
        if re.fullmatch(r'S ?[0-9]{1,2}', text):
            edits = [dict(index=0, old='S', new='5', category='level_digit')]
            if ' ' in text:
                edits.append(dict(index=1, old=' ', new='', category='level_token_boundary'))
            variants = [('5'+text[1:].replace(' ', ''), edits)]
    else:
        result['strict'] = strict_field(text)
        variants = [(text, [])]
        # One pass per category, at most three edits; no repeated search or digit inference.
        if text.endswith('%1'):
            variants.append((text[:-1]+']', [dict(index=len(text)-1, old='1', new=']', category='suffix')]))
        elif re.search(r'\[[0-9]{1,2}\.[0-9]{2}1\]$', text):
            variants.append((text[:-2]+'%]', [dict(index=len(text)-2, old='1', new='%', category='suffix')]))
        for value, edits in list(variants):
            for i, char in enumerate(value):
                if char == '1' and re.fullmatch(r'(?:[0-9]{1,2}[. ][0-9]{2}|[0-9]{3,4})%[1\]]', value[i+1:]):
                    variants.append((value[:i]+'['+value[i+1:], edits+[
                        dict(index=i, old='1', new='[', category='field_boundary')]))
        for value, edits in list(variants):
            spaced = re.search(r'\[([0-9]{1,2}) ([0-9]{2})%[1\]]$', value)
            compact = re.search(r'\[([0-9]{3,4})%[1\]]$', value)
            if spaced:
                i = spaced.end(1)
                variants.append((value[:i]+'.'+value[i+1:], edits+[
                    dict(index=i, old=' ', new='.', category='decimal')]))
            elif compact:
                i = compact.end(1)-2
                variants.append((value[:i]+'.'+value[i:], edits+[
                    dict(index=i, old='', new='.', category='decimal')]))
    if source_complete is False:
        return {**result, 'classification': 'incomplete_or_clipped_field',
                'reason': 'source_review_does_not_establish_complete_field'}
    if result['strict'] is not None:
        return {**result, 'classification': 'complete_raw_strict',
                'reason': 'syntax_only_not_numerical_verification'}
    for value, edits in variants:
        if not edits:
            continue
        if field == 'level':
            level = parse_level(value)
            reading = dict(kind='level_text', level=level) if level and 1 <= level <= 200 else None
        else:
            reading = strict_field(value)
        if reading and value not in [row['interpretation'] for row in result['proposals']]:
            result['proposals'].append(dict(interpretation=value, reading=reading, edits=edits,
                trusted=False, image_verification='required', numerical_identity_verified=False))
    if len(result['proposals']) == 1:
        edits = result['proposals'][0]['edits']
        result['classification'] = ('plausible_single_symbol_correction' if len(edits) == 1
                                    and edits[0]['category'] != 'field_boundary'
                                    else 'multiple_symbol_or_boundary_hypothesis')
    result['reason'] = ('hypotheses_only_not_observations' if result['proposals']
                        else 'no_bounded_edit_establishes_field_grammar')
    return result
