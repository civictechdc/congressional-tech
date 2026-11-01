"""Sealed batch inputs, caller-owned digest checks, and remote body reconciliation.

Prior evidence is reusable only when its caller-pinned file digest, exact desired
body identity, and a fresh remote ETag and size all agree. Unknown versions need
full byte verification. This command never writes to the object store.
"""
import argparse
from collections import Counter
import configparser
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import re

from corpus_recovery.url_normalization import (
    _normalize_and_key_url,
    narrow_address_repairs,
    scope_probe_urls,
    url_identity,
)


def compare_loaded_digest(data, expected, error):
    """Hash bytes the caller already loaded and raise that caller's error on mismatch."""
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise error()
    return actual


def compare_source_preparation(preparation, manifest_sha256, error):
    """Require this parsed preparation to cover the sealed manifest."""
    if preparation['unresolved'] or preparation['batch_manifest_sha256'] != manifest_sha256:
        raise error()


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def reusable_result(key, desired, prior):
    """Require explicit identities, never infer verification from a status alone."""
    sha = desired.get('sha256', '')
    return (isinstance(sha, str) and re.fullmatch('[0-9a-f]{64}', sha) is not None
            and key == f'bodies/sha256/{sha[:2]}/{sha}.gz'
            and prior.get('status') == 'verified_exact_body'
            and prior.get('sha256') == sha
            and type(prior.get('raw_bytes')) is int
            and prior['raw_bytes'] == desired.get('bytes')
            and type(prior.get('stored_bytes')) is int and prior['stored_bytes'] > 0
            and isinstance(prior.get('stored_sha256'), str)
            and re.fullmatch('[0-9a-f]{64}', prior['stored_sha256']) is not None
            and isinstance(prior.get('etag'), str) and bool(prior['etag']))


def head_body(store, key):
    from botocore.exceptions import ClientError
    try:
        return store.client.head_object(Bucket=store.bucket, Key=key)
    except ClientError as error:
        if error.response['Error']['Code'] in {'NoSuchKey', '404', 'NotFound'}:
            return None
        raise


def reconcile(store, inventory, *, prior=None):
    results = {}
    for key, info in inventory.items():
        sha = info['sha256']
        if key != f'bodies/sha256/{sha[:2]}/{sha}.gz' or type(info['bytes']) is not int or info['bytes'] < 0:
            raise ValueError(f'Invalid desired body identity: {key}')
        old = (prior or {}).get('results', {}).get(key, {})
        try:
            head = head_body(store, key)
            if head is None:
                results[key] = dict(status='absent', upload_required=True, sha256=sha, raw_bytes=info['bytes'])
                continue
            if reusable_result(key, info, old) and (head['ETag'], head['ContentLength']) == (old['etag'], old['stored_bytes']):
                results[key] = dict(old, verification='prior_full_bytes_plus_fresh_version_and_size')
                continue
            # Bind the bytes to their GET response, not to the earlier HEAD.
            response = store.client.get_object(Bucket=store.bucket, Key=key)
            with response['Body'] as stream:
                stored = stream.read()
            if len(stored) != response['ContentLength']:
                raise ValueError('Incomplete remote body')
            with gzip.GzipFile(fileobj=io.BytesIO(stored)) as stream:
                raw = stream.read(info['bytes'] + 1)
            exact = len(raw) == info['bytes'] and hashlib.sha256(raw).hexdigest() == sha
            results[key] = dict(status='verified_exact_body' if exact else 'conflict',
                                sha256=sha, raw_bytes=len(raw), etag=response['ETag'],
                                stored_sha256=hashlib.sha256(stored).hexdigest(), stored_bytes=len(stored),
                                verification='full_body_sha256', upload_required=False if exact else None)
        except Exception as error:
            results[key] = dict(status='unresolved', error_type=type(error).__name__, error=str(error))
    return dict(read_only=True, bodies=len(results), counts=dict(Counter(r['status'] for r in results.values())),
                results=results)


def sealed_inputs(batch):
    def changed(name):
        return ValueError(f'Batch changed: {name}')

    manifest_bytes = (batch / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    files = dict(manifest['files'])
    files['manifest.json'] = hashlib.sha256(manifest_bytes).hexdigest()
    loaded = {'manifest.json': manifest_bytes}
    for name in ('prepared-source-records.json', 'source-record-preparation.json'):
        data = (batch / name).read_bytes()
        loaded[name] = data
        if name in files:
            compare_loaded_digest(data, files[name], lambda name=name: changed(name))
        else:
            files[name] = hashlib.sha256(data).hexdigest()
    for name, expected in files.items():
        if Path(name).name != name:
            raise changed(name)
        data = loaded.get(name)
        if data is None:
            data = (batch / name).read_bytes()
            loaded[name] = data
        compare_loaded_digest(data, expected, lambda name=name: changed(name))
    source = json.loads(loaded['source-record-preparation.json'])
    compare_source_preparation(
        source, files['manifest.json'],
        lambda: ValueError('Incomplete or mismatched source preparation'))
    prepared = json.loads(loaded['prepared-source-records.json'])
    prepared += json.loads(loaded['zip-receipts.json'] if 'zip-receipts.json' in loaded
                           else (batch / 'zip-receipts.json').read_bytes())
    inventory = json.loads(loaded['bodies.json'] if 'bodies.json' in loaded
                           else (batch / 'bodies.json').read_bytes())
    captures = [cap for item in prepared for cap in item['captures']]
    if {cap['body_key'] for cap in captures} != set(inventory):
        raise ValueError('Capture/body inventory coverage differs')
    for cap in captures:
        if any(cap[field] != inventory[cap['body_key']][field] for field in ('sha256', 'bytes')):
            raise ValueError('Capture/body identity differs')
    return files, inventory, dict(receipt_records=len(prepared), capture_rows=len(captures), distinct_bodies=len(inventory))


_DOCUMENT_EXTENSIONS = ('.pdf', '.xml', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.zip', '.rtf', '.csv')
_ROW_URL_COLUMNS = ('url', 'context_url', 'requested_url')
# Every column the history scan reads; Parquet scans project only these.
_HISTORY_COLUMNS = (
    *_ROW_URL_COLUMNS, 'family', 'body_key', 'sha256', 'body_sha256', 'media_type', 'fidelity',
    'retrieved_at', 'checked_at', 'last_attempt', 'outcome', 'resolution', 'last_outcome',
    'http_status', 'last_status', 'complete', 'intact', 'mode', 'receipt_key', 'receipt_line',
    'evidence_id', 'record_role', 'is_real_file', 'placeholder_body', 'usable_direct', 'subtype',
    'attempts',
)


def _row_outcome(row):
    return row.get('resolution') or row.get('outcome') or row.get('last_outcome')


def _row_status(row):
    status = row.get('http_status')
    return row.get('last_status') if status is None else status


def _expects_document(url):
    lower = (url or '').lower()
    path = lower.split('#', 1)[0].split('?', 1)[0]
    return ('/404?notfound=' in lower or '/download/' in lower or 'download=1' in lower
            or path.endswith(_DOCUMENT_EXTENSIONS))


def _is_usable_direct_row(row, url=''):
    """Check whether a single capture/state row represents a usable direct body.

    Rows must carry receipt evidence, a document role (when stated), a complete
    (where the column exists) and intact body, and must not be retained imports.
    """
    if not isinstance(row, dict) or row.get('usable_direct') is False:
        return False
    if _row_evidence_id(row) is None or row.get('mode') == 'retained_import':
        return False
    if 'complete' in row and row['complete'] is not True:
        return False
    if row.get('intact') is False:
        return False
    if row.get('record_role') is not None and row['record_role'] != 'document':
        return False
    if row.get('usable_direct') is True:
        return True
    if not (row.get('body_key') or row.get('sha256') or row.get('body_sha256')):
        return False
    if row.get('is_real_file') is False or bool(row.get('placeholder_body')):
        return False
    outcome = _row_outcome(row)
    status = _row_status(row)
    if status is not None:
        if int(status) != 200 or outcome not in ('stored', 'unchanged', 'ok', 'usable_direct', 'verified'):
            return False
    # Never treat status-less 'unchanged' state rows as usable direct bodies.
    elif outcome not in ('stored', 'ok', 'usable_direct', 'verified'):
        return False
    media_type = (row.get('media_type') or '').split(';', 1)[0].strip().lower()
    if media_type in ('text/html', 'application/xhtml+xml'):
        row_urls = (url, *(row.get(c) for c in (*_ROW_URL_COLUMNS, 'raw_url')))
        if any(_expects_document(u) for u in row_urls if isinstance(u, str)):
            return False
    return True


def _iso_instant(value):
    """Render datetimes and ISO strings as comparable UTC ``YYYY-MM-DDTHH:MM:SS.ffffffZ``."""
    if value is None or value == '':
        return ''
    instant = value
    if isinstance(value, str):
        try:
            instant = datetime.fromisoformat(value.replace('Z', '+00:00').replace('z', '+00:00'))
        except ValueError:
            return value
    if not isinstance(instant, datetime):
        return str(value)
    if instant.tzinfo is not None:
        instant = instant.astimezone(timezone.utc).replace(tzinfo=None)
    return instant.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _row_order_key(row):
    return (
        _iso_instant(row.get('checked_at') or row.get('retrieved_at') or row.get('last_attempt')),
        str(row.get('receipt_key') or ''),
        int(row.get('receipt_line') or 0),
    )


def _row_evidence_id(row):
    if not isinstance(row, dict):
        return None
    return (
        row.get('evidence_id')
        or (
            f"{row['receipt_key']}#{row.get('receipt_line') or 1}"
            if row.get('receipt_key')
            else None
        )
        or row.get('body_key')
    )


def _matching_row_urls(row, wanted):
    urls = []
    for key in _ROW_URL_COLUMNS:
        val = row.get(key)
        if isinstance(val, str) and val and val not in urls:
            if wanted is None or val in wanted:
                urls.append(val)
    return urls


def _iter_table_rows(table_src, *, wanted=None, wanted_arr=None):
    """Yield history rows matching ``wanted`` URLs, projecting only ``_HISTORY_COLUMNS``."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    if wanted is not None and not wanted:
        return
    if isinstance(table_src, (str, Path)):
        table_src = pq.ParquetFile(table_src)
    if isinstance(table_src, pq.ParquetFile):
        names = table_src.schema_arrow.names
        batches = table_src.iter_batches(batch_size=65536, columns=[c for c in _HISTORY_COLUMNS if c in names])
    elif isinstance(table_src, pa.Table):
        names = table_src.schema.names
        batches = table_src.select([c for c in _HISTORY_COLUMNS if c in names]).to_batches(max_chunksize=65536)
    else:
        for row in table_src:
            if wanted is None or _matching_row_urls(row, wanted):
                yield row
        return

    if wanted is not None and wanted_arr is None:
        wanted_arr = pa.array(sorted(wanted), type=pa.string())
    for batch in batches:
        if wanted_arr is not None:
            mask = None
            for col in _ROW_URL_COLUMNS:
                if col in batch.schema.names:
                    col_in = pc.is_in(batch.column(col), value_set=wanted_arr)
                    mask = col_in if mask is None else pc.or_kleene(mask, col_in)
            if mask is None:
                continue
            batch = batch.filter(mask)
        if batch.num_rows:
            yield from batch.to_pylist()


def scan_receipt_history(
    source_or_store=None,
    *,
    captures=None,
    states=None,
    fetch_outcomes=None,
    urls=None,
):
    """Read URL recovery history from raw_archive tables directly when available.

    Streams ``fetch_outcomes``, ``states``, and ``captures`` Parquet tables (or a ``RawSnapshot``)
    with predicate pushdown over ``urls``.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    wanted = set(urls) if urls is not None else None
    history = {}
    if wanted is not None and not wanted:
        return history
    wanted_arr = pa.array(sorted(wanted), type=pa.string()) if wanted is not None else None

    def observe(url, cand, row):
        entry = history.setdefault(
            url,
            dict(attempts=0, latest_state=cand, usable_attempt=None, outcomes=[], body_keys=[], source='table'),
        )
        if _row_order_key(cand) >= _row_order_key(entry['latest_state']):
            entry['latest_state'] = cand
        if _is_usable_direct_row(row, url):
            if entry.get('usable_attempt') is None or _row_order_key(cand) >= _row_order_key(entry['usable_attempt']):
                entry['usable_attempt'] = cand
        outcome = _row_outcome(row)
        if outcome and outcome not in entry['outcomes']:
            entry['outcomes'].append(outcome)
        if row.get('body_key') and row['body_key'] not in entry['body_keys']:
            entry['body_keys'].append(row['body_key'])
        return entry

    if hasattr(source_or_store, 'captures') and callable(getattr(source_or_store, 'captures', None)):
        if captures is None:
            captures = source_or_store.captures()
    if hasattr(source_or_store, 'states_for') and callable(getattr(source_or_store, 'states_for', None)) and wanted:
        for url, state_row in source_or_store.states_for(wanted).items():
            cand = dict(state_row, url=url, raw_url=state_row.get('url'))
            history[url] = dict(
                attempts=int(state_row.get('attempts') or 0),
                latest_state=cand,
                usable_attempt=cand if _is_usable_direct_row(state_row, url) else None,
                outcomes=[state_row['outcome']] if state_row.get('outcome') else [],
                body_keys=[state_row['body_key']] if state_row.get('body_key') else [],
                source='table',
            )

    root_path = Path(source_or_store) if isinstance(source_or_store, (str, Path)) else None
    if root_path is not None:
        if fetch_outcomes is None and (root_path / 'indexes/fetch-outcomes.parquet').exists():
            fetch_outcomes = pq.ParquetFile(root_path / 'indexes/fetch-outcomes.parquet')
        if states is None and (root_path / 'indexes/download-state.parquet').exists():
            states = pq.ParquetFile(root_path / 'indexes/download-state.parquet')
        if captures is None and (root_path / 'indexes/captures.parquet').exists():
            captures = pq.ParquetFile(root_path / 'indexes/captures.parquet')

    for table_src in (fetch_outcomes, states):
        if table_src is None:
            continue
        for row in _iter_table_rows(table_src, wanted=wanted, wanted_arr=wanted_arr):
            for url in _matching_row_urls(row, wanted):
                entry = observe(url, dict(row, url=url, raw_url=row.get('url')), row)
                attempts = int(row.get('attempts') if row.get('attempts') is not None else 1)
                entry['attempts'] = max(entry['attempts'], attempts)

    if captures is not None:
        capture_attempts = Counter()
        for row in _iter_table_rows(captures, wanted=wanted, wanted_arr=wanted_arr):
            for url in _matching_row_urls(row, wanted):
                capture_attempts[(url, row.get('receipt_key'), row.get('receipt_line'))] += 1
                # Keep only columns the row has: an absent ``complete`` is not ``True``.
                cand = dict(
                    row, url=url, raw_url=row.get('url'),
                    checked_at=row.get('checked_at') or row.get('retrieved_at'),
                    outcome=_row_outcome(row),
                    attempts=1,
                )
                observe(url, cand, row)
        by_url_attempts = Counter(u for (u, _, _) in capture_attempts)
        for url, count in by_url_attempts.items():
            if url in history and count > history[url]['attempts']:
                history[url]['attempts'] = count
                history[url]['latest_state']['attempts'] = count

    return history


def _target_rows(targets):
    import pyarrow as pa
    import pyarrow.parquet as pq

    if isinstance(targets, (str, Path)):
        return pq.read_table(targets).to_pylist()
    if isinstance(targets, pa.Table):
        return targets.to_pylist()
    return [dict(target_url=t) if isinstance(t, str) else dict(t) for t in targets]


def build_target_inventory(
    targets,
    *,
    policy=None,
    history=None,
    source_or_store=None,
    captures=None,
    states=None,
    fetch_outcomes=None,
    output=None,
    membership_origin='baseline',
    refresh_policy='historical_only',
):
    """Build target inventory rows (and optional Parquet table) from receipt history and CapturePolicy.

    Direct usability is derived from `scan_receipt_history`. Scope exclusion
    (`acquisition_excluded`) is determined strictly by static `CapturePolicy.pattern_family(url) is None`
    (falling back to `CapturePolicy.family(url)`) for every spelling in `scope_probe_urls`
    (the literal and its narrow repairs, resolved against an optional row `context_url`),
    binding `evidence_id` to `capture_scope:{policy.digest}`.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    raw_targets = _target_rows(targets)

    if history is None:
        target_urls = [
            r.get('target_url') or r.get('url')
            for r in raw_targets
            if r.get('target_url') or r.get('url')
        ]
        history = scan_receipt_history(
            source_or_store,
            captures=captures,
            states=states,
            fetch_outcomes=fetch_outcomes,
            urls=target_urls,
        )

    policy_digest = None
    scope_fn = None
    if policy is not None:
        scope_fn = getattr(policy, 'pattern_family', policy.family)
        policy_digest = getattr(policy, 'digest', None)
        if not policy_digest and hasattr(policy, 'entries'):
            from congress_shared.custody import canonical_json_bytes
            policy_digest = hashlib.sha256(
                canonical_json_bytes({'version': 1, 'entries': [entry for entry, _ in policy.entries]})
            ).hexdigest()

    rows = []
    for raw in raw_targets:
        target_url = raw.get('target_url') or raw.get('url')
        if not isinstance(target_url, str) or not target_url.strip():
            raise ValueError('Target inventory row requires a non-empty target_url')
        context_url = raw.get('context_url') if isinstance(raw.get('context_url'), str) else None
        hist = history.get(target_url) if history else None
        latest = (hist.get('latest_state') or {}) if hist else {}

        if hist is not None:
            usable_row = hist.get('usable_attempt')
            if usable_row is None and 'usable_attempt' not in hist and _is_usable_direct_row(latest, target_url):
                usable_row = latest
            usable_direct = usable_row is not None
            hist_evidence_id = _row_evidence_id(usable_row) if usable_row is not None else _row_evidence_id(latest)
        else:
            usable_direct = bool(raw.get('usable_direct', False))
            hist_evidence_id = raw.get('evidence_id')

        if usable_direct:
            acquisition_excluded = False
            evidence_id = hist_evidence_id or raw.get('evidence_id')
            if not evidence_id:
                raise ValueError(f'Usable direct target requires receipt evidence_id: {target_url}')
            subtype = raw.get('subtype') or (usable_row or latest).get('subtype') or 'usable_direct'
            unresolved_reason = None
        elif policy is not None:
            in_scope = any(scope_fn(probe) is not None for probe in scope_probe_urls(target_url, context_url))
            if not in_scope:
                acquisition_excluded = True
                if not policy_digest:
                    raise ValueError('CapturePolicy requires a digest or entries to bind scope exclusion evidence')
                evidence_id = f'capture_scope:{policy_digest}'
                subtype = 'capture_scope_excluded'
                unresolved_reason = None
            else:
                acquisition_excluded = False
                evidence_id = hist_evidence_id or raw.get('evidence_id')
                subtype = raw.get('subtype') or latest.get('outcome') or latest.get('last_outcome') or 'missing_direct'
                unresolved_reason = raw.get('unresolved_reason')
        else:
            acquisition_excluded = bool(raw.get('acquisition_excluded', False))
            evidence_id = hist_evidence_id or raw.get('evidence_id')
            if acquisition_excluded and not evidence_id:
                raise ValueError(f'Excluded target requires evidence_id: {target_url}')
            subtype = raw.get('subtype') or latest.get('outcome') or latest.get('last_outcome')
            unresolved_reason = raw.get('unresolved_reason')

        computed_norm, computed_key = _normalize_and_key_url(target_url)
        normalized_url = raw.get('normalized_url') or computed_norm
        url_key = raw.get('url_key') or computed_key
        row_refresh = (
            raw['refresh_policy']
            if 'refresh_policy' in raw and raw['refresh_policy'] is not None
            else refresh_policy
        )
        rows.append(
            dict(
                target_url=target_url,
                normalized_url=normalized_url,
                url_key=url_key,
                usable_direct=bool(usable_direct),
                acquisition_excluded=bool(acquisition_excluded),
                evidence_id=evidence_id,
                subtype=subtype,
                unresolved_reason=unresolved_reason,
                refresh_policy=row_refresh,
                membership_origin=raw.get('membership_origin') or membership_origin,
                context_url=context_url,
            )
        )

    if output is not None:
        schema = pa.schema([
            ('target_url', pa.string()),
            ('normalized_url', pa.string()),
            ('url_key', pa.string()),
            ('usable_direct', pa.bool_()),
            ('acquisition_excluded', pa.bool_()),
            ('evidence_id', pa.string()),
            ('subtype', pa.string()),
            ('unresolved_reason', pa.string()),
            ('refresh_policy', pa.string()),
            ('membership_origin', pa.string()),
            ('context_url', pa.string()),
        ])
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), out_path)

    return rows


def run(args):
    batch = args.batch.resolve()
    files, inventory, counts = sealed_inputs(batch)
    prior = None
    if args.prior:
        if not args.prior_sha256 or digest(args.prior) != args.prior_sha256:
            raise ValueError('Prior evidence digest mismatch')
        prior = json.loads(args.prior.read_text())
    from congress_shared.storage import R2Config, connect_r2
    from congress_api.retention.r2 import R2Store
    config = configparser.ConfigParser()
    config.read(args.config)
    account = config['congressionalraw']
    client = connect_r2(R2Config.from_ini_section(account, connect_timeout=15, read_timeout=180, retries={'total_max_attempts': 1}))
    store = R2Store(client, 'congressional-tech-raw')
    report = reconcile(store, inventory, prior=prior)
    report.update(at=datetime.now(timezone.utc).isoformat(), batch_manifest_sha256=files['manifest.json'], files=files)
    if args.prior:
        report.update(prior_evidence_sha256=args.prior_sha256)
    # State the versions expected at the next guarded dispatch, without admitting writes.
    versions = {key: client.head_object(Bucket=store.bucket, Key=key)['ETag'] for key in
                ('indexes/raw.json', 'indexes/catalog.json',
                 'viewer-publications/recoveries/accepted.json')}
    args.destination.mkdir(parents=True, exist_ok=False)
    report_path = args.destination / 'remote-body-readback.json'
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    readiness = dict(at=report['at'], files=files, **counts, remote_existing=report['counts'].get('verified_exact_body', 0),
                     remote_absent=report['counts'].get('absent', 0), expected_remote_versions=versions,
                     remote_body_readback_sha256=digest(report_path), batch=str(batch),
                     ready=all(r['status'] in {'verified_exact_body', 'absent'} for r in report['results'].values()),
                     writes_authorized=False)
    (args.destination / 'import-readiness.json').write_text(json.dumps(readiness, indent=2) + '\n')
    return readiness


def main(argv=None, *, root):
    """Run the reconciliation command against the checkout that owns the lock config."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--prior', type=Path)
    parser.add_argument('--prior-sha256')
    parser.add_argument('--config', type=Path, default=Path(root) / '.cache/r2-admin/rclone.conf')
    print(json.dumps(run(parser.parse_args(argv)), indent=2))
