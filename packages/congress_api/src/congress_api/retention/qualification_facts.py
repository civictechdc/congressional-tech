"""Verified body qualification facts and HTTP validator gating for capture and URL state.

Keep byte-hashed parsers and ``corpus_recovery.qualification`` untouched: this
module re-verifies serialized ``QualificationRecord`` evidence through the
maintained verifier, binds observed HTTP validators (``ETag``,
``Last-Modified``, ``Content-Length``) to the resource that answered, and
provides native model inputs and conditional-refetch rules from one owner.

Trust rules (ct-zohj review 7):
- every fact carries its full ``QualificationRecord``; a flat summary is refused;
- the record must pass the maintained verifier (checksum, identity, configuration
  and PDF page/render evidence); a record from another validator version or
  configuration is *stale* and is ignored, so the body is qualified again;
- whether a URL got its expected format is computed from verified fields only;
  a stored ``url_qualified`` may lower that answer, never raise it;
- a retryable checker failure never suppresses a refetch;
- equal ``Content-Length`` alone never suppresses a full response.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict
import gzip
import hashlib
import importlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from congress_shared.custody import canonical_json_bytes, verify_local_file

from congress_api.retention.provenance import _put_identical, json_input, timestamp_key
from congress_api.retention.receipt_privacy import cut_paths

HEX64 = re.compile(r"^[0-9a-f]{64}$")
BODY_KEY_SHA = re.compile(r"^bodies/sha256/[0-9a-f]{2}/([0-9a-f]{64})(?:\.[a-z0-9]+)?$")
PDF_SPELLING = re.compile(r"(?i)\.pdf(?:$|[&#?])")
QUALIFICATIONS_PREFIX = "provenance/qualifications/"
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


class StaleQualification(ValueError):
    """A verified-format record from another validator version or configuration."""


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


def expects_pdf_response(url: str | None, headers: Mapping[str, Any] | None = None) -> bool:
    """Whether the URL path/wrapper or response Content-Type declares a PDF document.

    ``archive_url_state.py`` applies the same rule in SQL to the requested URL,
    the final URL and the captured media type.
    """
    if isinstance(url, str) and url:
        try:
            if urlsplit(url).path.lower().endswith(".pdf"):
                return True
        except ValueError:
            pass
        if PDF_SPELLING.search(url):
            return True
    content_type = _header_value(headers, "content-type")
    return bool(content_type and "application/pdf" in content_type.lower())


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


def _suppresses(prior_validators: Mapping[str, Any] | None) -> bool:
    """Only a definitive (non-retryable) failed qualification may gate a refetch."""
    return (
        isinstance(prior_validators, Mapping)
        and prior_validators.get("qualified") is False
        and not prior_validators.get("retryable", False)
    )


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def conditional_request_headers(
    prior_validators: Mapping[str, Any] | None,
    existing_headers: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Attach If-None-Match / If-Modified-Since when rechecking a definitively unqualified URL."""
    merged = dict(existing_headers or {})
    if not _suppresses(prior_validators):
        return merged
    lowered = {k.lower() for k in merged if isinstance(k, str)}
    etag = _text(prior_validators.get("etag"))
    if etag and "if-none-match" not in lowered:
        merged["If-None-Match"] = etag
    last_modified = _text(prior_validators.get("last_modified"))
    if last_modified and "if-modified-since" not in lowered:
        merged["If-Modified-Since"] = last_modified
    return merged


def validators_unchanged(
    prior_validators: Mapping[str, Any] | None,
    response_headers: Mapping[str, Any] | None,
) -> bool:
    """Whether a full HTTP-200 response carries exactly the validators of a failed body.

    Requires a definitive failed qualification and at least one of ``ETag`` or
    ``Last-Modified``: an equal declared length alone cannot show the publisher
    kept the same file. Healthy and retryable URLs are never suppressed.
    """
    if not _suppresses(prior_validators):
        return False
    prior_etag = _text(prior_validators.get("etag"))
    prior_lm = _text(prior_validators.get("last_modified"))
    if prior_etag is None and prior_lm is None:
        return False
    prior_cl = prior_validators.get("content_length")
    if isinstance(prior_cl, int) and not isinstance(prior_cl, bool) and prior_cl >= 0:
        prior_cl = str(prior_cl)
    elif isinstance(prior_cl, str) and prior_cl.strip().isdigit():
        prior_cl = str(int(prior_cl.strip()))
    else:
        prior_cl = None
    current = extract_validators(response_headers)
    return (current["etag"], current["last_modified"], current["content_length"]) == (prior_etag, prior_lm, prior_cl)


def _maintained():
    # A string import keeps corpus_recovery out of congress_api's static dependency
    # and out of the model's import closure; the verifier itself is unchanged.
    return importlib.import_module("corpus_recovery.qualification")


def _verify_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Checksum, then the maintained verifier under the current version and configuration."""
    if not isinstance(record, Mapping):
        raise ValueError("Qualification record must be an object")
    body = dict(record)
    checksum = body.pop("qualification_sha256", None)
    if not isinstance(checksum, str) or not HEX64.fullmatch(checksum):
        raise ValueError("Qualification record requires a lowercase SHA-256 digest")
    if hashlib.sha256(canonical_json_bytes(body)).hexdigest() != checksum:
        raise ValueError("Qualification record integrity mismatch")
    module = _maintained()
    validator = body.get("validator")
    if not isinstance(validator, Mapping) or not isinstance(body.get("config"), Mapping):
        raise ValueError("Invalid qualification record fields")
    if validator.get("version") != module.VERSION or dict(body["config"]) != asdict(module.QualificationConfig()):
        raise StaleQualification("Qualification record predates the maintained validator or configuration")
    sha, size = body.get("body_sha256"), body.get("body_bytes")
    if not isinstance(sha, str) or not HEX64.fullmatch(sha) or type(size) is not int or size < 0:
        raise ValueError("Invalid qualification record fields")
    module.verify_qualification_record(
        dict(record), body_sha256=sha, body_bytes=size, config=module.QualificationConfig()
    )
    return dict(body, qualification_sha256=checksum, retryable=bool(body.get("retryable", False)))


def _url_qualified(record: Mapping[str, Any], *, requested_url, url, content_type) -> bool:
    headers = {"content-type": content_type} if isinstance(content_type, str) else None
    pdf_expected = expects_pdf_response(requested_url, headers) or expects_pdf_response(url, headers)
    return bool(record["status"] == "qualified" and not (pdf_expected and record["media_type"] != "application/pdf"))


def verify_qualification_fact(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Verify a raw QualificationRecord or a persisted URL-bound qualification fact."""
    if not isinstance(entry, Mapping):
        raise ValueError("Qualification fact must be an object")
    raw = "validator" in entry and "config" in entry
    record_source = entry if raw else entry.get("qualification_record")
    if record_source is None:
        raise ValueError("Qualification fact requires its full qualification record")
    record = _verify_record(record_source)
    if not raw:
        for key in ("body_sha256", "body_bytes", "status", "media_type", "qualification_sha256"):
            if key in entry and entry[key] != record[key]:
                raise ValueError(f"Qualification fact {key} disagrees with verified record")
    base = {
        "body_sha256": record["body_sha256"],
        "body_bytes": record["body_bytes"],
        "status": record["status"],
        "qualified": record["status"] == "qualified",
        "media_type": record["media_type"],
        "reason": record["reason"],
        "retryable": record["retryable"],
        "qualification_sha256": record["qualification_sha256"],
        "qualification_record": record,
    }
    if raw:
        return base
    requested_url, final_url = entry.get("requested_url"), entry.get("url")
    content_type = entry.get("content_type")
    for name, value in (("requested_url", requested_url), ("url", final_url), ("content_type", content_type)):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"Qualification fact {name} must be a string")
    url_qualified = _url_qualified(record, requested_url=requested_url, url=final_url, content_type=content_type)
    if entry.get("url_qualified") is False:  # may lower, never raise
        url_qualified = False
    validators = extract_validators({
        "etag": entry.get("etag"),
        "last-modified": entry.get("last_modified"),
        "content-length": str(entry["content_length"]) if type(entry.get("content_length")) is int else entry.get("content_length"),
    })
    base.update(
        requested_url=requested_url,
        url=final_url,
        content_type=content_type,
        receipt_key=entry.get("receipt_key") if isinstance(entry.get("receipt_key"), str) else None,
        retrieved_at=entry.get("retrieved_at") if isinstance(entry.get("retrieved_at"), str) else None,
        http_status=entry.get("http_status") if type(entry.get("http_status")) is int else None,
        url_qualified=url_qualified,
        reason="candidate_format_mismatch" if base["qualified"] and not url_qualified else record["reason"],
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
    """Bind a verified QualificationRecord to a capture's URLs, media type and HTTP validators."""
    verified = _verify_record(record)
    content_type = _header_value(headers, "content-type")
    url_qualified = _url_qualified(verified, requested_url=requested_url, url=url, content_type=content_type)
    body_qualified = verified["status"] == "qualified"
    return {
        "requested_url": requested_url,
        "url": url,
        "content_type": content_type,
        "receipt_key": receipt_key,
        "retrieved_at": retrieved_at,
        "http_status": http_status,
        "body_sha256": verified["body_sha256"],
        "body_bytes": verified["body_bytes"],
        "status": verified["status"],
        "qualified": body_qualified,
        "url_qualified": url_qualified,
        "media_type": verified["media_type"],
        "reason": "candidate_format_mismatch" if body_qualified and not url_qualified else verified["reason"],
        "retryable": verified["retryable"],
        "qualification_sha256": verified["qualification_sha256"],
        **extract_validators(headers),
        "qualification_record": verified,
    }


def responding_url(fact: Mapping[str, Any]) -> str | None:
    """Validators belong to the resource that answered, not every redirect hop."""
    for key in ("url", "requested_url"):
        value = fact.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def url_validator_entry(fact: Mapping[str, Any]) -> dict[str, Any]:
    """The per-URL gate a verified fact implies for its responding resource."""
    return {
        "url": responding_url(fact),
        "body_sha256": fact["body_sha256"],
        "body_bytes": fact["body_bytes"],
        "qualified": bool(fact.get("url_qualified", fact["qualified"])),
        "reason": fact["reason"],
        "retryable": bool(fact.get("retryable", False)),
        "qualification_sha256": fact["qualification_sha256"],
        "etag": fact.get("etag"),
        "last_modified": fact.get("last_modified"),
        "content_length": fact.get("content_length"),
        "retrieved_at": fact.get("retrieved_at"),
        "receipt_key": fact.get("receipt_key"),
        "http_status": fact.get("http_status"),
    }


def refresh_url_entry(prior: Mapping[str, Any], *, retrieved_at, receipt_key, http_status) -> dict[str, Any]:
    """A body-less 304 / unchanged recheck keeps the earlier validators and verdict."""
    return {**prior, "retrieved_at": retrieved_at, "receipt_key": receipt_key, "http_status": http_status}


def _jsonl_entries(stream) -> Iterable[Mapping[str, Any]]:
    """Yield JSONL objects, tolerating only a torn final line from an interrupted append."""
    lines = stream.read().split("\n")
    for index, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            if index == len(lines) - 1:
                return
            raise


def _iter_raw_entries(source: Any) -> Iterable[Mapping[str, Any]]:
    if source is None:
        return
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            return
        if path.is_dir():
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
                yield from _jsonl_entries(stream)
            else:
                loaded = json.load(stream)
                if isinstance(loaded, list):
                    yield from loaded
                elif isinstance(loaded, Mapping):
                    if "body_sha256" in loaded:
                        yield loaded
                    else:
                        yield from (item for item in loaded.values() if isinstance(item, Mapping))
        return
    if isinstance(source, Mapping):
        if "body_sha256" in source:
            yield source
        elif isinstance(source.get("path"), (str, Path)):
            yield from _iter_raw_entries(source["path"])
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


def merge_fact(by_sha256: dict, by_url: dict, fact: Mapping[str, Any]) -> None:
    """Fold one verified fact into body and responding-URL indexes (newest URL fact wins)."""
    sha = fact["body_sha256"]
    existing = by_sha256.get(sha)
    if existing is None or (existing.get("retryable") and not fact.get("retryable")):
        by_sha256[sha] = {
            key: fact[key]
            for key in ("body_sha256", "body_bytes", "status", "qualified", "media_type", "retryable",
                        "qualification_sha256", "qualification_record")
        } | {"reason": fact["qualification_record"]["reason"]}
    target = responding_url(fact)
    if target is not None and ("requested_url" in fact or "url" in fact):
        entry = url_validator_entry(fact)
        prev = by_url.get(target)
        if prev is None or _url_order_key(entry) >= _url_order_key(prev):
            by_url[target] = entry


def load_qualification_facts(source: Any) -> dict[str, Any]:
    """Load verified body and responding-URL facts; stale records are counted and ignored."""
    by_sha256: dict[str, dict[str, Any]] = {}
    by_url: dict[str, dict[str, Any]] = {}
    retryable_by_key: dict[tuple[str, str | None, str | None], dict[str, Any]] = {}
    stale = 0
    for raw in _iter_raw_entries(source):
        try:
            fact = verify_qualification_fact(raw)
        except StaleQualification:
            stale += 1
            continue
        merge_fact(by_sha256, by_url, fact)
        if fact.get("retryable"):
            retryable_by_key[(fact["body_sha256"], responding_url(fact), fact.get("receipt_key"))] = fact
    retryable_facts = [
        fact
        for fact in retryable_by_key.values()
        if by_sha256.get(fact["body_sha256"], {}).get("retryable")
    ]
    return {"by_sha256": by_sha256, "by_url": by_url, "stale": stale, "retryable_facts": retryable_facts}


def _check_no_local_paths(value: Any) -> None:
    if isinstance(value, str) and cut_paths(value)[1]:
        raise ValueError("Local path in public qualification provenance")
    if isinstance(value, Mapping):
        for k, v in value.items():
            _check_no_local_paths(k)
            _check_no_local_paths(v)
    elif isinstance(value, list):
        for child in value:
            _check_no_local_paths(child)


def import_qualifications(
    store: Any,
    source: Any,
    *,
    decided_at: str,
) -> dict[str, Any] | None:
    """Persist verified receipt-bound qualification facts create-only under ``provenance/qualifications/``."""
    from tempfile import TemporaryDirectory

    facts: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for raw in _iter_raw_entries(source):
        try:
            fact = verify_qualification_fact(raw)
        except StaleQualification:
            continue
        _check_no_local_paths({k: v for k, v in fact.items() if k != "qualification_record"})
        dedup_key = (
            fact["body_sha256"],
            fact.get("requested_url"),
            fact.get("url"),
            fact.get("receipt_key"),
            fact["qualification_sha256"],
        )
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        facts.append(fact)
    if not facts:
        return None
    stamp = timestamp_key(decided_at)
    with TemporaryDirectory(prefix="raw-qualifications-") as temporary:
        frozen = Path(temporary) / "qualifications.jsonl"
        digest = hashlib.sha256()
        size = 0
        with frozen.open("xb") as out:
            for fact in facts:
                line = (json.dumps(fact, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
                out.write(line)
                digest.update(line)
                size += len(line)
        key = f"{QUALIFICATIONS_PREFIX}{stamp}-{digest.hexdigest()}.jsonl"
        _put_identical(store, key, frozen)
    return {"key": key, "records": len(facts), "sha256": digest.hexdigest(), "size": size}


def load_store_qualifications(store: Any, *, work: str | Path) -> dict[str, Any]:
    """Read and verify all ``provenance/qualifications/*.jsonl`` objects from a Local or R2 BodyStore."""
    from uuid import uuid4
    from congress_api.retention.provenance_inventory import ProvenanceInventory

    class _QualificationsInventory(ProvenanceInventory):
        prefix = QUALIFICATIONS_PREFIX

    work_dir = Path(work).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    with _QualificationsInventory(store, work=work_dir / uuid4().hex) as snapshot:
        keys = [
            row["key"]
            for row in snapshot.metadata()
            if row["key"].startswith(QUALIFICATIONS_PREFIX) and row["key"].endswith(".jsonl")
        ]
        rows = snapshot.qualify(keys) if keys else []
    loaded = load_qualification_facts(rows)
    loaded["files"] = rows
    return loaded


def _read_retained_body(store: Any, body_sha256: str, dest: Path) -> Path | None:
    """Materialize a retained raw body from BodyStore (Local or R2) into ``dest`` for qualification."""
    adapter = getattr(store, "adapter", None)
    if adapter is None or not hasattr(adapter, "head") or not hasattr(adapter, "get"):
        return None
    base_key = f"bodies/sha256/{body_sha256[:2]}/{body_sha256}"
    for suffix in ("", ".gz"):
        key = base_key + suffix
        if adapter.head(key) is None:
            continue
        response = adapter.get(key)
        body_stream = response["Body"]
        try:
            raw_bytes = body_stream.read()
        finally:
            body_stream.close()
        payload = gzip.decompress(raw_bytes) if suffix == ".gz" else raw_bytes
        dest.write_bytes(payload)
        return dest
    return None


def retry_retained_qualifications(
    store: Any,
    retryable_facts: Iterable[Mapping[str, Any]],
    *,
    qualify_fn: Any,
    cache_dir: str | Path,
    work: str | Path,
) -> list[dict[str, Any]]:
    """Retry prior transient (``retryable=True``) checker failures directly against retained store bytes."""
    from tempfile import TemporaryDirectory

    work_dir = Path(work)
    work_dir.mkdir(parents=True, exist_ok=True)
    cache_path = Path(cache_dir)
    retried: list[dict[str, Any]] = []
    with TemporaryDirectory(prefix="retry-qual-", dir=work_dir) as temp_dir:
        temp_root = Path(temp_dir)
        for index, prior in enumerate(retryable_facts):
            sha = extract_sha256_hex(prior.get("body_sha256"))
            if sha is None:
                continue
            target_file = _read_retained_body(store, sha, temp_root / f"{index}-{sha}.body")
            if target_file is None:
                continue
            expected_size = prior.get("body_bytes")
            verified = verify_local_file(
                target_file,
                expected_sha256=sha,
                expected_size=expected_size if type(expected_size) is int and expected_size >= 0 else target_file.stat().st_size,
            )
            q_record = qualify_fn(verified, cache_path)
            headers: dict[str, str] = {}
            if isinstance(prior.get("content_type"), str) and prior["content_type"]:
                headers["Content-Type"] = prior["content_type"]
            if isinstance(prior.get("etag"), str) and prior["etag"]:
                headers["ETag"] = prior["etag"]
            if isinstance(prior.get("last_modified"), str) and prior["last_modified"]:
                headers["Last-Modified"] = prior["last_modified"]
            if isinstance(prior.get("content_length"), str) and prior["content_length"]:
                headers["Content-Length"] = prior["content_length"]
            retried.append(
                build_qualification_fact(
                    q_record,
                    requested_url=prior.get("requested_url"),
                    url=prior.get("url"),
                    receipt_key=prior.get("receipt_key"),
                    retrieved_at=prior.get("retrieved_at"),
                    http_status=prior.get("http_status"),
                    headers=headers,
                )
            )
    return retried


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
    Validators bind to the receipt's final URL (the resource that answered).
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
                req_url, fin_url = line.get("requested_url"), line.get("url")
                target = fin_url if isinstance(fin_url, str) and fin_url else req_url
                if not isinstance(target, str) or not target:
                    continue
                status, retrieved_at = line.get("http_status"), line.get("retrieved_at")
                headers = line.get("response_headers") if isinstance(line.get("response_headers"), Mapping) else {}
                if status == 304 or line.get("error_type") == "validator_unchanged":
                    prev = by_url.get(target)
                    if prev is not None and (str(retrieved_at or ""), rel_key) >= _url_order_key(prev):
                        by_url[target] = refresh_url_entry(prev, retrieved_at=retrieved_at, receipt_key=rel_key, http_status=status)
                    continue
                primary = next(
                    (c for c in line.get("captures") or []
                     if isinstance(c, Mapping) and c.get("attempt", 0) == 0 and c.get("member_path") is None),
                    None,
                )
                sha = extract_sha256_hex(primary.get("sha256")) if primary is not None else None
                if sha is None:
                    continue
                body_q = by_sha256.get(sha)
                matched = bool(unqualified_urls and (req_url in unqualified_urls or fin_url in unqualified_urls))
                if body_q is None and not matched:
                    continue
                if body_q is not None:
                    content_type = _header_value(headers, "content-type")
                    url_qual = _url_qualified(body_q, requested_url=req_url, url=fin_url, content_type=content_type)
                    reason, q_sha, retryable = body_q["reason"], body_q["qualification_sha256"], bool(body_q.get("retryable"))
                else:
                    url_qual, reason, q_sha, retryable = False, "body_not_qualified", None, False
                cand = {
                    "url": target,
                    "body_sha256": sha,
                    "body_bytes": primary.get("bytes"),
                    "qualified": url_qual,
                    "reason": reason,
                    "retryable": retryable,
                    "qualification_sha256": q_sha,
                    **extract_validators(headers),
                    "retrieved_at": retrieved_at,
                    "receipt_key": rel_key,
                    "http_status": status,
                }
                prev = by_url.get(target)
                if prev is None or _url_order_key(cand) >= _url_order_key(prev):
                    by_url[target] = cand
    return by_url


def model_qualification_input(source: Any, scratch: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the native JSONL input and materialized relation ``body_qualifications``.

    Retryable checker failures are omitted: they are not a fact about the body.
    """
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
