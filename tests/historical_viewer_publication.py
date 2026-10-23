"""Test-only version-5 generator for immutable historical reader fixtures.

Native production preparation imports publish_selected from the maintained builder.
This reference intentionally has no executable writer CLI.
"""
from array import array
from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import struct
import time
import pyarrow as pa
import pyarrow.parquet as pq
from congress_api.retention.derived_files import VerifiedFile, copy_checked, custody_identity, file_identity
from congress_api.retention.viewer_inventory import PreparedManifest
from viewer_publication.filename_resources import owned_resources
from viewer_publication.filename_budget import DEFAULT_DECODED_POLICY, DecodedBudgetExceeded, failure_receipt
from viewer_publication.filename_json_stream import ObservationCounts
from viewer_publication.filename_compression import CompressionPolicy, DEFAULT_COMPRESSION_POLICY

import viewer_publication.publish_filename_viewer as shared
viewer, observations, details = shared.viewer, shared.observations, shared.details
navigation, review_binding = shared.navigation, shared.review_binding
digest, verify, fetch = shared.digest, shared.verify, shared.fetch
write_u32, repack_and_verify = shared.write_u32, shared.repack_and_verify


def publish(root, target, modified=None, *, validation=None, review_identities=review_binding.IDENTITIES,
            compression_policy=DEFAULT_COMPRESSION_POLICY, stage_timings=None, stage_event=None,
            decoded_policy=DEFAULT_DECODED_POLICY, memory_metrics=None):
    memory_metrics = memory_metrics if memory_metrics is not None else {}
    try:
        with owned_resources() as owned:
            return _publish(root, target, modified, validation=validation, review_identities=review_identities,
                compression_policy=compression_policy, stage_timings=stage_timings, stage_event=stage_event, owned=owned,
                decoded_policy=decoded_policy, memory_metrics=memory_metrics)
    except DecodedBudgetExceeded as error:
        failure_receipt(target, error, decoded_policy, memory_metrics)
        raise


def _publish(root, target, modified, *, validation, review_identities, compression_policy, stage_timings, stage_event, owned, decoded_policy, memory_metrics):
    target = Path(target)
    if target.exists() and (not target.is_dir() or target.is_symlink() or any(target.iterdir())):
        raise ValueError('Viewer output must be a fresh empty directory; choose a new target to retry the build.')
    timings = stage_timings if stage_timings is not None else {}
    started = time.perf_counter()
    last_stage = started
    def stage(name, next_stage=None):
        nonlocal last_stage
        now = time.perf_counter()
        timings[name] = now - last_stage
        last_stage = now
        if stage_event:
            stage_event({'event': 'stage_completed', 'stage': name, 'seconds': timings[name]})
            if next_stage:
                stage_event({'event': 'stage_started', 'stage': next_stage})
    if stage_event:
        stage_event({'event': 'stage_started', 'stage': 'input_verification'})
    manifest = json.loads((root / 'indexes/catalog.json').read_text())
    document_item = manifest['files']['documents']
    document_path = root / document_item['key']
    document_custody = custody_identity(document_path)
    verify(root, manifest, validation=validation)
    stage('input_verification', 'catalog_loading')
    catalog = owned.enter_context(viewer.Catalog(root / manifest['files']['filenames']['key'], search_indexes=False))
    stage('catalog_loading', 'documents_preparation')
    target.mkdir(parents=True, exist_ok=True)
    # Generation-specific paths prevent a stale tab from mixing data from
    # different snapshots. Removed files fail visibly and require a reload.
    output = target / manifest['generation'] / 'viewer-v2'
    output.mkdir(parents=True, exist_ok=False)
    files = {}
    file_proofs = {}

    def describe(name, path, rows=None, *, proof=None):
        if proof is None:
            proof = file_identity(path)
        elif not isinstance(proof, VerifiedFile):
            raise ValueError('Describing a copied file requires its issued destination proof')
        proof.require(path)
        relative = str(path.relative_to(target))
        file_proofs[relative] = proof
        files[name] = dict(path=relative, **proof)
        if rows is not None:
            files[name]['rows'] = rows

    # Documents are an archive download, not a browser decoding input. Preserve
    # their verified bytes without requiring a giant source row to fit a decoder.
    document_file = catalog.document_file
    if (catalog.document_path.resolve() != document_path.resolve()
            or custody_identity(document_path) != document_custody
            or document_file.metadata.num_rows != document_item['rows']
            or (document_file.schema_arrow.metadata or {}).get(b'catalog_id', b'').decode() != manifest['catalog_id']):
        raise ValueError('Document archive source custody or catalog identity changed')
    path = output / 'documents.parquet'
    copy_started = time.perf_counter()
    with document_path.open('rb') as stream:
        proof = copy_checked(stream, path, size=document_item['bytes'], expected=document_item, key=document_item['key'])
    if custody_identity(document_path) != document_custody:
        raise ValueError('Document archive source custody changed during copy')
    describe('documents', path, document_file.metadata.num_rows, proof=proof)
    files['documents']['encoding'] = dict(mode='source_passthrough', source_sha256=document_item['sha256'])
    timings['documents_copy'] = dict(rows=document_file.metadata.num_rows, **proof,
        copy_seconds=time.perf_counter() - copy_started, verification_method='complete_sha256_bytes')
    stage('documents_preparation', 'filenames_preparation')
    print(f"documents: {proof['bytes']:,} bytes; complete source SHA-256/bytes verified", flush=True)

    path = output / 'filenames.parquet'
    result = repack_and_verify(catalog.file, path, compression_policy,
        decoded_policy=decoded_policy, metrics=memory_metrics)
    timings['filenames_repack'] = result
    describe('filenames', path, result['rows'])
    stage('filenames_preparation', 'observations')
    print(f'filenames: {path.stat().st_size:,} bytes; all values verified', flush=True)

    source = catalog.file
    counts = owned.enter_context(ObservationCounts(source))
    observations.publish_observations(source, output, counts=counts, policy=decoded_policy, metrics=memory_metrics)
    for name, filename in [('observations', 'observations.bin'), ('observation_rows', 'observation-rows.bin'), ('observation_index', 'observation-index.json')]:
        describe(name, output / filename)
    print('Source observations: every reconstructed value verified', flush=True)
    stage('observations', 'details')
    document_file = catalog.document_file
    detail_path = output / 'details.parquet'
    detail_info = details.publish_details(source, detail_path, observation_counts=counts, policy=decoded_policy, metrics=memory_metrics, compression_policy=compression_policy)
    describe('details', detail_path, detail_info['rows'])

    stage('details', 'navigation')
    order = catalog.order.to_pylist()
    position = catalog.entry_positions
    # Group positions always refer to browse.parquet's filename-sorted rows.
    group = array('I', (position[value] for value in catalog.entry_ids))
    preferred = array('I', (catalog.preferred_sources[value] for value in order))
    flags = bytes((1 if catalog.saved_responses[value] else 0) |
                  (2 if value in catalog.document_entries else 0) |
                  (4 if not catalog.documents['document_kind'][value].as_py() else 0) |
                  (8 if not catalog.documents['document_family'][value].as_py() else 0) |
                  (16 if value in catalog.api_entries else 0) |
                  (32 if value in catalog.video_entries else 0) for value in order)
    for name, values in [('groups', group), ('preferred', preferred)]:
        path = output / f'{name}.bin'
        write_u32(path, values)
        describe(name, path)
    for name, path in navigation.publish_navigation(group, preferred, output).items():
        describe(name, path)
    path = output / 'flags.bin'
    path.write_bytes(flags)
    describe('flags', path)

    stage('navigation', 'review_binding')
    # Reviews are published once; their positions are recomputed for every
    # catalog version from stable identities, so they survive rebuilds.
    if review_identities and (identities := review_binding.load_identities(review_identities)) is not None:
        binding = review_binding.bind(catalog, identities)
        path = output / 'review-binding.json'
        path.write_text(json.dumps(binding, sort_keys=True, separators=(',', ':')) + '\n')
        describe('review_binding', path)
        print(f"Review binding: {len(binding['rows'])} bound, {len(binding['withdrawn'])} withdrawn", flush=True)

    stage('review_binding', 'browse')
    # IDs are resolved when a row is opened; carrying both hashes on every
    # list row would duplicate tens of megabytes without displaying them.
    browse = catalog.documents.drop([name for name in ['body_key', 'source_id', 'document_id', 'extension', 'recovered_filename', 'response_result'] if name in catalog.documents.column_names]).take(catalog.order)
    basis = document_file.read(columns=['document_kind_source']).take(catalog.order) if 'document_kind_source' in document_file.schema_arrow.names else pa.table({'document_kind_source': pa.nulls(len(browse), type=pa.list_(pa.string()))})
    browse = browse.append_column('document_kind_source', basis.column(0))
    browse = browse.append_column('source_count', pa.array([len(catalog.members[value]) for value in order], type=pa.uint32()))
    browse = browse.append_column('retained', pa.array([bool(catalog.saved_responses[value]) for value in order]))
    path = output / 'browse.parquet'
    pq.write_table(browse, path, row_group_size=1024, compression=compression_policy.codec, compression_level=compression_policy.level)
    describe('browse', path, len(browse))

    stage('browse', 'ids')
    # Stable source IDs resolve through one small binary prefix file, instead
    # of loading a million 64-character IDs into browser memory.
    ids = output / 'ids'
    ids.mkdir(exist_ok=True)
    with ExitStack() as streams:
        shard_streams = [streams.enter_context((ids / f'{prefix:02x}.bin').open('wb')) for prefix in range(256)]
        for identity, index in catalog.source_ids.items():
            raw = bytes.fromhex(identity)
            if len(raw) != 32:
                raise ValueError('Expected a SHA-256 source ID.')
            shard_streams[raw[0]].write(raw + struct.pack('<I', index))
    for prefix in range(256):
        path = ids / f'{prefix:02x}.bin'
        file_proofs[str(path.relative_to(target))] = file_identity(path)

    stage('ids', 'manifest')
    info = dict(catalog.info, generation=manifest['generation'], remote_last_modified=modified or catalog.info.get('remote_last_modified'))
    info.pop('synced_at', None)
    publication = dict(version=5, published_at=datetime.now(timezone.utc).isoformat(), info=info, files=files,
                       source_manifest=manifest, ids=str(ids.relative_to(target)) + '/',
                       compression_policy=dict(compression_policy._asdict(), applies_to=['filenames']))
    (target / 'manifest.json').write_text(json.dumps(publication, ensure_ascii=False, separators=(',', ':')))
    print(f'Publication: {sum(p.stat().st_size for p in target.rglob("*") if p.is_file()):,} bytes', flush=True)
    stage('manifest')
    timings['total_seconds'] = time.perf_counter() - started
    timings['decoded_memory'] = {'policy': asdict(decoded_policy), 'observed': dict(memory_metrics)}
    file_proofs['manifest.json'] = file_identity(target / 'manifest.json')
    return PreparedManifest(publication, file_proofs)
