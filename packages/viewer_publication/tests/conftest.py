"""Pytest configuration and release binary resolution for viewer_publication tests."""
import os
from pathlib import Path
import sys
import pytest

# Reuse the raw producer's authored fixtures when this package runs by itself or
# in a different CI shard. Production modules and import order stay unchanged.
_RAW_TESTS = Path(__file__).resolve().parents[2] / 'congress_api/tests'
if str(_RAW_TESTS) not in sys.path:
    sys.path.append(str(_RAW_TESTS))

_DEFAULT_SOURCE_FETCH = Path(__file__).resolve().parents[2] / "source-fetch/target/release/source-fetch"
if not os.environ.get("SOURCE_FETCH_BINARY") and _DEFAULT_SOURCE_FETCH.is_file():
    os.environ["SOURCE_FETCH_BINARY"] = str(_DEFAULT_SOURCE_FETCH)


@pytest.fixture
def release_adapter(tmp_path):
    from ddk.adapters.docspec import DocSpecAdapter
    from docspec_client.client import NativeDatasets

    runtime = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    return DocSpecAdapter(runtime.binary, runtime.limits, timeout=120,
        source_commit=runtime.source_revision, evidence_dir=tmp_path/'native-evidence')


@pytest.fixture
def build_native_fixture(tmp_path, release_adapter):
    from viewer_publication.archive_fixture import build_fixture_release

    def build(fixture=None, *, name='fixture', metadata_queries=(), entity_files=None):
        root = tmp_path/name
        workspace = root/'workspace'
        workspace.mkdir(parents=True)
        return build_fixture_release(
            fixture or Path(__file__).parents[3]/'model/fixtures/hand-release.json',
            output=root/'controls', scratch=root/'request', adapter=release_adapter,
            workspace=workspace, operation=name, metadata_queries=metadata_queries, entity_files=entity_files)
    return build
