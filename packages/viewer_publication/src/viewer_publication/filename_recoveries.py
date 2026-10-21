"""Accepted URL recoveries, indexed against an existing viewer publication."""
import hashlib
import json
import struct
import time
from urllib.parse import urlsplit

from viewer_publication.filename_aliases import valid_body

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
                or not valid_body(value['body_key'])):
            raise ValueError('Invalid or duplicate accepted recovery.')
        seen.add(value['original_url'])
        result.append(value)
    return sorted(result, key=lambda row: row['original_url'])


def index_recoveries(root, manifest, rows, *, validation=None, metrics=None):
    """Index accepted and catalog-derived links without rewriting source values."""
    rows = accepted_rows(rows)
    info = manifest['info']
    paths = {}
    for name in ('filenames', 'groups'):
        item = manifest['files'][name]
        path = (root / item['path']).resolve()
        if not path.is_relative_to(root.resolve()) or path.stat().st_size != item['bytes']:
            raise ValueError('Invalid recovery index input.')
        if validation is not None:
            validation.file(path, expected=item)
        else:
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != item['sha256']:
                    raise ValueError('Recovery index input hash mismatch.')
        paths[name] = path
    import mmap
    from contextlib import ExitStack
    from viewer_publication.filename_alias_index import AliasIndex, OUTPUT_BYTES
    size = paths['groups'].stat().st_size
    if size != 4 * info['rows']:
        raise ValueError('Recovery group counts disagree with catalog.')
    with ExitStack() as owned:
        stream = owned.enter_context(paths['groups'].open('rb'))
        groups = owned.enter_context(mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)) if size else None
        def group_for(position):
            if not 0 <= position < info['rows']:
                raise ValueError('Recovery source counts disagree with catalog.')
            group, = struct.unpack_from('<I', groups, position * 4)
            if group >= info['entries']:
                raise ValueError('Recovery group counts disagree with catalog.')
            return group
        with AliasIndex(paths['filenames'], rows, group_for=group_for, metrics=metrics) as index:
            result_rows = rows + index.aliases()
            sources, matched_groups = index.mappings(result_rows)
            if index.rows != info['rows']:
                raise ValueError('Recovery source counts disagree with catalog.')
            result = {'version': 1, 'catalog_id': info['catalog_id'], 'rows': index.rows, 'entries': info['entries'],
                      'recoveries': result_rows, 'sources': sources, 'groups': matched_groups}
            # Entry accounting already includes each exact encoded entry plus
            # one separator. Add the small empty-array header and remove the
            # final separator from every nonempty array; do not walk output twice.
            started = time.perf_counter()
            arrays = ('recoveries', 'sources', 'groups')
            header = dict(result, **{name: [] for name in arrays})
            header_bytes = sum(len(fragment.encode()) for fragment in
                json.JSONEncoder(sort_keys=True, separators=(',', ':')).iterencode(header))
            encoded_bytes = header_bytes + index.output_bytes - sum(bool(result[name]) for name in arrays)
            if encoded_bytes > OUTPUT_BYTES:
                raise ValueError(f'Recovery status exceeds {OUTPUT_BYTES} byte output budget')
            if metrics is not None:
                metrics['exact_output_bytes'] = encoded_bytes
                metrics['output_header_check_seconds'] = time.perf_counter() - started
            return result
