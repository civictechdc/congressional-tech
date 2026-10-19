"""Merge recovery mapping additions and conditionally publish them.

``merge_mappings`` performs no network calls. ``publish_mappings`` requires an
injected S3 client with SDK write retries disabled and does not advance the
public viewer pointer.
"""
import hashlib
import json
from copy import deepcopy

from congress_api.retention.control_documents import CONTROL_LIMITS, bounded_control_read
from corpus_recovery.acknowledge import reconcile_lost_acknowledgment

KEY = 'viewer-publications/recoveries/accepted.json'


def merge_mappings(baseline, prepared, fresh):
    def index(document):
        if document.get('version') != 1:
            raise ValueError('Unsupported recovery mapping version')
        result = {}
        for row in document['recoveries']:
            url = row['original_url']
            if url in result:
                raise ValueError('Duplicate recovery URL: ' + url)
            result[url] = row
        return result

    before, desired, current = map(index, (baseline, prepared, fresh))
    for url, row in before.items():
        if desired.get(url) != row:
            raise ValueError('Prepared mapping changes a baseline recovery: ' + url)
    additions = {url: row for url, row in desired.items() if url not in before}
    for url, row in additions.items():
        if url in current and current[url] != row:
            raise ValueError('Fresh mapping conflicts with new recovery: ' + url)
    result = deepcopy(fresh)
    result['recoveries'] = [deepcopy(row) for _, row in
                            sorted((current | additions).items())]
    return result


def publish_mappings(client, *, bucket, baseline, prepared, validate,
                     guard, save_payload, journal):
    def read():
        response = client.get_object(Bucket=bucket, Key=KEY)
        with response['Body'] as stream:
            raw = bounded_control_read(stream, kind='accepted', declared=response['ContentLength'],
                                       expected=response['ContentLength'])
        if not isinstance(response['ETag'], str) or not response['ETag']:
            raise ValueError('Recovery mapping is missing its object version')
        return raw, response['ETag']

    def canonical(document):
        if (not isinstance(document, dict) or type(document.get('version')) is not int
                or document['version'] != 1 or not isinstance(document.get('recoveries'), list)):
            raise ValueError('Invalid recovery mapping document')
        return {**document, 'recoveries': validate(document['recoveries'])}

    guard()
    previous, expected = read()
    fresh = json.loads(previous)
    merged = canonical(merge_mappings(canonical(baseline), canonical(prepared), canonical(fresh)))
    if merged == fresh:
        return dict(complete=True, wrote=False, etag=expected,
                    sha256=hashlib.sha256(previous).hexdigest())
    payload = (json.dumps(merged, sort_keys=True, separators=(',', ':')) + '\n').encode()
    if len(payload) > CONTROL_LIMITS['accepted']:
        raise ValueError('Recovery mapping exceeds the accepted control byte limit')
    save_payload('accepted-before.json', previous)
    save_payload('accepted-proposed.json', payload)
    intent = dict(key=KEY, expected_etag=expected,
                  sha256=hashlib.sha256(payload).hexdigest())
    journal('mapping_write_intent', intent)
    guard()

    def put():
        return client.put_object(Bucket=bucket, Key=KEY, Body=payload,
                                 ContentType='application/json', IfMatch=expected)

    readback = None
    reconciled = False
    if callable(getattr(client, 'confirm_transfer', None)):
        # Guarded clients already own their PUT/readback/error reconciliation.
        response = put()
        receipt = response.get('_verified_transfer') if isinstance(response, dict) else None
        if receipt is not None and client.confirm_transfer(
                receipt, bucket=bucket, key=KEY, size=len(payload), sha256=intent['sha256']):
            version = receipt.etag
        else:
            readback = read()
    else:
        def read_exact():
            nonlocal readback
            readback = read()
            return readback[0]

        reconciled = reconcile_lost_acknowledgment(put, read_exact, payload)
        if reconciled:
            journal('mapping_acknowledgment_reconciled', intent)
        else:
            readback = read()
    if readback is not None:
        actual, version = readback
        if actual != payload:
            raise ValueError('Recovery mapping readback differs from proposed bytes')
    result = dict(complete=True, wrote=True, etag=version,
                  sha256=intent['sha256'], acknowledgment_reconciled=reconciled,
                  rows=len(merged['recoveries']), viewer_pointer_advanced=False)
    journal('mapping_readback_verified', result)
    return result
