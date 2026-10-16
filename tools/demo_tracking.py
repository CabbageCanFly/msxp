"""Owned synthetic evidence through the real trust gate; never contacts Twitch.

Run against a NEW ignored database: python tools/demo_tracking.py artifacts/demo.sqlite3
This is a persistence demo, not a claim that a synthetic font is a game calibration.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import time

from exp_tracker.glyphs import GlyphProfile, SYMBOLS
from exp_tracker.models import Reading, Recognition
from exp_tracker.store import Store


def main(path, *, animate=False, interval=5):
    if not math.isfinite(interval) or not 0 < interval <= 60:
        raise ValueError("demo interval must be finite and in (0,60] seconds to stay within the gap limit")
    if path.exists():
        raise ValueError("demo requires a new database; choose another path")
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = GlyphProfile(9, {c: 6 for c in SYMBOLS}, {c: (1 << i,) for i, c in enumerate(SYMBOLS)})
    start = datetime.now(timezone.utc) - timedelta(seconds=20)
    with Store(path) as store:
        store.add_channel("demo")
        character = store.add_character("demo", "Synthetic character")
        store.select_character("demo", character, at=start)
        session = store.start_session("demo", at=start)
        steps = (1000, 1500, "unreadable", 2100, "offline", 2600, 3100) if animate else (1000, 1500)
        for index, exp in enumerate(steps):
            if animate and index:
                time.sleep(interval)
            if isinstance(exp, int):
                percent = exp / 100
                result = Recognition("accepted", Reading(60, exp, percent), .99,
                                     raw={"exp": [dict(variant="pixel", text=f"{exp:,}[{percent:.2f}%]", confidence=.99)]})
            else:
                result = Recognition(exp, reasons=["synthetic_demo_" + exp])
            when = datetime.now(timezone.utc) if animate else start + timedelta(seconds=index + 1)
            store.ingest("demo", f"demo-{index}", when, result,
                         profile=profile, session_id=session, source="synthetic-demo")
            if animate:
                print(json.dumps(store.state("demo")), flush=True)
    with Store(path) as restarted:
        state = restarted.state("demo")
        assert state["last_trusted"]["current_exp"] == (3100 if animate else 1500)
        assert state["observed_session_exp"] == (1600 if animate else 500)
        if not animate:
            print(json.dumps(state, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--animate", action="store_true", help="Append seven new synthetic events over time for the local overlay")
    parser.add_argument("--interval", type=float, default=5, help="Seconds between animated events")
    args = parser.parse_args()
    main(args.path, animate=args.animate, interval=args.interval)
