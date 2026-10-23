"""Keep tests that need real local sockets out of the offline suite.

offline-python.py replaces socket connections for its whole process, which also
blocks loopback HTTP servers and multiprocessing managers. Mark such tests
`loopback`; capture-raw-sources.yml runs their files without the wrapper.
"""
import _socket
import os
from pathlib import Path
import socket

import pytest

_DEFAULT_DOCSPEC = Path("/Users/mikewolfd/Work/spicy-stack/docspec-rs/target/release/docspec")
if not os.environ.get("DOCSPEC_BINARY") and _DEFAULT_DOCSPEC.is_file():
    os.environ["DOCSPEC_BINARY"] = str(_DEFAULT_DOCSPEC)

_DEFAULT_SOURCE_FETCH = Path(__file__).resolve().parents[1] / "packages/source-fetch/target/release/source-fetch"
if not os.environ.get("SOURCE_FETCH_BINARY") and _DEFAULT_SOURCE_FETCH.is_file():
    os.environ["SOURCE_FETCH_BINARY"] = str(_DEFAULT_SOURCE_FETCH)


def pytest_configure(config):
    config.addinivalue_line('markers', 'loopback: needs real local socket connections')


def pytest_collection_modifyitems(config, items):
    if socket.socket.connect is _socket.socket.connect:
        return
    skip = pytest.mark.skip(reason='needs real local sockets; capture-raw-sources.yml runs it natively')
    for item in items:
        if item.get_closest_marker('loopback'):
            item.add_marker(skip)
