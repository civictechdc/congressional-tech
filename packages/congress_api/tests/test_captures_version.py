"""Daily admission binds the mapper, projection and both policy registries."""
from hashlib import sha256
from pathlib import Path

from congress_api.lake import captures

APPROVED_MAPPING='56b1cac50e4d5bbe978049d34a61c523bd2827e13094290705ed3a7bb10d1ef5'


def test_current_capture_version_preserves_the_existing_byte_identity():
    source=Path(captures.__file__)
    expected=sha256(source.read_bytes()+source.with_name('receipt_metadata.py').read_bytes()+captures.DOMAIN_OUTCOMES.read_bytes()+captures.LINE_KINDS.read_bytes()).hexdigest()
    assert captures.current_version()==expected==APPROVED_MAPPING
