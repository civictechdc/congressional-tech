#!/usr/bin/env python3
"""Small catalog covering group retention, API scope and source provenance."""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PKG = _ROOT / 'packages/viewer_publication/src'
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from viewer_publication.filename_test_fixture import *
import viewer_publication.filename_test_fixture as _impl

if __name__ in ('__main__', 'native_legacy_fixture'):
    _impl.main(sys.argv[1:])
