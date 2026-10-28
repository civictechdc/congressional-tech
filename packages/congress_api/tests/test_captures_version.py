"""Daily admission reuses the established two-file D1 mapping identity."""
from hashlib import sha256
from pathlib import Path

from congress_api.lake import captures


def test_current_capture_version_preserves_the_existing_byte_identity():
    source=Path(captures.__file__)
    expected=sha256(source.read_bytes()+source.with_name('receipt_metadata.py').read_bytes()).hexdigest()
    assert captures.current_version()==expected
