"""Process ownership and bounded HTTP I/O for the maintained local DocSpec API."""
import httpx
from .host import ArrowResponse, Host, acquire_host
from .models import (
    REQUIRED_LOOPBACK_CAPABILITIES,
    RESPONSE_LIMIT,
    DocSpecFailure,
)

__all__ = [
    'REQUIRED_LOOPBACK_CAPABILITIES',
    'RESPONSE_LIMIT',
    'ArrowResponse',
    'DocSpecFailure',
    'Host',
    'acquire_host',
    'httpx',
]
