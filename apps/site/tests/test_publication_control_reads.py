"""Complete control reads enforce both declared and streamed byte bounds."""
import importlib.util
import io
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('bounded_publisher', Path(__file__).resolve().parents[3] / 'apps/site/scripts/publish-viewer-r2.py')
publisher = importlib.util.module_from_spec(spec); spec.loader.exec_module(publisher)


@pytest.mark.parametrize('status,attempt_count', [(404, 1), (503, 4)])
def test_terminal_public_http_errors_close_every_body_without_changing_retries(monkeypatch, status, attempt_count):
    errors, sleeps = [], []
    def fail(request, **kwargs):
        error = publisher.urllib.error.HTTPError(request.full_url, status, 'Failed', {}, io.BytesIO(b'error'))
        errors.append(error)
        raise error
    monkeypatch.setattr(publisher.urllib.request, 'urlopen', fail)
    monkeypatch.setattr(publisher.time, 'sleep', sleeps.append)
    with pytest.raises(publisher.urllib.error.HTTPError) as caught:
        publisher.open_public(publisher.public_request('https://data.test/manifest.json'))
    assert caught.value is errors[-1]
    assert len(errors) == attempt_count and all(error.fp.closed for error in errors)
    assert sleeps == ([1, 2, 4] if attempt_count == 4 else [])


def test_public_body_failure_propagates_without_reopening_and_caller_closes(monkeypatch):
    failure = OSError('body interrupted')
    class Broken(io.BytesIO):
        headers = {}
        def read(self, *args):
            raise failure
    body = Broken(b'body')
    opens = []
    monkeypatch.setattr(publisher.urllib.request, 'urlopen', lambda *a, **kw: opens.append(True) or body)
    monkeypatch.setattr(publisher.time, 'sleep', lambda *a: pytest.fail('Body failure retried'))
    with pytest.raises(OSError) as caught:
        with publisher.open_public(publisher.public_request('https://data.test/manifest.json')) as response:
            publisher.public_control(response)
    assert caught.value is failure and opens == [True] and body.closed

@pytest.mark.parametrize('raw,declared,expected,match', [
    (b'123', 100, None, 'declared'), (b'123456789', None, None, 'Oversized'),
    (b'123', 4, None, 'Incomplete'), (b'1234', 3, None, 'Incomplete'),
    (b'1234', None, 3, 'Oversized'), (b'12', None, 3, 'Incomplete'),
    (b'123', 'bad', None, 'Invalid'), (b'', -1, None, 'declared'),
])
def test_bounded_complete_read_rejects_bad_lengths(monkeypatch, raw, declared, expected, match):
    monkeypatch.setitem(publisher.CONTROL_LIMITS, 'manifest', 8)
    with pytest.raises(ValueError, match=match):
        publisher.bounded_control_read(io.BytesIO(raw), declared=declared, expected=expected)


def test_r2_body_closes_for_malformed_truncated_and_oversized_response(monkeypatch):
    monkeypatch.setitem(publisher.CONTROL_LIMITS, 'manifest', 8)
    for raw, declared in [(b'{', 1), (b'{}', 3), (b'oversized', 9), (b'{}', 2)]:
        body = io.BytesIO(raw)
        class Client:
            def get_object(self, **kwargs):
                return {'Body': body, 'ContentLength': declared, 'ETag': 'e',
                        'LastModified': __import__('datetime').datetime.now()}
        if raw == b'{}' and declared == 2:
            assert publisher.read_identity(Client(), 'indexes/catalog.json')[0] == {}
        else:
            with pytest.raises(ValueError):
                publisher.read_identity(Client(), 'indexes/catalog.json')
        assert body.closed


def test_separate_input_reads_do_not_claim_atomic_exclusion(monkeypatch):
    selected = ({'catalog_id': 'old'}, 'source-v1', 'time', 'digest')
    accepted = (None, None, None, None)
    pointer = ({'catalog_id': 'old'}, 'viewer-v1', 'time', 'digest')
    calls = []
    source = {'current': selected}
    def read(client, key, **kwargs):
        calls.append(key)
        if key == 'indexes/catalog.json':
            return source['current']
        if key == publisher.ACCEPTED_KEY:
            source['current'] = ({'catalog_id':'new'}, 'source-v2', 'time', 'other')
            return accepted
        return pointer
    monkeypatch.setattr(publisher, 'read_identity', read)
    # This passes despite a source advance after its read. The final viewer CAS
    # fences viewer writers only; separate input objects are not a transaction.
    publisher.check_recovery_inputs(object(), selected, accepted, pointer)
    assert source['current'] != selected
    assert calls == ['indexes/catalog.json', publisher.ACCEPTED_KEY, publisher.PREFIX+'manifest.json']


def test_oversized_recovery_json_refuses_before_remote_put(monkeypatch):
    monkeypatch.setitem(publisher.CONTROL_LIMITS,'recovery',4)
    class Client:
        def put_object(self,**kwargs):pytest.fail('oversized mutation')
    with pytest.raises(ValueError,match='before upload'):
        publisher.store_recovery_index(Client(),{'long':'value'})
