"""Exercise the real HTTP adapter against controlled test-only transports."""
import os

from congress_api.retention.docspec_host import Host


def host_for_client(client, *, timeout=120):
    host = Host.__new__(Host)
    host.client = client
    host.pid = os.getpid()
    host.closed = False
    host.process = None
    host.timeout = timeout
    host.responses = set()
    return host
