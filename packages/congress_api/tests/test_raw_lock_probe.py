"""B1: the lock's actual HTTP semantics decide the writer, before any raw lock."""
from botocore.exceptions import ClientError
import pytest


class LockedBucket:
    def __init__(self, conditional_status=412):
        self.conditional_status = conditional_status
        self.keys, self.calls, self.uploads = set(), [], {}

    def put_object(self, **args):
        self.calls.append('put')
        if args['Key'] in self.keys:
            self.fail(self.conditional_status if args.get('IfNoneMatch') else 403)
        self.keys.add(args['Key'])
        return self.response(200)

    @staticmethod
    def response(status):
        return {'ResponseMetadata': {'HTTPStatusCode': status}, 'ETag': 'test'}

    @staticmethod
    def fail(status):
        raise ClientError({'Error': {'Code': str(status)},
                           'ResponseMetadata': {'HTTPStatusCode': status}}, 'probe')

    def delete_object(self, **args):
        self.calls.append('delete')
        self.fail(403)

    def create_multipart_upload(self, **args):
        self.calls.append('multipart_create')
        self.uploads[args['Key']] = True
        return dict(self.response(200), UploadId='upload')

    def upload_part(self, **args):
        return self.response(200)

    def complete_multipart_upload(self, **args):
        if args['Key'] in self.keys:
            self.fail(403)
        self.keys.add(args['Key'])
        return self.response(200)

    def abort_multipart_upload(self, **args):
        self.calls.append('multipart_abort')
        return self.response(204)


def test_probe_records_all_statuses_and_the_412_decision():
    from congress_api.retention.lock_probe import probe
    result = probe(LockedBucket(), 'cx-engine-first-lock-probe-test', run_id='fixture')
    assert result['statuses'] == dict(create=200, create_existing=412, overwrite=403,
                                     delete=403, multipart_create=200,
                                     multipart_complete=200, multipart_overwrite=403)
    assert result['safe_to_lock'] is True


def test_lock_denial_before_conditional_evaluation_requires_a_rule_change():
    from congress_api.retention.lock_probe import probe
    result = probe(LockedBucket(conditional_status=403),
                   'cx-engine-first-lock-probe-test', run_id='fixture')
    assert result['safe_to_lock'] is False
    assert 'B3' in result['decision'] and '7.1' in result['decision']


@pytest.mark.parametrize('bucket', ['congressional-tech-raw', 'other', '', '../raw'])
def test_probe_refuses_every_non_probe_bucket_before_io(bucket):
    from congress_api.retention.lock_probe import probe
    client = LockedBucket()
    with pytest.raises(ValueError, match='scratch bucket'):
        probe(client, bucket)
    assert client.calls == []
