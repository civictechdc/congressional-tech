"""Parse the content-addressed keys used by retained source evidence."""
import re


_BODY_KEY = re.compile(r'bodies/sha256/([a-f0-9]{2})/([a-f0-9]{64})\.gz')


def body_key_digest(key):
    """Return the digest only when its shard agrees; missing keys return None.

    Keep regex type errors for nonempty non-string keys, as existing evidence
    readers do. Callers that refuse types explicitly retain their own errors.
    """
    match = _BODY_KEY.fullmatch(key or '')
    return match[2] if match and match[1] == match[2][:2] else None
