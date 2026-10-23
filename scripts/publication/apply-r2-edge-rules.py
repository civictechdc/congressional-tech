#!/usr/bin/env python3
"""Plan, apply, and verify Cloudflare R2 Custom Domain, CORS, WAF, and Response Header Transform Rules."""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PKG = _ROOT / 'packages/viewer_publication/src'
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from viewer_publication.apply_r2_edge_rules import *
import viewer_publication.apply_r2_edge_rules as _impl

if __name__ == '__main__':
    raise SystemExit(_impl.main())
