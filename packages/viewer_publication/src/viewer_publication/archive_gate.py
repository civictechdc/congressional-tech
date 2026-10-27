"""Run the reader gates before committing the one conditional public pointer."""
import re

from viewer_publication.client import publish_manifest_pointer


def gate_and_flip(client, *, bucket, release_id, previous_release_id, expected_etag, canary, contract):
    """Callbacks run the shipped reader checks; any refusal prevents the flip.

    The caller pins the outgoing pointer and its ETag before preparation. Reusing
    that ETag here detects a concurrent publication instead of overwriting it.
    """
    for value in [release_id, previous_release_id]:
        if value is not None and not re.fullmatch('[a-f0-9]{64}', value):
            raise ValueError('Invalid release ID')
    if release_id is None or bool(previous_release_id) != bool(expected_etag):
        raise ValueError('Outgoing release and pointer ETag must be pinned together')
    # Admit the local candidate before the publisher uploads and probes HTTPS.
    for name, check in [('contract', contract), ('canary', canary)]:
        receipt = check()
        if not isinstance(receipt, dict) or receipt.get('status') != 'passed' or receipt.get('releaseId') != release_id:
            raise ValueError(f'Archive {name} did not pass for the candidate')
    return publish_manifest_pointer(client, bucket=bucket,
        pointer={'release_id': release_id, 'previous_release_id': previous_release_id}, expected_etag=expected_etag)
