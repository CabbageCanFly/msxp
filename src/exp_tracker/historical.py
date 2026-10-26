"""Bounded, read-only daily observations, independent of live history replay."""
from datetime import datetime, timedelta

from .store import utc
from .daily_snapshots import complete_progress


def daily_history(store, channel, *, character=None, days=30, now=None):
    if type(days) is not int or not 1 <= days <= 365:
        raise ValueError('invalid days')
    streamer = store._channel(channel)
    cid = streamer['selected_character_id'] if character is None else character
    row = store.db.execute('SELECT id,label FROM characters WHERE id=? AND streamer_id=?',
                           (cid, streamer['id'])).fetchone()
    if (row is None or store._pending_character(cid)
            or cid in store.invalidated_characters(streamer['id'])):
        raise LookupError('unknown character')
    stamp = utc(now)
    end = datetime.fromisoformat(stamp).date()
    start = end - timedelta(days=days - 1)
    points = []
    if store.schema_version >= 9:
        for reading in store.db.execute('''SELECT utc_date,observed_at,level,current_exp,percentage_bp,
                source,level_basis,exp_basis,percentage_basis FROM daily_character_exp
                WHERE character_id=? AND utc_date>=? AND utc_date<=? ORDER BY utc_date''',
                (cid, start.isoformat(), end.isoformat())):
            value = dict(reading)
            if value['level'] is None:continue
            exp, bp = complete_progress(value['level'], value['current_exp'], value['percentage_bp'])
            if value['current_exp'] is None and exp is not None:value['exp_basis']='derived_from_percentage'
            if value['percentage_bp'] is None and bp is not None:value['percentage_basis']='derived_from_exp'
            value['current_exp'], value['percentage_bp'] = exp, bp
            value['current_exp'] = str(value['current_exp']) if value['current_exp'] is not None else None
            points.append(value)
    return dict(character_id=cid, label=row['label'], start=start.isoformat(), end=end.isoformat(),
                days=days, points=points, served_at=stamp, available=store.schema_version >= 9)
