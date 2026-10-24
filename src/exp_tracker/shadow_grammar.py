"""Bounded full-EXP text hypotheses for display/review only. Never observations."""

from functools import lru_cache
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
    """Memoized: a pure function of its arguments. Callers treat the result as read-only."""
    if text is not None and type(text) is not str or source_complete is not None and type(source_complete) is not bool:
        return _interpret_exp(text, source_complete=source_complete)
    return _interpret_memo(text, source_complete)


@lru_cache(maxsize=4096)  # A card rebuild parses each of ~800 recent texts about a dozen times.
def _interpret_memo(text, source_complete):
    return _interpret_exp(text, source_complete=source_complete)


def _interpret_exp(text, *, source_complete=None):
    """Versioned diagnostic interpretations; v1 and both strict parsers stay frozen.

    Complete numeric fields may recover one S/O/B glyph. Missing digits and
    decimal placement are never inferred; normal downstream validation still applies.
    """
    base = dict(classification='rejected', proposals=[], trusted=False,
                numerical_identity_verified=False, reason='no_bounded_interpretation')
    result = dict(policy='bounded_exp_v11', raw=text if isinstance(text, str) and len(text) <= MAX_TEXT else None,
                  strict_full=None, strict_percentage_only=None, full_exp={**base}, percentage={**base},
                  symbol_hypotheses=[], percentage_hypotheses=[], source_complete=source_complete, trusted=False)
    if not isinstance(text, str) or not text or len(text) > MAX_TEXT:
        for field in ('full_exp', 'percentage'):
            result[field] = {**base, 'classification': 'unavailable', 'reason': 'missing_or_unbounded_text'}
        return result
    # Three integer characters cannot be an ordinary 10..99% token. Interpreting
    # the first '1' still needs prior field-mode evidence, never text grammar alone.
    leading = re.fullmatch(r'1([1-9][0-9]\.[0-9]{2})%([\]1I])', text)
    if leading and source_complete is not False:
        interpretation=f'[{leading[1]}%]'
        edits=[dict(index=0,old='1',new='[',category='opening_bracket')]
        if leading[2]!=']':edits.append(dict(index=len(text)-1,old=leading[2],new=']',category='closing_bracket'))
        result['percentage'].update(classification='review_only',reason='prior_strict_percentage_only_context_required')
        result['percentage_hypotheses']=[dict(interpretation=interpretation,reading=parse_percentage_only(interpretation),
            edits=edits,required_context='two_prior_strict_percentage_only',field_span=[0,len(text)],
            image_verification='required',source_completeness_verified=False,
            trusted=False,numerical_identity_verified=False)]
        return result
    strict, only = _full_reading(text), parse_percentage_only(text)
    if strict or only:
        result.update(strict_full=strict, strict_percentage_only=only)
        for field in ('full_exp', 'percentage'):
            result[field] = {**base, 'classification': 'raw_strict', 'reason': 'original_strict_result_unchanged'}
        return result
    # One known glyph across both numeric fields; re-use the complete-field grammar.
    digit=re.fullmatch(r'(?:([0-9SOB.,]+)([\[1|])|\[)?([0-9SOB]{1,2}\.[0-9SOB]{2})%([\]1|Il]{0,3})',text)
    if digit and source_complete is not False and sum(c in 'SOB' for c in text)==1:
        index=next(i for i,c in enumerate(text) if c in 'SOB')
        corrected=text[:index]+{'S':'5','O':'0','B':'8'}[text[index]]+text[index+1:]
        parsed=interpret_exp(corrected,source_complete=source_complete)
        for field in ('full_exp','percentage'):
            prior=parsed[field]['proposals']
            full=parsed['strict_full']
            reading=(full if field=='full_exp' else parse_percentage_only(f'[{full["percentage"]}%]')) if full else (
                parsed['strict_percentage_only'] if field=='percentage' else None)
            if reading is None and parsed[field]['classification']=='unique_proposal':reading=prior[0]['reading']
            if reading is None:continue
            edits=[dict(index=index,old=text[index],new=corrected[index],
                category='percentage_digit' if index>=digit.start(3) else 'exp_digit')]+(prior[0]['edits'] if prior else [])
            if len(edits)>5:continue
            result[field]={**base,'classification':'unique_proposal','reason':'single_numeric_glyph_recovery',
                'proposals':[dict(reading=reading,interpretation=prior[0]['interpretation'] if prior else corrected,
                    edits=edits,field_span=prior[0]['field_span'] if prior else [0,len(text)],
                    trusted=False,numerical_identity_verified=False,image_verification='required',source_completeness_verified=False)]}
        return result
    # Whole-string anchoring prevents extracting a plausible tail from clipped
    # digits or competing fields. A single leading digit needs an actual opener.
    token = re.fullmatch(r'([0-9]{2}\.[0-9]{2})%([\]1|Il]{0,3})', text)
    if token:
        only = parse_percentage_only(f'[{token[1]}%]')
        if only:
            end = text.index('%') + 1
            result['percentage'] = {**base, 'classification': 'unique_proposal',
                'reason': 'complete_standalone_percentage_token', 'proposals': [dict(
                    interpretation=text[:end], reading=only, field_span=[0, end],
                    edits=[dict(index=end, old=token[2], new='', category='closing_suffix_ignored')] if token[2] else [],
                    image_verification='required', source_completeness_verified=False,
                    trusted=False, numerical_identity_verified=False)]}
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
    # One label-tail P before an independently complete numeric field; never strip arbitrary text.
    if text.startswith('P') and len(text)>1 and text[1].isascii() and text[1].isdigit():
        tail=interpret_exp(text[1:],source_complete=source_complete)
        full=tail['strict_full'] or (tail['full_exp']['proposals'][0]['reading']
            if tail['full_exp']['classification']=='unique_proposal' else None)
        pct=tail['percentage']
        if full or (pct['classification']=='unique_proposal' and pct['proposals'][0]['field_span'][0]>0):
            for field in ('full_exp','percentage'):
                prior=tail[field]['proposals']
                reading=(full if field=='full_exp' else parse_percentage_only(f'[{full["percentage"]}%]')) if full else (
                    prior[0]['reading'] if prior else None)
                if reading is None or field=='full_exp' and source_complete is False:continue
                edits=[dict(index=0,old='P',new='',category='exp_label_tail')]+[
                    {**edit,'index':edit['index']+1} for edit in (prior[0]['edits'] if prior else [])]
                if len(edits)>4:continue
                interpretation=prior[0]['interpretation'] if prior else text[1:] if field=='full_exp' else f'[{reading["percentage"]}%]'
                span=prior[0]['field_span'] if prior else [0,len(text)-1]
                result[field]={**base,'classification':'unique_proposal','reason':'exp_label_tail_before_complete_field',
                    'proposals':[dict(interpretation=interpretation,reading=reading,edits=edits,
                        field_span=[span[0]+1,span[1]+1],image_verification='required',source_completeness_verified=False,
                        trusted=False,numerical_identity_verified=False)]}
            return result
    # An actual '[' can identify the percentage even when the preceding EXP token is unreadable.
    labelled=re.fullmatch(r'P[0-9][0-9A-Za-z,.?]*\[([0-9]{1,2}\.[0-9]{2})%([\]1])',text)
    if labelled and (reading:=parse_percentage_only(f'[{labelled[1]}%]')) is not None:
        edits=[dict(index=0,old='P',new='',category='exp_label_tail')]
        if labelled[2]=='1':edits.append(dict(index=len(text)-1,old='1',new=']',category='closing_bracket'))
        result['percentage']={**base,'classification':'unique_proposal','reason':'labelled_percentage_without_complete_exp',
            'proposals':[dict(interpretation=f'[{labelled[1]}%]',reading=reading,edits=edits,
                field_span=[text.index('['),len(text)],image_verification='required',source_completeness_verified=False,
                trusted=False,numerical_identity_verified=False)]}
        return result
    # Only a complete, unique pair may supply a missing closing bracket; no digits are added.
    if text.endswith('%') and source_complete is not False:
        closed=interpret_exp(text+']',source_complete=source_complete)
        full=closed['strict_full'] or (closed['full_exp']['proposals'][0]['reading']
            if closed['full_exp']['classification']=='unique_proposal' else None)
        if full and closed['percentage']['classification'] in ('raw_strict','unique_proposal'):
            for field,reading in (('full_exp',full),('percentage',parse_percentage_only(f'[{full["percentage"]}%]'))):
                prior=closed[field]['proposals']
                edits=(prior[0]['edits'] if prior else [])+[dict(index=len(text),old='',new=']',category='closing_bracket')]
                if len(edits)>4:return result
                interpretation=text+']' if field=='full_exp' else f'[{full["percentage"]}%]'
                if prior:interpretation=prior[0]['interpretation']
                result[field]={**base,'classification':'unique_proposal','reason':'complete_pair_missing_closing_bracket',
                    'proposals':[dict(interpretation=interpretation,reading=reading,edits=edits,
                        field_span=[0,len(text)],image_verification='required',source_completeness_verified=False,
                        trusted=False,numerical_identity_verified=False)]}
            return result
    # ')' is a bracket the strict parser already accepts; after a literal '%' it cannot be a digit.
    if not text.endswith(('%]', '%1', '%|', '%)')):
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
        # One mixed double separator is an extra dot at an otherwise valid group boundary.
        extra=re.fullmatch(r'[0-9]{1,3}(?:[,.][0-9]{3})*(?:\.,|,\.)[0-9]{3}(?:[,.][0-9]{3})*',prefix)
        dot=prefix.index('.',re.search(r'\.,|,\.',prefix).start()) if extra else None
        grouped_prefix=prefix if dot is None else prefix[:dot]+prefix[dot+1:]
        # Below 1,000 no comma proves the '1' is the opener: '192' + '10.07%' behind a lost opener
        # reads the same. Only arithmetic at an independently read level may accept it (project()).
        ungrouped = char == '1' and re.fullmatch(r'0|[1-9][0-9]{0,2}', prefix) is not None
        if char == '1' and not ungrouped and not re.fullmatch(GROUPED, grouped_prefix):
            continue
        if prefix and not re.fullmatch(r'[0-9.,]+', prefix):
            continue
        edits = []
        if char != '[':
            edits.append(dict(index=index, old=char, new='[', category='ungrouped_exp_opener' if ungrouped else 'opening_bracket'))
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
        grouped = re.fullmatch(rf'(?:{GROUPED}|[0-9]+)', grouped_prefix)
        if source_complete is not False and grouped and ',' not in token:
            full_edits = [dict(index=i, old='.', new=',', category='exp_grouping')
                          for i, c in enumerate(prefix) if c == '.' and i!=dot] + edits
            if dot is not None:full_edits.insert(0,dict(index=dot,old='.',new='',category='extra_exp_grouping'))
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
