"""`python -m congress_docmeta.cli docmeta-sweep INPUT OUTPUT`: run the DocMeta sweep over a queue Parquet.

Moved from fast-gemma4's `gemma4 docmeta-sweep` (11dcf14) with the same flags. The engine is fast-gemma4's and is
imported when the command runs.
"""

from __future__ import annotations

import argparse
import json


def _cmd_docmeta_sweep(args: argparse.Namespace) -> int:
    from fast_gemma4.engine import FastGemma4Engine

    from .parquet_runner_v6 import run_docmeta_parquet_sweep

    ring_raw = str(getattr(args, "use_ane_ring", "auto")).strip().lower()
    use_ane_ring: bool | str = True if ring_raw == "true" else (False if ring_raw == "false" else "auto")
    eng = FastGemma4Engine(
        home=args.home,
        model_dir=getattr(args, "model_dir", None),
        default_mode=getattr(args, "mode", "auto"),
        ane_variant=getattr(args, "ane_variant", "w8"),
        lm_head_mode=getattr(args, "lm_head_mode", "q4"),
        mlp_dtype=getattr(args, "mlp_dtype", "bfloat16"),
        kv_i8=not getattr(args, "no_kv_i8", False),
        warmup=not getattr(args, "no_warmup", False),
        warmup_ane=bool(getattr(args, "mode", "auto") == "hetero" or use_ane_ring is not False),
    )
    try:
        summary = run_docmeta_parquet_sweep(
            eng,
            args.input,
            args.output,
            chunk_rows=args.chunk_rows,
            b_slots=args.b_slots,
            refill_min=args.refill_min,
            max_tokens=args.max_tokens,
            use_ane_ring=use_ane_ring,
            resume=args.resume,
            wire_format=args.wire_format,
            embed_ane=args.embed_ane,
            grammar_router=args.grammar_router,
            atomic_verifier=args.atomic_verifier,
            repair_persona_roles=args.repair_persona_roles,
            escalate_gpt_oss=args.escalate_gpt_oss,
            gpt_oss_model_dir=args.gpt_oss_model_dir,
            gpt_oss_batch_size=args.gpt_oss_batch_size,
            gpt_oss_k=args.gpt_oss_k,
        )
        print(
            json.dumps(
                {
                    "docs_processed": summary.docs_processed,
                    "docs_skipped_resume": summary.docs_skipped_resume,
                    "llm_decoded_docs": summary.llm_decoded_docs,
                    "triage_short_circuited_docs": summary.triage_short_circuited_docs,
                    "strict_v4_valid_docs": summary.strict_v4_valid_docs,
                    "anomaly_flagged_docs": summary.anomaly_flagged_docs,
                    "pass2_escalated_docs": summary.pass2_escalated_docs,
                    "pass2_accepted_docs": summary.pass2_accepted_docs,
                    "ane_embedded_docs": summary.ane_embedded_docs,
                    "chunks_written": summary.chunks_written,
                    "prompt_tokens": summary.prompt_tokens,
                    "completion_tokens": summary.completion_tokens,
                    "elapsed_sec": round(summary.elapsed_sec, 3),
                    "docs_per_sec": round(summary.docs_per_sec, 2),
                    "decode_tok_s": round(summary.decode_tok_s, 1),
                    "output_path": str(summary.output_path),
                    "parts_dir": str(summary.parts_dir),
                },
                indent=2,
            )
        )
    finally:
        eng.close()
    return 0


def _add_model_args(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("--model-dir", default=None, help="Override local HuggingFace/fused checkpoint directory")
    subparser.add_argument("--no-kv-i8", action="store_true", help="Disable INT8 rolling KV cache compression")
    subparser.add_argument("--lm-head-mode", choices=("q4", "bf16_mpp"), default="q4")
    subparser.add_argument("--mlp-dtype", choices=("bfloat16", "quantized"), default="bfloat16")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="congress_docmeta", description="DocMeta sweep over the fast-gemma4 engine")
    p.add_argument("--home", default=None, help="Override FAST_GEMMA4_HOME directory")
    sub = p.add_subparsers(dest="cmd", required=True)

    dm_p = sub.add_parser(
        "docmeta-sweep",
        help="Stream DocMeta V6.2 Parquet queue with atomic link_key_hex checkpointing, ANE embeddings, and Pass-2 escalation",
    )
    _add_model_args(dm_p)
    dm_p.add_argument("input", help="Input llm_queue_v6_2.parquet path, directory, or glob")
    dm_p.add_argument("output", help="Output .parquet file or shard directory")
    dm_p.add_argument("--chunk-rows", type=int, default=4096)
    dm_p.add_argument("--b-slots", type=int, default=256)
    dm_p.add_argument("--refill-min", type=int, default=32)
    dm_p.add_argument("--max-tokens", type=int, default=768)
    dm_p.add_argument("--mode", choices=("auto", "gpu", "hetero"), default="auto")
    dm_p.add_argument("--ane-variant", choices=("fp16", "w8"), default="w8")
    dm_p.add_argument("--use-ane-ring", choices=("auto", "true", "false"), default="auto")
    dm_p.add_argument(
        "--wire-format",
        choices=("auto", "v4", "compact"),
        default="auto",
        help="Pass-1 prompt/schema wire format ('auto' inspects checkpoint docmeta_wire_config.json)",
    )
    dm_p.add_argument(
        "--embed-ane",
        choices=("none", "bge-small", "embeddinggemma-2"),
        default="none",
        help="Co-execute pure-ANE search embeddings on background thread during GPU decode (Proposal B4)",
    )
    dm_p.add_argument(
        "--grammar-router",
        choices=("none", "fast", "ane"),
        default="none",
        help="Pre-decode calibrated grammar router on open-kind rows ('fast' linear CPU or 'ane' Laya-Typed ANE)",
    )
    dm_p.add_argument(
        "--atomic-verifier",
        choices=("none", "laya-ane", "kev-0.8b", "both"),
        default="none",
        help="Post-LLM atomic Noul output verifier ('laya-ane', 'kev-0.8b', or 'both')",
    )
    dm_p.add_argument(
        "--repair-persona-roles",
        action="store_true",
        help="Auto-repair grounded human personas flagged with role defects via Laya-Typed ANE Choice(16)",
    )
    dm_p.add_argument("--escalate-gpt-oss", action="store_true", help="Escalate anomaly-flagged docs to fast-gpt-oss Pass-2")
    dm_p.add_argument("--gpt-oss-model-dir", default=None)
    dm_p.add_argument("--gpt-oss-batch-size", type=int, default=8)
    dm_p.add_argument("--gpt-oss-k", type=int, default=1)
    dm_p.add_argument("--resume", action="store_true")
    dm_p.add_argument("--no-warmup", action="store_true")
    dm_p.set_defaults(func=_cmd_docmeta_sweep)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
