"""Accepted preparation and explicit durable publication attempts for the viewer."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import uuid
from datetime import datetime, timezone

from viewer_publication.plan import accept_viewer_plan
from viewer_publication.resume import resume_descriptor, validate_resume_descriptor
from viewer_publication.client import ContinuedPublicationClient
from viewer_publication.continuation import Continuation, DurableJournal, MissingPublicationJournal, sha256
from congress_api.retention.derived_files import file_identity
from congress_api.retention.viewer_inventory import verify_inventory, issue_inventory, InventoryValidation


class PreparedVerification(tuple):
    def __new__(cls, receipt, manifest, result, validation, plan):
        value = super().__new__(cls, (receipt, manifest, result))
        value.validation = validation
        value.plan = plan
        return value


class Superseded(ValueError):
    pass


def content_identity(publisher):
    return publisher.full_release_identity()


def record_input(publisher, client, key, optional=False):
    value, etag, modified, digest = publisher.read_identity(client, key, optional=optional)
    return {'value': value, 'etag': etag, 'modified': modified, 'sha256': digest}


def prepare(publisher, client, root, *, run_id, run_attempt, public_url, native=None):
    """Read inputs and accept complete local output; perform no publication writes."""
    selected = record_input(publisher, client, 'indexes/catalog.json')
    previous = record_input(publisher, client, publisher.PREFIX + 'manifest.json', optional=True)
    accepted = record_input(publisher, client, publisher.ACCEPTED_KEY, optional=True)
    publisher.validated_accepted(accepted['value'])
    binding = {'version': 1, 'code_runtime': content_identity(publisher), 'source': selected,
               'viewer': previous, 'accepted': accepted, 'run_id': str(run_id), 'run_attempt': str(run_attempt),
               'publisher_version': publisher.PUBLISHER_VERSION}
    binding['provenance_revision'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'],
        cwd=Path(publisher.__file__).resolve().parents[3], text=True, timeout=10).strip()
    mode = 'full'
    if (previous['value'] and previous['value'].get('source_manifest') == selected['value']
            and previous['value'].get('publisher_version') == publisher.PUBLISHER_VERSION
            and previous['value'].get('full_release_inputs') == binding['code_runtime']):
        result = publisher.check_selected_publication(client, previous['value'], public_url=public_url,
            records=(tuple(selected[k] for k in ('value', 'etag', 'modified', 'sha256')),
                     tuple(accepted[k] for k in ('value', 'etag', 'modified', 'sha256')),
                     tuple(previous[k] for k in ('value', 'etag', 'modified', 'sha256'))),
            release_identity=binding['code_runtime'])
        if result['status'] == 'unchanged':
            return result
        mode = 'recovery'
    if selected['value'].get('version') != 2:
        raise ValueError('Viewer updates require explicitly adopted native catalog storage')
    if native is None:
        from congress_api.retention.docspec import NativeDatasets
        configuration = os.environ.get('DOCSPEC_CONFIG')
        if not configuration:
            raise ValueError('Native viewer preparation requires explicit DOCSPEC_CONFIG or --native-config')
        native = NativeDatasets.from_config(configuration)
    from congress_api.retention.catalog_publication import read_catalog
    from congress_api.retention.r2 import R2Store
    snapshot = read_catalog(R2Store(client, publisher.BUCKET), native=native)
    if (snapshot.manifest != selected['value'] or snapshot.identity['selector_sha256'] != selected['sha256']
            or snapshot.version != selected['etag']):
        raise ValueError('Catalog changed before native viewer preparation')
    native_inputs = {str(Path(path).resolve()): file_identity(path) for path in native.execution_files()}
    binding['native_execution'] = {path: dict(identity) for path, identity in native_inputs.items()}
    binding['mode'] = mode
    continuation = Continuation(root, binding)
    publication = root / 'publication'
    inventory_proof = None
    def build():
        nonlocal inventory_proof
        identities = {}
        import importlib.util
        from viewer_publication.native import prepare_native_output
        spec = importlib.util.spec_from_file_location('prepared_viewer_builder', Path(publisher.__file__).with_name('publish-filename-viewer.py'))
        builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
        manifest, recovery = prepare_native_output(publisher, builder, client, snapshot, publication,
            accepted_record=tuple(accepted[k] for k in ('value', 'etag', 'modified', 'sha256')),
            viewer_record=tuple(previous[k] for k in ('value', 'etag', 'modified', 'sha256')),
            recovery_only=mode == 'recovery')
        for path, identity in native_inputs.items():
            identity.require(path)
        identities = dict(manifest.identities)
        proof = issue_inventory(publication, identities, context=binding)
        publisher.prepare_recovery(publication, manifest,
            tuple(accepted[k] for k in ('value', 'etag', 'modified', 'sha256')), validation=proof, index=recovery)
        publisher.validate_prepared_output(publication, manifest)
        for name in ('manifest.json', 'recovery-prepared.json'):
            identities[name] = file_identity(publication / name)
        inventory_proof = issue_inventory(root,
            {'publication/' + relative: proof for relative, proof in identities.items()}, context=binding)
        return manifest
    manifest = continuation.phase('prepared', build, files=lambda: [], inventory=lambda: inventory_proof)
    inventory = inventory_proof.files
    plan = {'release': 'releases/' + uuid.uuid4().hex + '/', 'published_at': datetime.now(timezone.utc).isoformat()}
    receipt = {'version': 1, 'binding': binding, 'files': inventory, 'release_plan': plan,
               'compression_policy': manifest.get('compression_policy'), 'manifest_sha256': inventory['publication/manifest.json']['sha256']}
    receipt_bytes = publisher.encoded(receipt)
    receipt_digest = hashlib.sha256(receipt_bytes).hexdigest()
    continuation.save('preparation.json', receipt_bytes)
    result = {'status': 'prepared', 'mode': mode, 'preparation_sha256': receipt_digest,
              'artifact_name': f'viewer-prepared-{run_id}-{run_attempt}-{receipt_digest}',
              'attempt': f'{run_id}-{run_attempt}-{receipt_digest}', 'catalog_id': manifest['info']['catalog_id']}
    continuation.save('prepared-result.json', publisher.encoded(result))
    verify_prepared(publisher, root, validation=inventory_proof)
    return result


def verify_prepared(publisher, root, *, validation=None):
    """Verify every accepted output and exact stable selection/control custody."""
    receipt = json.loads((root / 'preparation.json').read_text())
    if receipt.get('version') != 1 or receipt['binding']['code_runtime'] != content_identity(publisher):
        raise ValueError('Prepared runtime, code or review identities changed')
    manifest = json.loads((root / 'publication/manifest.json').read_text())
    publisher.validate_prepared_output(root / 'publication', manifest)
    if (receipt['manifest_sha256'] != receipt['files'].get('publication/manifest.json', {}).get('sha256')
            or receipt['compression_policy'] != manifest.get('compression_policy')
            or manifest['source_manifest'] != receipt['binding']['source']['value']):
        raise ValueError('Prepared policy or source selection changed')
    actual = {str(path.relative_to(root)) for path in (root / 'publication').rglob('*') if path.is_file()}
    if actual != set(receipt['files']):
        raise ValueError('Prepared publication inventory changed')
    if validation is None:
        validation = verify_inventory(root, receipt['files'], context=receipt['binding'])
    elif not isinstance(validation, InventoryValidation):
        raise ValueError('Prepared inventory requires an issued proof')
    else:
        validation.require(root, receipt['files'], context=receipt['binding'])
    validation.file(root / 'publication/manifest.json', expected=dict(bytes=(root / 'publication/manifest.json').stat().st_size,
                    sha256=receipt['manifest_sha256']))
    continuation = Continuation(root, receipt['binding'], resume=True)
    continuation.phase('prepared', lambda: (_ for _ in ()).throw(ValueError('Missing accepted preparation')),
                       files=lambda: [], inventory=lambda: validation)
    result = json.loads((root / 'prepared-result.json').read_text())
    receipt_digest = sha256(root / 'preparation.json')
    run_id, run_attempt = receipt['binding']['run_id'], receipt['binding']['run_attempt']
    expected = {'status': 'prepared', 'mode': receipt['binding']['mode'], 'preparation_sha256': receipt_digest,
                'artifact_name': f'viewer-prepared-{run_id}-{run_attempt}-{receipt_digest}',
                'attempt': f'{run_id}-{run_attempt}-{receipt_digest}',
                'catalog_id': manifest['info']['catalog_id']}
    if result != expected:
        raise ValueError('Prepared receipt digest or attempt identity differs')
    protected = {name: tuple(receipt['binding'][name][key] for key in ('value', 'etag', 'modified', 'sha256'))
                 for name in ('source', 'accepted', 'viewer')}
    plan = accept_viewer_plan(publisher, root / 'publication', manifest,
        validation=validation, context=receipt['binding'], protected=protected,
        source_pins=receipt['binding']['code_runtime'], release_plan=receipt['release_plan'],
        conditions=dict(previous_etag=protected['viewer'][1], selected_etag=protected['source'][1]),
        mode=receipt['binding']['mode'])
    return PreparedVerification(receipt, manifest, result, validation, plan)


def github_json(route):
    raw = subprocess.check_output(['gh', 'api', route], timeout=60)
    if len(raw) > 2 * 1024**2:
        raise ValueError('GitHub artifact metadata exceeds 2 MiB limit')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('GitHub artifact metadata must be an object')
    return value


def artifact_route(artifact):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', str(artifact.get('repository', ''))):
        raise ValueError('Artifact repository must be owner/name')
    if not str(artifact.get('id', '')).isdigit() or int(artifact['id']) < 1:
        raise ValueError('Artifact ID must be a positive integer')
    return f"repos/{artifact['repository']}/actions/artifacts/{artifact['id']}"


def verify_github_artifact(artifact, prepared):
    """Require exact GitHub custody before any public or journal mutation."""
    if not artifact.get('id') or not artifact.get('digest') or not artifact.get('repository'):
        raise ValueError('Accepted preparation artifact is required before publication')
    route = artifact_route(artifact)
    metadata = github_json(route)
    expected_digest = artifact['digest'].removeprefix('sha256:')
    checks = (
        (str(metadata.get('id')) == str(artifact['id']), 'Artifact ID differs'),
        (metadata.get('expired') is False, 'Preparation artifact expired'),
        (metadata.get('name') == prepared['artifact_name'], 'Artifact name differs from prepared receipt'),
        (metadata.get('digest', '').removeprefix('sha256:') == expected_digest, 'Artifact digest differs'),
        (str(metadata.get('workflow_run', {}).get('id')) == str(artifact.get('run_id')), 'Artifact original run ID differs'))
    for passed, diagnostic in checks:
        if not passed:
            raise ValueError(diagnostic)
    return {'id': str(metadata['id']), 'digest': expected_digest, 'name': metadata['name'],
            'run_id': str(artifact['run_id']), 'repository': artifact['repository']}


def lookup_attempt(repository, run_id, artifact_id=None):
    """Read-only discovery; never downloads, reconciles, retries or publishes."""
    artifact_route({'repository': repository, 'id': artifact_id or '1'})
    if not str(run_id).isdigit():
        raise ValueError('Preparation run ID must be numeric')
    run = github_json(f'repos/{repository}/actions/runs/{run_id}')
    if str(run.get('id')) != str(run_id):
        raise ValueError('GitHub preparation run ID differs')
    artifacts = []
    for page in range(1, 11):
        response = github_json(f'repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100&page={page}')
        rows = response.get('artifacts')
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError('Malformed bounded artifact listing')
        for item in rows:
            if (isinstance(item, dict) and item.get('expired') is False and item.get('name', '').startswith('viewer-prepared-')
                    and (artifact_id is None or str(item.get('id')) == str(artifact_id))):
                artifacts.append(resume_descriptor(item, run, repository))
        if len(rows) < 100:
            break
    else:
        raise ValueError('Artifact listing exceeds 1,000-item lookup limit')
    if len(artifacts) != 1:
        raise ValueError('Expected one original preparation artifact; select --artifact-id from the original run')
    return artifacts[0]


def publish(publisher, client, root, *, artifact, public_url, resume=False, attempt=None,
            verify_artifact=verify_github_artifact, probe=None):
    verified = verify_prepared(publisher, root)
    receipt, manifest, prepared = verified
    custody = verify_artifact(artifact, prepared)
    binding = receipt['binding']
    if str(custody['run_id']) != binding['run_id']:
        raise ValueError('Artifact does not belong to the preparation run')
    if attempt is not None and attempt != prepared['attempt']:
        raise ValueError('Explicit attempt differs from prepared attempt')
    if resume and attempt is None:
        raise ValueError('Explicit resume requires the original attempt identity')
    continuation = Continuation(root, binding, resume=True)
    versions = continuation.value['versions']
    if not versions:
        versions.update({key: binding[name]['etag'] for key, name in (
            ('indexes/catalog.json', 'source'), (publisher.PREFIX + 'manifest.json', 'viewer'),
            (publisher.ACCEPTED_KEY, 'accepted'))})
        continuation.flush()
    journal_binding = {'preparation_sha256': prepared['preparation_sha256'], 'artifact': custody,
                       'release_plan': receipt['release_plan']}
    # Reconcile the remote log before checking protected versions. A runner may
    # have died after selecting our pointer but before recording its acknowledgment.
    if resume:
        try:
            journal = DurableJournal(client, publisher.BUCKET, continuation, prepared['attempt'], journal_binding, resume=True)
        except MissingPublicationJournal:
            # An accepted artifact may outlive failure before its first journal
            # event. This explicit invocation may claim the original attempt
            # after the fresh protected-input check, with conditional creation.
            journal = None
        continuation.reconcile(client, publisher.BUCKET)
    else:
        journal = None
    def guard():
        for key, name in (('indexes/catalog.json', 'source'), (publisher.ACCEPTED_KEY, 'accepted'),
                          (publisher.PREFIX + 'manifest.json', 'viewer')):
            current = record_input(publisher, client, key, optional=name != 'source')
            if current['etag'] != versions[key]:
                raise Superseded('Publication input changed: ' + key)
            if name != 'viewer' and current['value'] != binding[name]['value']:
                raise Superseded('Publication input changed: ' + key)
    try:
        guard()
    except Superseded as error:
        return {'status': 'superseded', 'reason': str(error), 'attempt': prepared['attempt']}
    if journal is None:
        journal = DurableJournal(client, publisher.BUCKET, continuation, prepared['attempt'], journal_binding)
    class PublicationGuard:
        def check(self):
            # Immutable, conditional writes may leave unselected files if inputs
            # advance. Their exact prepared bytes and unique release/digest names
            # do not depend on a fresh mutable selector.
            return None
        def shared_commit(self):
            guard()
    guarded = ContinuedPublicationClient(client, continuation=continuation, guard=PublicationGuard(), journal=journal.record,
                                         after_write=lambda *args: None)
    try:
        if binding['mode'] == 'recovery' and continuation.value['writes'].get(publisher.PREFIX + 'manifest.json', {}).get('verified'):
            pointer = publisher.read_json(client, publisher.PREFIX + 'manifest.json')[0]
            index = publisher.verify_recovery_status(client, pointer['recovery'], pointer, public_url=public_url)
            with publisher.open_public(publisher.public_request(public_url + 'manifest.json')) as response:
                if json.loads(publisher.public_control(response)) != pointer:
                    raise ValueError('Public recovery pointer differs after reconciliation')
            guard()
            result = publisher.recovery_result(pointer, index, publisher.validated_accepted(binding['accepted']['value']),
                                               status='recovery_updated')
        elif binding['mode'] == 'recovery':
            pointer_record = tuple(binding['viewer'][key] for key in ('value', 'etag', 'modified', 'sha256'))
            selected_record = tuple(binding['source'][key] for key in ('value', 'etag', 'modified', 'sha256'))
            accepted_record = tuple(binding['accepted'][key] for key in ('value', 'etag', 'modified', 'sha256'))
            # Require prepared manifest values; bind the current raw-byte digest below.
            remote, _, _, manifest_digest = publisher.read_identity(client, publisher.PREFIX + binding['viewer']['value']['manifest'])
            if remote != manifest:
                raise ValueError('Prepared recovery release manifest changed')
            result = publisher.select_recoveries(guarded, root / 'publication', manifest, selected_record,
                accepted_record, pointer_record, manifest_digest, public_url=public_url,
                index=verified.plan.require(root / 'publication', manifest).recovery)
        else:
            result = publisher.upload(guarded, root / 'publication', manifest,
                previous_etag=binding['viewer']['etag'], selected_etag=binding['source']['etag'], public_url=public_url,
                publication_plan=receipt['release_plan'], plan=verified.plan,
                **({'probe': probe} if probe is not None else {}))
        journal.record('publication_completed', result)
        continuation.save('publication-result.json', publisher.encoded(result), replace=True)
        return dict(result, attempt=prepared['attempt'], preparation_reused=resume)
    except BaseException as error:
        # Diagnostic failure must never replace the original publication error.
        try:
            journal.record('publication_failed', {'error_type': type(error).__name__, 'error': str(error)})
        except BaseException as diagnostic:
            error.add_note('Publication diagnostic save also failed: ' + repr(diagnostic))
        if isinstance(error, Superseded):
            return {'status': 'superseded', 'reason': str(error), 'attempt': prepared['attempt']}
        raise
