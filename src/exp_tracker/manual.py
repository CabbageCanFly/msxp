"""Read-time manual provenance. Events never become OCR observations or EXP endpoints."""
from datetime import datetime


def annotate(rows, events):
    for row in rows:
        # A frame acquired before the correction cannot resume it merely by arriving late.
        stamp = min(row.get('received_at') or row['attempted_at'], row['attempted_at'])
        event = next((e for e in reversed(events) if e['session_id'] == row['session_id']
            and e['character_id'] == row['character_id'] and datetime.fromisoformat(e['effective_at']) < datetime.fromisoformat(stamp)), None)
        row['manual_epoch'] = event['id'] if event else None
        row['manual_context'] = event if event and event['action'] == 'set' else None
    return rows


def metadata(event):
    return {k:event[k] for k in ('id','event_id','character_id','session_id','effective_at','recorded_at',
                                'provenance','action','level','current_exp','percentage_bp','reason')}


def level_evidence(event):
    return dict(value=event['level'],status='manual_admin',reason='operator_selected_level',
        policy='manual_admin_v1',correction_id=event['id'],trusted=False,identity_verified=False,
        strict_window_eligible=False)


def present(value, snapshot):
    """Replace display coordinates, never feed an operator value into earned EXP."""
    events = [e for e in snapshot.get('manual_corrections',[]) if e['session_id'] == value['session_id']
              and e['character_id'] == (value['character'] or {}).get('id')]
    if not events:
        return value
    event = events[-1]
    value['manual_correction'] = metadata(event)
    for metrics in (value.get('recent_windows',{}),value.get('current_level_windows',{})):
        for metric in metrics.values():
            eta=metric.get('eta')
            if eta and eta['estimated_at'] <= event['effective_at']:metric['eta']=None
    if event['action'] == 'clear':
        if value['reading'] and value['reading'].get('manual_epoch') != event['id']:
            value['reading']=None
        if (value.get('display_level') or {}).get('manual_epoch') != event['id']:
            value['display_level']=None;value['level_context']=None
        return value
    from .product import percentage_exp
    latest = value['reading']
    resumed = bool(latest and latest.get('manual_epoch') == event['id'] and latest['fresh_at_capture']
                   and not latest['simulated'])
    display = value.get('display_level')
    if event['level'] is not None and (not display or display.get('manual_epoch') != event['id']):
        evidence = level_evidence(event)
        display = value['display_level'] = dict(value=event['level'],timestamp=event['effective_at'],
            event_id='manual:'+event['event_id'],evidence=evidence,display_only=True,trusted=False,manual_epoch=event['id'])
    if not resumed:
        level = display['evidence'] if display else dict(value=None,status='unavailable',trusted=False)
        bp = event['percentage_bp']
        value['reading'] = dict(event_id='manual:'+event['event_id'],timestamp=event['effective_at'],
            exp=str(event['current_exp']) if event['current_exp'] is not None else None,
            percentage=f'{bp//100}.{bp%100:02}' if bp is not None else None,bp=bp,level=level,
            estimated_exp=percentage_exp(bp,level) if bp is not None and event['current_exp'] is None else None,
            exp_validity=dict(status='manual_admin',trusted=False),evidence='manual_admin',
            fresh_at_capture=False,simulated=False,trusted=False,manual_epoch=event['id'],
            provenance=metadata(event))
        value['movement']=None;value['segment']=None
    # An adjustment invalidates old current/ETA estimates, while historical gains remain available.
    value['level_context'] = None if not resumed else value['level_context']
    return value
