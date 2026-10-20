"""Maintained closed-scope grouping and one coherent native catalog publication."""
from copy import deepcopy
from contextlib import ExitStack, closing
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
from .catalog_inputs import CatalogKeys
from .catalog_staging import DiskRows, WorkingCatalog
from .catalog_scope import prepare_catalog_scope, verify_catalog_scope, read_catalog_scope, catalog_scope_requirements
from .immutable_metadata import encoded
from .catalog_selection import NativeCatalogSnapshot, publish_native_catalog
from .catalog_validation import catalog_reference_requirements


def selected_body_coverage(previous, dependencies, expected_bodies):
    """Verify specific already selected bodies through the non-grouping index."""
    if not isinstance(expected_bodies, CatalogKeys):
        with TemporaryDirectory(prefix='catalog-body-keys-') as temporary, closing(
                WorkingCatalog(Path(temporary) / 'keys.sqlite')) as work:
            return selected_body_coverage(previous, dependencies,
                CatalogKeys(work, 'expected', expected_bodies, 'Expected catalog body identities'))
    expected = expected_bodies
    basis = previous.selection['dependency'] if isinstance(previous, NativeCatalogSnapshot) else None
    for body in expected:
        source = next(iter(dependencies.sources_at_body(basis, body)), None)
        if source is None or source['source_values'].get('body_key') != body:
            raise ValueError('Selected catalog omits an expected retained body')
    return dict(expected_count=len(expected), expected_sha256=expected.identity()['sha256'],
                selected_count=len(expected), selected_identity=deepcopy(previous.identity),
                basis='selected-body-lookup-v1')


def update_native_catalog(store, *, native, previous, dependencies, replacements=(), deletions=(),
                          candidate, directory, max_chunk_rows, max_chunk_bytes, rules, expected_bodies=(), source_update=None,
                          full_update=False):
    """Replace complete interpreted rows; preserve untouched components and pins.

    Raw receipt interpretation supplies complete replacements/deletions here.
    This function owns grouping and publication, not source acquisition or
    interpretation policy. The returned scope_reference is durable evidence for
    retry/continuation and is bound to the exact prior application selection.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='catalog-inputs-', dir=directory) as temporary, closing(
            WorkingCatalog(Path(temporary) / 'inputs.sqlite')) as work:
        rows = DiskRows(work.connection, 'replacement_rows')
        for row in replacements:
            rows.append(row)
        removed = CatalogKeys(work, 'deletions', deletions, 'Catalog deletion identities', reject_duplicates=True)
        expected = CatalogKeys(work, 'expected_bodies', expected_bodies, 'Expected catalog body identities')
        return _update_native_catalog(store, native=native, previous=previous, dependencies=dependencies,
            replacements=rows, deletions=removed, candidate=candidate, directory=directory,
            max_chunk_rows=max_chunk_rows, max_chunk_bytes=max_chunk_bytes, rules=rules,
            expected_bodies=expected, source_update=source_update, full_update=full_update, work=work)


def _update_native_catalog(store, *, native, previous, dependencies, replacements, deletions,
                           candidate, directory, max_chunk_rows, max_chunk_bytes, rules,
                           expected_bodies, source_update, full_update, work):
    native_previous = isinstance(previous, NativeCatalogSnapshot)
    if not native_previous and (previous.manifest is not None or previous.files):
        raise ValueError('Native catalog update requires explicit prior adoption')
    if full_update:
        from .source_update_proof import read_source_update
        if not native_previous or source_update is None:
            raise ValueError('Full source update requires a selected native base and retained source proof')
        purpose = read_source_update(store, source_update)
        if (purpose.get('purpose') not in {'qualification', 'rule-upgrade'}
                or purpose.get('purpose') == 'rule-upgrade' and not purpose.get('rule_version')):
            raise ValueError('Full source update requires explicit complete qualification or versioned rules')
    if not replacements and not deletions and source_update is None:
        coverage = selected_body_coverage(previous, dependencies, expected_bodies)
        return dict(unchanged=True, body_coverage=coverage, selected_identity=deepcopy(previous.identity), selection=deepcopy(previous.identity['selected_ref']),
                    counts=deepcopy(previous.selection['counts']) if native_previous else dict(source_rows=0, document_rows=0))
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
                   deletions=deletions.identity(), max_chunk_rows=max_chunk_rows,
                   max_chunk_bytes=max_chunk_bytes, expected_bodies=expected_bodies.identity(), source_update=source_update,
                   full_update=full_update)
    from .derived_files import file_identity
    native_inputs = {str(Path(path).resolve()): file_identity(path)
        for path in native.execution_files()} if hasattr(native, 'execution_files') else {}
    request['native_execution'] = native_inputs
    def require_runtime():
        for path, identity in native_inputs.items():
            identity.require(path)
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
        require_runtime()
        result = publish_native_catalog(store, reference, previous=previous)
        return receipt(dict(result, unchanged=False), reference, proof)
    if full_update and purpose['base'] != previous.identity:
        raise ValueError('Full source update has a different selected base')
    preparation_request = directory / 'preparation-request.json'
    # Coverage is an admission assertion, not a chunk input. A failed assertion
    # may be corrected before admission; the final scope receipt binds it exactly.
    preparation_inputs = {key: value for key, value in request.items() if key != 'expected_bodies'}
    binding = dict(request=preparation_inputs, base=previous.identity, requirements=catalog_scope_requirements())
    if preparation_request.exists():
        if json.loads(preparation_request.read_bytes()) != binding:
            raise ValueError('Catalog continuation inputs or selected base differ from the retained preparation')
    else:
        staging = preparation_request.with_suffix('.tmp')
        staging.write_bytes(encoded(binding))
        staging.replace(preparation_request)
    basis = previous.selection['dependency'] if native_previous else None
    with ExitStack() as owners:
        selected = owners.enter_context(closing(dependencies.selected(basis)))
        scope = owners.enter_context(closing(affected_sources(selected, replacements=replacements, deletions=deletions)))
        orders = work.mapping('source_orders')
        for key in scope.before:
            orders[key] = selected.order(key)
        ordinal = basis['next_source_order'] if basis is not None else 0
        for row in replacements:
            key = index.source_identity(row)
            if key not in orders:
                orders[key], ordinal = ordinal, ordinal + 1
        prepared = owners.enter_context(closing(prepare_catalog_scope(
            directory / 'grouped-scope', scope, schema=dependencies.source_schema,
            source_orders=orders, candidate=candidate, checkpoint_directory=directory / 'grouped-components')))
        after = (dependencies.prepare_full(basis, replacements=prepared.source_values(), source_orders=orders)
                 if full_update else dependencies.prepare(basis, replacements=prepared.source_values(),
                                                         deletions=deletions, source_orders=orders))
        require_runtime()
        components = prepare_native_catalog_components(store, native, candidate=candidate,
            source_chunks=prepared.source_chunks(max_rows=max_chunk_rows, max_bytes=max_chunk_bytes),
            document_chunks=prepared.document_chunks(max_rows=max_chunk_rows, max_bytes=max_chunk_bytes),
            source_schema=prepared.source_schema, document_schema=prepared.document_schema,
            max_chunk_rows=max_chunk_rows, max_chunk_bytes=max_chunk_bytes,
            checkpoint_directory=directory / 'prepared-chunks')
        reference = verify_catalog_scope(store, dependencies=dependencies, dependency_before=basis,
            dependency_after=after, prepared=prepared, base=previous.identity,
            component_lookup=previous.component_ref if native_previous else lambda key: None,
            prepared_components=iterator_prepared_components(store, components),
            read_component=CatalogComponentReader(store).read,
            read_new_component=CatalogComponentReader(store, requirements=catalog_reference_requirements()).read,
            rules=rules, expected_bodies=expected_bodies, source_update=source_update,
            interpretation_before=previous.selection.get('interpretation') if native_previous else None,
            complete_counts=previous.selection['counts'] if full_update else None)
        payload = encoded(dict(request=request, scope_reference=reference))
        staging = directory / 'prepared-scope.tmp'
        staging.write_bytes(payload)
        staging.replace(checkpoint)
    require_runtime()
    result = publish_native_catalog(store, reference, previous=previous)
    return receipt(dict(result, unchanged=False), reference, read_catalog_scope(store, reference))
