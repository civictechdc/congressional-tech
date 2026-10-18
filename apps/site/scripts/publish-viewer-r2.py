"""Publish the selected catalog to R2 without writing any archive/catalog keys."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path, PurePosixPath
import tempfile
import time
import urllib.request
import urllib.parse
import urllib.error
import uuid
from typing import NamedTuple

from botocore.exceptions import ClientError
from filename_recoveries import ACCEPTED_KEY, accepted_rows, index_recoveries

BUCKET = 'congressional-tech-raw'
PREFIX = 'viewer-publications/'
PUBLIC_URL = 'https://congressional-viewer-data.mdeeb.workers.dev/'
PUBLISHER_VERSION = 10
USER_AGENT = 'congressional-tech-viewer-publisher/1.0 (+https://github.com/civictechdc/congressional-tech)'


def public_request(url, headers=None):
    # Identify our automated verifier; Cloudflare rejects the generic urllib UA.
    return urllib.request.Request(url, headers={'User-Agent': USER_AGENT, **(headers or {})})


def open_public(request, *, timeout=60):
    for attempt in range(4):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
            error.close()
        except urllib.error.URLError:
            if attempt == 3:
                raise
        time.sleep(2 ** attempt)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


# These ceilings bound complete control-plane documents, never catalog payloads.
# Recovery status and admission mappings have larger per-source entries; exceeding
# a supported ceiling is an explicit format/capacity decision, not partial proof.
CONTROL_LIMITS = {'manifest': 4 * 1024**2, 'accepted': 16 * 1024**2, 'recovery': 32 * 1024**2}


def bounded_control_read(stream, *, kind='manifest', declared=None, expected=None):
    limit = CONTROL_LIMITS[kind]
    if expected is not None and (type(expected) is not int or not 0 <= expected <= limit):
        raise ValueError('Unsupported ' + kind + ' expected byte length')
    if declared is not None:
        try:
            declared = int(declared)
        except (ValueError, TypeError) as error:
            raise ValueError('Invalid ' + kind + ' declared byte length') from error
        if declared < 0 or declared > limit or (expected is not None and declared != expected):
            raise ValueError('Unsupported ' + kind + ' declared byte length')
    chunks, count = [], 0
    while chunk := stream.read(min(64 * 1024, limit + 1 - count)):
        count += len(chunk)
        if count > limit or (expected is not None and count > expected):
            raise ValueError('Oversized ' + kind + ' control response')
        chunks.append(chunk)
    if (declared is not None and count != declared) or (expected is not None and count != expected):
        raise ValueError('Incomplete ' + kind + ' control response')
    return b''.join(chunks)


def public_control(response, *, kind='manifest', expected=None):
    # open_public retries opening only; a body-read failure propagates. No write
    # or response-body retry is hidden here, including incomplete HTTP transfers.
    return bounded_control_read(response, kind=kind, declared=getattr(response, 'headers', {}).get('Content-Length'), expected=expected)


class ProtectedIdentity(NamedTuple):
    value: object
    etag: str | None
    modified: str | None
    sha256: str | None


def validate_prepared_output(root, manifest):
    """Refuse unsupported outputs before artifact acceptance or any remote write."""
    for path in root.rglob('*'):
        if path.is_file() and path.stat().st_size >= 5 * 1024**3:
            raise ValueError('Prepared publication exceeds single-PUT limit: ' + str(path.relative_to(root)))
    if len(encoded(manifest)) > CONTROL_LIMITS['manifest']:
        raise ValueError('Prepared manifest exceeds control byte limit')
    recovery = root / 'recovery-prepared.json'
    if recovery.exists() and recovery.stat().st_size > CONTROL_LIMITS['recovery']:
        raise ValueError('Prepared recovery status exceeds control byte limit')


def read_identity(client, key, *, optional=False):
    try:
        response = client.get_object(Bucket=BUCKET, Key=key)
    except ClientError as error:
        if optional and error.response['Error']['Code'] in ('NoSuchKey', '404'):
            return ProtectedIdentity(None, None, None, None)
        raise
    with response['Body'] as stream:
        payload = bounded_control_read(stream, kind='accepted' if key == ACCEPTED_KEY else 'manifest',
                                       declared=response.get('ContentLength'))
    return ProtectedIdentity(json.loads(payload), response['ETag'], response['LastModified'].isoformat(),
            hashlib.sha256(payload).hexdigest())



def read_json(client, key, *, optional=False):
    return read_identity(client, key, optional=optional)[:3]


def release_source_files(root=None):
    from viewer_release_identity import source_files
    return source_files(root or Path(__file__).resolve().parents[3])


def implementation_identity():
    return hashlib.sha256(encoded(release_source_files())).hexdigest()


def dependency_fingerprint():
    from viewer_release_identity import installed_runtime
    return installed_runtime()


def full_release_identity():
    return {'version': 1, 'implementation': implementation_identity(),
            'dependencies': dependency_fingerprint(), 'publisher_version': PUBLISHER_VERSION}


def validated_accepted(value):
    if value is None:
        return []
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('recoveries'), list):
        raise ValueError('Invalid accepted recovery mapping.')
    return accepted_rows(value['recoveries'])


def recovery_inputs(selected_digest, manifest_digest, manifest, accepted, *, release_identity=None):
    rows = validated_accepted(accepted)
    return {'version': 1, 'raw_manifest_sha256': selected_digest,
            'viewer_manifest_sha256': manifest_digest,
            'files': {name: manifest['files'][name]['sha256'] for name in ('filenames', 'groups')},
            'accepted': {'present': accepted is not None, 'sha256': hashlib.sha256(encoded(rows)).hexdigest()},
            'full_release_inputs': release_identity or full_release_identity()}


def verify_recovery_status(client, descriptor, pointer, *, public_url):
    if (not isinstance(descriptor, dict) or not isinstance(descriptor.get('path'), str)
            or not descriptor['path'].startswith('releases/') or '..' in PurePosixPath(descriptor['path']).parts):
        raise ValueError('Invalid selected recovery descriptor.')
    response = client.get_object(Bucket=BUCKET, Key=PREFIX + descriptor['path'])
    with response['Body'] as stream:
        payload = bounded_control_read(stream, kind='recovery', declared=response.get('ContentLength'), expected=descriptor['bytes'])
    if len(payload) != descriptor['bytes'] or hashlib.sha256(payload).hexdigest() != descriptor['sha256']:
        raise ValueError('Selected recovery status hash mismatch.')
    index = json.loads(payload)
    if index.get('version') != 1 or index.get('catalog_id') != pointer['catalog_id']:
        raise ValueError('Selected recovery status identity mismatch.')
    with open_public(public_request(public_url + descriptor['path'], {'Origin': 'https://civictechdc.github.io'})) as response:
        if public_control(response, kind='recovery', expected=descriptor['bytes']) != payload or response.headers.get('Access-Control-Allow-Origin') != '*':
            raise ValueError('Public recovery status or browser access differs.')
    return index


def check_recovery_inputs(client, selected_record, accepted_record, pointer_record):
    # These separate reads are a freshness observation, not a cross-object transaction.
    # The final viewer IfMatch still fences competing selector writers; source or
    # accepted inputs can advance after their individual read and need a later poll.
    if read_identity(client, 'indexes/catalog.json') != selected_record:
        raise ValueError('Catalog changed while preparing recovery status.')
    if read_identity(client, ACCEPTED_KEY, optional=True) != accepted_record:
        raise ValueError('Accepted recovery mappings changed before selection.')
    if read_identity(client, PREFIX + 'manifest.json') != pointer_record:
        raise ValueError('Viewer pointer changed while preparing recovery status.')


def recovery_result(pointer, index, rows, *, status):
    return {'status': status, 'catalog_id': pointer['catalog_id'],
            'accepted_recoveries': len(rows), 'affected_sources': len(index['sources']),
            'affected_groups': len(index['groups']), 'recovery': pointer['recovery'],
            'catalog_payloads_reused': True, 'raw_catalog_unchanged': True}

def prepared_files(root, manifest, *, validation=None):
    """Allow only manifest-declared files and the bounded source-ID shards."""
    if manifest.get('version') != 5:
        raise ValueError('Unsupported viewer manifest version.')
    selected = manifest['source_manifest']
    if selected['catalog_id'] != manifest['info']['catalog_id']:
        raise ValueError('Viewer and source catalog identities differ.')
    expected_prefix = selected['generation'] + '/viewer-v2/'
    files = {}
    for item in manifest['files'].values():
        name = item['path']
        if not name.startswith(expected_prefix) or '..' in PurePosixPath(name).parts:
            raise ValueError('Invalid publication path.')
        path = root / name
        if validation is not None:
            validation.file(path, expected=item)
        if path.is_symlink() or path.stat().st_size != item['bytes'] or (validation is None and digest(path) != item['sha256']):
            raise ValueError('Prepared publication differs from its manifest: ' + name)
        files[name] = path
    if manifest['ids'] != expected_prefix + 'ids/':
        raise ValueError('Invalid source-ID directory.')
    rows = 0
    for prefix in range(256):
        name = manifest['ids'] + f'{prefix:02x}.bin'
        path = root / name
        if validation is not None:
            validation.file(path)
        if path.is_symlink() or path.stat().st_size % 36:
            raise ValueError('Invalid source-ID shard.')
        rows += path.stat().st_size // 36
        files[name] = path
    if rows != manifest['info']['rows']:
        raise ValueError('Source-ID count does not match the catalog.')
    return files


def put_json(client, key, value, **condition):
    if not key.startswith(PREFIX):
        raise ValueError('Viewer publisher cannot write archive keys.')
    return client.put_object(Bucket=BUCKET, Key=key, Body=encoded(value),
                      ContentType='application/json', CacheControl='no-store', **condition)


def store_recovery_index(client, value):
    payload = encoded(value)
    if len(payload) > CONTROL_LIMITS['recovery']:
        raise ValueError('Recovery status exceeds control byte limit before upload')
    sha256 = hashlib.sha256(payload).hexdigest()
    # Use the gateway's existing immutable publication path allowlist.
    path = f'releases/{sha256[:32]}/{sha256[32:]}/viewer-v2/recovery-status.json'
    result = None
    try:
        result = put_json(client, PREFIX + path, value, IfNoneMatch='*')
    except ClientError as error:
        if error.response['Error']['Code'] not in ('PreconditionFailed', '412'):
            raise
    confirm = getattr(client, 'confirm_transfer', None)
    proof = result.get('_verified_transfer') if isinstance(result, dict) else None
    if confirm is None or not confirm(proof, bucket=BUCKET, key=PREFIX + path, size=len(payload), sha256=sha256):
        response = client.get_object(Bucket=BUCKET, Key=PREFIX + path)
        with response['Body'] as stream:
            if bounded_control_read(stream, kind='recovery', declared=response.get('ContentLength'), expected=len(payload)) != payload:
                raise ValueError('Recovery status failed complete readback.')
    return {'path': path, 'bytes': len(payload), 'sha256': sha256}


def recovery_preparation_inputs(manifest, accepted_record):
    return dict(version=1, source_manifest=manifest['source_manifest'],
        files={name: manifest['files'][name] for name in ('filenames', 'groups')},
        catalog={key: manifest['info'][key] for key in ('catalog_id', 'rows', 'entries')},
        accepted_present=accepted_record[0] is not None, accepted_sha256=accepted_record[3])


def prepare_recovery(root, manifest, accepted_record, *, validation=None):
    value = index_recoveries(root, manifest, validated_accepted(accepted_record[0]),
                             **({'validation': validation} if validation is not None else {}))
    prepared = dict(version=1, inputs=recovery_preparation_inputs(manifest, accepted_record), value=value)
    payload = encoded(prepared)
    if len(payload) > CONTROL_LIMITS['recovery']:
        raise ValueError('Prepared recovery status exceeds control byte limit')
    (root / 'recovery-prepared.json').write_bytes(payload)
    return prepared


def load_prepared_recovery(root, manifest, accepted_record, *, validation):
    path = root / 'recovery-prepared.json'
    validation.file(path)
    prepared = json.loads(path.read_bytes())
    if prepared.get('version') != 1 or prepared.get('inputs') != recovery_preparation_inputs(manifest, accepted_record):
        raise ValueError('Prepared recovery inputs changed')
    value = prepared['value']
    if (value.get('catalog_id') != manifest['info']['catalog_id'] or value.get('rows') != manifest['info']['rows']
            or value.get('entries') != manifest['info']['entries']):
        raise ValueError('Prepared recovery status identity changed')
    return value


def recovery_for_publication(client, root, manifest, *, validation=None):
    accepted_record = read_identity(client, ACCEPTED_KEY, optional=True)
    index = (load_prepared_recovery(root, manifest, accepted_record, validation=validation)
             if validation is not None else index_recoveries(root, manifest, validated_accepted(accepted_record[0])))
    return store_recovery_index(client, index), accepted_record


def select_recoveries(client, root, manifest, selected_record, accepted_record, pointer_record,
                      manifest_digest, *, public_url, index=None):
    pointer, pointer_etag = pointer_record[:2]
    accepted = validated_accepted(accepted_record[0])
    if index is None:
        index = index_recoveries(root, manifest, accepted)
    descriptor = store_recovery_index(client, index)
    updated = dict(pointer, recovery=descriptor,
                   recovery_inputs=recovery_inputs(selected_record[3], manifest_digest, manifest, accepted_record[0]))
    verify_recovery_status(client, descriptor, updated, public_url=public_url)
    check_recovery_inputs(client, selected_record, accepted_record, pointer_record)
    if updated != pointer:
        put_json(client, PREFIX + 'manifest.json', updated, IfMatch=pointer_etag)
    with open_public(public_request(public_url + 'manifest.json')) as response:
        if json.loads(public_control(response)) != updated:
            raise ValueError('Public recovery pointer differs.')
    return recovery_result(updated, index, accepted, status='recovery_updated')


def public_probe(base, pointer, manifest):
    """Check the actual public read path, including browser range/CORS headers."""
    manifest_url = base + pointer['manifest']
    request = public_request(manifest_url, {'Origin': 'https://civictechdc.github.io'})
    with open_public(request) as response:
        if json.loads(public_control(response)) != manifest or response.headers.get('Access-Control-Allow-Origin') != '*':
            raise ValueError('Public manifest or browser access differs.')
    # Recovery links are selected by the pointer and need their own public proof.
    if descriptor := pointer.get('recovery'):
        with open_public(public_request(base + descriptor['path'], {'Origin': 'https://civictechdc.github.io'})) as response:
            payload = public_control(response, kind='recovery', expected=descriptor['bytes'])
            if (len(payload) != descriptor['bytes'] or hashlib.sha256(payload).hexdigest() != descriptor['sha256']
                    or response.headers.get('Access-Control-Allow-Origin') != '*'):
                raise ValueError('Public recovery status failed verification.')
    # Detail views need the navigation and observation files as well as Parquet.
    def check_file(item):
        request = public_request(urllib.parse.urljoin(manifest_url, item['path']), {
            'Origin': 'https://civictechdc.github.io'})
        request.method = 'HEAD'
        with open_public(request) as response:
            if (response.status != 200 or int(response.headers.get('Content-Length', -1)) != item['bytes']
                    or response.headers.get('Access-Control-Allow-Origin') != '*'):
                raise ValueError('Public supporting file validation failed: ' + item['path'])
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(check_file, manifest['files'].values()))
    for name, item in manifest['files'].items():
        if not item['path'].endswith('.parquet'):
            continue
        request = public_request(urllib.parse.urljoin(manifest_url, item['path']), {
            'Origin': 'https://civictechdc.github.io', 'Range': 'bytes=0-3'})
        with open_public(request) as response:
            if (response.status != 206 or response.headers.get('Content-Range') != f"bytes 0-3/{item['bytes']}"
                    or response.read() != b'PAR1' or response.headers.get('Access-Control-Allow-Origin') != '*'
                    or 'content-range' not in response.headers.get('Access-Control-Expose-Headers', '').lower()):
                raise ValueError('Public Parquet range validation failed: ' + name)


def upload(client, root, manifest, *, previous_etag, selected_etag, public_url=PUBLIC_URL,
           probe=public_probe, publication_plan=None, validation=None):
    from guarded_recovery_publication_client import require_publication_client
    require_publication_client(client)
    if not all(callable(getattr(client,name,None)) for name in ('get_object','put_object','download_file')):
        raise TypeError('Viewer publication client requires conditional writes and complete file upload/readback')
    validate_prepared_output(root, manifest)
    files = prepared_files(root, manifest, **({'validation': validation} if validation is not None else {}))
    # Bind accepted status to the unmodified prepared manifest. Presentation-only
    # publication timestamps below do not change the accepted indexing inputs.
    recovery_manifest = manifest
    print(f"Uploading and reading back {len(files)} viewer objects for {manifest['info']['catalog_id']}", flush=True)
    plan = publication_plan or dict(release='releases/' + uuid.uuid4().hex + '/',
                                    published_at=datetime.now(timezone.utc).isoformat())
    release = plan['release']
    if (not release.startswith('releases/') or not release.endswith('/')
            or len(release.split('/')) != 3 or len(release.split('/')[1]) != 32
            or any(c not in '0123456789abcdef' for c in release.split('/')[1])):
        raise ValueError('Invalid persisted publication release')
    manifest = dict(manifest, published_at=plan['published_at'])
    manifest['info'] = dict(manifest['info'], publication_version=PUBLISHER_VERSION)
    pointer = {'version': 1, 'publisher_version': PUBLISHER_VERSION, 'catalog_id': manifest['info']['catalog_id'],
               'source_manifest': manifest['source_manifest'], 'published_at': manifest['published_at'],
               'manifest': release + 'manifest.json', 'full_release_inputs': full_release_identity()}
    recovery, accepted_record = recovery_for_publication(client, root, recovery_manifest,
        **({'validation': validation} if validation is not None else {}))
    pointer['recovery'] = recovery
    selected_record = read_identity(client, 'indexes/catalog.json')
    pointer['recovery_inputs'] = recovery_inputs(
        hashlib.sha256(encoded(manifest['source_manifest'])).hexdigest(),
        hashlib.sha256(encoded(manifest)).hexdigest(), manifest, accepted_record[0])
    if selected_record[0] == manifest['source_manifest']:
        pointer['recovery_inputs']['raw_manifest_sha256'] = selected_record[3]

    def transfer(item):
        name, path = item
        key = PREFIX + release + name
        local = validation.file(path) if validation is not None else None
        expected = local['sha256'] if local is not None else digest(path)
        content_type = ('application/vnd.apache.parquet' if name.endswith('.parquet') else
                        'application/json' if name.endswith('.json') else 'application/octet-stream')
        options = {'ContentType': content_type, 'CacheControl': 'public, max-age=31536000, immutable',
                   'Metadata': {'sha256': expected}}
        upload_local = getattr(client, 'upload_verified_file', None) if local is not None else None
        if upload_local is not None:
            receipt = upload_local(str(path), BUCKET, key, ExtraArgs=options, validation=local)
        else:
            # Plain SDK adapters also get one explicitly conditional single PUT.
            # Managed upload_file can retry/multipart without this condition.
            with path.open('rb') as stream:
                response = client.put_object(Bucket=BUCKET, Key=key, Body=stream,
                    ContentLength=path.stat().st_size, IfNoneMatch='*', **options)
            receipt = response.get('_verified_transfer') if isinstance(response, dict) else None
        confirm = getattr(client, 'confirm_transfer', None)
        verified = confirm is not None and confirm(receipt, bucket=BUCKET, key=key,
                                                   size=path.stat().st_size, sha256=expected)
        if not verified:
            # Plain SDK clients retain independent full-byte readback. A guarded
            # result can replace it only while its exact remote version remains.
            with tempfile.TemporaryDirectory(prefix='viewer-readback-') as folder:
                downloaded = Path(folder) / 'object'
                client.download_file(BUCKET, key, str(downloaded))
                if downloaded.stat().st_size != path.stat().st_size or digest(downloaded) != expected:
                    raise ValueError('Uploaded object failed readback: ' + name)
        if path.stat().st_size > 1_000_000:
            print(f'Verified {name}: {path.stat().st_size:,} bytes', flush=True)
        return path.stat().st_size

    with ThreadPoolExecutor(max_workers=6) as pool:
        total = sum(pool.map(transfer, files.items()))
    put_json(client, PREFIX + pointer['manifest'], manifest, IfNoneMatch='*')
    probe(public_url, pointer, manifest)
    # Keep old review links usable. Never replace an existing catalog locator.
    try:
        put_json(client, PREFIX + 'catalogs/' + pointer['catalog_id'] + '.json', pointer, IfNoneMatch='*')
    except ClientError as error:
        if error.response['Error']['Code'] not in ('PreconditionFailed', '412'):
            raise
    result = {'catalog_id': pointer['catalog_id'], 'bytes': total, 'files': len(files), 'manifest': pointer['manifest']}
    selected, etag, _ = read_json(client, 'indexes/catalog.json')
    if etag != selected_etag or selected != manifest['source_manifest']:
        return dict(result, status='superseded', reason='The raw catalog advanced; the next check will publish it.')
    if read_identity(client, ACCEPTED_KEY, optional=True) != accepted_record:
        return dict(result, status='superseded', reason='Accepted recovery mappings changed before selection.')
    try:
        put_json(client, PREFIX + 'manifest.json', pointer,
                 **({'IfMatch': previous_etag} if previous_etag else {'IfNoneMatch': '*'}))
    except ClientError as error:
        if error.response['Error']['Code'] in ('PreconditionFailed', '412'):
            return dict(result, status='superseded', reason='Another viewer publisher advanced the manifest.')
        raise
    actual, _, _ = read_json(client, PREFIX + 'manifest.json')
    if actual != pointer:
        raise ValueError('Selected viewer manifest failed readback.')
    with open_public(public_request(public_url + 'manifest.json')) as response:
        if json.loads(public_control(response)) != pointer:
            raise ValueError('Public viewer manifest differs from the selected publication.')
    return dict(result, status='published')


def check_selected_publication(client, pointer, *, public_url=PUBLIC_URL, records=None, release_identity=None):
    """Read-only: verify exact reuse, or require a new accepted preparation."""
    selected_record, accepted_record, pointer_record = records or (
        read_identity(client, 'indexes/catalog.json'), read_identity(client, ACCEPTED_KEY, optional=True),
        read_identity(client, PREFIX + 'manifest.json'))
    if pointer_record[0] != pointer or pointer['source_manifest'] != selected_record[0]:
        raise ValueError('Recovery status requires the currently selected viewer publication.')
    rows = validated_accepted(accepted_record[0])
    manifest, _, _, manifest_digest = read_identity(client, PREFIX + pointer['manifest'])
    if (manifest['source_manifest'] != selected_record[0]
            or manifest['info']['catalog_id'] != pointer['catalog_id']):
        raise ValueError('Selected viewer manifest differs from the catalog.')
    inputs = recovery_inputs(selected_record[3], manifest_digest, manifest, accepted_record[0], release_identity=release_identity)
    if pointer.get('recovery_inputs') == inputs:
        index = verify_recovery_status(client, pointer.get('recovery'), pointer, public_url=public_url)
        with open_public(public_request(public_url + 'manifest.json')) as response:
            if json.loads(public_control(response)) != pointer:
                raise ValueError('Public recovery pointer differs.')
        check_recovery_inputs(client, selected_record, accepted_record, pointer_record)
        return recovery_result(pointer, index, rows, status='unchanged')
    return {'status': 'recovery_preparation_required', 'catalog_id': pointer['catalog_id']}


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
    from publication_cli import main
    raise SystemExit(main(sys.modules[__name__]))
