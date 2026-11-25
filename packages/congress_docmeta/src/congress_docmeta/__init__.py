"""DocMeta V7: FRBR/ELI-DL decomposed schemas, 3-family SOTA corpus factory, and release contract."""

from __future__ import annotations

from . import v7
from .v7 import *  # noqa: F403

__all__ = ["v7", *v7.__all__]
