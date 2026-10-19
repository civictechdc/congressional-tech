"""Conditionally publish recovery mappings through an injected S3 client.

The caller owns the lock, cloud/input/source guards and a client with SDK
write retries disabled. This does not advance the public viewer pointer.
"""
import hashlib
import json

from corpus_recovery.merge_corpus_recovery_mappings import merge_mappings
from viewer_publication.lost_acknowledgment import reconcile_lost_acknowledgment

KEY = 'viewer-publications/recoveries/accepted.json'


def publish_mappings(client, *, bucket, baseline, prepared, validate,
                     guard, save_payload, journal):
    def read():
        response = client.get_object(Bucket=bucket, Key=KEY)
        with response['Body'] as stream:
            raw = stream.read()
        if len(raw) != response['ContentLength']:
            raise ValueError('Incomplete recovery mapping read')
        return raw, response['ETag']

    def canonical(document):
        return {**document, 'recoveries': validate(document['recoveries'])}

    guard()
    previous, expected = read()
    fresh = json.loads(previous)
    # Store exactly the viewer validator's canonical rows: the viewer publisher
    # requires accepted_rows() of the stored mapping to equal the stored mapping,
    # and batch evidence fields (local body paths, candidates) must stay in local
    # batch evidence, not in this public object. Comparing canonical inputs also
    # lets a previously non-canonical mapping be rewritten without conflicts.
    merged = canonical(merge_mappings(canonical(baseline), canonical(prepared), canonical(fresh)))
    if merged == fresh:
        return dict(complete=True, wrote=False, etag=expected,
                    sha256=hashlib.sha256(previous).hexdigest())
    payload = (json.dumps(merged, sort_keys=True, separators=(',', ':')) + '\n').encode()
    save_payload('accepted-before.json', previous)
    save_payload('accepted-proposed.json', payload)
    intent = dict(key=KEY, expected_etag=expected,
                  sha256=hashlib.sha256(payload).hexdigest())
    journal('mapping_write_intent', intent)
    guard()

    def put():
        return client.put_object(Bucket=bucket, Key=KEY, Body=payload,
                                 ContentType='application/json', IfMatch=expected)

    # A guarded client already verified this PUT and returns a receipt. Consume
    # that receipt instead of reading the body again. A plain client reconciles
    # a lost acknowledgment from exact bytes and never sends a second PUT.
    if callable(getattr(client, 'confirm_transfer', None)):
        response = put()
        receipt = response.get('_verified_transfer') if isinstance(response, dict) else None
        if receipt is None or not client.confirm_transfer(
                receipt, bucket=bucket, key=KEY, size=len(payload), sha256=intent['sha256']):
            raise ValueError('Recovery mapping readback differs from proposed bytes')
        version = receipt.etag
        reconciled = False
    else:
        def read_exact():
            actual, _version = read()
            return actual

        reconciled = reconcile_lost_acknowledgment(put, read_exact, payload)
        if reconciled:
            journal('mapping_acknowledgment_reconciled', intent)
        actual, version = read()
        if actual != payload:
            raise ValueError('Recovery mapping readback differs from proposed bytes')
    result = dict(complete=True, wrote=True, etag=version,
                  sha256=intent['sha256'], acknowledgment_reconciled=reconciled,
                  rows=len(merged['recoveries']), viewer_pointer_advanced=False)
    journal('mapping_readback_verified', result)
    return result
