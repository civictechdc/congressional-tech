"""Update stable recovery links from affected URLs and retained row ownership."""
import json
from contextlib import closing
from pathlib import Path
import pickle
import sqlite3
from tempfile import TemporaryDirectory

from congress_api.parsers.archive_links import allowed_url
from congress_api.retention.saved_responses import saved_response
from congress_api.retention.source_aliases import resolution_candidates
from viewer_publication.filename_aliases import content_kind, valid_body
from viewer_publication.filename_alias_index import OUTPUT_BYTES
from viewer_publication.filename_recoveries import accepted_rows


class CatalogRecoverySources:
    """Adapt selected source lookups; preserve the original encounter ordering."""
    def __init__(self, snapshot, *, max_ordered_bytes):
        from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
        self.snapshot, self.max_ordered_bytes = snapshot, max_ordered_bytes
        self.owner = CatalogDependencyStorage.for_snapshot(snapshot)
        self.selection = snapshot.selection['dependency']

    def urls(self):
        # Initial adoption only. Subsequent updates use the exact change cursor.
        for batch in self.snapshot.table('filenames', max_ordered_bytes=self.max_ordered_bytes).iter_batches(
                columns=['source_url']):
            yield from (url for url in batch.column(0).to_pylist() if url)

    def at_url(self, url):
        # URL membership is hash routed, while the historical content-kind rule
        # uses the last encounter. Spill a prolific URL's rows before ordering.
        with TemporaryDirectory(prefix='recovery-url-') as directory, closing(
                sqlite3.connect(Path(directory) / 'sources.sqlite')) as db:
            db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192; '
                             'CREATE TABLE sources(position INTEGER PRIMARY KEY,body BLOB);')
            for record in self.owner.sources_at_url(self.selection, url):
                db.execute('INSERT INTO sources VALUES (?,?)',
                           (record['source_order'], pickle.dumps(record['source_values'])))
            for body, in db.execute('SELECT body FROM sources ORDER BY position'):
                yield pickle.loads(body)

    def targeting(self, url):
        for record in self.owner.originals_targeting(self.selection, url):
            yield record['source_values']


def index_catalog_recoveries(snapshot, rows, *, max_ordered_bytes, previous=None, metrics=None):
    """Bind recovery updates to exact retained catalog ancestry and row values."""
    source_identity = previous['source_identity'] if previous is not None else None

    def changed_rows():
        for change in snapshot.changes_since(source_identity):
            for which in ('retired', 'prepared'):
                table = snapshot.changed_sources(change, which=which, max_ordered_bytes=max_ordered_bytes)
                for batch in table.iter_batches(columns=['source_id', 'source_url']):
                    yield from batch.to_pylist()

    counts = snapshot.selection['counts']
    info = dict(catalog_id=snapshot.schemas['filenames'].metadata[b'catalog_id'].decode(),
                rows=counts['source_rows'], entries=counts['document_rows'])
    return index_selected_recoveries(info, snapshot.identity,
        CatalogRecoverySources(snapshot, max_ordered_bytes=max_ordered_bytes), rows,
        previous=previous, previous_identity=source_identity,
        changed_sources=changed_rows() if previous is not None else (), metrics=metrics)


def _alias(original, sources, accepted, accepted_targets):
    """Apply the existing all-observations ambiguity and saved-response policy."""
    if original in accepted:
        return None
    candidates, saved = set(), False
    for row in sources.at_url(original):
        saved |= saved_response(row)
        candidates.update(json.dumps(value, ensure_ascii=False) for value in resolution_candidates(row))
        if saved or len(candidates) > 1:
            return None
    if saved or len(candidates) != 1:
        return None
    target = json.loads(next(iter(candidates)))
    if not isinstance(target, str) or target == original or allowed_url(target) != target:
        return None
    bodies = {}
    # The lookup preserves source order, including last-observation kind policy.
    for row in sources.at_url(target):
        body = row.get('body_key')
        if saved_response(row) and valid_body(body):
            bodies[body] = content_kind(row)
            if len(bodies) > 1:
                return None
    bodies.update(accepted_targets.get(target, {}))
    if len(bodies) != 1:
        return None
    body, kind = next(iter(bodies.items()))
    return dict(original_url=original, recovered_url=target, body_key=body, kind=kind,
                recovery_status='recovered', recovery_basis='resolved_source_url')


def _size(value):
    return sum(len(part.encode()) for part in
               json.JSONEncoder(sort_keys=True, separators=(',', ':')).iterencode(value))


def index_selected_recoveries(info, source_identity, sources, rows, *, previous=None,
                              previous_identity=None, changed_sources=(), metrics=None):
    """Return bounded status metadata with stable source and document IDs.

    ``sources`` supplies ordered ``at_url`` rows and reverse ``targeting`` rows.
    ``urls`` is enumerated only for initial adoption. The caller binds previous
    status to its exact catalog and supplies every old/new changed source row
    from the catalog's immutable change chain. No source values are modified.
    """
    accepted = accepted_rows(rows)
    old_accepted, aliases, mappings = {}, {}, {}
    if previous is not None:
        if (previous.get('version') != 2 or previous_identity is None
                or previous.get('source_identity') != previous_identity):
            raise ValueError('Previous recovery status has a different catalog basis')
        if _size(previous) > OUTPUT_BYTES:
            raise ValueError('Previous recovery status exceeds the output budget')
        old_accepted = {row['original_url']: row for row in accepted_rows(previous['accepted'])}
        aliases = {row['original_url']: row for row in previous['recoveries']
                   if row['recovery_basis'] == 'resolved_source_url'}
        for source, document, match in previous['sources']:
            if source in mappings or type(match) is not int or not 0 <= match < len(previous['recoveries']):
                raise ValueError('Previous recovery source ownership is invalid')
            mappings[source] = (document, previous['recoveries'][match]['original_url'])
    elif previous_identity is not None:
        raise ValueError('A previous catalog basis requires its recovery status')
    current_accepted = {row['original_url']: row for row in accepted}
    accepted_targets = {}
    for row in accepted:
        if row['kind'] != 'video':
            for url in (row['original_url'], row['recovered_url']):
                accepted_targets.setdefault(url, {})[row['body_key']] = row['kind']
    urls, changed_ids = set(), set()
    for original in old_accepted.keys() | current_accepted.keys():
        if old_accepted.get(original) != current_accepted.get(original):
            urls.add(original)
            urls.update(row['recovered_url'] for row in
                        (old_accepted.get(original), current_accepted.get(original)) if row)
    for row in changed_sources:
        changed_ids.add(row['source_id'])
        if row.get('source_url'):
            urls.add(row['source_url'])
    if previous is None:
        urls.update(sources.urls())
    affected = set(urls)
    # Old successful aliases supply removed reverse links; current memberships
    # also find formerly ambiguous aliases that have become resolvable.
    affected.update(original for original, row in aliases.items() if row['recovered_url'] in urls)
    for url in sorted(urls):
        affected.update(row['source_url'] for row in sources.targeting(url) if row.get('source_url'))
    alias_bytes = sum(_size(row) + 1 for row in aliases.values())
    accepted_bytes = _size(accepted)
    for original in sorted(affected):
        removed = aliases.pop(original, None)
        if removed is not None:
            alias_bytes -= _size(removed) + 1
        row = _alias(original, sources, current_accepted, accepted_targets)
        if row is not None:
            aliases[original] = row
            alias_bytes += _size(row) + 1
            if alias_bytes + accepted_bytes > OUTPUT_BYTES:
                raise ValueError('Recovery status exceeds the output budget')
    recoveries = accepted + [aliases[url] for url in sorted(aliases) if url not in current_accepted]
    positions = {row['original_url']: i for i, row in enumerate(recoveries)}
    retained = {(row['recovered_url'], row['body_key']): row['original_url'] for row in accepted}
    mappings = {source: (document, original) for source, (document, original) in mappings.items()
                if source not in changed_ids and original in positions}
    mapping_bytes = sum(_size([source, document, positions[original]]) + 1
                        for source, (document, original) in mappings.items())
    recovery_bytes = _size(recoveries)
    for url in sorted(affected):
        for row in sources.at_url(url):
            source, document = row.get('source_id'), row.get('document_id')
            if not isinstance(source, str) or not source or not isinstance(document, str) or not document:
                raise ValueError('Recovery row lacks stable source/document ownership')
            prior = mappings.pop(source, None)
            if prior is not None:
                mapping_bytes -= _size([source, prior[0], positions[prior[1]]]) + 1
            original = url if url in positions else retained.get((url, row.get('body_key')))
            if original is not None:
                mappings[source] = (document, original)
                mapping_bytes += _size([source, document, positions[original]]) + 1
                if mapping_bytes + recovery_bytes > OUTPUT_BYTES:
                    raise ValueError('Recovery status exceeds the output budget')
    if len(mappings) > info['rows']:
        raise ValueError('Recovery source ownership exceeds the selected catalog')
    matched_groups, source_pairs = {}, []
    for source, (document, original) in sorted(mappings.items()):
        match = positions[original]
        source_pairs.append([source, document, match])
        matched_groups.setdefault(document, set()).add(match)
    if len(matched_groups) > info['entries']:
        raise ValueError('Recovery document ownership exceeds the selected catalog')
    result = dict(version=2, source_identity=source_identity, **{
        name: info[name] for name in ('catalog_id', 'rows', 'entries')},
        accepted=accepted, recoveries=recoveries, sources=source_pairs,
        groups=[[document, sorted(matches)] for document, matches in sorted(matched_groups.items())])
    size = _size(result)
    if size > OUTPUT_BYTES:
        raise ValueError('Recovery status exceeds the output budget')
    if metrics is not None:
        metrics.update(affected_urls=len(affected), changed_source_ids=len(changed_ids),
                       exact_output_bytes=size, initial_url_enumeration=previous is None)
    return result
