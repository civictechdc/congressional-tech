"""Qualify exact existing catalog values before selecting native storage."""
import base64
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq

from .catalog_batches import CatalogComponentReader, iterator_prepared_components, prepare_native_catalog_components
from .catalog_partitions import CatalogTable
from .catalog_scope import _component_pages, catalog_scope_requirements
from .catalog_validation import catalog_reference_requirements
from .immutable_metadata import MetadataObjects, encoded
from .derived_files import VerifiedFile, check_identity, file_identity


def adoption_requirements():
    return dict(validator='catalog-native-adoption-v1',
                implementation_sha256=sha256(Path(__file__).read_bytes() + Path(__file__).with_name('catalog_rows.py').read_bytes()).hexdigest())


def _save_preparation(path, request, dependency=None):
    """Retain one completed preparation result, never native operation state."""
    value = dict(request=request, dependency=dependency)
    value['binding'] = sha256(encoded(value)).hexdigest()
    staging = path.with_suffix('.tmp')
    staging.write_bytes(encoded(value))
    staging.replace(path)


def ordered_chunks(file, *, max_rows, max_bytes):
    from .catalog_rows import core_table, row_bytes
    schema = file.schema_arrow.append(pa.field('_catalog_order', pa.int64(), nullable=False))
    pending, rows, size, physical_total, offset = [], 0, 0, 0, 0
    def table():
        values = pa.Table.from_batches(pending, schema=file.schema_arrow).combine_chunks()
        return pa.Table.from_arrays([*values.columns, pa.array(range(offset, offset + rows), type=pa.int64())], schema=schema)
    for batch in file.iter_batches(batch_size=min(max_rows,128)):
        physical=core_table(pa.Table.from_batches([batch]))
        physical_sizes=row_bytes(physical.to_batches()[0])
        logical_sizes=row_bytes(batch)
        start=0
        for i,(physical_size,logical_size)in enumerate(zip(physical_sizes,logical_sizes)):
            physical_size+=8;logical_size+=8
            if physical_size>max_bytes:
                raise ValueError('One selected catalog row exceeds its native adoption budget')
            if pending or i>start:
                if rows==max_rows or size+logical_size>max_bytes or physical_total+physical_size>max_bytes:
                    if i>start:pending.append(batch.slice(start,i-start))
                    yield table()
                    offset+=rows;pending=[];rows=size=physical_total=0;start=i
            rows+=1;size+=logical_size;physical_total+=physical_size
        if len(batch)>start:pending.append(batch.slice(start))
    if pending:yield table()


def _hash_table(digest, table):
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    payload = sink.getvalue().to_pybytes()
    digest.update(len(payload).to_bytes(8, 'big'))
    digest.update(payload)


def qualify_adoption_readback(store, native, prepared, files, *, max_bytes):
    """Compare every logical native value and saved position against old files."""
    reader = CatalogComponentReader(store, requirements=catalog_reference_requirements())
    with TemporaryDirectory(prefix='catalog-adoption-readback-') as directory, closing(
            sqlite3.connect(Path(directory) / 'chunks.sqlite')) as db:
        db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192; '
            'CREATE TABLE chunks(label TEXT,name TEXT,first_order INTEGER,reference TEXT,PRIMARY KEY(label,name));')
        for _, reference in iterator_prepared_components(store, prepared):
            page = reader.page(reference['page'])
            component = page['components'][reference['component']]
            for label in ('filenames', 'documents'):
                for view in component['tables'][label]['chunks']:
                    pin = page['chunks'][view['name']]
                    physical = reader.chunks.read(pin)
                    db.execute('INSERT OR IGNORE INTO chunks VALUES (?,?,?,?)',
                        (label, view['name'], physical['order_min'], json.dumps(pin)))
        result = {}
        for label in ('filenames', 'documents'):
            file = files[label]
            old_batches = iter(file.iter_batches(batch_size=1))
            pending, position, total = None, 0, 0
            digest, mapping = sha256(), sha256()
            for name, reference in db.execute('SELECT name,reference FROM chunks WHERE label=? ORDER BY first_order,name', (label,)):
                physical = reader.chunks.read(json.loads(reference))
                count = physical['release']['dataset']['groups']['source']['rows']
                parts, remaining = [], count
                while remaining:
                    if pending is None or position == len(pending):
                        pending, position = next(old_batches, None), 0
                    if pending is None:
                        raise ValueError('Adoption native rows exceed the selected file')
                    take = min(remaining, len(pending) - position)
                    parts.append(pending.slice(position, take))
                    remaining, position = remaining - take, position + take
                expected = pa.Table.from_batches(parts, schema=file.schema_arrow).combine_chunks()
                physical_schema = file.schema_arrow.append(pa.field('_catalog_order', pa.int64(), nullable=False))
                table = CatalogTable(physical_schema, [(name, physical['release'])], native=native, store=store)
                observed = pa.Table.from_batches(list(table.iter_batches())).combine_chunks()
                ordinals = observed['_catalog_order'].to_pylist()
                actual = observed.sort_by('_catalog_order').drop(['_catalog_order'])
                if (physical['order_min'] != total or physical['order_max'] != total + count - 1
                        or any(type(value) is not int for value in ordinals)
                        or sorted(ordinals) != list(range(total, total + count))
                        or not actual.equals(expected, check_metadata=True)):
                    raise ValueError('Adoption changed selected values, IDs, mappings or row order')
                _hash_table(digest, actual)
                keys = ['source_id', 'document_id'] if label == 'filenames' else ['document_id']
                _hash_table(mapping, actual.select(keys))
                total += count
            if total != file.metadata.num_rows or (pending is not None and position < len(pending)) or next(old_batches, None) is not None:
                raise ValueError('Adoption omitted selected source or document rows')
            result[label] = dict(rows=total, all_fields_sha256=digest.hexdigest(),
                                 ordered_ids_sha256=mapping.hexdigest())
        return result


def read_adoption_proof(store, reference, *, previous, scope_reference, scope):
    proof = MetadataObjects(store, 'catalog-adoption-v1', max_cache_entries=1).read(reference)
    binding = proof.get('binding')
    if (proof.get('version') != 1 or proof.get('requirements') != adoption_requirements()
            or binding != sha256(encoded({k: v for k, v in proof.items() if k != 'binding'})).hexdigest()
            or proof.get('base') != previous.identity or proof.get('files') != previous.files
            or proof.get('scope_reference') != scope_reference or proof.get('schemas') != scope['schemas']
            or proof.get('dependency_after') != scope['dependency_after']
            or scope['dependency_before'] is not None or scope['retired']['count'] != 0):
        raise ValueError('Native adoption proof differs from the exact selected file basis')
    for label, count in [('filenames', 'source'), ('documents', 'document')]:
        evidence = proof['readback'][label]
        with pq.ParquetFile(previous.filenames_path if label == 'filenames' else previous.documents_path) as old:
            old_count = old.metadata.num_rows
            old_schema = base64.b64encode(old.schema_arrow.serialize().to_pybytes()).decode()
        if (evidence['rows'] != old_count or proof['schemas'][label] != old_schema
                or evidence['rows'] != scope['counts']['prepared_' + count + '_rows']
                or any(not isinstance(evidence.get(name), str) or len(evidence[name]) != 64
                       for name in ('all_fields_sha256', 'ordered_ids_sha256'))):
            raise ValueError('Native adoption completeness or mapping proof differs')
    return proof


def adopt_native_catalog(store, *, native, previous, dependencies, candidate, directory,
                         max_chunk_rows, max_chunk_bytes, rules):
    """Preserve the exact existing pair; no grouping or classification replay."""
    from .catalog_selection import NativeCatalogSnapshot, publish_native_catalog
    if not isinstance(candidate, str) or not candidate or not isinstance(rules, dict) or not rules:
        raise ValueError('Native adoption requires a candidate and explicit preserved interpretation rules')
    if type(max_chunk_rows) is not int or max_chunk_rows < 1 or type(max_chunk_bytes) is not int or max_chunk_bytes < 1:
        raise ValueError('Native adoption requires positive chunk budgets')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    checkpoint = directory / 'qualified-adoption.json'
    inputs = dict(candidate=candidate, max_chunk_rows=max_chunk_rows, max_chunk_bytes=max_chunk_bytes, rules=rules)
    native_files = {str(Path(path).resolve()): file_identity(path)
                    for path in native.execution_files()} if hasattr(native, 'execution_files') else {}
    def native_settings():
        return dict(workspace=str(Path(native.workspace).resolve()) if hasattr(native, 'workspace') else None,
                    timeout=getattr(native, 'timeout', None))
    settings = native_settings()
    inputs.update(native_execution=dict(files=native_files, **settings),
        dependency_basis=dependencies._selection(None),
        dependency_schema=base64.b64encode(dependencies.source_schema.serialize()).decode(),
        requirements=dict(adoption=adoption_requirements(), scope=catalog_scope_requirements(),
            references=catalog_reference_requirements(),
            dependencies=sha256(b''.join(Path(__file__).with_name(name).read_bytes() for name in (
                'catalog_dependency_storage.py', 'catalog_dependencies.py', 'catalog_memberships.py',
                'partition_routing.py', 'document_index.py'))).hexdigest()))

    def require_runtime():
        current_files = tuple(str(Path(path).resolve()) for path in native.execution_files()) if hasattr(native, 'execution_files') else ()
        if native_settings() != settings or current_files != tuple(native_files):
            raise ValueError('Native adoption continuation runtime changed')
        for path, identity in native_files.items():
            identity.require(path)

    input_files = {}
    if not isinstance(previous, NativeCatalogSnapshot):
        for label, path in [('filenames', previous.filenames_path), ('documents', previous.documents_path)]:
            if path is not None:
                identity = previous.files[label]
                actual = identity.require(path) if isinstance(identity, VerifiedFile) else file_identity(path)
                check_identity(actual, identity, label)
                input_files[str(path)] = actual

    def require_inputs():
        require_runtime()
        for path, identity in input_files.items():
            identity.require(path)

    retained = json.loads(checkpoint.read_bytes()) if checkpoint.exists() else None
    if retained is not None:
        if retained['inputs'] != inputs:
            raise ValueError('Native adoption continuation inputs differ')
        require_inputs()
        if isinstance(previous, NativeCatalogSnapshot):
            if previous.selection.get('adoption') != retained['adoption_reference']:
                raise ValueError('Native adoption continuation selected another result')
            return dict(unchanged=True, selection=previous.identity['selected_ref'], counts=previous.selection['counts'],
                        scope_reference=retained['scope_reference'], adoption_reference=retained['adoption_reference'])
        return dict(publish_native_catalog(store, retained['scope_reference'], previous=previous,
                                          adoption_reference=retained['adoption_reference']),
                    scope_reference=retained['scope_reference'], adoption_reference=retained['adoption_reference'])
    if isinstance(previous, NativeCatalogSnapshot) or not previous.files:
        raise ValueError('Explicit adoption requires an existing file catalog')
    with pq.ParquetFile(previous.filenames_path) as sources, pq.ParquetFile(previous.documents_path) as documents:
        schemas = dict(filenames=sources.schema_arrow, documents=documents.schema_arrow)
        files = dict(filenames=sources, documents=documents)
        if not schemas['filenames'].equals(dependencies.source_schema, check_metadata=True):
            raise ValueError('Native adoption dependency schema differs from selected files')
        schema_text = {key: base64.b64encode(schema.serialize()).decode() for key, schema in schemas.items()}
        request = dict(version=1, inputs=inputs, base=previous.identity, files=previous.files, schemas=schema_text)
        preparation = directory / 'preparation-request.json'
        dependency = None
        if preparation.exists():
            saved = json.loads(preparation.read_bytes())
            binding = saved.pop('binding', None)
            if binding != sha256(encoded(saved)).hexdigest() or saved.get('request') != request:
                raise ValueError('Native adoption continuation inputs or preparation differ')
            dependency = saved['dependency']
        else:
            _save_preparation(preparation, request)
        require_inputs()
        if dependency is None:
            dependency = dependencies.adopt(chunk.drop(['_catalog_order']) for chunk in ordered_chunks(
                sources, max_rows=max_chunk_rows, max_bytes=max_chunk_bytes))
            require_inputs()
            _save_preparation(preparation, request, dependency)
        prepared = prepare_native_catalog_components(store, native, candidate=candidate,
            source_chunks=ordered_chunks(sources, max_rows=max_chunk_rows, max_bytes=max_chunk_bytes),
            document_chunks=ordered_chunks(documents, max_rows=max_chunk_rows, max_bytes=max_chunk_bytes),
            source_schema=schemas['filenames'], document_schema=schemas['documents'],
            max_chunk_rows=max_chunk_rows, max_chunk_bytes=max_chunk_bytes,
            checkpoint_directory=directory / 'prepared-chunks')
        require_inputs()
        readback = qualify_adoption_readback(store, native, prepared, files, max_bytes=max_chunk_bytes)
        body = dict(version=1, base=previous.identity, dependency_before=None, dependency_after=dependency,
            candidate=candidate, schemas=schema_text,
            retired=dict(head=None, count=0), prepared=_component_pages(store, iterator_prepared_components(store, prepared)),
            counts=dict(retired_source_rows=0, retired_document_rows=0,
                prepared_source_rows=sources.metadata.num_rows, prepared_document_rows=documents.metadata.num_rows),
            rules=rules, mapping=None, requirements=catalog_scope_requirements())
        body['binding'] = sha256(encoded(body)).hexdigest()
        scope_reference = MetadataObjects(store, 'catalog-scope-proofs-v1').put(body)
        proof = dict(version=1, base=previous.identity, files=previous.files, scope_reference=scope_reference,
            schemas=body['schemas'], dependency_after=dependency, readback=readback,
            requirements=adoption_requirements())
        proof['binding'] = sha256(encoded(proof)).hexdigest()
        adoption_reference = MetadataObjects(store, 'catalog-adoption-v1').put(proof)
        pending = directory / 'qualified-adoption.tmp'
        require_inputs()
        pending.write_bytes(encoded(dict(inputs=inputs, scope_reference=scope_reference,
                                         adoption_reference=adoption_reference)))
        pending.replace(checkpoint)
        require_inputs()
        return dict(publish_native_catalog(store, scope_reference, previous=previous,
                                          adoption_reference=adoption_reference),
                    scope_reference=scope_reference, adoption_reference=adoption_reference)
