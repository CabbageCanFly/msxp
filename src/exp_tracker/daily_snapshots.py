"""Compact observed daily status, written only inside retention's transaction."""
from datetime import datetime

from .store import utc


def save(store, character_id, observed_at, level, exp, bp, source, level_basis, exp_basis, percentage_basis):
    # Retention replays from a read snapshot; it saves these later, in the transaction that deletes the source.
    if (deferred:=getattr(store,'deferred_daily',None)) is not None:
        deferred.append((character_id,observed_at,level,exp,bp,source,level_basis,exp_basis,percentage_basis));return
    if exp is None and bp is None:return
    if store._pending_character(character_id):return
    stamp=utc(datetime.fromisoformat(observed_at))
    store.db.execute('''INSERT INTO daily_character_exp VALUES(?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(character_id,utc_date) DO UPDATE SET
            observed_at=excluded.observed_at,level=excluded.level,current_exp=excluded.current_exp,
            percentage_bp=excluded.percentage_bp,source=excluded.source,level_basis=excluded.level_basis,
            exp_basis=excluded.exp_basis,percentage_basis=excluded.percentage_basis
        WHERE excluded.observed_at>daily_character_exp.observed_at OR
            (excluded.observed_at=daily_character_exp.observed_at AND
                (excluded.source='manual_correction' AND daily_character_exp.source!='manual_correction'
                 OR excluded.source='trusted_ocr' AND daily_character_exp.source='diagnostic'))''',
        (character_id,stamp[:10],stamp,level,int(exp) if exp is not None else None,bp,
         source,level_basis,exp_basis,percentage_basis))


def _reading(store, character_id, value, *, manual=False):
    exp=value['exp'] if value['exp_validity']['status']!='invalid' else None
    source='manual_correction' if manual else 'diagnostic'
    basis='manual_supplied' if manual else value['evidence']
    percentage_basis='derived_from_manual_exp' if value.get('estimated_percentage') else basis
    save(store,character_id,value['timestamp'],value['level']['value'],exp,value['bp'],source,
        value['level']['status'],basis if exp is not None else None,percentage_basis if value['bp'] is not None else None)


def diagnostics(store, rows, recoveries):
    from .product import reading
    recovered={r['event_id']:r['value'] for r in recoveries if r['status']=='eligible_experimental'}
    for row in rows:
        value=recovered.get(row['event_id']) or reading(row)
        if (value is None or row.get('timestamp_ordered') is False or row.get('crop_suspect')
                or row.get('timing_mode')=='simulated'):continue
        manual=bool(row.get('manual_point'))
        if not manual and not value['fresh_at_capture']:continue
        _reading(store,row['character_id'],value,manual=manual)


def trusted(store, session_id, through_id, after_id, revised_rows):
    from .manual import corrected_reading
    session=store.db.execute('SELECT s.*,st.login FROM sessions s JOIN streamers st ON st.id=s.streamer_id WHERE s.id=?',
        (session_id,)).fetchone()
    points={e['target_event_id']:e for e in store.manual_history(session['login'],character_id=session['character_id'],active_only=True)
        if e['kind']=='point' and e['target_kind']=='observation' and e['session_id']==session_id}
    accepted={r['id']:r for r in revised_rows if r['outcome'] in ('accepted','baseline')}
    for row in store.db.execute('SELECT id,observed_at FROM observations WHERE session_id=? AND id>? AND id<=? ORDER BY id',
            (session_id,after_id,through_id)):
        point=points.get(str(row['id']))
        if point:
            _reading(store,session['character_id'],corrected_reading(point,timestamp=row['observed_at']),manual=True)
        elif row['id'] in accepted:
            value=accepted[row['id']]
            save(store,session['character_id'],row['observed_at'],value['level'],value['current_exp'],value['percentage_bp'],
                'trusted_ocr','trusted_ocr','observed_integer','displayed')
