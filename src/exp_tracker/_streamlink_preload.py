"""Imported last by the forkserver, before it creates any capture children."""
from pathlib import Path

import streamlink_cli.main  # noqa: F401
import streamlink.plugins.twitch  # noqa: F401

if len(list(Path('/proc/self/task').iterdir())) != 1:
    raise RuntimeError('Streamlink preload imports started extra threads; disable preloading')
