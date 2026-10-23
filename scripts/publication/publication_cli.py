#!/usr/bin/env python3
"""One supported viewer command interface, including read-only attempt discovery."""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PKG = _ROOT / 'packages/viewer_publication/src'
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

import viewer_publication.publication_cli as _impl
from viewer_publication.publication_cli import *

# Replace wrapper in sys.modules so monkeypatching and attribute access on publication_cli
# directly target the canonical implementation in viewer_publication.publication_cli.
sys.modules[__name__] = _impl
