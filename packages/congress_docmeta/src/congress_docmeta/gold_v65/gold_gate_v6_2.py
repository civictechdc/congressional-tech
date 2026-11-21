#!/usr/bin/env python3
"""Zero-Leakage & Strict-Schema Gate for Hydrogen-High Gold Expansion (V6.2 / V6.3 / V6.4 / V6.5).

Guards against ANY overlap with:
- Sacred eval sets: `eval_val48_v4_gold.json` (48) & `eval_docs8_v4_gold.json` (8)
- Prior training sets: `train_v4_all360.jsonl` (360), `train_v6_hydrogen_bodytext.jsonl` (58),
  `train_v6_2_cluster_hydrogen_high.jsonl` (2,000, via `--prior-2000` or Shard 21..29 auto-detection),
  `train_v6_3_complete_ssot_gold.jsonl` (2,917, via `--prior-v6-3` or Shard 30..31 auto-detection),
  and `train_v6_4_complete_ssot_gold.jsonl` (3,077, via `--prior-v6-4` or Shard 32..36 auto-detection)
Supports `--allow-rehydrate-360` for Shards 26..29 (`BodyTextSSOT` re-hydration of `train_v4_all360.jsonl`),
`consolidate-v6-3`, and `consolidate-v6-4` for assembling the complete zero-leakage SSOT gold corpus.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

import duckdb

from viewer_publication.body_text_ssot import head_tail_window

from .. import (
    build_prompt_v4,
    canonicalize_docmeta_v4,
    strict_validate_v4,
    validate_docmeta_v4,
)
from .paths import resolve_docmeta_v6_data_dir, resolve_docmeta_v65_dir

DOCMETA_V6_DIR = resolve_docmeta_v6_data_dir()
LOOKUPS_DIR = DOCMETA_V6_DIR / "lookups_and_gold"
VAL48_PATH = LOOKUPS_DIR / "eval_val48_v4_gold.json"
DOCS8_PATH = LOOKUPS_DIR / "eval_docs8_v4_gold.json"
TRAIN360_PATH = LOOKUPS_DIR / "train_v4_all360.jsonl"
TRAIN58_PATH = LOOKUPS_DIR / "train_v6_hydrogen_bodytext.jsonl"
TARGET_GOLD_PATH = LOOKUPS_DIR / "train_v6_2_cluster_hydrogen_high.jsonl"
COMBINED_GOLD_PATH = LOOKUPS_DIR / "train_v6_2_combined_gold.jsonl"
GAP500_GOLD_PATH = LOOKUPS_DIR / "train_v6_3_gap500_hydrogen_high.jsonl"
REHYDRATED360_GOLD_PATH = LOOKUPS_DIR / "train_v6_3_rehydrated360_ssot.jsonl"
COMPLETE_V6_3_GOLD_PATH = LOOKUPS_DIR / "train_v6_3_complete_ssot_gold.jsonl"
RESIDUAL160_GOLD_PATH = LOOKUPS_DIR / "train_v6_4_residual160_hydrogen_high.jsonl"
COMPLETE_V6_4_GOLD_PATH = LOOKUPS_DIR / "train_v6_4_complete_ssot_gold.jsonl"
DET_V6_1_PATH = DOCMETA_V6_DIR / "parquets_v6_1/deterministic_323k_v6_1.parquet"
DET_V6_2_PATH = DOCMETA_V6_DIR / "parquets_v6_2/deterministic_323k_v6_2.parquet"

EMPTY_BODY_PLACEHOLDER = "[EMPTY_BODY]"
SHORT_TEXT_ALLOWED_STATUSES = frozenset({"stub_or_blank", "error_or_block", "ocr_unreadable"})
GENERIC_ENDPOINT_FILENAMES = frozenset({
    "documentsingle.aspx", "default.aspx", "r.aspx", "index.html", "index.htm",
    "text", "document", "hearings", "events", "calendar", "press-releases",
    "markups", "news", "legislation", "o",
})
# Single pre-existing document present in both legacy V4-360 (row 357, unkeyed) and V6-58 (`bt-h2-html`):
LEGACY_V4_TRAIN58_OVERLAP_LKS = frozenset({"015813354aa52c32"})

REQUIRED_PROVENANCE_KEYS = (
    "saved_body_hex",
    "link_key_hex",
    "parser",
    "parser_version",
    "text_sha256",
    "stratum",
    "reviewer_id",
)

HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
HEX16_RE = re.compile(r"^[0-9a-f]{16}$")
SHARD_GAP_RE = re.compile(r"(?:gold_)?shard_2[1-5]\b|gap500", re.I)
SHARD_REHYD_RE = re.compile(r"(?:gold_)?shard_2[6-9]\b|rehydrated?360", re.I)
SHARD_V64_GAP_RE = re.compile(r"(?:gold_)?shard_3[01]\b|residual160|gap160", re.I)
SHARD_V65_RARE_RE = re.compile(r"(?:gold_)?shard_3[2-7]\b|raretypes|lineage|v6[_.]?5", re.I)
SHARD_37_LINEAGE_RE = re.compile(r"(?:gold_)?shard_37\b|lineage", re.I)


def norm_ws_hash(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", (text or "").strip().lower())
    return sha256(collapsed.encode("utf-8")).hexdigest()


def norm_alnum_prefix(text: str, length: int = 240) -> str:
    alnum = re.sub(r"[^a-z0-9]+", "", (text or "").lower())
    return alnum[:length]


def extract_prompt_filename_and_text(user_content: str) -> tuple[str, str]:
    m = re.search(r"\nFilename:\s*(.*?)\nText:\n(.*)$", user_content, flags=re.S)
    if not m:
        return "", user_content
    return m.group(1).strip(), m.group(2)


def make_gold_record(
    case: Mapping[str, Any],
    gold_dict: Mapping[str, Any],
    *,
    reviewer_id: str,
    stratum: str | None = None,
) -> dict[str, Any]:
    """Build a canonical, prompt-formatted DocMetaV4Causal JSONL record from a pre-packaged shard case."""
    win_txt = str(case.get("window_text") or "")
    if not win_txt:
        full_text = str(case.get("full_text") or "")
        offsets = list(case.get("page_offsets") or [0])
        win_txt = head_tail_window(full_text, offsets, max_chars=9000, head_pages=2, tail_chars=2520)
    if not win_txt.strip():
        win_txt = EMPTY_BODY_PLACEHOLDER
    known_obj = case.get("known") or {"congress": None, "chambers": [], "cmt": [], "date": None}
    known_str = known_obj if isinstance(known_obj, str) else json.dumps(known_obj)
    filename = str(case.get("filename") or "document")
    user_prompt = build_prompt_v4(known_str, filename, win_txt)
    canon = canonicalize_docmeta_v4(dict(gold_dict))
    canon_str = json.dumps(canon, separators=(",", ":"), ensure_ascii=False)
    sb = str(case.get("saved_body_hex") or "").strip().lower()
    raw_ftc = case.get("full_text_chars")
    ftc = int(raw_ftc) if raw_ftc is not None else (0 if win_txt == EMPTY_BODY_PLACEHOLDER else len(win_txt))
    out: dict[str, Any] = {
        "messages": [
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": canon_str},
        ],
        "saved_body_hex": sb,
        "link_key_hex": str(case["link_key_hex"]).strip().lower(),
        "parser": str(case.get("parser") or "pdf_text"),
        "parser_version": str(case["parser_version"]).strip().lower(),
        "text_sha256": str(case["text_sha256"]).strip().lower(),
        "full_text_chars": ftc,
        "stratum": str(stratum or case.get("stratum") or "cluster_sampled"),
        "reviewer_id": reviewer_id,
    }
    if case.get("cluster_id"):
        out["cluster_id"] = str(case["cluster_id"])
    if case.get("doc_key"):
        out["doc_key"] = str(case["doc_key"]).strip().lower()
    return out


def load_forbidden_sets(
    *,
    include_prior_2000: bool = False,
    allow_rehydrate_360: bool = False,
    include_prior_58: bool = True,
    include_prior_v6_3: bool = False,
    include_prior_v6_4: bool = False,
    include_prior_shards_32_36: bool = False,
) -> dict[str, set[str]]:
    """Build exhaustive sacred eval (val48 + docs8) & prior-train exclusion sets."""
    if include_prior_shards_32_36:
        include_prior_v6_4 = True
    sacred_shas: set[str] = set()
    sacred_link_keys: set[str] = set()
    sacred_doc_keys: set[str] = set()
    sacred_filenames: set[str] = set()
    sacred_ws_hashes: set[str] = set()
    sacred_alnum_prefixes: set[str] = set()

    val48 = json.loads(VAL48_PATH.read_text(encoding="utf-8"))
    docs8 = json.loads(DOCS8_PATH.read_text(encoding="utf-8"))
    for row in [*val48, *docs8]:
        if row.get("body_sha"):
            sacred_shas.add(str(row["body_sha"]).strip().lower())
        if row.get("link_key"):
            sacred_link_keys.add(str(row["link_key"]).strip().lower())
        if row.get("doc_id"):
            sacred_doc_keys.add(str(row["doc_id"]).strip().lower())
        fn = str(row.get("filename") or "").strip()
        if fn:
            sacred_filenames.add(fn)
        txt = str(row.get("text") or "")
        if txt.strip():
            sacred_ws_hashes.add(norm_ws_hash(txt))
            pref = norm_alnum_prefix(txt)
            if len(pref) >= 40:
                sacred_alnum_prefixes.add(pref)

    prior_shas: set[str] = set()
    prior_link_keys: set[str] = set()
    prior_doc_keys: set[str] = set()
    prior_ws_hashes: set[str] = set()
    prior_alnum_prefixes: set[str] = set()
    prior_filenames: set[str] = set()

    prior_paths: list[Path] = []
    if not allow_rehydrate_360:
        prior_paths.append(TRAIN360_PATH)
    if include_prior_58:
        prior_paths.append(TRAIN58_PATH)
    if include_prior_2000 or include_prior_v6_3 or include_prior_v6_4:
        prior_paths.append(TARGET_GOLD_PATH)
    if include_prior_v6_3 or include_prior_v6_4:
        for vp in (GAP500_GOLD_PATH, REHYDRATED360_GOLD_PATH, COMPLETE_V6_3_GOLD_PATH):
            if vp not in prior_paths:
                prior_paths.append(vp)
    if include_prior_v6_4:
        for vp in (RESIDUAL160_GOLD_PATH, COMPLETE_V6_4_GOLD_PATH):
            if vp not in prior_paths:
                prior_paths.append(vp)
    exp_root = resolve_docmeta_v65_dir()
    s32_36_gold_paths: set[Path] = set()
    if include_prior_shards_32_36:
        for sid in range(32, 37):
            gp = exp_root / "outputs_2000" / f"gold_shard_{sid:02d}.jsonl"
            s32_36_gold_paths.add(gp)
            if gp not in prior_paths:
                prior_paths.append(gp)
            sp = exp_root / "shards_2000" / f"shard_{sid:02d}_store.json"
            if sp.is_file():
                st_data = json.loads(sp.read_text(encoding="utf-8"))
                for c in st_data.get("cases", []):
                    lk_c = str(c.get("link_key_hex") or "").strip().lower()
                    sb_c = str(c.get("saved_body_hex") or "").strip().lower()
                    dk_c = str(c.get("doc_key") or "").strip().lower()
                    fn_c = str(c.get("filename") or "").strip()
                    wt_c = str(c.get("window_text") or "")
                    if lk_c:
                        prior_link_keys.add(lk_c)
                    if sb_c:
                        prior_shas.add(sb_c)
                    if dk_c:
                        prior_doc_keys.add(dk_c)
                    if fn_c and fn_c.lower() not in GENERIC_ENDPOINT_FILENAMES:
                        prior_filenames.add(fn_c)
                    if wt_c.strip() and wt_c.strip() != EMPTY_BODY_PLACEHOLDER:
                        prior_ws_hashes.add(norm_ws_hash(wt_c))
                        pref_c = norm_alnum_prefix(wt_c)
                        if len(pref_c) >= 40:
                            prior_alnum_prefixes.add(pref_c)

    for prior_p in prior_paths:
        if not prior_p.is_file():
            continue
        for line in prior_p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            lk_val = str(obj.get("link_key_hex") or "").strip().lower()
            if allow_rehydrate_360 and prior_p == TRAIN58_PATH and lk_val in LEGACY_V4_TRAIN58_OVERLAP_LKS:
                continue
            if obj.get("saved_body_hex"):
                prior_shas.add(str(obj["saved_body_hex"]).strip().lower())
            if lk_val:
                prior_link_keys.add(lk_val)
            if obj.get("doc_key"):
                prior_doc_keys.add(str(obj["doc_key"]).strip().lower())
            msgs = obj.get("messages") or []
            if msgs and isinstance(msgs[0], dict):
                fn, txt = extract_prompt_filename_and_text(str(msgs[0].get("content") or ""))
                if fn and fn.lower() not in GENERIC_ENDPOINT_FILENAMES:
                    prior_filenames.add(fn)
                if txt.strip() and txt.strip() != EMPTY_BODY_PLACEHOLDER:
                    prior_ws_hashes.add(norm_ws_hash(txt))
                    # Prefix fingerprint is only needed for legacy unkeyed V4 records when rehydrated-360 SSOT keys are not loaded
                    # (keyed SSOT HTML records on the same committee/THOMAS domain share >240 chars of top CMS navigation menu).
                    if (
                        (include_prior_v6_4 and (prior_p == COMPLETE_V6_4_GOLD_PATH or prior_p in s32_36_gold_paths))
                        or (
                            not obj.get("saved_body_hex")
                            and not lk_val
                            and not ((include_prior_v6_3 or include_prior_v6_4) and REHYDRATED360_GOLD_PATH.is_file())
                        )
                    ):
                        pref = norm_alnum_prefix(txt)
                        if len(pref) >= 40:
                            prior_alnum_prefixes.add(pref)

    con = duckdb.connect()
    try:
        con.execute("SET memory_limit='4GB'")
        det_pq_path = DET_V6_2_PATH if DET_V6_2_PATH.is_file() else DET_V6_1_PATH
        if det_pq_path.is_file():
            rows = con.execute(
                f"""
                SELECT link_key_hex, doc_key, saved_body_hex, effective_body_sha_hex, filename
                FROM read_parquet('{det_pq_path}')
                """
            ).fetchall()
            for lk, dk, sb, eb, fn in rows:
                lk_l = lk.lower() if lk else ""
                dk_l = dk.lower() if dk else ""
                sb_l = sb.lower() if sb else ""
                eb_l = eb.lower() if eb else ""
                if (
                    (sb_l and sb_l in sacred_shas)
                    or (eb_l and eb_l in sacred_shas)
                    or (fn and fn in sacred_filenames and fn.lower() not in GENERIC_ENDPOINT_FILENAMES)
                ):
                    if lk_l:
                        sacred_link_keys.add(lk_l)
                    if dk_l:
                        sacred_doc_keys.add(dk_l)
                    if sb_l:
                        sacred_shas.add(sb_l)
                    if eb_l:
                        sacred_shas.add(eb_l)
                if (include_prior_v6_3 or include_prior_v6_4) and (
                    (lk_l and lk_l in prior_link_keys)
                    or (sb_l and sb_l in prior_shas)
                    or (eb_l and eb_l in prior_shas)
                ):
                    if dk_l:
                        prior_doc_keys.add(dk_l)
                    if sb_l:
                        prior_shas.add(sb_l)
                    if eb_l:
                        prior_shas.add(eb_l)
    finally:
        con.close()

    return {
        "sacred_shas": sacred_shas,
        "sacred_link_keys": sacred_link_keys,
        "sacred_doc_keys": sacred_doc_keys,
        "sacred_filenames": sacred_filenames,
        "sacred_ws_hashes": sacred_ws_hashes,
        "sacred_alnum_prefixes": sacred_alnum_prefixes,
        "prior_shas": prior_shas,
        "prior_link_keys": prior_link_keys,
        "prior_doc_keys": prior_doc_keys,
        "prior_ws_hashes": prior_ws_hashes,
        "prior_alnum_prefixes": prior_alnum_prefixes,
        "prior_filenames": prior_filenames,
    }


def validate_gold_record(
    record: Mapping[str, Any],
    forbidden: Mapping[str, set[str]],
) -> tuple[bool, list[str], dict[str, Any] | None]:
    errs: list[str] = []
    for k in REQUIRED_PROVENANCE_KEYS:
        val = record.get(k)
        if not isinstance(val, str) or not val.strip():
            errs.append(f"missing_provenance:{k}")

    sb = str(record.get("saved_body_hex") or "").strip().lower()
    lk = str(record.get("link_key_hex") or "").strip().lower()
    pv = str(record.get("parser_version") or "").strip().lower()
    tsha = str(record.get("text_sha256") or "").strip().lower()
    parser = str(record.get("parser") or "").strip()
    dk = str(record.get("doc_key") or "").strip().lower()

    if not HEX64_RE.match(sb):
        errs.append(f"invalid_saved_body_hex:{sb}")
    if not HEX16_RE.match(lk):
        errs.append(f"invalid_link_key_hex:{lk}")
    if not HEX64_RE.match(pv):
        errs.append(f"invalid_parser_version:{pv}")
    if not HEX64_RE.match(tsha):
        errs.append(f"invalid_text_sha256:{tsha}")
    if parser not in {"pdf_text", "html_text", "xml_text", "warc", "cold_r2_excerpt"}:
        errs.append(f"invalid_parser:{parser}")

    if sb in forbidden["sacred_shas"]:
        errs.append(f"SACRED_LEAK_SAVED_BODY:{sb}")
    if lk in forbidden["sacred_link_keys"]:
        errs.append(f"SACRED_LEAK_LINK_KEY:{lk}")
    if dk and dk in forbidden["sacred_doc_keys"]:
        errs.append(f"SACRED_LEAK_DOC_KEY:{dk}")

    if sb in forbidden["prior_shas"]:
        errs.append(f"DUPLICATE_PRIOR_SAVED_BODY:{sb}")
    if lk in forbidden["prior_link_keys"]:
        errs.append(f"DUPLICATE_PRIOR_LINK_KEY:{lk}")
    if dk and dk in forbidden.get("prior_doc_keys", set()):
        errs.append(f"DUPLICATE_PRIOR_DOC_KEY:{dk}")

    msgs = record.get("messages")
    if not isinstance(msgs, list) or len(msgs) != 2:
        errs.append("messages_must_be_2_turn_list")
        return False, errs, None

    u_msg, a_msg = msgs[0], msgs[1]
    if not isinstance(u_msg, dict) or u_msg.get("role") != "user" or not isinstance(u_msg.get("content"), str):
        errs.append("invalid_user_message")
        return False, errs, None
    if not isinstance(a_msg, dict) or a_msg.get("role") != "assistant":
        errs.append("invalid_assistant_message")
        return False, errs, None

    fn, prompt_txt = extract_prompt_filename_and_text(u_msg["content"])
    ws_h = norm_ws_hash(prompt_txt)
    alnum_p = norm_alnum_prefix(prompt_txt)
    if ws_h in forbidden["sacred_ws_hashes"] or (len(alnum_p) >= 40 and alnum_p in forbidden["sacred_alnum_prefixes"]):
        errs.append("SACRED_LEAK_TEXT_FINGERPRINT")
    if fn and fn in forbidden["sacred_filenames"] and fn.lower() not in GENERIC_ENDPOINT_FILENAMES:
        errs.append(f"SACRED_LEAK_FILENAME:{fn}")

    raw_gold = a_msg.get("content")
    if isinstance(raw_gold, str):
        try:
            gold_obj = json.loads(raw_gold)
        except Exception as exc:
            errs.append(f"assistant_json_parse_error:{exc}")
            return False, errs, None
    elif isinstance(raw_gold, Mapping):
        gold_obj = dict(raw_gold)
    else:
        errs.append("invalid_assistant_content_type")
        return False, errs, None

    try:
        canon = canonicalize_docmeta_v4(gold_obj)
    except Exception as exc:
        errs.append(f"canonicalize_error:{exc}")
        return False, errs, None

    status_val = str(canon.get("status") or "usable")
    if not prompt_txt.strip():
        errs.append("prompt_text_too_short")
    elif len(prompt_txt.strip()) < 20 and status_val not in SHORT_TEXT_ALLOWED_STATUSES:
        errs.append("prompt_text_too_short")

    # Prose duplicate fingerprint check (stub_or_blank / error_or_block / ocr_unreadable may share [EMPTY_BODY] or short server error text while having distinct saved_body_hex & link_key_hex)
    if status_val not in SHORT_TEXT_ALLOWED_STATUSES and prompt_txt.strip() != EMPTY_BODY_PLACEHOLDER:
        if ws_h in forbidden["prior_ws_hashes"] or (len(alnum_p) >= 40 and alnum_p in forbidden["prior_alnum_prefixes"]):
            errs.append("DUPLICATE_PRIOR_GOLD_TEXT")

    ok_v4, err_v4 = validate_docmeta_v4(canon)
    if not ok_v4:
        errs.append(f"validate_docmeta_v4:{err_v4}")

    ok_strict, strict_err = strict_validate_v4(canon)
    if not ok_strict:
        errs.append(f"strict_validate_v4:{strict_err}")

    canon_str = json.dumps(canon, separators=(",", ":"), ensure_ascii=False)

    if status_val == "usable":
        ct = str(canon.get("composed_title") or "")
        gist = str(canon.get("gist") or "")
        if len(ct) >= 110 or len(ct) < 8:
            errs.append(f"composed_title_length:{len(ct)}")
        if len(gist.split()) > 22 or len(gist.split()) < 4:
            errs.append(f"gist_word_count:{len(gist.split())}")

    if errs:
        return False, errs, None

    normalized_record: dict[str, Any] = {
        "messages": [
            {"role": "user", "content": u_msg["content"]},
            {"role": "assistant", "content": canon_str},
        ],
        "saved_body_hex": sb,
        "link_key_hex": lk,
        "parser": parser,
        "parser_version": pv,
        "text_sha256": tsha,
        "stratum": str(record["stratum"]).strip(),
        "reviewer_id": str(record["reviewer_id"]).strip(),
    }
    if record.get("full_text_chars") is not None:
        normalized_record["full_text_chars"] = int(record["full_text_chars"])
    if record.get("cluster_id"):
        normalized_record["cluster_id"] = str(record["cluster_id"])
    if dk:
        normalized_record["doc_key"] = dk
    return True, [], normalized_record


def _ws_dedupe_key(norm_record: Mapping[str, Any]) -> str:
    _, prompt_txt = extract_prompt_filename_and_text(norm_record["messages"][0]["content"])
    ws_h = norm_ws_hash(prompt_txt)
    status_val = json.loads(norm_record["messages"][1]["content"]).get("status", "usable")
    if status_val in SHORT_TEXT_ALLOWED_STATUSES or prompt_txt.strip() == EMPTY_BODY_PLACEHOLDER:
        return f"{norm_record['saved_body_hex']}:{ws_h}"
    return ws_h


def _validate_jsonl_files(
    paths: list[Path],
    forbidden: Mapping[str, set[str]],
) -> tuple[list[dict[str, Any]], list[tuple[str, int, list[str]]]]:
    seen_sb: set[str] = set()
    seen_lk: set[str] = set()
    seen_dk: set[str] = set()
    seen_ws: set[str] = set()
    seen_alnum: set[str] = set()
    valid_records: list[dict[str, Any]] = []
    failures: list[tuple[str, int, list[str]]] = []

    for inp in paths:
        for lineno, line in enumerate(inp.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            raw = json.loads(line)
            ok, errs, norm = validate_gold_record(raw, forbidden)
            if not ok or norm is None:
                failures.append((str(inp), lineno, errs))
                continue
            wkey = _ws_dedupe_key(norm)
            dk = str(norm.get("doc_key") or "").strip().lower()
            _, p_txt = extract_prompt_filename_and_text(norm["messages"][0]["content"])
            st_v = json.loads(norm["messages"][1]["content"]).get("status", "usable")
            ap_v = norm_alnum_prefix(p_txt) if (st_v not in SHORT_TEXT_ALLOWED_STATUSES and p_txt.strip() != EMPTY_BODY_PLACEHOLDER) else ""
            if (
                norm["saved_body_hex"] in seen_sb
                or norm["link_key_hex"] in seen_lk
                or (dk and dk in seen_dk)
                or wkey in seen_ws
                or (len(ap_v) >= 40 and ap_v in seen_alnum)
            ):
                failures.append((str(inp), lineno, ["duplicate_within_batch"]))
                continue
            seen_sb.add(norm["saved_body_hex"])
            seen_lk.add(norm["link_key_hex"])
            if dk:
                seen_dk.add(dk)
            seen_ws.add(wkey)
            if len(ap_v) >= 40:
                seen_alnum.add(ap_v)
            valid_records.append(norm)
    return valid_records, failures


def _atomic_write_jsonl(out_path: Path, records: list[dict[str, Any]]) -> str:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".jsonl.tmp")
    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(out_path)
    return sha256(out_path.read_bytes()).hexdigest()


def _infer_flags_from_inputs(
    inputs: list[Path],
    prior_2000_flag: bool,
    allow_rehyd_flag: bool,
    prior_v6_3_flag: bool = False,
    prior_v6_4_flag: bool = False,
    prior_shards_32_36_flag: bool = False,
) -> tuple[bool, bool, bool, bool, bool]:
    names = [p.name for p in inputs]
    if prior_shards_32_36_flag or (names and all(SHARD_37_LINEAGE_RE.search(n) for n in names)):
        return True, False, True, True, True
    if prior_v6_4_flag or (names and all(SHARD_V65_RARE_RE.search(n) for n in names)):
        return True, False, True, True, False
    if prior_v6_3_flag or (names and all(SHARD_V64_GAP_RE.search(n) for n in names)):
        return True, False, True, False, False
    if allow_rehyd_flag or (names and all(SHARD_REHYD_RE.search(n) for n in names)):
        return True, True, False, False, False
    if prior_2000_flag or (names and all(SHARD_GAP_RE.search(n) for n in names)):
        return True, False, False, False, False
    return prior_2000_flag, allow_rehyd_flag, prior_v6_3_flag, prior_v6_4_flag, prior_shards_32_36_flag


def cmd_consolidate_v6_3(args: argparse.Namespace) -> int:
    sacred_only = load_forbidden_sets(
        include_prior_2000=False,
        allow_rehydrate_360=True,
        include_prior_58=False,
    )
    forb_gap = load_forbidden_sets(include_prior_2000=True, allow_rehydrate_360=False, include_prior_58=True)
    forb_rehyd = load_forbidden_sets(include_prior_2000=True, allow_rehydrate_360=True, include_prior_58=True)

    gap_records, gap_fails = _validate_jsonl_files(args.gap_500, forb_gap)
    rehyd_records, rehyd_fails = _validate_jsonl_files(args.rehydrated_360, forb_rehyd)
    b58_records, b58_fails = _validate_jsonl_files([args.bodytext_58], sacred_only)
    c2000_records, c2000_fails = _validate_jsonl_files([args.cluster_2000], sacred_only)

    all_fails = [*gap_fails, *rehyd_fails, *b58_fails, *c2000_fails]
    if all_fails:
        for path_s, ln, errs in all_fails:
            print(f"FAIL {path_s}:{ln} -> {errs}", file=sys.stderr)
        return 1

    if not args.allow_partial:
        if len(gap_records) != 500:
            print(f"FAIL expected 500 gap records, got {len(gap_records)}", file=sys.stderr)
            return 1
        if len(rehyd_records) != 360:
            print(f"FAIL expected 360 rehydrated V4 records, got {len(rehyd_records)}", file=sys.stderr)
            return 1
        if len(b58_records) != 58:
            print(f"FAIL expected 58 bodytext records, got {len(b58_records)}", file=sys.stderr)
            return 1
        if len(c2000_records) != 2000:
            print(f"FAIL expected 2000 cluster records, got {len(c2000_records)}", file=sys.stderr)
            return 1

    rehyd_lks = {r["link_key_hex"] for r in rehyd_records}
    deduped_legacy_lks: list[str] = []
    filtered_b58: list[dict[str, Any]] = []
    for r in b58_records:
        if r["link_key_hex"] in rehyd_lks and r["link_key_hex"] in LEGACY_V4_TRAIN58_OVERLAP_LKS:
            deduped_legacy_lks.append(r["link_key_hex"])
            continue
        filtered_b58.append(r)

    seen_sb: set[str] = set()
    seen_lk: set[str] = set()
    seen_ws: set[str] = set()
    complete_records: list[dict[str, Any]] = []
    cross_dups: list[str] = []

    for label, batch in (
        ("rehydrated_360", rehyd_records),
        ("bodytext_58", filtered_b58),
        ("cluster_2000", c2000_records),
        ("gap_500", gap_records),
    ):
        for r in batch:
            wkey = _ws_dedupe_key(r)
            if r["saved_body_hex"] in seen_sb or r["link_key_hex"] in seen_lk or wkey in seen_ws:
                cross_dups.append(f"{label}:lk={r['link_key_hex']}:sb={r['saved_body_hex'][:16]}")
                continue
            seen_sb.add(r["saved_body_hex"])
            seen_lk.add(r["link_key_hex"])
            seen_ws.add(wkey)
            complete_records.append(r)

    if cross_dups:
        for cd in cross_dups:
            print(f"FAIL cross_set_duplicate -> {cd}", file=sys.stderr)
        return 1

    sha_gap = _atomic_write_jsonl(args.out_gap500, gap_records)
    sha_rehyd = _atomic_write_jsonl(args.out_rehydrated360, rehyd_records)
    sha_comp = _atomic_write_jsonl(args.out_complete, complete_records)

    print(
        json.dumps(
            {
                "status": "consolidated_v6_3",
                "gap500_out": str(args.out_gap500),
                "gap500_records": len(gap_records),
                "gap500_sha256": sha_gap,
                "rehydrated360_out": str(args.out_rehydrated360),
                "rehydrated360_records": len(rehyd_records),
                "rehydrated360_sha256": sha_rehyd,
                "complete_out": str(args.out_complete),
                "complete_records": len(complete_records),
                "raw_component_sum": len(rehyd_records) + len(b58_records) + len(c2000_records) + len(gap_records),
                "deduped_legacy_v4_train58_overlaps": deduped_legacy_lks,
                "complete_sha256": sha_comp,
                "sacred_shas_guarded": len(sacred_only["sacred_shas"]),
                "sacred_link_keys_guarded": len(sacred_only["sacred_link_keys"]),
            },
            indent=2,
        )
    )
    return 0


def cmd_consolidate_v6_4(args: argparse.Namespace) -> int:
    sacred_only = load_forbidden_sets(
        include_prior_2000=False,
        allow_rehydrate_360=True,
        include_prior_58=False,
        include_prior_v6_3=False,
    )
    forb_v6_4 = load_forbidden_sets(
        include_prior_2000=True,
        allow_rehydrate_360=False,
        include_prior_58=True,
        include_prior_v6_3=True,
    )

    v63_records, v63_fails = _validate_jsonl_files([args.prior_complete_v6_3], sacred_only)
    gap160_records, gap160_fails = _validate_jsonl_files(args.gap_160, forb_v6_4)

    all_fails = [*v63_fails, *gap160_fails]
    if all_fails:
        for path_s, ln, errs in all_fails:
            print(f"FAIL {path_s}:{ln} -> {errs}", file=sys.stderr)
        return 1

    if not args.allow_partial:
        if len(v63_records) != 2917:
            print(f"FAIL expected 2917 V6.3 complete records, got {len(v63_records)}", file=sys.stderr)
            return 1
        if len(gap160_records) != 160:
            print(f"FAIL expected 160 V6.4 residual gap records, got {len(gap160_records)}", file=sys.stderr)
            return 1

    seen_sb: set[str] = set()
    seen_lk: set[str] = set()
    seen_dk: set[str] = set()
    seen_ws: set[str] = set()
    complete_records: list[dict[str, Any]] = []
    cross_dups: list[str] = []

    for label, batch in (
        ("prior_v6_3_complete", v63_records),
        ("residual_gap_160", gap160_records),
    ):
        for r in batch:
            wkey = _ws_dedupe_key(r)
            dk = str(r.get("doc_key") or "").strip().lower()
            if (
                r["saved_body_hex"] in seen_sb
                or r["link_key_hex"] in seen_lk
                or (dk and dk in seen_dk)
                or wkey in seen_ws
            ):
                cross_dups.append(f"{label}:lk={r['link_key_hex']}:sb={r['saved_body_hex'][:16]}")
                continue
            seen_sb.add(r["saved_body_hex"])
            seen_lk.add(r["link_key_hex"])
            if dk:
                seen_dk.add(dk)
            seen_ws.add(wkey)
            complete_records.append(r)

    if cross_dups:
        for cd in cross_dups:
            print(f"FAIL cross_set_duplicate -> {cd}", file=sys.stderr)
        return 1

    sha_gap160 = _atomic_write_jsonl(args.out_residual160, gap160_records)
    sha_comp = _atomic_write_jsonl(args.out_complete, complete_records)

    print(
        json.dumps(
            {
                "status": "consolidated_v6_4",
                "residual160_out": str(args.out_residual160),
                "residual160_records": len(gap160_records),
                "residual160_sha256": sha_gap160,
                "prior_v6_3_records": len(v63_records),
                "complete_out": str(args.out_complete),
                "complete_records": len(complete_records),
                "complete_sha256": sha_comp,
                "sacred_shas_guarded": len(sacred_only["sacred_shas"]),
                "sacred_link_keys_guarded": len(sacred_only["sacred_link_keys"]),
                "prior_shas_guarded": len(forb_v6_4["prior_shas"]),
                "prior_link_keys_guarded": len(forb_v6_4["prior_link_keys"]),
            },
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="Validate one or more candidate gold JSONL files")
    p_check.add_argument("inputs", nargs="+", type=Path)
    p_check.add_argument("--prior-2000", action="store_true", help="Also guard against train_v6_2_cluster_hydrogen_high.jsonl")
    p_check.add_argument("--prior-v6-3", action="store_true", help="Also guard against train_v6_3_complete_ssot_gold.jsonl + train_58")
    p_check.add_argument("--prior-v6-4", action="store_true", help="Also guard against train_v6_4_complete_ssot_gold.jsonl (3,077 rows)")
    p_check.add_argument("--prior-shards-32-36", action="store_true", help="Also guard against Shards 32..36 stores and outputs")
    p_check.add_argument("--allow-rehydrate-360", action="store_true", help="Allow replacing legacy train_v4_all360.jsonl (Shards 26..29)")

    p_merge = sub.add_parser("consolidate", help="Validate, deduplicate, and write consolidated gold JSONL")
    p_merge.add_argument("inputs", nargs="+", type=Path)
    p_merge.add_argument("--out", type=Path, default=resolve_docmeta_v65_dir() / "outputs_2000/train_v6_5_raretypes_hydrogen_high.jsonl")
    p_merge.add_argument("--write-combined", action="store_true", help="Also write combined (360+58+new) JSONL")
    p_merge.add_argument("--prior-2000", action="store_true", help="Also guard against train_v6_2_cluster_hydrogen_high.jsonl")
    p_merge.add_argument("--prior-v6-3", action="store_true", help="Also guard against train_v6_3_complete_ssot_gold.jsonl + train_58")
    p_merge.add_argument("--prior-v6-4", action="store_true", help="Also guard against train_v6_4_complete_ssot_gold.jsonl (3,077 rows)")
    p_merge.add_argument("--prior-shards-32-36", action="store_true", help="Also guard against Shards 32..36 stores and outputs")
    p_merge.add_argument("--allow-rehydrate-360", action="store_true", help="Allow replacing legacy train_v4_all360.jsonl")

    p_v63 = sub.add_parser("consolidate-v6-3", help="Validate and consolidate V6.3 Gap-500 + Rehydrated-360 + V6.2-2000 + V6-58 SSOT gold")
    p_v63.add_argument("--gap-500", nargs="+", type=Path, required=True, help="Shard 21..25 JSONL files (500 gap records)")
    p_v63.add_argument("--rehydrated-360", nargs="+", type=Path, required=True, help="Shard 26..29 JSONL files (360 rehydrated V4 records)")
    p_v63.add_argument("--cluster-2000", type=Path, default=TARGET_GOLD_PATH)
    p_v63.add_argument("--bodytext-58", type=Path, default=TRAIN58_PATH)
    p_v63.add_argument("--out-gap500", type=Path, default=GAP500_GOLD_PATH)
    p_v63.add_argument("--out-rehydrated360", type=Path, default=REHYDRATED360_GOLD_PATH)
    p_v63.add_argument("--out-complete", type=Path, default=COMPLETE_V6_3_GOLD_PATH)
    p_v63.add_argument("--allow-partial", action="store_true", help="Allow partial shard counts during smoke tests")

    p_v64 = sub.add_parser("consolidate-v6-4", help="Validate and consolidate V6.4 Residual-160 (Shards 30..31) + V6.3 Complete-SSOT (2,917) -> 3,077 SSOT gold")
    p_v64.add_argument("--gap-160", nargs="+", type=Path, required=True, help="Shard 30..31 JSONL files (160 residual gap records)")
    p_v64.add_argument("--prior-complete-v6-3", type=Path, default=COMPLETE_V6_3_GOLD_PATH)
    p_v64.add_argument("--out-residual160", type=Path, default=RESIDUAL160_GOLD_PATH)
    p_v64.add_argument("--out-complete", type=Path, default=COMPLETE_V6_4_GOLD_PATH)
    p_v64.add_argument("--allow-partial", action="store_true", help="Allow partial shard counts during smoke tests")

    args = ap.parse_args(argv)
    if args.cmd == "consolidate-v6-3":
        return cmd_consolidate_v6_3(args)
    if args.cmd == "consolidate-v6-4":
        return cmd_consolidate_v6_4(args)

    inc_2000, allow_rehyd, inc_v63, inc_v64, inc_s32_36 = _infer_flags_from_inputs(
        args.inputs,
        args.prior_2000,
        args.allow_rehydrate_360,
        args.prior_v6_3,
        args.prior_v6_4,
        args.prior_shards_32_36,
    )
    forbidden = load_forbidden_sets(
        include_prior_2000=inc_2000,
        allow_rehydrate_360=allow_rehyd,
        include_prior_v6_3=inc_v63,
        include_prior_v6_4=inc_v64,
        include_prior_shards_32_36=inc_s32_36,
    )
    valid_records, failures = _validate_jsonl_files(args.inputs, forbidden)

    if failures:
        for path_s, ln, errs in failures:
            print(f"FAIL {path_s}:{ln} -> {errs}", file=sys.stderr)
        return 1

    if args.cmd == "consolidate":
        out_path: Path = args.out
        sha_out = _atomic_write_jsonl(out_path, valid_records)
        result: dict[str, Any] = {
            "status": "consolidated",
            "out": str(out_path),
            "new_records": len(valid_records),
            "sha256": sha_out,
            "sacred_shas_guarded": len(forbidden["sacred_shas"]),
            "sacred_link_keys_guarded": len(forbidden["sacred_link_keys"]),
            "prior_gold_guarded": len(forbidden["prior_ws_hashes"]),
            "include_prior_2000": inc_2000,
            "include_prior_v6_3": inc_v63,
            "include_prior_v6_4": inc_v64,
            "include_prior_shards_32_36": inc_s32_36,
            "allow_rehydrate_360": allow_rehyd,
        }
        if args.write_combined:
            comb_out = out_path.parent / "train_v6_5_combined_gold.jsonl"
            comb_lines: list[str] = []
            for p in (COMPLETE_V6_4_GOLD_PATH, out_path):
                if p.is_file():
                    comb_lines.extend(l for l in p.read_text(encoding="utf-8").splitlines() if l.strip())
            tmp_c = comb_out.with_suffix(".jsonl.tmp")
            tmp_c.write_text("\n".join(comb_lines) + "\n", encoding="utf-8")
            tmp_c.replace(comb_out)
            result["combined_out"] = str(comb_out)
            result["combined_records"] = len(comb_lines)
            result["combined_sha256"] = sha256(comb_out.read_bytes()).hexdigest()
        print(json.dumps(result, indent=2))
    else:
        print(
            json.dumps(
                {
                    "status": "valid",
                    "records": len(valid_records),
                    "sacred_shas_guarded": len(forbidden["sacred_shas"]),
                    "sacred_link_keys_guarded": len(forbidden["sacred_link_keys"]),
                    "prior_gold_guarded": len(forbidden["prior_ws_hashes"]),
                    "include_prior_2000": inc_2000,
                    "include_prior_v6_3": inc_v63,
                    "include_prior_v6_4": inc_v64,
                    "include_prior_shards_32_36": inc_s32_36,
                    "allow_rehydrate_360": allow_rehyd,
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
