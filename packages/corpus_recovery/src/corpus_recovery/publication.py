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


def prepare_viewer(publisher, builder, client, continuation, snapshot, publication_conditions, *,
                   renderer_upgrade=False, resume_upgrade=False):
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
        from viewer_publication.native import prepare_native_output
        if (snapshot is None or snapshot.manifest != inputs['source'][0]
                or snapshot.identity['selector_sha256'] != inputs['source'][3]):
            raise ValueError('Selected native source differs from accepted viewer input')
        upgrade_options=dict(renderer_upgrade=True,resume_upgrade=resume_upgrade) if renderer_upgrade else {}
        manifest, recovery = prepare_native_output(publisher, builder, client, snapshot, target,
            accepted_record=inputs['accepted'], viewer_record=inputs['viewer'], **upgrade_options)
        publisher.validate_prepared_output(target, manifest)
        initial = issue_inventory(target, manifest.identities, context=binding)
        publisher.prepare_recovery(target, manifest, inputs['accepted'], validation=initial, index=recovery)
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
                     bucket, imported, builder, publisher, publication_conditions, native,
                     renderer_upgrade=False, resume_upgrade=False):
    """Run domain work only after the dispatcher admits and guards its runtime."""
    from congress_api.retention.r2 import R2Store
    from congress_api.retention.catalog_publication import read_catalog
    from congress_api.retention.raw_catalog import update_from_raw
    from congress_api.retention.raw_storage import RawStorage
    from viewer_publication.filename_recoveries import accepted_rows
    from corpus_recovery.mappings import publish_mappings
    from corpus_recovery.guards import GuardedNative

    save = continuation.save
    def report(name, value):
        save(name, (json.dumps(value, indent=2, sort_keys=True) + '\n').encode())
    def journal(event, value):
        continuation.record(event, value)
    source = destination/'source'; expected = set(json.loads((batch/'bodies.json').read_text()))
    class Store(R2Store):
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
    guard.boundary()
    store = Store(proxy, bucket)
    guarded_native = GuardedNative(native, guard=guard.check, journal=journal)
    raw = RawStorage.open(store, guarded_native)
    if raw.snapshot().identity != imported['raw_identity']:
        raise ValueError('Raw selection changed since the admitted recovery import')

    def catalog_phase():
        catalog = update_from_raw(store, raw_storage=raw, directory=destination/'catalog-update',
            candidate=imported['raw_identity'][:32], expected_bodies=expected)
        report('coverage.json', catalog['body_coverage'])
        return catalog
    catalog = continuation.phase('catalog', catalog_phase,
        files=lambda: [source/'indexes/catalog.json', destination/'coverage.json'])
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
    with read_catalog(store, native=guarded_native) as snapshot:
        if snapshot.identity != catalog['selected_identity']:
            raise ValueError('Selected catalog differs from the accepted recovery update')
        upgrade_options=dict(renderer_upgrade=True,resume_upgrade=resume_upgrade) if renderer_upgrade else {}
        plan = prepare_viewer(publisher, builder, client, continuation, snapshot, publication_conditions, **upgrade_options)
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
