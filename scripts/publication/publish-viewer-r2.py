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
import gc
import types
import viewer_publication.publish_viewer_r2 as _impl


class _ShimModule(types.ModuleType):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if hasattr(_impl, name):
            setattr(_impl, name, value)


for _obj in gc.get_referrers(globals()):
    if isinstance(_obj, types.ModuleType) and _obj.__dict__ is globals():
        _obj.__class__ = _ShimModule


if __name__ == '__main__':
    from viewer_publication.publication_cli import main
    raise SystemExit(main(_impl))
