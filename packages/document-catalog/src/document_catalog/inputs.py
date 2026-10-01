"""Discover every input; deduplicate decoded source bytes while retaining aliases."""

import gzip
import json
import mimetypes
from pathlib import Path
import re

from .store import digest, identity


def discover(paths=(), manifest=None):
    rows = []
    for supplied in paths:
        path = Path(supplied).resolve()
        candidates = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
        rows.extend({"path": str(p), "filename": p.name} for p in candidates)
    if manifest:
        base = Path(manifest).resolve().parent
        value = json.loads(Path(manifest).read_text())
        supplied = value if isinstance(value, list) else value.get("sources", value.get("documents"))
        if not isinstance(supplied, list):
            raise ValueError("Manifest requires a sources array")
        for item in supplied:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ValueError("Each manifest source requires a path")
            row = dict(item)
            path = Path(row["path"])
            row["path"] = str((base / path).resolve() if not path.is_absolute() else path.resolve())
            row.setdefault("filename", path.name)
            rows.append(row)
    # Repeated identical manifest entries are not additional independent sources.
    return [dict(row, source_entry_id=identity(row)) for row in {identity(row): row for row in rows}.values()]


def source_format(data, filename):
    if data.lstrip()[:5] == b"%PDF-":
        return "pdf", "application/pdf", "magic"
    mime = mimetypes.guess_type(filename.removesuffix(".gz"))[0]
    suffix = Path(filename.removesuffix(".gz")).suffix.lower().lstrip(".") or "unknown"
    return suffix, mime or "application/octet-stream", "filename"


def ingest(store, rows, config):
    documents, entries = {}, []
    pattern = config["selection"]["filename_regex"]
    for row in rows:
        entry = {"source_entry_id": row["source_entry_id"], "alias": row}
        if pattern and not re.search(pattern, row["filename"]):
            entries.append({**entry, "status": "no_match", "document_id": None})
            continue
        try:
            raw = Path(row["path"]).read_bytes()
            compressed = raw[:2] == b"\x1f\x8b"
            data = gzip.decompress(raw) if compressed else raw
            sha = digest(data)
            if row.get("sha256") and row["sha256"] != sha:
                raise ValueError("Manifest source sha256 does not match decoded bytes")
            doc_id = f"d-{sha}"
            format_, mime, evidence = source_format(data, row["filename"])
            if doc_id not in documents:
                documents[doc_id] = {"document_id": doc_id, "source_sha256": sha,
                    "source": store.put(data, "pdf" if format_ == "pdf" else "bin"),
                    "format": format_, "mime_type": mime, "format_evidence": evidence,
                    "aliases": [], "source_entries": [], "status": "pending" if format_ == "pdf" else "unsupported_format"}
            documents[doc_id]["aliases"].append({**row, "transport_sha256": digest(raw), "compression": "gzip" if compressed else "none"})
            documents[doc_id]["source_entries"].append(row["source_entry_id"])
            entries.append({**entry, "status": "ingested", "document_id": doc_id})
        except Exception as exc:
            entries.append({**entry, "status": "source_failed", "document_id": None,
                            "error": f"{type(exc).__name__}: {exc}"})
    return sorted(documents.values(), key=lambda d: d["document_id"]), entries
