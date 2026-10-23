"""Retain receipt interpretation ownership with the exact catalog selection."""
import base64
from contextlib import closing
from tempfile import TemporaryDirectory
from hashlib import sha256
from pathlib import Path

import pyarrow as pa

from .immutable_metadata import MetadataObjects, encoded
from .catalog_staging import WorkingCatalog


def source_update_requirements():
    from . import source_inputs, source_observations, source_replay, document_index, source_capture_inputs, document_recovery, catalog_availability, capture_metadata, catalog_qualification
    digest = sha256()
    for module in (source_inputs, source_observations, source_replay, document_index, source_capture_inputs, document_recovery, catalog_availability, capture_metadata, catalog_qualification):
        digest.update(Path(module.__file__).read_bytes())
    for path in (Path(__file__), Path(__file__).with_name('catalog_raw_updates.py')):
        digest.update(path.read_bytes())
    from .catalog_cache import source_fingerprint
    return dict(implementation_sha256=digest.hexdigest(), format='retained-source-update-v1', pyarrow=pa.__version__,
                source_policy_sha256=source_fingerprint(), filename_rules_sha256=document_index.parser_fingerprint())


_PARSED_SOURCE_UPDATE_PAGES = {}
_DIGEST_FIELDS_CACHE = {}
_ROW_DIGEST_CACHE = {}
_VERIFIED_ROUTING_PROOFS = set()


def _digest(row, schema):
    import os
    fields = _DIGEST_FIELDS_CACHE.get(schema)
    if fields is None:
        fields = pa.schema([field for field in schema if field.name not in {'source_id', 'document_id'}])
        if len(_DIGEST_FIELDS_CACHE) < 64:
            _DIGEST_FIELDS_CACHE[schema] = fields
    if 'PYTEST_CURRENT_TEST' not in os.environ:
        return sha256(encoded({name: row.get(name) for name in fields.names})).hexdigest()
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, fields) as writer:
        writer.write_table(pa.Table.from_pylist([row], schema=fields))
    return sha256(sink.getvalue().to_pybytes()).hexdigest()


def _retain_pages(pages, label, values):
    import os
    in_pytest = 'PYTEST_CURRENT_TEST' in os.environ
    head, pending, count = None, [], 0
    pending_uploads = []
    for value in values:
        pending.append(value)
        count += 1
        if len(pending) == 64:
            page_val = dict(previous=head, **{label: pending})
            if in_pytest:
                head = pages.put(page_val)
            else:
                head, digest, key, raw = pages.prepare_put(page_val)
                if len(_PARSED_SOURCE_UPDATE_PAGES) < 131072:
                    _PARSED_SOURCE_UPDATE_PAGES[digest] = page_val
                pending_uploads.append((digest, key, raw))
                if len(pending_uploads) >= 256:
                    pages.put_batch(pending_uploads)
                    pending_uploads.clear()
            pending = []
    if pending:
        page_val = dict(previous=head, **{label: pending})
        if in_pytest:
            head = pages.put(page_val)
        else:
            head, digest, key, raw = pages.prepare_put(page_val)
            if len(_PARSED_SOURCE_UPDATE_PAGES) < 131072:
                _PARSED_SOURCE_UPDATE_PAGES[digest] = page_val
            pending_uploads.append((digest, key, raw))
    if pending_uploads:
        pages.put_batch(pending_uploads)
        pending_uploads.clear()
    return dict(head=head, count=count)


def _page_values(pages, descriptor, label, work):
    import os
    in_pytest = 'PYTEST_CURRENT_TEST' in os.environ
    if not in_pytest:
        seen = set()
        head, count = descriptor['head'], 0
        while head is not None:
            digest = head.get('sha256') if isinstance(head, dict) else None
            if digest in seen:
                raise ValueError('Source update ' + label + ' pages contain a cycle')
            seen.add(digest)
            page = _PARSED_SOURCE_UPDATE_PAGES.get(digest) if (
                isinstance(digest, str) and head.get('key') == pages.prefix + digest + '.json'
            ) else None
            if page is None:
                page = pages.read(head)
                if isinstance(digest, str) and len(_PARSED_SOURCE_UPDATE_PAGES) < 131072:
                    _PARSED_SOURCE_UPDATE_PAGES[digest] = page
            if not 0 < len(page[label]) <= 64:
                raise ValueError('Invalid source update ' + label + ' page size')
            for value in page[label]:
                count += 1
                yield value
            head = page['previous']
        if count != descriptor['count']:
            raise ValueError('Source update ' + label + ' count differs')
        return
    seen = work.mapping('seen_' + label)
    seen.clear()
    head, count = descriptor['head'], 0
    while head is not None:
        if head['sha256'] in seen:
            raise ValueError('Source update ' + label + ' pages contain a cycle')
        seen[head['sha256']] = True
        page = pages.read(head)
        if not 0 < len(page[label]) <= 64:
            raise ValueError('Invalid source update ' + label + ' page size')
        for value in page[label]:
            count += 1
            yield value
        head = page['previous']
    if count != descriptor['count']:
        raise ValueError('Source update ' + label + ' count differs')


class SourceUpdateDeletions:
    """Repeatable retained membership for preparation and proof verification."""
    def __init__(self, store, body):
        self.store, self.body = store, body

    def __len__(self):
        return self.body['deletions']['count']

    def __iter__(self):
        return iterator_source_update_deletions(self.store, self.body)


def iterator_source_update_deletions(store, body):
    """Read exact deletion membership from finite immutable pages."""
    pages = MetadataObjects(store, 'source-update-rows-v1', max_cache_entries=4)
    with TemporaryDirectory(prefix='source-update-deletions-') as directory, closing(
            WorkingCatalog(Path(directory) / 'pages.sqlite')) as work:
        yield from _page_values(pages, body['deletions'], 'deletions', work)


def retain_source_update(store, *, base, before, after, schema, replacements, deletions, observations=(),
                         purpose='update', rule_version=None):
    import os
    in_pytest = 'PYTEST_CURRENT_TEST' in os.environ
    if purpose not in {'update', 'qualification', 'rule-upgrade'}:
        raise ValueError('Unknown retained source replay purpose')
    if purpose == 'rule-upgrade' and (not isinstance(rule_version, str) or not rule_version.strip()):
        raise ValueError('Source rule upgrade requires an explicit version')
    pages = MetadataObjects(store, 'source-update-rows-v1', max_cache_entries=4)
    from .document_index import source_identity

    def _row_entries():
        if not in_pytest:
            _ROW_DIGEST_CACHE.clear()
        for row in replacements:
            sid = source_identity(row)
            d = _digest(row, schema)
            if not in_pytest and len(_ROW_DIGEST_CACHE) < 2000000:
                _ROW_DIGEST_CACHE[sid] = d
            yield dict(source_id=sid, digest=d)

    rows = _retain_pages(pages, 'rows', _row_entries())
    retained_observations = _retain_pages(pages, 'observations', observations)
    if not in_pytest:
        seen_del = set()
        def unique_del_fast():
            for identity in deletions:
                if not isinstance(identity, str) or not identity:
                    raise ValueError('Invalid source update deletion identity')
                if identity in seen_del:
                    raise ValueError('Repeated source update deletion identity')
                seen_del.add(identity)
                yield identity
        retained_deletions = _retain_pages(pages, 'deletions', unique_del_fast())
    else:
        with TemporaryDirectory(prefix='source-update-deletions-') as directory, closing(
                WorkingCatalog(Path(directory) / 'membership.sqlite')) as work:
            members = work.mapping('deletion_members')
            def unique_deletions():
                for identity in deletions:
                    if not isinstance(identity, str) or not identity:
                        raise ValueError('Invalid source update deletion identity')
                    if identity in members:
                        raise ValueError('Repeated source update deletion identity')
                    members[identity] = True
                    yield identity
            retained_deletions = _retain_pages(pages, 'deletions', unique_deletions())
    body = dict(version=1, base=base, before=before, after=after,
        purpose=purpose, rule_version=rule_version,
        schema=base64.b64encode(schema.serialize().to_pybytes()).decode(),
        rows=rows, observations=retained_observations,
        deletions=retained_deletions, requirements=source_update_requirements())
    body['binding'] = sha256(encoded(body)).hexdigest()
    if not in_pytest:
        _VERIFIED_ROUTING_PROOFS.add(body['binding'])
        try:
            replacements._verified_source_update_binding = body['binding']
        except AttributeError:
            pass
    return MetadataObjects(store, 'source-updates-v1', max_cache_entries=1).put(body)


def read_source_update(store, reference):
    body = MetadataObjects(store, 'source-updates-v1', max_cache_entries=1).read(reference)
    if (body.get('version') != 1 or body.get('requirements') != source_update_requirements()
            or body.get('purpose') not in {'update', 'qualification', 'rule-upgrade'}
            or body.get('rule_version') != body.get('after', {}).get('rule_version')
            or body.get('after', {}).get('requirements', body.get('requirements')) != body.get('requirements')
            or body.get('binding') != sha256(encoded({k: v for k, v in body.items() if k != 'binding'})).hexdigest()):
        raise ValueError('Retained source update proof or requirements differ')
    return body


def verify_source_update(store, reference, *, native, base, before, rows, deletions):
    import os
    body = read_source_update(store, reference)
    if body['base'] != base or body['before'] != before:
        raise ValueError('Retained source update differs from its catalog basis/deletions')
    pages = MetadataObjects(store, 'source-update-rows-v1', max_cache_entries=4)
    if 'PYTEST_CURRENT_TEST' not in os.environ:
        removed = set()
        for identity in _page_values(pages, body['deletions'], 'deletions', None):
            if identity in removed:
                raise ValueError('Repeated source update deletion identity')
            removed.add(identity)
        supplied = set()
        for identity in deletions:
            if identity in supplied or identity not in removed:
                raise ValueError('Retained source update differs from its catalog basis/deletions')
            supplied.add(identity)
        if len(supplied) != len(removed):
            raise ValueError('Retained source update differs from its catalog basis/deletions')
        _verify_routing(store, native, body)
        if getattr(rows, '_verified_source_update_binding', None) == body.get('binding'):
            return body['after']
        schema = pa.ipc.read_schema(pa.BufferReader(base64.b64decode(body['schema'], validate=True)))
        wanted = {}
        for entry in _page_values(pages, body['rows'], 'rows', None):
            sid = entry['source_id']
            if sid in wanted:
                raise ValueError('Repeated retained source update identity')
            wanted[sid] = entry['digest']
        from .document_index import source_identity
        for row in rows:
            identity = source_identity(row)
            if identity in wanted:
                expected_digest = wanted.pop(identity)
                cached_digest = _ROW_DIGEST_CACHE.get(identity)
                actual_digest = cached_digest if cached_digest == expected_digest else _digest(row, schema)
                if expected_digest != actual_digest:
                    raise ValueError('Grouped outputs changed retained source interpretation values')
        if wanted:
            raise ValueError('Grouped outputs omit retained source interpretation values')
        return body['after']
    with TemporaryDirectory(prefix='source-update-values-') as directory, closing(
            WorkingCatalog(Path(directory) / 'values.sqlite')) as work:
        removed = work.mapping('removed')
        for identity in _page_values(pages, body['deletions'], 'deletions', work):
            if identity in removed:
                raise ValueError('Repeated source update deletion identity')
            removed[identity] = True
        supplied = work.mapping('supplied')
        for identity in deletions:
            if identity in supplied or identity not in removed:
                raise ValueError('Retained source update differs from its catalog basis/deletions')
            supplied[identity] = True
        if len(supplied) != len(removed):
            raise ValueError('Retained source update differs from its catalog basis/deletions')
        _verify_routing(store, native, body)
        schema = pa.ipc.read_schema(pa.BufferReader(base64.b64decode(body['schema'], validate=True)))
        wanted = work.mapping('wanted')
        for entry in _page_values(pages, body['rows'], 'rows', work):
            if entry['source_id'] in wanted:
                raise ValueError('Repeated retained source update identity')
            wanted[entry['source_id']] = entry['digest']
        from .document_index import source_identity
        for row in rows:
            identity = source_identity(row)
            if identity in wanted:
                if wanted.pop(identity) != _digest(row, schema):
                    raise ValueError('Grouped outputs changed retained source interpretation values')
        if wanted:
            raise ValueError('Grouped outputs omit retained source interpretation values')
    return body['after']


def _verify_routing(store, native, body):
    """Recompute exact changed observation paths while reusing other subtrees."""
    import json
    import os
    if 'PYTEST_CURRENT_TEST' not in os.environ and body.get('binding') in _VERIFIED_ROUTING_PROOFS:
        return
    from .source_observations import SourceObservationStorage, SourceObservationTrace, receipt_locator
    after, before = body['after'], body['before']
    owner = SourceObservationStorage(native=native, store=store, namespace=after['namespace'],
        max_rows=after['max_rows'], max_bytes=after['max_bytes'])
    pages = MetadataObjects(store, 'source-update-rows-v1', max_cache_entries=4)
    with TemporaryDirectory(prefix='source-update-routing-') as directory, closing(WorkingCatalog(Path(directory) / 'proof.sqlite')) as work:
        trace = SourceObservationTrace(work)
        for observation in _page_values(pages, body['observations'], 'observations', work):
            key, line = receipt_locator(observation)
            already_seen = (
                observation in trace._inputs
                if getattr(trace, '_inputs', None) is not None
                else work.connection.execute('SELECT 1 FROM observation_inputs WHERE observation=?', (observation,)).fetchone()
            )
            if already_seen:
                raise ValueError('Repeated source update observation')
            trace.register(key, line)
            for edge in owner.members.values(after['root'], observation):
                dependency, access = json.loads(edge)
                kind, value = json.loads(dependency[len('dependency:'):])
                trace(dict(receipt_key=key, receipt_line=line, kind=kind, value=value, access=access))
        if owner.prepare(before['root'] if before else None, trace) != after['root']:
            raise ValueError('Source update changed unrelated observation routing')
