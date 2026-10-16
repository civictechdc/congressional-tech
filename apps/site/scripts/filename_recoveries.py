"""Accepted URL recoveries, indexed against an existing viewer publication."""
import hashlib
import re
import struct
from urllib.parse import urlsplit

import pyarrow.parquet as pq

from filename_aliases import catalog_aliases

ACCEPTED_KEY = 'viewer-publications/recoveries/accepted.json'
FIELDS = ('original_url', 'recovered_url', 'body_key', 'kind', 'recovery_status', 'recovery_basis')


def accepted_rows(rows):
    result = []
    seen = set()
    for row in rows:
        value = {key: row[key] for key in FIELDS}
        for key in ('original_url', 'recovered_url'):
            url = urlsplit(value[key])
            if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
                raise ValueError('Invalid recovery URL.')
        if (value['original_url'] in seen or value['recovery_status'] != 'recovered'
                or value['recovery_basis'] not in {'user_accepted_url_variant',
                    'verified_archive_capture', 'official_document_identifier'}
                or value['kind'] not in ('pdf', 'html', 'xml', 'doc', 'video')
                or not re.fullmatch(r'bodies/sha256/[a-f0-9]{2}/[a-f0-9]{64}\.gz', value['body_key'])):
            raise ValueError('Invalid or duplicate accepted recovery.')
        seen.add(value['original_url'])
        result.append(value)
    return sorted(result, key=lambda row: row['original_url'])


def index_recoveries(root, manifest, rows):
    """Index accepted and catalog-derived links without rewriting source values."""
    rows = accepted_rows(rows)
    info = manifest['info']
    paths = {}
    for name in ('filenames', 'groups'):
        item = manifest['files'][name]
        path = (root / item['path']).resolve()
        if not path.is_relative_to(root.resolve()) or path.stat().st_size != item['bytes']:
            raise ValueError('Invalid recovery index input.')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != item['sha256']:
                raise ValueError('Recovery index input hash mismatch.')
        paths[name] = path
    groups = [value[0] for value in struct.iter_unpack('<I', paths['groups'].read_bytes())]
    if len(groups) != info['rows'] or any(group >= info['entries'] for group in groups):
        raise ValueError('Recovery group counts disagree with catalog.')
    accepted_count = len(rows)
    rows += catalog_aliases(paths['filenames'], rows)
    by_original = {row['original_url']: i for i, row in enumerate(rows)}
    by_saved = {(row['recovered_url'], row['body_key']): i for i, row in enumerate(rows[:accepted_count])}
    sources = []
    group_matches = {}
    position = 0
    for batch in pq.ParquetFile(paths['filenames']).iter_batches(columns=['source_url', 'body_key']):
        for row in batch.to_pylist():
            match = by_original.get(row['source_url'])
            if match is None:
                match = by_saved.get((row['source_url'], row['body_key']))
            if match is not None:
                sources.append([position, match])
                group_matches.setdefault(groups[position], set()).add(match)
            position += 1
    if position != info['rows']:
        raise ValueError('Recovery source counts disagree with catalog.')
    return {'version': 1, 'catalog_id': info['catalog_id'], 'rows': position, 'entries': info['entries'],
            'recoveries': rows, 'sources': sources,
            'groups': [[group, sorted(matches)] for group, matches in sorted(group_matches.items())]}
