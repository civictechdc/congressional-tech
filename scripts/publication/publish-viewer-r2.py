#!/usr/bin/env python3
"""Publish the selected catalog to R2 without writing any archive/catalog keys."""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PKG = _ROOT / 'packages/viewer_publication/src'
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from viewer_publication.publish_viewer_r2 import *
import viewer_publication.publish_viewer_r2 as _impl

if __name__ == '__main__':
    sys.path.insert(0, str(_ROOT / 'scripts'))
    sys.path.insert(0, str(_ROOT / 'scripts/publication'))
    from publication_cli import main
    raise SystemExit(main(_impl))
