"""Owned synthetic evidence through the real trust gate; never contacts Twitch.

Run against a NEW ignored database: python tools/demo_tracking.py artifacts/demo.sqlite3
This is a persistence demo, not a claim that a synthetic font is a game calibration.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

from exp_tracker.glyphs import GlyphProfile, SYMBOLS
from exp_tracker.models import Reading, Recognition
from exp_tracker.store import Store


def main(path):
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
        for index, exp in enumerate((1000, 1500)):
            percent = exp / 100
            result = Recognition("accepted", Reading(60, exp, percent), .99,
                                 raw={"exp": [dict(variant="pixel", text=f"{exp:,}[{percent:.2f}%]", confidence=.99)]})
            store.ingest("demo", f"demo-{index}", start + timedelta(seconds=index + 1), result,
                         profile=profile, session_id=session, source="synthetic-demo")
    with Store(path) as restarted:
        state = restarted.state("demo")
        assert state["last_trusted"]["current_exp"] == 1500
        assert state["observed_session_exp"] == 500
        print(json.dumps(state, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
