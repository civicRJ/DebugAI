"""Where DebugAI writes its runtime state (diagnoses, traces, calibration, users).

Defaults to the ``server/`` directory (local dev). Set ``DEBUGAI_DATA_DIR`` to a
writable path — e.g. a mounted Docker volume — to persist state outside the
code tree.
"""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DEBUGAI_DATA_DIR") or Path(__file__).resolve().parent)
DATA_DIR.mkdir(parents=True, exist_ok=True)


def data_path(name: str) -> Path:
    return DATA_DIR / name
