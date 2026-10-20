"""Retain receipt interpretation ownership with the exact catalog selection."""
import base64
from hashlib import sha256
from pathlib import Path

import pyarrow as pa

from .immutable_metadata import MetadataObjects, encoded


def source_update_requirements():
    from . import source_inputs, source_observations, source_replay, document_index, source_capture_inputs, document_recovery, catalog_availability, capture_metadata
    digest = sha256()
    for module in (source_inputs, source_observations, source_replay, document_index, source_capture_inputs, document_recovery, catalog_availability, capture_metadata):
        digest.update(Path(module.__file__).read_bytes())
    for path in (Path(__file__), Path(__file__).with_name('catalog_raw_updates.py')):
        digest.update(path.read_bytes())
    return dict(implementation_sha256=digest.hexdigest(), format='retained-source-update-v1', pyarrow=pa.__version__)


def _digest(row, schema):
    fields = pa.schema([field for field in schema if field.name not in {'source_id', 'document_id'}])
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, fields) as writer:
        writer.write_table(pa.Table.from_pylist([row], schema=fields))
    return sha256(sink.getvalue().to_pybytes()).hexdigest()


def retain_source_update(store, *, base, before, after, schema, replacements, deletions, observations=()):
    pages = MetadataObjects(store, 'source-update-rows-v1', max_cache_entries=4)
    head, pending, count = None, [], 0
    from .document_index import source_identity
    for row in replacements:
        pending.append(dict(source_id=source_identity(row), digest=_digest(row, schema)))
        count += 1
        if len(pending) == 64:
            head = pages.put(dict(previous=head, rows=pending))
            pending = []
    if pending:
        head = pages.put(dict(previous=head, rows=pending))
    observation_head, observation_count, pending = None, 0, []
    for observation in observations:
        pending.append(observation)
        observation_count += 1
        if len(pending) == 64:
            observation_head = pages.put(dict(previous=observation_head, observations=pending))
            pending = []
    if pending:
        observation_head = pages.put(dict(previous=observation_head, observations=pending))
    body = dict(version=1, base=base, before=before, after=after,
        schema=base64.b64encode(schema.serialize().to_pybytes()).decode(),
        rows=dict(head=head, count=count), observations=dict(head=observation_head, count=observation_count),
        deletions=sorted(deletions), requirements=source_update_requirements())
    body['binding'] = sha256(encoded(body)).hexdigest()
    return MetadataObjects(store, 'source-updates-v1', max_cache_entries=1).put(body)


def read_source_update(store, reference):
    body = MetadataObjects(store, 'source-updates-v1', max_cache_entries=1).read(reference)
    if (body.get('version') != 1 or body.get('requirements') != source_update_requirements()
            or body.get('binding') != sha256(encoded({k: v for k, v in body.items() if k != 'binding'})).hexdigest()):
        raise ValueError('Retained source update proof or requirements differ')
    return body


def verify_source_update(store, reference, *, native, base, before, rows, deletions):
    body = read_source_update(store, reference)
    if body['base'] != base or body['before'] != before or set(body['deletions']) != set(deletions):
        raise ValueError('Retained source update differs from its catalog basis/deletions')
    _verify_routing(store, native, body)
    schema = pa.ipc.read_schema(pa.BufferReader(base64.b64decode(body['schema'], validate=True)))
    wanted, head, count, seen = {}, body['rows']['head'], 0, set()
    pages = MetadataObjects(store, 'source-update-rows-v1', max_cache_entries=4)
    while head is not None:
        if head['sha256'] in seen:
            raise ValueError('Retained source update row pages contain a cycle')
        seen.add(head['sha256'])
        page = pages.read(head)
        if not 0 < len(page['rows']) <= 64:
            raise ValueError('Invalid source update page size')
        for entry in page['rows']:
            if entry['source_id'] in wanted:
                raise ValueError('Repeated retained source update identity')
            wanted[entry['source_id']] = entry['digest']
            count += 1
        head = page['previous']
    if count != body['rows']['count']:
        raise ValueError('Retained source update row count differs')
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
    from contextlib import closing
    import json
    from tempfile import TemporaryDirectory
    from .catalog_staging import WorkingCatalog
    from .source_observations import SourceObservationStorage, SourceObservationTrace, receipt_locator
    after, before = body['after'], body['before']
    owner = SourceObservationStorage(native=native, store=store, namespace=after['namespace'],
        max_rows=after['max_rows'], max_bytes=after['max_bytes'])
    pages = MetadataObjects(store, 'source-update-rows-v1', max_cache_entries=4)
    head, count, seen = body['observations']['head'], 0, set()
    with TemporaryDirectory(prefix='source-update-routing-') as directory, closing(WorkingCatalog(Path(directory) / 'proof.sqlite')) as work:
        trace = SourceObservationTrace(work)
        while head is not None:
            if head['sha256'] in seen:
                raise ValueError('Source update observation pages contain a cycle')
            seen.add(head['sha256'])
            page = pages.read(head)
            if not 0 < len(page['observations']) <= 64:
                raise ValueError('Invalid source update observation page')
            for observation in page['observations']:
                key, line = receipt_locator(observation)
                if work.connection.execute('SELECT 1 FROM observation_inputs WHERE observation=?', (observation,)).fetchone():
                    raise ValueError('Repeated source update observation')
                trace.register(key, line)
                count += 1
                for edge in owner.members.values(after['root'], observation):
                    dependency, access = json.loads(edge)
                    kind, value = json.loads(dependency[len('dependency:'):])
                    trace(dict(receipt_key=key, receipt_line=line, kind=kind, value=value, access=access))
            head = page['previous']
        if count != body['observations']['count']:
            raise ValueError('Source update observation count differs')
        if owner.prepare(before['root'] if before else None, trace) != after['root']:
            raise ValueError('Source update changed unrelated observation routing')
