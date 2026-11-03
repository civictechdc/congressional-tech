"""Run the reader gates before committing the one conditional public pointer."""
import re

from viewer_publication.client import publish_manifest_pointer
from viewer_publication.archive_comparison_acceptance import require_comparison


def qualified_target_status(status,manifest_origin=None):
    """Admitted model releases may use candidate-bound emulation or a recorded owner deferral."""
    return status in {'owner-approved','deferred'} or (status=='provisional-emulated'
        and isinstance(manifest_origin,dict)
        and manifest_origin.get('kind')=='model' and manifest_origin.get('display_only') is not True)


def validate_receipt(receipt, *, release_id, name, manifest_origin=None):
    """Require the measured reader result for this exact candidate."""
    if not isinstance(receipt, dict) or receipt.get('status') != 'passed' or receipt.get('releaseId') != release_id:
        raise ValueError(f'Archive {name} did not pass for the candidate')
    if not qualified_target_status(receipt.get('targets'),manifest_origin):
        raise ValueError(f'Archive {name} requires measured-target qualification')


def gate_and_flip(client, *, bucket, release_id, previous_release_id, expected_etag, canary, contract,manifest_origin=None,comparison_acceptance=None):
    """Callbacks run the shipped reader checks; any refusal prevents the flip.

    The caller pins the outgoing pointer and its ETag before preparation. Reusing
    that ETag here detects a concurrent publication instead of overwriting it.
    The first engine release can replace the legacy pointer with its observed
    ETag even though that pointer names no previous engine release.
    """
    require_comparison(comparison_acceptance)
    for value in [release_id, previous_release_id]:
        if value is not None and not re.fullmatch('[a-f0-9]{64}', value):
            raise ValueError('Invalid release ID')
    if (release_id is None or previous_release_id is not None and expected_etag is None
            or expected_etag is not None and (not isinstance(expected_etag, str) or not expected_etag.strip())):
        raise ValueError('Outgoing release and pointer ETag must be pinned together')
    # Admit the local candidate before the publisher uploads and probes HTTPS.
    for name, check in [('contract', contract), ('canary', canary)]:
        validate_receipt(check(), release_id=release_id, name=name,manifest_origin=manifest_origin)
        require_comparison(comparison_acceptance)
    require_comparison(comparison_acceptance)
    pointer={'release_id': release_id, 'previous_release_id': previous_release_id}
    try:
        transfer=publish_manifest_pointer(client, bucket=bucket, pointer=pointer, expected_etag=expected_etag)
        if not isinstance(transfer.etag,str) or not transfer.etag.strip():
            raise ValueError('Pointer PUT returned no ETag')
        return transfer
    except Exception as error:
        # The conditional PUT may have committed before its response was lost.
        # Only the exact selected pointer and its observed ETag settle that uncertainty.
        try:
            from viewer_publication.archive_publish import read_pointer
            selected,etag=read_pointer(client,bucket=bucket)
        except Exception as read_error:
            error.add_note('Pointer reconciliation failed: '+type(read_error).__name__)
            raise error
        if selected!=pointer:
            raise
        from viewer_publication.client import VerifiedTransfer
        import hashlib
        import json
        raw=json.dumps(pointer,ensure_ascii=False,sort_keys=True,separators=(',', ':'),allow_nan=False).encode('utf-8')
        return VerifiedTransfer(bucket=bucket,key='viewer-publications/manifest.json',bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),etag=etag,reconciled=True)
