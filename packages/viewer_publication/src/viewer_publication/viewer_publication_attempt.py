"""Accepted preparation and explicit durable publication attempts for the viewer."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone

from viewer_publication.guarded_recovery_publication_client import ContinuedPublicationClient
from viewer_publication.recovery_publication_continuation import Continuation, DurableJournal, MissingPublicationJournal, sha256
from congress_api.retention.derived_files import file_identity
from congress_api.retention.viewer_inventory import verify_inventory, issue_inventory, InventoryValidation


class PreparedVerification(tuple):
    def __new__(cls, receipt, manifest, result, validation):
        value = super().__new__(cls, (receipt, manifest, result))
        value.validation = validation
        return value


class Superseded(ValueError):
    pass


def content_identity(publisher):
    return publisher.full_release_identity()


def record_input(publisher, client, key, optional=False):
    value, etag, modified, digest = publisher.read_identity(client, key, optional=optional)
    return {'value': value, 'etag': etag, 'modified': modified, 'sha256': digest}


def prepare(publisher, client, root, *, run_id, run_attempt, public_url):
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
    binding['mode'] = mode
    continuation = Continuation(root, binding)
    publication = root / 'publication'
    inventory_proof = None
    def build():
        nonlocal inventory_proof
        identities = {}
        if mode == 'recovery':
            pointer = previous['value']
            manifest, _, _ = publisher.read_json(client, publisher.PREFIX + pointer['manifest'])
            release = str(PurePosixPath(pointer['manifest']).parent) + '/'
            for name in ('filenames', 'groups'):
                item = manifest['files'][name]
                path = publication / item['path']
                if not path.resolve().is_relative_to(publication.resolve()):
                    raise ValueError('Invalid prepared recovery path')
                path.parent.mkdir(parents=True, exist_ok=True)
                client.download_file(publisher.BUCKET, publisher.PREFIX + release + item['path'], str(path))
            # Accept the complete status once. The original table identities stay
            # bound in that status; the recovery artifact needs only its output.
            input_proof = verify_inventory(publication,
                {manifest['files'][name]['path']: manifest['files'][name] for name in ('filenames', 'groups')},
                context=binding)
            publisher.prepare_recovery(publication, manifest,
                tuple(accepted[k] for k in ('value', 'etag', 'modified', 'sha256')), validation=input_proof)
            for name in ('filenames', 'groups'):
                (publication / manifest['files'][name]['path']).unlink()
        else:
            import importlib.util
            spec = importlib.util.spec_from_file_location('prepared_viewer_builder', Path(publisher.__file__).with_name('publish-filename-viewer.py'))
            builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
            with tempfile.TemporaryDirectory(prefix='viewer-source-', dir=root.parent) as folder:
                source = Path(folder)
                (source / 'indexes').mkdir()
                (source / 'indexes/catalog.json').write_bytes(publisher.encoded(selected['value']))
                for item in selected['value']['files'].values():
                    key = item['key']
                    if not key.startswith('catalog-generations/' + selected['value']['generation'] + '/') or '..' in PurePosixPath(key).parts:
                        raise ValueError('Invalid immutable source location')
                    path = source / key; path.parent.mkdir(parents=True, exist_ok=True)
                    client.download_file(publisher.BUCKET, key, str(path))
                manifest = builder.publish(source, publication, selected['modified'])
                identities = dict(getattr(manifest, 'identities', {}))
                proof = (issue_inventory(publication, identities, context=binding) if identities else
                         verify_inventory(publication, {str(p.relative_to(publication)): None for p in publication.rglob('*') if p.is_file()}, context=binding))
                identities = dict(proof.identities)
                publisher.prepare_recovery(publication, manifest,
                    tuple(accepted[k] for k in ('value', 'etag', 'modified', 'sha256')), validation=proof)
        publisher.validate_prepared_output(publication, manifest)
        (publication / 'manifest.json').write_bytes(publisher.encoded(manifest))
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
              'attempt': f'{run_id}-{run_attempt}-{receipt_digest}', 'catalog_id': selected['value']['catalog_id']}
    continuation.save('prepared-result.json', publisher.encoded(result))
    verify_prepared(publisher, root, validation=inventory_proof)
    return result


def verify_prepared(publisher, root, *, validation=None):
    """Verify every accepted output including all 256 source-ID shard hashes."""
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
    if receipt['binding']['mode'] == 'full':
        publisher.prepared_files(root / 'publication', manifest, validation=validation)
    continuation = Continuation(root, receipt['binding'], resume=True)
    continuation.phase('prepared', lambda: (_ for _ in ()).throw(ValueError('Missing accepted preparation')),
                       files=lambda: [], inventory=lambda: validation)
    result = json.loads((root / 'prepared-result.json').read_text())
    receipt_digest = sha256(root / 'preparation.json')
    run_id, run_attempt = receipt['binding']['run_id'], receipt['binding']['run_attempt']
    expected = {'status': 'prepared', 'mode': receipt['binding']['mode'], 'preparation_sha256': receipt_digest,
                'artifact_name': f'viewer-prepared-{run_id}-{run_attempt}-{receipt_digest}',
                'attempt': f'{run_id}-{run_attempt}-{receipt_digest}',
                'catalog_id': receipt['binding']['source']['value']['catalog_id']}
    if result != expected:
        raise ValueError('Prepared receipt digest or attempt identity differs')
    return PreparedVerification(receipt, manifest, result, validation)


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


def resume_descriptor(artifact, run, repository):
    name = artifact.get('name', '')
    match = re.fullmatch(r'viewer-prepared-([0-9]+)-([0-9]+)-([a-f0-9]{64})', name)
    if not match or match[1] != str(run.get('id')):
        raise ValueError('Artifact name does not identify the original preparation run')
    result = {'version': 1, 'revision': run.get('head_sha'), 'run_id': str(run['id']),
              'run_attempt': match[2], 'artifact_id': str(artifact.get('id', '')),
              'artifact_digest': artifact.get('digest', '').removeprefix('sha256:'),
              'artifact_name': name, 'attempt': '-'.join(match.groups()), 'repository': repository}
    return validate_resume_descriptor(result)


def validate_resume_descriptor(value):
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1:
        raise ValueError('Unsupported resume descriptor version')
    for name, pattern in (('revision', r'[a-f0-9]{40}'), ('run_id', r'[0-9]+'),
            ('run_attempt', r'[0-9]+'), ('artifact_id', r'[0-9]+'),
            ('artifact_digest', r'[a-f0-9]{64}'), ('repository', r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')):
        if not isinstance(value.get(name), str) or not re.fullmatch(pattern, value[name]):
            raise ValueError('Invalid resume descriptor field: ' + name)
    match = re.fullmatch(r'viewer-prepared-([0-9]+)-([0-9]+)-([a-f0-9]{64})', value.get('artifact_name', ''))
    if (not match or match[1] != value['run_id'] or match[2] != value['run_attempt']
            or value.get('attempt') != '-'.join(match.groups())):
        raise ValueError('Resume descriptor attempt/name/run fields differ')
    return value


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
    def after_write(key, version):
        if key in versions:
            versions[key] = version
            continuation.flush()
    class PublicationGuard:
        def check(self):
            # Immutable, conditional writes may leave unselected files if inputs
            # advance. Their exact prepared bytes and unique release/digest names
            # do not depend on a fresh mutable selector.
            return None
        def shared_commit(self):
            guard()
    guarded = ContinuedPublicationClient(client, continuation=continuation, guard=PublicationGuard(), journal=journal.record, after_write=after_write)
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
                index=publisher.load_prepared_recovery(root / 'publication', manifest, accepted_record,
                                                       validation=verified.validation))
        else:
            result = publisher.upload(guarded, root / 'publication', manifest,
                previous_etag=binding['viewer']['etag'], selected_etag=binding['source']['etag'], public_url=public_url,
                publication_plan=receipt['release_plan'], validation=verified.validation,
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
