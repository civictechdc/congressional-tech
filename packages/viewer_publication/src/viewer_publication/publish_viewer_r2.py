"""Publish the selected catalog to R2 without writing any archive/catalog keys."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
import time
import urllib.request
import urllib.parse
import urllib.error
import uuid
from typing import NamedTuple

from botocore.exceptions import ClientError
from congress_api.retention.control_documents import CONTROL_LIMITS, bounded_control_read
from viewer_publication.constants import (
    ACCEPTED_KEY,
    BUCKET,
    PREFIX,
    PUBLIC_URL,
    PUBLISHER_VERSION,
    USER_AGENT,
)
from viewer_publication.filename_recoveries import accepted_rows, index_recoveries


def public_request(url, headers=None):
    # Identify our automated verifier; Cloudflare rejects the generic urllib UA.
    return urllib.request.Request(url, headers={'User-Agent': USER_AGENT, **(headers or {})})


def open_public(request, *, timeout=60):
    for attempt in range(4):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            error.close()
            if error.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
        except urllib.error.URLError:
            if attempt == 3:
                raise
        time.sleep(2 ** attempt)


from congress_shared.custody import canonical_json_bytes, file_identity


def encoded(value):
    return canonical_json_bytes(value, ensure_ascii=True)


def digest(path):
    return file_identity(path).sha256


def public_control(response, *, kind='manifest', expected=None):
    # open_public retries opening only; a body-read failure propagates. No write
    # or response-body retry is hidden here, including incomplete HTTP transfers.
    return bounded_control_read(response, kind=kind, declared=getattr(response, 'headers', {}).get('Content-Length'), expected=expected)


class ProtectedIdentity(NamedTuple):
    value: object
    etag: str | None
    modified: str | None
    sha256: str | None


def as_protected(record):
    if record is None:
        return None
    if isinstance(record, ProtectedIdentity):
        return record
    if isinstance(record, dict):
        return ProtectedIdentity(record.get('value'), record.get('etag'), record.get('modified'), record.get('sha256'))
    return ProtectedIdentity(*record)


def validate_prepared_output(root, manifest):
    """Refuse unsupported outputs before artifact acceptance or any remote write."""
    for path in root.rglob('*'):
        if path.is_file() and path.stat().st_size >= 5 * 1024**3:
            raise ValueError('Prepared publication exceeds single-PUT limit: ' + str(path.relative_to(root)))
    if len(encoded(manifest)) > CONTROL_LIMITS['manifest']:
        raise ValueError('Prepared manifest exceeds control byte limit')
    if manifest.get('version') == 6:
        from viewer_publication.filename_native import ViewerAssets, validate_publication
        validate_publication(ViewerAssets(root), manifest)
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
    from viewer_publication.release_identity import source_files
    return source_files(root or Path(__file__).resolve().parents[4])


def implementation_identity():
    return hashlib.sha256(encoded(release_source_files())).hexdigest()


def dependency_fingerprint():
    from viewer_publication.release_identity import installed_runtime
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
    basis = ({'version': 2, 'source_identity': manifest['source_identity'], 'roots': manifest['roots']}
             if manifest.get('version') == 6 else
             {'version': 1, 'files': {name: manifest['files'][name]['sha256'] for name in ('filenames', 'groups')}})
    return {**basis, 'raw_manifest_sha256': selected_digest,
            'viewer_manifest_sha256': manifest_digest,
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
    version = 2 if pointer.get('source_manifest', {}).get('version') == 2 else 1
    if (index.get('version') != version or index.get('catalog_id') != pointer['catalog_id']
            or version == 2 and (not pointer.get('source_identity')
                                 or index.get('source_identity') != pointer['source_identity'])):
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
    if manifest.get('version') == 6:
        from viewer_publication.filename_native import ViewerAssets, iterator_inventory, validate_publication
        assets = ViewerAssets(root)
        validate_publication(assets, manifest)
        files = {}
        for item in iterator_inventory(assets, manifest['inventory']):
            name, path = item['path'], root / item['path']
            if validation is not None:
                validation.file(path, expected=item)
            if (path.is_symlink() or not path.is_file() or path.stat().st_size != item['bytes']
                    or validation is None and digest(path) != item['sha256']):
                raise ValueError('Prepared publication differs from its inventory: ' + name)
            files[name] = path
        return files
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
    accepted_record = as_protected(accepted_record)
    basis = (dict(version=2, source_identity=manifest['source_identity'], roots=manifest['roots'])
             if manifest.get('version') == 6 else
             dict(version=1, files={name: manifest['files'][name] for name in ('filenames', 'groups')}))
    return dict(basis, source_manifest=manifest['source_manifest'],
        catalog={key: manifest['info'][key] for key in ('catalog_id', 'rows', 'entries')},
        accepted_present=accepted_record.value is not None, accepted_sha256=accepted_record.sha256)


def require_native_recovery(value, manifest):
    if (not isinstance(value, dict) or value.get('version') != 2
            or value.get('source_identity') != manifest['source_identity']
            or any(value.get(key) != manifest['info'][key] for key in ('catalog_id', 'rows', 'entries'))):
        raise ValueError('Stable recovery status identity differs from the selected catalog')


def prepare_recovery(root, manifest, accepted_record, *, validation=None, index=None):
    accepted_record = as_protected(accepted_record)
    if manifest.get('version') == 6:
        if index is None:
            raise ValueError('Native publication requires an explicitly prepared stable recovery index')
        require_native_recovery(index, manifest)
        if index.get('accepted') != validated_accepted(accepted_record.value):
            raise ValueError('Stable recovery acceptance differs from its selected inputs')
        value = index
    else:
        if index is not None:
            raise ValueError('Historical recovery preparation requires verified source files')
        value = index_recoveries(root, manifest, validated_accepted(accepted_record.value),
                                **({'validation': validation} if validation is not None else {}))
    prepared = dict(version=1, inputs=recovery_preparation_inputs(manifest, accepted_record), value=value)
    payload = encoded(prepared)
    if len(payload) > CONTROL_LIMITS['recovery']:
        raise ValueError('Prepared recovery status exceeds control byte limit')
    (root / 'recovery-prepared.json').write_bytes(payload)
    return prepared


def load_prepared_recovery(root, manifest, accepted_record, *, validation):
    accepted_record = as_protected(accepted_record)
    path = root / 'recovery-prepared.json'
    validation.file(path)
    prepared = json.loads(path.read_bytes())
    if prepared.get('version') != 1 or prepared.get('inputs') != recovery_preparation_inputs(manifest, accepted_record):
        raise ValueError('Prepared recovery inputs changed')
    value = prepared['value']
    if manifest.get('version') == 6:
        require_native_recovery(value, manifest)
        if value.get('accepted') != validated_accepted(accepted_record.value):
            raise ValueError('Stable recovery acceptance differs from its selected inputs')
    if (value.get('catalog_id') != manifest['info']['catalog_id'] or value.get('rows') != manifest['info']['rows']
            or value.get('entries') != manifest['info']['entries']):
        raise ValueError('Prepared recovery status identity changed')
    return value


def recovery_for_publication(client, root, manifest, *, validation=None, plan=None):
    accepted_record = as_protected(read_identity(client, ACCEPTED_KEY, optional=True))
    if plan is not None:
        # upload already required complete plan custody before any write.
        if tuple(accepted_record) != tuple(plan.protected['accepted']):
            raise ValueError('Accepted recovery mappings changed after viewer preparation')
        index = plan.recovery
    else:
        if manifest.get('version') == 6 and validation is None:
            raise ValueError('Native recovery publication requires verified prepared status')
        index = (load_prepared_recovery(root, manifest, accepted_record, validation=validation)
                 if validation is not None else index_recoveries(root, manifest, validated_accepted(accepted_record.value)))
    return store_recovery_index(client, index), accepted_record


def select_recoveries(client, root, manifest, selected_record, accepted_record, pointer_record,
                      manifest_digest, *, public_url, index=None):
    selected_record = as_protected(selected_record)
    accepted_record = as_protected(accepted_record)
    pointer_record = as_protected(pointer_record)
    pointer, pointer_etag = pointer_record.value, pointer_record.etag
    accepted = validated_accepted(accepted_record.value)
    if index is None:
        if manifest.get('version') == 6:
            raise ValueError('Native publication requires an explicitly prepared stable recovery index')
        index = index_recoveries(root, manifest, accepted)
    if manifest.get('version') == 6:
        require_native_recovery(index, manifest)
        if index.get('accepted') != accepted:
            raise ValueError('Stable recovery acceptance differs from its selected inputs')
    descriptor = store_recovery_index(client, index)
    updated = dict(pointer, recovery=descriptor,
                   recovery_inputs=recovery_inputs(selected_record.sha256, manifest_digest, manifest, accepted_record.value))
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
    if manifest.get('version') == 6:
        return public_probe_selected(base, manifest)
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


def public_probe_selected(base, manifest):
    """Verify root custody and sample one selected partition's public ranges.

    Every newly uploaded object already receives complete private readback. This
    bounded sample checks the browser gateway without fetching all reused data.
    """
    from viewer_publication.filename_native import ViewerAssets, validate_publication
    def read_asset(path):
        with open_public(public_request(base + path, {'Origin': 'https://civictechdc.github.io'})) as response:
            if response.headers.get('Access-Control-Allow-Origin') != '*':
                raise ValueError('Public catalog metadata browser access differs')
            return public_control(response)
    with tempfile.TemporaryDirectory(prefix='viewer-public-probe-') as directory:
        assets = ViewerAssets(directory, read_asset=read_asset)
        validate_publication(assets, manifest)
        current = manifest['roots']['sources']
        while current:
            node = assets.read_node(current)
            if node['kind'] == 'source-leaf':
                for item in node['source']['files'].values():
                    is_parquet = item['path'].endswith('.parquet')
                    request = public_request(base + item['path'], dict(Origin='https://civictechdc.github.io',
                        **({'Range': 'bytes=0-3'} if is_parquet else {})))
                    if not is_parquet:
                        request.method = 'HEAD'
                    with open_public(request) as response:
                        if response.headers.get('Access-Control-Allow-Origin') != '*':
                            raise ValueError('Public partition browser access differs')
                        if is_parquet:
                            if (response.status != 206 or response.headers.get('Content-Range') != f"bytes 0-3/{item['bytes']}"
                                    or response.read() != b'PAR1' or 'content-range' not in response.headers.get('Access-Control-Expose-Headers', '').lower()):
                                raise ValueError('Public selected Parquet range differs')
                        elif response.status != 200 or int(response.headers.get('Content-Length', -1)) != item['bytes']:
                            raise ValueError('Public selected supporting file length differs')
                break
            if node['kind'] != 'source-branch':
                raise ValueError('Invalid public source partition route')
            current = next(iter(node['children'].values()), None)


def upload(client, root, manifest, *, previous_etag, selected_etag, public_url=PUBLIC_URL,
           probe=public_probe, publication_plan=None, validation=None, plan=None):
    from viewer_publication.client import require_publication_client
    require_publication_client(client)
    if not all(callable(getattr(client, name, None)) for name in ('get_object', 'put_object', 'download_file')):
        raise TypeError('Viewer publication client requires conditional writes and complete file upload/readback')
    if plan is not None:
        if plan.mode != 'full':
            raise ValueError('Full upload requires an accepted full viewer plan')
        plan.require(root, manifest)
        if (plan.conditions != dict(previous_etag=previous_etag, selected_etag=selected_etag)
                or plan.release_plan != publication_plan):
            raise ValueError('Upload differs from accepted original viewer plan')
        validation = plan.validation
        files = plan.files
    else:
        validate_prepared_output(root, manifest)
        files = prepared_files(root, manifest, **({'validation': validation} if validation is not None else {}))
    # Bind accepted status to the unmodified prepared manifest. Presentation-only
    # publication timestamps below do not change the accepted indexing inputs.
    recovery_manifest = manifest
    print(f"Uploading and reading back {len(files)} viewer objects for {manifest['info']['catalog_id']}", flush=True)
    release_plan = publication_plan or dict(release='releases/' + uuid.uuid4().hex + '/',
                                    published_at=datetime.now(timezone.utc).isoformat())
    release = release_plan['release']
    if (not release.startswith('releases/') or not release.endswith('/')
            or len(release.split('/')) != 3 or len(release.split('/')[1]) != 32
            or any(c not in '0123456789abcdef' for c in release.split('/')[1])):
        raise ValueError('Invalid persisted publication release')
    manifest = dict(manifest, published_at=release_plan['published_at'])
    manifest['info'] = dict(manifest['info'], publication_version=PUBLISHER_VERSION)
    pointer = {'version': 1, 'publisher_version': PUBLISHER_VERSION, 'catalog_id': manifest['info']['catalog_id'],
               'source_manifest': manifest['source_manifest'], 'published_at': manifest['published_at'],
               'manifest': release + 'manifest.json', 'full_release_inputs': full_release_identity()}
    if manifest.get('version') == 6:
        pointer['source_identity'] = manifest['source_identity']
    recovery, accepted_record = recovery_for_publication(client, root, recovery_manifest,
        **({'plan': plan} if plan is not None else {'validation': validation} if validation is not None else {}))
    pointer['recovery'] = recovery
    selected_record = as_protected(read_identity(client, 'indexes/catalog.json'))
    accepted_record = as_protected(accepted_record)
    pointer['recovery_inputs'] = recovery_inputs(
        hashlib.sha256(encoded(manifest['source_manifest'])).hexdigest(),
        hashlib.sha256(encoded(manifest)).hexdigest(), manifest, accepted_record.value)
    if selected_record.value == manifest['source_manifest']:
        pointer['recovery_inputs']['raw_manifest_sha256'] = selected_record.sha256

    def transfer(item):
        name, path = item
        key = PREFIX + (name if manifest.get('version') == 6 else release + name)
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
            try:
                with path.open('rb') as stream:
                    response = client.put_object(Bucket=BUCKET, Key=key, Body=stream,
                        ContentLength=path.stat().st_size, IfNoneMatch='*', **options)
            except ClientError as error:
                if error.response['Error']['Code'] not in ('PreconditionFailed', '412'):
                    raise
                response = None  # Verify the existing immutable bytes; never resend.
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
        from viewer_publication.client import publish_manifest_pointer
        publish_manifest_pointer(
            client,
            bucket=BUCKET,
            pointer=pointer,
            key=PREFIX + 'manifest.json',
            expected_etag=previous_etag,
        )
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
    if records is not None:
        selected_record = as_protected(records[0])
        accepted_record = as_protected(records[1])
        pointer_record = as_protected(records[2])
    else:
        selected_record = as_protected(read_identity(client, 'indexes/catalog.json'))
        accepted_record = as_protected(read_identity(client, ACCEPTED_KEY, optional=True))
        pointer_record = as_protected(read_identity(client, PREFIX + 'manifest.json'))
    if pointer_record.value != pointer or pointer['source_manifest'] != selected_record.value:
        raise ValueError('Recovery status requires the currently selected viewer publication.')
    rows = validated_accepted(accepted_record.value)
    manifest, _, _, manifest_digest = read_identity(client, PREFIX + pointer['manifest'])
    if (manifest['source_manifest'] != selected_record.value
            or manifest['info']['catalog_id'] != pointer['catalog_id']):
        raise ValueError('Selected viewer manifest differs from the catalog.')
    if (manifest.get('version') == 6 and
            (pointer.get('source_identity') != manifest.get('source_identity')
             or manifest['source_identity'].get('selector_sha256') != selected_record.sha256)):
        raise ValueError('Selected viewer source identity differs from the exact catalog.')
    inputs = recovery_inputs(selected_record.sha256, manifest_digest, manifest, accepted_record.value, release_identity=release_identity)
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
    from viewer_publication.publication_cli import main
    raise SystemExit(main(sys.modules[__name__]))
