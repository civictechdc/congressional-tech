"""Publish the selected catalog to R2 without writing any archive/catalog keys."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import time
import urllib.request
import urllib.parse
import urllib.error
import uuid

from botocore.exceptions import ClientError
from filename_recoveries import ACCEPTED_KEY, accepted_rows, index_recoveries

BUCKET = 'congressional-tech-raw'
PREFIX = 'viewer-publications/'
PUBLIC_URL = 'https://congressional-viewer-data.mdeeb.workers.dev/'
PUBLISHER_VERSION = 9
PAGES_MANIFEST = 'https://civictechdc.github.io/congressional-tech/data/filenames/manifest.json'
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


def read_json(client, key, *, optional=False):
    try:
        response = client.get_object(Bucket=BUCKET, Key=key)
    except ClientError as error:
        if optional and error.response['Error']['Code'] in ('NoSuchKey', '404'):
            return None, None, None
        raise
    with response['Body'] as stream:
        return json.load(stream), response['ETag'], response['LastModified'].isoformat()


def prepared_files(root, manifest):
    """Allow only manifest-declared files and the bounded source-ID shards."""
    if manifest.get('version') not in (2, 5):
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
        if path.is_symlink() or path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
            raise ValueError('Prepared publication differs from its manifest: ' + name)
        files[name] = path
    if manifest['ids'] != expected_prefix + 'ids/':
        raise ValueError('Invalid source-ID directory.')
    rows = 0
    for prefix in range(256):
        name = manifest['ids'] + f'{prefix:02x}.bin'
        path = root / name
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
    client.put_object(Bucket=BUCKET, Key=key, Body=encoded(value),
                      ContentType='application/json', CacheControl='no-store', **condition)


def store_recovery_index(client, value):
    payload = encoded(value)
    sha256 = hashlib.sha256(payload).hexdigest()
    # Use the gateway's existing immutable publication path allowlist.
    path = f'releases/{sha256[:32]}/{sha256[32:]}/viewer-v2/recovery-status.json'
    try:
        put_json(client, PREFIX + path, value, IfNoneMatch='*')
    except ClientError as error:
        if error.response['Error']['Code'] not in ('PreconditionFailed', '412'):
            raise
    response = client.get_object(Bucket=BUCKET, Key=PREFIX + path)
    with response['Body'] as stream:
        if stream.read() != payload:
            raise ValueError('Recovery status failed complete readback.')
    return {'path': path, 'bytes': len(payload), 'sha256': sha256}


def recovery_for_publication(client, root, manifest):
    accepted, _, _ = read_json(client, ACCEPTED_KEY, optional=True)
    index = index_recoveries(root, manifest, accepted['recoveries'] if accepted else [])
    return store_recovery_index(client, index) if index['recoveries'] else None


def accept_recoveries(client, root, rows, *, public_url=PUBLIC_URL):
    """Amend only viewer status; reuse every existing publication payload."""
    selected, selected_etag, _ = read_json(client, 'indexes/catalog.json')
    pointer, pointer_etag, _ = read_json(client, PREFIX + 'manifest.json')
    manifest = json.loads((root / 'manifest.json').read_text())
    remote_manifest, _, _ = read_json(client, PREFIX + pointer['manifest'])
    if (pointer['source_manifest'] != selected or manifest['source_manifest'] != selected
            or manifest['files'] != remote_manifest['files'] or manifest['info']['catalog_id'] != pointer['catalog_id']):
        raise ValueError('Recovery status requires the currently selected viewer publication.')
    accepted = {'version': 1, 'recoveries': accepted_rows(rows)}
    index = index_recoveries(root, manifest, accepted['recoveries'])
    previous, _, _ = read_json(client, ACCEPTED_KEY, optional=True)
    if previous is not None and previous != accepted:
        raise ValueError('A different accepted recovery mapping already exists.')
    if previous is None:
        put_json(client, ACCEPTED_KEY, accepted, IfNoneMatch='*')
    readback, _, _ = read_json(client, ACCEPTED_KEY)
    if readback != accepted:
        raise ValueError('Accepted recovery mapping failed readback.')
    descriptor = store_recovery_index(client, index)
    with open_public(public_request(public_url + descriptor['path'], {'Origin': 'https://civictechdc.github.io'})) as response:
        if (response.read() != encoded(index) or response.headers.get('Access-Control-Allow-Origin') != '*'):
            raise ValueError('Public recovery status or browser access differs.')
    fresh, fresh_etag, _ = read_json(client, 'indexes/catalog.json')
    if fresh != selected or fresh_etag != selected_etag:
        raise ValueError('Catalog changed while preparing recovery status.')
    fresh_accepted, _, _ = read_json(client, ACCEPTED_KEY)
    if fresh_accepted != accepted:
        raise ValueError('Accepted recovery mappings changed before selection.')
    updated = dict(pointer, recovery=descriptor)
    if updated != pointer:
        put_json(client, PREFIX + 'manifest.json', updated, IfMatch=pointer_etag)
    with open_public(public_request(public_url + 'manifest.json')) as response:
        if json.load(response) != updated:
            raise ValueError('Public recovery pointer differs.')
    return {'status': 'recovery_updated', 'catalog_id': pointer['catalog_id'],
            'accepted_recoveries': len(accepted['recoveries']), 'affected_sources': len(index['sources']),
            'affected_groups': len(index['groups']), 'recovery': descriptor,
            'catalog_payloads_reused': True, 'raw_catalog_unchanged': True}


def public_probe(base, pointer, manifest):
    """Check the actual public read path, including browser range/CORS headers."""
    manifest_url = base + pointer['manifest']
    request = public_request(manifest_url, {'Origin': 'https://civictechdc.github.io'})
    with open_public(request) as response:
        if json.load(response) != manifest or response.headers.get('Access-Control-Allow-Origin') != '*':
            raise ValueError('Public manifest or browser access differs.')
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
           probe=public_probe, archive_only=False, publication_plan=None):
    files = prepared_files(root, manifest)
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
               'manifest': release + 'manifest.json'}
    recovery = recovery_for_publication(client, root, manifest)
    if recovery:
        pointer['recovery'] = recovery

    def transfer(item):
        name, path = item
        key = PREFIX + release + name
        expected = digest(path)
        content_type = ('application/vnd.apache.parquet' if name.endswith('.parquet') else
                        'application/json' if name.endswith('.json') else 'application/octet-stream')
        receipt = client.upload_file(str(path), BUCKET, key, ExtraArgs={
            'ContentType': content_type, 'CacheControl': 'public, max-age=31536000, immutable',
            'Metadata': {'sha256': expected}})
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
    if archive_only:
        return dict(result, status='archived')
    selected, etag, _ = read_json(client, 'indexes/catalog.json')
    if etag != selected_etag or selected != manifest['source_manifest']:
        return dict(result, status='superseded', reason='The raw catalog advanced; the next check will publish it.')
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
        if json.load(response) != pointer:
            raise ValueError('Public viewer manifest differs from the selected publication.')
    return dict(result, status='published')


def bootstrap_pages(selected, root):
    """One-time migration reuses the current public files when their source matches."""
    try:
        with open_public(public_request(PAGES_MANIFEST), timeout=30) as response:
            manifest = json.load(response)
    except (OSError, ValueError):
        return None
    if manifest.get('version') != 2 or manifest.get('source_manifest') != selected:
        return None
    expected = selected['generation'] + '/viewer-v2/'
    names = [item['path'] for item in manifest['files'].values()]
    if manifest['ids'] != expected + 'ids/':
        raise ValueError('Invalid legacy source-ID directory.')
    names += [manifest['ids'] + f'{prefix:02x}.bin' for prefix in range(256)]
    for name in names:
        if not name.startswith(expected) or '..' in PurePosixPath(name).parts:
            raise ValueError('Invalid legacy publication path.')
    def download(name):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_public(public_request(urllib.parse.urljoin(PAGES_MANIFEST, name)), timeout=120) as response, path.open('wb') as output:
            while data := response.read(8 * 1024 * 1024):
                output.write(data)
    print('Migrating the matching verified Pages publication', flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(download, names))
    return manifest


def refresh_recoveries(client, pointer, *, public_url=PUBLIC_URL):
    """Refresh URL mappings against the existing immutable viewer tables."""
    accepted, accepted_etag, _ = read_json(client, ACCEPTED_KEY, optional=True)
    if accepted is None:
        return {'status': 'unchanged', 'catalog_id': pointer['catalog_id']}
    manifest, _, _ = read_json(client, PREFIX + pointer['manifest'])
    with tempfile.TemporaryDirectory(prefix='viewer-recovery-refresh-') as folder:
        root = Path(folder)
        (root / 'manifest.json').write_bytes(encoded(manifest))
        release = str(PurePosixPath(pointer['manifest']).parent) + '/'
        for name in ('filenames', 'groups'):
            item = manifest['files'][name]
            path = root / item['path']
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('Invalid recovery input path.')
            path.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(BUCKET, PREFIX + release + item['path'], str(path))
        fresh, fresh_etag, _ = read_json(client, ACCEPTED_KEY)
        if fresh != accepted or fresh_etag != accepted_etag:
            raise ValueError('Accepted recovery mappings changed during refresh.')
        return accept_recoveries(client, root, accepted['recoveries'], public_url=public_url)


def run(client, *, prepared=None, public_url=PUBLIC_URL, archive_only=False, publication_plan=None):
    selected, selected_etag, modified = read_json(client, 'indexes/catalog.json')
    previous, previous_etag, _ = read_json(client, PREFIX + 'manifest.json', optional=True)
    if publication_plan is None and not archive_only and previous and previous.get('source_manifest') == selected and previous.get('publisher_version') == PUBLISHER_VERSION:
        return refresh_recoveries(client, previous, public_url=public_url)
    with tempfile.TemporaryDirectory(prefix='filename-publication-') as folder:
        folder = Path(folder)
        if prepared:
            root = prepared
            manifest = json.loads((root / 'manifest.json').read_text())
            if not archive_only and manifest['source_manifest'] != selected:
                raise ValueError('Prepared publication is not the currently selected R2 catalog.')
        else:
            if archive_only:
                raise ValueError('Archiving requires a prepared publication.')
            root = folder / 'publication'
            manifest = bootstrap_pages(selected, root) if previous is None else None
        if not prepared and manifest is None:
            spec = importlib.util.spec_from_file_location('filename_publication', Path(__file__).with_name('publish-filename-viewer.py'))
            publication = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(publication)
            source = folder / 'source'
            (source / 'indexes').mkdir(parents=True)
            (source / 'indexes/catalog.json').write_bytes(encoded(selected))
            for item in selected['files'].values():
                key = item['key']
                if not key.startswith('catalog-generations/' + selected['generation'] + '/') or '..' in PurePosixPath(key).parts:
                    raise ValueError('Invalid immutable source location.')
                path = source / key
                path.parent.mkdir(parents=True, exist_ok=True)
                client.download_file(BUCKET, key, str(path))
            manifest = publication.publish(source, root, modified)
        manifest['info']['remote_last_modified'] = modified if not archive_only else manifest['info'].get('remote_last_modified')
        return upload(client, root, manifest, previous_etag=previous_etag, selected_etag=selected_etag,
                      public_url=public_url, archive_only=archive_only, publication_plan=publication_plan)


if __name__ == '__main__':
    import boto3
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, help='Reuse an already verified viewer publication during migration.')
    parser.add_argument('--archive-only', action='store_true', help='Retain a previous review snapshot without selecting it.')
    parser.add_argument('--public-url', default=PUBLIC_URL)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--accept-recoveries', type=Path, help='Mark retained URL variants recovered without rebuilding or uploading catalog tables; requires --prepared.')
    args = parser.parse_args()
    client = boto3.client('s3', endpoint_url=f'https://{os.environ["CLOUDFLARE_ACCOUNT_ID"]}.r2.cloudflarestorage.com',
                          aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'], aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'], region_name='auto')
    if args.accept_recoveries:
        if not args.prepared or args.archive_only:
            parser.error('--accept-recoveries requires --prepared and cannot be combined with --archive-only')
        result = accept_recoveries(client, args.prepared, json.loads(args.accept_recoveries.read_text()), public_url=args.public_url)
    else:
        result = run(client, prepared=args.prepared, public_url=args.public_url, archive_only=args.archive_only)
    if args.report:
        args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
