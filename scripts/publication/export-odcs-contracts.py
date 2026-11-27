#!/usr/bin/env python3
"""Export and drift-check ODCS v3.2.0 DataContracts and RefSpec URN bindings for archive tables."""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PKG = _ROOT / 'packages/viewer_publication/src'
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from viewer_publication.archive_odcs import *
import viewer_publication.archive_odcs as _impl

if __name__ == '__main__':
    raise SystemExit(_impl.main())
