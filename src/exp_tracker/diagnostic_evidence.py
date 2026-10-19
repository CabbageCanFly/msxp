"""Versioned read-time evidence only; never changes raw candidates or trusted state."""

from collections import deque
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
import math

from .exp_consistency import MODES, assess, infer_levels
from .exp_requirements import community_table, requirement
from .shadow_grammar import interpret_exp

POLICY = 'experimental_level_v5'
EXP_DERIVED_POLICY = 'exp_derived_level_v1'
# Separate fresh frames, one unique table level and rising EXP; one pair never suffices.
DERIVED_SAMPLES = 3
# Like missing reader levels, unconfirming frames carry a confirmed level only briefly.
DERIVED_CARRY = 2
DERIVED_CARRY_SECONDS = 30
# A seed-quality gate, not calibrated correctness; repetition and corroboration are mandatory.
NEURAL_SEED_SCORE = .90
CONTEXT_SECONDS = 120
CONTEXT_CONFLICTS = 2
# Evidence expires by actual elapsed time, not an ideal sequential-worker cadence.
CONFIRM_GAP_SECONDS = 120


def full_reading(row):
    parsed = interpret_exp(row.get('raw_text'))
    if row.get('candidate_invalid') or row.get('percentage_only_invalid'): return None
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


@lru_cache(maxsize=4096)  # Long-running servers see a new pair nearly every frame.
def _exp_derived(exp, percentage):
    data, sha = community_table()
    table = {int(k): v for k, v in data['to_next'].items()}
    hypotheses = {mode: infer_levels(int(exp), percentage, table, mode) for mode in MODES}
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


def _percentage(row, full):
    if full: return full['percentage']
    parsed = interpret_exp(row.get('raw_text'))
    pct = parsed['strict_percentage_only'] or (parsed['percentage']['proposals'][0]['reading']
        if parsed['percentage']['classification'] == 'unique_proposal' else None)
    return pct['percentage'] if pct else None


def _derived_step(state, row, inference, exp, bp):
    """Advance the EXP-derived hypothesis on a safe frame without reader levels."""
    when = datetime.fromisoformat(row['received_at'])
    age = (when - datetime.fromisoformat(state['supported_at'])).total_seconds() if state else None
    if state and age > CONFIRM_GAP_SECONDS: state = None
    # A wrapped/decreasing display is never a level-up; a new level needs its own pairs.
    orderly = bool(state and (bp is None or 0 <= bp - state['bp'] < 1000)
        and (exp is None or state['exp'] is None or exp >= state['exp']))
    level, frame = (inference or {}).get('unique_level'), row.get('frame_sha256')
    if level is not None and frame:
        sample = dict(event_id=row.get('event_id'), frame_sha256=frame, exp=exp, bp=bp, timestamp=row['received_at'])
        same = orderly and state['level'] == level
        samples = (state['samples'] if same else [])[-(DERIVED_SAMPLES - 1):] + [sample]
        confirmed = same and state['confirmed'] or (len(samples) >= DERIVED_SAMPLES
            and samples[-1]['exp'] > samples[0]['exp'] and len({s['frame_sha256'] for s in samples}) == len(samples))
        state = dict(level=level, samples=samples, confirmed=confirmed, supported_at=row['received_at'], missing=0, exp=exp, bp=bp)
        return state, level if confirmed else None, 'repeated_unique_exp_inference' if confirmed else 'exp_derived_confirmation_pending'
    if inference and not (state and state['level'] in inference['levels'] and inference['status'] in ('unique', 'ambiguous')):
        return None, None, 'exp_derived_' + inference['status']
    if not state: return None, None, None
    if not orderly: return None, None, 'exp_derived_progression_contradiction'
    carried = state['confirmed'] and state['missing'] < DERIVED_CARRY and age <= DERIVED_CARRY_SECONDS
    state = dict(state, missing=state['missing'] + 1, exp=state['exp'] if exp is None else exp, bp=state['bp'] if bp is None else bp)
    return state, state['level'] if carried else None, 'short_exp_derived_context' if carried else 'exp_derived_confirmation_pending'


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


def project(rows, *, state=None, allow_context=True):
    """Only past, adjacent observations corroborate a level; no lookahead.

    EXP-derived levels are a separate, explicitly labeled fallback for frames without
    any reader level; they never become reader evidence or a reader-supported anchor.
    """
    output=[]; recent=deque(maxlen=3); previous=None; established=None; established_at=None; neural_context=False; missing=0; corroborated_at=None
    anchor=None; context_conflicts=0;context_frames=deque(maxlen=12);capture_gaps=0;derived=None
    if state:
        recent=state['recent'];previous=state['previous'];established=state['established'];established_at=state['established_at']
        neural_context=state['neural_context'];missing=state['missing'];corroborated_at=state['corroborated_at']
        anchor=state.get('anchor');context_conflicts=state.get('context_conflicts',0)
        context_frames=state.get('context_frames',context_frames)
        capture_gaps=state.get('capture_gaps',0);derived=state.get('derived')
    for original in rows:
        row=dict(original); visual=_visual(row); neural,score=_neural(row)
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
        if not adjacent or not fresh:
            recent.clear(); established=None; neural_context=False; missing=0; corroborated_at=None
            anchor=None;context_conflicts=0;derived=None
            context_frames.clear()
        full=full_reading(row)
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
            elif established is not None and neural is not None and neural!=established and not (carried_gaps and visual==neural):
                established=None; neural_context=False; recent.clear(); corroborated_at=None
                status,reason='conflict','new_neural_level_requires_confirmation'
            elif neural is not None:
                if recent and recent[-1]['level']!=neural: recent.clear()
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
        # The EXP-derived hypothesis never outranks a reader level, verifies its own
        # pairs or survives a disagreement with recent reader-supported context.
        reader=next((v for v in (selected,visual,neural) if v is not None),None)
        claimed_any=reader is not None or (row.get('neural_level') or {}).get('level') is not None
        strict=full if safe and row.get('candidate') else None
        inference=exp_derived(strict) if strict and (not claimed_any or derived) else None
        if inference:evidence['exp_derived']=inference
        derived_value=derived_reason=None
        if not safe:derived=None
        elif claimed_any:
            if derived and derived['confirmed'] and reader not in (None,derived['level']):
                evidence['exp_derived_disagreement']=dict(exp_derived_level=derived['level'],reader_level=reader,
                    reader_status=status,reader_reason=reason,trusted=False)
                age=(datetime.fromisoformat(row['received_at'])-datetime.fromisoformat(derived['supported_at'])).total_seconds()
                if status!='agreement' and derived['missing']<DERIVED_CARRY and age<=DERIVED_CARRY_SECONDS:
                    selected=None;status,reason='conflict','reader_conflicts_exp_derived_level'
                    evidence.update(value=None,status=status,reason=reason)
                    derived=dict(derived,missing=derived['missing']+1)
                else:derived=None
            else:derived=None
        elif anchor and anchor['samples']>=2 and (inference or {}).get('unique_level') not in (None,anchor['value']):
            derived=None;derived_reason='recent_reader_level_disagrees'
        else:
            pct=_percentage(row,full)
            derived,derived_value,derived_reason=_derived_step(derived,row,inference,
                int(full['exp']) if full else None,int(Decimal(pct)*100) if pct else None)
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
            evidence['exp_derived_context']=dict(policy=EXP_DERIVED_POLICY,reason=derived_reason,
                level=derived and derived['level'],confirmed=bool(derived and derived['confirmed']),
                sample_event_ids=[s['event_id'] for s in derived['samples']] if derived else [],
                unconfirmed_frames=derived and derived['missing'],supported_at=derived and derived['supported_at'],trusted=False)
        if derived_value is not None and selected is None:
            selected=derived_value
            evidence.update(value=selected,status='exp_derived',reason=derived_reason,strict_window_eligible=False)
        row['experimental_level']=evidence
        row['exp_validity']=pair_check if veto else consistency(full,selected)
        if evidence['status']=='exp_derived':
            # The level came from these same OCR pairs; agreement would be circular.
            row['exp_validity'].update(status='indeterminate',reason='level_derived_from_exp_pairs')
        output.append(row); previous=row
    if state is not None:
        state.update(recent=recent,previous=previous,established=established,established_at=established_at,
            neural_context=neural_context,missing=missing,corroborated_at=corroborated_at,
            anchor=anchor,context_conflicts=context_conflicts,context_frames=context_frames,capture_gaps=capture_gaps,derived=derived)
    return output
