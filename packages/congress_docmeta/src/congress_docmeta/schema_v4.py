"""The `DocMetaV4Causal` output schema, read once, and the limits code takes from it.

`docmeta_v4_causal.schema.json` is the published contract: every `docmeta_json` the release carries is valid
under it, and the decoding grammar is compiled from it. A limit is written there and nowhere else; modules
import it from here instead of restating the number. Stdlib only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "docmeta_v4_causal.schema.json"
SCHEMA_V4_STR: str = SCHEMA_PATH.read_text(encoding="utf-8")
SCHEMA_OBJ: dict[str, Any] = json.loads(SCHEMA_V4_STR)

# `maxItems` of every capped top-level array (`personas`, `refs`, `topics`, ...).
ARRAY_MAX_ITEMS: dict[str, int] = {
    k: int(p["maxItems"]) for k, p in SCHEMA_OBJ["properties"].items() if isinstance(p, dict) and "maxItems" in p
}

# The most people one record lists. Rules that add people stop here, and the canonicalizers cut here.
MAX_PERSONAS: int = ARRAY_MAX_ITEMS["personas"]

# Decode budget for one answer, in output tokens (pass 1 and the pass-2 teacher).
MAX_OUTPUT_TOKENS: int = 768

__all__ = [
    "ARRAY_MAX_ITEMS",
    "MAX_OUTPUT_TOKENS",
    "MAX_PERSONAS",
    "SCHEMA_OBJ",
    "SCHEMA_PATH",
    "SCHEMA_V4_STR",
]
