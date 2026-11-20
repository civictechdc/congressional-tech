"""Verification tests for V6.3 validator training optimizations (P0.1, P0.2, P1.5, P2.8, P2.9).

Proves:
  - `fast-ir-guard --strict-bool-mask --coreml --act-dtype bfloat16` passes with 0 errors and 0 warnings.
  - P0.1 + P0.2: Pre-cast BF16 frozen weights + BF16 `head.layers.{0,1}` + `@mx.compile` ops/AdamW match
    the original FP32-head baseline (`|Δloss| < 1e-3`, trainable grad cosine `>= 0.999`).
  - P1.5: Varlen sequence packing with per-segment RoPE `position_ids` reset and block-diagonal Full/SWA
    segment masks has 0.0 cross-segment leakage, 0.0 pad leakage, exact per-item loss normalization (no
    `K×` effective LR shift), `|Δloss| < 1e-3`, and trainable grad cosine `>= 0.999` vs unpacked batches.
  - P2.8: `FrozenTrunkActivationCache` matches live frozen trunk (`|Δloss| < 1e-3`, grad cosine `>= 0.999`)
    for both unpacked and packed steps, hits with 0 frozen trunk calls on reuse, and invalidates cleanly on
    sequence, config, frozen weight, or `freeze_below_layer` changes.
  - P2.9: `Kev-0.8B` teacher scoring groups clean + corrupted candidates by source document, prefills the
    shared document prefix once per document, and matches naive `score_multi_states_noul` (verified on both
    a causal backbone unit harness and live `W8 Kev-0.8B` when artifacts are present).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import math
from pathlib import Path
import random
from typing import Any

import numpy as np
import pytest

pytest.importorskip("mlx.core", reason="needs fast-silicon MLX environment")
pytest.importorskip("fast_decision_models", reason="needs fast-decision-models in fast-silicon venv")

from fast_decision_models.paths import resolve_kev_dir  # noqa: E402

PKG_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PKG_ROOT / "scripts" / "train_v63_validators.py"
KEV_ARTIFACTS_DIR = resolve_kev_dir()
GOLD_JSONL_PATH = (
    PKG_ROOT.parents[1]
    / ".cache"
    / "archive-release"
    / "docmeta-v6-20261116"
    / "lookups_and_gold"
    / "train_v6_3_complete_ssot_gold.jsonl"
)


def _load_script_module() -> Any:
    spec = importlib.util.spec_from_file_location("train_v63_validators_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tv63 = _load_script_module()


def _make_mini_enc_cfg(
    *,
    n_layers: int = 6,
    hidden_size: int = 128,
    n_heads: int = 4,
    intermediate_size: int = 256,
    local_attention: int = 16,
    vocab_size: int = 512,
) -> dict[str, Any]:
    layer_types = ["full_attention" if i % 3 == 0 else "sliding_attention" for i in range(n_layers)]
    return {
        "hidden_size": hidden_size,
        "num_hidden_layers": n_layers,
        "num_attention_heads": n_heads,
        "intermediate_size": intermediate_size,
        "local_attention": local_attention,
        "layer_types": layer_types,
        "norm_eps": 1e-5,
        "vocab_size": vocab_size,
        "rope_parameters": {
            "full_attention": {"rope_theta": 160000.0},
            "sliding_attention": {"rope_theta": 10000.0},
        },
    }


def _make_synthetic_weights(enc_cfg: dict[str, Any], seed: int = 1234) -> dict[str, Any]:
    import mlx.core as mx

    rng = np.random.default_rng(seed)
    H = int(enc_cfg["hidden_size"])
    I = int(enc_cfg["intermediate_size"])
    V = int(enc_cfg["vocab_size"])
    n_layers = int(enc_cfg["num_hidden_layers"])
    scale = 0.04

    def _w(shape: tuple[int, ...], s: float = scale) -> Any:
        return mx.array((rng.standard_normal(shape) * s).astype(np.float32))

    def _ones(shape: tuple[int, ...]) -> Any:
        return mx.array((1.0 + rng.standard_normal(shape) * 0.05).astype(np.float32))

    def _bias(shape: tuple[int, ...]) -> Any:
        return mx.array((rng.standard_normal(shape) * 0.02).astype(np.float32))

    w: dict[str, Any] = {
        "encoder.embeddings.tok_embeddings.weight": _w((V, H), 0.1),
        "encoder.embeddings.norm.weight": _ones((H,)),
        "encoder.final_norm.weight": _ones((H,)),
        "type_emb.weight": _w((3, H), 0.08),
        "scorer.0.weight": _ones((H,)),
        "scorer.0.bias": _bias((H,)),
        "scorer.1.weight": _w((H, H)),
        "scorer.1.bias": _bias((H,)),
        "scorer.3.weight": _w((1, H)),
        "scorer.3.bias": _bias((1,)),
    }
    for i in range(n_layers):
        px = f"encoder.layers.{i}."
        if i > 0:
            w[px + "attn_norm.weight"] = _ones((H,))
        w[px + "attn.Wqkv.weight"] = _w((3 * H, H))
        w[px + "attn.Wo.weight"] = _w((H, H))
        w[px + "mlp_norm.weight"] = _ones((H,))
        w[px + "mlp.Wi.weight"] = _w((2 * I, H))
        w[px + "mlp.Wo.weight"] = _w((H, I))

    for hi in range(2):
        hp = f"head.layers.{hi}."
        w[hp + "norm1.weight"] = _ones((H,))
        w[hp + "norm1.bias"] = _bias((H,))
        w[hp + "self_attn.in_proj_weight"] = _w((3 * H, H))
        w[hp + "self_attn.in_proj_bias"] = _bias((3 * H,))
        w[hp + "self_attn.out_proj.weight"] = _w((H, H))
        w[hp + "self_attn.out_proj.bias"] = _bias((H,))
        w[hp + "norm2.weight"] = _ones((H,))
        w[hp + "norm2.bias"] = _bias((H,))
        w[hp + "linear1.weight"] = _w((2 * H, H))
        w[hp + "linear1.bias"] = _bias((2 * H,))
        w[hp + "linear2.weight"] = _w((H, 2 * H))
        w[hp + "linear2.bias"] = _bias((H,))

    mx.eval(w)
    return w


def _make_synthetic_items(
    n_items: int,
    *,
    vocab_size: int = 512,
    min_len: int = 24,
    max_len: int = 110,
    seed: int = 2026,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    items: list[dict[str, Any]] = []
    for idx in range(n_items):
        ln = rng.randint(min_len, max_len)
        ids = [rng.randint(10, vocab_size - 10) for _ in range(ln)]
        qtype = idx % 3
        if qtype == 2:
            k = 2
            markers = [2, 6]
            soft_p1 = round(rng.uniform(0.1, 0.9), 3) if (idx % 2 == 0) else None
            task = "doc_noul_primary_kind"
        elif qtype == 0:
            k = 6 if (idx % 2 == 0) else 10
            markers = [2 + 2 * j for j in range(k)]
            soft_p1 = None
            task = "router_choice" if k == 6 else "persona_role_choice"
        else:
            k = 4
            markers = [3 + 3 * j for j in range(k)]
            soft_p1 = None
            task = "score_item"
        items.append(
            {
                "ids": ids,
                "markers": markers,
                "qtype": qtype,
                "target": rng.randrange(k),
                "soft_p1": soft_p1,
                "task": task,
            }
        )
    return items


def _legacy_fp32_head_reference(
    raw_weights: dict[str, Any],
    enc_cfg: dict[str, Any],
    freeze_below_layer: int,
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    """Exact pre-fix reference implementation (manual FP32 LN + per-step casts + FP32 head SDPA)."""
    import mlx.core as mx
    import mlx.nn as nn

    H = int(enc_cfg["hidden_size"])
    n_layers = int(enc_cfg["num_hidden_layers"])
    n_heads = int(enc_cfg["num_attention_heads"])
    hd = H // n_heads
    attn_scale = 1.0 / math.sqrt(hd)
    layer_types = list(enc_cfg["layer_types"])
    local_window = int(enc_cfg.get("local_attention", 128))
    rope_params = enc_cfg.get("rope_parameters", {})
    theta_full = float(rope_params.get("full_attention", {}).get("rope_theta", 160000.0))
    theta_swa = float(rope_params.get("sliding_attention", {}).get("rope_theta", 10000.0))

    def _rope_tables(max_s: int, theta: float) -> tuple[Any, Any]:
        half = hd // 2
        inv_freq = 1.0 / (theta ** (np.arange(half, dtype=np.float64) / half))
        angles = np.arange(max_s, dtype=np.float64)[:, None] * inv_freq[None, :]
        cos = mx.array(np.cos(angles).astype(np.float32)[None, None, :, :])
        sin = mx.array(np.sin(angles).astype(np.float32)[None, None, :, :])
        return cos, sin

    cos_full, sin_full = _rope_tables(512, theta_full)
    cos_swa, sin_swa = _rope_tables(512, theta_swa)
    idx_512 = np.arange(512)
    swa_allow = np.abs(idx_512[:, None] - idx_512[None, :]) <= (local_window // 2)
    swa_bias_512 = mx.array(np.where(swa_allow, 0.0, -10000.0).astype(np.float32)[None, None, :, :])

    def _apply_rope(x: Any, cos_t: Any, sin_t: Any, S: int) -> Any:
        c = cos_t[:, :, :S, :].astype(x.dtype)
        s = sin_t[:, :, :S, :].astype(x.dtype)
        x0, x1 = mx.split(x, 2, axis=-1)
        return mx.concatenate([x0 * c - x1 * s, x1 * c + x0 * s], axis=-1)

    def _ln_nobias(x: Any, w: Any) -> Any:
        xf = x.astype(mx.float32)
        mn = mx.mean(xf, axis=-1, keepdims=True)
        xc = xf - mn
        vr = mx.mean(xc * xc, axis=-1, keepdims=True)
        xn = xc * mx.rsqrt(vr + 1e-5)
        return (xn * w.astype(mx.float32)).astype(x.dtype)

    def _ln_bias(x: Any, w: Any, b: Any) -> Any:
        xf = x.astype(mx.float32)
        mn = mx.mean(xf, axis=-1, keepdims=True)
        xc = xf - mn
        vr = mx.mean(xc * xc, axis=-1, keepdims=True)
        xn = xc * mx.rsqrt(vr + 1e-5)
        return (xn * w.astype(mx.float32) + b.astype(mx.float32)).astype(x.dtype)

    frozen: dict[str, Any] = {}
    trainable: dict[str, Any] = {}
    for k, v in raw_weights.items():
        is_train = False
        if k.startswith(("head.", "scorer.", "type_emb.", "encoder.final_norm.")):
            is_train = True
        elif k.startswith("encoder.layers.") and int(k.split(".")[2]) >= freeze_below_layer:
            is_train = True
        if is_train:
            trainable[k] = v.astype(mx.float32)
        else:
            frozen[k] = v.astype(mx.bfloat16)
    mx.eval(frozen, trainable)

    def forward_logits(params: dict[str, Any], ids: Any, valid_lens: Any, qtypes: Any) -> Any:
        B, S = ids.shape
        pos = mx.arange(S)[None, :]
        valid_2d = pos < valid_lens[:, None]
        ext_mask = mx.where(valid_2d[:, None, None, :], 0.0, -10000.0).astype(mx.bfloat16)
        swa_mask = ext_mask + swa_bias_512[:, :, :S, :S].astype(mx.bfloat16)

        tok_emb = mx.take(frozen["encoder.embeddings.tok_embeddings.weight"], ids, axis=0)
        cur = _ln_nobias(tok_emb, frozen["encoder.embeddings.norm.weight"])

        for i in range(n_layers):
            px = f"encoder.layers.{i}."
            src = frozen if i < freeze_below_layer else params
            is_full = layer_types[i] == "full_attention"
            x_attn = cur if i == 0 else _ln_nobias(cur, src[px + "attn_norm.weight"])
            wqkv = src[px + "attn.Wqkv.weight"].astype(mx.bfloat16)
            qkv = x_attn @ wqkv.T
            qt, kt, vt = mx.split(qkv, 3, axis=-1)
            qh = qt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            kh = kt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            vh = vt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            c_t, s_t = (cos_full, sin_full) if is_full else (cos_swa, sin_swa)
            qrp = _apply_rope(qh, c_t, s_t, S)
            krp = _apply_rope(kh, c_t, s_t, S)
            att = mx.fast.scaled_dot_product_attention(
                qrp, krp, vh, scale=attn_scale, mask=(ext_mask if is_full else swa_mask)
            )
            att_flat = att.transpose(0, 2, 1, 3).reshape(B, S, H)
            wo = src[px + "attn.Wo.weight"].astype(mx.bfloat16)
            cur = cur + (att_flat @ wo.T)

            x_mlp = _ln_nobias(cur, src[px + "mlp_norm.weight"])
            wi = src[px + "mlp.Wi.weight"].astype(mx.bfloat16)
            val_h, gate_h = mx.split(x_mlp @ wi.T, 2, axis=-1)
            geglu = nn.gelu(val_h) * gate_h
            wom = src[px + "mlp.Wo.weight"].astype(mx.bfloat16)
            cur = cur + (geglu @ wom.T)

            if i == freeze_below_layer - 1:
                cur = mx.stop_gradient(cur)

        h = _ln_nobias(cur, params["encoder.final_norm.weight"]).astype(mx.float32)
        t_vec = mx.take(params["type_emb.weight"], qtypes, axis=0)[:, None, :]
        h = h + t_vec

        ext_f32 = ext_mask.astype(mx.float32)
        for hi in range(2):
            hp = f"head.layers.{hi}."
            hn1 = _ln_bias(h, params[hp + "norm1.weight"], params[hp + "norm1.bias"])
            hqkv = hn1 @ params[hp + "self_attn.in_proj_weight"].T + params[hp + "self_attn.in_proj_bias"]
            hqt, hkt, hvt = mx.split(hqkv, 3, axis=-1)
            hqh = hqt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            hkh = hkt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            hvh = hvt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            hatt = mx.fast.scaled_dot_product_attention(  # guard: allow-fp32-mask
                hqh, hkh, hvh, scale=attn_scale, mask=ext_f32
            )
            hatt_flat = hatt.transpose(0, 2, 1, 3).reshape(B, S, H)
            h = h + (hatt_flat @ params[hp + "self_attn.out_proj.weight"].T + params[hp + "self_attn.out_proj.bias"])
            hn2 = _ln_bias(h, params[hp + "norm2.weight"], params[hp + "norm2.bias"])
            hl1 = nn.relu(hn2 @ params[hp + "linear1.weight"].T + params[hp + "linear1.bias"])
            h = h + (hl1 @ params[hp + "linear2.weight"].T + params[hp + "linear2.bias"])

        sn = _ln_bias(h, params["scorer.0.weight"], params["scorer.0.bias"])
        sg = nn.gelu(sn @ params["scorer.1.weight"].T + params["scorer.1.bias"])
        pos_logits = (sg @ params["scorer.3.weight"].T + params["scorer.3.bias"]).squeeze(-1)
        return pos_logits

    return frozen, trainable, forward_logits


def _grad_cosine_stats(grads_a: dict[str, Any], grads_b: dict[str, Any]) -> tuple[float, float, str]:
    assert set(grads_a.keys()) == set(grads_b.keys())
    flat_a: list[np.ndarray] = []
    flat_b: list[np.ndarray] = []
    min_cos = 1.0
    min_key = ""
    for k in sorted(grads_a.keys()):
        a = np.asarray(grads_a[k], dtype=np.float64).ravel()
        b = np.asarray(grads_b[k], dtype=np.float64).ravel()
        flat_a.append(a)
        flat_b.append(b)
        na = float(np.linalg.norm(a))
        nb = float(np.linalg.norm(b))
        if na > 1e-8 and nb > 1e-8:
            c = float(np.dot(a, b) / (na * nb))
            if c < min_cos:
                min_cos = c
                min_key = k
    va = np.concatenate(flat_a)
    vb = np.concatenate(flat_b)
    global_cos = float(np.dot(va, vb) / max(float(np.linalg.norm(va) * np.linalg.norm(vb)), 1e-12))
    return global_cos, min_cos, min_key


def _compute_loss_and_grads_from_batch(
    model: Any,
    params: dict[str, Any],
    batch: dict[str, Any],
    *,
    frozen_cache: Any = None,
) -> tuple[float, dict[str, Any]]:
    import mlx.core as mx

    ids_np = batch["ids"]
    B_rows, S_len = int(ids_np.shape[0]), int(ids_np.shape[1])
    if batch["packed"]:
        vl_mx = None
        qt_mx = None
        pos_mx = mx.array(batch["pos_ids"])
        seg_mx = mx.array(batch["seg_ids"])
        tok_qt_mx = mx.array(batch["token_qtypes"])
    else:
        vl_mx = mx.array(batch["valid_lens"])
        qt_mx = mx.array(batch["qtypes"])
        pos_mx = None
        seg_mx = None
        tok_qt_mx = None

    full_mask, swa_mask = model.build_attention_masks(
        S_len, valid_lens=vl_mx, pos_ids=pos_mx, seg_ids=seg_mx
    )
    rope_tables = model.prepare_rope(S_len, pos_ids=pos_mx)
    if frozen_cache is not None:
        h_frozen = frozen_cache.gather_batch(batch["item_spans"], B_rows, S_len)
    else:
        h_frozen = mx.stop_gradient(
            model.run_frozen_trunk(
                mx.array(ids_np),
                valid_lens=vl_mx,
                pos_ids=pos_mx,
                seg_ids=seg_mx,
                full_mask=full_mask,
                swa_mask=swa_mask,
                rope_tables=rope_tables,
            )
        )

    flat_mk_mx = mx.array(batch["flat_mk_idx"])
    mkv_mx = mx.array(batch["mk_valid"])
    tgt_mx = mx.array(batch["targets"])
    sp1_mx = mx.array(batch["soft_p1"])
    hsp_mx = mx.array(batch["has_soft"])
    invt_mx = mx.array(batch["inv_temp"])
    iv_mx = mx.array(batch["item_valid"])

    def _loss(p: dict[str, Any]) -> Any:
        pos_logits = model.forward_from_frozen(
            p,
            h_frozen,
            qtypes=qt_mx,
            token_qtypes=tok_qt_mx,
            full_mask=full_mask,
            swa_mask=swa_mask,
            rope_tables=rope_tables,
        )
        return model.compute_pointer_loss(
            pos_logits, flat_mk_mx, mkv_mx, tgt_mx, sp1_mx, hsp_mx, invt_mx, iv_mx
        )

    loss_v, grads = mx.value_and_grad(_loss)(params)
    mx.eval(loss_v, grads)
    return float(loss_v.item()), grads


# ---------------------------------------------------------------------------
# 1. Static IR / AST Hygiene (`fast-ir-guard` + zero per-step frozen weight cast)
# ---------------------------------------------------------------------------


def test_fast_ir_guard_and_frozen_weight_cast_hygiene() -> None:
    from fast_shared.ir_dtype_guard import check_mlx_file

    report = check_mlx_file(
        SCRIPT_PATH,
        flag_bool_sdpa_as_error=True,
        expected_act_dtype="bfloat16",
        check_coreml_ast=True,
    )
    assert len(report.errors) == 0, [f.format() for f in report.errors]
    assert len(report.warnings) == 0, [f.format() for f in report.warnings]

    # Verify AST of `LayaMlxModel.run_frozen_trunk` has ZERO `.astype(...)` calls.
    src = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(SCRIPT_PATH))
    found_run_frozen = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run_frozen_trunk":
            found_run_frozen = True
            astype_calls = [
                sub.lineno
                for sub in ast.walk(node)
                if isinstance(sub, ast.Attribute) and sub.attr == "astype"
            ]
            assert astype_calls == [], f"Unexpected per-step .astype() inside run_frozen_trunk at lines {astype_calls}"
    assert found_run_frozen, "LayaMlxModel.run_frozen_trunk not found"


# ---------------------------------------------------------------------------
# 2. P0.1 + P0.2: BF16 Head + Pre-cast Frozen Weights Parity
# ---------------------------------------------------------------------------


def test_bf16_head_step0_loss_and_grad_parity() -> None:
    import mlx.core as mx

    with tv63.acquire_hw_lock("test_bf16_head_parity"):
        enc_cfg = _make_mini_enc_cfg(n_layers=6, hidden_size=128, n_heads=4, intermediate_size=256)
        raw_w = _make_synthetic_weights(enc_cfg, seed=101)
        items = _make_synthetic_items(8, vocab_size=512, min_len=30, max_len=96, seed=202)
        batch = tv63.build_unpacked_batch(items, seq_len=128, pad_id=502, k_max=16)

        _, ref_params, ref_fwd = _legacy_fp32_head_reference(raw_w, enc_cfg, freeze_below_layer=4)
        frozen_w, fast_params, fast_fwd = tv63.build_mlx_laya_trainer(raw_w, enc_cfg, freeze_below_layer=4)
        model = fast_fwd.model

        # Verify ALL frozen tensors are pre-cast to BF16 once at initialization.
        assert len(frozen_w) > 0
        for k, v in frozen_w.items():
            assert v.dtype == mx.bfloat16, f"Frozen tensor {k} has dtype {v.dtype}, expected bfloat16"

        # Reference step-0 loss & grads
        ids_mx = mx.array(batch["ids"])
        vl_mx = mx.array(batch["valid_lens"])
        qt_mx = mx.array(batch["qtypes"])
        flat_mk_mx = mx.array(batch["flat_mk_idx"])
        mkv_mx = mx.array(batch["mk_valid"])
        tgt_mx = mx.array(batch["targets"])
        sp1_mx = mx.array(batch["soft_p1"])
        hsp_mx = mx.array(batch["has_soft"])
        invt_mx = mx.array(batch["inv_temp"])
        iv_mx = mx.array(batch["item_valid"])

        def _ref_loss(p: dict[str, Any]) -> Any:
            pos_logits = ref_fwd(p, ids_mx, vl_mx, qt_mx)
            return model.compute_pointer_loss(
                pos_logits, flat_mk_mx, mkv_mx, tgt_mx, sp1_mx, hsp_mx, invt_mx, iv_mx
            )

        ref_loss_v, ref_grads = mx.value_and_grad(_ref_loss)(ref_params)
        mx.eval(ref_loss_v, ref_grads)
        ref_loss = float(ref_loss_v.item())

        fast_loss, fast_grads = _compute_loss_and_grads_from_batch(model, fast_params, batch)
        delta_loss = abs(fast_loss - ref_loss)
        global_cos, min_cos, min_key = _grad_cosine_stats(ref_grads, fast_grads)

        assert delta_loss < 1e-3, f"Step-0 |Δloss|={delta_loss:.6f} >= 1e-3 (ref={ref_loss}, fast={fast_loss})"
        assert global_cos >= 0.999, f"Global trainable grad cosine={global_cos:.6f} < 0.999"
        # Note: 1D ReLU biases (`head.layers.*.linear1.bias`) have hard 0/1 subgradient flips at 0.0 under BF16 rounding.
        assert min_cos >= 0.990, f"Worst param grad cosine={min_cos:.6f} on {min_key}"


# ---------------------------------------------------------------------------
# 3. P0.2: Compiled GPU Global-Norm Clipping + AdamW Update Parity
# ---------------------------------------------------------------------------


def test_compiled_optimizer_step_parity_and_lr_schedule() -> None:
    import mlx.core as mx
    import mlx.optimizers as optim

    with tv63.acquire_hw_lock("test_compiled_opt_parity"):
        p_ref = {
            "w": mx.ones((32, 32), dtype=mx.float32) * 0.5,
            "b": mx.zeros((32,), dtype=mx.float32),
        }
        p_cmp = {k: mx.array(np.asarray(v)) for k, v in p_ref.items()}
        opt_ref = optim.AdamW(learning_rate=1e-2, weight_decay=0.01)
        opt_cmp = optim.AdamW(learning_rate=1e-2, weight_decay=0.01)
        compiled_step, opt_state = tv63.make_compiled_optimizer_step(p_cmp, opt_cmp, max_grad_norm=1.0)

        w_initial = np.asarray(p_cmp["w"]).copy()
        # Exercise both clipped (scale=0.5 -> gnorm > 1.0) and unclipped (scale=0.005 -> gnorm < 1.0) steps with changing LR.
        for lr, g_scale in ((1e-2, 0.5), (5e-3, 0.005), (1e-3, 0.8)):
            grads = {
                "w": mx.full((32, 32), g_scale, dtype=mx.float32),
                "b": mx.full((32,), -0.5 * g_scale, dtype=mx.float32),
            }
            opt_ref.learning_rate = lr
            sq = sum(float(mx.sum(v * v)) for v in grads.values())
            gn = math.sqrt(max(sq, 1e-12))
            g_ref = {k: v * (1.0 / gn) if gn > 1.0 else v for k, v in grads.items()}
            opt_ref.update(p_ref, g_ref)
            mx.eval(p_ref, opt_ref.state)

            opt_cmp.learning_rate = lr
            compiled_step(grads)
            mx.eval(opt_state)

            for k in ("w", "b"):
                diff = float(mx.max(mx.abs(p_ref[k] - p_cmp[k])))
                assert diff < 1e-5, f"Compiled AdamW diverged on {k} at lr={lr}: max_diff={diff}"

        # Confirm closed-over `p_cmp` actually mutated (regression test against tracer-dict bug).
        assert float(np.max(np.abs(np.asarray(p_cmp["w"]) - w_initial))) > 1e-3


# ---------------------------------------------------------------------------
# 4. P1.5: Varlen Packing + Per-Segment RoPE + Block-Diagonal Isolation + Loss Norm
# ---------------------------------------------------------------------------


def test_varlen_packing_parity_isolation_and_lr_invariance() -> None:
    import mlx.core as mx

    with tv63.acquire_hw_lock("test_varlen_packing"):
        enc_cfg = _make_mini_enc_cfg(
            n_layers=6, hidden_size=128, n_heads=4, intermediate_size=256, local_attention=16
        )
        raw_w = _make_synthetic_weights(enc_cfg, seed=303)
        model = tv63.LayaMlxModel(raw_w, enc_cfg, freeze_below_layer=4)
        params = model.trainable

        # 8 heterogeneous items (mixed qtypes 0/1/2, mixed lengths 24..72, mixed soft_p1)
        items = _make_synthetic_items(8, vocab_size=512, min_len=24, max_len=72, seed=404)
        unpacked_batch = tv63.build_unpacked_batch(items, seq_len=128, pad_id=502, k_max=16)
        packed_bins = tv63.pack_validator_items(items, pack_tokens=160, shuffle=False)
        assert len(packed_bins) < len(items), "Expected multiple items packed per bin"
        packed_batch = tv63.build_packed_batch(packed_bins, pack_tokens=160, pad_id=502, k_max=16)
        assert packed_batch["num_items"] == len(items)

        # (a) Verify per-segment RoPE position_ids reset to `0..L_i-1`
        for _orig_idx, bin_row, off, ln in packed_batch["item_spans"]:
            expected_pos = np.arange(ln, dtype=np.int32)
            np.testing.assert_array_equal(packed_batch["pos_ids"][bin_row, off : off + ln], expected_pos)

        # (b) Verify ZERO cross-segment leakage (Full + SWA + Head) & ZERO trailing-pad leakage!
        multi_bin_idx = next(bi for bi, b in enumerate(packed_bins) if len(b) >= 2)
        test_bin = [packed_bins[multi_bin_idx]]
        b_orig = tv63.build_packed_batch(test_bin, pack_tokens=160, pad_id=502, k_max=16)
        logits_orig = np.asarray(
            model.forward_logits(
                params,
                mx.array(b_orig["ids"]),
                pos_ids=mx.array(b_orig["pos_ids"]),
                seg_ids=mx.array(b_orig["seg_ids"]),
                token_qtypes=mx.array(b_orig["token_qtypes"]),
            )
        )[0]

        # Perturb segment 2 tokens AND trailing pad tokens; segment 1 outputs must be BIT-IDENTICAL!
        seg1_span = b_orig["item_spans"][0]
        seg2_span = b_orig["item_spans"][1]
        ids_pert = b_orig["ids"].copy()
        ids_pert[0, seg2_span[2] : seg2_span[2] + seg2_span[3]] = 77
        pad_mask = b_orig["seg_ids"][0] == 0
        ids_pert[0, pad_mask] = 99
        logits_pert = np.asarray(
            model.forward_logits(
                params,
                mx.array(ids_pert),
                pos_ids=mx.array(b_orig["pos_ids"]),
                seg_ids=mx.array(b_orig["seg_ids"]),
                token_qtypes=mx.array(b_orig["token_qtypes"]),
            )
        )[0]
        seg1_diff = float(
            np.max(
                np.abs(
                    logits_orig[seg1_span[2] : seg1_span[2] + seg1_span[3]]
                    - logits_pert[seg1_span[2] : seg1_span[2] + seg1_span[3]]
                )
            )
        )
        assert seg1_diff == 0.0, f"Cross-segment or pad attention leakage detected: max_diff={seg1_diff}"

        # (c) Step-0 loss & trainable gradient parity: Packed vs Unpacked on EXACT same items
        unp_loss, unp_grads = _compute_loss_and_grads_from_batch(model, params, unpacked_batch)
        pk_loss, pk_grads = _compute_loss_and_grads_from_batch(model, params, packed_batch)
        delta_loss = abs(pk_loss - unp_loss)
        global_cos, min_cos, min_key = _grad_cosine_stats(unp_grads, pk_grads)

        assert delta_loss < 1e-3, f"Packed vs unpacked |Δloss|={delta_loss:.6f} >= 1e-3 ({pk_loss} vs {unp_loss})"
        assert global_cos >= 0.999, f"Packed vs unpacked global grad cos={global_cos:.6f} < 0.999"
        assert min_cos >= 0.998, f"Packed vs unpacked worst grad cos={min_cos:.6f} on {min_key}"

        # (d) Exact per-item normalization invariance: K identical copies in 1 packed bin == 1 unpacked copy
        solo = [items[0]]
        tripled = [items[0], items[0], items[0]]
        b_solo = tv63.build_unpacked_batch(solo, seq_len=128, pad_id=502, k_max=16)
        b_trip = tv63.build_packed_batch(
            tv63.pack_validator_items(tripled, pack_tokens=256, shuffle=False),
            pack_tokens=256,
            pad_id=502,
            k_max=16,
        )
        l_solo, g_solo = _compute_loss_and_grads_from_batch(model, params, b_solo)
        l_trip, g_trip = _compute_loss_and_grads_from_batch(model, params, b_trip)
        assert abs(l_solo - l_trip) < 1e-3, f"Loss scaling changed when packing K=3 copies: {l_solo} vs {l_trip}"
        norm_solo = math.sqrt(sum(float(mx.sum(g * g)) for g in g_solo.values()))
        norm_trip = math.sqrt(sum(float(mx.sum(g * g)) for g in g_trip.values()))
        rel_norm_diff = abs(norm_trip - norm_solo) / max(norm_solo, 1e-8)
        assert rel_norm_diff < 1e-2, f"Effective LR shifted by packing K=3 copies: norm {norm_solo} vs {norm_trip}"


# ---------------------------------------------------------------------------
# 5. P2.8: Frozen Trunk Activation Cache Parity, Hit Zero-FLOPs & Invalidation
# ---------------------------------------------------------------------------


def test_frozen_trunk_cache_parity_hit_and_invalidation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import mlx.core as mx
    import mlx.optimizers as optim

    with tv63.acquire_hw_lock("test_frozen_trunk_cache"):
        enc_cfg = _make_mini_enc_cfg(n_layers=6, hidden_size=128, n_heads=4, intermediate_size=256)
        raw_w = _make_synthetic_weights(enc_cfg, seed=505)
        model = tv63.LayaMlxModel(raw_w, enc_cfg, freeze_below_layer=4)
        params = model.trainable
        items = _make_synthetic_items(10, vocab_size=512, min_len=24, max_len=72, seed=606)

        cache_dir = tmp_path / "frozen_cache"
        cache = tv63.FrozenTrunkActivationCache(cache_dir, hidden_size=model.hidden_size, freeze_below_layer=4)

        # First populate -> miss (builds cache)
        hit1 = cache.ensure_populated(model, items, pad_id=502, max_seq_len=128, pack_tokens=160, pack_bins=4)
        assert hit1 is False
        assert (cache_dir / "meta.json").exists()
        assert (cache_dir / "offsets.npy").exists()
        assert (cache_dir / "hidden_bf16.bin").exists()

        # Re-open with identical inputs -> HIT with ZERO calls to `run_frozen_trunk`!
        cache2 = tv63.FrozenTrunkActivationCache(cache_dir, hidden_size=model.hidden_size, freeze_below_layer=4)
        calls = {"n": 0}
        orig_run = model.run_frozen_trunk

        def _counting_run(*args: Any, **kwargs: Any) -> Any:
            calls["n"] += 1
            return orig_run(*args, **kwargs)

        monkeypatch.setattr(model, "run_frozen_trunk", _counting_run)
        hit2 = cache2.ensure_populated(model, items, pad_id=502, max_seq_len=128, pack_tokens=160, pack_bins=4)
        assert hit2 is True
        assert calls["n"] == 0, f"Cache hit unexpectedly called run_frozen_trunk {calls['n']} times"

        # Parity check (BOTH unpacked AND packed!) vs live frozen trunk
        monkeypatch.setattr(model, "run_frozen_trunk", orig_run)
        unp_batch = tv63.build_unpacked_batch(items[:6], seq_len=128, pad_id=502, item_indices=list(range(6)))
        l_live_u, g_live_u = _compute_loss_and_grads_from_batch(model, params, unp_batch, frozen_cache=None)
        l_cache_u, g_cache_u = _compute_loss_and_grads_from_batch(model, params, unp_batch, frozen_cache=cache2)
        cos_u, min_u, key_u = _grad_cosine_stats(g_live_u, g_cache_u)
        assert abs(l_live_u - l_cache_u) < 1e-3, f"Cached unpacked |Δloss|={abs(l_live_u - l_cache_u):.6f}"
        assert cos_u >= 0.999 and min_u >= 0.998, f"Cached unpacked grad cos={cos_u:.6f}, min={min_u:.6f} ({key_u})"

        pk_bins = tv63.pack_validator_items(items, pack_tokens=160, shuffle=False)
        pk_batch = tv63.build_packed_batch(pk_bins, pack_tokens=160, pad_id=502)
        l_live_p, g_live_p = _compute_loss_and_grads_from_batch(model, params, pk_batch, frozen_cache=None)
        l_cache_p, g_cache_p = _compute_loss_and_grads_from_batch(model, params, pk_batch, frozen_cache=cache2)
        cos_p, min_p, key_p = _grad_cosine_stats(g_live_p, g_cache_p)
        assert abs(l_live_p - l_cache_p) < 1e-3, f"Cached packed |Δloss|={abs(l_live_p - l_cache_p):.6f}"
        assert cos_p >= 0.999 and min_p >= 0.998, f"Cached packed grad cos={cos_p:.6f}, min={min_p:.6f} ({key_p})"

        # Multi-step convergence sanity using `make_validator_train_step` + cached packed batches
        opt = optim.AdamW(learning_rate=1e-3, weight_decay=0.01)
        train_step = tv63.make_validator_train_step(model, params, opt, max_grad_norm=1.0)
        losses: list[float] = []
        for _ in range(5):
            lv, n_it, n_tk = train_step(pk_batch, frozen_cache=cache2)
            assert math.isfinite(lv) and n_it == len(items) and n_tk > 0
            losses.append(lv)
        assert losses[-1] < losses[0], f"Expected cached packed training loss to drop: {losses}"

        # Invalidation test 1: sequence token change
        items_mut = [dict(it) for it in items]
        items_mut[0] = dict(items[0], ids=[items[0]["ids"][0] + 1] + items[0]["ids"][1:])
        assert cache2.ensure_populated(model, items_mut, pad_id=502, max_seq_len=128, pack_tokens=160) is False

        # Restore original items -> invalidates again
        assert cache2.ensure_populated(model, items, pad_id=502, max_seq_len=128, pack_tokens=160) is False

        # Invalidation test 2: model config change (`local_attention` changed)
        enc_cfg_mod = dict(enc_cfg, local_attention=32)
        model_cfg_mod = tv63.LayaMlxModel(raw_w, enc_cfg_mod, freeze_below_layer=4)
        assert cache2.ensure_populated(model_cfg_mod, items, pad_id=502, max_seq_len=128, pack_tokens=160) is False

        # Invalidation test 3: frozen weight byte change
        raw_w_mod = dict(raw_w)
        raw_w_mod["encoder.layers.0.attn.Wo.weight"] = raw_w["encoder.layers.0.attn.Wo.weight"] + 0.01
        mx.eval(raw_w_mod["encoder.layers.0.attn.Wo.weight"])
        model_w_mod = tv63.LayaMlxModel(raw_w_mod, enc_cfg_mod, freeze_below_layer=4)
        assert cache2.ensure_populated(model_w_mod, items, pad_id=502, max_seq_len=128, pack_tokens=160) is False

        # Invalidation test 4: `freeze_below_layer` change (4 -> 3)
        model_f3 = tv63.LayaMlxModel(raw_w_mod, enc_cfg_mod, freeze_below_layer=3)
        cache_f3 = tv63.FrozenTrunkActivationCache(cache_dir, hidden_size=model.hidden_size, freeze_below_layer=3)
        assert cache_f3.ensure_populated(model_f3, items, pad_id=502, max_seq_len=128, pack_tokens=160) is False

        # Over-read guard & `max_item_len` clamping when `pack_tokens > max_seq_len` and `len(ids) > max_seq_len`
        long_items = [dict(it) for it in items[:4]]
        long_items[0] = dict(
            items[0],
            ids=[((j * 17) % 480) + 10 for j in range(180)],
            markers=[2, 6],
            qtype=2,
            target=1,
        )
        cache_clamp = tv63.FrozenTrunkActivationCache(
            tmp_path / "frozen_cache_clamp", hidden_size=model.hidden_size, freeze_below_layer=4
        )
        assert cache_clamp.ensure_populated(model, long_items, pad_id=502, max_seq_len=128, pack_tokens=256) is False
        clamped_bins = tv63.pack_validator_items(long_items, pack_tokens=256, max_item_len=128, shuffle=False)
        clamped_stats = tv63.compute_packing_stats(clamped_bins, 256, max_item_len=128)
        clamped_batch = tv63.build_packed_batch(clamped_bins, pack_tokens=256, pad_id=502, max_item_len=128)
        assert clamped_stats["real_tokens"] == clamped_batch["real_tokens"]
        assert max(sp[3] for sp in clamped_batch["item_spans"]) <= 128
        l_live_c, g_live_c = _compute_loss_and_grads_from_batch(model, params, clamped_batch, frozen_cache=None)
        l_cache_c, g_cache_c = _compute_loss_and_grads_from_batch(model, params, clamped_batch, frozen_cache=cache_clamp)
        cos_c, _, _ = _grad_cosine_stats(g_live_c, g_cache_c)
        assert abs(l_live_c - l_cache_c) < 1e-3, f"Clamped cached |Δloss|={abs(l_live_c - l_cache_c):.6f}"
        assert cos_c >= 0.999, f"Clamped cached grad cos={cos_c:.6f} < 0.999"
        with pytest.raises(ValueError, match="over-read"):
            cache_clamp.gather_batch([(0, 0, 0, 180)], batch_rows=1, seq_len=256)

        # RoPE capacity auto-growth when `pos_ids` is passed with `seq_len > _max_pos_len`
        pos_big = mx.zeros((1, 1100), dtype=mx.int32)
        cos_f_big, _, _, _ = model.prepare_rope(1100, pos_ids=pos_big)
        assert model._max_pos_len >= 1100 and tuple(cos_f_big.shape) == (1, 1, 1100, model.head_dim // 2)

        cache.close()
        cache2.close()
        cache_f3.close()
        cache_clamp.close()


# ---------------------------------------------------------------------------
# 6. P2.9: Kev-0.8B Teacher Document Prefix Reuse (Unit + Live W8 Parity)
# ---------------------------------------------------------------------------


def test_kev_teacher_prefix_reuse_causal_unit_and_fallback() -> None:
    import mlx.core as mx

    # Deterministic causal fake backbone storing prefix token sums (strictly causal prefix->branch equivalence).
    class _FakeCache:
        def __init__(self) -> None:
            self.prefix_sum: Any = None
            self.prefix_len: Any = None

    class _FakeCausalBackbone:
        def __init__(self) -> None:
            self.prefix_prefill_calls = 0
            self.prefix_prefill_rows = 0
            self.branch_calls = 0

        def make_cache(self) -> list[_FakeCache]:
            return [_FakeCache()]

        def __call__(
            self,
            input_ids: Any,
            cache: list[_FakeCache],
            *,
            valid_token_scale: Any | None = None,
            attn_mask: Any = "causal",
            pos_2d: Any | None = None,
            owner_idx: Any | None = None,
            owner_is_identity: bool = False,
            write_state: bool = True,
        ) -> Any:
            ids_f = input_ids.astype(mx.float32)
            B, S = ids_f.shape
            if write_state:
                self.prefix_prefill_calls += 1
                self.prefix_prefill_rows += int(B)
                if valid_token_scale is not None:
                    v_m = valid_token_scale.squeeze(-1).astype(mx.float32)
                else:
                    v_m = mx.ones((B, S), dtype=mx.float32)
                cs = mx.cumsum(ids_f * v_m, axis=1)
                cl = mx.cumsum(v_m, axis=1)
                cache[0].prefix_sum = cs[:, -1:]
                cache[0].prefix_len = cl[:, -1:]
                return mx.stack([cs, cl], axis=-1).astype(mx.bfloat16)

            self.branch_calls += 1
            o_idx = owner_idx if owner_idx is not None else mx.arange(B, dtype=mx.int32)
            base_sum = mx.take(cache[0].prefix_sum, o_idx, axis=0)
            base_len = mx.take(cache[0].prefix_len, o_idx, axis=0)
            cs = base_sum + mx.cumsum(ids_f, axis=1)
            cl = base_len + mx.arange(1, S + 1, dtype=mx.float32)[None, :]
            return mx.stack([cs, cl], axis=-1).astype(mx.bfloat16)

    class _FakeKevBackend:
        def __init__(self) -> None:
            self._mx = mx
            self.backbone = _FakeCausalBackbone()
            self.pad_id = 0
            self.batch_docs = 4
            self.max_branch_batch = 8

        def _tok(self, txt: str) -> list[int]:
            return [(ord(ch) % 97) + 1 for ch in txt]

        def encode_questions(self, state: Any, questions: list[dict[str, Any]]) -> tuple[list[int], list[dict[str, Any]]]:
            st_str = (
                f"doc={state['document_excerpt']}|cand={state['candidate_extraction']['primary_kind']}"
                f"|cmt={state['candidate_extraction']['committees']}"
            )
            st_ids = [101] + self._tok(st_str)
            rows = []
            for q in questions:
                q_ids = [102] + self._tok(q["id"]) + [103, 104, 105]
                rows.append({"ids": q_ids, "decide": len(q_ids) - 1, "opts": [len(q_ids) - 3, len(q_ids) - 2], "k": 2})
            return st_ids, rows

        def _pointer_logits_and_probs(self, h_row_f32: Any, decide_idx: int, opt_indices: list[int]) -> tuple[list[float], list[float]]:
            d_val = float(h_row_f32[decide_idx, 0]) / max(float(h_row_f32[decide_idx, 1]), 1.0)
            z0 = (float(h_row_f32[opt_indices[0], 0]) - d_val) * 0.001
            z1 = (float(h_row_f32[opt_indices[1], 0]) + d_val) * 0.001
            m = max(z0, z1)
            e0, e1 = math.exp(z0 - m), math.exp(z1 - m)
            return [e0 / (e0 + e1), e1 / (e0 + e1)], [z0, z1]

        def score_multi_states_noul(self, batch_in: list[tuple[Any, list[dict[str, Any]]]], batch_docs: int | None = None) -> list[list[tuple[float, list[float]]]]:
            out = []
            for st, qs in batch_in:
                st_ids, rows = self.encode_questions(st, qs)
                c = self.backbone.make_cache()
                h_st = self.backbone(mx.array([st_ids], dtype=mx.int32), c, write_state=True)
                mx.eval(h_st)
                doc_res = []
                for r in rows:
                    h_br = self.backbone(
                        mx.array([r["ids"]], dtype=mx.int32), c, owner_idx=mx.array([0], dtype=mx.int32), write_state=False
                    )
                    mx.eval(h_br)
                    probs, rz = self._pointer_logits_and_probs(np.asarray(h_br.astype(mx.float32))[0], r["decide"], r["opts"])
                    doc_res.append((probs[1], rz))
                out.append(doc_res)
            return out

    with tv63.acquire_hw_lock("test_kev_prefix_unit"):
        kev_jobs = []
        for doc_i in range(3):
            shared_body = f"Congressional Hearing Transcript {doc_i} " + ("testimony witness committee " * 4)
            st_clean = {"document_excerpt": shared_body, "candidate_extraction": {"primary_kind": "witness_statement", "committees": "Ways"}}
            kev_jobs.append((doc_i, st_clean, [{"id": "q1"}, {"id": "q2"}], [doc_i * 10, doc_i * 10 + 1]))
            for ci, bad_k in enumerate(("hearing_notice", "oversight_letter", "committee_vote")):
                st_bad = {"document_excerpt": shared_body, "candidate_extraction": {"primary_kind": bad_k, "committees": "Rules"}}
                kev_jobs.append((doc_i, st_bad, [{"id": f"q_bad_{ci}"}], [doc_i * 10 + 2 + ci]))

        # Naive scoring
        fake_naive = _FakeKevBackend()
        naive_outs = fake_naive.score_multi_states_noul([(st, qs) for (_d, st, qs, _i) in kev_jobs])

        # Grouped shared-prefix scoring
        fake_reuse = _FakeKevBackend()
        reuse_outs, stats = tv63.score_kev_teacher_jobs_with_prefix_reuse(fake_reuse, kev_jobs, batch_docs=4)

        assert stats["used_prefix_reuse"] == 1
        assert stats["unique_docs"] == 3
        assert stats["total_jobs"] == 12
        assert stats["prefix_groups"] == 3
        # Prefilled 3 unique doc prefixes instead of 12 state prefills!
        assert fake_reuse.backbone.prefix_prefill_rows == 3
        assert fake_naive.backbone.prefix_prefill_rows == 12
        assert stats["shared_prefix_tokens"] + stats["suffix_tokens"] < stats["naive_state_tokens"] * 0.5

        for j_naive, j_reuse in zip(naive_outs, reuse_outs):
            assert len(j_naive) == len(j_reuse)
            for (p_n, z_n), (p_r, z_r) in zip(j_naive, j_reuse):
                assert abs(p_n - p_r) < 1e-4, f"Prefix reuse P(true) mismatch: {p_n} vs {p_r}"
                assert np.allclose(z_n, z_r, atol=1e-3), f"Prefix reuse logits mismatch: {z_n} vs {z_r}"

        # Fallback path when teacher has no `.backbone` (mock teacher)
        class _MockOnlyTeacher:
            def __init__(self) -> None:
                self.calls = 0

            def score_multi_states_noul(self, items: list[Any], batch_docs: int | None = None) -> list[list[tuple[float, list[float]]]]:
                self.calls += len(items)
                return [[(0.75, [-0.5, 0.5]) for _ in qs] for (_st, qs) in items]

        mock_t = _MockOnlyTeacher()
        dup_jobs = [
            (0, {"a": 1}, [{"id": "q1"}], [0]),
            (0, {"a": 1}, [{"id": "q2"}], [1]),
            (0, {"a": 2}, [{"id": "q3"}], [2]),
        ]
        m_outs, m_stats = tv63.score_kev_teacher_jobs_with_prefix_reuse(mock_t, dup_jobs)
        assert m_stats["used_prefix_reuse"] == 0
        assert mock_t.calls == 2  # deduplicated identical `{"a": 1}` state
        assert [x[0][0] for x in m_outs] == [0.75, 0.75, 0.75]


@pytest.mark.skipif(
    not (KEV_ARTIFACTS_DIR.exists() and GOLD_JSONL_PATH.exists()),
    reason="Requires local W8 Kev-0.8B artifacts and V6.3 gold JSONL",
)
def test_kev_teacher_prefix_reuse_live_w8_parity() -> None:
    from congress_docmeta.atomic_validator_v6 import build_atomic_doc_questions_v6
    from fast_decision_models import Kev08bMlxBackend

    raw_lines = GOLD_JSONL_PATH.read_text(encoding="utf-8").splitlines()
    usable_recs = []
    for ln in raw_lines[:80]:
        if not ln.strip():
            continue
        rec = tv63.parse_v4_prompt_row(json.loads(ln))
        if rec["gold"].get("status") == "usable" and rec["p12_clean_text"]:
            usable_recs.append(rec)
        if len(usable_recs) >= 4:
            break
    assert len(usable_recs) == 4

    kev_jobs = []
    for di, rec in enumerate(usable_recs):
        g = rec["gold"]
        st_c, qs_c = build_atomic_doc_questions_v6(
            g, rec, head_chars=1450, tail_chars=500, include_genre_check=True, include_omission_check=True
        )
        kev_jobs.append((di, st_c, qs_c[:3], list(range(3))))
        # 3 corruptions per doc
        bad1 = json.loads(json.dumps(g))
        bad1["primary_kind"] = "other" if g.get("primary_kind") != "other" else "hearing_notice"
        st1, qs1 = build_atomic_doc_questions_v6(bad1, rec, head_chars=1450, tail_chars=500, include_genre_check=True, include_omission_check=True)
        kev_jobs.append((di, st1, [qs1[0]], [0]))

        bad2 = json.loads(json.dumps(g))
        bad2["committees"] = ["House Committee on Rules"]
        st2, qs2 = build_atomic_doc_questions_v6(bad2, rec, head_chars=1450, tail_chars=500, include_genre_check=True, include_omission_check=True)
        kev_jobs.append((di, st2, [qs2[1]], [0]))

        bad3 = json.loads(json.dumps(g))
        bad3["gist"] = "Mandates repealing $84 billion under H.R. 9942."
        st3, qs3 = build_atomic_doc_questions_v6(bad3, rec, head_chars=1450, tail_chars=500, include_genre_check=True, include_omission_check=True)
        kev_jobs.append((di, st3, [qs3[2]], [0]))

    with tv63.acquire_hw_lock("test_kev_prefix_live_w8"):
        with Kev08bMlxBackend(KEV_ARTIFACTS_DIR, quant_mode="w8", batch_docs=4) as kev:
            naive_outs = kev.score_multi_states_noul([(st, qs) for (_d, st, qs, _i) in kev_jobs], batch_docs=4)
            reuse_outs, stats = tv63.score_kev_teacher_jobs_with_prefix_reuse(kev, kev_jobs, batch_docs=4)

    assert stats["used_prefix_reuse"] == 1
    assert stats["unique_docs"] == 4
    assert stats["prefix_groups"] == 4
    kept_toks = stats["shared_prefix_tokens"] + stats["suffix_tokens"]
    assert kept_toks < stats["naive_state_tokens"] * 0.50, f"Expected >50% state token savings, got {stats}"

    max_dp = 0.0
    z_naive_all: list[float] = []
    z_reuse_all: list[float] = []
    for j_n, j_r in zip(naive_outs, reuse_outs):
        for (p_n, z_n), (p_r, z_r) in zip(j_n, j_r):
            max_dp = max(max_dp, abs(p_n - p_r))
            z_naive_all.extend(z_n)
            z_reuse_all.extend(z_r)

    zn = np.asarray(z_naive_all, dtype=np.float64)
    zr = np.asarray(z_reuse_all, dtype=np.float64)
    z_cos = float(np.dot(zn, zr) / max(float(np.linalg.norm(zn) * np.linalg.norm(zr)), 1e-12))
    assert max_dp < 0.01, f"Live W8 Kev prefix reuse max |ΔP(true)|={max_dp:.5f} >= 0.01"
    assert z_cos >= 0.999, f"Live W8 Kev prefix reuse logit cos={z_cos:.6f} < 0.999"


def test_train_v63_grouped_split_and_feature_dedup() -> None:
    from congress_docmeta.grammar_router_ane_v6 import extract_router_sparse_features_v6

    i_ssot, v_ssot = extract_router_sparse_features_v6(
        "test_memo.pdf",
        '{"congress": 118, "cmt": ["hsgo00"], "date": "2024-03-14"}',
        "<html><body>Memorandum from Chairman Comer regarding oversight</body></html>",
        "Memorandum from Chairman Comer regarding oversight hearing next Tuesday.",
    )
    i_tr, v_tr = tv63.extract_router_sparse_features(
        "test_memo.pdf",
        '{"congress": 118, "cmt": ["hsgo00"], "date": "2024-03-14"}',
        "<html><body>Memorandum from Chairman Comer regarding oversight</body></html>",
        "Memorandum from Chairman Comer regarding oversight hearing next Tuesday.",
    )
    assert list(i_tr) == i_ssot
    assert np.allclose(v_tr, v_ssot)

    # Create synthetic records with shared hearings + duplicate text_sha256 + rare 2-doc class
    records: list[dict[str, Any]] = []
    for k in range(12):
        ev = f"evt_{k // 2}"
        sha = "dup_sha_a" if k in (0, 1) else f"sha_{k}"
        records.append(
            {
                "doc_key": f"d_{k}",
                "text_sha256": sha,
                "event_id": ev,
                "filename": f"doc_{k}.pdf",
                "known": json.dumps({"congress": 118, "cmt": ["hsju00"], "date": f"2024-01-{(k // 2) + 10:02d}"}),
                "p12_raw_text": f"Hearing document text #{k} " + ("congressional testimony " * 4),
                "p12_clean_text": f"Hearing document text #{k} " + ("congressional testimony " * 4),
                "gold": {"status": "usable", "primary_kind": "witness_statement"},
                "router_class": "witness_statement",
            }
        )
    for k in range(2):
        records.append(
            {
                "doc_key": f"rare_{k}",
                "text_sha256": f"rare_sha_{k}",
                "event_id": f"rare_ev_{k}",
                "filename": f"rare_{k}.pdf",
                "known": "{}",
                "p12_raw_text": f"Rare subpoena text {k}",
                "p12_clean_text": f"Rare subpoena text {k}",
                "gold": {"status": "usable", "primary_kind": "subpoena"},
                "router_class": "subpoena",
            }
        )

    tr, cal = tv63.split_records_grouped_stratified(records, target_cal=4, seed=20261116)
    ct, es = tv63.split_cal_records_disjoint(cal, early_stop_frac=0.5, seed=20261117)
    tr_evs = {r["event_id"] for r in tr}
    cal_evs = {r["event_id"] for r in cal}
    ct_evs = {r["event_id"] for r in ct}
    es_evs = {r["event_id"] for r in es}
    assert tr_evs.isdisjoint(cal_evs), "Same hearing leaked across train/cal!"
    assert ct_evs.isdisjoint(es_evs), "Same hearing leaked between early_stop and cal_thresh!"
    # Rare <= 2-doc class stays 100% in train
    assert sum(1 for r in tr if r["router_class"] == "subpoena") == 2


def test_train_v63_genre_corruptions_persona_distill_and_prefix_clustering() -> None:
    truncate_flags: list[Any] = []

    class _MockTok:
        def encode_item(self, state: Any, qdef: dict[str, Any], *, on_truncate: str = "warn") -> dict[str, Any]:
            truncate_flags.append(on_truncate)
            n_opts = len(qdef.get("criteria") or {})
            qt = 2 if qdef.get("type") == "noul" else 1
            return {
                "ids": [1, 2, 3, 4, 5, 6],
                "markers": list(range(max(2, n_opts))),
                "qtype": qt,
            }

    class _FakePrefixBackbone:
        def __init__(self) -> None:
            self.prefix_prefill_rows = 0

        def make_cache(self) -> list[dict[str, Any]]:
            return [{"sum": None, "len": None}]

        def __call__(self, input_ids: Any, cache: list[dict[str, Any]], **kw: Any) -> Any:
            import mlx.core as mx

            ids_f = input_ids.astype(mx.float32)
            B, S = ids_f.shape
            if kw.get("write_state", True):
                self.prefix_prefill_rows += int(B)
                cs = mx.cumsum(ids_f, axis=1)
                cl = mx.arange(1, S + 1, dtype=mx.float32)[None, :] * mx.ones((B, 1), dtype=mx.float32)
                cache[0]["sum"] = cs[:, -1:]
                cache[0]["len"] = cl[:, -1:]
                return mx.stack([cs, cl], axis=-1).astype(mx.bfloat16)
            o_idx = kw.get("owner_idx")
            base_s = mx.take(cache[0]["sum"], o_idx, axis=0)
            base_l = mx.take(cache[0]["len"], o_idx, axis=0)
            cs = base_s + mx.cumsum(ids_f, axis=1)
            cl = base_l + mx.arange(1, S + 1, dtype=mx.float32)[None, :]
            return mx.stack([cs, cl], axis=-1).astype(mx.bfloat16)

    class _FakeMixedKev:
        def __init__(self) -> None:
            import mlx.core as mx

            self._mx = mx
            self.backbone = _FakePrefixBackbone()
            self.pad_id = 0
            self.batch_docs = 8
            self.max_branch_batch = 16

        def encode_questions(self, state: Any, questions: list[dict[str, Any]]) -> tuple[list[int], list[dict[str, Any]]]:
            # Distinguish doc-level state vs persona-level state cleanly just like real atomic questions!
            if "candidate_actor" in state:
                s_txt = f"ACTOR|{state['candidate_actor']['name']}|{state['candidate_actor']['role']}"
            else:
                s_txt = f"DOC|{state.get('document_excerpt', '')}|{state.get('candidate_extraction', {}).get('primary_kind', '')}"
            st_ids = [10] + [(ord(c) % 89) + 11 for c in s_txt]
            rows = []
            for q in questions:
                q_ids = [2] + [(ord(c) % 50) + 10 for c in q["id"]] + [3, 4, 5]
                rows.append({"ids": q_ids, "decide": len(q_ids) - 1, "opts": [len(q_ids) - 3, len(q_ids) - 2], "k": 2})
            return st_ids, rows

        def _pointer_logits_and_probs(self, _h_row: Any, _d: int, _o: list[int]) -> tuple[list[float], list[float]]:
            return [0.25, 0.75], [-0.5, 0.6]

    rec = {
        "doc_key": "d_multi",
        "text_sha256": "sha_multi",
        "filename": "letter_disclosure.pdf",
        "known": '{"congress": 118}',
        "p12_raw_text": "Dear Chairman Smith, I submit this Truth in Testimony disclosure for Jane Doe regarding the Energy bill.",
        "p12_clean_text": "Dear Chairman Smith, I submit this Truth in Testimony disclosure for Jane Doe regarding the Energy bill.",
        "gold": {
            "status": "usable",
            "primary_kind": "external_submission_letter",
            "committees": ["House Committee on Energy and Commerce"],
            "composed_title": "External Letter from Jane Doe",
            "gist": "Jane Doe submits a letter and Truth in Testimony disclosure.",
            "disclosure": {"capacity": "individual", "gov_witness": False, "has_federal_grants": False},
            "correspondence_flow": "incoming_to_committee",
            "personas": [{"name": "Jane Doe", "role": "witness", "entity_type": "non_gov_person"}],
        },
        "router_class": "external_submission_letter",
    }

    kev_mock = _FakeMixedKev()
    with tv63.acquire_hw_lock("test_genre_corruptions_prefix"):
        items = tv63.synthesize_training_examples(
            [rec],
            [["external_submission_letter", "oversight_letter", "witness_statement", "hearing_notice", "other", "committee_report"]],
            _MockTok(),
            kev_mock,
            distill_docs=1,
            seed=20261116,
            reuse_doc_prefix=True,
        )
    assert all(f == "ignore" for f in truncate_flags), "Expected on_truncate='ignore' on Laya encoding"
    tasks = [it["task"] for it in items]
    # Independent `if` checks must emit BOTH disclosure AND correspondence_flow negatives
    assert "doc_noul_neg_disclosure" in tasks
    assert "doc_noul_neg_correspondence_flow" in tasks
    # Both persona_noul_pos and persona_noul_neg must receive Kev-0.8B soft distillation targets
    p_pos = [it for it in items if it["task"] == "persona_noul_pos"]
    p_neg = [it for it in items if it["task"] == "persona_noul_neg"]
    assert p_pos and all(it["soft_p1"] is not None for it in p_pos)
    assert p_neg and all(it["soft_p1"] is not None for it in p_neg)
    # Prefix sub-clustering keeps shared doc prefix reuse intact (`1` doc cluster + `1–2` persona cluster(s))
    assert kev_mock.backbone.prefix_prefill_rows in (2, 3)


def test_train_v63_router_fusion_monotonic_thresholds_and_validator_calibration() -> None:
    rng = np.random.default_rng(7)
    n, c = 60, len(tv63.ROUTER_CLASSES)
    y_cal = np.arange(n) % 6
    cal_lin = np.full((n, c), 0.002, dtype=np.float64)
    top6_order = np.zeros((n, 6), dtype=np.int32)
    ane_logits = np.zeros((n, 6), dtype=np.float32)
    for i in range(n):
        top6 = [0, 1, 2, 3, 4, 5]
        top6_order[i] = top6
        for k, ci in enumerate(top6):
            cal_lin[i, ci] = 0.35 if ci == y_cal[i] else 0.10
            ane_logits[i, k] = (3.5 if ci == y_cal[i] else -1.0) + float(rng.normal(0.0, 0.25))
    cal_lin /= cal_lin.sum(axis=-1, keepdims=True)

    cal_dict, fused = tv63.fit_fused_router_calibration(
        cal_lin, ane_logits, top6_order, y_cal, tv63.ROUTER_CLASSES, train_docs=100
    )
    assert cal_dict["ane_tau_top1"] <= cal_dict["ane_tau_top2"] <= cal_dict["ane_tau_top3"]
    assert cal_dict["fast_linear_tau_top1"] <= cal_dict["fast_linear_tau_top2"] <= cal_dict["fast_linear_tau_top3"]
    assert np.allclose(fused.sum(axis=-1), 1.0, atol=1e-5)

    v0_s = [0.02] * 30 + [0.70] * 30
    l_s = [0.22] * 30 + [0.76] * 30
    y_bad = [0] * 30 + [1] * 30
    role_probs = np.zeros((40, 16), dtype=np.float32)
    role_y = np.arange(40) % 16
    for i in range(40):
        role_probs[i, :] = 0.01
        role_probs[i, role_y[i]] = 0.85 if i < 36 else 0.20
    role_probs /= role_probs.sum(axis=-1, keepdims=True)
    val_fit = tv63.fit_validator_fusion_calibration(
        v0_s,
        l_s,
        y_bad,
        role_probs=role_probs,
        role_y=role_y,
        persona_v0_scores=[0.05] * 20 + [0.8] * 20,
        persona_laya_scores=[0.1] * 20 + [0.85] * 20,
        persona_y_bad=[0] * 20 + [1] * 20,
    )
    assert 0.15 <= val_fit["laya_raw_offset"] <= 0.58
    assert 0.25 <= val_fit["laya_raw_scale"] <= 0.70
    assert val_fit["stage1_cal_f1"] == 1.0
    assert 0.45 <= val_fit["role_repair_min_prob"] <= 0.78
    assert 0.45 <= val_fit["role_repair_min_defect"] <= 0.68

    # Rank-preserving calibration: when q50(clean_l) > 0.38, AUROC-first selection must avoid clamping clean ranks
    v0_rank = [0.02] * 12 + [0.05] * 12 + [0.06] * 12
    l_rank = [0.24 + 0.02 * i for i in range(12)] + [0.40 + 0.004 * i for i in range(12)] + [0.46 + 0.02 * i for i in range(12)]
    y_rank = [0] * 24 + [1] * 12
    rank_fit = tv63.fit_validator_fusion_calibration(v0_rank, l_rank, y_rank)
    assert rank_fit["laya_raw_offset"] <= 0.38
    w0_r, wl_r = rank_fit["v0_laya_weights"]
    comb_r = [
        w0_r * v_i + wl_r * max(0.0, min(1.0, (l_i - rank_fit["laya_raw_offset"]) / max(rank_fit["laya_raw_scale"], 1e-4)))
        for v_i, l_i in zip(v0_rank, l_rank)
    ]
    pos_r = [c for c, y_i in zip(comb_r, y_rank) if y_i == 1]
    neg_r = [c for c, y_i in zip(comb_r, y_rank) if y_i == 0]
    auc_r = sum((p > n) + 0.5 * (p == n) for p in pos_r for n in neg_r) / float(len(pos_r) * len(neg_r))
    assert auc_r >= 0.99

