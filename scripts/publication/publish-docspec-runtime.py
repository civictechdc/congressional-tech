#!/usr/bin/env python3
"""Build, verify, and optionally upload a byte-pinned DocSpec runtime artifact to R2."""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PKG = _ROOT / 'packages/viewer_publication/src'
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from viewer_publication.publish_docspec_runtime import *
import viewer_publication.publish_docspec_runtime as _impl

if __name__ == '__main__':
    raise SystemExit(_impl.main())
