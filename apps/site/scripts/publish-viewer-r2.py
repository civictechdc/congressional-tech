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
import urllib.request
import urllib.parse
import uuid

from botocore.exceptions import ClientError

BUCKET = 'congressional-tech-raw'
PREFIX = 'viewer-publications/'
PUBLIC_URL = 'https://congressional-viewer-data.mdeeb.workers.dev/'
PUBLISHER_VERSION = 1
PAGES_MANIFEST = 'https://civictechdc.github.io/congressional-tech/data/filenames/manifest.json'
USER_AGENT = 'congressional-tech-viewer-publisher/1.0 (+https://github.com/civictechdc/congressional-tech)'


def public_request(url, headers=None):
    # Identify our automated verifier; Cloudflare rejects the generic urllib UA.
    return urllib.request.Request(url, headers={'User-Agent': USER_AGENT, **(headers or {})})


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
    if manifest.get('version') != 2:
        raise ValueError('Expected viewer manifest version 2.')
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


def public_probe(base, pointer, manifest):
    """Check the actual public read path, including browser range/CORS headers."""
    manifest_url = base + pointer['manifest']
    request = public_request(manifest_url, {'Origin': 'https://civictechdc.github.io'})
    with urllib.request.urlopen(request, timeout=60) as response:
        if json.load(response) != manifest or response.headers.get('Access-Control-Allow-Origin') != '*':
            raise ValueError('Public manifest or browser access differs.')
    for name in ('filenames', 'documents', 'browse', 'document_summaries'):
        item = manifest['files'][name]
        request = public_request(urllib.parse.urljoin(manifest_url, item['path']), {
            'Origin': 'https://civictechdc.github.io', 'Range': 'bytes=0-3'})
        with urllib.request.urlopen(request, timeout=60) as response:
            if (response.status != 206 or response.headers.get('Content-Range') != f"bytes 0-3/{item['bytes']}"
                    or response.read() != b'PAR1' or response.headers.get('Access-Control-Allow-Origin') != '*'
                    or 'content-range' not in response.headers.get('Access-Control-Expose-Headers', '').lower()):
                raise ValueError('Public Parquet range validation failed: ' + name)


def upload(client, root, manifest, *, previous_etag, selected_etag, public_url=PUBLIC_URL,
           probe=public_probe, archive_only=False):
    files = prepared_files(root, manifest)
    print(f"Uploading and reading back {len(files)} viewer objects for {manifest['info']['catalog_id']}", flush=True)
    release = 'releases/' + uuid.uuid4().hex + '/'
    manifest = dict(manifest, published_at=datetime.now(timezone.utc).isoformat())
    manifest['info'] = dict(manifest['info'], publication_version=PUBLISHER_VERSION)
    pointer = {'version': 1, 'publisher_version': PUBLISHER_VERSION, 'catalog_id': manifest['info']['catalog_id'],
               'source_manifest': manifest['source_manifest'], 'published_at': manifest['published_at'],
               'manifest': release + 'manifest.json'}

    def transfer(item):
        name, path = item
        key = PREFIX + release + name
        expected = digest(path)
        content_type = ('application/vnd.apache.parquet' if name.endswith('.parquet') else
                        'application/json' if name.endswith('.json') else 'application/octet-stream')
        client.upload_file(str(path), BUCKET, key, ExtraArgs={
            'ContentType': content_type, 'CacheControl': 'public, max-age=31536000, immutable',
            'Metadata': {'sha256': expected}})
        # Read back actual bytes; multipart ETags are not content hashes.
        response = client.get_object(Bucket=BUCKET, Key=key)
        actual = hashlib.sha256()
        with response['Body'] as stream:
            while part := stream.read(8 * 1024 * 1024):
                actual.update(part)
        if response['ContentLength'] != path.stat().st_size or actual.hexdigest() != expected:
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
    with urllib.request.urlopen(public_request(public_url + 'manifest.json'), timeout=60) as response:
        if json.load(response) != pointer:
            raise ValueError('Public viewer manifest differs from the selected publication.')
    return dict(result, status='published')


def bootstrap_pages(selected, root):
    """One-time migration reuses the current public files when their source matches."""
    try:
        with urllib.request.urlopen(public_request(PAGES_MANIFEST), timeout=30) as response:
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
        with urllib.request.urlopen(public_request(urllib.parse.urljoin(PAGES_MANIFEST, name)), timeout=120) as response, path.open('wb') as output:
            while data := response.read(8 * 1024 * 1024):
                output.write(data)
    print('Migrating the matching verified Pages publication', flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(download, names))
    return manifest


def run(client, *, prepared=None, public_url=PUBLIC_URL, archive_only=False):
    selected, selected_etag, modified = read_json(client, 'indexes/catalog.json')
    previous, previous_etag, _ = read_json(client, PREFIX + 'manifest.json', optional=True)
    if not archive_only and previous and previous.get('source_manifest') == selected and previous.get('publisher_version') == PUBLISHER_VERSION:
        return {'status': 'unchanged', 'catalog_id': selected['catalog_id']}
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
                      public_url=public_url, archive_only=archive_only)


if __name__ == '__main__':
    import boto3
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, help='Reuse an already verified viewer publication during migration.')
    parser.add_argument('--archive-only', action='store_true', help='Retain a previous review snapshot without selecting it.')
    parser.add_argument('--public-url', default=PUBLIC_URL)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    client = boto3.client('s3', endpoint_url=f'https://{os.environ["CLOUDFLARE_ACCOUNT_ID"]}.r2.cloudflarestorage.com',
                          aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'], aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'], region_name='auto')
    result = run(client, prepared=args.prepared, public_url=args.public_url, archive_only=args.archive_only)
    if args.report:
        args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
