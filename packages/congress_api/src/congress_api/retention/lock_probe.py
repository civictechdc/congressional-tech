"""Observe a scratch bucket's lock semantics; never configure a lock or touch raw."""
import base64
import hashlib
import re
from uuid import uuid4

from botocore.exceptions import ClientError

SCRATCH_BUCKET = re.compile(r'cx-engine-first-lock-probe-[a-z0-9][a-z0-9-]*')
EXPECTED = dict(create=200, create_existing=412, overwrite=403, delete=403,
                multipart_create=200, multipart_complete=200, multipart_overwrite=403)


def validate_bucket(bucket):
    if not SCRATCH_BUCKET.fullmatch(bucket):
        raise ValueError('Use a dedicated cx-engine-first-lock-probe-* scratch bucket')


def probe(client, bucket, *, run_id=None):
    """Record HTTP results against an already locked, disposable prefix. O(1) requests."""
    validate_bucket(bucket)
    run_id = run_id or uuid4().hex
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
        raise ValueError('Invalid probe run ID')
    key = f'bodies/lock-probe/{run_id}'
    payload = b'engine-first lock probe\n'
    args = dict(Bucket=bucket, Key=key, Body=payload,
                ContentMD5=base64.b64encode(hashlib.md5(payload).digest()).decode())
    statuses = {}

    def observe(name, method, **request):
        try:
            result = method(**request)
        except ClientError as error:
            statuses[name] = error.response['ResponseMetadata']['HTTPStatusCode']
            return None
        statuses[name] = result['ResponseMetadata']['HTTPStatusCode']
        return result

    observe('create', client.put_object, **args, IfNoneMatch='*')
    if statuses['create'] != 200:
        raise ValueError('Scratch create failed; check the bucket, credential and prefix lock')
    observe('create_existing', client.put_object, **args, IfNoneMatch='*')
    observe('overwrite', client.put_object, **args)
    observe('delete', client.delete_object, Bucket=bucket, Key=key)
    # Initiation does not establish whether the completed object respects locks.
    # Probe completion at both a fresh key and an existing locked key.
    for target, completion in ((key + '-multipart', 'multipart_complete'),
                               (key, 'multipart_overwrite')):
        initiated = observe('multipart_create' if completion == 'multipart_complete'
                            else 'multipart_existing_create',
                            client.create_multipart_upload, Bucket=bucket, Key=target)
        if initiated is None:
            continue
        request = dict(Bucket=bucket, Key=target, UploadId=initiated['UploadId'])
        try:
            part = client.upload_part(**request, PartNumber=1, Body=payload,
                                     ContentMD5=args['ContentMD5'])
            observe(completion, client.complete_multipart_upload, **request,
                    MultipartUpload={'Parts': [{'PartNumber': 1, 'ETag': part['ETag']}]})
        finally:
            if not 200 <= statuses.get(completion, 0) < 300:
                client.abort_multipart_upload(**request)
    # Keep the required observations concise; the existing-key initiation's
    # status is relevant only if it prevented observing completion.
    if statuses.get('multipart_existing_create') == 200:
        statuses.pop('multipart_existing_create')
    safe = statuses == EXPECTED
    decision = ('Expected semantics observed; owner may review and lock the raw prefixes.'
                if safe else 'Do not lock raw: revise B3 and ARCH §7.1 if the existing-key '
                'create-only PUT is not 412; investigate every other unexpected status.')
    return dict(bucket=bucket, key=key, expected=EXPECTED, statuses=statuses,
                safe_to_lock=safe, decision=decision)
