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


def selected_body_coverage(previous, dependencies, expected_bodies):
    """Verify specific already selected bodies through the non-grouping index."""
    expected = sorted(set(expected_bodies))
    basis = previous.selection['dependency'] if isinstance(previous, NativeCatalogSnapshot) else None
    for body in expected:
        source = next(iter(dependencies.sources_at_body(basis, body)), None)
        if source is None or source['source_values'].get('body_key') != body:
            raise ValueError('Selected catalog omits an expected retained body')
    return dict(expected_count=len(expected), expected_sha256=sha256(encoded(expected)).hexdigest(),
                selected_count=len(expected), selected_identity=deepcopy(previous.identity),
                basis='selected-body-lookup-v1')


def update_native_catalog(store, *, native, previous, dependencies, replacements=(), deletions=(),
                          candidate, directory, max_chunk_rows, max_chunk_bytes, rules, expected_bodies=(), source_update=None):
    """Replace complete interpreted rows; preserve untouched components and pins.

    Raw receipt interpretation supplies complete replacements/deletions here.
    This function owns grouping and publication, not source acquisition or
    interpretation policy. The returned scope_reference is durable evidence for
    retry/continuation and is bound to the exact prior application selection.
    """
    expected_bodies = sorted(set(expected_bodies))
    if any(not isinstance(body, str) or not body for body in expected_bodies):
        raise ValueError('Expected catalog body identities must be nonempty strings')
    native_previous = isinstance(previous, NativeCatalogSnapshot)
    if not native_previous and (previous.manifest is not None or previous.files):
        raise ValueError('Native catalog update requires explicit prior adoption')
    replacements, deletions = list(replacements), tuple(deletions)
    if not replacements and not deletions and source_update is None:
        coverage = selected_body_coverage(previous, dependencies, expected_bodies)
        return dict(unchanged=True, body_coverage=coverage, selected_identity=deepcopy(previous.identity), selection=deepcopy(previous.identity['selected_ref']),
                    counts=deepcopy(previous.selection['counts']) if native_previous else dict(source_rows=0, document_rows=0))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    checkpoint = directory / 'prepared-scope.json'
    input_hash = sha256()
    for row in replacements:
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, dependencies.source_schema.remove_metadata()) as writer:
            writer.write_table(pa.Table.from_pylist([row], schema=dependencies.source_schema.remove_metadata()))
        payload = sink.getvalue().to_pybytes()
        input_hash.update(len(payload).to_bytes(8, 'big'))
        input_hash.update(payload)
    input_digest = input_hash.hexdigest()
    request = dict(candidate=candidate, rules=rules, replacements_sha256=input_digest,
                   deletions=sorted(deletions), max_chunk_rows=max_chunk_rows,
                   max_chunk_bytes=max_chunk_bytes, expected_bodies=expected_bodies, source_update=source_update)
    def receipt(result, reference, proof):
        result = dict(result, scope_reference=reference, body_coverage=proof['body_coverage'])
        result['selected_identity'] = dict(selected_ref=result['selection'],
            selector_sha256=sha256(encoded(dict(version=2, selection=result['selection']))).hexdigest())
        return result
    if checkpoint.exists():
        retained = json.loads(checkpoint.read_bytes())
        if retained['request'] != request:
            raise ValueError('Catalog continuation inputs differ from the retained candidate')
        reference = retained['scope_reference']
        proof = read_catalog_scope(store, reference, requirements=catalog_scope_requirements())
        if native_previous and previous.selection['scope'] == reference:
            return receipt(dict(unchanged=True, selection=previous.identity['selected_ref'],
                        counts=previous.selection['counts']), reference, proof)
        if proof['base'] != previous.identity:
            raise ValueError('Catalog continuation base changed')
        result = publish_native_catalog(store, reference, previous=previous)
        return receipt(dict(result, unchanged=False), reference, proof)
    basis = previous.selection['dependency'] if native_previous else None
    selected = dependencies.selected(basis)
    scope = affected_sources(selected, replacements=replacements, deletions=deletions)
    orders = {key: selected.order(key) for key in scope.before}
    ordinal = basis['next_source_order'] if basis is not None else 0
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
            component_lookup=previous.component_ref if native_previous else lambda key: None,
            prepared_components=iterator_prepared_components(store, components),
            read_component=CatalogComponentReader(store).read,
            read_new_component=CatalogComponentReader(store, requirements=catalog_reference_requirements()).read,
            rules=rules, expected_bodies=expected_bodies, source_update=source_update,
            interpretation_before=previous.selection.get('interpretation') if native_previous else None)
        payload = encoded(dict(request=request, scope_reference=reference))
        staging = directory / 'prepared-scope.tmp'
        staging.write_bytes(payload)
        staging.replace(checkpoint)
    result = publish_native_catalog(store, reference, previous=previous)
    return receipt(dict(result, unchanged=False), reference, read_catalog_scope(store, reference))
