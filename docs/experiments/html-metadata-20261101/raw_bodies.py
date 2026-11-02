"""Read retained bodies by digest: a local mirror when present, else the public store.

Every body is checked against its digest. Set RAW_MIRROR to a directory holding
bodies/sha256/<xx>/<sha>.gz. No credential is used; nothing is written to the store.
"""
import gzip
import hashlib
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

PUBLIC = 'https://congressional-data.spicygov.ai/bodies/sha256'


def stored(sha):
    mirror = os.environ.get('RAW_MIRROR')
    path = Path(mirror) / 'bodies/sha256' / sha[:2] / f'{sha}.gz' if mirror else None
    if path and path.is_file():
        return path.read_bytes(), 'mirror'
    for attempt in range(4):
        try:
            request = urllib.request.Request(f'{PUBLIC}/{sha[:2]}/{sha}.gz', headers={'User-Agent': 'congressional-tech-evidence'})
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read(), 'public'
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def read_body(sha):
    """(body, source). Raises when the stored bytes are not the named body."""
    data, source = stored(sha)
    body = gzip.decompress(data)
    if hashlib.sha256(body).hexdigest() != sha:
        raise ValueError(f'digest mismatch: {sha}')
    return body, source
