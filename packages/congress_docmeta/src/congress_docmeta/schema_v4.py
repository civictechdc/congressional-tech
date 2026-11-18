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

# The most people one record lists. Rules that add people stop here, and the canonicalizers cut here. 26 since
# 2026-11-18 (ct-bult, was 10): hearing transcripts print a witness list, and 30 of 324 labeled transcripts list
# 11 to 26 witnesses. A roster dump is guarded by role, not by this number (anomaly_router_v6.LIST_ROLES_V6).
MAX_PERSONAS: int = ARRAY_MAX_ITEMS["personas"]

# Decode budget for one answer, in output tokens (pass 1 and the pass-2 teacher). Measured on the 3,449 training
# labels with the Gemma-4 tokenizer (2026-11-18): an answer is about 170 tokens besides its people (99th
# percentile 328) and a person about 41 (median 33); the largest real 25-26-person answer is 926. 328 + 26 x 41
# = 1,394, rounded up to a multiple of 256. The engine sizes every decode slot's full-attention cache to the
# batch's longest prompt suffix + this + 64 (fast-gemma4 `speculative.py`), so a larger budget costs memory on
# every document, not only long ones. Was 768 while the cap was 10.
MAX_OUTPUT_TOKENS: int = 1536

__all__ = [
    "ARRAY_MAX_ITEMS",
    "MAX_OUTPUT_TOKENS",
    "MAX_PERSONAS",
    "SCHEMA_OBJ",
    "SCHEMA_PATH",
    "SCHEMA_V4_STR",
]
