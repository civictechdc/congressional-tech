"""Run the reader gates before committing the one conditional public pointer."""
import re

from viewer_publication.client import publish_manifest_pointer


def qualified_target_status(status,manifest_origin=None):
    """Admitted seed and model releases may use candidate-bound emulation."""
    return status=='owner-approved' or (status=='provisional-emulated'
        and isinstance(manifest_origin,dict) and (
            manifest_origin.get('kind')=='seed_v5' and manifest_origin.get('display_only') is True
            or manifest_origin.get('kind')=='model' and manifest_origin.get('display_only') is not True))


def validate_receipt(receipt, *, release_id, name, manifest_origin=None):
    """Require the measured reader result for this exact candidate."""
    if not isinstance(receipt, dict) or receipt.get('status') != 'passed' or receipt.get('releaseId') != release_id:
        raise ValueError(f'Archive {name} did not pass for the candidate')
    if not qualified_target_status(receipt.get('targets'),manifest_origin):
        raise ValueError(f'Archive {name} requires measured-target qualification')


def gate_and_flip(client, *, bucket, release_id, previous_release_id, expected_etag, canary, contract,manifest_origin=None):
    """Callbacks run the shipped reader checks; any refusal prevents the flip.

    The caller pins the outgoing pointer and its ETag before preparation. Reusing
    that ETag here detects a concurrent publication instead of overwriting it.
    The first engine release can replace the legacy pointer with its observed
    ETag even though that pointer names no previous engine release.
    """
    for value in [release_id, previous_release_id]:
        if value is not None and not re.fullmatch('[a-f0-9]{64}', value):
            raise ValueError('Invalid release ID')
    if (release_id is None or previous_release_id is not None and expected_etag is None
            or expected_etag is not None and (not isinstance(expected_etag, str) or not expected_etag.strip())):
        raise ValueError('Outgoing release and pointer ETag must be pinned together')
    # Admit the local candidate before the publisher uploads and probes HTTPS.
    for name, check in [('contract', contract), ('canary', canary)]:
        validate_receipt(check(), release_id=release_id, name=name,manifest_origin=manifest_origin)
    return publish_manifest_pointer(client, bucket=bucket,
        pointer={'release_id': release_id, 'previous_release_id': previous_release_id}, expected_etag=expected_etag)
