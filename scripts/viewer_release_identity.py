#!/usr/bin/env python3
"""Standard-library release identity shared by early checks and publication."""
from __future__ import annotations
import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / 'packages/viewer_publication/src'
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from viewer_publication.release_identity import *
