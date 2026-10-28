"""Pytest configuration and release binary resolution for viewer_publication tests."""
import os
from pathlib import Path
import sys

# Reuse the raw producer's authored fixtures when this package runs by itself or
# in a different CI shard. Production modules and import order stay unchanged.
_RAW_TESTS = Path(__file__).resolve().parents[2] / 'congress_api/tests'
if str(_RAW_TESTS) not in sys.path:
    sys.path.append(str(_RAW_TESTS))

_DEFAULT_DOCSPEC = Path(__file__).resolve().parents[4] / "spicy-stack/docspec-rs/target/release/docspec"
if not os.environ.get("DOCSPEC_BINARY") and _DEFAULT_DOCSPEC.is_file():
    os.environ["DOCSPEC_BINARY"] = str(_DEFAULT_DOCSPEC)

_DEFAULT_SOURCE_FETCH = Path(__file__).resolve().parents[2] / "source-fetch/target/release/source-fetch"
if not os.environ.get("SOURCE_FETCH_BINARY") and _DEFAULT_SOURCE_FETCH.is_file():
    os.environ["SOURCE_FETCH_BINARY"] = str(_DEFAULT_SOURCE_FETCH)
