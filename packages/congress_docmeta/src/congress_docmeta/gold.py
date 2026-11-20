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
from .relational_rules_v6 import resolve_docmeta_v6_data_dir

DEFAULT_ARCHIVE_DIR = resolve_docmeta_v6_data_dir()
DEFAULT_GOLD_JSONL = DEFAULT_ARCHIVE_DIR / "lookups_and_gold" / "train_v6_4_complete_ssot_gold.jsonl"
DEFAULT_VAL48_JSON = DEFAULT_ARCHIVE_DIR / "lookups_and_gold" / "eval_val48_v4_gold.json"
DEFAULT_DOCS8_JSON = DEFAULT_ARCHIVE_DIR / "lookups_and_gold" / "eval_docs8_v4_gold.json"
DEFAULT_QUEUE_PARQUET = DEFAULT_ARCHIVE_DIR / "parquets_v6_2" / "llm_queue_v6_2.parquet"
# The 183 held-out docs, by link key. The seeded draw below depends on every row's class, so one repaired label
# would swap held-out docs for docs earlier checkpoints trained on; membership is read from this file instead.
DEFAULT_HELDOUT_KEYS_JSON = (
    DEFAULT_ARCHIVE_DIR.parent / "docmeta-v65-raretypes-20261118" / "lookups_and_gold" / "heldout_v6_4_183_link_keys.json"
)

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
    *,
    augment_personas: bool = True,
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
        raw_gold_v4 = json.loads(raw["messages"][-1]["content"])
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

        # Rules R4-R6 restore one listing convention across training gold batches; held-out evaluation sets pass
        # `augment_personas=False` (or score `raw_gold_v4`) so a rule never grades its own additions (`ct-2cig`).
        if augment_personas and gold_v4.get("status", "usable") == "usable":
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
                "raw_gold_v4": raw_gold_v4,
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
    parsed_rows: list[dict[str, Any]],
    *,
    val_size: int = 180,
    seed: int = 20261117,
    heldout_keys_json: Path | None = DEFAULT_HELDOUT_KEYS_JSON,
) -> tuple[set[int], random.Random]:
    """Held-out split; returns the indices and the RNG (reused for augmentation draws).

    Membership comes from `heldout_keys_json` when that file exists (rows are matched by link key, so label
    repairs and dropped rows cannot move a doc across the split). Without it, a class-stratified seeded draw.
    """
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
    if heldout_keys_json is not None and heldout_keys_json.is_file():
        keys = set(json.loads(heldout_keys_json.read_text(encoding="utf-8"))["link_key_hex"])
        val_indices = {i for i, r in enumerate(parsed_rows) if r["link_key_hex"] in keys}
        if not val_indices:
            raise RuntimeError(f"no row matches the held-out keys in {heldout_keys_json}")
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
    train_docs: int = 0,
    class_cap: int = 0,
    extra_train_jsonl: Path | None = None,
) -> tuple[list[tuple[list[int], int]], list[tuple[list[int], int]], dict[str, Any]]:
    """Build zero-leakage C2+C4 `(full_ids, prompt_len)` train & valid datasets.

    `train_docs > 0` keeps a class-stratified sample of the training docs (every class with at least one doc
    keeps one) and drops the rare-class second views, so short config-sweep runs share one small, fixed set.
    `class_cap > 0` keeps a fixed random `class_cap` training docs of any class that has more, so the largest
    classes (witness statements and biographies are 40% of the set) stop pulling the kind decision.
    `extra_train_jsonl` rows are appended after the held-out split is drawn, so they only ever train and the
    held-out docs stay the same ones.
    """
    parsed_rows, p_stats = parse_gold_rows(gold_jsonl, (val48_json, docs8_json))
    val_indices, rng = select_val_indices(parsed_rows, val_size=val_size, seed=seed)
    if extra_train_jsonl is not None:
        extra_rows, e_stats = parse_gold_rows(extra_train_jsonl, (val48_json, docs8_json))
        seen = {r["link_key_hex"] for r in parsed_rows}
        extra_rows = [r for r in extra_rows if r["link_key_hex"] not in seen]
        parsed_rows = parsed_rows + extra_rows
        p_stats = {**p_stats, "extra_train_docs": len(extra_rows), "extra_skipped_blind_eval_overlap": e_stats["skipped_blind_eval_overlap"]}
    n_total = len(parsed_rows)
    skip_train: set[int] = set()
    if train_docs > 0:
        sub_rng = random.Random(seed + 1)
        by_cls_train: dict[str, list[int]] = defaultdict(list)
        for i, r in enumerate(parsed_rows):
            if i not in val_indices:
                by_cls_train[r["cls_key"]].append(i)
        frac_keep = train_docs / max(1, sum(len(v) for v in by_cls_train.values()))
        keep: set[int] = set()
        for cls_k in sorted(by_cls_train):
            idxs = list(by_cls_train[cls_k])
            sub_rng.shuffle(idxs)
            keep.update(idxs[: max(1, round(len(idxs) * frac_keep))])
        skip_train = {i for v in by_cls_train.values() for i in v} - keep
        rare_oversample_max_count = 0
    if class_cap > 0:
        cap_rng = random.Random(seed + 2)
        by_cls_kept: dict[str, list[int]] = defaultdict(list)
        for i, r in enumerate(parsed_rows):
            if i not in val_indices and i not in skip_train:
                by_cls_kept[r["cls_key"]].append(i)
        for cls_k in sorted(by_cls_kept):
            idxs = by_cls_kept[cls_k]
            if len(idxs) > class_cap:
                cap_rng.shuffle(idxs)
                skip_train.update(idxs[class_cap:])
    cls_train_counts = Counter(parsed_rows[i]["cls_key"] for i in range(n_total) if i not in val_indices)

    def _encode_pair(known: str, fn: str, text_body: str, ans_json: str) -> tuple[list[int], int]:
        f_ids: list[int] = []
        p_ids: list[int] = []
        for char_cap in (None, 8200, 6400, 4800, 3400):
            eff_txt = text_body if char_cap is None else head_tail_window_chars(text_body, char_cap, 0.72)
            u_str = build_prompt_v6_compact(known, fn, eff_txt)
            msgs = [{"role": "user", "content": u_str}, {"role": "assistant", "content": ans_json}]
            # enable_thinking=False: mlx-lm's template otherwise prepends a `<|think|>` system turn (7 tokens)
            # that the sweep's `format_chat(..., enable_thinking=False)` never sends.
            p_str = tok.apply_chat_template([msgs[0]], tokenize=False, add_generation_prompt=True, enable_thinking=False)
            f_str = tok.apply_chat_template(msgs, tokenize=False, enable_thinking=False)
            if "<|think|>" in p_str:
                raise RuntimeError("training prompt still carries the thinking block production never sends")
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
        if i in skip_train:
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
        "train_docs_base": n_total - len(val_indices) - len(skip_train),
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
