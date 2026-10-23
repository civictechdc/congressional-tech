#!/usr/bin/env python3
"""CLI to backfill uncompressed .pdf sibling objects in R2 or LocalStore for accepted-files.json PDFs."""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PKG = _ROOT / 'packages/viewer_publication/src'
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from viewer_publication.backfill_uncompressed_pdfs import *
import viewer_publication.backfill_uncompressed_pdfs as _impl

if __name__ == '__main__':
    raise SystemExit(_impl.main())
