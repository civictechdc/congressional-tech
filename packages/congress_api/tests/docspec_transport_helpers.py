"""Exercise the real HTTP adapter against controlled test-only transports."""
import os

from congress_api.retention.docspec_host import Host


class TestHost(Host):
    """Test double for Host that binds directly to a mock HTTP client without spawning a daemon."""

    def __init__(self, client, *, timeout=120):
        self.client = client
        self.pid = os.getpid()
        self.closed = False
        self.process = None
        self.timeout = timeout
        self.responses = set()


def host_for_client(client, *, timeout=120):
    return TestHost(client, timeout=timeout)
