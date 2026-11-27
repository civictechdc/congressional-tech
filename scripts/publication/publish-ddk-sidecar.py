#!/usr/bin/env python3
"""Build, dry-run, or publish a zero-copy DDK + Iceberg v2 sidecar bound to BodyTextSSOT."""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PKG = _ROOT / 'packages/viewer_publication/src'
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from viewer_publication.archive_ddk_sidecar import *
import viewer_publication.archive_ddk_sidecar as _impl

if __name__ == '__main__':
    raise SystemExit(_impl.main())
