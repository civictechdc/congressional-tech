"""Maintained catalog/mapping/viewer phases for an admitted local recovery run.

The dispatcher owns runtime selection, source pins, SDK policy, lock and guard.
This entry point owns domain phases and retained source/proposed output custody.
"""
import json
from pathlib import Path
from datetime import datetime, timezone
import uuid

from congress_api.retention.derived_files import file_identity
from congress_api.retention.viewer_inventory import issue_inventory, verify_inventory
from viewer_publication.plan import accept_viewer_plan


def prepare_viewer(publisher, builder, client, continuation, source, validate_pair,
                   pair_proof, publication_conditions):
    """Accept the existing prepared phase once, including its recovery status."""
    root = continuation.root
    target = root / 'prepared'
    binding = continuation.value['binding']
    inputs = continuation.value.get('viewer_inputs')
    if inputs is None:
        inputs = {name: tuple(publisher.read_identity(client, key, optional=name != 'source'))
                  for name, key in (('source', 'indexes/catalog.json'),
                                    ('accepted', publisher.ACCEPTED_KEY),
                                    ('viewer', publisher.PREFIX + 'manifest.json'))}
        if any(record[1] != continuation.value['versions'][key] for key, record in (
                ('indexes/catalog.json', inputs['source']),
                (publisher.ACCEPTED_KEY, inputs['accepted']),
                (publisher.PREFIX + 'manifest.json', inputs['viewer']))):
            raise ValueError('Protected input changed before accepted viewer preparation')
        continuation.value['viewer_inputs'] = inputs
        continuation.value.setdefault('release_plan', dict(release='releases/' + uuid.uuid4().hex + '/',
            published_at=datetime.now(timezone.utc).isoformat()))
        continuation.flush()
    conditions = publication_conditions(continuation)
    proof = None

    def build():
        nonlocal proof
        selected = json.loads((source / 'indexes/catalog.json').read_text())
        validate_pair(selected)
        if selected != inputs['source'][0]:
            raise ValueError('Retained source differs from accepted viewer input')
        manifest = builder.publish(source, target, inputs['source'][2], validation=pair_proof())
        publisher.validate_prepared_output(target, manifest)
        identities = getattr(manifest, 'identities', None)
        initial = (issue_inventory(target, identities, context=binding) if identities is not None else
                   verify_inventory(target, {str(p.relative_to(target)): None for p in target.rglob('*') if p.is_file()}, context=binding))
        publisher.prepare_recovery(target, manifest, inputs['accepted'], validation=initial)
        identities = dict(initial.identities)
        identities['recovery-prepared.json'] = file_identity(target / 'recovery-prepared.json')
        proof = issue_inventory(root, {'prepared/' + key: value for key, value in identities.items()}, context=binding)
        return dict(manifest)

    saved = continuation.value['phases'].get('prepared')
    if saved is not None:
        publisher.validate_prepared_output(target, saved['result'])
        actual = {str(p.relative_to(root)) for p in target.rglob('*') if p.is_file()}
        if actual != set(saved['files']):
            raise ValueError('Prepared publication inventory changed')
        proof = verify_inventory(root, {relative: dict(bytes=(root / relative).stat().st_size, sha256=digest)
                                       for relative, digest in saved['files'].items()}, context=binding)
    manifest = continuation.phase('prepared', build, files=lambda: [], inventory=lambda: proof)
    return accept_viewer_plan(publisher, target, manifest, validation=proof, context=binding,
        protected=inputs, source_pins=binding['pins'], release_plan=continuation.value['release_plan'],
        conditions=conditions)


def publish_imported(*, client, proxy, guard, continuation, destination, batch, baseline,
                     bucket, imported, builder, publisher, publication_conditions):
    """Run domain work only after the dispatcher admits and guards its runtime."""
    from congress_api.retention.r2 import R2Store
    from congress_api.retention.catalog_staging import WorkingCatalog
    from congress_api.cli.raw_progress import ProgressLog
    from congress_api.retention.document_index import validate_document_indexes
    from congress_api.retention.catalog_validation import validate_catalog_pair
    from congress_api.retention.raw_catalog import rebuild_catalog_in_directory
    from viewer_publication.filename_recoveries import accepted_rows
    from corpus_recovery.mappings import publish_mappings

    save = continuation.save
    def report(name, value):
        save(name, (json.dumps(value, indent=2) + '\n').encode())
    def journal(event, value):
        continuation.record(event, value)
    versions = continuation.value['versions']
    source = destination/'source'; expected = set(json.loads((batch/'bodies.json').read_text()))
    pair_validation = None
    content_validation = None
    def validate_pair(manifest):
        nonlocal pair_validation
        if pair_validation is not None:
            return pair_validation.require(source, manifest, validator=validate_document_indexes, expected_bodies=expected)
        pair_validation = validate_catalog_pair(source, manifest, validator=validate_document_indexes,
                                               expected_bodies=expected, references=content_validation)
        return pair_validation.coverage
    class Store(R2Store):
        def accept_catalog_validation(self, validation):
            nonlocal content_validation
            content_validation = validation
        def read(self, key):
            body = super().read(key)
            if body is not None and key == 'indexes/catalog.json':
                save('source/'+key, body, replace=key == 'indexes/catalog.json')
            return body
        def put(self, key, body, *, immutable=False):
            if key == 'indexes/catalog.json':
                save('proposed/'+key, body, replace=True)
            result = super().put(key, body, immutable=immutable)
            if key == 'indexes/catalog.json':
                save('source/'+key, body, replace=True)
            return result
        def save_derived(self, key, path, identity):
            from congress_api.retention.derived_files import retain_verified_file
            return retain_verified_file(path, source / key, expected=identity, key=key)
        def read_derived_file(self, key, path, *, expected=None):
            identity = super().read_derived_file(key, path, expected=expected)
            if identity is not None:
                self.save_derived(key, path, identity)
            return identity
        def put_derived_file(self, key, path, *, expected):
            self.save_derived(key, path, expected)
            return super().put_derived_file(key, path, expected=expected)
        def put_catalog_manifest(self, data, *, expected_version):
            manifest = json.loads(data)
            coverage = validate_pair(manifest)
            report('coverage.json', coverage)
            return super().put_catalog_manifest(data, expected_version=expected_version)
    guard.boundary()
    def catalog_phase():
        build = destination/'build'
        # An unaccepted build may contain the only diagnostic SQLite state.
        # Explicit continuation reuses accepted phases; it never deletes or
        # silently restarts incomplete catalog work.
        if build.exists():
            raise RuntimeError('Incomplete catalog build retained; reconcile before continuation: '+str(build))
        build.mkdir(); (build/'indexes').mkdir()
        working = WorkingCatalog(build/'working.sqlite')
        try:
            with ProgressLog(destination/'catalog-progress.json'):
                catalog = rebuild_catalog_in_directory(Store(proxy,bucket), working=working, root=build)
        finally: working.close()
        manifest = json.loads((source/'indexes/catalog.json').read_text())
        coverage = validate_pair(manifest)
        report('coverage.json', coverage)
        return catalog
    catalog = continuation.phase('catalog', catalog_phase,
        files=lambda: [*source.rglob('*parquet'), source/'indexes/catalog.json', destination/'coverage.json'])
    report('catalog-result.json', catalog)
    guard.boundary()
    def mapping_phase():
        mapping = publish_mappings(proxy, bucket=bucket,
            baseline=json.loads(baseline.read_text()), prepared=json.loads((batch/'accepted.json').read_text()),
            validate=accepted_rows, guard=guard.boundary, save_payload=save, journal=journal)
        return mapping
    mapping = continuation.phase('mappings', mapping_phase, files=lambda: [p for p in (destination/'accepted-proposed.json', destination/'accepted-before.json') if p.exists()])
    report('mapping-result.json', mapping)
    guard.boundary()
    plan = prepare_viewer(publisher, builder, client, continuation, source,
                          validate_pair, lambda: pair_validation, publication_conditions)
    guard.boundary()
    def publication_phase():
        publication = publisher.upload(proxy, plan.root, plan.manifest,
            **plan.conditions, publication_plan=plan.release_plan, plan=plan)
        if publication['status'] not in {'published', 'unchanged'}:
            raise ValueError('Viewer was not published')
        return publication
    publication = continuation.phase('publication', publication_phase, files=lambda: [])
    guard.boundary()
    report('complete.json', dict(complete=True, catalog=catalog, mapping=mapping,
                                publication=publication, imported=imported))
    return publication
