"""Runs msxp from a checkout: ./msxp (macOS/Linux/Git Bash), .\\msxp (Windows) or python tools/msxp.py."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from exp_tracker.msxp import main

raise SystemExit(main())
