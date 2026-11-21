"""Environment- and checkout-aware path resolution for DocMeta V6.5 gold artifacts (`ct-2uc9`)."""

from __future__ import annotations

import os
from pathlib import Path

from ..relational_rules_v6 import _discover_main_checkout_root, resolve_docmeta_v6_data_dir

PACKAGE_DATA_DIR = Path(__file__).resolve().parent


def resolve_docmeta_v65_dir(env_override: str | None = None) -> Path:
    """Resolve `<main checkout>/.cache/archive-release/docmeta-v65-raretypes-20261118` or `DOCMETA_V65_DIR`."""
    raw = env_override if env_override is not None else os.environ.get("DOCMETA_V65_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return _discover_main_checkout_root() / ".cache" / "archive-release" / "docmeta-v65-raretypes-20261118"


def resolve_package_fallback(cache_path: Path, package_rel: str) -> Path:
    """Return `cache_path` when present on disk, else the checked-in file in `gold_v65`."""
    if cache_path.is_file():
        return cache_path
    pkg_cand = PACKAGE_DATA_DIR / package_rel
    if pkg_cand.is_file():
        return pkg_cand
    return cache_path


__all__ = [
    "PACKAGE_DATA_DIR",
    "resolve_docmeta_v6_data_dir",
    "resolve_docmeta_v65_dir",
    "resolve_package_fallback",
]
