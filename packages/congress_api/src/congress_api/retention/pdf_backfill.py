"""Streamed .gz-to-.pdf body copier and verification provenance writer (B13)."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from contextlib import closing
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Any
import zlib

import pyarrow as pa
import pyarrow.parquet as pq
from congress_shared.custody import copy_checked
from congress_shared.storage import single_put_md5

from congress_api.lake.readings import current_version
from congress_api.lake.tables import table_input
from congress_api.retention.body_store import BODY, BodyStore, LocalAdapter, R2Adapter
from congress_api.retention.pdf_tools import check_pdf
from congress_api.retention.provenance import (
    field,
    file_pin,
    json_input,
    parquet_output,
    parquet_records,
    run_job,
)
from congress_api.retention.sniff import BODY_LIMIT, PREFIX_BYTES

ROOT = Path(__file__).resolve().parents[5]
STREAM_CHUNK_BYTES = 1024 * 1024
SINGLE_PUT_LIMIT = 5 * 1024**3


class _HashedReader:
    def __init__(self, source):
        self.source = source
        self.md5 = hashlib.md5()
        self.sha = hashlib.sha256()
        self.size = 0

    def read(self, size: int = -1) -> bytes:
        data = self.source.read(min(size, STREAM_CHUNK_BYTES) if size >= 0 else STREAM_CHUNK_BYTES)
        self.md5.update(data)
        self.sha.update(data)
        self.size += len(data)
        return data


def _extract_digest(item: Any) -> str:
    if isinstance(item, Mapping):
        for name in ('sha256', 'body_sha', 'key', 'gz_key', 'body_key'):
            if item.get(name) is not None:
                return _extract_digest(item[name])
        raise ValueError('Candidate mapping requires sha256 or body key')
    if isinstance(item, (bytes, bytearray)):
        if len(item) == 32:
            return bytes(item).hex()
        raise ValueError('Binary candidate digest must be 32 bytes')
    if not isinstance(item, str):
        raise ValueError('Candidate must be a SHA-256 hex digest or body key')
    value = item.strip()
    if re.fullmatch('[0-9a-f]{64}', value):
        return value
    match = BODY.fullmatch(value)
    if match and match[1] == match[2][:2]:
        return match[2]
    raise ValueError(f'Invalid candidate SHA-256 or body key: {item!r}')


def _verified_pdf_copies(verification_files: Iterable[Mapping[str, Any]]) -> set[str]:
    copied: set[str] = set()
    latest: dict[str, tuple[str, bool]] = {}
    for item in verification_files or ():
        path = Path(item['path'] if isinstance(item, Mapping) else item)
        opener = gzip.open if path.suffix == '.gz' else Path.open
        with opener(path, 'rt', encoding='utf-8') as source:
            for line in source:
                if not line.strip():
                    continue
                row = json.loads(line)
                key = row.get('key')
                if (isinstance(key, str) and key.endswith('.pdf')
                        and row.get('sha256_verified') is True
                        and type(row.get('intact')) is bool):
                    digest = _extract_digest(key)
                    stamp = str(row.get('checked_at') or '')
                    prev = latest.get(digest)
                    if prev is None or stamp >= prev[0]:
                        latest[digest] = (stamp, True)
    copied.update(latest.keys())
    return copied


def _load_candidates(candidates: Any, *, verification_files: Iterable[Mapping[str, Any]] = ()) -> list[str]:
    if isinstance(candidates, (str, Path)):
        path = Path(candidates)
        if path.suffix == '.parquet':
            rows = list(parquet_records(path))
        elif path.suffix == '.jsonl' or path.name.endswith('.jsonl.gz'):
            opener = gzip.open if path.suffix == '.gz' else Path.open
            with opener(path, 'rt', encoding='utf-8') as source:
                rows = [json.loads(line) for line in source if line.strip()]
        else:
            payload = json.loads(path.read_text(encoding='utf-8'))
            rows = payload.get('candidates', payload) if isinstance(payload, Mapping) else payload
    elif isinstance(candidates, Iterable):
        rows = list(candidates)
    else:
        raise ValueError('Unsupported candidates input')
    already_copied = _verified_pdf_copies(verification_files)
    seen: dict[str, None] = {}
    for item in rows:
        digest = _extract_digest(item)
        if digest not in already_copied:
            seen.setdefault(digest, None)
    return list(seen.keys())


def select_pdf_candidates(
    *,
    captures: Any,
    readings: Any,
    engine: Any,
    work: Path,
    verification_files: Iterable[Mapping[str, Any]] = (),
    sniff_version: str | None = None,
    root: Path = ROOT,
) -> list[str]:
    """Select .gz-only bodies whose pinned sniff format is pdf and lack a verified .pdf copy."""
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    version = sniff_version or current_version('sniff')
    inputs = [
        table_input('captures', captures),
        table_input('readings', readings),
        json_input(work, 'parser_versions', [dict(parser='sniff', version=version)], parser='Utf8', version='Utf8'),
    ]
    verify_schema = dict(key='Utf8', size='Int64', intact='Boolean', sha256_verified='Boolean', checked_at='Utf8')
    v_files = [dict(key=item['key'], path=str(Path(item['path']).resolve())) for item in (verification_files or ())]
    if v_files:
        inputs.append(dict(
            name='verification_records',
            kind='json_lines',
            files=v_files,
            schema=dict(fields=[field(k, v) for k, v in verify_schema.items()], metadata={}),
        ))
    else:
        inputs.append(json_input(work, 'verification_records', [], **verify_schema))

    def sql_step(name: str, filename: str, materialize: bool = True) -> dict[str, Any]:
        return dict(name=name, sql=(Path(root) / 'model/sql' / filename).read_text(), materialize=materialize)

    capture_sha = 'c.sha256'
    if not isinstance(captures, dict) or captures.get('kind') == 'parquet':
        cap_path = Path(captures['path'] if isinstance(captures, dict) else captures)
        cap_schema = pq.read_schema(cap_path)
        if 'sha256' in cap_schema.names and pa.types.is_string(cap_schema.field('sha256').type):
            capture_sha = "decode(c.sha256, 'hex')"

    steps = [
        sql_step('pinned_readings', 'pinned-readings.sql'),
        dict(
            name='sniff_observations',
            sql=(
                "SELECT body_sha,format,intact,error_type,'read' AS intact_basis "
                "FROM pinned_readings WHERE parser='sniff' AND status='completed' "
                "UNION ALL "
                f"SELECT {capture_sha} AS body_sha,c.sniffed_format AS format,c.intact,cast(NULL AS VARCHAR) AS error_type,'capture' AS intact_basis "
                "FROM captures c JOIN parser_versions v ON v.parser='sniff' AND c.sniff_version=v.version "
                "WHERE c.sha256 IS NOT NULL AND c.sniffed_format IS NOT NULL"
            ),
            materialize=True,
        ),
        sql_step('sniff_conflicts', 'sniff-conflicts.sql'),
        sql_step('sniff_facts', 'sniff-facts.sql'),
        sql_step('copy_verifications', 'copy-verifications.sql'),
        dict(
            name='stored_gz',
            sql=(
                f"SELECT lower(encode({capture_sha}, 'hex')) AS body_sha "
                "FROM captures c WHERE c.sha256 IS NOT NULL "
                f"GROUP BY {capture_sha} "
                "HAVING bool_or(coalesce(c.stored_suffix, '.gz') = '.gz') "
                "AND NOT bool_or(coalesce(c.stored_suffix, '.gz') = '')"
            ),
            materialize=True,
        ),
        dict(
            name='pdf_candidates',
            sql=(
                "SELECT g.body_sha AS sha256 "
                "FROM stored_gz g "
                "JOIN sniff_facts s ON g.body_sha = lower(encode(s.body_sha, 'hex')) "
                "LEFT ANTI JOIN copy_verifications v ON g.body_sha = v.body_sha "
                "WHERE s.format = 'pdf'"
            ),
            materialize=True,
        ),
    ]
    out_path = work / 'candidates.parquet'
    reports = run_job(
        work / 'plan',
        engine,
        inputs=inputs,
        steps=steps,
        outputs=[parquet_output(work, 'candidates', 'SELECT sha256 FROM pdf_candidates', ['sha256'])],
        queries=[dict(name='conflicts', sql='SELECT count(*) AS n FROM sniff_conflicts')],
    )
    if reports['conflicts'][0]['n']:
        raise ValueError('Refusing PDF backfill candidate selection with conflicting sniff observations')
    return [row['sha256'] for row in parquet_records(out_path)]


def _check_pdf_intact(pdf_path: Path, pdf_size: int, tail: bytes) -> bool:
    if b'%%EOF' in tail:
        return True
    if pdf_size > BODY_LIMIT:
        return False
    return check_pdf(pdf_path.read_bytes())


def _is_missing_object_error(error: Exception) -> bool:
    if isinstance(error, FileNotFoundError):
        return True
    response = getattr(error, 'response', None) or {}
    code = (response.get('Error') or {}).get('Code')
    return code in {'404', 'NoSuchKey', 'NotFound'}


def apply_staged(work: Path, store: BodyStore) -> dict[str, Any]:
    """Publish staged verification provenance records after custody verification."""
    work = Path(work)
    report = json.loads((work / 'report.json').read_text(encoding='utf-8'))
    records = work / 'verification.jsonl'
    key = report.get('provenance_key')
    count = report.get('verification_records_count', 0)
    if count == 0:
        return dict(provenance=None, backfilled=len(report.get('backfilled', ())), records=0)
    if not isinstance(key, str) or not key.startswith('provenance/verification/'):
        raise ValueError('Invalid verification provenance key')
    with TemporaryDirectory(prefix='pdf-backfill-apply-') as temporary:
        frozen = Path(temporary) / 'verification.jsonl'
        pin = copy_checked(records, frozen)
        if pin.sha256 != report.get('records_sha256'):
            raise ValueError('Verification records changed after staging')
        store.put(key, frozen, 'application/x-ndjson')
    return dict(provenance=key, backfilled=len(report.get('backfilled', ())), records=count)


def backfill_uncompressed_pdfs(
    store: BodyStore,
    candidates: Any = None,
    *,
    captures: Any = None,
    readings: Any = None,
    verification_files: Iterable[Mapping[str, Any]] = (),
    engine: Any = None,
    work: Path | None = None,
    checked_at: str | None = None,
    dry_run: bool = False,
    stage_only: bool = False,
    sniff_version: str | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Stream-decompress .gz PDF bodies to .pdf through BodyStore and write verification provenance."""
    if type(dry_run) is not bool or type(stage_only) is not bool:
        raise ValueError('dry_run and stage_only must be explicit booleans')
    if not isinstance(store, BodyStore) or not isinstance(store.adapter, (LocalAdapter, R2Adapter)):
        raise ValueError('PDF backfill requires a BodyStore with LocalAdapter or R2Adapter')

    checked_at = checked_at or datetime.now(timezone.utc).isoformat()
    stamp = datetime.fromisoformat(checked_at.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Verification time needs a timezone')
    canonical_checked_at = stamp.astimezone(timezone.utc).isoformat()

    if work is not None:
        work = Path(work).resolve()
        work.mkdir(parents=True, exist_ok=False)

    if candidates is None:
        if captures is None or readings is None or engine is None:
            raise ValueError('Provide explicit candidates or captures, readings, and engine')
        with TemporaryDirectory(prefix='pdf-candidates-') as tmp_plan:
            plan_dir = (work / 'candidates') if work is not None else (Path(tmp_plan) / 'candidates')
            pdf_digests = select_pdf_candidates(
                captures=captures,
                readings=readings,
                engine=engine,
                work=plan_dir,
                verification_files=verification_files,
                sniff_version=sniff_version,
                root=root,
            )
    else:
        pdf_digests = _load_candidates(candidates, verification_files=verification_files)

    backfilled: list[str] = []
    already_present: list[str] = []
    would_backfill: list[str] = []
    missing_source: list[str] = []
    mismatches: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []

    with TemporaryDirectory(prefix='pdf-backfill-') as tmp_dir:
        spool_root = Path(tmp_dir)
        for index, digest in enumerate(pdf_digests):
            gz_key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
            pdf_key = f'bodies/sha256/{digest[:2]}/{digest}.pdf'
            if dry_run:
                would_backfill.append(pdf_key)
                continue

            try:
                response = store.adapter.get(gz_key)
            except Exception as error:
                if _is_missing_object_error(error):
                    missing_source.append(gz_key)
                    continue
                raise

            pdf_path = spool_root / f'{index}-{digest}.pdf'
            pdf_md5 = hashlib.md5()
            pdf_sha256 = hashlib.sha256()
            pdf_size = 0
            tail = b''
            decompress_error: str | None = None

            try:
                with closing(response['Body']) as raw_stream:
                    hashed = _HashedReader(raw_stream)
                    try:
                        with gzip.GzipFile(fileobj=hashed, mode='rb') as gz_reader, pdf_path.open('wb') as out:
                            while chunk := gz_reader.read(STREAM_CHUNK_BYTES):
                                pdf_size += len(chunk)
                                if pdf_size > SINGLE_PUT_LIMIT:
                                    raise ValueError('Single-PUT size limit exceeded')
                                pdf_md5.update(chunk)
                                pdf_sha256.update(chunk)
                                tail = (tail + chunk)[-PREFIX_BYTES:]
                                out.write(chunk)
                    except (OSError, EOFError, zlib.error) as error:
                        decompress_error = type(error).__name__
                        while hashed.read(STREAM_CHUNK_BYTES):
                            pass
                    else:
                        while hashed.read(STREAM_CHUNK_BYTES):
                            pass

                etag = response['ETag'].strip('"')
                expected_gz_size = response.get('ContentLength')
                expected_gz_md5 = single_put_md5(etag)
                if expected_gz_size is not None and hashed.size != expected_gz_size:
                    raise ValueError('Compressed stream length differs from ContentLength')
                if expected_gz_md5 is not None and hashed.md5.hexdigest() != expected_gz_md5:
                    raise ValueError('Compressed stream MD5 differs from ETag')

                if decompress_error is not None or pdf_sha256.hexdigest() != digest:
                    reason = decompress_error or 'identity_mismatch'
                    mismatches.append(dict(key=gz_key, error=reason))
                    records.append(dict(
                        key=gz_key,
                        size=hashed.size,
                        etag=etag,
                        sha256_verified=False,
                        stored_sha256=hashed.sha.hexdigest(),
                        checked_at=canonical_checked_at,
                        job='pdf-backfill',
                        error=reason,
                    ))
                    continue

                intact = _check_pdf_intact(pdf_path, pdf_size, tail)
                write_res = store.put_pdf_copy(
                    pdf_key,
                    pdf_path,
                    expected_md5=pdf_md5.hexdigest(),
                    expected_size=pdf_size,
                )
                if write_res.outcome == 'stored':
                    backfilled.append(pdf_key)
                else:
                    already_present.append(pdf_key)

                records.append(dict(
                    key=gz_key,
                    size=hashed.size,
                    etag=etag,
                    sha256_verified=True,
                    stored_sha256=hashed.sha.hexdigest(),
                    checked_at=canonical_checked_at,
                    job='pdf-backfill',
                ))
                records.append(dict(
                    key=pdf_key,
                    size=pdf_size,
                    etag=pdf_md5.hexdigest(),
                    sha256_verified=True,
                    stored_sha256=digest,
                    intact=intact,
                    checked_at=canonical_checked_at,
                    job='pdf-backfill',
                ))
            finally:
                pdf_path.unlink(missing_ok=True)

        provenance_key: str | None = None
        records_sha256: str | None = None
        records_path = (work / 'verification.jsonl') if work is not None else (spool_root / 'verification.jsonl')
        if records and not dry_run:
            with records_path.open('x', encoding='utf-8') as out:
                for row in records:
                    out.write(json.dumps(row, separators=(',', ':'), allow_nan=False) + '\n')
            records_sha256 = file_pin(records_path)['sha256']
            ts_label = stamp.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            provenance_key = f'provenance/verification/{ts_label}-{records_sha256[:16]}.jsonl'
            if not stage_only:
                store.put(provenance_key, records_path, 'application/x-ndjson')

    report: dict[str, Any] = dict(
        dry_run=dry_run,
        stage_only=stage_only,
        candidates=len(pdf_digests),
        backfilled=backfilled,
        already_present=already_present,
        would_backfill=would_backfill,
        missing_source=missing_source,
        mismatches=mismatches,
        verification_records_count=len(records),
        provenance_key=provenance_key,
        records_sha256=records_sha256,
    )
    if work is not None:
        (work / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report
