"""`python -m congress_docmeta.cli docmeta-sweep INPUT OUTPUT`: run the DocMeta sweep over a queue Parquet.

Moved from fast-gemma4's `gemma4 docmeta-sweep` (11dcf14) with the same flags. The engine is fast-gemma4's and is
imported when the command runs.
"""

from __future__ import annotations

import argparse
import json

from .schema_v4 import MAX_OUTPUT_TOKENS


def _run_retry_escalated_with_limits(
    queue_path: str,
    pass1_results_path: str,
    output_path: str,
    args: argparse.Namespace,
) -> dict[str, object]:
    from .parquet_runner_v6 import run_offline_escalation_queue_v6
    from .silicon_runtime_v6 import (
        mlx_limits_scope,
        mlx_wired_limit_scope,
        resolve_default_mlx_limits,
        run_silicon_preflight,
    )

    preflight = run_silicon_preflight(escalate_gpt_oss=True, require_r8_deps=True, once=True)
    host_ram_gb = int(preflight.get("mem_gb") or 0)
    def_mem_gb, def_cache_gb = resolve_default_mlx_limits(host_ram_gb)
    raw_mem = getattr(args, "memory_limit_gb", None)
    raw_cache = getattr(args, "cache_limit_gb", None)
    mem_limit_gb = float(def_mem_gb if raw_mem is None else raw_mem)
    cache_limit_gb = float(def_cache_gb if raw_cache is None else raw_cache)

    with (
        mlx_limits_scope(memory_limit_gb=mem_limit_gb, cache_limit_gb=cache_limit_gb) as mlx_limits,
        mlx_wired_limit_scope(),
    ):
        receipt = run_offline_escalation_queue_v6(
            queue_path,
            pass1_results_path,
            output_path,
            gpt_oss_model_dir=getattr(args, "gpt_oss_model_dir", None),
            gpt_oss_batch_size=int(getattr(args, "gpt_oss_batch_size", 8)),
            gpt_oss_k=int(getattr(args, "gpt_oss_k", 1)),
            max_tokens=int(getattr(args, "max_tokens", MAX_OUTPUT_TOKENS)),
        )
    receipt["mlx_limits"] = mlx_limits
    return receipt


def _cmd_retry_escalated(args: argparse.Namespace) -> int:
    receipt = _run_retry_escalated_with_limits(
        args.escalation_queue,
        args.pass1_results,
        args.output,
        args,
    )
    print(json.dumps(receipt, indent=2))
    return 0


def _cmd_docmeta_sweep(args: argparse.Namespace) -> int:
    if getattr(args, "retry_escalated", None):
        receipt = _run_retry_escalated_with_limits(
            str(args.retry_escalated),
            args.input,
            args.output,
            args,
        )
        print(json.dumps(receipt, indent=2))
        return 0

    from fast_gemma4.engine import FastGemma4Engine

    from .parquet_runner_v6 import run_docmeta_parquet_sweep
    from .silicon_runtime_v6 import (
        mlx_limits_scope,
        mlx_wired_limit_scope,
        resolve_default_docmeta_batch_size,
        resolve_default_mlx_limits,
        run_silicon_preflight,
    )

    preflight = run_silicon_preflight(
        escalate_gpt_oss=bool(getattr(args, "escalate_gpt_oss", False)),
        require_r8_deps=True,
        once=True,
    )
    host_ram_gb = int(preflight.get("mem_gb") or 0)
    def_mem_gb, def_cache_gb = resolve_default_mlx_limits(host_ram_gb)
    def_b_slots = resolve_default_docmeta_batch_size(host_ram_gb)

    ring_raw = str(getattr(args, "use_ane_ring", "auto")).strip().lower()
    use_ane_ring: bool | str = True if ring_raw == "true" else (False if ring_raw == "false" else "auto")
    tp_raw = str(getattr(args, "two_phase_pass2", "auto")).strip().lower()
    two_phase_pass2: bool | str = True if tp_raw == "true" else (False if tp_raw == "false" else "auto")
    raw_mem = getattr(args, "memory_limit_gb", None)
    raw_cache = getattr(args, "cache_limit_gb", None)
    raw_b_slots = getattr(args, "b_slots", None)
    mem_limit_gb = float(def_mem_gb if raw_mem is None else raw_mem)
    cache_limit_gb = float(def_cache_gb if raw_cache is None else raw_cache)
    eff_b_slots = int(def_b_slots if raw_b_slots is None else raw_b_slots)

    with (
        mlx_limits_scope(memory_limit_gb=mem_limit_gb, cache_limit_gb=cache_limit_gb) as mlx_limits,
        mlx_wired_limit_scope(),
    ):
        eng = FastGemma4Engine(
            home=args.home,
            model_dir=getattr(args, "model_dir", None),
            default_mode=getattr(args, "mode", "auto"),
            ane_variant=getattr(args, "ane_variant", "fp16"),
            ane_ring_variant=getattr(args, "ane_variant", "fp16"),
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
                b_slots=eff_b_slots,
                refill_min=args.refill_min,
                max_tokens=args.max_tokens,
                use_ane_ring=use_ane_ring,
                resume=args.resume,
                wire_format=args.wire_format,
                embed_ane=args.embed_ane,
                grammar_router=args.grammar_router,
                atomic_verifier=args.atomic_verifier,
                kev_batch_docs=getattr(args, "kev_batch_docs", 8),
                repair_persona_roles=args.repair_persona_roles,
                escalate_gpt_oss=args.escalate_gpt_oss,
                gpt_oss_model_dir=args.gpt_oss_model_dir,
                gpt_oss_batch_size=args.gpt_oss_batch_size,
                gpt_oss_k=args.gpt_oss_k,
                two_phase_pass2=two_phase_pass2,
                bm25_multicrop=bool(getattr(args, "bm25_multicrop", False)),
                use_telemetry=getattr(args, "telemetry", "auto"),
                use_extractconf=not bool(getattr(args, "no_extractconf", False)),
                escalation_queue_out=getattr(args, "escalation_queue_out", None),
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
                        "extractconf_flagged_docs": summary.extractconf_flagged_docs,
                        "telemetry_wrapped_chunks": summary.telemetry_wrapped_chunks,
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
                        "escalation_queue_path": (
                            str(getattr(summary, "escalation_queue_path", None))
                            if getattr(summary, "escalation_queue_path", None)
                            else None
                        ),
                        "escalation_queued_docs": getattr(summary, "escalation_queued_docs", 0),
                        "b_slots": eff_b_slots,
                        "mlx_limits": mlx_limits,
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
    dm_p.add_argument(
        "--b-slots",
        "--batch-size",
        dest="b_slots",
        type=int,
        default=None,
        help="Rolling slot/batch size (default: auto: 128 on <=24 GiB Macs, 256 otherwise)",
    )
    dm_p.add_argument("--refill-min", type=int, default=32)
    dm_p.add_argument("--max-tokens", type=int, default=MAX_OUTPUT_TOKENS)
    dm_p.add_argument("--mode", choices=("auto", "gpu", "hetero"), default="auto")
    dm_p.add_argument("--ane-variant", choices=("fp16", "w8"), default="fp16")
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
        default="fast",
        help="Pre-decode calibrated grammar router on open-kind rows ('fast' linear CPU + CROQ a=0.05, 'ane', or 'none')",
    )
    dm_p.add_argument(
        "--atomic-verifier",
        choices=("none", "laya-ane", "kev-0.8b", "both"),
        default="none",
        help="Optional post-LLM atomic Noul output verifier ('none' default, 'laya-ane', 'kev-0.8b', or 'both')",
    )
    dm_p.add_argument(
        "--telemetry",
        choices=("auto", "on", "off"),
        default="auto",
        help="Capture pre-mask grammar uncertainty telemetry for ExtractConf ('auto' enables when supported)",
    )
    dm_p.add_argument(
        "--no-extractconf",
        action="store_true",
        help="Disable calibrated ExtractConf per-field defect risk scoring sidecar/column",
    )
    dm_p.add_argument(
        "--bm25-multicrop",
        action="store_true",
        help="Opt-in CPU BM25 multi-crop window packing for >3000-char Pass-1 prompts (default: full uncut text)",
    )
    dm_p.add_argument(
        "--kev-batch-docs",
        type=int,
        default=8,
        help="Cross-document batch size for Stage-2 Kev-0.8B MLX validator (default: 8)",
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
    dm_p.add_argument(
        "--two-phase-pass2",
        choices=("auto", "true", "false"),
        default="auto",
        help="Unload Pass-1 Gemma-4 before loading GPT-OSS-20B Pass-2 ('auto' enables on <=48 GiB Macs)",
    )
    dm_p.add_argument("--resume", action="store_true")
    dm_p.add_argument("--no-warmup", action="store_true")
    dm_p.add_argument(
        "--memory-limit-gb",
        type=float,
        default=None,
        help="MLX active memory cap in GiB (default: auto: min(20.0, 0.8*RAM) on <=24 GiB Macs, 24.0 otherwise; <=0 disables)",
    )
    dm_p.add_argument(
        "--cache-limit-gb",
        type=float,
        default=None,
        help="MLX free-buffer cache cap in GiB (default: auto: 1.5 on <=24 GiB Macs, 2.0 otherwise; <0 disables, 0 turns caching off)",
    )
    dm_p.add_argument(
        "--escalation-queue-out",
        default=None,
        help="Optional JSONL path exporting flagged/ExtractConf rows for standalone single-model Pass-2 escalation",
    )
    dm_p.add_argument(
        "--retry-escalated",
        default=None,
        help="Run standalone single-model GPT-OSS-20B Pass-2 over this JSONL queue using INPUT as Pass-1 Parquet and OUTPUT as updated Parquet",
    )
    dm_p.set_defaults(func=_cmd_docmeta_sweep)

    re_p = sub.add_parser(
        "retry-escalated",
        help="Run single-model GPT-OSS-20B Pass-2 offline over an exported escalation JSONL queue",
    )
    re_p.add_argument("escalation_queue", help="Input JSONL escalation queue produced by --escalation-queue-out")
    re_p.add_argument("pass1_results", help="Pass-1 results .parquet file to update with accepted Pass-2 repairs")
    re_p.add_argument("output", help="Output merged .parquet file")
    re_p.add_argument("--gpt-oss-model-dir", default=None)
    re_p.add_argument("--gpt-oss-batch-size", type=int, default=8)
    re_p.add_argument("--gpt-oss-k", type=int, default=1)
    re_p.add_argument("--max-tokens", type=int, default=MAX_OUTPUT_TOKENS)
    re_p.add_argument("--memory-limit-gb", type=float, default=None)
    re_p.add_argument("--cache-limit-gb", type=float, default=None)
    re_p.set_defaults(func=_cmd_retry_escalated)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
