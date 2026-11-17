"""A client that sat idle past a hosted runner's NAT timeout must not reuse its pooled sockets."""
from io import BytesIO

import boto3
from botocore.stub import Stubber
import pytest

from viewer_publication.client import IDLE_SECONDS, evict_idle_connections, idle_evicting


@pytest.fixture
def s3():
    """A real SDK client with stubbed responses: its own events fire, no socket opens."""
    client = boto3.client('s3', region_name='auto', endpoint_url='https://r2.invalid',
                          aws_access_key_id='k', aws_secret_access_key='s')
    closed = []
    client.close = lambda: closed.append(True)
    stub = Stubber(client)
    for _ in range(8):
        stub.add_response('get_object', dict(Body=BytesIO(b'x'), ContentLength=1))
    stub.activate()
    return client, closed


def test_a_call_after_a_long_silence_first_drops_the_pool_and_a_busy_client_keeps_it(s3):
    client, closed = s3
    now = [1000.0]
    assert evict_idle_connections(client, clock=lambda: now[0]) is client
    get = lambda: client.get_object(Bucket='b', Key='k')
    get(); now[0] += IDLE_SECONDS; get()            # exactly the allowance: still warm
    assert closed == []
    now[0] += IDLE_SECONDS + 1; get()               # the model build, the daily producers
    assert closed == [True]
    now[0] += 5; get(); now[0] += 5; get()          # in use again: nothing more is dropped
    assert closed == [True]
    now[0] += 1200; get()
    assert closed == [True, True]


def test_the_silence_is_measured_from_the_end_of_the_last_call(s3):
    client, closed = s3
    now = [0.0]
    evict_idle_connections(client, clock=lambda: now[0])
    def slow(**_):
        now[0] += 300                                # a slow response is activity, not silence
    client.meta.events.register_first('after-call.s3', slow)
    client.get_object(Bucket='b', Key='k'); now[0] += 10; client.get_object(Bucket='b', Key='k')
    assert closed == []


def test_no_request_is_repeated_and_registering_twice_changes_nothing(s3):
    client, closed = s3
    now = [0.0]
    evict_idle_connections(evict_idle_connections(client, clock=lambda: now[0]), clock=lambda: now[0])
    calls = []
    client.meta.events.register('before-parameter-build.s3', lambda **_: calls.append(1))
    now[0] += 500; client.get_object(Bucket='b', Key='k')
    assert calls == [1] and closed == [True]


def test_a_factory_wraps_every_client_it_makes_and_passes_fakes_through():
    made = []
    class Fake:                                      # the publish job's test doubles have no SDK events
        pass
    def factory(**request):
        made.append(request)
        return Fake()
    connect = idle_evicting(factory)
    client = connect(bucket='b', retries={'total_max_attempts': 1})
    assert isinstance(client, Fake) and made == [dict(bucket='b', retries={'total_max_attempts': 1})]
