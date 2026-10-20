"""Maintained closed-scope grouping and one coherent native catalog publication."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa

from . import document_index as index
from .catalog_batches import (
    CatalogComponentReader, iterator_prepared_components, prepare_native_catalog_components,
)
from .catalog_dependencies import affected_sources
from .catalog_scope import prepare_catalog_scope, verify_catalog_scope, read_catalog_scope, catalog_scope_requirements
from .immutable_metadata import encoded
from .catalog_selection import NativeCatalogSnapshot, publish_native_catalog
from .catalog_validation import catalog_reference_requirements


def update_native_catalog(store, *, native, previous, dependencies, replacements=(), deletions=(),
                          candidate, directory, max_chunk_rows, max_chunk_bytes, rules):
    """Replace complete interpreted rows; preserve untouched components and pins.

    Raw receipt interpretation supplies complete replacements/deletions here.
    This function owns grouping and publication, not source acquisition or
    interpretation policy. The returned scope_reference is durable evidence for
    retry/continuation and is bound to the exact prior application selection.
    """
    if not isinstance(previous, NativeCatalogSnapshot):
        raise ValueError('Native catalog update requires explicit prior adoption')
    replacements, deletions = list(replacements), tuple(deletions)
    if not replacements and not deletions:
        return dict(unchanged=True, selection=deepcopy(previous.identity['selected_ref']),
                    counts=deepcopy(previous.selection['counts']))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    checkpoint = directory / 'prepared-scope.json'
    input_hash = sha256()
    for row in replacements:
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, dependencies.source_schema) as writer:
            writer.write_table(pa.Table.from_pylist([row], schema=dependencies.source_schema))
        payload = sink.getvalue().to_pybytes()
        input_hash.update(len(payload).to_bytes(8, 'big'))
        input_hash.update(payload)
    input_digest = input_hash.hexdigest()
    request = dict(candidate=candidate, rules=rules, replacements_sha256=input_digest,
                   deletions=sorted(deletions), max_chunk_rows=max_chunk_rows,
                   max_chunk_bytes=max_chunk_bytes)
    if checkpoint.exists():
        retained = json.loads(checkpoint.read_bytes())
        if retained['request'] != request:
            raise ValueError('Catalog continuation inputs differ from the retained candidate')
        reference = retained['scope_reference']
        proof = read_catalog_scope(store, reference, requirements=catalog_scope_requirements())
        if previous.selection['scope'] == reference:
            return dict(unchanged=True, selection=previous.identity['selected_ref'],
                        counts=previous.selection['counts'], scope_reference=reference)
        if proof['base'] != previous.identity:
            raise ValueError('Catalog continuation base changed')
        result = publish_native_catalog(store, reference, previous=previous)
        return dict(result, scope_reference=reference, unchanged=False)
    basis = previous.selection['dependency']
    selected = dependencies.selected(basis)
    scope = affected_sources(selected, replacements=replacements, deletions=deletions)
    orders = {key: selected.order(key) for key in scope.before}
    ordinal = basis['next_source_order']
    for row in replacements:
        key = index.source_identity(row)
        if key not in orders:
            orders[key], ordinal = ordinal, ordinal + 1
    with TemporaryDirectory(prefix='catalog-grouped-', dir=directory) as group_directory:
        prepared = prepare_catalog_scope(Path(group_directory) / 'scope', scope, schema=dependencies.source_schema,
                                         source_orders=orders, candidate=candidate)
        after = dependencies.prepare(basis, replacements=prepared.source_values(), deletions=deletions,
                                     source_orders=orders)
        components = prepare_native_catalog_components(store, native, candidate=candidate,
            source_chunks=prepared.source_chunks(max_rows=max_chunk_rows, max_bytes=max_chunk_bytes),
            document_chunks=prepared.document_chunks(max_rows=max_chunk_rows, max_bytes=max_chunk_bytes),
            source_schema=prepared.source_schema, document_schema=prepared.document_schema,
            max_chunk_rows=max_chunk_rows, max_chunk_bytes=max_chunk_bytes)
        reference = verify_catalog_scope(store, dependencies=dependencies, dependency_before=basis,
            dependency_after=after, prepared=prepared, base=previous.identity,
            component_lookup=previous.component_ref,
            prepared_components=iterator_prepared_components(store, components),
            read_component=CatalogComponentReader(store).read,
            read_new_component=CatalogComponentReader(store, requirements=catalog_reference_requirements()).read,
            rules=rules)
        payload = encoded(dict(request=request, scope_reference=reference))
        staging = directory / 'prepared-scope.tmp'
        staging.write_bytes(payload)
        staging.replace(checkpoint)
    result = publish_native_catalog(store, reference, previous=previous)
    return dict(result, scope_reference=reference, unchanged=False)
