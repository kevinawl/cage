"""Puts bridge/ on sys.path, the way running a bridge script does. Import first in every test."""

import sys
from pathlib import Path

BRIDGE = Path(__file__).resolve().parent.parent / "bridge"
if str(BRIDGE) not in sys.path:
    sys.path.insert(0, str(BRIDGE))
