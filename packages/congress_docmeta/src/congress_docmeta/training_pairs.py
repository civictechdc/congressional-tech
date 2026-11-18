"""`python -m congress_docmeta.training_pairs`: write the tokenized DocMeta training pairs fast-gemma4 trains on.

This side owns the task: gold parsing, label repair, the held-out split, prompts and answers (`gold.py`). The
engine's trainer (`fast-gemma4/scripts/train_lora.py --pairs`) owns the LoRA loop, fuse and pack, and knows
nothing about DocMeta. The hand-over is two files:

  PAIRS.json                 `{"train": [[ids, prompt_len], ...], "valid": [...], "stats": {...}}`
  docmeta_wire_config.json   names the wire format the checkpoint was trained on; pass it to the trainer with
                             `--checkpoint-config` so `detect_checkpoint_wire_format` finds it in the checkpoint.

Run with a Python that has `mlx_lm` with Gemma-4 support, which supplies the base snapshot's tokenizer and chat
template (`~/.venv-vllm-metal/bin/python`, with this package on `PYTHONPATH`).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .gold import DEFAULT_DOCS8_JSON, DEFAULT_GOLD_JSONL, DEFAULT_VAL48_JSON, load_and_prepare_v64_splits

WIRE_CONFIG = {
    "wire_format": "compact_v6",
    "version": "v6_4_c2_c4_8bit_bf16mlp",
    "sys_prompt": "SYS_DOCMETA_V6_COMPACT",
    "schema": "DocMetaV6Compact",
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-snap", type=Path, required=True, help="the BF16 base snapshot the trainer will load")
    ap.add_argument("--gold-jsonl", type=Path, default=DEFAULT_GOLD_JSONL)
    ap.add_argument("--val-size", type=int, default=180)
    ap.add_argument("--max-seq-len", type=int, default=3584)
    ap.add_argument("--train-docs", type=int, default=0,
                    help="keep a class-stratified sample of this many training docs (0 = all); for config sweeps")
    ap.add_argument("--class-cap", type=int, default=0,
                    help="keep at most this many training docs per class (0 = no cap)")
    ap.add_argument("--extra-train-jsonl", type=Path, default=None,
                    help="more gold rows, used for training only (the held-out split is drawn before they are added)")
    ap.add_argument("--out", type=Path, required=True, help="PAIRS.json; docmeta_wire_config.json is written beside it")
    args = ap.parse_args(argv)

    from mlx_lm.utils import load_tokenizer

    tok = load_tokenizer(args.base_snap)
    train, valid, stats = load_and_prepare_v64_splits(
        args.gold_jsonl, DEFAULT_VAL48_JSON, DEFAULT_DOCS8_JSON, tok, val_size=args.val_size, max_seq_len=args.max_seq_len,
        train_docs=args.train_docs, class_cap=args.class_cap, extra_train_jsonl=args.extra_train_jsonl,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"stats": stats, "train": train, "valid": valid}, separators=(",", ":")), encoding="utf-8")
    wire_p = args.out.parent / "docmeta_wire_config.json"
    wire_p.write_text(json.dumps(WIRE_CONFIG, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats))
    print(f"wrote {args.out} ({len(train)} train, {len(valid)} valid) and {wire_p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
