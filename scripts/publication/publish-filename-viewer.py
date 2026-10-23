#!/usr/bin/env python3
"""Prepare native viewer output and retain shared verified-file utilities."""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PKG = _ROOT / 'packages/viewer_publication/src'
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from viewer_publication.publish_filename_viewer import *
import viewer_publication.publish_filename_viewer as _impl

if __name__ == '__main__':
    raise SystemExit('Direct viewer generation is retired; use publish-viewer-r2.py prepare with explicit native storage.')
