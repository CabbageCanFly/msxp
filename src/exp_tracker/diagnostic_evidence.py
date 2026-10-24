"""Versioned read-time evidence only; never changes raw candidates or trusted state."""

from collections import deque
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
import math

from .exp_consistency import MODES, assess, infer_indexed, requirement_index
from .exp_requirements import community_table, requirement
from .shadow_grammar import interpret_exp

POLICY = 'experimental_level_v8'
EXP_DERIVED_POLICY = 'exp_derived_level_v4'
# Repeated forward evidence is still required for a wrap or a competing level.
DERIVED_SAMPLES = 3
# Keep the entire inference chain or withhold it; forgotten frames cannot become new support.
TRANSITION_SAMPLES = 64
# A near-100% to near-0% display is a level-up hypothesis, not proof. Heuristic, uncalibrated.
WRAP_FROM_BP = 9500
WRAP_TO_BP = 500
LARGE_CHANGE_BP = 1000  # Same 10-point evidence gate as diagnostic_percentage.
# A seed-quality gate, not calibrated correctness; repetition and corroboration are mandatory.
NEURAL_SEED_SCORE = .90
CONTEXT_SECONDS = 120
CONTEXT_CONFLICTS = 2
# Evidence expires by actual elapsed time, not an ideal sequential-worker cadence.
CONFIRM_GAP_SECONDS = 120


def full_reading(row):
    parsed = interpret_exp(row.get('raw_text'))
    if row.get('candidate_invalid') or row.get('percentage_only_invalid') or row.get('exp_opener_unverified'): return None
    if row.get('candidate'):
        return parsed['strict_full'] if parsed['strict_full'] and all(row['candidate'].get(k)==parsed['strict_full'][k] for k in ('exp','percentage')) else None
    proposal = parsed['full_exp']
    return proposal['proposals'][0]['reading'] if proposal['classification']=='unique_proposal' else None


def consistency(full, level):
    """Veto only a contradiction under BOTH hypotheses with supported visual context."""
    req = requirement(level)
    result = dict(status='indeterminate', level=level, requirement=req, hypotheses={}, trusted=False,
                  reason='no_full_exp' if full is None else req['status'])
    if full is None or req['to_next'] is None: return result
    checks = {mode: assess(level,int(full['exp']),full['percentage'],{level:req['to_next']},mode) for mode in MODES}
    statuses = [value['status'] for value in checks.values()]
    status = 'consistent' if 'consistent' in statuses else 'invalid' if all(s=='inconsistent' for s in statuses) else 'indeterminate'
    return {**result, 'status':status, 'hypotheses':checks,
            'reason':'contradicts_both_display_hypotheses' if status=='invalid' else 'conditional_table_agreement' if status=='consistent' else 'unavailable_numeric'}


def supported_exp(value):
    """Public numeric endpoint support, including circular level arithmetic, never verification."""
    check=value.get('exp_validity',{})
    return value.get('exp') is not None and (check.get('status')=='consistent' or
        check.get('status')=='indeterminate' and check.get('reason')=='level_derived_from_exp_pairs')


@lru_cache(maxsize=1)
def _supported_table():
    """(table, validated index); read-only, built once per process."""
    data, _ = community_table()
    table = {int(k): v for k, v in data['to_next'].items()}
    return table, requirement_index(table)


@lru_cache(maxsize=4096)  # Long-running servers see a new pair nearly every frame.
def _exp_derived(exp, percentage):
    data, sha = community_table()
    table, index = _supported_table()
    hypotheses = {mode: infer_indexed(int(exp), percentage, index, mode) for mode in MODES}
    levels = sorted({level for value in hypotheses.values() for level in value['levels']})
    result = dict(policy=EXP_DERIVED_POLICY, exp=exp, percentage=percentage, table_version=data['version'],
        table_sha256=sha, supported_levels=[min(table), max(table)], levels=levels, unique_level=None,
        hypotheses={mode: value['levels'] for mode, value in hypotheses.items()},
        source='exp_and_percentage_arithmetic', visual=False, trusted=False, authoritative=False)
    if any(value['status'] == 'invalid_input' for value in hypotheses.values()):
        return {**result, 'status': 'invalid_input', 'levels': []}
    bp = int(Decimal(percentage) * 100)
    # Disputed/missing 90+ requirements are assumed >= level 89's. A pair that could
    # need such a requirement (including every 0.00%) is outside supported coverage.
    if bp == 0 or 20000 * int(exp) >= (2 * bp - 1) * max(table.values()):
        return {**result, 'status': 'outside_supported_coverage'}
    return {**result, 'status': 'unique' if len(levels) == 1 else 'ambiguous' if levels else 'incompatible',
            'unique_level': levels[0] if len(levels) == 1 else None}


def exp_derived(full):
    """Table-only level candidates for one pair; neither visual evidence nor digit verification."""
    return None if full is None else deepcopy(_exp_derived(full['exp'], full['percentage']))


def ungrouped_opener(row):
    """The reading needs a '1' after an EXP below 1,000 to be the opener, not a digit before a lost one."""
    parsed = interpret_exp(row.get('raw_text'))
    return any(edit['category'] == 'ungrouped_exp_opener' for field in ('full_exp', 'percentage')
               if parsed[field]['classification'] == 'unique_proposal' for edit in parsed[field]['proposals'][0]['edits'])


def _percentage(row, full):
    if full: return full['percentage']
    if row.get('exp_opener_unverified'): return None
    parsed = interpret_exp(row.get('raw_text'))
    pct = parsed['strict_percentage_only'] or (parsed['percentage']['proposals'][0]['reading']
        if parsed['percentage']['classification'] == 'unique_proposal' else None)
    return pct['percentage'] if pct else None


def _forward(state, s):
    return ((s['bp'] is None or state['bp'] is None or 0 <= s['bp'] - state['bp'] < LARGE_CHANGE_BP)
        and (s['exp'] is None or state['exp'] is None or s['exp'] >= state['exp']))


def _numbers(state, s, when, **changes):
    return {**state, 'last_at': when, 'bp': state['bp'] if s['bp'] is None else s['bp'],
        'exp': state['exp'] if s['exp'] is None or s['bp'] is None else s['exp'], **changes}


def _chain(samples):
    return (len(samples) >= DERIVED_SAMPLES
        and (samples[-1]['bp'] > samples[0]['bp'] or all(s['exp'] is not None for s in samples)
             and samples[-1]['exp'] > samples[0]['exp'])
        and all(_forward(a,b) for a,b in zip(samples,samples[1:]))
        and len({s['frame_sha256'] for s in samples}) == len(samples))


def _established(level, s, when, source, previous=None):
    return dict(level=level, confirmed=True, source=source, samples=[s], confirmed_at=when, supported_at=when,
        last_at=when, exp=s['exp'], bp=s['bp'], unsupported=0, competing=None, transition=None,
        last_transition=_resolved(previous['last_transition']) if (previous or {}).get('last_transition') else None)


def compact_transition(tr):
    """Bound legacy evidence and public provenance without re-evaluating a shortened chain."""
    limit = TRANSITION_SAMPLES if 'before' in tr else DERIVED_SAMPLES
    if len(tr['samples']) <= limit: return tr
    result = {**tr, 'samples': tr['samples'][:limit-1] + tr['samples'][-1:],
        'sample_count': max(tr.get('sample_count', 0), len(tr['samples']))}
    if 'before' in tr: result['evidence_exhausted'] = True
    return result


def _resolved(tr, **changes):
    return compact_transition({**{k: v for k, v in tr.items() if k != 'before'}, **changes})


def _revert(state, s, when, reason):
    """The percentage wrap was not a level-up; keep the previous level and record why."""
    tr = state['transition']
    return _numbers(tr['before'], s, when, unsupported=tr['before']['unsupported'] + 1,
        last_transition=_resolved(tr, phase='abandoned', abandoned_at=when, abandoned_reason=reason))


def _corroborate(state, s, when, by):
    tr = state['transition']
    return {**_established(tr['to_level'], s, when, by),
        'last_transition': _resolved(tr, phase='corroborated', corroborated_at=when, corroborated_by=by)}


def _wrap(current, state, s, when):
    if state.get('last_transition'): state = {**state, 'last_transition': _resolved(state['last_transition'])}
    return dict(from_level=current, to_level=current + 1, phase='possible', detected_at=when, before_bp=state['bp'],
        after_bp=s['bp'], wrap_event_id=s['event_id'], wrap_frame=s['frame_sha256'], samples=[], before=state)


def _transition_step(state, s, inference, level, when):
    tr = compact_transition(state['transition'])
    state = {**state, 'transition': tr}
    if level == tr['to_level']:
        new = _corroborate(state, s, when, 'unique_exp_pair')
        return new, new['level'], 'exp_derived', 'level_up_corroborated_by_exp_pair'
    if level is not None:
        if level == tr['from_level'] and _forward(tr['before'], s):
            return _revert(state, s, when, 'pair_supports_previous_level'), level, 'retained_level', 'level_up_hypothesis_abandoned'
        return None, None, 'unavailable', 'level_up_hypothesis_contradicted'
    shown = tr['to_level'] if tr['phase'] == 'provisional' else None
    phase = 'provisional_level_up' if shown else 'possible_level_up'
    if inference and tr['to_level'] not in inference['levels']:
        s = {**s, 'exp': None}  # Integer withheld by exp_validity; the percentage remains.
    if s['bp'] is None:
        if tr.get('evidence_exhausted'):
            return {**state, 'last_at': when}, None, 'unavailable', 'transition_evidence_limit'
        return {**state, 'last_at': when}, shown, phase, 'post_transition_unreadable'
    last = tr['samples'][-1]['bp'] if tr['samples'] else tr['after_bp']
    if 0 <= s['bp'] - last < LARGE_CHANGE_BP:
        seen = {t['frame_sha256'] for t in tr['samples']} | {tr['wrap_frame']}
        if not tr.get('evidence_exhausted') and s['frame_sha256'] and s['frame_sha256'] not in seen:
            if len(tr['samples']) == TRANSITION_SAMPLES:
                tr = {**tr, 'evidence_exhausted': True}
            else:
                tr = {**tr, 'samples': tr['samples'] + [s]}
        if tr.get('evidence_exhausted'):
            return ({**state, 'last_at': when, 'transition': tr}, None, 'unavailable', 'transition_evidence_limit')
        # Never promote into a level whose requirement is disputed or missing.
        if tr['phase'] == 'possible' and _chain(tr['samples']) and requirement(tr['to_level'])['to_next'] is not None:
            tr.update(phase='provisional', provisional_at=when)
        shown = tr['to_level'] if tr['phase'] == 'provisional' else None
        return (_numbers(state, s, when, transition=tr, unsupported=state['unsupported'] + 1), shown,
            'provisional_level_up' if shown else 'possible_level_up', 'post_transition_progress')
    if _forward(tr['before'], s):
        return _revert(state, s, when, 'percentage_returned_to_previous_level'), tr['from_level'], 'retained_level', 'level_up_hypothesis_abandoned'
    return None, None, 'unavailable', 'level_up_hypothesis_contradicted'


def _derived_step(state, row, inference, exp, bp):
    """One fresh frame without a selected reader level: (state, value, status, reason)."""
    when = row['received_at']; frame = row.get('frame_sha256')
    if state and (datetime.fromisoformat(when) - datetime.fromisoformat(state['last_at'])).total_seconds() > CONFIRM_GAP_SECONDS:
        state = None
    level = (inference or {}).get('unique_level')
    s = dict(event_id=row.get('event_id'), frame_sha256=frame, exp=exp, bp=bp, timestamp=when)
    if not state or not state['confirmed']:
        if level is not None and frame:
            return _established(level, s, when, 'exp_derived', state), level, 'exp_derived', 'unique_exp_inference'
        if inference and not (state and state['level'] in inference['levels']):
            return None, None, 'unavailable', 'exp_derived_' + inference['status']
        if not state: return None, None, 'unavailable', None
        if not _forward(state, s): return None, None, 'unavailable', 'exp_derived_progression_contradiction'
        return _numbers(state, s, when), None, 'unavailable', 'exp_derived_confirmation_pending'
    if state['transition']:
        return _transition_step(state, s, inference, level, when)
    current = state['level']
    if level == current:
        if s['bp'] is not None and state['bp'] - s['bp'] >= LARGE_CHANGE_BP:
            return None, None, 'unavailable', 'exp_derived_progression_contradiction'
        return (_numbers(state, s, when, supported_at=when, unsupported=0, competing=None, source='exp_derived'),
            current, 'exp_derived', 'exp_derived_level_renewed')
    if level is not None:
        if state['bp'] >= WRAP_FROM_BP and s['bp'] < WRAP_TO_BP and level == current + 1:
            new = _corroborate({**state, 'transition': _wrap(current, state, s, when)}, s, when, 'unique_exp_pair')
            return new, level, 'exp_derived', 'level_up_corroborated_by_exp_pair'
        # Another unique level needs its own full chain; until then neither is shown.
        competing = state['competing']
        samples = competing['samples'] if competing and competing['level'] == level and _forward(competing['samples'][-1], s) else []
        samples = (samples + [s] if frame else samples)[-DERIVED_SAMPLES:]
        if _chain(samples) and samples[-1]['exp'] > samples[0]['exp']:
            new = {**_established(level, s, when, 'exp_derived', state), 'samples': samples, 'replaced_level': current}
            return new, level, 'exp_derived', 'exp_derived_level_replaced'
        competing = dict(level=level, samples=samples) if samples else competing
        return {**state, 'last_at': when, 'competing': competing}, None, 'conflict', 'competing_exp_derived_level'
    state = {**state, 'unsupported': state['unsupported'] + 1}
    if inference and current not in inference['levels']:
        s = {**s, 'exp': None}  # Integer withheld by exp_validity; the percentage remains.
    if s['bp'] is None or _forward(state, s):
        return _numbers(state, s, when), current, 'retained_level', 'retained_last_supported_level'
    if state['bp'] >= WRAP_FROM_BP and s['bp'] < WRAP_TO_BP:
        # A wrap is a hypothesis: the previous level stays the last supported one.
        return ({**state, 'last_at': when, 'bp': s['bp'], 'exp': s['exp'], 'transition': _wrap(current, state, s, when)},
            None, 'possible_level_up', 'percentage_wrap')
    if state['bp'] - s['bp'] < LARGE_CHANGE_BP:
        # EXP loss or a misread: the level cannot fall, but continuity is no longer ordered.
        return _numbers(state, s, when, decrease_at=when), current, 'retained_level', 'retained_after_percentage_decrease'
    return None, None, 'unavailable', 'unexplained_percentage_decrease'


def _reader_step(state, selected, status, s, when):
    """A selected reader level renews, resolves or contradicts the retained level."""
    if not state or not state['confirmed']: return None, None
    tr = state['transition']
    if tr and selected == tr['to_level']:
        return _corroborate(state, s, when, 'reader_' + status), None
    if selected == state['level']:
        if tr: return {**_revert(state, s, when, 'reader_supports_previous_level'), 'supported_at': when, 'unsupported': 0}, None
        return _numbers(state, s, when, supported_at=when, unsupported=0, source='reader_' + status), None
    if status == 'agreement': return None, 'readers_agree_on_other_level'
    return {**state, 'last_at': when}, 'reader_conflicts_exp_derived_level'


def level_context(state, when):
    """Public provenance of the retained level; never verification of it."""
    if not state: return None
    tr = state['transition'] and _resolved(state['transition'])
    return dict(policy=EXP_DERIVED_POLICY, last_supported_level=state['level'] if state['confirmed'] else None,
        candidate_level=None if state['confirmed'] else state['level'], source=state['source'],
        confirmed_at=state['confirmed_at'], supported_at=state['supported_at'], last_observed_at=state['last_at'],
        support_age_seconds=(datetime.fromisoformat(when) - datetime.fromisoformat(state['supported_at'])).total_seconds(),
        unsupported_frames=state['unsupported'], sample_event_ids=[s['event_id'] for s in state['samples']],
        transition=tr, last_transition=_resolved(state['last_transition']) if state['last_transition'] else None,
        competing_level=(state['competing'] or {}).get('level'), replaced_level=state.get('replaced_level'),
        continuity='percentage_decrease_observed' if state.get('decrease_at') else 'ordered', verified=False, trusted=False)


def _visual(row):
    value=row.get('visual_level')
    return value if row.get('visual_status')=='available' and type(value) is int and 1<=value<=200 else None


def _neural(row):
    value=row.get('neural_level') or {}; level=value.get('level'); score=value.get('score')
    valid=(value.get('status')=='numeric_candidate' and type(level) is int and 1<=level<=200
        and isinstance(value.get('text'),str) and value['text'].strip()==str(level)
        and value.get('source_complete') is not False and value.get('preprocessing') in (None,'neutral4')
        and type(score) in (int,float) and math.isfinite(score) and 0<score<=1)
    return (level,score) if valid else (None,None)


def _adjacent(before,row):
    try:
        a,b=(datetime.fromisoformat(r.get('received_at') or r['attempted_at']) for r in (before,row))
        elapsed=(b-a).total_seconds()
        rotated=(row.get('rotation_from')==before.get('run_id') and before.get('index')==60 and row.get('index')==1
            and row.get('source_identity') is not None and row.get('source_identity')==before.get('source_identity')
            and row.get('coordinator_instance') is not None and row.get('coordinator_instance')==before.get('coordinator_instance'))
        return (a.utcoffset() is not None and b.utcoffset() is not None and 0<elapsed<=CONFIRM_GAP_SECONDS
            and all(before.get(k)==row.get(k) for k in ('assigned_channel','channel','source_kind','character_id','session_id','source_identity'))
            and (before.get('run_id')==row.get('run_id') and row.get('index')==before.get('index',0)+1 or rotated)
            and (not before.get('run_interrupted') or before.get('run_id')==row.get('run_id')))
    except (TypeError,ValueError,KeyError): return False


class Projected(list):
    """A from-scratch project() result. project() never reads the fields it writes, so
    projecting these rows again from scratch returns equal rows; callers may reuse them."""


def project(rows, *, state=None, allow_context=True):
    """Only past, adjacent observations corroborate a level; no lookahead.

    EXP-derived levels are a separate, explicitly labeled fallback for frames without
    any reader level; they never become reader evidence or a reader-supported anchor.
    """
    output=[]; recent=deque(maxlen=3); previous=None; established=None; established_at=None; neural_context=False; missing=0; corroborated_at=None
    anchor=None; context_conflicts=0;context_frames=deque(maxlen=12);capture_gaps=0;derived=None
    manual_epoch=None;manual_released=False
    if state:
        recent=state['recent'];previous=state['previous'];established=state['established'];established_at=state['established_at']
        neural_context=state['neural_context'];missing=state['missing'];corroborated_at=state['corroborated_at']
        anchor=state.get('anchor');context_conflicts=state.get('context_conflicts',0)
        context_frames=state.get('context_frames',context_frames)
        capture_gaps=state.get('capture_gaps',0);derived=state.get('derived')
        manual_epoch=state.get('manual_epoch');manual_released=state.get('manual_released',False)
    for original in rows:
        if original.get('reading_invalidated'):
            row=dict(original,experimental_level=dict(value=None,status='invalidated',trusted=False),
                     exp_validity=consistency(None,None))
            output.append(row)
            continue
        if original.get('manual_epoch') != manual_epoch:
            recent.clear();previous=None;established=None;established_at=None;neural_context=False
            missing=0;corroborated_at=None;anchor=None;context_conflicts=0;capture_gaps=0;derived=None
            manual_epoch=original.get('manual_epoch');manual_released=False
        row=dict(original); visual=_visual(row); neural,score=_neural(row)
        row.pop('exp_opener_unverified',None)  # Decided again from this projection's level evidence.
        if row.get('manual_point'):
            from .manual import corrected_reading
            corrected=corrected_reading(row['manual_point'])
            row.update(experimental_level=corrected['level'],exp_validity=corrected['exp_validity'],manual_resume_eligible=False)
            output.append(row);previous=None;derived=None
            continue
        frame=row.get('frame_sha256')
        fresh=(row.get('fresh_at_capture') is True and row.get('capture_acquired') is True
            and row.get('status') in ('diagnostic_pair','diagnostic_percentage_only','malformed_or_unavailable')
            and row.get('hud_count')==1 and row.get('timestamp_ordered') is not False
            and row.get('timing_mode')!='simulated' and bool(row.get('received_at'))
            and (row.get('neural_level') or {}).get('source_complete') is not False
            and not row.get('crop_suspect') and (not frame or frame not in context_frames))
        adjacent=bool(previous and _adjacent(previous,row))
        # A failed acquisition carries no numerical point and cannot renew the
        # reader-supported anchor. Stale/duplicate/competing evidence still resets.
        ordinary_gap=(allow_context and adjacent and anchor and anchor['samples']>=2 and capture_gaps<2
            and (row.get('status') in ('missing_hud','capture_failed') or
                row.get('status')=='unavailable' and row.get('reasons')==['missing_hud'])
            and row.get('hud_count') in (None,0)
            and visual is None and neural is None and (row.get('neural_level') or {}).get('level') is None
            and (row.get('neural_level') or {}).get('source_complete') is not False
            and not row.get('raw_text') and not row.get('crop_suspect')
            and row.get('timestamp_ordered') is not False and row.get('timing_mode')!='simulated'
            and (row.get('local_age_seconds') is None or row['local_age_seconds']<=15)
            and (not frame or frame not in context_frames)
            and 0<(datetime.fromisoformat(row.get('received_at') or row['attempted_at'])-
                datetime.fromisoformat(anchor['timestamp'])).total_seconds()<=CONTEXT_SECONDS)
        if ordinary_gap:
            capture_gaps+=1
            row['experimental_level']=dict(policy=POLICY,value=None,status='unavailable',
                reason='ordinary_unreadable_context_preserved',context_gap_attempts=capture_gaps,
                context_expires_at_seconds=CONTEXT_SECONDS,visual=None,neural=None,trusted=False)
            row['exp_validity']=consistency(None,None)
            if frame:context_frames.append(frame)
            output.append(row);previous=row
            continue
        carried_gaps=capture_gaps;capture_gaps=0
        if carried_gaps and anchor and row.get('received_at') and (
                datetime.fromisoformat(row['received_at'])-datetime.fromisoformat(anchor['timestamp'])).total_seconds()>CONTEXT_SECONDS:
            adjacent=False
        # Unreadable, stale or duplicate frames of the same source carry no evidence: they
        # neither renew nor reset a retained level, which still needs fresh evidence <=120s.
        hold=(adjacent and not fresh and (row.get('hud_count') or 0)<=1 and row.get('timing_mode')!='simulated'
            and row.get('timestamp_ordered') is not False)
        if not adjacent or not fresh:
            recent.clear(); established=None; neural_context=False; missing=0; corroborated_at=None
            anchor=None;context_conflicts=0;derived=derived if hold else None
            context_frames.clear()
        manual=row.get('manual_context')
        if fresh and manual and manual['level'] is not None and not manual_released and derived is None:
            from .manual import corrected_reading
            seed=corrected_reading(manual)
            if seed['bp'] is not None:
                sample=dict(event_id='manual:'+manual['event_id'],frame_sha256='manual:'+str(manual['id']),
                    exp=manual['current_exp'],bp=seed['bp'],timestamp=manual['effective_at'])
                derived=_established(manual['level'],sample,row['received_at'],'manual_admin')
        full=full_reading(row)
        leading_exp_repair=bool(full and (row.get('raw_text') or '')[:1] in ('S','B'))
        opener=ungrouped_opener(row)
        direct=consistency(full,neural) if row.get('candidate') and neural is not None else None
        # Zero/zero fits every requirement and supplies no identifying level evidence.
        strict_support=bool(direct and direct['status']=='consistent' and full['exp']!='0' and full['percentage']!='0.00')
        selected=None; status='unavailable'; reason='visual_level_unavailable'
        conflict=visual is not None and neural is not None and visual!=neural
        evidence=dict(policy=POLICY,value=None,status=status,reason=reason,visual=visual,neural=neural,
            neural_score=score,seed_score=NEURAL_SEED_SCORE,temporal_samples=0,trusted=False)
        if fresh:
            claimed=(row.get('neural_level') or {}).get('level')
            if claimed is not None and neural is None:
                established=None; neural_context=False; recent.clear(); corroborated_at=None
                status,reason='conflict','invalid_neural_level_evidence'
            elif established is not None and neural is not None and neural!=established and visual!=neural:
                established=None; neural_context=False; recent.clear(); corroborated_at=None
                status,reason='conflict','new_neural_level_requires_confirmation'
            elif neural is not None:
                if recent and recent[-1]['level']!=neural: recent.clear(); corroborated_at=None
                recent.append(dict(level=neural,score=score,strict_support=strict_support,conflict=conflict,
                    arithmetic_conflict=bool(direct and direct['status']=='invalid')))
                if strict_support: corroborated_at=row['received_at']
                supported_recently=(corroborated_at is not None and
                    (datetime.fromisoformat(row['received_at'])-datetime.fromisoformat(corroborated_at)).total_seconds()<=30)
                seeded=any(r['score']>=NEURAL_SEED_SCORE for r in recent) and (row.get('neural_level') or {}).get('preprocessing')=='neutral4'
                corroborated=len(recent)>=2 and seeded and any(r['strict_support'] for r in recent)
                repeated=len(recent)>=3 and seeded and not any(r['conflict'] or r['arithmetic_conflict'] for r in recent)
                if visual==neural:
                    selected=neural; status='agreement'; reason='both_visual_readers'
                elif (not conflict and row.get('validated_level_floor')==neural and score>=NEURAL_SEED_SCORE
                        and (row.get('neural_level') or {}).get('preprocessing')=='neutral4'
                        and full and int(full['exp'])>0 and Decimal(full['percentage'])>0
                        and consistency(full,neural)['status']=='consistent'):
                    selected=neural; status='provisional_neural'; reason='persistent_level_guard'
                elif established==neural and (not conflict or supported_recently):
                    selected=neural; status='provisional_neural'; reason='confirmed_recent_neural_context'
                elif corroborated or repeated:
                    selected=neural; status='provisional_neural'; reason='repeated_neural_with_strict_arithmetic' if corroborated else 'repeated_neural_no_competing_visual'
                else:
                    status='conflict' if conflict else 'pending'; reason='neural_confirmation_pending'
                if selected is not None: established=selected; established_at=row['received_at']; neural_context=True
                else: established=None; neural_context=False
                missing=0
            elif visual is not None:
                if established is None or visual==established or not neural_context:
                    selected=visual; status='single_reader'; reason='available_tesseract'
                    established=visual; established_at=row['received_at']; missing=0
                else:
                    status='conflict'; reason='new_tesseract_level_requires_confirmation'
                    established=None; neural_context=False; recent.clear(); corroborated_at=None
            elif neural_context and established is not None and missing<2 and established_at and (
                    datetime.fromisoformat(row['received_at'])-datetime.fromisoformat(established_at)).total_seconds()<=30:
                missing+=1; selected=established; status='recent_context'; reason='short_missing_level_read'
            else:
                established=None; neural_context=False; recent.clear(); corroborated_at=None
        else:
            reason='failed_stale_or_ambiguous_capture'
        evidence.update(value=selected,status=status,reason=reason,temporal_samples=len(recent))
        if carried_gaps and adjacent and fresh and selected is not None:
            evidence.update(context_gap_attempts=carried_gaps,strict_window_eligible=False)
        # Context never seeds itself or renews its own expiry. Two supported reader
        # observations establish the hypothesis; arithmetic can only corroborate it.
        safe=(fresh and not row.get('crop_suspect') and (claimed is None or neural is not None)
            and not row.get('candidate_invalid') and not row.get('percentage_only_invalid')
            and (not frame or frame not in context_frames))
        if frame:context_frames.append(frame)
        if not safe:anchor=None
        if anchor:
            age=(datetime.fromisoformat(row['received_at'])-datetime.fromisoformat(anchor['timestamp'])).total_seconds()
            if (age>CONTEXT_SECONDS or visual not in (None,anchor['value'])
                    or neural not in (None,anchor['value']) and score>=NEURAL_SEED_SCORE
                    or selected not in (None,anchor['value'])):
                anchor=None;context_conflicts=0
        # The derived/retained level never outranks a selected reader level, verifies its
        # own pairs or survives a disagreement with recent reader-supported context.
        derived_safe=fresh and not row.get('candidate_invalid') and not row.get('percentage_only_invalid')
        # A leading letter may be a label tail, and an ungrouped opener may be a digit before a lost
        # opener ('192' + '10.07%'); these pairs cannot establish their own level.
        leading_verified=not (leading_exp_repair or opener)
        if not leading_verified:
            independent=selected if selected is not None else anchor['value'] if anchor and anchor['samples']>=2 and safe else None
            leading_verified=bool(safe and consistency(full,independent)['status']=='consistent')
            if not leading_verified:full=None
        # Unverified, its percentage is no more certain than its EXP: abstain as before.
        if opener and not leading_verified:row['exp_opener_unverified']=True
        inference=exp_derived(full) if derived_safe and full else None
        if inference:evidence['exp_derived']=inference
        pct=_percentage(row,full) if derived_safe else None
        numbers=dict(event_id=row.get('event_id'),frame_sha256=frame,exp=int(full['exp']) if full else None,
            bp=int(Decimal(pct)*100) if pct else None,timestamp=row.get('received_at'))
        claims={k:v for k,v in (('visual',visual),('neural',(row.get('neural_level') or {}).get('level'))) if v is not None}
        derived_value=derived_status=derived_reason=None
        if not derived_safe:
            if not hold:derived=None
        elif selected is not None:
            prior=level_context(derived,row['received_at'])
            derived,derived_reason=_reader_step(derived,selected,status,numbers,row['received_at'])
            if derived_reason:
                evidence['exp_derived_disagreement']=dict(level_context=prior,reader_level=selected,
                    reader_status=status,reader_reason=reason,resolution=derived_reason,trusted=False)
            if derived_reason=='reader_conflicts_exp_derived_level':
                selected=None;status,reason='conflict',derived_reason
                evidence.update(value=None,status=status,reason=reason)
        elif visual is not None:
            if derived:derived={**derived,'last_at':row['received_at']}
            derived_reason='unselected_visual_level'
        elif status=='conflict' and (inference or {}).get('unique_level') is None:
            derived=None;derived_reason='reader_conflict_without_unique_exp_support'
        elif anchor and anchor['samples']>=2 and (inference or {}).get('unique_level') not in (None,anchor['value']):
            derived=None;derived_reason='recent_reader_level_disagrees'
        else:
            derived,derived_value,derived_status,derived_reason=_derived_step(derived,row,inference,numbers['exp'],numbers['bp'])
        # A recent independently reader-supported level may veto a WHOLE pair,
        # even when this frame cannot establish a level. It never repairs digits.
        pair_check=consistency(full,anchor['value']) if anchor and anchor['samples']>=2 and safe else None
        veto=bool(pair_check and pair_check['status']=='invalid')
        if veto:
            pair_check.update(whole_pair_rejected=True,level_context={k:anchor[k] for k in ('value','timestamp','event_id','samples')})
        strong=safe and selected is not None and status in ('agreement','provisional_neural')
        strong=strong and (status=='agreement' or score is not None and score>=NEURAL_SEED_SCORE)
        if strong and consistency(full,selected)['status']!='invalid':
            hits=anchor['samples']+1 if anchor and anchor['value']==selected else 1
            anchor=dict(value=selected,timestamp=row['received_at'],event_id=row.get('event_id'),samples=hits,
                full=full,percentage=_percentage(row,full))
            context_conflicts=0
        elif allow_context and anchor and anchor['samples']>=2 and safe:
            support=consistency(full,anchor['value'])
            weak_conflict=neural not in (None,anchor['value'])
            if weak_conflict:context_conflicts+=1
            evidence['context_hypothesis']=dict(**anchor,
                age_seconds=(datetime.fromisoformat(row['received_at'])-datetime.fromisoformat(anchor['timestamp'])).total_seconds(),
                expires_after_seconds=CONTEXT_SECONDS,weak_conflicts=context_conflicts,
                exp_consistency=support['status'],trusted=False)
            orderly=bool(full and (anchor['full'] is None or int(full['exp'])>=int(anchor['full']['exp']))
                and (anchor['percentage'] is None or 0<=Decimal(full['percentage'])-Decimal(anchor['percentage'])<10))
            if (selected is None and context_conflicts<=CONTEXT_CONFLICTS
                    and (visual==anchor['value'] or support['status']=='consistent' and orderly)
                    and (neural in (None,anchor['value']) or score<NEURAL_SEED_SCORE)):
                evidence['reader_evidence']=dict(value=selected,status=status,reason=reason)
                selected=anchor['value']
                evidence.update(value=selected,status='contextual',reason='recent_corroborated_level',
                    contextual=True,strict_window_eligible=False)
        if derived or derived_reason:
            evidence['level_context']={**(level_context(derived,row.get('received_at') or row['attempted_at']) or {}),'reason':derived_reason}
        if selected is None and derived_status not in (None,'unavailable'):
            selected=derived_value
            evidence.update(value=selected,status=derived_status,reason=derived_reason,strict_window_eligible=False)
            # Unconfirmed reader numbers stay visible; an obscured HUD can produce them.
            if claims:evidence['unselected_reader_claims']=claims
        if manual and manual['level'] is not None and fresh:
            if status in ('agreement','provisional_neural') and selected is not None:
                manual_released=True
            transition=(derived or {}).get('last_transition') or (derived or {}).get('transition') or {}
            forward_transition=(derived_value==manual['level']+1 and (
                transition.get('from_level')==manual['level'] and transition.get('phase') in ('provisional','corroborated')
                or (derived or {}).get('replaced_level')==manual['level'] and len((derived or {}).get('samples',[]))>=DERIVED_SAMPLES))
            if forward_transition and derived_status in ('exp_derived','provisional_level_up'):
                manual_released=True
                evidence['manual_seed']=dict(correction_id=manual['id'],level=manual['level'],effective_at=manual['effective_at'])
            if not manual_released:
                from .manual import level_evidence
                context=evidence.get('level_context')
                evidence=level_evidence(manual)
                evidence.update(reader_evidence=dict(value=selected,status=status),visual=visual,neural=neural)
                if context:evidence['level_context']=context
                selected=manual['level']
        row['experimental_level']=evidence
        row['exp_validity']=pair_check if veto else consistency(full,selected)
        if evidence['status']=='exp_derived':
            # The level came from these same OCR pairs; agreement would be circular.
            row['exp_validity'].update(status='indeterminate',reason='level_derived_from_exp_pairs')
        if leading_exp_repair and (not leading_verified or row['exp_validity']['status']!='consistent'):
            row['exp_validity'].update(status='invalid',reason='leading_exp_glyph_requires_independent_arithmetic')
        if opener and row['exp_validity']['status']!='consistent':row['exp_opener_unverified']=True
        if row.get('manual_epoch') is not None:
            row['manual_resume_eligible']=bool(fresh and not row.get('candidate_invalid')
                and not row.get('percentage_only_invalid') and row['exp_validity']['status']!='invalid'
                and evidence['status']!='conflict')
        output.append(row); previous=row
    if state is not None:
        state.update(recent=recent,previous=previous,established=established,established_at=established_at,
            neural_context=neural_context,missing=missing,corroborated_at=corroborated_at,
            anchor=anchor,context_conflicts=context_conflicts,context_frames=context_frames,capture_gaps=capture_gaps,derived=derived,
            manual_epoch=manual_epoch,manual_released=manual_released)
    return Projected(output) if state is None and allow_context else output
