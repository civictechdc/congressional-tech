"""Compatibility shim: the DocSpec host transport now lives in ``docspec_client``.

Congress-api callers keep this import path; the implementation and custody
invariants have one neutral owner shared with other domain packages.
"""
from docspec_client.docspec_host import (
    REQUIRED_LOOPBACK_CAPABILITIES,
    ArrowResponse,
    DocSpecFailure,
    Host,
    acquire_host,
)

__all__ = [
    'REQUIRED_LOOPBACK_CAPABILITIES',
    'ArrowResponse',
    'DocSpecFailure',
    'Host',
    'acquire_host',
]
