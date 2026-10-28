"""Prepare native viewer output through the maintained builder and recovery policy."""
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import time

from congress_api.retention.control_documents import bounded_control_read


def _release_path(path):
    if (not isinstance(path, str) or not path.startswith('releases/')
            or '..' in PurePosixPath(path).parts or str(PurePosixPath(path)) != path):
        raise ValueError('Invalid retained viewer release path')
    return path


def _read(client, publisher, path, *, kind, expected=None, digest=None):
    response = client.get_object(Bucket=publisher.BUCKET, Key=publisher.PREFIX + _release_path(path))
    with response['Body'] as stream:
        raw = bounded_control_read(stream, kind=kind, declared=response.get('ContentLength'), expected=expected)
    if expected is not None and len(raw) != expected or digest is not None and sha256(raw).hexdigest() != digest:
        raise ValueError('Retained viewer input identity differs')
    return raw


def prepare_native_output(publisher=None, builder=None, client=None, snapshot=None, target=None, *, accepted_record, viewer_record,
                          recovery_only=False, renderer_upgrade=False, resume_upgrade=False,
                          preparation_binding=None, resume_preparation=False,
                          stage_timings=None, stage_event=None, memory_metrics=None):
    """Reuse only a hash-verified prior release; leave selection to the caller.

    Local and hosted callers retain their existing input pins, accepted phase,
    artifact checks, conditional writes and continuation. This function owns no
    remote write and never interprets a missing prior result as a rebuild request.
    """
    if publisher is None:
        from viewer_publication import publish_viewer_r2 as publisher
    if builder is None:
        from viewer_publication import publish_filename_viewer as builder
    if resume_upgrade and not renderer_upgrade:
        raise ValueError('Renderer upgrade resume requires an explicit upgrade')
    from congress_api.retention.catalog_selection import NativeCatalogSnapshot
    from viewer_publication.filename_native_recoveries import index_catalog_recoveries
    if not isinstance(snapshot, NativeCatalogSnapshot):
        raise ValueError('Viewer preparation requires an explicitly adopted native catalog')
    previous, previous_recovery, prior_binding = None, None, None
    pointer = viewer_record[0]
    if pointer is not None:
        expected_digest = pointer.get('recovery_inputs', {}).get('viewer_manifest_sha256')
        if not isinstance(expected_digest, str) or len(expected_digest) != 64:
            raise ValueError('Prior viewer release lacks its exact retained manifest digest')
        previous_raw = _read(client, publisher, pointer['manifest'], kind='manifest', digest=expected_digest)
        previous_value = json.loads(previous_raw)
        if (previous_value['info']['catalog_id'] != pointer['catalog_id']
                or previous_value['source_manifest'] != pointer['source_manifest']):
            raise ValueError('Prior viewer release differs from its selected pointer')
        if previous_value.get('version') == 6:
            if previous_value['source_identity'] != pointer.get('source_identity'):
                raise ValueError('Prior native viewer source identity differs')
            descriptor = pointer['recovery']
            previous_recovery = json.loads(_read(client, publisher, descriptor['path'], kind='recovery',
                expected=descriptor['bytes'], digest=descriptor['sha256']))
            publisher.require_native_recovery(previous_recovery, previous_value)
            previous = previous_value
        elif previous_value.get('version') == 5:
            # Initial serving adoption retains recorded withdrawals. Historical
            # row positions are never interpreted as current document positions.
            descriptor = previous_value['files']['review_binding']
            prefix = pointer['manifest'].rsplit('/', 1)[0] + '/'
            prior_binding = json.loads(_read(client, publisher, prefix + descriptor['path'], kind='manifest',
                expected=descriptor['bytes'], digest=descriptor['sha256']))
            if prior_binding.get('catalog_id') != pointer['catalog_id'] or prior_binding.get('version') != 1:
                raise ValueError('Historical review binding differs from its selected catalog')
        else:
            raise ValueError('Unsupported prior viewer publication')

    def read_asset(path):
        return _read(client, publisher, path, kind='manifest')

    if recovery_only and (renderer_upgrade or resume_upgrade):
        raise ValueError('Renderer upgrades require full viewer preparation')
    if recovery_only:
        # A recovery-only publication changes the sidecar, not the release it
        # describes. Retain its exact bytes and enough proof for offline restore.
        if previous is None or previous['source_identity'] != snapshot.identity:
            raise ValueError('Recovery-only preparation requires the same selected native catalog')
        from congress_api.retention.derived_files import file_identity
        from congress_api.retention.viewer_inventory import PreparedManifest
        from viewer_publication.filename_native import ViewerAssets, validate_publication
        target = Path(target)
        if target.is_symlink() or target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ValueError('Viewer output must be a fresh empty directory')
        assets = ViewerAssets(target, read_asset=read_asset)
        validate_publication(assets, previous)
        for reference in (previous['proof'], previous['source_selection']):
            assets.put_node(assets.read_node(reference))
        (target / 'manifest.json').write_bytes(previous_raw)
        assets.identities['manifest.json'] = file_identity(target / 'manifest.json')
        manifest = PreparedManifest(previous, assets.identities)
    else:
        options = dict(previous=previous, read_asset=read_asset, stage_timings=stage_timings,
                       stage_event=stage_event, memory_metrics=memory_metrics)
        if preparation_binding is not None:
            options.update(preparation_binding=preparation_binding, resume_preparation=resume_preparation)
        if renderer_upgrade:
            options.update(renderer_upgrade=True, resume_upgrade=resume_upgrade)
        if prior_binding is not None:
            options['prior_review_binding'] = prior_binding
        manifest = builder.publish_selected(snapshot, target, **options)
    if stage_event:
        stage_event(dict(event='stage_started', stage='recovery_preparation'))
    started = time.perf_counter()
    try:
        recovery = index_catalog_recoveries(snapshot, publisher.validated_accepted(accepted_record[0]),
            previous=previous_recovery, max_ordered_bytes=96 << 20, metrics=memory_metrics,
            admission_directory=(Path(target).with_name(Path(target).name + '.recovery-admission')
                                 if preparation_binding is not None else None))
        publisher.require_native_recovery(recovery, manifest)
    except BaseException:
        seconds = time.perf_counter() - started
        if stage_timings is not None:
            stage_timings['recovery_preparation'] = seconds
        if stage_event:
            stage_event(dict(event='stage_interrupted', stage='recovery_preparation', seconds=seconds))
        raise
    seconds = time.perf_counter() - started
    if stage_timings is not None:
        stage_timings['recovery_preparation'] = seconds
    if stage_event:
        stage_event(dict(event='stage_completed', stage='recovery_preparation', seconds=seconds))
    return manifest, recovery
