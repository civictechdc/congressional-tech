"""Daily admission binds the mapper, projection and both policy registries."""
from hashlib import sha256
from pathlib import Path

from congress_api.lake import captures

APPROVED_MAPPING='2dd8ee5f1ff42bb88517f3e250b6bd5a63ed06e477d8d747988051af33b738d5'


def test_current_capture_version_preserves_the_existing_byte_identity():
    source=Path(captures.__file__)
    expected=sha256(source.read_bytes()+source.with_name('receipt_metadata.py').read_bytes()+captures.DOMAIN_OUTCOMES.read_bytes()+captures.LINE_KINDS.read_bytes()).hexdigest()
    assert captures.current_version()==expected==APPROVED_MAPPING
