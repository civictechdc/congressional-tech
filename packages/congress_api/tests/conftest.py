"""Pytest configuration, loopback gate, and shared fixtures for congress_api tests."""
import _socket
import os
from pathlib import Path
import shutil
import socket

import pytest

_DEFAULT_DOCSPEC = Path(__file__).resolve().parents[4] / "spicy-stack/docspec-rs/target/release/docspec"
if not os.environ.get("DOCSPEC_BINARY") and _DEFAULT_DOCSPEC.is_file():
    os.environ["DOCSPEC_BINARY"] = str(_DEFAULT_DOCSPEC)

_DEFAULT_SOURCE_FETCH = Path(__file__).resolve().parents[2] / "source-fetch/target/release/source-fetch"
if not os.environ.get("SOURCE_FETCH_BINARY") and _DEFAULT_SOURCE_FETCH.is_file():
    os.environ["SOURCE_FETCH_BINARY"] = str(_DEFAULT_SOURCE_FETCH)

from native_test_helpers import native_test_client
from testing_fakes import (
    AsyncMemoryStore,
    FakeR2Remote,
    MemoryNative,
    MemoryStore,
    SelectorStore,
    receipts,
    response,
)


def pytest_configure(config):
    config.addinivalue_line('markers', 'loopback: needs real local socket connections')


def pytest_collection_modifyitems(config, items):
    if socket.socket.connect is _socket.socket.connect:
        return
    skip = pytest.mark.skip(reason='needs real local sockets; capture-raw-sources.yml runs it natively')
    for item in items:
        if item.get_closest_marker('loopback'):
            item.add_marker(skip)


@pytest.fixture
def native(tmp_path):
    binary = os.environ.get('DOCSPEC_BINARY') or shutil.which('docspec')
    if not binary:
        pytest.skip('Set DOCSPEC_BINARY to the qualified maintained CLI')
    return native_test_client(binary, tmp_path / 'workspace')


__all__ = [
    'pytest_configure',
    'pytest_collection_modifyitems',
    'native',
    'MemoryStore',
    'SelectorStore',
    'MemoryNative',
    'AsyncMemoryStore',
    'receipts',
    'FakeR2Remote',
    'response',
]
