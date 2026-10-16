"""Seed a NEW database with 35 minutes of explicitly synthetic, guarded history."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from exp_tracker.glyphs import GlyphProfile, SYMBOLS
from exp_tracker.models import Reading, Recognition
from exp_tracker.store import Store, utc


def main(path, *, as_of=None):
    end = datetime.fromisoformat(utc(as_of))
    if path.exists():
        raise ValueError("synthetic history requires a new database; choose another path")
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = GlyphProfile(9, {c: 6 for c in SYMBOLS}, {c: (1 << i,) for i, c in enumerate(SYMBOLS)})
    start = end - timedelta(minutes=35)
    with Store(path) as store:
        store.add_channel("demo")
        character = store.add_character("demo", "Synthetic hero")
        store.select_character("demo", character, at=start)
        session = store.start_session("demo", at=start)
        for index in range(71):
            exp = 100000 + index * 2000
            # This scale is invented synthetic test data, NOT a MapleStory EXP table.
            percentage = exp / 10000
            result = Recognition("unreadable", reasons=["synthetic_missing_frame"]) if index == 65 else Recognition(
                "accepted", Reading(60, exp, percentage), .99,
                raw={"exp": [dict(variant="pixel", text=f"{exp:,}[{percentage:.2f}%]", confidence=.99)]})
            store.ingest("demo", f"synthetic-history-{index}", start + timedelta(seconds=index * 30), result,
                         profile=profile, session_id=session, source="synthetic-statistics-demo")
        state = store.state("demo", as_of=end)
    print(json.dumps(state, indent=2))
    return state


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--at", type=datetime.fromisoformat, help="Aware ISO end time; default now, for a fresh local preview")
    args = parser.parse_args()
    main(args.path, as_of=args.at)
