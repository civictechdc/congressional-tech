"""Provider-agnostic 3-family parallel runner for DocMeta V7.2.

Supports:
- `claude_cli`: `/Users/mikewolfd/.local/bin/claude` (`-p --output-format json --json-schema ... --tools "" --permission-mode plan --no-session-persistence`)
- `codex_cli`: `/Users/mikewolfd/.nvm/versions/node/v22.22.2/bin/codex` (`exec -s read-only --ephemeral --skip-git-repo-check --output-schema ... -o ... -`)
- `gemini_cli`: `/opt/homebrew/bin/gemini` (`-p ... -o json --approval-mode plan`)
- `custom`: caller-supplied Python callables for deterministic tests or custom providers

Every execution runs behind `SixTupleCache` (excluding `parse()` from cache keys)
with clean timeouts, bounded parse retries via `rollout_id`, and `ThreadPoolExecutor`
parallelism across families.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, Mapping, Sequence

from .cache import (
    CacheEntry,
    CacheKey,
    SixTupleCache,
    canonical_json_sha256,
    make_cache_key,
    sha256_text,
)


DEFAULT_CLAUDE_BIN = "/Users/mikewolfd/.local/bin/claude"
DEFAULT_CODEX_BIN = "/Users/mikewolfd/.nvm/versions/node/v22.22.2/bin/codex"
DEFAULT_AGY_BIN = "/Users/mikewolfd/.local/bin/agy"
DEFAULT_GEMINI_BIN = "/opt/homebrew/bin/gemini"

DEFAULT_MODEL_IDS: dict[str, str] = {
    "claude": "claude-sonnet-default",
    "codex": "codex-default",
    "gemini": "gemini-4-carbon-medium",
    "custom": "custom-default",
}

DEFAULT_PROVIDER_KINDS: dict[str, str] = {
    "claude": "claude_cli",
    "codex": "codex_cli",
    "gemini": "agy_cli",
    "custom": "custom",
}

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL | re.IGNORECASE)


@dataclass
class AdapterOutput:
    """Raw output returned by a CLI or custom provider adapter."""

    raw_text: str
    extracted_json_str: str | None = None
    returncode: int = 0
    error: str | None = None
    latency_ms: float = 0.0
    usage_pct: float | None = None
    rate_limit_info: dict[str, Any] | None = None
    cost_usd: float | None = None


@dataclass
class RunnerConfig:
    """Configuration for the 3-family parallel runner."""

    claude_bin: str = DEFAULT_CLAUDE_BIN
    codex_bin: str = DEFAULT_CODEX_BIN
    agy_bin: str = DEFAULT_AGY_BIN
    gemini_bin: str = DEFAULT_GEMINI_BIN
    claude_model: str | None = None
    claude_effort: str | None = None
    codex_model: str | None = None
    codex_reasoning_effort: str | None = None
    gemini_model: str | None = "gemini-4-carbon-medium"
    timeout_s: float = 120.0
    max_parse_retries: int = 2
    max_workers: int = 3
    cache_cli_errors: bool = False
    stripped_prefix: bool = False
    system_prompt: str | None = None
    fixed_cwd: Path | None = None
    emit_usage_telemetry: bool = False
    on_adapter_output: Callable[[str, AdapterOutput], None] | None = None
    provider_overrides: dict[str, str] = field(default_factory=dict)
    model_overrides: dict[str, str] = field(default_factory=dict)

    def model_id_for(self, family: str) -> str:
        if family in self.model_overrides and self.model_overrides[family]:
            return self.model_overrides[family]
        if family == "claude":
            base = self.claude_model or DEFAULT_MODEL_IDS["claude"]
            return f"{base}:effort={self.claude_effort}" if self.claude_effort else base
        if family == "codex":
            base = self.codex_model or DEFAULT_MODEL_IDS["codex"]
            return f"{base}:effort={self.codex_reasoning_effort}" if self.codex_reasoning_effort else base
        if family == "gemini" and self.gemini_model:
            return self.gemini_model
        return DEFAULT_MODEL_IDS.get(family, f"{family}-default")

    def provider_for(self, family: str) -> str:
        if family in self.provider_overrides:
            return self.provider_overrides[family]
        return DEFAULT_PROVIDER_KINDS.get(family, "custom")


@dataclass
class FamilyRunResult:
    """Structured result for one family's extraction on one document."""

    family: str
    model_id: str
    cache_hit: bool
    rollout_id: int
    ok: bool
    raw_text: str
    extracted_json_str: str | None
    parsed: dict[str, Any] | None
    latency_ms: float
    returncode: int
    error: str | None
    cache_key: CacheKey


def build_claude_command(
    schema: dict[str, Any],
    *,
    binary: str = DEFAULT_CLAUDE_BIN,
    model: str | None = None,
    effort: str | None = None,
    system_prompt: str | None = None,
    stripped_prefix: bool = False,
    stream_json: bool = False,
) -> list[str]:
    """Build verified headless command for `claude` CLI (`2.1.x`)."""
    schema_json = json.dumps(schema, separators=(",", ":"), ensure_ascii=False)
    cmd = [
        binary,
        "-p",
        "--output-format",
        "stream-json" if stream_json else "json",
    ]
    if stream_json:
        cmd.append("--verbose")
    cmd.extend(
        [
            "--json-schema",
            schema_json,
            "--tools",
            "",
            "--permission-mode",
            "plan",
            "--no-session-persistence",
        ]
    )
    if stripped_prefix:
        cmd.extend(["--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands", "--agents", "{}"])
    if system_prompt is not None:
        cmd.extend(["--system-prompt", system_prompt])
    if model:
        cmd.extend(["--model", model])
    if effort:
        cmd.extend(["--effort", effort])
    return cmd


def build_codex_command(
    schema_path: Path,
    output_path: Path,
    *,
    binary: str = DEFAULT_CODEX_BIN,
    model: str | None = None,
    reasoning_effort: str | None = None,
    skip_git_repo_check: bool = True,
    stripped_prefix: bool = False,
    json_events: bool = False,
    ephemeral: bool = True,
) -> list[str]:
    """Build verified headless command for `codex exec` CLI (`0.169.x`)."""
    cmd = [binary, "exec"]
    if json_events:
        cmd.append("--json")
    cmd.extend(["-s", "read-only"])
    if ephemeral:
        cmd.append("--ephemeral")
    cmd.extend(
        [
            "--color",
            "never",
            "--output-schema",
            str(schema_path),
            "-o",
            str(output_path),
        ]
    )
    if skip_git_repo_check:
        cmd.append("--skip-git-repo-check")
    if stripped_prefix:
        cmd.extend(
            [
                "-c",
                "mcp_servers={}",
                "-c",
                "plugins={}",
                "-c",
                'web_search="disabled"',
                "-c",
                'service_tier="default"',
                "-c",
                "notify=[]",
                "-c",
                "project_doc_max_bytes=0",
                "--disable",
                "memories",
                "--disable",
                "multi_agent",
                "--disable",
                "goals",
                "--disable",
                "steer",
                "--disable",
                "code_mode_host",
                "--disable",
                "shell_tool",
                "--disable",
                "unified_exec",
                "--disable",
                "apps",
                "--disable",
                "browser_use",
                "--disable",
                "computer_use",
                "--disable",
                "sleep_tool",
                "--disable",
                "view_image",
                "--disable",
                "tool_suggest",
                "--disable",
                "plugins",
                "--disable",
                "hooks",
                "--disable",
                "skill_search",
            ]
        )
    if reasoning_effort:
        cmd.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    if model:
        cmd.extend(["-m", model])
    cmd.append("-")
    return cmd


def build_agy_command(
    prompt_text: str,
    schema_path: Path,
    *,
    binary: str = DEFAULT_AGY_BIN,
    model: str | None = None,
) -> list[str]:
    """Build verified headless command for native Antigravity `agy` CLI (`-p --output-format json --json-schema`)."""
    cmd = [
        binary,
        "-p",
        prompt_text,
        "--output-format",
        "json",
        "--json-schema",
        str(schema_path),
        "--mode",
        "plan",
        "--disable-slash-commands",
    ]
    if model:
        cmd.extend(["--model", model])
    return cmd


def build_agy_stripped_command(
    prompt_text: str,
    settings_path: Path,
    *,
    agent_name: str = "docmeta-bulk-reviewer",
    binary: str = DEFAULT_AGY_BIN,
    model: str = "gemini-4-neon-medium",
) -> list[str]:
    """Build single-turn zero-tool headless command for `agy` without `--json-schema` or `--mode`."""
    cmd = [
        binary,
        "-p",
        prompt_text,
        "--agent",
        agent_name,
        "--model",
        model,
        "--disable-slash-commands",
        "--settings",
        str(settings_path),
        "--output-format",
        "json",
    ]
    return cmd


def build_gemini_command(
    prompt_flag: str = "Respond strictly with valid JSON matching the requested schema.",
    *,
    binary: str = DEFAULT_GEMINI_BIN,
    model: str | None = None,
) -> list[str]:
    """Build verified headless command for `gemini` CLI (`-p ... -o json --approval-mode plan`)."""
    cmd = [
        binary,
        "-p",
        prompt_flag,
        "-o",
        "json",
        "--approval-mode",
        "plan",
    ]
    if model:
        cmd.extend(["-m", model])
    return cmd


def strip_markdown_fences(text: str) -> str:
    """Extract inner payload from ```json ... ``` fences if present."""
    stripped = text.strip()
    match = _FENCE_RE.search(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def _scan_first_json_object(text: str) -> dict[str, Any] | None:
    """Scan `text` for the first balanced JSON object."""
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text, idx)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _unwrap_cli_envelope(obj: Any, provider: str | None = None) -> Any:
    """Unwrap Claude/Gemini CLI JSON envelopes down to the model output dict or text."""
    if isinstance(obj, list):
        # Claude stream/event arrays occasionally place the result item last.
        for item in reversed(obj):
            if isinstance(item, dict) and item.get("type") == "result":
                return _unwrap_cli_envelope(item, provider=provider)
        return obj

    if not isinstance(obj, dict):
        return obj

    # Claude / Antigravity `agy` `--output-format json --json-schema` envelope.
    if obj.get("type") == "result" or "structured_output" in obj or "conversation_id" in obj:
        status_val = str(obj.get("status") or "").upper()
        if obj.get("is_error") is True or status_val in {"ERROR", "FAILED", "CANCELLED"}:
            raise ValueError(f"CLI reported error result: {obj.get('error') or obj.get('result') or obj}")
        if isinstance(obj.get("structured_output"), dict):
            return obj["structured_output"]
        if "response" in obj and obj["response"] is not None:
            return obj["response"]
        if "result" in obj and obj["result"] is not None:
            return obj["result"]

    # Gemini `-o json` envelope (`{"response": "...", "stats": {...}}`).
    if "response" in obj and (
        provider == "gemini_cli"
        or "stats" in obj
        or "session_id" in obj
        or set(obj.keys()) <= {"response", "stats", "session_id", "error"}
    ):
        if obj.get("error"):
            raise ValueError(f"Gemini CLI reported error: {obj['error']}")
        return obj["response"]

    return obj


def extract_json_payload(
    raw_text: str,
    *,
    provider: str | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Unwrap CLI envelopes / markdown fences and parse the JSON object payload."""
    if not raw_text or not raw_text.strip():
        return None, None

    candidate: Any = raw_text.strip()
    # Up to two unwrap passes (envelope -> string -> fence -> dict).
    for _ in range(3):
        if isinstance(candidate, dict):
            unwrapped = _unwrap_cli_envelope(candidate, provider=provider)
            if unwrapped is candidate:
                return json.dumps(candidate, ensure_ascii=False), candidate
            candidate = unwrapped
            continue

        if isinstance(candidate, list):
            unwrapped = _unwrap_cli_envelope(candidate, provider=provider)
            if unwrapped is candidate:
                return None, None
            candidate = unwrapped
            continue

        if isinstance(candidate, str):
            cleaned = strip_markdown_fences(candidate)
            try:
                parsed = json.loads(cleaned)
                candidate = parsed
                continue
            except json.JSONDecodeError:
                scanned = _scan_first_json_object(cleaned)
                if scanned is None and cleaned != candidate:
                    scanned = _scan_first_json_object(candidate)
                if scanned is not None:
                    candidate = scanned
                    continue
                return None, None

        return None, None

    if isinstance(candidate, dict):
        return json.dumps(candidate, ensure_ascii=False), candidate
    return None, None


def default_parse_fn(
    raw_text: str,
    *,
    provider: str | None = None,
    model_cls: Any = None,
) -> dict[str, Any]:
    """Default pure `parse()` function executed AFTER `SixTupleCache` lookup.

    Accepts optional Pydantic model class `model_cls` (`model_validate`) so schema
    validation or normalization changes replay from cache with zero CLI re-runs.
    """
    _, payload = extract_json_payload(raw_text, provider=provider)
    if payload is None:
        raise ValueError("Could not extract valid JSON object from raw model output")
    if model_cls is not None:
        if hasattr(model_cls, "model_validate"):
            validated = model_cls.model_validate(payload)
            return validated.model_dump()
        if callable(model_cls):
            validated = model_cls(payload)
            return validated if isinstance(validated, dict) else dict(validated)
    return payload


def _decode_stream(data: str | bytes | None) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


def _invoke_subprocess(
    cmd: list[str],
    *,
    stdin_text: str | None,
    timeout_s: float,
    cwd: Path | None = None,
    env_overrides: Mapping[str, str] | None = None,
) -> tuple[int, str, str, float, str | None]:
    t0 = time.perf_counter()
    env = os.environ.copy()
    if env_overrides:
        env.update({str(k): str(v) for k, v in env_overrides.items()})
    try:
        run_kwargs: dict[str, Any] = {
            "text": True,
            "capture_output": True,
            "timeout": timeout_s,
            "cwd": str(cwd) if cwd is not None else None,
            "env": env,
        }
        if stdin_text is None:
            run_kwargs["stdin"] = subprocess.DEVNULL
        else:
            run_kwargs["input"] = stdin_text
        proc = subprocess.run(cmd, **run_kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        err = proc.stderr.strip() or None if proc.returncode != 0 else None
        return proc.returncode, proc.stdout or "", proc.stderr or "", latency_ms, err
    except subprocess.TimeoutExpired as exc:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        stdout = _decode_stream(exc.stdout)
        stderr = _decode_stream(exc.stderr)
        return -1, stdout, stderr, latency_ms, f"timeout after {timeout_s:.1f}s"
    except OSError as exc:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return -1, "", "", latency_ms, f"os_error: {exc}"


_QUOTA_ERR_RE = re.compile(
    r"(rate[_\s-]?limit|usage[_\s-]?limit|quota[_\s-]?(?:exceeded|exhausted|reached)|429|"
    r"too many requests|out[_\s_-]of[_\s_-]credits|overageStatus.*rejected|hit your limit)",
    re.IGNORECASE,
)

_AGY_QUOTA_ERR_RE = re.compile(
    r"(RESOURCE_EXHAUSTED|quota|429|rate[\s_-]?limit|exhausted|capacity|too many requests)",
    re.IGNORECASE,
)


def parse_claude_stream_json(
    stdout: str,
) -> tuple[dict[str, Any] | None, float | None, dict[str, Any] | None, float | None]:
    """Parse `claude -p --output-format stream-json --verbose` NDJSON lines.

    Returns `(result_envelope, max_usage_pct, rate_limit_info, cost_usd)`.
    """
    result_env: dict[str, Any] | None = None
    rate_limit_info: dict[str, Any] | None = None
    max_usage_pct: float | None = None
    cost_usd: float | None = None

    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue

        ev_type = obj.get("type")
        if ev_type == "rate_limit_event" and isinstance(obj.get("rate_limit_info"), dict):
            rl = obj["rate_limit_info"]
            rate_limit_info = rl
            pcts: list[float] = []
            status = str(rl.get("status") or "").lower()
            if status in {"rejected", "rate_limited", "blocked"}:
                pcts.append(100.0)
            if isinstance(rl.get("utilization"), (int, float)):
                pcts.append(float(rl["utilization"]) * 100.0)
            windows = rl.get("unifiedWindows")
            if isinstance(windows, dict):
                for win in windows.values():
                    if isinstance(win, dict):
                        w_status = str(win.get("status") or "").lower()
                        if w_status in {"rejected", "rate_limited", "blocked"}:
                            pcts.append(100.0)
                        util = win.get("utilization")
                        if isinstance(util, (int, float)):
                            pcts.append(float(util) * 100.0)
            if pcts:
                cand = max(pcts)
                max_usage_pct = cand if max_usage_pct is None else max(max_usage_pct, cand)
        elif ev_type == "result":
            result_env = obj
            mu = obj.get("modelUsage")
            if isinstance(mu, dict) and mu:
                costs = [
                    float(entry.get("costUSD", 0.0) or 0.0)
                    for entry in mu.values()
                    if isinstance(entry, dict) and entry.get("costUSD") is not None
                ]
                if costs:
                    cost_usd = sum(costs)
            elif isinstance(obj.get("total_cost_usd"), (int, float)):
                cost_usd = float(obj["total_cost_usd"])

    return result_env, max_usage_pct, rate_limit_info, cost_usd


def read_codex_rollout_rate_limits(
    thread_id: str | None,
    sessions_root: Path | None = None,
) -> tuple[float | None, dict[str, Any] | None]:
    """Read `rate_limits` from Codex's session rollout JSONL without modifying session files."""
    root = sessions_root or (Path.home() / ".codex" / "sessions")
    if not root.is_dir():
        return None, None

    candidates: list[Path] = []
    if thread_id:
        now_local = datetime.now()
        now_utc = datetime.now(timezone.utc)
        day_dirs: list[Path] = []
        for dt in (now_local, now_local - timedelta(days=1), now_utc, now_utc - timedelta(days=1)):
            d = root / f"{dt.year:04d}" / f"{dt.month:02d}" / f"{dt.day:02d}"
            if d.is_dir() and d not in day_dirs:
                day_dirs.append(d)
        for d in day_dirs:
            candidates.extend(sorted(d.glob(f"*{thread_id}*.jsonl")))
        if not candidates:
            candidates.extend(sorted(root.rglob(f"*{thread_id}*.jsonl")))

    if not candidates:
        return None, None

    rollout_path = max(candidates, key=lambda p: p.stat().st_mtime)
    try:
        lines = rollout_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None, None

    for raw_line in reversed(lines):
        if "rate_limits" not in raw_line:
            continue
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        rl = (obj.get("payload") or {}).get("rate_limits") if isinstance(obj.get("payload"), dict) else obj.get("rate_limits")
        if not isinstance(rl, dict):
            continue
        pcts: list[float] = []
        if rl.get("rate_limit_reached_type") is not None or rl.get("spend_control_reached") is True:
            pcts.append(100.0)
        for bucket in ("primary", "secondary"):
            b_val = rl.get(bucket)
            if isinstance(b_val, dict) and isinstance(b_val.get("used_percent"), (int, float)):
                pcts.append(float(b_val["used_percent"]))
        if pcts:
            return max(pcts), rl
        return None, rl

    return None, None


class UsageGuard:
    """Thread-safe circuit breaker that halts workers if any model reaches `max_usage_pct`."""

    def __init__(
        self,
        max_usage_pct: float | None = 50.0,
        *,
        require_telemetry: bool = False,
        max_missing_telemetry: int = 2,
        telemetry_families: Sequence[str] | None = None,
    ) -> None:
        self.max_usage_pct = max_usage_pct
        self.require_telemetry = bool(require_telemetry)
        self.max_missing_telemetry = max(1, int(max_missing_telemetry))
        self.telemetry_families: set[str] | None = (
            set(telemetry_families) if telemetry_families is not None else None
        )
        self._lock = threading.Lock()
        self.stop_event = threading.Event()
        self.usage_by_family: dict[str, float] = {}
        self.rate_limit_by_family: dict[str, dict[str, Any]] = {}
        self._missing_telemetry_streak: dict[str, int] = {}
        self.triggered_reason: str | None = None

    def trip(self, reason: str) -> None:
        """Manually trip the circuit breaker with an explicit stop reason."""
        with self._lock:
            if not self.stop_event.is_set():
                self.triggered_reason = reason
                self.stop_event.set()

    def record(
        self,
        family: str,
        usage_pct: float | None,
        rate_limit_info: dict[str, Any] | None = None,
        error: str | None = None,
        *,
        returncode: int = 0,
    ) -> bool:
        """Record latest provider usage telemetry and return True if circuit breaker tripped."""
        with self._lock:
            if usage_pct is not None:
                self.usage_by_family[family] = float(usage_pct)
                self._missing_telemetry_streak[family] = 0
            elif (
                self.require_telemetry
                and self.max_usage_pct is not None
                and returncode == 0
                and error is None
                and (self.telemetry_families is None or family in self.telemetry_families)
            ):
                streak = self._missing_telemetry_streak.get(family, 0) + 1
                self._missing_telemetry_streak[family] = streak
                if streak >= self.max_missing_telemetry and not self.stop_event.is_set():
                    self.triggered_reason = (
                        f"{family} returned {streak} consecutive rc=0 calls without usage_pct telemetry; "
                        f"refusing to run blind under {self.max_usage_pct:.1f}% cap"
                    )
                    self.stop_event.set()
            if isinstance(rate_limit_info, dict):
                self.rate_limit_by_family[family] = dict(rate_limit_info)

            if self.max_usage_pct is not None and usage_pct is not None and float(usage_pct) >= self.max_usage_pct:
                if not self.stop_event.is_set():
                    self.triggered_reason = (
                        f"{family} usage reached {float(usage_pct):.1f}% >= {self.max_usage_pct:.1f}% limit"
                    )
                    self.stop_event.set()
            elif error and (
                _QUOTA_ERR_RE.search(error)
                or (returncode != 0 and _AGY_QUOTA_ERR_RE.search(error))
            ):
                if not self.stop_event.is_set():
                    self.triggered_reason = f"{family} quota/rate-limit error: {error[:160]}"
                    self.stop_event.set()
            return self.stop_event.is_set()

    def should_stop(self) -> bool:
        return self.stop_event.is_set()

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "max_usage_pct": self.max_usage_pct,
                "tripped": self.stop_event.is_set(),
                "triggered_reason": self.triggered_reason,
                "usage_by_family": dict(self.usage_by_family),
                "rate_limit_by_family": dict(self.rate_limit_by_family),
            }


def invoke_claude_cli(
    prompt: str,
    schema: dict[str, Any],
    *,
    model_id: str | None = None,
    effort: str | None = None,
    timeout_s: float = 120.0,
    binary: str = DEFAULT_CLAUDE_BIN,
    cwd: Path | None = None,
    system_prompt: str | None = None,
    stripped_prefix: bool = False,
    stream_json: bool = False,
) -> AdapterOutput:
    """Execute Claude CLI headlessly with strict `--json-schema` and zero tools."""
    raw_model = model_id or ""
    effective_effort = effort
    if ":effort=" in raw_model:
        raw_model, effort_part = raw_model.split(":effort=", 1)
        if not effective_effort and effort_part:
            effective_effort = effort_part
    effective_model = None if not raw_model or raw_model.endswith("-default") else raw_model
    cmd = build_claude_command(
        schema,
        binary=binary,
        model=effective_model,
        effort=effective_effort,
        system_prompt=system_prompt,
        stripped_prefix=stripped_prefix,
        stream_json=stream_json,
    )
    if cwd is not None:
        cwd.mkdir(parents=True, exist_ok=True)
    ctx = nullcontext(cwd) if cwd is not None else tempfile.TemporaryDirectory(prefix="docmeta_claude_")
    with ctx as cwd_or_tmp:
        run_cwd = Path(cwd_or_tmp)
        rc, stdout, stderr, latency_ms, err = _invoke_subprocess(
            cmd, stdin_text=prompt, timeout_s=timeout_s, cwd=run_cwd
        )

    usage_pct: float | None = None
    rate_limit_info: dict[str, Any] | None = None
    cost_usd: float | None = None
    raw_for_cache = stdout

    if stream_json:
        result_env, usage_pct, rate_limit_info, cost_usd = parse_claude_stream_json(stdout)
        if result_env is not None:
            raw_for_cache = json.dumps(result_env, ensure_ascii=False)
    else:
        try:
            env = json.loads(stdout)
            if isinstance(env, dict) and isinstance(env.get("modelUsage"), dict):
                costs = [
                    float(entry.get("costUSD", 0.0) or 0.0)
                    for entry in env["modelUsage"].values()
                    if isinstance(entry, dict) and entry.get("costUSD") is not None
                ]
                if costs:
                    cost_usd = sum(costs)
        except Exception:
            pass

    extracted: str | None = None
    if rc == 0:
        try:
            extracted, _ = extract_json_payload(raw_for_cache, provider="claude_cli")
        except ValueError as exc:
            err = str(exc)
    elif not err:
        err = stderr.strip() or f"claude exited with code {rc}"
    return AdapterOutput(
        raw_text=raw_for_cache,
        extracted_json_str=extracted,
        returncode=rc,
        error=err,
        latency_ms=latency_ms,
        usage_pct=usage_pct,
        rate_limit_info=rate_limit_info,
        cost_usd=cost_usd,
    )


def _prepare_stripped_codex_home(tmp: Path) -> tuple[Path, Path]:
    """Create isolated `HOME` and `CODEX_HOME` stripping skills, plugins, MCPs, tools, and prompts."""
    fake_home = tmp / "home"
    clean_codex_home = tmp / "codex_home"
    fake_home.mkdir(parents=True, exist_ok=True)
    clean_codex_home.mkdir(parents=True, exist_ok=True)

    real_auth = Path.home() / ".codex" / "auth.json"
    auth_link = clean_codex_home / "auth.json"
    if real_auth.is_file() and not auth_link.exists():
        os.symlink(real_auth, auth_link)

    base_inst_path = clean_codex_home / "base_instructions.txt"
    base_inst_path.write_text(
        "You are a deterministic structured JSON extractor.\n"
        "NEVER call any tool (do NOT call exec, wait, shell, or agent tools).\n"
        "Output ONLY valid JSON conforming strictly to the output schema on your very first response.\n"
        "Exact character start/end offsets for SpanRef are auto-recomputed downstream from your verbatim quote.\n",
        encoding="utf-8",
    )
    (clean_codex_home / "config.toml").write_text(
        'approval_policy = "never"\n'
        'sandbox_mode = "read-only"\n'
        'web_search = "disabled"\n'
        'service_tier = "default"\n'
        "project_doc_max_bytes = 0\n"
        f"model_instructions_file = {json.dumps(str(base_inst_path))}\n"
        "notify = []\n"
        "mcp_servers = {}\n"
        "plugins = {}\n"
        "\n"
        "[features]\n"
        "memories = false\n"
        "multi_agent = false\n"
        "goals = false\n"
        "steer = false\n"
        "code_mode = false\n"
        "code_mode_host = false\n"
        "shell_tool = false\n"
        "unified_exec = false\n"
        "apps = false\n"
        "browser_use = false\n"
        "computer_use = false\n"
        "sleep_tool = false\n"
        "view_image = false\n"
        "tool_suggest = false\n"
        "skills = false\n"
        "skill_search = false\n"
        "plugins = false\n"
        "hooks = false\n"
        "collaboration_modes = false\n",
        encoding="utf-8",
    )
    return fake_home, clean_codex_home


def invoke_codex_cli(
    prompt: str,
    schema: dict[str, Any],
    *,
    model_id: str | None = None,
    reasoning_effort: str | None = None,
    timeout_s: float = 120.0,
    binary: str = DEFAULT_CODEX_BIN,
    cwd: Path | None = None,
    stripped_prefix: bool = False,
    json_events: bool = False,
    ephemeral: bool = True,
    sessions_root: Path | None = None,
) -> AdapterOutput:
    """Execute Codex CLI headlessly in `read-only` sandbox with `--output-schema`."""
    raw_model = model_id or ""
    effort = reasoning_effort
    if ":effort=" in raw_model:
        raw_model, effort_part = raw_model.split(":effort=", 1)
        if not effort and effort_part:
            effort = effort_part
    effective_model = None if not raw_model or raw_model.endswith("-default") else raw_model
    if cwd is not None:
        cwd.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="docmeta_codex_") as tmpdir:
        tmp = Path(tmpdir)
        schema_path = tmp / "schema.json"
        output_path = tmp / "last_message.json"
        schema_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
        env_overrides: dict[str, str] | None = None
        effective_sessions_root = sessions_root
        if stripped_prefix:
            fake_home, clean_codex_home = _prepare_stripped_codex_home(tmp)
            env_overrides = {"HOME": str(fake_home), "CODEX_HOME": str(clean_codex_home)}
            if effective_sessions_root is None:
                effective_sessions_root = clean_codex_home / "sessions"
        cmd = build_codex_command(
            schema_path,
            output_path,
            binary=binary,
            model=effective_model,
            reasoning_effort=effort,
            stripped_prefix=stripped_prefix,
            json_events=json_events,
            ephemeral=ephemeral,
        )
        run_cwd = cwd if cwd is not None else tmp
        rc, stdout, stderr, latency_ms, err = _invoke_subprocess(
            cmd,
            stdin_text=prompt,
            timeout_s=timeout_s,
            cwd=run_cwd,
            env_overrides=env_overrides,
        )
        file_text = ""
        if output_path.is_file():
            file_text = output_path.read_text(encoding="utf-8", errors="replace").strip()

        thread_id: str | None = None
        agent_msg_text = ""
        if json_events and stdout:
            for line in stdout.splitlines():
                stripped = line.strip()
                if not stripped.startswith("{"):
                    continue
                try:
                    ev = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if not isinstance(ev, dict):
                    continue
                if ev.get("type") == "thread.started" and ev.get("thread_id"):
                    thread_id = str(ev["thread_id"])
                elif (
                    ev.get("type") == "item.completed"
                    and isinstance(ev.get("item"), dict)
                    and ev["item"].get("type") == "agent_message"
                ):
                    agent_msg_text = str(ev["item"].get("text") or "").strip()

        usage_pct: float | None = None
        rate_limit_info: dict[str, Any] | None = None
        if not ephemeral:
            usage_pct, rate_limit_info = read_codex_rollout_rate_limits(
                thread_id, sessions_root=effective_sessions_root
            )

        raw_text = file_text or agent_msg_text or stdout
        extracted: str | None = None
        if rc == 0:
            try:
                extracted, _ = extract_json_payload(raw_text, provider="codex_cli")
            except ValueError as exc:
                err = str(exc)
        elif not err:
            err = stderr.strip() or f"codex exited with code {rc}"
        return AdapterOutput(
            raw_text=raw_text,
            extracted_json_str=extracted,
            returncode=rc,
            error=err,
            latency_ms=latency_ms,
            usage_pct=usage_pct,
            rate_limit_info=rate_limit_info,
        )


def invoke_agy_cli(
    prompt: str,
    schema: dict[str, Any],
    *,
    model_id: str | None = None,
    timeout_s: float = 120.0,
    binary: str = DEFAULT_AGY_BIN,
    cwd: Path | None = None,
) -> AdapterOutput:
    """Execute Antigravity `agy` CLI headlessly with Gemini + `--json-schema` in an isolated empty dir."""
    effective_model = None if not model_id or model_id.endswith("-default") else model_id
    with tempfile.TemporaryDirectory(prefix="docmeta_agy_") as tmpdir:
        tmp = Path(tmpdir)
        schema_path = tmp / "schema.json"
        schema_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
        cmd = build_agy_command(
            prompt,
            schema_path,
            binary=binary,
            model=effective_model,
        )
        run_cwd = cwd if cwd is not None else tmp
        rc, stdout, stderr, latency_ms, err = _invoke_subprocess(
            cmd, stdin_text=None, timeout_s=timeout_s, cwd=run_cwd
        )
    extracted: str | None = None
    if rc == 0:
        try:
            extracted, _ = extract_json_payload(stdout, provider="agy_cli")
        except ValueError as exc:
            err = str(exc)
    elif not err:
        err = stderr.strip() or f"agy exited with code {rc}"
    return AdapterOutput(
        raw_text=stdout,
        extracted_json_str=extracted,
        returncode=rc,
        error=err,
        latency_ms=latency_ms,
    )


def _prepare_stripped_agy_workspace(
    tmp: Path,
    *,
    system_prompt: str,
    agent_name: str = "docmeta-bulk-reviewer",
) -> tuple[Path, Path]:
    """Create isolated workspace containing only a zero-tool custom agent and deny-all settings."""
    agent_dir = tmp / ".agents" / "agents" / agent_name
    agent_dir.mkdir(parents=True, exist_ok=True)
    agent_md = (
        "---\n"
        f"name: {agent_name}\n"
        "description: Stripped zero-tool JSON bulk reviewer.\n"
        "tools: []\n"
        "mainAgent: true\n"
        "subagent: false\n"
        "commandExecutionPolicy: off\n"
        "mcpServers: []\n"
        "skills: []\n"
        "plugins: []\n"
        "---\n"
        f"{system_prompt.strip()}\n"
    )
    (agent_dir / "agent.md").write_text(agent_md, encoding="utf-8")

    settings_path = tmp / "settings.json"
    settings_path.write_text(
        json.dumps({"disableSlashCommands": True, "permissions": {"deny": ["*"]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    return tmp, settings_path


def invoke_agy_stripped_cli(
    prompt: str,
    *,
    system_prompt: str,
    model_id: str = "gemini-4-neon-medium",
    timeout_s: float = 180.0,
    binary: str = DEFAULT_AGY_BIN,
    agent_name: str = "docmeta-bulk-reviewer",
) -> AdapterOutput:
    """Execute stripped single-turn zero-tool `agy` CLI in an isolated temp workspace."""
    with tempfile.TemporaryDirectory(prefix="docmeta_agy_strip_") as tmpdir:
        tmp = Path(tmpdir)
        ws_cwd, settings_path = _prepare_stripped_agy_workspace(
            tmp,
            system_prompt=system_prompt,
            agent_name=agent_name,
        )
        cmd = build_agy_stripped_command(
            prompt,
            settings_path,
            agent_name=agent_name,
            binary=binary,
            model=model_id,
        )
        rc, stdout, stderr, latency_ms, err = _invoke_subprocess(
            cmd,
            stdin_text=None,
            timeout_s=timeout_s,
            cwd=ws_cwd,
        )

    raw_stripped = stdout.strip()
    env_obj: dict[str, Any] | None = None
    if raw_stripped:
        try:
            loaded = json.loads(raw_stripped)
            if isinstance(loaded, dict):
                env_obj = loaded
        except json.JSONDecodeError:
            pass

    if isinstance(env_obj, dict):
        env_status = str(env_obj.get("status") or "").upper()
        env_err = env_obj.get("error")
        if env_err or env_status in {"ERROR", "FAILED", "CANCELLED"}:
            err_msg = str(env_err or env_obj.get("response") or f"agy status={env_status}")
            err = f"{err}; {err_msg}" if (err and err_msg not in err) else err_msg
            rc = rc if rc != 0 else 1

    quota_blob = "\n".join(part for part in (err or "", stderr.strip(), stdout if rc != 0 else "") if part)
    if quota_blob and _AGY_QUOTA_ERR_RE.search(quota_blob):
        err_match_src = err or stderr.strip() or raw_stripped[:300]
        if not err:
            err = err_match_src
        rc = rc if rc != 0 else 1

    extracted: str | None = None
    if rc == 0 and err is None:
        try:
            extracted, _ = extract_json_payload(stdout, provider="agy_cli")
            if extracted is None:
                err = "extract_json_payload returned empty output"
        except ValueError as exc:
            err = str(exc)
            if _AGY_QUOTA_ERR_RE.search(err):
                rc = 1
    elif not err:
        err = stderr.strip() or f"agy exited with code {rc}"

    return AdapterOutput(
        raw_text=stdout,
        extracted_json_str=extracted,
        returncode=rc,
        error=err,
        latency_ms=latency_ms,
    )


def invoke_gemini_cli(
    prompt: str,
    schema: dict[str, Any],
    *,
    model_id: str | None = None,
    timeout_s: float = 120.0,
    binary: str = DEFAULT_GEMINI_BIN,
    cwd: Path | None = None,
    prompt_flag: str = "Respond strictly with valid JSON matching the requested schema.",
) -> AdapterOutput:
    """Execute Gemini CLI headlessly with `-p`, `-o json`, and `--approval-mode plan`."""
    del schema  # Prompt carries schema details; Gemini CLI uses `-o json` + prompt instructions.
    effective_model = None if not model_id or model_id.endswith("-default") else model_id
    cmd = build_gemini_command(prompt_flag=prompt_flag, binary=binary, model=effective_model)
    rc, stdout, stderr, latency_ms, err = _invoke_subprocess(
        cmd, stdin_text=prompt, timeout_s=timeout_s, cwd=cwd
    )
    extracted: str | None = None
    if rc == 0:
        try:
            extracted, _ = extract_json_payload(stdout, provider="gemini_cli")
        except ValueError as exc:
            err = str(exc)
    elif not err:
        err = stderr.strip() or f"gemini exited with code {rc}"
    return AdapterOutput(
        raw_text=stdout,
        extracted_json_str=extracted,
        returncode=rc,
        error=err,
        latency_ms=latency_ms,
    )


def _normalize_adapter_result(res: Any, latency_ms: float, provider: str | None) -> AdapterOutput:
    if isinstance(res, AdapterOutput):
        if res.latency_ms == 0.0:
            res.latency_ms = latency_ms
        return res
    if isinstance(res, dict):
        raw = json.dumps(res, ensure_ascii=False)
        return AdapterOutput(raw_text=raw, extracted_json_str=raw, returncode=0, latency_ms=latency_ms)
    if isinstance(res, str):
        extracted, _ = extract_json_payload(res, provider=provider)
        return AdapterOutput(raw_text=res, extracted_json_str=extracted, returncode=0, latency_ms=latency_ms)
    if isinstance(res, tuple) and len(res) >= 2:
        raw = str(res[0])
        rc = int(res[1])
        err = str(res[2]) if len(res) > 2 and res[2] is not None else None
        extracted, _ = extract_json_payload(raw, provider=provider) if rc == 0 else (None, None)
        return AdapterOutput(
            raw_text=raw,
            extracted_json_str=extracted,
            returncode=rc,
            error=err,
            latency_ms=latency_ms,
        )
    raise TypeError(f"Unsupported adapter return type: {type(res).__name__}")


def _resolve_adapter(
    family: str,
    config: RunnerConfig,
    adapters: Mapping[str, Callable[..., Any]] | None,
) -> tuple[str, Callable[..., AdapterOutput]]:
    if adapters and family in adapters:
        fn = adapters[family]

        def _custom_wrapper(
            prompt: str,
            schema: dict[str, Any],
            *,
            model_id: str,
            timeout_s: float,
            rollout_id: int = 0,
        ) -> AdapterOutput:
            t0 = time.perf_counter()
            try:
                res = fn(prompt, schema, model_id=model_id, timeout_s=timeout_s, rollout_id=rollout_id)
            except TypeError:
                try:
                    res = fn(prompt, schema, model_id=model_id, timeout_s=timeout_s)
                except TypeError:
                    res = fn(prompt, schema)
            elapsed = (time.perf_counter() - t0) * 1000.0
            return _normalize_adapter_result(res, elapsed, provider="custom")

        return "custom", _custom_wrapper

    provider = config.provider_for(family)
    if provider == "claude_cli":
        return provider, lambda p, s, *, model_id, timeout_s, rollout_id=0: invoke_claude_cli(
            p,
            s,
            model_id=model_id,
            effort=config.claude_effort,
            timeout_s=timeout_s,
            binary=config.claude_bin,
            cwd=config.fixed_cwd,
            system_prompt=config.system_prompt,
            stripped_prefix=config.stripped_prefix,
            stream_json=config.emit_usage_telemetry,
        )
    if provider == "codex_cli":
        return provider, lambda p, s, *, model_id, timeout_s, rollout_id=0: invoke_codex_cli(
            p,
            s,
            model_id=model_id,
            reasoning_effort=config.codex_reasoning_effort,
            timeout_s=timeout_s,
            binary=config.codex_bin,
            cwd=config.fixed_cwd,
            stripped_prefix=config.stripped_prefix,
            json_events=config.emit_usage_telemetry,
            ephemeral=not config.emit_usage_telemetry,
        )
    if provider == "agy_cli":
        if config.stripped_prefix and config.system_prompt:
            sys_prompt = config.system_prompt
            return provider, lambda p, s, *, model_id, timeout_s, rollout_id=0: invoke_agy_stripped_cli(
                p,
                system_prompt=sys_prompt,
                model_id=model_id,
                timeout_s=timeout_s,
                binary=config.agy_bin,
            )
        return provider, lambda p, s, *, model_id, timeout_s, rollout_id=0: invoke_agy_cli(
            p, s, model_id=model_id, timeout_s=timeout_s, binary=config.agy_bin
        )
    if provider == "gemini_cli":
        return provider, lambda p, s, *, model_id, timeout_s, rollout_id=0: invoke_gemini_cli(
            p, s, model_id=model_id, timeout_s=timeout_s, binary=config.gemini_bin
        )
    raise ValueError(f"No adapter registered for family={family!r} (provider={provider!r})")


def run_family_with_cache(
    *,
    family: str,
    input_text: str,
    prompt_text: str,
    schema: dict[str, Any],
    codebook_version: str,
    cache: SixTupleCache,
    config: RunnerConfig | None = None,
    slice_spec: str = "blind_text_only",
    stage: str = "core_triage",
    parse_fn: Callable[[str], dict[str, Any]] | None = None,
    adapters: Mapping[str, Callable[..., Any]] | None = None,
    model_id: str | None = None,
) -> FamilyRunResult:
    """Run one family behind `SixTupleCache` with bounded JSON parse retries."""
    cfg = config or RunnerConfig()
    resolved_model_id = model_id or cfg.model_id_for(family)
    provider, adapter_fn = _resolve_adapter(family, cfg, adapters)
    active_parse = parse_fn or (lambda raw: default_parse_fn(raw, provider=provider))

    input_digest = sha256_text(input_text)
    prompt_digest = sha256_text(prompt_text)
    schema_digest = canonical_json_sha256(schema)

    last_result: FamilyRunResult | None = None
    for rollout_id in range(max(0, cfg.max_parse_retries) + 1):
        key = make_cache_key(
            input_sha256=input_digest,
            codebook_version=codebook_version,
            model_id=resolved_model_id,
            prompt_hash=prompt_digest,
            schema_hash=schema_digest,
            slice_spec=slice_spec,
            rollout_id=rollout_id,
        )

        entry = cache.get(key)
        if entry is not None:
            if entry.returncode == 0 and entry.error is None:
                try:
                    parsed = active_parse(entry.raw_text)
                    return FamilyRunResult(
                        family=family,
                        model_id=resolved_model_id,
                        cache_hit=True,
                        rollout_id=rollout_id,
                        ok=True,
                        raw_text=entry.raw_text,
                        extracted_json_str=entry.extracted_json_str,
                        parsed=parsed,
                        latency_ms=entry.latency_ms,
                        returncode=entry.returncode,
                        error=None,
                        cache_key=key,
                    )
                except Exception as exc:
                    last_result = FamilyRunResult(
                        family=family,
                        model_id=resolved_model_id,
                        cache_hit=True,
                        rollout_id=rollout_id,
                        ok=False,
                        raw_text=entry.raw_text,
                        extracted_json_str=entry.extracted_json_str,
                        parsed=None,
                        latency_ms=entry.latency_ms,
                        returncode=entry.returncode,
                        error=f"parse_error: {exc}",
                        cache_key=key,
                    )
                    continue
            # Cached non-zero error entry; retry on next rollout_id.
            last_result = FamilyRunResult(
                family=family,
                model_id=resolved_model_id,
                cache_hit=True,
                rollout_id=rollout_id,
                ok=False,
                raw_text=entry.raw_text,
                extracted_json_str=entry.extracted_json_str,
                parsed=None,
                latency_ms=entry.latency_ms,
                returncode=entry.returncode,
                error=entry.error or f"cached returncode={entry.returncode}",
                cache_key=key,
            )
            continue

        # Cache miss: invoke underlying adapter / CLI.
        out = adapter_fn(
            prompt_text,
            schema,
            model_id=resolved_model_id,
            timeout_s=cfg.timeout_s,
            rollout_id=rollout_id,
        )
        if cfg.on_adapter_output is not None:
            cfg.on_adapter_output(family, out)
        now_iso = datetime.now(timezone.utc).isoformat()
        if out.returncode == 0 and out.error is None:
            cache.put(
                CacheEntry(
                    key=key,
                    raw_text=out.raw_text,
                    extracted_json_str=out.extracted_json_str,
                    latency_ms=out.latency_ms,
                    created_at=now_iso,
                    returncode=out.returncode,
                    error=None,
                    family=family,
                    stage=stage,
                )
            )
            try:
                parsed = active_parse(out.raw_text)
                return FamilyRunResult(
                    family=family,
                    model_id=resolved_model_id,
                    cache_hit=False,
                    rollout_id=rollout_id,
                    ok=True,
                    raw_text=out.raw_text,
                    extracted_json_str=out.extracted_json_str,
                    parsed=parsed,
                    latency_ms=out.latency_ms,
                    returncode=out.returncode,
                    error=None,
                    cache_key=key,
                )
            except Exception as exc:
                last_result = FamilyRunResult(
                    family=family,
                    model_id=resolved_model_id,
                    cache_hit=False,
                    rollout_id=rollout_id,
                    ok=False,
                    raw_text=out.raw_text,
                    extracted_json_str=out.extracted_json_str,
                    parsed=None,
                    latency_ms=out.latency_ms,
                    returncode=out.returncode,
                    error=f"parse_error: {exc}",
                    cache_key=key,
                )
                continue

        if cfg.cache_cli_errors:
            cache.put(
                CacheEntry(
                    key=key,
                    raw_text=out.raw_text,
                    extracted_json_str=out.extracted_json_str,
                    latency_ms=out.latency_ms,
                    created_at=now_iso,
                    returncode=out.returncode,
                    error=out.error,
                    family=family,
                    stage=stage,
                )
            )
        last_result = FamilyRunResult(
            family=family,
            model_id=resolved_model_id,
            cache_hit=False,
            rollout_id=rollout_id,
            ok=False,
            raw_text=out.raw_text,
            extracted_json_str=out.extracted_json_str,
            parsed=None,
            latency_ms=out.latency_ms,
            returncode=out.returncode,
            error=out.error or f"adapter exited with code {out.returncode}",
            cache_key=key,
        )
        if out.returncode != 0:
            break

    assert last_result is not None
    return last_result


def run_three_family_parallel(
    *,
    input_text: str,
    prompt_text: str,
    schema: dict[str, Any],
    codebook_version: str,
    cache: SixTupleCache,
    families: Sequence[str] = ("claude", "codex", "gemini"),
    config: RunnerConfig | None = None,
    slice_spec: str = "blind_text_only",
    stage: str = "core_triage",
    parse_fn: Callable[[str], dict[str, Any]] | None = None,
    adapters: Mapping[str, Callable[..., Any]] | None = None,
    model_ids: Mapping[str, str] | None = None,
) -> dict[str, FamilyRunResult]:
    """Run all configured model families concurrently behind `SixTupleCache`."""
    cfg = config or RunnerConfig()
    fam_list = list(families)
    if not fam_list:
        return {}

    workers = max(1, min(cfg.max_workers, len(fam_list)))
    unordered: dict[str, FamilyRunResult] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_fam = {
            pool.submit(
                run_family_with_cache,
                family=fam,
                input_text=input_text,
                prompt_text=prompt_text,
                schema=schema,
                codebook_version=codebook_version,
                cache=cache,
                config=cfg,
                slice_spec=slice_spec,
                stage=stage,
                parse_fn=parse_fn,
                adapters=adapters,
                model_id=model_ids.get(fam) if model_ids else None,
            ): fam
            for fam in fam_list
        }
        for fut in as_completed(future_to_fam):
            fam = future_to_fam[fut]
            unordered[fam] = fut.result()

    return {fam: unordered[fam] for fam in fam_list}


__all__ = [
    "AdapterOutput",
    "DEFAULT_AGY_BIN",
    "DEFAULT_CLAUDE_BIN",
    "DEFAULT_CODEX_BIN",
    "DEFAULT_GEMINI_BIN",
    "DEFAULT_MODEL_IDS",
    "FamilyRunResult",
    "RunnerConfig",
    "UsageGuard",
    "_prepare_stripped_agy_workspace",
    "build_agy_command",
    "build_agy_stripped_command",
    "build_claude_command",
    "build_codex_command",
    "build_gemini_command",
    "default_parse_fn",
    "extract_json_payload",
    "invoke_agy_cli",
    "invoke_agy_stripped_cli",
    "invoke_claude_cli",
    "invoke_codex_cli",
    "invoke_gemini_cli",
    "parse_claude_stream_json",
    "read_codex_rollout_rate_limits",
    "run_family_with_cache",
    "run_three_family_parallel",
    "strip_markdown_fences",
]
