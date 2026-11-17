"""Gold sets for DocMeta: where they live, how a gold row is turned into what the sweep would feed the model,
the held-out split, and the tokenized training pairs.

Moved from fast-gemma4 `scripts/train_lora_v64.py` (11dcf14, then 8edf64b's label repair), which keeps only the LoRA loop, fuse and pack.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import random
import re
from typing import Any

from .compact_wire_v6 import SYS_DOCMETA_V6_COMPACT, build_prompt_v6_compact, encode_v4_to_compact_v6

DEFAULT_ARCHIVE_DIR = Path("/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/docmeta-v6-20261116")
DEFAULT_GOLD_JSONL = DEFAULT_ARCHIVE_DIR / "lookups_and_gold" / "train_v6_4_complete_ssot_gold.jsonl"
DEFAULT_VAL48_JSON = DEFAULT_ARCHIVE_DIR / "lookups_and_gold" / "eval_val48_v4_gold.json"
DEFAULT_DOCS8_JSON = DEFAULT_ARCHIVE_DIR / "lookups_and_gold" / "eval_docs8_v4_gold.json"
DEFAULT_QUEUE_PARQUET = DEFAULT_ARCHIVE_DIR / "parquets_v6_2" / "llm_queue_v6_2.parquet"

_PROMPT_PARSE_RE = re.compile(
    r"Advisory known metadata:\s*(?P<known>[^\n]*)\nFilename:\s*(?P<filename>[^\n]*)\nText:\n(?P<text>.*)\Z",
    re.DOTALL,
)
_WS_COLLAPSE_RE = re.compile(r"\s+")


def _norm_ws(text: str) -> str:
    return _WS_COLLAPSE_RE.sub(" ", (text or "")).strip().lower()


def head_tail_window_chars(text: str, max_chars: int, head_ratio: float = 0.72) -> str:
    if len(text) <= max_chars:
        return text
    h = int(max_chars * head_ratio)
    t = max(0, max_chars - h - 5)
    return text[:h] + "\n...\n" + (text[-t:] if t > 0 else "")


def load_blind_keys(blind_jsons: tuple[Path, ...]) -> dict[str, set[Any]]:
    """Leak keys for the blind sets: body hash, 600-char head, and (filename, 200-char head).

    A whole-text hash alone misses a doc re-windowed under a different slice. Shorter heads and bare filenames
    over-match: GPO cover boilerplate shares 200 chars and `documentsingle.aspx` names many pages.
    """
    keys: dict[str, set[Any]] = {"body_sha": set(), "head600": set(), "fn_head200": set()}
    for bp in blind_jsons:
        if not bp.is_file():
            continue
        for r in json.loads(bp.read_text(encoding="utf-8")):
            norm = _norm_ws(str(r.get("text") or ""))
            if r.get("body_sha"):
                keys["body_sha"].add(str(r["body_sha"]))
            if len(norm) >= 40:
                keys["head600"].add(norm[:600])
                keys["fn_head200"].add((str(r.get("filename") or "").strip(), norm[:200]))
    return keys


def load_queue_rows(queue_parquet: Path, keys: set[str], key_col: str = "link_key_hex") -> dict[str, dict[str, Any]]:
    """`key -> llm_queue row` for the docs the production sweep will actually decode."""
    if not queue_parquet.is_file() or not keys:
        return {}
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.dataset as pads

    tbl = pads.dataset(str(queue_parquet)).to_table(filter=pc.field(key_col).isin(pa.array(sorted(keys))))
    return {str(r[key_col]): r for r in tbl.to_pylist()}


def parse_gold_rows(
    gold_jsonl: Path,
    blind_jsons: tuple[Path, ...],
    queue_parquet: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Gold rows as the sweep presents them: queue `known`/`filename`/`text` when the doc is in the queue.

    Personas named in a fixed form are restored by rules R4-R6 (see the comment at the call).
    The reviewer's own text window is kept as `alt_text` (a second view of the same labels). Rows that share a
    body hash, filename, or 200-char head with a blind eval doc are dropped.
    """
    from .parquet_runner_v6 import _build_precomputed_context_from_queue_row
    from .pythonic_v5 import SCHEMA_OBJ
    from .relational_rules_v6 import add_text_grounded_personas_v6

    blind = load_blind_keys(blind_jsons)
    raw_rows = [json.loads(line) for line in gold_jsonl.open("r", encoding="utf-8") if line.strip()]
    queue = load_queue_rows(
        queue_parquet if queue_parquet is not None else DEFAULT_QUEUE_PARQUET,
        {str(r.get("link_key_hex") or "") for r in raw_rows} - {""},
    )

    parsed_rows: list[dict[str, Any]] = []
    stats = {"skipped_blind_eval_overlap": 0, "queue_context_rows": 0, "text_grounded_personas_added": 0}
    for raw in raw_rows:
        u = raw["messages"][0]["content"]
        gold_v4 = json.loads(raw["messages"][-1]["content"])
        m = _PROMPT_PARSE_RE.search(u)
        known, fn, gold_txt = (
            (m.group("known").strip(), m.group("filename").strip(), m.group("text") or "") if m else ("<NONE>", "", u)
        )
        q_row = queue.get(str(raw.get("link_key_hex") or ""))
        if q_row is not None:
            known, _, fn, text, _ = _build_precomputed_context_from_queue_row(q_row)
        else:
            text = gold_txt

        norms = [_norm_ws(t) for t in (text, gold_txt)]
        if (
            str(raw.get("saved_body_hex") or "") in blind["body_sha"]
            or any(n[:600] in blind["head600"] or (fn, n[:200]) in blind["fn_head200"] for n in norms)
        ):
            stats["skipped_blind_eval_overlap"] += 1
            continue
        stats["queue_context_rows"] += int(q_row is not None)

        # Rules R4-R6 restore one listing convention across gold batches: the chair / ranking member a witness
        # addresses (listed in 28% of cluster-gold witness statements, 92-100% of re-hydrated V4 and blind gold),
        # a bill's sponsor line, and a letter's addressees. Additive only: nothing a reviewer wrote is changed.
        if gold_v4.get("status", "usable") == "usable":
            fixed = add_text_grounded_personas_v6(
                gold_v4.get("personas") or [],
                primary_kind=gold_v4.get("primary_kind"),
                text=text,
                additive_only=True,
            )
            n_before = len(gold_v4.get("personas") or [])
            if len(fixed) > n_before:
                stats["text_grounded_personas_added"] += len(fixed) - n_before
                gold_v4["personas"] = fixed
                gold_v4 = {k: gold_v4[k] for k in SCHEMA_OBJ["properties"] if k in gold_v4}  # causal key order

        st = str(gold_v4.get("status") or "usable")
        parsed_rows.append(
            {
                "known": known,
                "filename": fn,
                "text": text,
                "alt_text": gold_txt if _norm_ws(gold_txt) != _norm_ws(text) else None,
                "cls_key": str(gold_v4.get("primary_kind") or "other") if st == "usable" else f"status:{st}",
                "gold_v4": gold_v4,
                "compact_json": json.dumps(
                    encode_v4_to_compact_v6(gold_v4), separators=(",", ":"), ensure_ascii=False
                ),
                "link_key_hex": str(raw.get("link_key_hex") or ""),
                "queue_row": q_row,
            }
        )
    return parsed_rows, stats


def select_val_indices(
    parsed_rows: list[dict[str, Any]], *, val_size: int = 180, seed: int = 20261117
) -> tuple[set[int], random.Random]:
    """Class-stratified held-out split; returns the indices and the RNG (reused for augmentation draws)."""
    rng = random.Random(seed)
    by_cls: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(parsed_rows):
        by_cls[r["cls_key"]].append(i)
    val_indices: set[int] = set()
    frac = float(val_size) / max(len(parsed_rows), 1)
    for cls_k in sorted(by_cls):
        idxs = list(by_cls[cls_k])
        rng.shuffle(idxs)
        n_take = max(1, round(len(idxs) * frac)) if len(idxs) >= 4 else (1 if len(idxs) >= 2 else 0)
        val_indices.update(idxs[:n_take])
    return val_indices, rng


def load_and_prepare_v64_splits(
    gold_jsonl: Path,
    val48_json: Path,
    docs8_json: Path,
    tok: Any,
    *,
    val_size: int = 180,
    max_seq_len: int = 3584,
    rare_oversample_max_count: int = 30,
    seed: int = 20261117,
) -> tuple[list[tuple[list[int], int]], list[tuple[list[int], int]], dict[str, Any]]:
    """Build zero-leakage C2+C4 `(full_ids, prompt_len)` train & valid datasets."""
    parsed_rows, p_stats = parse_gold_rows(gold_jsonl, (val48_json, docs8_json))
    val_indices, rng = select_val_indices(parsed_rows, val_size=val_size, seed=seed)
    n_total = len(parsed_rows)
    cls_train_counts = Counter(parsed_rows[i]["cls_key"] for i in range(n_total) if i not in val_indices)

    def _encode_pair(known: str, fn: str, text_body: str, ans_json: str) -> tuple[list[int], int]:
        f_ids: list[int] = []
        p_ids: list[int] = []
        for char_cap in (None, 8200, 6400, 4800, 3400):
            eff_txt = text_body if char_cap is None else head_tail_window_chars(text_body, char_cap, 0.72)
            u_str = build_prompt_v6_compact(known, fn, eff_txt)
            msgs = [{"role": "user", "content": u_str}, {"role": "assistant", "content": ans_json}]
            p_str = tok.apply_chat_template([msgs[0]], tokenize=False, add_generation_prompt=True)
            f_str = tok.apply_chat_template(msgs, tokenize=False)
            p_ids = list(tok.encode(p_str, add_special_tokens=False))
            f_ids = list(tok.encode(f_str, add_special_tokens=False))
            while len(f_ids) > len(p_ids) and f_ids[-1] != 106 and tok.decode([f_ids[-1]]).strip() == "":
                f_ids.pop()
            if f_ids[: len(p_ids)] != p_ids:
                raise RuntimeError("Chat template prefix mismatch in C2+C4 tokenizer!")
            if len(f_ids) <= max_seq_len:
                return f_ids, len(p_ids)
        keep_p = max_seq_len - (len(f_ids) - len(p_ids)) - 4
        return p_ids[:keep_p] + f_ids[len(p_ids) :], keep_p

    train_items: list[tuple[list[int], int]] = []
    val_items: list[tuple[list[int], int]] = []
    out_tok_lens: list[int] = []
    seq_lens: list[int] = []
    rare_boosted = 0

    for i, r in enumerate(parsed_rows):
        pair = _encode_pair(r["known"], r["filename"], r["text"], r["compact_json"])
        out_tok_lens.append(len(pair[0]) - pair[1])
        if i in val_indices:
            val_items.append(pair)
            continue
        train_items.append(pair)
        seq_lens.append(len(pair[0]))
        # Rare tail kinds and non-usable statuses get a second view: the reviewer's own window when it differs
        # from the sweep's, else the same text with whitespace collapsed.
        if cls_train_counts[r["cls_key"]] < rare_oversample_max_count:
            alt_txt = r["alt_text"] or _WS_COLLAPSE_RE.sub(" ", r["text"]).strip()
            alt_pair = _encode_pair(r["known"], r["filename"], alt_txt, r["compact_json"])
            train_items.append(alt_pair)
            seq_lens.append(len(alt_pair[0]))
            rare_boosted += 1

    seq_sorted = sorted(seq_lens)
    stats = {
        "raw_gold_docs": n_total,
        **p_stats,
        "train_docs_base": n_total - len(val_indices),
        "rare_tail_oversampled": rare_boosted,
        "train_items_total": len(train_items),
        "valid_items": len(val_items),
        "sys_prompt_tokens": len(tok.encode(SYS_DOCMETA_V6_COMPACT, add_special_tokens=False)),
        "mean_compact_out_tokens": round(sum(out_tok_lens) / max(len(out_tok_lens), 1), 1),
        "train_seq_tokens_mean_p50_p90_max": [
            round(sum(seq_lens) / max(len(seq_lens), 1)),
            seq_sorted[len(seq_sorted) // 2],
            seq_sorted[int(len(seq_sorted) * 0.9)],
            seq_sorted[-1],
        ],
        "train_tokens_total": sum(seq_lens),
    }
    return train_items, val_items, stats
