#!/usr/bin/env python3
"""Build static JSON bundle for the local DocMeta v6.5 review web app."""
from __future__ import annotations

import argparse
import collections
import json
import os
from pathlib import Path
import re
import time

import pyarrow.parquet as pq

from ..paths import resolve_docmeta_v6_data_dir, resolve_docmeta_v65_dir, resolve_package_fallback

PROMPT_RE = re.compile(
    r"\nAdvisory known metadata:\s*([^\n]*)\nFilename:\s*([^\n]*)\nText:\n(.*)$",
    re.DOTALL,
)

OPEN_FINDING_STATUSES = frozenset({"needs_owner", "scope_question"})


def _infer_format(effective_format: str | None, filename: str, parser: str | None) -> str:
    if effective_format and effective_format.strip():
        fmt = effective_format.strip().lower()
        if fmt in ("htm", "xhtml"):
            return "html"
        if fmt == "txt":
            return "text"
        return fmt
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext in ("pdf", "docx", "doc", "xml", "json", "csv"):
        return ext
    if ext in ("htm", "html", "xhtml"):
        return "html"
    if ext == "txt":
        return "text"
    if parser == "pdf_text":
        return "pdf"
    if parser == "html_text":
        return "html"
    if parser == "xml_text":
        return "xml"
    if parser == "warc":
        return "warc"
    return ext or "other"


def _parse_prompt(prompt: str) -> tuple[object, str, str]:
    m = PROMPT_RE.search(prompt)
    if not m:
        return None, "", prompt
    known_str, filename, text = m.group(1).strip(), m.group(2).strip(), m.group(3)
    try:
        known = json.loads(known_str) if known_str else None
    except json.JSONDecodeError:
        known = known_str
    return known, filename, text


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v65-dir", type=Path, default=None)
    parser.add_argument("--v6-dir", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    v65_dir = args.v65_dir.expanduser().resolve() if args.v65_dir is not None else resolve_docmeta_v65_dir()
    v6_dir = args.v6_dir.expanduser().resolve() if args.v6_dir is not None else resolve_docmeta_v6_data_dir()
    queue_parquet = v6_dir / "parquets_v6_2/llm_queue_v6_2.parquet"
    ssot_path = v65_dir / "ssot/docmeta_gold_v6_5.jsonl"
    signal_path = v65_dir / "lookups_and_gold/gold_v6_5n_signal.jsonl"
    changelog_path = v65_dir / "lookups_and_gold/normalize_changelog.jsonl"
    findings_path = v65_dir / "raw_review_20261118/full/findings_all.jsonl"
    resolution_path = v65_dir / "lookups_and_gold/swarm_resolution.jsonl"
    adjudications_path = resolve_package_fallback(v65_dir / "contract/adjudications.jsonl", "adjudications.jsonl")
    second_opinion_path = v65_dir / "lookups_and_gold/second_opinion_rulings.jsonl"
    second_opinion_held_path = v65_dir / "lookups_and_gold/second_opinion_held.jsonl"
    second_opinion_applied_path = v65_dir / "lookups_and_gold/second_opinion_applied.jsonl"
    out_dir = (args.out_dir.expanduser().resolve() if args.out_dir is not None else (v65_dir / "viewer/data"))
    docs_dir = out_dir / "docs"

    t0 = time.monotonic()
    docs_dir.mkdir(parents=True, exist_ok=True)

    ssot_rows = _read_jsonl(ssot_path)
    key_set = {r["link_key_hex"] for r in ssot_rows}
    print(f"Loaded {len(ssot_rows)} SSOT rows ({len(key_set)} unique keys)")

    # Read only needed parquet columns, filtered strictly to the 3,733 keys
    pq_cols = [
        "link_key_hex",
        "filename",
        "p12_raw_text",
        "p12_clean_text",
        "known_json",
        "effective_format",
    ]
    queue_by_key: dict[str, dict] = {}
    if queue_parquet.is_file():
        table = pq.read_table(
            queue_parquet,
            columns=pq_cols,
            filters=[("link_key_hex", "in", key_set)],
        )
        for row in table.to_pylist():
            queue_by_key[row["link_key_hex"]] = row
        del table
    print(f"Matched {len(queue_by_key)} / {len(ssot_rows)} rows in llm_queue_v6_2.parquet")

    # Removed values (signal)
    signal_by_key: dict[str, list[dict]] = collections.defaultdict(list)
    for item in _read_jsonl(signal_path):
        k = item.get("link_key_hex")
        if k in key_set:
            signal_by_key[k].append(
                {
                    "field": item.get("field"),
                    "value": item.get("value"),
                    "source": item.get("source"),
                    "occurs_in": item.get("occurs_in"),
                    "rule": item.get("rule"),
                }
            )

    # Normalize changelog
    changes_by_key: dict[str, list[dict]] = collections.defaultdict(list)
    for item in _read_jsonl(changelog_path):
        k = item.get("link_key_hex")
        if k in key_set:
            changes_by_key[k].append(
                {
                    "rule": item.get("rule"),
                    "field": item.get("field"),
                    "before": item.get("before"),
                    "after": item.get("after"),
                }
            )

    # Reviewer findings + swarm resolution
    raw_findings = _read_jsonl(findings_path)
    resolutions = _read_jsonl(resolution_path)
    findings_by_key: dict[str, list[dict]] = collections.defaultdict(list)

    if len(raw_findings) == len(resolutions) and all(
        f.get("key") == r.get("key") and f.get("field") == r.get("field")
        for f, r in zip(raw_findings, resolutions)
    ):
        paired = zip(raw_findings, resolutions)
    else:
        res_lookup: dict[tuple, dict] = {}
        for r in resolutions:
            rk = (r.get("key"), r.get("field"), r.get("type"), r.get("quote"))
            res_lookup[rk] = r
        paired = [
            (f, res_lookup.get((f.get("key"), f.get("field"), f.get("type"), f.get("quote")), {}))
            for f in raw_findings
        ]

    for f, r in paired:
        k = f.get("key")
        if k not in key_set:
            continue
        findings_by_key[k].append(
            {
                "field": f.get("field"),
                "type": f.get("type"),
                "status": r.get("status", "unknown"),
                "rule": r.get("rule"),
                "reason": r.get("reason"),
                "basis": r.get("basis"),
                "quote": f.get("quote"),
                "quote_verified": f.get("quote_verified"),
                "label_value": f.get("label_value"),
                "should_be": f.get("should_be"),
                "why": f.get("why"),
                "confidence": f.get("confidence"),
            }
        )

    # Surface Stage-3 held and not_applied second-opinion rulings under `needs_owner`
    so_rulings = {(r.get("link_key_hex"), int(r["n"])): r for r in _read_jsonl(second_opinion_path) if r.get("n") is not None}
    for item in _read_jsonl(second_opinion_held_path):
        k = item.get("link_key_hex")
        if k not in key_set:
            continue
        fr = item.get("first_reviewer") or {}
        findings_by_key[k].append(
            {
                "field": item.get("field"),
                "type": fr.get("type"),
                "status": "needs_owner",
                "rule": "C2_held",
                "reason": item.get("held_reason"),
                "basis": "second_opinion_held",
                "quote": item.get("quote"),
                "quote_verified": None,
                "label_value": fr.get("label_value"),
                "should_be": item.get("final_value"),
                "why": item.get("why"),
                "confidence": item.get("confidence"),
            }
        )
    for item in _read_jsonl(second_opinion_applied_path):
        if item.get("status") != "not_applied":
            continue
        k = item.get("link_key_hex")
        n_val = item.get("n")
        if k not in key_set or n_val is None:
            continue
        ruling = so_rulings.get((k, int(n_val)), {})
        fr = ruling.get("first_reviewer") or {}
        findings_by_key[k].append(
            {
                "field": item.get("field") or ruling.get("field"),
                "type": fr.get("type"),
                "status": "needs_owner",
                "rule": "C2_not_applied",
                "reason": item.get("reason"),
                "basis": "second_opinion_not_applied",
                "quote": ruling.get("quote"),
                "quote_verified": None,
                "label_value": fr.get("label_value"),
                "should_be": item.get("final_value") if "final_value" in item else ruling.get("final_value"),
                "why": ruling.get("why"),
                "confidence": ruling.get("confidence"),
            }
        )

    # Rulings (adjudications)
    rulings_by_key: dict[str, list[dict]] = collections.defaultdict(list)
    for item in _read_jsonl(adjudications_path):
        k = item.get("link_key_hex")
        if k in key_set:
            rulings_by_key[k].append(
                {
                    "rule": item.get("rule"),
                    "verdict": item.get("verdict"),
                    "quote": item.get("quote"),
                    "ruled_by": item.get("ruled_by"),
                    "ruled_at": item.get("ruled_at"),
                    "note": item.get("note"),
                }
            )

    index_entries: list[dict] = []

    for row in ssot_rows:
        key = row["link_key_hex"]
        messages = row.get("messages") or []
        prompt_content = messages[0]["content"] if messages else ""
        label_raw = messages[-1]["content"] if len(messages) >= 2 else "{}"
        label = json.loads(label_raw)

        prompt_known, prompt_filename, prompt_text = _parse_prompt(prompt_content)
        q = queue_by_key.get(key)

        if q is not None:
            filename = q.get("filename") or prompt_filename or key
            if q.get("p12_raw_text"):
                text = q["p12_raw_text"]
                text_source = "p12_raw_text"
            elif q.get("p12_clean_text"):
                text = q["p12_clean_text"]
                text_source = "p12_clean_text"
            else:
                text = prompt_text
                text_source = "prompt"
            known_raw = q.get("known_json")
            if known_raw:
                try:
                    known = json.loads(known_raw)
                except json.JSONDecodeError:
                    known = known_raw
            else:
                known = prompt_known
            fmt = _infer_format(q.get("effective_format"), filename, row.get("parser"))
        else:
            filename = prompt_filename or key
            text = prompt_text
            text_source = "prompt"
            known = prompt_known
            fmt = _infer_format(None, filename, row.get("parser"))

        sig_list = signal_by_key.get(key) or row.get("signal") or []
        chg_list = changes_by_key.get(key, [])
        fnd_list = findings_by_key.get(key, [])
        rul_list = rulings_by_key.get(key, [])

        personas = label.get("personas") or []
        people_count = len(personas) if isinstance(personas, list) else 0
        status_val = label.get("status") or "unknown"
        primary_kind = label.get("primary_kind")
        kind_or_status = primary_kind if primary_kind else f"status:{status_val}"

        open_count = sum(1 for item in fnd_list if item.get("status") in OPEN_FINDING_STATUSES)
        needs_owner_count = sum(1 for item in fnd_list if item.get("status") == "needs_owner")

        index_entries.append(
            {
                "key": key,
                "split": row.get("split") or "unknown",
                "kind": kind_or_status,
                "status": status_val,
                "filename": filename,
                "format": fmt,
                "people_count": people_count,
                "has_open_findings": open_count > 0,
                "open_findings_count": open_count,
                "needs_owner_count": needs_owner_count,
                "findings_count": len(fnd_list),
                "has_removed_values": len(sig_list) > 0,
                "removed_count": len(sig_list),
                "has_rulings": len(rul_list) > 0,
                "rulings_count": len(rul_list),
                "changes_count": len(chg_list),
                "more_than_10_people": people_count > 10,
            }
        )

        doc_payload = {
            "key": key,
            "doc_key": row.get("doc_key"),
            "saved_body_hex": row.get("saved_body_hex"),
            "split": row.get("split"),
            "excluded_reason": row.get("excluded_reason"),
            "source_batch": row.get("source_batch"),
            "seen_template": row.get("seen_template"),
            "parser": row.get("parser"),
            "filename": filename,
            "format": fmt,
            "known": known,
            "text_source": text_source,
            "text": text,
            "label": label,
            "label_raw": label_raw,
            "signal": sig_list,
            "changes": chg_list,
            "findings": fnd_list,
            "rulings": rul_list,
        }

        doc_path = docs_dir / f"{key}.json"
        tmp_doc = docs_dir / f".{key}.json.tmp"
        tmp_doc.write_text(json.dumps(doc_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp_doc, doc_path)

    # Sort index predictably: non-train review splits first or archive key order? Keep SSOT order or key order
    index_path = out_dir / "index.json"
    tmp_index = out_dir / ".index.json.tmp"
    tmp_index.write_text(
        json.dumps(index_entries, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(tmp_index, index_path)

    elapsed = time.monotonic() - t0
    print(f"Wrote {len(index_entries)} docs and {index_path} in {elapsed:.2f}s")


if __name__ == "__main__":
    main()
