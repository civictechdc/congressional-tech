"""Conditionally publish recovery mappings through an injected S3 client.

The caller owns the lock, cloud/input/source guards and a client with SDK
write retries disabled. This does not advance the public viewer pointer.
"""
import hashlib
import json

from merge_corpus_recovery_mappings import merge_mappings

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

    guard()
    previous, expected = read()
    fresh = json.loads(previous)
    merged = merge_mappings(baseline, prepared, fresh)
    # Validate with the maintained viewer validator without dropping fields.
    validate(merged['recoveries'])
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
    reconciled = False
    try:
        client.put_object(Bucket=bucket, Key=KEY, Body=payload,
                          ContentType='application/json', IfMatch=expected)
    except Exception:
        actual, _ = read()
        if actual != payload:
            raise
        reconciled = True
        journal('mapping_acknowledgment_reconciled', intent)
    actual, version = read()
    if actual != payload:
        raise ValueError('Recovery mapping readback differs from proposed bytes')
    result = dict(complete=True, wrote=True, etag=version,
                  sha256=intent['sha256'], acknowledgment_reconciled=reconciled,
                  rows=len(merged['recoveries']), viewer_pointer_advanced=False)
    journal('mapping_readback_verified', result)
    return result
