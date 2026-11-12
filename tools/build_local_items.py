"""Build the item table and icon sheets for the /local pickup tracker.

    python tools/build_local_items.py --source maplestory-io [--delay 2.7]
    python tools/build_local_items.py --source niadb [--delay 10] [--item-pages]

maplestory-io (used): maplestory.io's copy of the MapleStory Classic World client data (region MCW, version
1): every item's Classic name, category and icon, from one item list and one icon request per item. It
matched all 924 items of the NiaDB build by game ID and name (checked 2026-11-11). The client data has no
drop tables, so the table holds every non-cash Equip, Use and Etc item. Icons are kept in --icon-cache, so
an interrupted run resumes. maplestory.io states no request limits; MSIO_GAP paces a full run near 1.5 h.

niadb (kept as a backup): NiaMeowDB's MapleStory Classic monster pages. Each drop lists the Classic item name (what
pickup messages show) and an icon named by the game item ID; the ID's first digit is the inventory
tab (1 Equip, 2 Use, 3 Setup, 4 Etc). Only items monsters drop are included. Requests go one at a
time, at least MIN_GAP seconds apart (the site's tool rules, https://meowdb.com/reuse#tool-rules), and
the run stops at the first refusal (403 or 429): the site blocked a run at 2 s that kept going. Run by hand when the game adds content; players' browsers
load only the generated static files, never these sites.

Measured 2026-11-11: the monster list page shows only part of the monsters, and a monster page can
omit drops its items' pages name (Animal Fur Bundle is not on Fire Boar's page). --item-pages also
visits every item page (about 4,300) and adds those marked as monster drops; each page read is kept
in --cache, so an interrupted run resumes where it stopped.
"""

import argparse
import gzip
import html
import tempfile
from urllib.error import HTTPError
from urllib.parse import unquote_plus
from io import BytesIO
import json
from pathlib import Path
import re
import time
from urllib.request import Request, urlopen

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'src' / 'exp_tracker' / 'web' / 'local' / 'items'
AGENT = 'msxp-item-sync/1.0 (+https://msxp.pages.dev)'
SITE = 'https://meowdb.com/msclassic'
ICON = 'https://cdn.meowdb.com/icons/{}.png'
CELL, PER_ROW, PER_SHEET = 32, 16, 256  # 32x32 icons on a 16x16 grid: 256 icons per sheet.
TABS = {'1': 'Equip', '2': 'Use', '3': 'Setup', '4': 'Etc'}


MIN_GAP = 10  # Seconds between any two NiaDB requests, icons included.
MSIO = 'https://maplestory.io/api/MCW/1'
MSIO_GAP = 2.5  # Seconds between maplestory.io requests (no stated limit; ~2,000 icons in about 1.5 h at 2.7).


def fetch(url, delay, floor=MIN_GAP):
    time.sleep(max(delay, floor))
    try:
        # Compressed: an item page is ~280 KB as HTML (measured), several times smaller gzipped.
        with urlopen(Request(url, headers={'User-Agent': AGENT, 'Accept-Encoding': 'gzip'}), timeout=60) as response:
            body = response.read()
            return gzip.decompress(body) if response.headers.get('Content-Encoding') == 'gzip' else body
    except HTTPError as error:
        if error.code in (403, 429):  # Refused: never retry; SystemExit passes every `except Exception`.
            raise SystemExit(f'Stopped: {url} answered {error.code}. Ask the site before running again.') from error
        raise


def monster_ids(page):
    return sorted({int(i) for i in re.findall(r'/msclassic/monsters/(\d+)', page)} | {int(i) for i in re.findall(r'mob_(\d+)\.png', page)})


def drops(page):
    """(game ID, Classic name) for every drop on a monster page; icons are named by game ID."""
    found = {}
    # The name is the icon's alt text, or (drop tables with alt="", e.g. ores) the label right after it.
    for gid, alt, label in re.findall(r'<img src="https://cdn\.meowdb\.com/icons/(\d+)\.png" alt="([^"]*)"[^>]*>(?:<span[^>]*>([^<]+)</span>)?', page):
        if alt or label: found.setdefault(int(gid), html.unescape(alt or label).strip())
    return found


def named(parts):
    """Monster names only: not "3 monsters", "2 other monsters", "a reward from 2 quests" (older caches kept those)."""
    return [m for m in parts if not re.match(r'(or )?(\d+ (other )?monsters?$|a reward )', m)]


def item_page(page):
    """(game ID, name, monsters) when an item page marks the item as a monster drop, else None.

    The page's share image names the item, its icon (game ID) and "Monster Drop"; the description lists
    up to two monsters ("dropped by Fire Boar, Stirge and 2 other monsters")."""
    image = re.search(r'<meta property="og:image" content="([^"]+)"', page)
    if not image: return None
    query = unquote_plus(html.unescape(image.group(1)))
    gid, name = re.search(r'/icons/(\d+)', query), re.search(r'[?&]title=([^&]+)', query)
    description = html.unescape(re.search(r'<meta name="description" content="([^"]*)"', page).group(1)) if 'name="description"' in page else ''
    dropped = re.search(r'dropped by (.+?)(?: and \d+ other monsters?)?\.', description)
    if not gid or not name or not ('Monster Drop' in query or dropped): return None
    # Only named monsters: not "3 monsters", "2 other monsters" or "or a reward from 2 quests".
    monsters = named(re.split(r',? and |,? or |, ', dropped.group(1))) if dropped else []
    return [int(gid.group(1)), name.group(1).strip(), monsters]


def item_pages(delay, cache, misses=100, limit=20000):
    """Every item page in order until `misses` missing pages in a row; results are appended to `cache`."""
    seen = {}
    if cache.exists():
        for line in cache.read_text(encoding='utf-8').splitlines():
            n, found = json.loads(line); seen[n] = found
    n, gap = 0, 0
    with cache.open('a', encoding='utf-8') as log:
        while gap < misses and n < limit:
            n += 1
            if n in seen: gap = 0 if seen[n] != 'missing' else gap + 1; continue
            try:
                found = item_page(fetch(f'{SITE}/item-db/{n}', delay).decode('utf-8')) or 'not a drop'
            except HTTPError as error:
                if error.code != 404: print(f'item page {n}: {error}'); continue
                found = 'missing'
            except Exception as error:
                print(f'item page {n}: {error}'); continue  # Not cached: tried again on the next run.
            seen[n] = found; gap = 0 if found != 'missing' else gap + 1
            log.write(json.dumps([n, found]) + '\n'); log.flush()
            if n % 100 == 0: print(f'item page {n}: {sum(isinstance(v, list) for v in seen.values())} monster drops so far')  # Drops are lists, as in the cache.
    return [v for v in seen.values() if isinstance(v, list)]


def build(out, delay, icon_delay, pages=False, cache=None):
    monsters = monster_ids(fetch(f'{SITE}/monsters', 0).decode('utf-8'))
    items, sources = {}, {}
    for n, mob in enumerate(monsters, 1):
        try:
            page = fetch(f'{SITE}/monsters/{mob}', delay).decode('utf-8')
        except Exception as error:
            print(f'monster {mob}: {error}'); continue
        title = re.search(r'<title>(.*?) - MapleStory Classic', page)
        for gid, name in drops(page).items():
            if str(gid)[0] in TABS:
                items[gid] = name
                sources.setdefault(gid, []).append(html.unescape(title.group(1)) if title else str(mob))
        print(f'{n}/{len(monsters)} monster {mob}: {len(items)} items so far')
    if pages:
        for gid, name, mobs in item_pages(delay, cache):
            if str(gid)[0] in TABS:
                items.setdefault(gid, name)
                sources.setdefault(gid, []).extend(named(mobs))
    out.mkdir(parents=True, exist_ok=True)
    rows, sheet, index = [], None, 0
    for n, gid in enumerate(sorted(items)):
        if n % PER_SHEET == 0:
            if sheet: sheet.save(out / f'icons-{index}.png', optimize=True); index += 1
            sheet = Image.new('RGBA', (CELL * PER_ROW, CELL * PER_ROW), (0, 0, 0, 0))
        cell, row = n % PER_SHEET, [items[gid], TABS[str(gid)[0]], gid, sorted(set(sources[gid]))]
        try:
            icon = Image.open(BytesIO(fetch(ICON.format(gid), icon_delay))).convert('RGBA')
            icon.thumbnail((CELL, CELL))
            sheet.paste(icon, ((cell % PER_ROW) * CELL + (CELL - icon.width) // 2, (cell // PER_ROW) * CELL + (CELL - icon.height) // 2))
            row += [index, cell]
        except Exception as error:  # A missing icon only means a text-only entry.
            print(f'no icon for {gid} {items[gid]}: {error}')
        rows.append(row)
    if sheet: sheet.save(out / f'icons-{index}.png', optimize=True)
    data = {'source': 'NiaMeowDB MapleStory Classic monster drops', 'cell': CELL, 'perRow': PER_ROW,
            'items': sorted(rows, key=lambda r: r[0].lower())}  # [name, tab, game ID, [monsters], sheet?, cell?]
    (out / 'items.json').write_text(json.dumps(data, separators=(',', ':'), ensure_ascii=False), encoding='utf-8')
    print(f'{len(rows)} items from {len(monsters)} monsters, {index + 1} icon sheets in {out}')


def msio_items(listing):
    """The items players can pick up: non-cash Equip, Use and Etc, not hair, faces or skins. Ordered Etc,
    Use, Equip (then by ID), so common drops share the first icon sheets and a browser loads few sheets."""
    order = {'Etc': 0, 'Use': 1, 'Equip': 2}
    keep = [x for x in listing if not x.get('isCash') and x['typeInfo']['overallCategory'] in order
            and x['typeInfo'].get('subCategory') not in ('Hair', 'Face', 'Skin') and str(x['id'])[0] in TABS and x.get('name', '').strip()]
    # One entry per name and tab: messages show only the name, and two equal names (Blue Potion 2000003 and
    # 2000008) made the matcher refuse both. The lowest ID is the regular item.
    unique = {}
    for x in sorted(keep, key=lambda x: x['id']): unique.setdefault((x['name'].strip().lower(), str(x['id'])[0]), x)
    return sorted(unique.values(), key=lambda x: (order[x['typeInfo']['overallCategory']], x['id']))


def build_msio(out, delay, icon_cache):
    listing = json.loads(fetch(f'{MSIO}/item?startPosition=0&count=100000', 0, MSIO_GAP))
    items = msio_items(listing)
    icon_cache.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    rows, sheet, index, fetched = [], None, 0, 0
    for n, x in enumerate(items):
        if n % PER_SHEET == 0:
            if sheet: sheet.save(out / f'icons-{index}.png', optimize=True); index += 1
            sheet = Image.new('RGBA', (CELL * PER_ROW, CELL * PER_ROW), (0, 0, 0, 0))
        gid, cell = x['id'], n % PER_SHEET
        row, cached = [x['name'].strip(), TABS[str(gid)[0]], gid, []], icon_cache / f'{gid}.png'
        try:
            if not cached.exists():
                cached.write_bytes(fetch(f'{MSIO}/item/{gid}/icon', delay, MSIO_GAP)); fetched += 1
            icon = Image.open(cached).convert('RGBA')
            icon.thumbnail((CELL, CELL))
            sheet.paste(icon, ((cell % PER_ROW) * CELL + (CELL - icon.width) // 2, (cell // PER_ROW) * CELL + (CELL - icon.height) // 2))
            row += [index, cell]
        except Exception as error:  # A missing icon only means a text-only entry; a refusal stops the run (SystemExit).
            print(f'no icon for {gid} {x["name"]}: {error}')
        rows.append(row)
        if (n + 1) % 100 == 0: print(f'{n + 1}/{len(items)} items, {fetched} icons fetched this run', flush=True)
    if sheet: sheet.save(out / f'icons-{index}.png', optimize=True)
    for old in out.glob('icons-*.png'):  # Sheets left over from a larger earlier build.
        if int(old.stem.split('-')[1]) > index: old.unlink()
    data = {'source': 'maplestory.io MapleStory Classic World client data (MCW 1)', 'cell': CELL, 'perRow': PER_ROW,
            'items': sorted(rows, key=lambda r: r[0].lower())}  # [name, tab, game ID, [monsters], sheet?, cell?]
    (out / 'items.json').write_text(json.dumps(data, separators=(',', ':'), ensure_ascii=False), encoding='utf-8')
    print(f'{len(rows)} items, {index + 1} icon sheets in {out}')


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument('--source', choices=['maplestory-io', 'niadb'], default='maplestory-io')
    cli.add_argument('--out', type=Path, default=OUT)
    cli.add_argument('--delay', type=float, default=None, help=f'Seconds between requests (at least {MSIO_GAP} for maplestory-io, {MIN_GAP} for niadb)')
    cli.add_argument('--icon-delay', type=float, default=MIN_GAP, help=f'Seconds between icon requests (at least {MIN_GAP})')
    cli.add_argument('--item-pages', action='store_true', help='Also read every item page (about 4,300) for monster drops')
    cli.add_argument('--cache', type=Path, default=Path(tempfile.gettempdir()) / 'msxp-item-pages.jsonl', help='NiaDB item pages already read (resumes a run)')
    cli.add_argument('--icon-cache', type=Path, default=Path(tempfile.gettempdir()) / 'msxp-msio-icons', help='maplestory.io icons already fetched (resumes a run)')
    args = cli.parse_args(argv)
    if args.source == 'maplestory-io': build_msio(args.out, args.delay if args.delay is not None else 2.7, args.icon_cache)
    else: build(args.out, args.delay if args.delay is not None else MIN_GAP, args.icon_delay, args.item_pages, args.cache)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
