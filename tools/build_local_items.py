"""Build the monster-drop item table and icon sheets for the /local pickup tracker.

    python tools/build_local_items.py [--out src/exp_tracker/web/local/items] [--delay 3]

Source: NiaMeowDB's MapleStory Classic monster pages. Each drop lists the Classic item name (what
pickup messages show) and an icon named by the game item ID; the ID's first digit is the inventory
tab (1 Equip, 2 Use, 3 Setup, 4 Etc). Only items monsters drop are included. Pages are fetched one
at a time with a pause between requests. Run by hand when the game adds content; players' browsers
load only the generated static files, never these sites.
"""

import argparse
import html
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


def fetch(url, delay):
    time.sleep(delay)
    with urlopen(Request(url, headers={'User-Agent': AGENT}), timeout=60) as response:
        return response.read()


def monster_ids(page):
    return sorted({int(i) for i in re.findall(r'/msclassic/monsters/(\d+)', page)} | {int(i) for i in re.findall(r'mob_(\d+)\.png', page)})


def drops(page):
    """(game ID, Classic name) for every drop on a monster page; icons are named by game ID."""
    found = {}
    # The name is the icon's alt text, or (drop tables with alt="", e.g. ores) the label right after it.
    for gid, alt, label in re.findall(r'<img src="https://cdn\.meowdb\.com/icons/(\d+)\.png" alt="([^"]*)"[^>]*>(?:<span[^>]*>([^<]+)</span>)?', page):
        if alt or label: found.setdefault(int(gid), html.unescape(alt or label).strip())
    return found


def build(out, delay, icon_delay):
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


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument('--out', type=Path, default=OUT)
    cli.add_argument('--delay', type=float, default=3.0, help='Seconds between monster page requests')
    cli.add_argument('--icon-delay', type=float, default=0.5, help='Seconds between icon requests')
    args = cli.parse_args(argv)
    build(args.out, args.delay, args.icon_delay)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
