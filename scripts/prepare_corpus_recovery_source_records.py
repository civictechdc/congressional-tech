"""Prepare local recovery source records using explicit retained timestamp evidence.

Adds missing prepared-source-records.json and source-record-preparation.json to a
sealed batch. The manifest and existing outputs are never replaced. An interrupted
pair needs diagnosis or a fresh batch copy; this command never resumes implicitly.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import sys
from urllib.parse import urlsplit

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
for package in ('congress_api', 'house-naming'):
    sys.path.insert(0, str(ROOT/'packages'/package/'src'))

from congress_api.models.content import CapturedBody
from congress_api.retention import raw_archive

OUTPUTS = ('prepared-source-records.json', 'source-record-preparation.json')
MEDIA = {'pdf': 'application/pdf', 'xml': 'application/xml', 'html': 'text/html',
         'doc': 'application/msword', 'txt': 'text/plain'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def instant(value):
    if not isinstance(value, str): return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def prepare(batch, captures, timestamp_aliases=None):
    batch, captures = Path(batch).resolve(), Path(captures).resolve()
    existing = [name for name in OUTPUTS if (batch/name).exists()]
    if existing:
        raise ValueError('Preparation outputs already exist; diagnose partial or completed preparation: '+', '.join(existing))
    inputs = {}
    def read(path):
        path = Path(path).resolve(); raw = path.read_bytes()
        inputs[str(path)] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)
    manifest = read(batch/'manifest.json')
    for name, expected in manifest['files'].items():
        if Path(name).name != name or digest(batch/name) != expected:
            raise ValueError('Sealed batch input changed: '+name)
        inputs[str(batch/name)] = expected
    if 'recoveries.json' not in manifest['files']:
        raise ValueError('Recovery rows are not sealed by the manifest')
    rows = read(batch/'recoveries.json')
    inputs[str(captures)] = digest(captures)
    needed = {(row['recovered_url'], row['body_key']) for row in rows if row.get('reused_retained_body')}
    prior = {}
    columns = ['context_url', 'body_key', 'retrieved_at', 'receipt_key', 'receipt_line']
    for part in pq.ParquetFile(captures).iter_batches(columns=columns, batch_size=32768):
        for row in part.to_pylist():
            key = row['context_url'], row['body_key']
            at = instant(row['retrieved_at'])
            if key in needed and at is not None and (key not in prior or at > instant(prior[key]['retrieved_at'])):
                prior[key] = row
    aliases = read(timestamp_aliases) if timestamp_aliases is not None else []
    for alias in aliases:
        if instant(alias.get('retrieved_at')) is None: continue
        for row in rows:
            if (row.get('package_id') and alias['body_key'] == row['body_key']
                    and Path(urlsplit(alias['context_url']).path).name.lower() == row['package_id'].lower()+'.pdf'):
                prior.setdefault((row['recovered_url'], row['body_key']), alias)
    output, unresolved = [], []
    for row in rows:
        if row.get('validated') is not True:
            raise ValueError('Recovery has not been validated')
        path = Path(row['body_path']).resolve()
        raw = path.read_bytes(); sha = hashlib.sha256(raw).hexdigest()
        if (sha != row['sha256'] or row['body_key'] != f'bodies/sha256/{sha[:2]}/{sha}.gz'
                or len(raw) != row['bytes']):
            raise ValueError('Recovery body changed: '+str(path))
        inputs[str(path)] = sha
        rendered = row.get('rendered_copy') is True
        original = None; at = basis = None
        stamp = row.get('candidate', {}).get('timestamp')
        need_transport = ((rendered and instant(row.get('retrieved_at')) is None)
                          or (not rendered and not stamp and (row['recovered_url'], row['body_key']) not in prior))
        transport = read(row['request_evidence']) if need_transport and row.get('request_evidence') else {}
        if rendered:
            # Rendering time and the original archive snapshot time describe
            # different bytes. Keep both without substituting the older time.
            at = (row['retrieved_at'] if instant(row.get('retrieved_at')) is not None
                  else transport.get('record', {}).get('retrieved_at'))
            basis = 'rendered_transport_receipt_time'
        elif stamp:
            try:
                at = datetime.strptime(stamp, '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc).isoformat()
                basis = 'archive_index_capture_time'
            except ValueError:
                pass
        elif (row['recovered_url'], row['body_key']) in prior:
            original = prior[(row['recovered_url'], row['body_key'])]
            at, basis = original['retrieved_at'], 'existing_official_package_and_exact_body_capture'
        elif transport:
            at = transport.get('record', {}).get('retrieved_at')
            basis = 'retained_transport_receipt_time'
        if instant(at) is None:
            unresolved.append(dict(original_url=row['original_url'], reason='source_timestamp_not_established'))
            continue
        source_url = original['context_url'] if original else row['recovered_url']
        evidence = dict(timestamp_basis=basis, original_capture=original, acquisition=row,
                        current_publisher_status_not_tested=True)
        if rendered:
            evidence.update(rendered_copy=True, byte_provenance='browser_rendered_archive_copy',
                            original_archive_response_bytes=False)
        response = dict(url=source_url, requested_url=source_url, retrieved_at=at, http_status=200,
            complete=True, publisher_requested=False,
            content=CapturedBody.from_bytes(raw, row.get('media_type') or MEDIA[row['kind']]).source_dict(),
            source_associations=[dict(original_url=row['original_url'], basis=row['recovery_basis'])],
            recovery_evidence=evidence)
        if rendered: response['rendered_copy'] = True
        record, captured, bodies, _ = raw_archive.prepare_capture(response, outcome='saved', links=[], mode='retained_import')
        if len(captured) != 1 or captured[0]['body_key'] != row['body_key'] or set(bodies) != {row['body_key']}:
            raise ValueError('Recovery source must describe exactly its sealed body')
        output.append(dict(original_url=row['original_url'], record=record, captures=captured,
                           local_bodies={row['body_key']: str(path)}, preserve_download_state=True))
    report = dict(status='local_records_only_state_assignment_waits_for_fresh_baseline', records=len(output),
        input_urls=len(rows), unresolved=unresolved, batch_manifest_sha256=inputs[str(batch/'manifest.json')],
        source_sha256=digest(Path(__file__)), raw_archive_sha256=digest(Path(raw_archive.__file__)), input_hashes=inputs)
    if timestamp_aliases is not None:
        report['timestamp_alias_evidence_sha256'] = inputs[str(Path(timestamp_aliases).resolve())]
    # Recheck all evidence and local bytes before adding either output.
    if any(digest(Path(path)) != expected for path, expected in inputs.items()):
        raise ValueError('Preparation input changed while records were built')
    with tempfile.TemporaryDirectory(prefix='.source-preparation-', dir=batch) as folder:
        for name, value in zip(OUTPUTS, (output, report), strict=True):
            staged = Path(folder)/name
            with staged.open('w') as stream:
                json.dump(value, stream, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        # Hard links publish each completed file atomically without overwriting;
        # report-last is the completion marker used by maintained consumers.
        for name in OUTPUTS:
            os.link(Path(folder)/name, batch/name)
            descriptor = os.open(batch, os.O_RDONLY)
            try: os.fsync(descriptor)
            finally: os.close(descriptor)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--captures', type=Path, required=True)
    parser.add_argument('--timestamp-aliases', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.batch, args.captures, args.timestamp_aliases), indent=2))
