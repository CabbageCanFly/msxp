"""Audited read-time presentation. Operator coordinates never supply earned EXP."""
from datetime import datetime


def active(events):
    return [e for e in events if e.get('active',True) and e.get('operation','apply')!='retract']


def revision(events):
    return tuple((e['id'],e.get('active',True)) for e in events)


def annotate(rows, events):
    events=active(events)
    for row in rows:
        owned=[e for e in events if e['session_id']==row['session_id'] and e['character_id']==row['character_id']]
        # Receipt time alone cannot make a frame acquired before a baseline release it.
        stamp=min(datetime.fromisoformat(row.get('received_at') or row['attempted_at']),datetime.fromisoformat(row['attempted_at']))
        baseline=next((e for e in reversed(owned) if e.get('kind','baseline')=='baseline'
            and datetime.fromisoformat(e['effective_at'])<stamp),None)
        points=[e for e in owned if e.get('kind')=='point']
        point=next((e for e in reversed(points) if e['target_kind']=='diagnostic' and e['target_event_id']==row['event_id']),None)
        barriers=[e['id'] for e in points if datetime.fromisoformat(e['effective_at'])<=stamp]
        baseline_id=baseline['id'] if baseline else None
        row['manual_epoch']=f'b{baseline_id}:p{barriers[-1]}' if barriers else baseline_id
        if point:row['manual_epoch']=f'point:{point["id"]}'
        row['manual_baseline_id']=baseline_id
        row['manual_context']=baseline if baseline and baseline['action']=='set' else None
        row['manual_point']=point
    return rows


def metadata(event):
    return {k:event.get(k) for k in ('id','event_id','character_id','session_id','effective_at','recorded_at',
        'provenance','action','level','current_exp','percentage_bp','reason','kind','operation','replaces_id',
        'target_kind','target_event_id')}


def level_evidence(event):
    return dict(value=event['level'],status='manual_admin',reason='operator_selected_level',
        policy='manual_admin_v2',correction_id=event['id'],trusted=False,identity_verified=False,
        strict_window_eligible=False)


def corrected_reading(event, *, event_id=None, timestamp=None, epoch=None):
    from .product import percentage_exp
    from .diagnostic_evidence import consistency
    from .exp_requirements import requirement
    level=level_evidence(event);exp=event['current_exp'];bp=event['percentage_bp'];estimated_percentage=None
    req=requirement(event['level'])
    if bp is None and exp is not None and req['to_next'] is not None and exp<req['to_next']:
        bp=exp*10000//req['to_next']
        estimated_percentage=dict(bp=bp,value=f'{bp//100}.{bp%100:02}',source='manual_exp_and_community_requirement',
            rounding='truncation_for_display_estimate',requirement=req,trusted=False)
    pct=f'{bp//100}.{bp%100:02}' if bp is not None else None
    validity=consistency(dict(exp=str(exp),percentage=pct) if exp is not None and pct is not None else None,event['level'])
    if req['to_next'] is not None and exp is not None and exp>=req['to_next']:
        validity.update(status='invalid',reason='manual_exp_outside_level_requirement')
    validity.update(provenance='manual_admin',supplied_values_preserved=True)
    return dict(event_id=event_id or 'manual:'+event['event_id'],timestamp=timestamp or event['effective_at'],
        exp=str(exp) if exp is not None else None,percentage=pct,bp=bp,level=level,
        estimated_exp=percentage_exp(bp,level) if bp is not None and exp is None else None,
        estimated_percentage=estimated_percentage,exp_validity=validity,evidence='manual_admin',
        fresh_at_capture=False,simulated=False,trusted=False,manual_epoch=epoch if epoch is not None else event['id'],
        manual_baseline_id=event['id'] if event.get('kind','baseline')=='baseline' else None,
        supplied_fields=[k for k in ('level','current_exp','percentage_bp') if event[k] is not None],provenance=metadata(event))


def present(value, snapshot):
    events=[e for e in active(snapshot.get('manual_corrections',[])) if e['session_id']==value['session_id']
            and e['character_id']==(value['character'] or {}).get('id') and e.get('kind','baseline')=='baseline']
    if not events:return value
    event=events[-1];value['manual_correction']=metadata(event)
    for metrics in (value.get('recent_windows',{}),value.get('current_level_windows',{})):
        for metric in metrics.values():
            eta=metric.get('eta')
            if eta and eta['estimated_at']<=event['effective_at']:metric['eta']=None
    latest=value['reading'];display=value.get('display_level')
    # A later point correction is independent of an older baseline or clear.
    if latest and latest['evidence']=='manual_admin' and (latest.get('provenance') or {}).get('kind')=='point' and (
            datetime.fromisoformat(latest['timestamp'])>datetime.fromisoformat(event['effective_at'])):
        return value
    if event['action']=='clear':
        if latest and latest.get('manual_baseline_id',latest.get('manual_epoch'))!=event['id']:value['reading']=None
        if (display or {}).get('manual_baseline_id',(display or {}).get('manual_epoch'))!=event['id']:
            value['display_level']=None;value['level_context']=None
        return value
    resumed=bool(latest and latest.get('manual_baseline_id',latest.get('manual_epoch'))==event['id']
                 and latest['fresh_at_capture'] and not latest['simulated'])
    if event['level'] is not None and (not display or display.get('manual_baseline_id',display.get('manual_epoch'))!=event['id']):
        display=value['display_level']=dict(value=event['level'],timestamp=event['effective_at'],
            event_id='manual:'+event['event_id'],evidence=level_evidence(event),display_only=True,trusted=False,
            manual_epoch=event['id'],manual_baseline_id=event['id'])
    if not resumed:
        value['reading']=corrected_reading(event)
        if event['level'] is None and display:value['reading']['level']=display['evidence']
        value['movement']=None;value['segment']=None;value['level_context']=None
    return value
