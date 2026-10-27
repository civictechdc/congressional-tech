"""Accepted preparation and explicit durable publication attempts for the viewer."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import time
import uuid
from datetime import datetime, timezone

from viewer_publication.plan import accept_viewer_plan
from viewer_publication.resume import resume_descriptor, validate_resume_descriptor
from viewer_publication.client import ContinuedPublicationClient
from viewer_publication.continuation import Continuation, DurableJournal, MissingPublicationJournal, sha256, bounded_json
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


def as_protected(record_dict):
    from viewer_publication.publish_viewer_r2 import ProtectedIdentity
    return ProtectedIdentity(record_dict['value'], record_dict['etag'], record_dict['modified'], record_dict['sha256'])


def prepare(publisher=None, client=None, root=None, *, run_id, run_attempt, public_url, native=None,
            renderer_upgrade=False, resume_preparation=False, stage_timings=None, stage_event=None, memory_metrics=None):
    """Read inputs and accept complete local output; perform no publication writes."""
    if publisher is None:
        from viewer_publication import publish_viewer_r2 as publisher
    selected = record_input(publisher, client, 'indexes/catalog.json')
    previous = record_input(publisher, client, publisher.PREFIX + 'manifest.json', optional=True)
    accepted = record_input(publisher, client, publisher.ACCEPTED_KEY, optional=True)
    publisher.validated_accepted(accepted['value'])
    binding = {'version': 1, 'code_runtime': content_identity(publisher), 'source': selected,
               'viewer': previous, 'accepted': accepted, 'run_id': str(run_id), 'run_attempt': str(run_attempt),
               'publisher_version': publisher.PUBLISHER_VERSION}
    repo_root = Path(__file__).resolve().parents[4]
    binding['provenance_revision'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'],
        cwd=repo_root, text=True, timeout=10).strip()
    mode = 'full'
    if (not renderer_upgrade and previous['value'] and previous['value'].get('source_manifest') == selected['value']
            and previous['value'].get('publisher_version') == publisher.PUBLISHER_VERSION
            and previous['value'].get('full_release_inputs') == binding['code_runtime']):
        if not resume_preparation:
            result = publisher.check_selected_publication(client, previous['value'], public_url=public_url,
                records=(as_protected(selected), as_protected(accepted), as_protected(previous)),
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
    if renderer_upgrade:binding['renderer_upgrade']=True
    if resume_preparation:
        # Run identity describes checkpoint origin; it cannot change with each
        # runner. All source, code, review, native and control inputs still must.
        original = bounded_json(root / 'continuation.json')['binding']
        binding.update(run_id=original['run_id'], run_attempt=original['run_attempt'])
    continuation = Continuation(root, binding, resume=resume_preparation)
    publication = root / 'publication'
    timings = stage_timings if stage_timings is not None else {}
    metrics = memory_metrics if memory_metrics is not None else {}
    started = time.perf_counter()
    def progress(event):
        value = dict(event, at=datetime.now(timezone.utc).isoformat(),
                     elapsed_seconds=time.perf_counter() - started)
        # Close each line before notifying observers: interruption leaves the
        # last task start/completion on disk, including a hard runner timeout.
        with (root / 'preparation-events.jsonl').open('a') as stream:
            stream.write(json.dumps(value, sort_keys=True) + '\n')
            stream.flush()
        from viewer_publication.publication_cli import save_report
        save_report(root / 'preparation-diagnostics.json', dict(
            version=1, status=value.get('status', 'incomplete'), origin=dict(run_id=binding['run_id'], run_attempt=binding['run_attempt']),
            invocation=dict(run_id=str(run_id), run_attempt=str(run_attempt)),
            latest=value, stage_timings=timings, memory_metrics=metrics))
        if stage_event:
            stage_event(value)
    def stage(name, action):
        progress(dict(event='stage_started', stage=name))
        before = time.perf_counter()
        try:
            result = action()
        except BaseException:
            timings[name] = time.perf_counter() - before
            progress(dict(event='stage_interrupted', stage=name, seconds=timings[name]))
            raise
        timings[name] = time.perf_counter() - before
        progress(dict(event='stage_completed', stage=name, seconds=timings[name]))
        return result
    inventory_proof = None
    def build():
        nonlocal inventory_proof
        identities = {}
        from viewer_publication.native import prepare_native_output
        from viewer_publication import publish_filename_viewer as builder
        upgrade_options = dict(renderer_upgrade=True,resume_upgrade=resume_preparation) if renderer_upgrade else {}
        manifest, recovery = prepare_native_output(publisher, builder, client, snapshot, publication,
            accepted_record=as_protected(accepted),
            viewer_record=as_protected(previous),
            recovery_only=mode == 'recovery', preparation_binding=binding,
            resume_preparation=resume_preparation, stage_timings=timings, stage_event=progress,
            memory_metrics=metrics, **upgrade_options)
        for path, identity in native_inputs.items():
            identity.require(path)
        identities = dict(manifest.identities)
        proof = stage('renderer_inventory', lambda: issue_inventory(publication, identities, context=binding))
        stage('recovery_acceptance', lambda: publisher.prepare_recovery(publication, manifest,
            as_protected(accepted), validation=proof, index=recovery))
        stage('output_validation', lambda: publisher.validate_prepared_output(publication, manifest))
        for name in ('manifest.json', 'recovery-prepared.json'):
            identities[name] = file_identity(publication / name)
        inventory_proof = stage('preparation_inventory', lambda: issue_inventory(root,
            {'publication/' + relative: proof for relative, proof in identities.items()}, context=binding))
        return manifest
    saved=continuation.value['phases'].get('prepared')
    if saved is not None:
        inventory_proof=stage('retained_inventory_verification', lambda: verify_inventory(root,
            {name:dict(bytes=(root/name).stat().st_size,sha256=digest)
             for name,digest in saved['files'].items()},context=binding))
    progress(dict(event='preparation_started'))
    try:
        manifest = continuation.phase('prepared', build, files=lambda: [], inventory=lambda: inventory_proof)
    except BaseException as error:
        try:
            progress(dict(event='preparation_failed', error_type=type(error).__name__))
        except BaseException as diagnostic:
            error.add_note('Preparation diagnostic save failed: ' + type(diagnostic).__name__)
        raise
    progress(dict(event='prepared_phase_accepted'))
    inventory = inventory_proof.files
    has_receipt = (root / 'preparation.json').is_file()
    accepted_result = (root / 'prepared-result.json').is_file()
    if accepted_result and not has_receipt:
        raise ValueError('Accepted preparation receipt disappeared')
    if has_receipt:
        accepted_receipt=json.loads((root/'preparation.json').read_bytes())
        if accepted_receipt['binding']!=binding or accepted_receipt['files']!=inventory:
            raise ValueError('Accepted preparation inputs or inventory changed')
        plan=accepted_receipt['release_plan']
        producer = (accepted_receipt.get('artifact_producer',
            dict(run_id=binding['run_id'], run_attempt=binding['run_attempt'])) if accepted_result
            else dict(run_id=str(run_id), run_attempt=str(run_attempt)))
    else:
        plan = {'release': 'releases/' + uuid.uuid4().hex + '/', 'published_at': datetime.now(timezone.utc).isoformat()}
        producer = dict(run_id=str(run_id), run_attempt=str(run_attempt))
    receipt = {'version': 1, 'binding': binding, 'files': inventory, 'release_plan': plan,
               'compression_policy': manifest.get('compression_policy'), 'manifest_sha256': inventory['publication/manifest.json']['sha256']}
    if not accepted_result or 'artifact_producer' in accepted_receipt:
        receipt['artifact_producer'] = producer
    if has_receipt:
        expected_receipt = dict(receipt)
        if 'artifact_producer' in accepted_receipt:
            expected_receipt['artifact_producer'] = accepted_receipt['artifact_producer']
        else:
            expected_receipt.pop('artifact_producer', None)
        if accepted_receipt != expected_receipt:
            raise ValueError('Retained preparation receipt changed')
    receipt_bytes = publisher.encoded(receipt)
    receipt_digest = hashlib.sha256(receipt_bytes).hexdigest()
    # A receipt/result pair is accepted only after both files are complete.
    # An interrupted receipt alone keeps its release plan but takes the current
    # artifact producer. A completed pair is never rebound.
    stage('preparation_receipt', lambda: continuation.save('preparation.json', receipt_bytes,
        replace=has_receipt and not accepted_result))
    producer_run, producer_attempt = producer['run_id'], producer['run_attempt']
    result = {'status': 'prepared', 'mode': mode, 'preparation_sha256': receipt_digest,
              'artifact_name': f'viewer-prepared-{producer_run}-{producer_attempt}-{receipt_digest}',
              'attempt': f'{producer_run}-{producer_attempt}-{receipt_digest}', 'catalog_id': manifest['info']['catalog_id']}
    stage('prepared_result', lambda: continuation.save('prepared-result.json', publisher.encoded(result)))
    stage('accepted_preparation_verification', lambda: verify_prepared(publisher, root, validation=inventory_proof))
    progress(dict(event='preparation_completed', status='prepared'))
    return result


def verify_prepared(publisher, root, *, validation=None):
    """Verify every accepted output and exact stable selection/control custody."""
    receipt = json.loads((root / 'preparation.json').read_text())
    if receipt.get('version') != 1 or receipt['binding']['code_runtime'] != content_identity(publisher):
        raise ValueError('Prepared runtime, code or review identities changed')
    manifest = json.loads((root / 'publication/manifest.json').read_text())
    observed = publisher.validate_prepared_output(root / 'publication', manifest)
    if (receipt['manifest_sha256'] != receipt['files'].get('publication/manifest.json', {}).get('sha256')
            or receipt['compression_policy'] != manifest.get('compression_policy')
            or manifest['source_manifest'] != receipt['binding']['source']['value']):
        raise ValueError('Prepared policy or source selection changed')
    actual = {'publication/' + name for name in observed}
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
    producer = receipt.get('artifact_producer', receipt['binding'])
    run_id, run_attempt = producer['run_id'], producer['run_attempt']
    expected = {'status': 'prepared', 'mode': receipt['binding']['mode'], 'preparation_sha256': receipt_digest,
                'artifact_name': f'viewer-prepared-{run_id}-{run_attempt}-{receipt_digest}',
                'attempt': f'{run_id}-{run_attempt}-{receipt_digest}',
                'catalog_id': manifest['info']['catalog_id']}
    if result != expected:
        raise ValueError('Prepared receipt digest or attempt identity differs')
    protected = {name: as_protected(receipt['binding'][name]) for name in ('source', 'accepted', 'viewer')}
    plan = accept_viewer_plan(publisher, root / 'publication', manifest,
        validation=validation, context=receipt['binding'], protected=protected,
        source_pins=receipt['binding']['code_runtime'], release_plan=receipt['release_plan'],
        conditions=dict(previous_etag=protected['viewer'].etag, selected_etag=protected['source'].etag),
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
    if str(custody['run_id']) != receipt.get('artifact_producer', binding)['run_id']:
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
            # The durable pointer acknowledgment accepts this completed write.
            # Reuse its prepared status and keep only the bounded pointer smoke test.
            index = verified.plan.require(root / 'publication', manifest).recovery
            with publisher.open_public(publisher.public_request(public_url + 'manifest.json')) as response:
                if json.loads(publisher.public_control(response)) != pointer:
                    raise ValueError('Public recovery pointer differs after reconciliation')
            guard()
            result = publisher.recovery_result(pointer, index, publisher.validated_accepted(binding['accepted']['value']),
                                               status='recovery_updated')
        elif binding['mode'] == 'recovery':
            pointer_record = as_protected(binding['viewer'])
            selected_record = as_protected(binding['source'])
            accepted_record = as_protected(binding['accepted'])
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
