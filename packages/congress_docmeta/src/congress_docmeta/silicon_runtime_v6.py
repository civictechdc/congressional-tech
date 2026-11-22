#!/usr/bin/env python3
"""Apple Silicon preflight, MLX memory lifecycle, and chat-template helpers for `congress_docmeta`.

100% Python standard library at import time (`/usr/bin/python3 -B -I -S` clean).
`mlx`, `fast_shared`, and R8 dependencies are probed or imported lazily only inside functions.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
import gc
import importlib.util
import inspect
import os
import platform
import re
import subprocess
import sys
from typing import Any

MIN_MACOS_NAX_VERSION: tuple[int, ...] = (26, 2)
MIN_MACOS_METAL4_INT_VERSION: tuple[int, ...] = (26, 4)
MIN_MACOS_ANE_CORE_FIX_VERSION: tuple[int, ...] = (27, 2, 1)
MIN_MLX_VERSION: tuple[int, ...] = (0, 32, 4)

DEFAULT_MLX_MEMORY_LIMIT_GB: float = 24.0
DEFAULT_MLX_CACHE_LIMIT_GB: float = 2.0
DEFAULT_DOCMETA_BATCH_SIZE: int = 256
_AUTO_LIMIT = object()

REQUIRED_R8_MODULES: tuple[tuple[str, str], ...] = (
    ("usaddress", "usaddress==0.5.14"),
    ("pycountry", "pycountry==26.2.16"),
    ("msgspec_schemaorg", "msgspec-schemaorg==0.2.1"),
    ("msgspec", "msgspec==0.21.1"),
    ("jsonschema", "jsonschema>=4.18,<5"),
)

_PREFLIGHT_WARNED = False


def parse_semver(raw: str | None) -> tuple[int, ...]:
    """Parse leading integer version components from strings like `'26.6'`, `'0.32.4.dev1'`."""
    if not raw:
        return ()
    nums = re.findall(r"\d+", str(raw).strip())
    return tuple(int(x) for x in nums[:4])


def _version_lt(found: tuple[int, ...], minimum: tuple[int, ...]) -> bool:
    if not found:
        return False
    n = max(len(found), len(minimum))
    lhs = found + (0,) * (n - len(found))
    rhs = minimum + (0,) * (n - len(minimum))
    return lhs < rhs


def _run_cmd_quiet(args: Sequence[str], *, timeout: float = 2.0) -> str:
    try:
        return subprocess.check_output(
            list(args),
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        ).strip()
    except Exception:
        return ""


def probe_host_memory_gb() -> int:
    """Return host unified/physical RAM in whole GiB (`0` if unavailable)."""
    mem_bytes = 0
    if platform.system() == "Darwin":
        raw = _run_cmd_quiet(["sysctl", "-n", "hw.memsize"])
        if raw.isdigit():
            mem_bytes = int(raw)
    if mem_bytes <= 0 and hasattr(os, "sysconf"):
        try:
            pages = int(os.sysconf("SC_PHYS_PAGES"))
            page_sz = int(os.sysconf("SC_PAGE_SIZE"))
            if pages > 0 and page_sz > 0:
                mem_bytes = pages * page_sz
        except (ValueError, OSError):
            pass
    return int(round(mem_bytes / (1024**3))) if mem_bytes > 0 else 0


def resolve_default_mlx_limits(host_mem_gb: int | None = None) -> tuple[float, float]:
    """Return ``(memory_limit_gb, cache_limit_gb)`` auto-sized for host unified RAM.

    On ``<= 24 GiB`` hosts (e.g. Base M5 24 GiB), cap MLX active working-set memory
    at ``min(20.0, round(0.80 * host_mem_gb, 1))`` (``19.2`` GiB, staying within the
    Metal wired ceiling) and free-buffer cache at ``1.5`` GiB to prevent swap/OOM.
    On ``> 24 GiB`` hosts (e.g. 48 GiB M4 Pro) or unknown RAM (``0``), preserve
    ``(DEFAULT_MLX_MEMORY_LIMIT_GB, DEFAULT_MLX_CACHE_LIMIT_GB)`` (``(24.0, 2.0)``).
    """
    mem = probe_host_memory_gb() if host_mem_gb is None else int(host_mem_gb)
    if 0 < mem <= 24:
        return min(20.0, round(0.80 * float(mem), 1)), 1.5
    return DEFAULT_MLX_MEMORY_LIMIT_GB, DEFAULT_MLX_CACHE_LIMIT_GB


def resolve_default_docmeta_batch_size(host_mem_gb: int | None = None) -> int:
    """Return default rolling DocMeta slot/batch budget auto-sized to host unified RAM."""
    mem = probe_host_memory_gb() if host_mem_gb is None else int(host_mem_gb)
    if 0 < mem <= 24:
        return 128
    return DEFAULT_DOCMETA_BATCH_SIZE


def check_r8_dependencies(*, strict: bool = True) -> list[str]:
    """Verify R8 postal-address and JSON-schema dependencies are importable.

    Returns the list of missing distribution specs. When ``strict=True``, raises
    ``RuntimeError`` if any required package is absent instead of letting R8
    silently drop ``work_addr`` or fail deep inside a sweep.
    """
    missing: list[str] = []
    for mod_name, pkg_spec in REQUIRED_R8_MODULES:
        try:
            spec = importlib.util.find_spec(mod_name)
        except (ImportError, ValueError):
            spec = None
        if spec is None:
            missing.append(pkg_spec)
    if missing and strict:
        joined = ", ".join(missing)
        raise RuntimeError(
            f"Missing required congress_docmeta R8/schema dependencies in {sys.executable}: {joined}. "
            "Without them rule R8 cannot extract `work_addr` or validate strict V4 schemas. "
            "Run under `../fast-silicon/.venv/bin/python` after `uv sync --extra dev --extra extract` "
            "(or install the missing packages into this environment)."
        )
    return missing


def probe_silicon_environment() -> dict[str, Any]:
    """Collect host OS, chip, unified RAM, MLX version, env flags, and R8 dependency status."""
    is_darwin = platform.system() == "Darwin"
    os_version = _run_cmd_quiet(["sw_vers", "-productVersion"]) if is_darwin else platform.release()
    os_build = _run_cmd_quiet(["sw_vers", "-buildVersion"]) if is_darwin else ""
    chip = (
        _run_cmd_quiet(["sysctl", "-n", "machdep.cpu.brand_string"])
        if is_darwin
        else (platform.processor() or platform.machine())
    )
    hw_model = _run_cmd_quiet(["sysctl", "-n", "hw.model"]) if is_darwin else platform.machine()
    mem_gb = probe_host_memory_gb()

    mlx_version: str | None = None
    try:
        if importlib.util.find_spec("mlx") is not None:
            import mlx.core as mx  # type: ignore[import-not-found]

            mlx_version = str(getattr(mx, "__version__", "") or "") or None
    except Exception:
        mlx_version = None

    missing_r8 = check_r8_dependencies(strict=False)
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "executable": sys.executable,
        "os_version": os_version or None,
        "os_build": os_build or None,
        "chip": chip or None,
        "hw_model": hw_model or None,
        "mem_gb": mem_gb,
        "mlx_version": mlx_version,
        "mlx_enable_tf32": os.environ.get("MLX_ENABLE_TF32"),
        "mlx_metal_no_nax": os.environ.get("MLX_METAL_NO_NAX"),
        "r8_deps_ok": not missing_r8,
        "missing_r8_deps": missing_r8,
    }


def run_silicon_preflight(
    *,
    escalate_gpt_oss: bool = False,
    escalate_qwen: bool = False,
    require_r8_deps: bool = True,
    strict_os_mlx: bool = False,
    stream: Any = None,
    once: bool = False,
    env_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run Apple Silicon OS/MLX/TF32/RAM/R8 preflight validation and emit actionable diagnostics."""
    global _PREFLIGHT_WARNED
    info = dict(env_override) if env_override is not None else probe_silicon_environment()

    missing_r8 = list(info.get("missing_r8_deps") or ())
    if require_r8_deps and missing_r8:
        joined = ", ".join(missing_r8)
        raise RuntimeError(
            f"Missing required congress_docmeta R8/schema dependencies in {info.get('executable') or sys.executable}: "
            f"{joined}. Run under `../fast-silicon/.venv/bin/python` after `uv sync --extra dev --extra extract`."
        )

    warnings: list[str] = []
    if info.get("system") == "Darwin":
        os_ver_str = str(info.get("os_version") or "")
        os_ver = parse_semver(os_ver_str)
        if os_ver and _version_lt(os_ver, MIN_MACOS_NAX_VERSION):
            warnings.append(
                f"macOS {os_ver_str} < 26.2: MLX Apple10/NAX fast paths require macOS >= 26.2 "
                "(26.4+ for Metal 4 INT4/INT8 TensorOps)."
            )

    mlx_ver_str = info.get("mlx_version")
    if isinstance(mlx_ver_str, str) and mlx_ver_str:
        mlx_ver = parse_semver(mlx_ver_str)
        if mlx_ver and _version_lt(mlx_ver, MIN_MLX_VERSION):
            warnings.append(
                f"mlx=={mlx_ver_str} < 0.32.4: upgrade to mlx>=0.32.4 to avoid pre-0.32 MLX_METAL_NO_NAX "
                "and SDPA/M5 regressions."
            )

    tf32_val = info.get("mlx_enable_tf32")
    if str(tf32_val or "").strip() == "0":
        warnings.append(
            "MLX_ENABLE_TF32=0 is set: this disables FP32 NAX acceleration paths on Apple M5+ GPUs."
        )

    no_nax_val = info.get("mlx_metal_no_nax")
    if str(no_nax_val or "").strip() in ("1", "true", "TRUE", "yes"):
        warnings.append(
            f"MLX_METAL_NO_NAX={no_nax_val} is set: Metal NAX acceleration is disabled."
        )

    mem_gb = int(info.get("mem_gb") or 0)
    if escalate_gpt_oss and 0 < mem_gb < 32:
        warnings.append(
            f"Host unified memory is {mem_gb} GiB (< 32 GiB) with --escalate-gpt-oss enabled: "
            "two-phase Pass-1 unload before loading GPT-OSS-20B is required to avoid hard OOM."
        )
    elif escalate_gpt_oss and 0 < mem_gb <= 48:
        warnings.append(
            f"Host unified memory is {mem_gb} GiB (<= 48 GiB) with --escalate-gpt-oss enabled: "
            "using two-phase Pass-1 unload before Pass-2 GPT-OSS-20B to stay clear of compressed-memory swapout."
        )
    elif escalate_qwen and 0 < mem_gb <= 24:
        warnings.append(
            f"Host unified memory is {mem_gb} GiB (<= 24 GiB) with --escalate-qwen enabled: "
            "using two-phase Pass-1 unload before Pass-2 Qwen to stay within the 19.2 GiB MLX working-set budget."
        )

    info["warnings"] = warnings

    if strict_os_mlx and warnings:
        os_mlx_warns = [w for w in warnings if w.startswith(("macOS ", "mlx=="))]
        if os_mlx_warns:
            raise RuntimeError("Silicon preflight failed: " + " | ".join(os_mlx_warns))

    quiet = (
        os.environ.get("DOCMETA_NO_PREFLIGHT_WARN") == "1"
        or os.environ.get("FAST_SILICON_NO_HW_WARN") == "1"
    )
    if not quiet and not (once and _PREFLIGHT_WARNED):
        out = sys.stderr if stream is None else stream
        if env_override is None:
            try:
                if importlib.util.find_spec("fast_shared.hw_check") is not None:
                    from fast_shared.hw_check import warn_if_untested_hardware  # type: ignore[import-not-found]

                    warn_if_untested_hardware(stream=out, once=True)
            except Exception:
                pass
        if warnings:
            _PREFLIGHT_WARNED = True
            for w in warnings:
                print(f"[congress_docmeta] PREFLIGHT WARNING: {w}", file=out)

    return info


@contextmanager
def mlx_wired_limit_scope(
    *,
    enabled: bool = True,
    limit_bytes: int | None = None,
) -> Iterator[int | None]:
    """Set `mx.set_wired_limit` to `max_recommended_working_set_size` and restore prior limit on exit."""
    set_wired: Any = None
    target: int | None = None
    prev: int | None = None
    applied = False

    if enabled:
        mx: Any = None
        try:
            if importlib.util.find_spec("mlx") is not None:
                import mlx.core as mx  # type: ignore[import-not-found]
        except Exception:
            mx = None

        if mx is not None:
            cand_set_wired = getattr(mx, "set_wired_limit", None)
            if callable(cand_set_wired):
                set_wired = cand_set_wired
                target = limit_bytes
                if target is None:
                    try:
                        dev_info = mx.device_info()
                        raw_rec = (
                            dev_info.get("max_recommended_working_set_size")
                            if isinstance(dev_info, Mapping)
                            else None
                        )
                        target = int(raw_rec) if raw_rec else None
                    except Exception:
                        target = None
                if target is not None and target > 0:
                    try:
                        prev = int(set_wired(int(target)))
                        applied = True
                    except Exception:
                        applied = False

    try:
        yield int(target) if (applied and target is not None) else None
    finally:
        if applied and prev is not None and callable(set_wired):
            try:
                set_wired(prev)
            except Exception:
                pass


def apply_mlx_limits(
    *,
    memory_limit_gb: float | None | Any = _AUTO_LIMIT,
    cache_limit_gb: float | None | Any = _AUTO_LIMIT,
    mx_module: Any = None,
) -> dict[str, int | None]:
    """Set MLX global memory and free-buffer cache limits (`ct-s9l2`).

    When omitted, defaults are auto-sized via :func:`resolve_default_mlx_limits`.
    ``memory_limit_gb <= 0`` (or explicit ``None``) leaves the active memory limit
    untouched; ``cache_limit_gb < 0`` (or explicit ``None``) leaves the cache limit
    untouched (``0`` disables caching).
    Returns applied and previous byte limits so callers can record or restore them.
    """
    if memory_limit_gb is _AUTO_LIMIT or cache_limit_gb is _AUTO_LIMIT:
        def_mem, def_cache = resolve_default_mlx_limits()
        if memory_limit_gb is _AUTO_LIMIT:
            memory_limit_gb = def_mem
        if cache_limit_gb is _AUTO_LIMIT:
            cache_limit_gb = def_cache
    out: dict[str, int | None] = {
        "memory_limit_bytes": None,
        "prev_memory_limit_bytes": None,
        "cache_limit_bytes": None,
        "prev_cache_limit_bytes": None,
    }
    mx = mx_module
    if mx is None:
        try:
            if importlib.util.find_spec("mlx") is not None:
                import mlx.core as mx  # type: ignore[import-not-found]
        except Exception:
            mx = None
    if mx is None:
        return out

    if memory_limit_gb is not None and float(memory_limit_gb) > 0.0:
        set_mem = getattr(mx, "set_memory_limit", None)
        if callable(set_mem):
            mem_bytes = int(round(float(memory_limit_gb) * (1024**3)))
            try:
                out["prev_memory_limit_bytes"] = int(set_mem(mem_bytes))
                out["memory_limit_bytes"] = mem_bytes
            except Exception:
                pass

    if cache_limit_gb is not None and float(cache_limit_gb) >= 0.0:
        set_cache = getattr(mx, "set_cache_limit", None)
        if callable(set_cache):
            cache_bytes = int(round(float(cache_limit_gb) * (1024**3)))
            try:
                out["prev_cache_limit_bytes"] = int(set_cache(cache_bytes))
                out["cache_limit_bytes"] = cache_bytes
            except Exception:
                pass

    return out


@contextmanager
def mlx_limits_scope(
    *,
    memory_limit_gb: float | None | Any = _AUTO_LIMIT,
    cache_limit_gb: float | None | Any = _AUTO_LIMIT,
    mx_module: Any = None,
) -> Iterator[dict[str, int | None]]:
    """Apply ``mx.set_memory_limit`` + ``mx.set_cache_limit`` for a run and restore prior limits on exit."""
    mx = mx_module
    if mx is None:
        try:
            if importlib.util.find_spec("mlx") is not None:
                import mlx.core as mx  # type: ignore[import-not-found]
        except Exception:
            mx = None
    info = apply_mlx_limits(
        memory_limit_gb=memory_limit_gb,
        cache_limit_gb=cache_limit_gb,
        mx_module=mx,
    )
    try:
        yield info
    finally:
        if mx is not None:
            prev_mem = info.get("prev_memory_limit_bytes")
            if prev_mem is not None and callable(getattr(mx, "set_memory_limit", None)):
                try:
                    mx.set_memory_limit(int(prev_mem))
                except Exception:
                    pass
            prev_cache = info.get("prev_cache_limit_bytes")
            if prev_cache is not None and callable(getattr(mx, "set_cache_limit", None)):
                try:
                    mx.set_cache_limit(int(prev_cache))
                except Exception:
                    pass


def get_and_cap_mlx_cache_limit(*, max_cache_mib: int = 256) -> int | None:
    """Cap MLX's global free-buffer cache to `max_cache_mib` MiB and return the previous limit."""
    try:
        if importlib.util.find_spec("mlx") is None:
            return None
        import mlx.core as mx  # type: ignore[import-not-found]
    except Exception:
        return None
    set_cache = getattr(mx, "set_cache_limit", None)
    if not callable(set_cache):
        return None
    cap_bytes = max(0, int(max_cache_mib)) << 20
    try:
        return int(set_cache(cap_bytes))
    except Exception:
        return None


def restore_mlx_cache_limit(prev_limit: int | None) -> None:
    """Restore a previously saved MLX global buffer cache limit safely."""
    if prev_limit is None:
        return
    try:
        if importlib.util.find_spec("mlx") is None:
            return
        import mlx.core as mx  # type: ignore[import-not-found]
    except Exception:
        return
    set_cache = getattr(mx, "set_cache_limit", None)
    if callable(set_cache):
        try:
            set_cache(int(prev_limit))
        except Exception:
            pass


def clear_mlx_wave_cache(threshold_mib: int = 256, *, force: bool = False) -> bool:
    """Release MLX free-buffer arena between waves (`> threshold_mib` MiB, or unconditionally if `force=True`)."""
    gc.collect()
    try:
        if "mlx.core" not in sys.modules and importlib.util.find_spec("mlx") is None:
            return False
        import mlx.core as mx  # type: ignore[import-not-found]
    except Exception:
        return False

    clear_fn = getattr(mx, "clear_cache", None)
    if not callable(clear_fn):
        return False
    if force:
        clear_fn()
        return True
    get_cache = getattr(mx, "get_cache_memory", None)
    if callable(get_cache):
        try:
            if int(get_cache()) > (max(0, int(threshold_mib)) << 20):
                clear_fn()
                return True
            return False
        except Exception:
            pass
    clear_fn()
    return True


def unload_engine_memory(engine: Any) -> None:
    """Unload heavy GPU/CPU weights, prefix caches, and ANE CPU tables from a Pass-1 engine before Pass-2."""
    if engine is None:
        return
    close_fn = getattr(engine, "close", None)
    if callable(close_fn):
        try:
            close_fn()
        except Exception:
            pass

    for dict_attr in ("_prefix_cache", "_grammar_cache", "_ane_workers", "_ane_rings"):
        val = getattr(engine, dict_attr, None)
        if hasattr(val, "clear"):
            try:
                val.clear()
            except Exception:
                pass

    # Drop large CPU/GPU references (e.g. FastGemma4Engine's 2.68 GB FP16 _w_emb/_w_pli14 & model weights)
    # while keeping lightweight metadata such as `ane_ring_bundle` / `model_dir` readable for reporting.
    for heavy_attr in ("_w_emb", "_w_pli14", "_ane_runner", "_ane_ring_runner", "model"):
        if hasattr(engine, heavy_attr):
            try:
                setattr(engine, heavy_attr, None)
            except Exception:
                pass

    clear_mlx_wave_cache(0, force=True)


def format_chat_no_thinking(tok: Any, msgs: Sequence[Mapping[str, str]]) -> str:
    """Format chat messages with explicit `enable_thinking=False` across custom and HF/MLX tokenizers."""
    msg_list = [dict(m) for m in msgs]
    if hasattr(tok, "apply_chat_template"):
        fn = tok.apply_chat_template
        pass_thinking = False
        try:
            sig = inspect.signature(fn)
            pass_thinking = "enable_thinking" in sig.parameters or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
        except (TypeError, ValueError):
            pass_thinking = False
        if pass_thinking:
            return str(fn(msg_list, tokenize=False, add_generation_prompt=True, enable_thinking=False))
        return str(fn(msg_list, tokenize=False, add_generation_prompt=True))
    return str(tok.format_chat(msg_list, add_generation_prompt=True, enable_thinking=False))


def is_qwen_engine_or_model(engine_or_model: Any) -> bool:
    """Return True when `engine_or_model` looks like a Qwen engine/model rather than Gemma/GPT-OSS."""
    if engine_or_model is None:
        return False
    cls = type(engine_or_model)
    parts: list[str] = [cls.__name__, cls.__module__]
    for attr in ("model_name", "model_dir", "repo_id"):
        val = getattr(engine_or_model, attr, None)
        if val is not None:
            parts.append(str(val))
    inner = getattr(engine_or_model, "model", None)
    if inner is not None:
        parts.extend([type(inner).__name__, type(inner).__module__])
        for attr in ("model_name", "model_dir", "repo_id"):
            val = getattr(inner, attr, None)
            if val is not None:
                parts.append(str(val))
    return any("qwen" in p.lower() for p in parts if p)


def resolve_default_whitespace_flexible(engine_or_model: Any, *, explicit: Any = "auto") -> bool | None:
    """Resolve `GrammarHelper(..., whitespace_flexible=...)`: `None` (spaced `: `) for Qwen, `False` otherwise."""
    if explicit != "auto":
        return explicit
    if is_qwen_engine_or_model(engine_or_model):
        return None
    gen_fn = getattr(engine_or_model, "generate_batch", None)
    if callable(gen_fn):
        try:
            ws_param = inspect.signature(gen_fn).parameters.get("whitespace_flexible")
            if ws_param is not None and ws_param.default is None:
                return None
        except (TypeError, ValueError):
            pass
    return False


def resolve_pass2_source_tag(engine_or_model: Any) -> str:
    """Return canonical `docmeta_source` provenance tag for a Pass-2 escalation engine."""
    return "fast-qwen3-pass2" if is_qwen_engine_or_model(engine_or_model) else "fast-gpt-oss-20b-pass2"


__all__ = [
    "DEFAULT_DOCMETA_BATCH_SIZE",
    "DEFAULT_MLX_CACHE_LIMIT_GB",
    "DEFAULT_MLX_MEMORY_LIMIT_GB",
    "MIN_MACOS_ANE_CORE_FIX_VERSION",
    "MIN_MACOS_METAL4_INT_VERSION",
    "MIN_MACOS_NAX_VERSION",
    "MIN_MLX_VERSION",
    "REQUIRED_R8_MODULES",
    "apply_mlx_limits",
    "check_r8_dependencies",
    "clear_mlx_wave_cache",
    "format_chat_no_thinking",
    "get_and_cap_mlx_cache_limit",
    "is_qwen_engine_or_model",
    "mlx_limits_scope",
    "mlx_wired_limit_scope",
    "parse_semver",
    "probe_host_memory_gb",
    "probe_silicon_environment",
    "resolve_default_docmeta_batch_size",
    "resolve_default_mlx_limits",
    "resolve_default_whitespace_flexible",
    "resolve_pass2_source_tag",
    "restore_mlx_cache_limit",
    "run_silicon_preflight",
    "unload_engine_memory",
]
