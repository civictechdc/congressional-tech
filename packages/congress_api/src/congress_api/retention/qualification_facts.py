"""Verified body qualification facts and HTTP validator gating for capture and URL state.

Keep byte-hashed parsers and ``corpus_recovery.qualification`` untouched: this
module verifies serialized ``QualificationRecord`` digests, binds observed HTTP
validators (``ETag``, ``Last-Modified``, ``Content-Length``) to captured URLs,
and provides native model inputs and conditional-refetch rules from one owner.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import gzip
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from congress_shared.custody import canonical_json_bytes

from congress_api.retention.provenance import json_input

HEX64 = re.compile(r"^[0-9a-f]{64}$")
BODY_KEY_SHA = re.compile(r"^bodies/sha256/[0-9a-f]{2}/([0-9a-f]{64})(?:\.[a-z0-9]+)?$")
MODEL_QUALIFICATION_FIELDS = {
    "body_sha256": "Utf8",
    "body_bytes": "Int64",
    "status": "Utf8",
    "qualified": "Boolean",
    "media_type": "Utf8",
    "reason": "Utf8",
    "retryable": "Boolean",
    "qualification_sha256": "Utf8",
}


def extract_sha256_hex(value: Any) -> str | None:
    """Normalize a raw bytes, hex digest, or body key to lowercase 64-hex SHA-256."""
    if isinstance(value, (bytes, bytearray)) and len(value) == 32:
        return bytes(value).hex()
    if isinstance(value, str):
        lowered = value.strip().lower()
        if HEX64.fullmatch(lowered):
            return lowered
        match = BODY_KEY_SHA.fullmatch(lowered)
        if match:
            return match.group(1)
    return None


def expects_pdf_response(url: str | None, headers: Mapping[str, str] | None = None) -> bool:
    """Whether the target URL path/wrapper or response Content-Type declares a PDF document."""
    if isinstance(url, str) and url:
        try:
            if urlsplit(url).path.lower().endswith(".pdf"):
                return True
        except ValueError:
            pass
        if re.search(r"(?i)\.pdf(?:$|[&#?])", url):
            return True
    if isinstance(headers, Mapping):
        for key, value in headers.items():
            if isinstance(key, str) and key.lower() == "content-type" and isinstance(value, str):
                if "application/pdf" in value.lower():
                    return True
    return False


def _header_value(headers: Mapping[str, Any] | None, target: str) -> str | None:
    if not isinstance(headers, Mapping):
        return None
    wanted = target.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == wanted and isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else None
    return None


def extract_validators(headers: Mapping[str, Any] | None) -> dict[str, str | None]:
    """Extract normalized ETag, Last-Modified, and declared Content-Length validators."""
    etag = _header_value(headers, "etag")
    last_modified = _header_value(headers, "last-modified")
    raw_length = _header_value(headers, "content-length")
    content_length = None
    if raw_length is not None and raw_length.isascii() and raw_length.isdigit():
        content_length = str(int(raw_length))
    return {
        "etag": etag,
        "last_modified": last_modified,
        "content_length": content_length,
    }


def conditional_request_headers(
    prior_validators: Mapping[str, Any] | None,
    existing_headers: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Attach If-None-Match / If-Modified-Since when rechecking an unqualified URL."""
    merged = dict(existing_headers or {})
    if not isinstance(prior_validators, Mapping) or prior_validators.get("qualified") is not False:
        return merged
    lowered = {k.lower() for k in merged if isinstance(k, str)}
    etag = prior_validators.get("etag")
    if isinstance(etag, str) and etag.strip() and "if-none-match" not in lowered:
        merged["If-None-Match"] = etag.strip()
    last_modified = prior_validators.get("last_modified")
    if isinstance(last_modified, str) and last_modified.strip() and "if-modified-since" not in lowered:
        merged["If-Modified-Since"] = last_modified.strip()
    return merged


def validators_unchanged(
    prior_validators: Mapping[str, Any] | None,
    response_headers: Mapping[str, Any] | None,
) -> bool:
    """Whether an HTTP-200 response carries the exact same validators as a failed body.

    Returns True only when ``prior_validators`` marks an unqualified body
    (``qualified is False``) and none of ``ETag``, ``Last-Modified``, or
    ``Content-Length`` changed. Healthy URLs are never suppressed here.
    """
    if not isinstance(prior_validators, Mapping) or prior_validators.get("qualified") is not False:
        return False
    current = extract_validators(response_headers)
    prior_etag = prior_validators.get("etag")
    prior_lm = prior_validators.get("last_modified")
    prior_cl = prior_validators.get("content_length")
    if isinstance(prior_cl, int) and not isinstance(prior_cl, bool) and prior_cl >= 0:
        prior_cl = str(prior_cl)
    elif isinstance(prior_cl, str) and prior_cl.strip().isdigit():
        prior_cl = str(int(prior_cl.strip()))
    else:
        prior_cl = None
    prior_tuple = (
        prior_etag.strip() if isinstance(prior_etag, str) and prior_etag.strip() else None,
        prior_lm.strip() if isinstance(prior_lm, str) and prior_lm.strip() else None,
        prior_cl,
    )
    if prior_tuple == (None, None, None):
        return False
    curr_tuple = (current["etag"], current["last_modified"], current["content_length"])
    return curr_tuple == prior_tuple


def _verify_raw_qualification_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Verify QualificationRecord canonical checksum and structural invariants."""
    if not isinstance(record, Mapping):
        raise ValueError("Qualification record must be an object")
    body = dict(record)
    checksum = body.pop("qualification_sha256", None)
    if not isinstance(checksum, str) or not HEX64.fullmatch(checksum):
        raise ValueError("Qualification record requires a lowercase SHA-256 digest")
    computed = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    if computed != checksum:
        raise ValueError("Qualification record integrity mismatch")
    sha = body.get("body_sha256")
    size = body.get("body_bytes")
    status = body.get("status")
    media_type = body.get("media_type")
    reason = body.get("reason")
    retryable = body.get("retryable", False)
    if (
        not isinstance(sha, str)
        or not HEX64.fullmatch(sha)
        or type(size) is not int
        or size < 0
        or status not in ("qualified", "unresolved")
        or media_type not in (None, "application/pdf", "text/html")
        or not isinstance(reason, str)
        or not reason
        or type(retryable) is not bool
        or not isinstance(body.get("validator"), Mapping)
        or not isinstance(body.get("config"), Mapping)
    ):
        raise ValueError("Invalid qualification record fields")
    if status == "qualified" and retryable:
        raise ValueError("Qualified result cannot be retryable")
    return dict(body, qualification_sha256=checksum)


def verify_qualification_fact(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Verify either a raw QualificationRecord or a persisted qualification fact."""
    if not isinstance(entry, Mapping):
        raise ValueError("Qualification fact must be an object")
    if "validator" in entry and "config" in entry:
        verified = _verify_raw_qualification_record(entry)
        return {
            "body_sha256": verified["body_sha256"],
            "body_bytes": verified["body_bytes"],
            "status": verified["status"],
            "qualified": verified["status"] == "qualified",
            "media_type": verified["media_type"],
            "reason": verified["reason"],
            "retryable": bool(verified.get("retryable", False)),
            "qualification_sha256": verified["qualification_sha256"],
            "qualification_record": verified,
        }
    embedded = entry.get("qualification_record")
    if embedded is not None:
        verified = _verify_raw_qualification_record(embedded)
        expected_fields = {
            "body_sha256": verified["body_sha256"],
            "body_bytes": verified["body_bytes"],
            "status": verified["status"],
            "media_type": verified["media_type"],
            "qualification_sha256": verified["qualification_sha256"],
        }
        for key, wanted in expected_fields.items():
            if key in entry and entry[key] != wanted:
                raise ValueError(f"Qualification fact {key} disagrees with verified record")
        base = {
            "body_sha256": verified["body_sha256"],
            "body_bytes": verified["body_bytes"],
            "status": verified["status"],
            "qualified": verified["status"] == "qualified",
            "media_type": verified["media_type"],
            "reason": str(entry.get("reason") or verified["reason"]),
            "retryable": bool(verified.get("retryable", False)),
            "qualification_sha256": verified["qualification_sha256"],
            "qualification_record": verified,
        }
    else:
        sha = entry.get("body_sha256")
        q_sha = entry.get("qualification_sha256")
        size = entry.get("body_bytes")
        status = entry.get("status")
        qualified = entry.get("qualified")
        media_type = entry.get("media_type")
        reason = entry.get("reason")
        retryable = entry.get("retryable", False)
        if (
            not isinstance(sha, str)
            or not HEX64.fullmatch(sha)
            or not isinstance(q_sha, str)
            or not HEX64.fullmatch(q_sha)
            or type(size) is not int
            or size < 0
            or status not in ("qualified", "unresolved")
            or (qualified is not None and (type(qualified) is not bool or qualified != (status == "qualified")))
            or media_type not in (None, "application/pdf", "text/html")
            or not isinstance(reason, str)
            or not reason
            or type(retryable) is not bool
        ):
            raise ValueError("Invalid qualification fact fields")
        base = {
            "body_sha256": sha,
            "body_bytes": size,
            "status": status,
            "qualified": status == "qualified",
            "media_type": media_type,
            "reason": reason,
            "retryable": retryable,
            "qualification_sha256": q_sha,
        }
    requested_url = entry.get("requested_url")
    final_url = entry.get("url")
    if requested_url is not None and not isinstance(requested_url, str):
        raise ValueError("Qualification fact requested_url must be a string")
    if final_url is not None and not isinstance(final_url, str):
        raise ValueError("Qualification fact url must be a string")
    validators = extract_validators({
        "etag": entry.get("etag"),
        "last-modified": entry.get("last_modified"),
        "content-length": str(entry["content_length"]) if type(entry.get("content_length")) is int else entry.get("content_length"),
    })
    url_qualified = entry.get("url_qualified")
    if url_qualified is None:
        pdf_expected = expects_pdf_response(requested_url or final_url)
        url_qualified = bool(base["qualified"] and (not pdf_expected or base["media_type"] == "application/pdf"))
    elif type(url_qualified) is not bool:
        raise ValueError("Qualification fact url_qualified must be a boolean")
    if requested_url or final_url:
        base.update(
            requested_url=requested_url,
            url=final_url,
            receipt_key=entry.get("receipt_key") if isinstance(entry.get("receipt_key"), str) else None,
            retrieved_at=entry.get("retrieved_at") if isinstance(entry.get("retrieved_at"), str) else None,
            http_status=entry.get("http_status") if type(entry.get("http_status")) is int else None,
            url_qualified=url_qualified,
            **validators,
        )
    return base


def build_qualification_fact(
    record: Mapping[str, Any],
    *,
    requested_url: str | None = None,
    url: str | None = None,
    receipt_key: str | None = None,
    retrieved_at: str | None = None,
    http_status: int | None = None,
    headers: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind a verified QualificationRecord to a capture's URL and HTTP validators."""
    verified = _verify_raw_qualification_record(record)
    validators = extract_validators(headers)
    pdf_expected = expects_pdf_response(requested_url, headers) or expects_pdf_response(url, headers)
    body_qualified = verified["status"] == "qualified"
    format_mismatch = pdf_expected and verified["media_type"] != "application/pdf"
    url_qualified = bool(body_qualified and not format_mismatch)
    reason = "candidate_format_mismatch" if (body_qualified and format_mismatch) else verified["reason"]
    return {
        "requested_url": requested_url,
        "url": url,
        "receipt_key": receipt_key,
        "retrieved_at": retrieved_at,
        "http_status": http_status,
        "body_sha256": verified["body_sha256"],
        "body_bytes": verified["body_bytes"],
        "status": verified["status"],
        "qualified": body_qualified,
        "url_qualified": url_qualified,
        "media_type": verified["media_type"],
        "reason": reason,
        "retryable": bool(verified.get("retryable", False)),
        "qualification_sha256": verified["qualification_sha256"],
        **validators,
        "qualification_record": verified,
    }


def _iter_raw_entries(source: Any) -> Iterable[Mapping[str, Any]]:
    if source is None:
        return
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            return
        if path.is_dir():
            # Either a qualification-cache directory or a capture work root
            ledger = path / "qualifications.jsonl"
            if ledger.is_file():
                yield from _iter_raw_entries(ledger)
            cache = path / "qualification-cache" if (path / "qualification-cache").is_dir() else path
            for item in sorted(cache.glob("*.json")):
                if item.is_file():
                    yield json.loads(item.read_text(encoding="utf-8"))
            return
        name = path.name.lower()
        if name.endswith(".parquet"):
            import pyarrow.parquet as pq
            with pq.ParquetFile(path) as pf:
                for batch in pf.iter_batches(batch_size=1024):
                    yield from batch.to_pylist()
            return
        opener = (lambda p: gzip.open(p, "rt", encoding="utf-8")) if name.endswith(".gz") else (lambda p: p.open(encoding="utf-8"))
        with opener(path) as stream:
            if name.endswith((".jsonl", ".jsonl.gz")):
                for line in stream:
                    line = line.strip()
                    if line:
                        yield json.loads(line)
            else:
                loaded = json.load(stream)
                if isinstance(loaded, list):
                    for item in loaded:
                        yield item
                elif isinstance(loaded, Mapping):
                    if "body_sha256" in loaded:
                        yield loaded
                    else:
                        for item in loaded.values():
                            if isinstance(item, Mapping):
                                yield item
        return
    if isinstance(source, Mapping):
        if "body_sha256" in source:
            yield source
        else:
            for item in source.values():
                yield from _iter_raw_entries(item)
        return
    if isinstance(source, Iterable):
        for item in source:
            yield from _iter_raw_entries(item)
        return
    raise TypeError(f"Unsupported qualifications source: {type(source).__name__}")


def _url_order_key(fact: Mapping[str, Any]) -> tuple[str, str]:
    return (str(fact.get("retrieved_at") or ""), str(fact.get("receipt_key") or ""))


def load_qualification_facts(source: Any) -> dict[str, dict[str, dict[str, Any]]]:
    """Load verified body and per-URL validator facts from cache dirs, JSONL, Parquet, or dicts."""
    by_sha256: dict[str, dict[str, Any]] = {}
    by_url: dict[str, dict[str, Any]] = {}
    for raw in _iter_raw_entries(source):
        fact = verify_qualification_fact(raw)
        sha = fact["body_sha256"]
        existing = by_sha256.get(sha)
        if existing is not None and existing["qualification_sha256"] == fact["qualification_sha256"]:
            if existing["qualified"] != fact["qualified"]:
                raise ValueError(f"Conflicting qualification status for {sha}")
        if existing is None or not fact.get("retryable", False):
            sha_entry = {
                "body_sha256": sha,
                "body_bytes": fact["body_bytes"],
                "status": fact["status"],
                "qualified": fact["qualified"],
                "media_type": fact["media_type"],
                "reason": fact["reason"] if fact["reason"] != "candidate_format_mismatch" or fact.get("qualification_record") is None else fact["qualification_record"]["reason"],
                "retryable": fact["retryable"],
                "qualification_sha256": fact["qualification_sha256"],
            }
            if fact.get("qualification_record") is not None:
                sha_entry["qualification_record"] = fact["qualification_record"]
            by_sha256[sha] = sha_entry
        for key in ("requested_url", "url"):
            u = fact.get(key)
            if isinstance(u, str) and u:
                url_entry = {
                    "url": u,
                    "body_sha256": sha,
                    "body_bytes": fact["body_bytes"],
                    "qualified": bool(fact.get("url_qualified", fact["qualified"])),
                    "reason": fact["reason"],
                    "retryable": fact["retryable"],
                    "qualification_sha256": fact["qualification_sha256"],
                    "etag": fact.get("etag"),
                    "last_modified": fact.get("last_modified"),
                    "content_length": fact.get("content_length"),
                    "retrieved_at": fact.get("retrieved_at"),
                    "receipt_key": fact.get("receipt_key"),
                    "http_status": fact.get("http_status"),
                }
                prev = by_url.get(u)
                if prev is None or _url_order_key(url_entry) >= _url_order_key(prev):
                    by_url[u] = url_entry
    return {"by_sha256": by_sha256, "by_url": by_url}


def scan_local_store_validators(
    store_root: str | Path,
    *,
    by_sha256: Mapping[str, Mapping[str, Any]],
    unqualified_urls: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Pair local receipts' HTTP validators with verified body qualifications.

    Used when a caller supplies a ``qualification-cache`` directory or a release
    ``url_state.parquet`` with ``capture_reason='body_not_qualified'`` alongside
    a local ``BodyStore`` without a pre-joined ``qualifications.jsonl`` ledger.
    """
    root = Path(store_root) / "receipts"
    if not root.is_dir() or (not by_sha256 and not unqualified_urls):
        return {}
    by_url: dict[str, dict[str, Any]] = {}
    for receipt_path in sorted(root.rglob("*.jsonl.gz")):
        if not receipt_path.is_file():
            continue
        rel_key = receipt_path.relative_to(Path(store_root)).as_posix()
        with gzip.open(receipt_path, "rt", encoding="utf-8") as stream:
            for line_str in stream:
                line_str = line_str.strip()
                if not line_str:
                    continue
                line = json.loads(line_str)
                if not isinstance(line, Mapping) or line.get("mode") != "fetch":
                    continue
                req_url = line.get("requested_url")
                fin_url = line.get("url")
                status = line.get("http_status")
                retrieved_at = line.get("retrieved_at")
                headers = line.get("response_headers") if isinstance(line.get("response_headers"), Mapping) else {}
                validators = extract_validators(headers)
                if status == 304 or line.get("error_type") == "validator_unchanged":
                    for u in (req_url, fin_url):
                        if isinstance(u, str) and u in by_url:
                            prev = by_url[u]
                            if (str(retrieved_at or ""), rel_key) >= _url_order_key(prev):
                                by_url[u] = {
                                    **prev,
                                    "etag": validators["etag"] or prev.get("etag"),
                                    "last_modified": validators["last_modified"] or prev.get("last_modified"),
                                    "content_length": validators["content_length"] or prev.get("content_length"),
                                    "retrieved_at": retrieved_at,
                                    "receipt_key": rel_key,
                                    "http_status": status,
                                }
                    continue
                captures = line.get("captures") or []
                primary = next(
                    (c for c in captures if isinstance(c, Mapping) and c.get("attempt", 0) == 0 and c.get("member_path") is None),
                    None,
                )
                if primary is None:
                    continue
                sha = extract_sha256_hex(primary.get("sha256"))
                if sha is None:
                    continue
                body_q = by_sha256.get(sha)
                matched_unqualified_url = bool(
                    unqualified_urls and any(isinstance(u, str) and u in unqualified_urls for u in (req_url, fin_url))
                )
                if body_q is None and not matched_unqualified_url:
                    continue
                if body_q is not None:
                    pdf_expected = expects_pdf_response(req_url, headers) or expects_pdf_response(fin_url, headers)
                    url_qual = bool(
                        body_q["qualified"] and (not pdf_expected or body_q.get("media_type") == "application/pdf")
                    )
                    reason = body_q["reason"]
                    q_sha = body_q["qualification_sha256"]
                    retryable = bool(body_q.get("retryable", False))
                else:
                    url_qual = False
                    reason = "body_not_qualified"
                    q_sha = None
                    retryable = False
                for u in (req_url, fin_url):
                    if not isinstance(u, str) or not u:
                        continue
                    cand = {
                        "url": u,
                        "body_sha256": sha,
                        "body_bytes": primary.get("bytes"),
                        "qualified": url_qual,
                        "reason": reason,
                        "retryable": retryable,
                        "qualification_sha256": q_sha,
                        **validators,
                        "retrieved_at": retrieved_at,
                        "receipt_key": rel_key,
                        "http_status": status,
                    }
                    prev = by_url.get(u)
                    if prev is None or _url_order_key(cand) >= _url_order_key(prev):
                        by_url[u] = cand
    return by_url


def model_qualification_input(source: Any, scratch: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the native JSONL input and materialized relation ``body_qualifications``."""
    scratch_path = Path(scratch)
    scratch_path.mkdir(parents=True, exist_ok=True)
    if isinstance(source, Mapping) and set(source.keys()) >= {"path", "sha256", "size"} and "body_sha256" not in source:
        loaded = load_qualification_facts(source["path"])
    else:
        loaded = load_qualification_facts(source)
    rows = [
        {k: row[k] for k in MODEL_QUALIFICATION_FIELDS}
        for _, row in sorted(loaded["by_sha256"].items())
        if not row.get("retryable", False)
    ]
    inp = json_input(scratch_path, "body_qualifications_input", rows, **MODEL_QUALIFICATION_FIELDS)
    step = {
        "name": "body_qualifications",
        "sql": """SELECT
            arrow_cast(decode(body_sha256,'hex'),'FixedSizeBinary(32)') AS body_sha,
            body_sha256, body_bytes, status, qualified, media_type, reason, retryable, qualification_sha256
            FROM body_qualifications_input""",
        "materialize": True,
    }
    return inp, step
