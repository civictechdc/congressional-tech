"""Daily admission binds the mapper, projection and both policy registries."""
from hashlib import sha256
from pathlib import Path

from congress_api.lake import captures

APPROVED_MAPPING='9bb2864638ac2c7e7a8b984a75190f3e372d8deb3acb0afc973ef43600a88691'


def test_current_capture_version_preserves_the_existing_byte_identity():
    source=Path(captures.__file__)
    expected=sha256(source.read_bytes()+source.with_name('receipt_metadata.py').read_bytes()+captures.DOMAIN_OUTCOMES.read_bytes()+captures.LINE_KINDS.read_bytes()).hexdigest()
    assert captures.current_version()==expected==APPROVED_MAPPING
