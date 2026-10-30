"""Retain a downloaded GovInfo package without broadening recovery mappings."""
from collections import defaultdict
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import pyarrow as pa

from congress_shared.dates import parse_utc_timestamp

from congress_api.models.content import CapturedBody
from congress_api.retention.archive_members import (
    ArchiveReadError, ZipLimits, is_office_zip, iter_archive_members,
)
from congress_api.retention.body_keys import body_key_digest

CAPTURE_SCHEMA = pa.schema([
    ("family", pa.string()),
    ("capture_date", pa.string()),
    ("source_file", pa.string()),
    ("source_line", pa.int64()),
    ("receipt_key", pa.string()),
    ("receipt_line", pa.int64()),
    ("reference_kind", pa.string()),
    ("pointer_json", pa.string()),
    ("context_url", pa.string()),
    ("sha256", pa.binary(32)),
    ("bytes", pa.int64()),
    ("is_stored", pa.bool_()),
    ("stored_sha256", pa.binary(32)),
    ("stored_bytes", pa.int64()),
    ("fidelity", pa.string()),
    ("media_type", pa.string()),
    ("retrieved_at", pa.timestamp("us", tz="UTC")),
    ("http_status", pa.int16()),
    ("resolution", pa.string()),
    ("original_path", pa.string()),
])


def format_sha256(val):
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        return bytes(val).hex() if len(val) != 64 else bytes(val).decode("ascii")
    return str(val).lower()


def format_timestamp(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return (val.replace(tzinfo=timezone.utc) if val.tzinfo is None else val.astimezone(timezone.utc)).isoformat()
    return str(val)


def derive_body_key(sha256_val, media_type=None):
    hex_str = format_sha256(sha256_val)
    return f"bodies/sha256/{hex_str[:2]}/{hex_str}.gz" if hex_str else None


def _parse_sha256(val):
    if not val:
        return None
    if isinstance(val, (bytes, bytearray)):
        return bytes(val) if len(val) == 32 else bytes.fromhex(bytes(val).decode("ascii"))
    return bytes.fromhex(val)


def _parse_timestamp(val):
    if not val:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=timezone.utc) if val.tzinfo is None else val.astimezone(timezone.utc)
    dt = datetime.fromisoformat(val.strip().replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def prepare_capture_table(rows):
    if isinstance(rows, pa.Table):
        return rows if rows.schema.equals(CAPTURE_SCHEMA, check_metadata=False) else prepare_capture_table(rows.to_pylist())
    normalized = []
    for d in rows:
        sha = _parse_sha256(d.get("sha256") or body_key_digest(d.get("body_key")))
        stored_sha = d.get("stored_sha256")
        is_stored = bool(d["is_stored"]) if d.get("is_stored") is not None else (bool(stored_sha) if stored_sha is not None else (False if sha is not None else None))
        normalized.append({
            **{name: d.get(name) for name in CAPTURE_SCHEMA.names},
            "sha256": sha,
            "is_stored": is_stored,
            "stored_sha256": _parse_sha256(stored_sha),
            "retrieved_at": _parse_timestamp(d.get("retrieved_at")),
            "http_status": int(d["http_status"]) if d.get("http_status") is not None else None,
        })
    return pa.Table.from_pylist(normalized, schema=CAPTURE_SCHEMA)


def prepare_capture(response, *, outcome, links, context=None, mode="fetch", scanned=True,
                    max_payload_bytes=None, archive_limits=None):
    bodies = {}

    def retain(data):
        digest = hashlib.sha256(data).hexdigest()
        key = derive_body_key(digest)
        bodies.setdefault(key, data)
        return key

    record = {**response, "outcome": outcome, "mode": mode, "links": list(links), "source_context": context or {}}
    captures = []
    content = dict(record["content"])
    raw_body = content["body"]
    data = raw_body.data
    content["body"] = None
    record["content"] = content
    body_key = retain(data)
    publisher = {
        "pointer": ["content", "body"],
        "body_key": body_key,
        "sha256": raw_body.sha256,
        "bytes": len(data),
        "string_encoding": raw_body.body_encoding,
        "fidelity": "exact-bytes",
        "media_type": raw_body.media_type,
        "context_url": record.get("url") or record["requested_url"],
        "retrieved_at": record.get("retrieved_at"),
        "http_status": record.get("http_status"),
    }
    captures.append(publisher)
    if not record.get("complete") or outcome != "saved":
        return record, captures, bodies, scanned
    limits = archive_limits or ZipLimits()
    media = (content.get("media_type") or "").lower()
    suffix = urlsplit(record.get("url") or record["requested_url"]).path.lower().rsplit(".", 1)[-1]
    office = (suffix in {"docx", "docm", "dotx", "dotm", "xlsx", "xlsm", "xltx", "xltm",
                         "pptx", "pptm", "potx", "potm", "ppsx", "ppsm", "odt", "ods", "odp"}
              or "officedocument" in media or "vnd.ms-" in media
              or "vnd.oasis.opendocument" in media or is_office_zip(data, limits=limits))
    if office or not data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"rtfd")):
        return record, captures, bodies, scanned
    record["archive_members"] = []
    try:
        for member in iter_archive_members(data, archive_path=publisher["body_key"], limits=limits):
            position = len(record["archive_members"])
            item = dict(original_name=member.original_name, entry_index=member.entry_index,
                        parent_archive_body_key=publisher["body_key"], status=member.status,
                        error_type=member.error_type, unsafe_name=member.unsafe_name,
                        nested_archive=member.nested_archive, declared_bytes=member.declared_bytes,
                        compressed_bytes=member.compressed_bytes)
            if member.data is not None:
                extension = member.original_name.lower().rsplit(".", 1)[-1]
                member_media = {"pdf": "application/pdf", "xml": "application/xml",
                                "html": "text/html", "htm": "text/html", "txt": "text/plain",
                                "csv": "text/csv", "json": "application/json",
                                "zip": "application/zip"}.get(extension, "application/octet-stream")
                m_raw = CapturedBody.from_bytes(member.data, member_media)
                m_content = m_raw.source_dict()
                m_content["body"] = None
                item["content"] = m_content
                m_key = retain(member.data)
                captures.append({
                    "pointer": ["archive_members", position, "content", "body"],
                    "body_key": m_key,
                    "sha256": m_raw.sha256,
                    "bytes": len(member.data),
                    "string_encoding": m_raw.body_encoding,
                    "fidelity": "exact-bytes",
                    "media_type": m_raw.media_type,
                    "context_url": publisher["context_url"],
                    "original_path": member.original_name,
                    "retrieved_at": publisher["retrieved_at"],
                    "http_status": publisher["http_status"],
                })
            record["archive_members"].append(item)
        record["archive_processing"] = {"status": "completed"}
    except ArchiveReadError as exc:
        record["archive_processing"] = {"status": exc.status, "error_type": type(exc).__name__}
    return record, captures, bodies, scanned


def _read_bounded(path, limit):
    with Path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f'GovInfo package input exceeds read limit: {path}')
    return raw


def prepare_packages(recoveries, input_hashes):
    """Expand each acquisition once; retain ZIP, every member and exact receipt.

    Existing retained-body recoveries have no local acquisition to expand. Their
    selected document remains sufficient; this operation never fetches a package.
    """
    groups = defaultdict(list)
    for row in recoveries:
        if row.get('package_id') and row.get('archive_member'):
            if not row.get('request_evidence'):
                raise ValueError('GovInfo package member lacks acquisition receipt')
            groups[Path(row['request_evidence']).resolve()].append(row)
    prepared = []
    for path, rows in groups.items():
        raw_receipt = _read_bounded(path, 1024**2)
        receipt_sha = hashlib.sha256(raw_receipt).hexdigest()
        input_hashes[str(path)] = receipt_sha
        receipt = json.loads(raw_receipt)
        package_id = receipt['package_id']
        url = f'https://www.govinfo.gov/content/pkg/{package_id}.zip'
        response = receipt['record']
        if (receipt.get('outcome') != 'saved' or response.get('complete') is not True
                or response.get('http_status') != 200
                or response.get('url') != url or response.get('requested_url') != url):
            raise ValueError('GovInfo package receipt is incomplete or identifies another source')
        at = parse_utc_timestamp(response['retrieved_at'])
        parent_path = Path(response['local_body_path']).resolve()
        raw = _read_bounded(parent_path, ZipLimits().max_archive_bytes)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != response['content']['sha256'] or digest != response['body_sha256']:
            raise ValueError('GovInfo package ZIP identity mismatch')
        members = {member['name']: member for member in receipt['members']}
        if len(members) != len(receipt['members']) or not members:
            raise ValueError('GovInfo package receipt has duplicate or missing members')
        for row in rows:
            member = members.get(row['archive_member'], {})
            if (row['package_id'] != package_id or member.get('status') != 'completed'
                    or row['recovered_url'] != 'https://www.govinfo.gov/content/pkg/' + row['archive_member']
                    or not row['archive_member'].startswith(package_id + '/')
                    or (row['sha256'], row['bytes']) != (member.get('sha256'), member.get('bytes'))):
                raise ValueError('Selected recovery differs from its GovInfo package member')
        response = dict(response,
            content=CapturedBody.from_bytes(raw, 'application/zip').source_dict(),
            publisher_requested=False,
            # A self-reference satisfies receipt assembly without transferring any
            # committee document's identity to its ZIP or to sibling members.
            source_associations=[dict(original_url=url, basis='retained_package')],
            recovery_package=dict(package_id=package_id, acquisition_receipt_sha256=receipt_sha,
                                  acquisition_receipt_path=str(path),
                                  # Preserve exact receipt bytes inside the import
                                  # receipt, without indexing them as a document.
                                  acquisition_receipt_base64=base64.b64encode(raw_receipt).decode('ascii')))
        record, captures, bodies, _ = prepare_capture(
            response, outcome='saved', links=[], mode='retained_import')
        expanded = record.get('archive_members', [])
        if (record.get('archive_processing', {}).get('status') != 'completed'
                or len(expanded) != len(members)
                or {m['original_name'] for m in expanded} != set(members)
                or any(m['status'] != 'completed' for m in expanded)):
            raise ValueError('GovInfo package extraction is incomplete')
        local = {}
        for capture in captures:
            pointer = capture['pointer']
            if pointer == ['content', 'body']:
                body_path = parent_path
            elif pointer[0] == 'archive_members':
                member = members[capture['original_path']]
                if (member.get('status') != 'completed'
                        or (member['sha256'], member['bytes']) != (capture['sha256'], capture['bytes'])):
                    raise ValueError('GovInfo package member differs from acquisition receipt')
                body_path = Path(member['path']).resolve()
            else:
                raise ValueError('Unexpected GovInfo package capture')
            with body_path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != capture['sha256'] or body_path.stat().st_size != capture['bytes']:
                raise ValueError(f'GovInfo package local body changed: {body_path}')
            local.setdefault(capture['body_key'], str(body_path))
        if set(local) != set(bodies):
            raise ValueError('GovInfo package body inventory is incomplete')
        prepared.append(dict(original_url=url, record=record, captures=captures,
                             local_bodies=local, preserve_download_state=True))
    return prepared
