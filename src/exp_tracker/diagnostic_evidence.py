"""Versioned read-time evidence only; never changes raw candidates or trusted state."""

from collections import deque
from datetime import datetime
import math

from .exp_consistency import MODES, assess
from .exp_requirements import requirement
from .shadow_grammar import interpret_exp

POLICY = 'experimental_level_v1'
# A seed-quality gate, not calibrated correctness; repetition and corroboration are mandatory.
NEURAL_SEED_SCORE = .90


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
        a,b=datetime.fromisoformat(before['received_at']),datetime.fromisoformat(row['received_at'])
        elapsed=(b-a).total_seconds()
        rotated=(row.get('rotation_from')==before.get('run_id') and before.get('index')==60 and row.get('index')==1
            and row.get('source_identity') is not None and row.get('source_identity')==before.get('source_identity')
            and row.get('coordinator_instance') is not None and row.get('coordinator_instance')==before.get('coordinator_instance'))
        return (a.utcoffset() is not None and b.utcoffset() is not None and 0<elapsed<=min(120,1.5*before.get('interval_seconds',15))
            and all(before.get(k)==row.get(k) for k in ('assigned_channel','channel','source_kind','character_id','session_id','source_identity'))
            and (before.get('run_id')==row.get('run_id') and row.get('index')==before.get('index',0)+1 or rotated)
            and (not before.get('run_interrupted') or before.get('run_id')==row.get('run_id')))
    except (TypeError,ValueError,KeyError): return False


def project(rows, *, state=None):
    """Only past, adjacent observations corroborate a level; no lookahead or EXP-derived choice."""
    output=[]; recent=deque(maxlen=3); previous=None; established=None; established_at=None; neural_context=False; missing=0; corroborated_at=None
    if state:
        recent=state['recent'];previous=state['previous'];established=state['established'];established_at=state['established_at']
        neural_context=state['neural_context'];missing=state['missing'];corroborated_at=state['corroborated_at']
    for original in rows:
        row=dict(original); visual=_visual(row); neural,score=_neural(row)
        fresh=(row.get('fresh_at_capture') is True and row.get('capture_acquired') is True
            and row.get('status') in ('diagnostic_pair','diagnostic_percentage_only','malformed_or_unavailable')
            and row.get('hud_count')==1 and row.get('timestamp_ordered') is not False
            and row.get('timing_mode')!='simulated' and bool(row.get('received_at'))
            and (row.get('neural_level') or {}).get('source_complete') is not False)
        if not previous or not _adjacent(previous,row) or not fresh:
            recent.clear(); established=None; neural_context=False; missing=0; corroborated_at=None
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
            elif established is not None and neural is not None and neural!=established:
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
        row['experimental_level']=evidence
        row['exp_validity']=consistency(full,selected)
        output.append(row); previous=row
    if state is not None:
        state.update(recent=recent,previous=previous,established=established,established_at=established_at,
            neural_context=neural_context,missing=missing,corroborated_at=corroborated_at)
    return output
