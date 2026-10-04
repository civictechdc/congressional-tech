"""Capture and inspection select the published generation, including after resume."""
import gzip
import importlib.util
from pathlib import Path

from congress_api.retention import document_index as index
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import publish_catalog, read_catalog
from congress_api.retention.raw_archive import Archive
from test_raw_source_sync import MemoryStore


class ReadTrackingStore(MemoryStore):
    def __init__(self):
        super().__init__()
        self.reads = []

    def read(self, key):
        self.reads.append(key)
        return super().read(key)


def publish(store, directory, urls):
    (directory / "indexes").mkdir(parents=True)
    result = index.write_filename_metadata(directory, [
        dict(body_key="bodies/fixture.gz", filename=url.rsplit("/", 1)[-1],
             source_url=url, media_type=["application/pdf"], http_status=["200"])
        for url in urls
    ], workers=1)
    return publish_catalog(store, result['output'], result['documents_output'], previous=read_catalog(store))


def test_capture_resumes_selected_generation_without_reading_unchanged_tables(tmp_path):
    store = ReadTrackingStore()
    first_url, second_url = "https://example.gov/first.pdf", "https://example.gov/second.pdf"
    publish(store, tmp_path / "first", [first_url])
    first = Archive(store, "first")
    first.save()
    assert first_url in first.state
    store.reads.clear()
    resumed = Archive(store, "resume")
    assert resumed.state == first.state
    assert not any(key.startswith("catalog-generations/") for key in store.reads)
    publish(store, tmp_path / "second", [first_url, second_url])
    store.reads.clear()
    refreshed = Archive(store, "refresh")
    assert first_url in refreshed.state and second_url in refreshed.state
    assert any(key.startswith("catalog-generations/") for key in store.reads)


def test_probe_reads_selected_generation_with_stale_legacy_roots(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "core_probe", root / "docs/youtube-coverage/research/scripts/probe_document_links.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    url = "https://example.gov/retained.pdf"
    publish(LocalStore(tmp_path), tmp_path / "build", [url])
    body = tmp_path / "bodies/fixture.gz"
    body.parent.mkdir()
    content = b"%PDF-1.7\nretained body\n%%EOF"
    body.write_bytes(gzip.compress(content))
    (tmp_path / "indexes/document-filenames.parquet").write_bytes(b"stale root")
    result = probe.archive_reader(tmp_path)(url, max_bytes=4096)
    assert result.from_cache and result.complete
    assert result.content.body_bytes() == content
    assert result.body_key == "bodies/fixture.gz"
