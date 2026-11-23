"""Read-only username metadata; tables are installed only by an explicit merge."""
import json
from urllib.parse import parse_qs, urlencode


DDL = (
    '''CREATE TABLE IF NOT EXISTS streamer_aliases (
        source_streamer_id INTEGER PRIMARY KEY REFERENCES streamers(id),
        login TEXT NOT NULL UNIQUE, streamer_id INTEGER NOT NULL REFERENCES streamers(id),
        character_map_json TEXT NOT NULL, recorded_at TEXT NOT NULL,
        CHECK(source_streamer_id!=streamer_id))''',
    '''CREATE TABLE IF NOT EXISTS streamer_merges (
        id INTEGER PRIMARY KEY, source_streamer_id INTEGER NOT NULL REFERENCES streamers(id),
        streamer_id INTEGER NOT NULL REFERENCES streamers(id), receipt_json TEXT NOT NULL, recorded_at TEXT NOT NULL)''',
    '''CREATE TRIGGER IF NOT EXISTS retired_streamer_capture BEFORE UPDATE ON streamer_capture
        WHEN (NEW.tracking_enabled=1 OR NEW.public_visible=1)
            AND EXISTS(SELECT 1 FROM streamer_aliases WHERE source_streamer_id=NEW.streamer_id)
        BEGIN SELECT RAISE(ABORT,'retired Twitch username; configure its current profile'); END''',
    *tuple(f'''CREATE TRIGGER IF NOT EXISTS streamer_merge_no_{action.lower()} BEFORE {action} ON streamer_merges
        BEGIN SELECT RAISE(ABORT,'streamer merge audit is append-only'); END''' for action in ('UPDATE','DELETE')),
)


def load(store):
    if not store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='streamer_aliases'").fetchone():return {}
    return {r['login']:dict(channel=r['channel'],characters=json.loads(r['character_map_json']))
        for r in store.db.execute('''SELECT a.login,s.login AS channel,a.character_map_json FROM streamer_aliases a
            JOIN streamers s ON s.id=a.streamer_id ORDER BY a.recorded_at DESC,a.login''')}


def previous(aliases):
    result={}
    for old,record in aliases.items():result.setdefault(record['channel'],[]).append(old)
    return result


def canonical(aliases,channel,query):
    """Keep query options intact, remapping only explicitly merged character IDs."""
    target=aliases.get(channel,{}).get('channel',channel)
    records=[record for record in aliases.values() if record['channel']==target]
    if not records:return channel,query
    values=parse_qs(query,keep_blank_values=True)
    character=values.get('character')
    if character and len(character)==1:
        mapped=next((record['characters'][character[0]] for record in records if character[0] in record['characters']),character[0])
        if str(mapped)!=character[0]:
            values['character']=[str(mapped)];query=urlencode(values,doseq=True)
    return target,query
