"""Parse the content-addressed keys used by retained source evidence."""
import re


_BODY_KEY = re.compile(r'bodies/sha256/([a-f0-9]{2})/([a-f0-9]{64})\.gz')
_PUBLIC_BODY_OBJECT_KEY = re.compile(r'bodies/sha256/([a-f0-9]{2})/([a-f0-9]{64})\.(gz|pdf)')
_SHA256_DIGEST = re.compile(r'[a-f0-9]{64}')
PDF_MAGIC = b'%PDF-'


def body_key_digest(key):
    """Return the digest only when its shard agrees; missing keys return None.

    Keep regex type errors for nonempty non-string keys, as existing evidence
    readers do. Callers that refuse types explicitly retain their own errors.
    """
    match = _BODY_KEY.fullmatch(key or '')
    return match[2] if match and match[1] == match[2][:2] else None


def body_object_digest(key_or_sha256):
    """Extract a validated 64-hex SHA-256 from a logical/physical body key or raw hex digest."""
    if not isinstance(key_or_sha256, str) or not key_or_sha256:
        return None
    if _SHA256_DIGEST.fullmatch(key_or_sha256):
        return key_or_sha256
    match = _PUBLIC_BODY_OBJECT_KEY.fullmatch(key_or_sha256)
    return match[2] if match and match[1] == match[2][:2] else None


def is_pdf_bytes(data) -> bool:
    """Return True when raw body bytes begin with the PDF magic header ``%PDF-``."""
    return isinstance(data, (bytes, bytearray, memoryview)) and bytes(data[:5]) == PDF_MAGIC


def is_pdf_format(content_type_or_format) -> bool:
    """Return True when format metadata, MIME type, filename, or magic bytes indicate a PDF."""
    if content_type_or_format is None:
        return False
    if is_pdf_bytes(content_type_or_format):
        return True
    if isinstance(content_type_or_format, str):
        token = content_type_or_format.split(';', 1)[0].strip().lower()
        return token in {'pdf', 'application/pdf', '.pdf'} or token.endswith('.pdf')
    if isinstance(content_type_or_format, (list, tuple, set, frozenset)):
        return any(is_pdf_format(item) for item in content_type_or_format)
    return False


def physical_body_object_key(body_key: str, content_type_or_format=None, *, is_pdf: bool | None = None) -> str:
    """Map immutable logical ``body_key`` (``bodies/sha256/<xx>/<sha256>.gz``) to its physical R2 object key.

    Logical ``row['body_key']`` is hashed into all 1.68M ``source_id``s and 1.24M ``document_id``s
    and must never be mutated in catalog or archive rows. PDFs are stored uncompressed in R2 at
    ``bodies/sha256/<xx>/<sha256>.pdf`` for HTTP 206 byte-range streaming, while non-PDF bodies
    use ``bodies/sha256/<xx>/<sha256>.gz``.
    """
    digest = body_object_digest(body_key)
    if digest is None:
        raise ValueError(f'Invalid logical body_key: {body_key!r}')
    pdf = is_pdf if is_pdf is not None else is_pdf_format(content_type_or_format)
    ext = 'pdf' if pdf else 'gz'
    return f'bodies/sha256/{digest[:2]}/{digest}.{ext}'


def quarantine_body_key(key_or_sha256: str, *, is_pdf: bool = False) -> str:
    """Return the non-public quarantine object key for an excluded SHA-256 body."""
    digest = body_object_digest(key_or_sha256)
    if digest is None:
        raise ValueError(f'Invalid body key or SHA-256 digest for quarantine: {key_or_sha256!r}')
    ext = 'pdf' if is_pdf else 'gz'
    return f'quarantine/bodies/sha256/{digest[:2]}/{digest}.{ext}'

