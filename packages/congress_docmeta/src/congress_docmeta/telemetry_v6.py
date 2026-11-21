"""Pre-mask uncertainty telemetry (`H_pre` & `-log Z_valid`) via duck-typed wrapper.

Captures exact raw pre-mask softmax entropy ``H(p_pre)`` and constrained grammar mass
``Z_valid = sum_{v in M_t} p_pre(v)`` (reporting ``neg_log_z = -log(Z_valid)``) per decode
step, tracking all consumed tokens (including ``llguidance`` forced-forward tokens) so
field attribution to active ``DocMetaV4Causal`` top-level keys stays byte-exact over both
single-schema ``GrammarHelper`` and per-doc ``PerDocGrammarHelper`` without modifying
``fast_gemma4``.

Top-level import is 100% Python stdlib (``/usr/bin/python3 -B -I -S`` clean).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Callable, Sequence

from .compact_wire_v6 import INV_COMPACT_TOP_KEY_MAP


def infer_current_json_field(prefix_text: str) -> str:
    """Infer the active canonical top-level DocMeta key from a partial JSON string."""
    depth_obj = 0
    depth_arr = 0
    in_str = False
    esc = False
    top_key = "_preamble"
    i = 0
    n = len(prefix_text)
    while i < n:
        ch = prefix_text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == "{":
            depth_obj += 1
            i += 1
            continue
        if ch == "}":
            depth_obj = max(0, depth_obj - 1)
            i += 1
            continue
        if ch == "[":
            depth_arr += 1
            i += 1
            continue
        if ch == "]":
            depth_arr = max(0, depth_arr - 1)
            i += 1
            continue
        if ch == '"':
            if depth_obj == 1 and depth_arr == 0:
                j = i + 1
                esc_k = False
                chars: list[str] = []
                while j < n:
                    c2 = prefix_text[j]
                    if esc_k:
                        chars.append(c2)
                        esc_k = False
                    elif c2 == "\\":
                        esc_k = True
                    elif c2 == '"':
                        break
                    else:
                        chars.append(c2)
                    j += 1
                if j < n and prefix_text[j] == '"':
                    k_scan = j + 1
                    while k_scan < n and prefix_text[k_scan] in (" ", "\t", "\r", "\n"):
                        k_scan += 1
                    if k_scan < n and prefix_text[k_scan] == ":":
                        raw_k = "".join(chars)
                        top_key = INV_COMPACT_TOP_KEY_MAP.get(raw_k, raw_k)
                i = j + 1
                continue
            in_str = True
        i += 1
    return top_key


def compute_step_uncertainty(logits_1d: Any, allowed_mask: Any) -> tuple[float, float, float]:
    """Return ``(entropy_nats, neg_log_z_valid, z_valid)`` from pre-mask logits and boolean mask."""
    try:
        import numpy as np
    except ImportError:
        vals = [float(x) for x in logits_1d]
        if not vals:
            return 0.0, 0.0, 1.0
        m = max(vals)
        if not math.isfinite(m):
            return 0.0, 0.0, 1.0
        exps = [math.exp(x - m) for x in vals]
        denom = sum(exps)
        if denom <= 0.0 or not math.isfinite(denom):
            return 0.0, 0.0, 1.0
        log_d = math.log(denom)
        h_nats = max(0.0, sum((e / denom) * (log_d + m - x) for e, x in zip(exps, vals)))
        mask_list = [bool(b) for b in allowed_mask]
        if len(mask_list) == len(exps) and any(mask_list):
            z_valid = sum(e / denom for e, ok in zip(exps, mask_list) if ok)
        else:
            z_valid = 1.0
        z_valid = max(1e-12, min(1.0, z_valid))
        return h_nats, max(0.0, -math.log(z_valid)), z_valid

    arr = np.asarray(logits_1d, dtype=np.float64)
    if arr.size == 0:
        return 0.0, 0.0, 1.0
    m = float(np.max(arr))
    if not math.isfinite(m):
        return 0.0, 0.0, 1.0
    exps = np.exp(arr - m)
    denom = float(np.sum(exps))
    if denom <= 0.0 or not math.isfinite(denom):
        return 0.0, 0.0, 1.0
    probs = exps / denom
    h_nats = max(0.0, float(np.sum(probs * (math.log(denom) + m - arr))))
    mask_arr = np.asarray(allowed_mask, dtype=bool)
    if mask_arr.shape == probs.shape and bool(np.any(mask_arr)):
        z_valid = float(np.sum(probs[mask_arr]))
    else:
        z_valid = 1.0
    z_valid = max(1e-12, min(1.0, z_valid))
    neg_log_z = max(0.0, -math.log(z_valid))
    return h_nats, neg_log_z, z_valid


@dataclass
class FieldUncertaintySummary:
    steps: int = 0
    mean_h_pre: float = 0.0
    max_h_pre: float = 0.0
    mean_neg_log_z: float = 0.0
    max_neg_log_z: float = 0.0
    min_z_valid: float = 1.0
    masked_interventions: int = 0
    by_field: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_flat_features(self) -> dict[str, float]:
        out: dict[str, float] = {
            "tel_steps": float(self.steps),
            "tel_mean_h_pre": round(self.mean_h_pre, 6),
            "tel_max_h_pre": round(self.max_h_pre, 6),
            "tel_mean_neg_log_z": round(self.mean_neg_log_z, 6),
            "tel_max_neg_log_z": round(self.max_neg_log_z, 6),
            "tel_min_z_valid": round(self.min_z_valid, 6),
            "tel_masked_interventions": float(self.masked_interventions),
        }
        for fk in ("primary_kind", "committees", "date_spans", "doc_date", "personas"):
            fd = self.by_field.get(fk) or {}
            out[f"tel_{fk}_max_h"] = round(float(fd.get("max_h_pre", 0.0)), 6)
            out[f"tel_{fk}_mean_h"] = round(float(fd.get("mean_h_pre", 0.0)), 6)
            out[f"tel_{fk}_max_nlz"] = round(float(fd.get("max_neg_log_z", 0.0)), 6)
        return out


def summarize_records(recs: list[tuple[str, float, float, bool]]) -> FieldUncertaintySummary:
    if not recs:
        return FieldUncertaintySummary()
    hs = [r[1] for r in recs]
    nlzs = [r[2] for r in recs]
    by_f_raw: dict[str, list[tuple[float, float, bool]]] = {}
    for fn, h, nlz, masked in recs:
        by_f_raw.setdefault(fn, []).append((h, nlz, masked))
    by_f: dict[str, dict[str, float]] = {}
    for fn, items in by_f_raw.items():
        f_hs = [x[0] for x in items]
        f_nlzs = [x[1] for x in items]
        by_f[fn] = {
            "steps": float(len(items)),
            "mean_h_pre": sum(f_hs) / len(items),
            "max_h_pre": max(f_hs),
            "mean_neg_log_z": sum(f_nlzs) / len(items),
            "max_neg_log_z": max(f_nlzs),
            "masked_interventions": float(sum(1 for x in items if x[2])),
        }
    return FieldUncertaintySummary(
        steps=len(recs),
        mean_h_pre=sum(hs) / len(hs),
        max_h_pre=max(hs),
        mean_neg_log_z=sum(nlzs) / len(nlzs),
        max_neg_log_z=max(nlzs),
        min_z_valid=math.exp(-max(nlzs)),
        masked_interventions=sum(1 for r in recs if r[3]),
        by_field=by_f,
    )


class TelemetryMatcherProxyV6:
    """Matcher proxy tracking consumed UTF-8 bytes across masked picks and FF fast-forwarding."""

    def __init__(
        self,
        inner: Any,
        buf: bytearray,
        ltok: Any,
        *,
        doc_idx: int | None = None,
    ) -> None:
        self._inner = inner
        self._buf = buf
        self._ltok = ltok
        self.doc_idx = doc_idx
        self.recs: list[tuple[str, float, float, bool]] = []

    def _append_tokens(self, toks: Sequence[int]) -> None:
        for t in toks:
            self._buf.extend(self._ltok.decode_bytes([int(t)]))

    def current_field(self) -> str:
        return infer_current_json_field(bytes(self._buf).decode("utf-8", errors="replace"))

    def consume_token(self, tok_id: int) -> bool:
        ok = bool(self._inner.consume_token(int(tok_id)))
        if ok:
            self._append_tokens((int(tok_id),))
        return ok

    def consume_tokens(self, tokens: Sequence[int]) -> bool:
        toks = [int(t) for t in tokens]
        ok = bool(self._inner.consume_tokens(toks))
        if ok:
            self._append_tokens(toks)
        return ok

    def try_consume_tokens(self, tokens: Sequence[int]) -> int:
        toks = [int(t) for t in tokens]
        n = int(self._inner.try_consume_tokens(toks))
        if n > 0:
            self._append_tokens(toks[:n])
        return n

    def compute_ff_tokens(self) -> list[int]:
        return list(self._inner.compute_ff_tokens())

    def unsafe_compute_mask_ptr(self, ptr: int, nbytes: int) -> None:
        self._inner.unsafe_compute_mask_ptr(ptr, nbytes)

    def validate_tokens(self, tokens: Sequence[int]) -> bool:
        return bool(self._inner.validate_tokens(tokens))

    def is_stopped(self) -> bool:
        return bool(self._inner.is_stopped())

    def is_accepting(self) -> bool:
        return bool(self._inner.is_accepting())

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def can_wrap_grammar_helper_for_telemetry(gh: Any) -> bool:
    """Return True iff `gh` (or its wrapped `_gh_std`) exposes full llguidance mask buffers."""
    if gh is None:
        return False
    base_gh = getattr(gh, "_gh_std", gh)
    return (
        callable(getattr(gh, "pick_valid_token", None))
        and callable(getattr(gh, "new_matcher", None))
        and hasattr(base_gh, "_mask_lock")
        and hasattr(base_gh, "_mask_ptr")
        and hasattr(base_gh, "_mask_nbytes")
        and hasattr(base_gh, "_mask_buf")
        and hasattr(base_gh, "k_word")
        and hasattr(base_gh, "k_bit")
        and getattr(base_gh, "ltok", None) is not None
    )


class TelemetryPerDocWrapperV6:
    """Duck-typed wrapper capturing per-doc ``(H_pre, -log Z_valid)`` over any grammar helper.

    Pair with ``run_rolling(..., temperature=1e-4)`` and ``force_greedy=True`` so the model
    materializes pre-mask logits while token selection inside ``pick_valid_token`` remains
    strictly greedy (``temperature=0.0``). Works identically over both ``GrammarHelper``
    and ``PerDocGrammarHelper`` without recompiling ``llguidance`` grammars.
    """

    def __init__(self, inner_gh: Any, *, force_greedy: bool = True) -> None:
        if not can_wrap_grammar_helper_for_telemetry(inner_gh):
            raise TypeError(
                "TelemetryPerDocWrapperV6 requires a GrammarHelper or PerDocGrammarHelper with "
                "llguidance mask buffers (_mask_lock, _mask_ptr, _mask_buf, k_word, k_bit, ltok)."
            )
        self._inner_gh = inner_gh
        self._base_gh = getattr(inner_gh, "_gh_std", inner_gh)
        self.tok = getattr(inner_gh, "tok", getattr(inner_gh, "tokenizer", getattr(self._base_gh, "tok", None)))
        self.tokenizer = self.tok
        self.ltok = getattr(inner_gh, "ltok", getattr(self._base_gh, "ltok", None))
        self.upfront_ff = list(getattr(inner_gh, "upfront_ff", getattr(self._base_gh, "upfront_ff", ())) or ())
        self.new_to_old = getattr(inner_gh, "new_to_old", getattr(self._base_gh, "new_to_old", None))
        self.force_greedy = bool(force_greedy)
        self._matchers: list[TelemetryMatcherProxyV6] = []
        self._matchers_by_doc: dict[int, TelemetryMatcherProxyV6] = {}

    def reset_traces(self) -> None:
        self._matchers.clear()
        self._matchers_by_doc.clear()

    def _seed_upfront_buffer(self, up_ff: Sequence[int]) -> bytearray:
        buf = bytearray()
        for tid in up_ff:
            buf.extend(self.ltok.decode_bytes([int(tid)]))
        return buf

    def upfront_ff_for_doc(self, doc_idx: int) -> list[int]:
        inner_fn = getattr(self._inner_gh, "upfront_ff_for_doc", None)
        if callable(inner_fn):
            return list(inner_fn(int(doc_idx)))
        return list(self.upfront_ff)

    def new_matcher_for_doc(self, doc_idx: int) -> TelemetryMatcherProxyV6:
        d_i = int(doc_idx)
        by_doc = getattr(self._inner_gh, "new_matcher_for_doc", None)
        inner_m = by_doc(d_i) if callable(by_doc) else self._inner_gh.new_matcher()
        up_ff = self.upfront_ff_for_doc(d_i)
        proxy = TelemetryMatcherProxyV6(inner_m, self._seed_upfront_buffer(up_ff), self.ltok, doc_idx=d_i)
        self._matchers.append(proxy)
        self._matchers_by_doc[d_i] = proxy
        return proxy

    def new_matcher(self) -> TelemetryMatcherProxyV6:
        inner_m = self._inner_gh.new_matcher()
        doc_idx = getattr(inner_m, "doc_idx", None)
        up_ff = self.upfront_ff_for_doc(int(doc_idx)) if doc_idx is not None else self.upfront_ff
        proxy = TelemetryMatcherProxyV6(inner_m, self._seed_upfront_buffer(up_ff), self.ltok, doc_idx=doc_idx)
        self._matchers.append(proxy)
        if doc_idx is not None:
            self._matchers_by_doc[int(doc_idx)] = proxy
        return proxy

    def pick_valid_token(
        self,
        matcher: Any,
        logits_1d: Any | Callable[[], Any],
        argmax_idx: int,
        *,
        temperature: float = 0.0,
        top_p: float = 1.0,
        rng: Any = None,
        fallback_to_full_vocab: bool = False,
        full_logits_1d: Any | Callable[[], Any] | None = None,
    ) -> tuple[int, bool]:
        import numpy as np

        eff_temp = 0.0 if self.force_greedy else float(temperature)
        logits_arr = np.asarray(logits_1d() if callable(logits_1d) else logits_1d)
        base_gh = self._base_gh
        with base_gh._mask_lock:
            matcher.unsafe_compute_mask_ptr(base_gh._mask_ptr, base_gh._mask_nbytes)
            allowed = (((base_gh._mask_buf[base_gh.k_word] >> base_gh.k_bit) & 1) != 0).copy()
        tok_id, was_masked = self._inner_gh.pick_valid_token(
            matcher,
            logits_arr,
            argmax_idx,
            temperature=eff_temp,
            top_p=top_p,
            rng=rng,
            fallback_to_full_vocab=fallback_to_full_vocab,
            full_logits_1d=full_logits_1d,
        )
        if isinstance(matcher, TelemetryMatcherProxyV6):
            field_name = matcher.current_field()
            vocab_sz = int(base_gh.ltok.vocab_size)
            n2o = getattr(base_gh, "new_to_old", None)
            pruned_logits = (
                logits_arr[n2o]
                if (n2o is not None and len(logits_arr) >= vocab_sz and len(n2o) < len(logits_arr))
                else logits_arr
            )
            h_pre, nlz, _ = compute_step_uncertainty(pruned_logits, allowed)
            matcher.recs.append((field_name, h_pre, nlz, bool(was_masked)))
        return int(tok_id), bool(was_masked)

    def validate_token_sequence(self, full_ids: Sequence[int]) -> bool:
        return bool(self._inner_gh.validate_token_sequence(full_ids))

    def summarize_matcher(self, matcher: TelemetryMatcherProxyV6) -> FieldUncertaintySummary:
        return summarize_records(matcher.recs)

    def summarize_all_matchers(self) -> list[FieldUncertaintySummary]:
        return [summarize_records(m.recs) for m in self._matchers]

    def summarize_doc(self, doc_idx: int) -> FieldUncertaintySummary:
        proxy = self._matchers_by_doc.get(int(doc_idx))
        if proxy is None:
            return FieldUncertaintySummary()
        return summarize_records(proxy.recs)

    def summarize_docs(self, n_docs: int) -> list[FieldUncertaintySummary]:
        return [self.summarize_doc(i) for i in range(n_docs)]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner_gh, name)


def create_telemetry_grammar_helper(
    tokenizer: Any,
    schema: str | dict[str, Any],
    new_to_old: Any = None,
    *,
    whitespace_flexible: bool = False,
    max_whitespace_run: int | None = None,
    eos_token_id: int | None = None,
    force_greedy: bool = True,
) -> TelemetryPerDocWrapperV6:
    """Construct a standalone telemetry-enabled ``GrammarHelper`` wrapper."""
    from fast_gemma4.grammar import GrammarHelper

    gh = GrammarHelper(
        tokenizer,
        schema,
        new_to_old,
        whitespace_flexible=whitespace_flexible,
        max_whitespace_run=max_whitespace_run,
        eos_token_id=eos_token_id,
    )
    return TelemetryPerDocWrapperV6(gh, force_greedy=force_greedy)


__all__ = [
    "FieldUncertaintySummary",
    "TelemetryMatcherProxyV6",
    "TelemetryPerDocWrapperV6",
    "can_wrap_grammar_helper_for_telemetry",
    "compute_step_uncertainty",
    "create_telemetry_grammar_helper",
    "infer_current_json_field",
    "summarize_records",
]
