"""Raw receipts must become queryable metadata, including after publication failure."""
from catalog_test_helpers import selected_path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.acquisition.raw_sync import run_sync
from congress_api.retention.raw_archive import Archive
from congress_api.retention.raw_catalog import rebuild_catalog, FILENAMES, DOCUMENTS
from congress_api.retention import document_index as index
from test_raw_source_sync import MemoryStore, response


def table(store, key=FILENAMES):
    from congress_api.retention.catalog_publication import read_catalog
    snapshot = read_catalog(store) if key in (FILENAMES, DOCUMENTS) else None
    payload = (snapshot.filenames if key == FILENAMES else snapshot.documents) if snapshot else store.read(key)
    return pq.read_table(selected_path(pa.BufferReader(payload)))


def initialize(tmp_path):
    (tmp_path / "indexes").mkdir()
    index.write_filename_metadata(
        tmp_path,
        [
            dict(
                body_key=None,
                filename="Known statement.pdf",
                source_url="https://example.gov/Known%20statement.pdf",
            )
        ],
        workers=1,
    )
    store = MemoryStore()
    for key in (FILENAMES, DOCUMENTS):
        store.objects[key] = selected_path(tmp_path / key).read_bytes()
    return store


def test_capture_rebuild_preserves_headers_redirects_context_and_unfetched_names(
    tmp_path,
):
    store = initialize(tmp_path)
    start = "https://docs.house.gov/download?id=1"
    end = "https://docs.house.gov/HHRG-119-IF14-Wstate-WosinskaM-20260318.pdf"
    header = "HHRG-119-IF14-Wstate-WosinskaM-20260318.pdf"
    seed = dict(
        url=start,
        pointer=["meetingDocuments", 0, "url"],
        native={"documentType": "Witness Statement", "newPublisherField": "kept"},
        context={
            "eventId": 123,
            "congress": 119,
            "chamber": "House",
            "committees": [{"systemCode": "hsif14", "name": "Health"}],
        },
    )
    r = response(start, b"%PDF-1.7\n%%EOF")
    r["url"] = end
    r["response_headers"]["content-disposition"] = f'attachment; filename="{header}"'
    result = run_sync(
        Archive(store, "capture"),
        [seed],
        fetch=lambda _: r,
        limit=1,
    )
    result['catalog'] = rebuild_catalog(store, seeds=[seed], workers=1)
    rows = table(store).to_pylist()
    matches = [row for row in rows if row["filename"] == header]
    assert matches and all(
        row["document_kind"] == ["witness-statement"] for row in matches
    )
    assert any(row["source_url"] == end for row in rows)
    assert any(row["filename_origins"] == ["content_disposition"] for row in matches)
    assert any(row["source_committee_code"] == ["hsif14"] for row in matches)
    assert any(row["source_document_type"] == ["Witness Statement"] for row in matches)
    assert any(
        row["filename"] == "Known statement.pdf" and row["body_key"] is None
        for row in rows
    )
    assert (
        table(store).schema.metadata[b"catalog_id"]
        == table(store, DOCUMENTS).schema.metadata[b"catalog_id"]
    )
    assert result["catalog"]["document_rows"] == len(table(store, DOCUMENTS))


def test_only_new_names_parse_until_explicit_rebuild(tmp_path, monkeypatch):
    store = initialize(tmp_path)
    calls = []
    original = index.extract
    fingerprint = index.parser_fingerprint()
    monkeypatch.setattr(index, "parser_fingerprint", lambda: fingerprint)
    monkeypatch.setattr(
        index, "extract", lambda key: (calls.append(key), original(key))[1]
    )
    a = Archive(store, "empty")
    result = rebuild_catalog(store, a.captures, workers=1)
    assert calls == [] and result["parsed_inputs"] == 0
    seed = {"url": "https://example.gov/New-testimony.pdf"}
    result = rebuild_catalog(store, a.captures, seeds=[seed], workers=1)
    assert calls == [("New-testimony.pdf", seed["url"])]
    assert result["parsed_inputs"] == 1
    calls.clear()
    monkeypatch.setattr(index, "parser_fingerprint", lambda: "changed-rules")
    result = rebuild_catalog(store, a.captures, workers=1)
    assert calls == [] and result['parsed_inputs'] == 0
    result = rebuild_catalog(store, a.captures, workers=1, repair=True)
    assert len(calls) == 2 and result["parsed_inputs"] == 2


def test_failed_filename_publication_replays_delta_without_fetch(tmp_path):
    store = initialize(tmp_path)
    a = Archive(store, "capture")
    u = "https://example.gov/New-testimony.pdf"
    a.record(response(u, b"%PDF-1.7\n%%EOF"), outcome="saved", links=[])
    a.save()
    original_put = store.put

    def failed_put(key, *args, **kwargs):
        if key.startswith("catalog-generations/") and key.endswith("/document-filenames.parquet"):
            raise OSError("simulated second table upload failure")
        return original_put(key, *args, **kwargs)

    store.put = failed_put
    with pytest.raises(OSError):
        rebuild_catalog(store, a.captures, workers=1)
    assert (
        table(store).schema.metadata[b"catalog_id"]
        == table(store, DOCUMENTS).schema.metadata[b"catalog_id"]
    )
    assert not any(row["filename"] == "New-testimony.pdf" for row in table(store).to_pylist())
    store.put = original_put
    run_sync(
        Archive(store, "recover"),
        [],
        fetch=lambda _: pytest.fail("Rebuild should not fetch sources"),
        limit=0,
    )
    rebuild_catalog(store, workers=1)
    assert any(
        row["filename"] == "New-testimony.pdf" and row["body_key"]
        for row in table(store).to_pylist()
    )
    assert (
        table(store).schema.metadata[b"catalog_id"]
        == table(store, DOCUMENTS).schema.metadata[b"catalog_id"]
    )
    assert int(table(store).schema.metadata[b"raw_capture_rows"]) == len(a.captures)


def test_challenges_and_incomplete_files_cannot_merge_as_successful_documents(tmp_path):
    store = initialize(tmp_path)
    a = Archive(store, "bad")
    for i in range(2):
        u = f"https://example.gov/{i}.pdf"
        a.record(
            response(u, b"Identical challenge page", "application/pdf"),
            outcome="challenge",
            links=[],
        )
    a.save()
    rebuild_catalog(store, a.captures, workers=1)
    docs = [r for r in table(store, DOCUMENTS).to_pylist() if r.get("capture_outcome")]
    assert len(docs) == 2
    assert all(r["capture_outcome"] == ["challenge"] for r in docs)


def test_missing_new_receipt_does_not_advance_table_cursor(tmp_path):
    store = initialize(tmp_path)
    a = Archive(store, "missing")
    a.record(
        response("https://example.gov/a.pdf", b"%PDF-1.7\n%%EOF"),
        outcome="saved",
        links=[],
    )
    a.save()
    before = store.objects[FILENAMES]
    del store.objects[next(iter(store.keys("receipts/")))]
    with pytest.raises(ValueError, match="Missing capture receipt"):
        rebuild_catalog(store, a.captures, workers=1)
    assert store.objects[FILENAMES] == before


def test_retained_child_metadata_survives_run_budget(tmp_path):
    store = initialize(tmp_path)
    a = Archive(store, "parent")
    u = "https://example.gov/page"
    child = "https://example.gov/child.pdf"
    a.record(
        response(u, b"<html></html>", "text/html"),
        outcome="saved",
        links=[dict(url=child, text="Witness Statement", parent_url=u)],
    )
    a.save()
    rebuild_catalog(store, a.captures, workers=1)
    row = next(r for r in table(store).to_pylist() if r["source_url"] == child)
    assert row["body_key"] is None
    assert row["source_page_url"] == [u]
    assert row["source_document_label"] == ["Witness Statement"]


def test_metadata_only_refresh_preserves_capture_outcome(tmp_path):
    store = initialize(tmp_path)
    a = Archive(store, "partial")
    a.record(
        response("https://example.gov/a.pdf", b"%PDF-1.7\npart"),
        outcome="incomplete",
        links=[],
    )
    a.save()
    rebuild_catalog(store, a.captures, workers=1)
    from congress_api.retention.catalog_publication import read_catalog
    snapshot = read_catalog(store)
    for key, payload in ((FILENAMES, snapshot.filenames), (DOCUMENTS, snapshot.documents)):
        (tmp_path / key).write_bytes(payload)
    from congress_api.retention.catalog_cache import LocalStore
    from congress_api.retention.catalog_publication import publish_catalog
    local = LocalStore(tmp_path)
    publish_catalog(local, tmp_path / FILENAMES, tmp_path / DOCUMENTS, previous=read_catalog(local))
    index.refresh_filename_metadata(tmp_path, workers=1)
    rows = pq.read_table(selected_path(tmp_path / FILENAMES)).to_pylist()
    assert next(r for r in rows if r["filename"] == "a.pdf")["capture_outcome"] == [
        "incomplete"
    ]


def test_discovered_files_inherit_parent_committee_but_not_document_type():
    context = index.DocumentSources()
    context.add_link(
        dict(
            url="https://example.gov/page",
            native={"documentType": "Agenda"},
            context={
                "eventId": 123,
                "congress": 119,
                "chamber": "House",
                "committees": [{"systemCode": "hsif00"}],
            },
        )
    )
    context.add_link(
        dict(
            url="https://example.gov/statement.pdf",
            parent_url="https://example.gov/page",
            text="Statement",
        )
    )
    values = context.for_url("https://example.gov/statement.pdf")
    assert values["source_committee_code"] == ["hsif00"]
    assert values["source_meeting_id"] == ["123"]
    assert "source_document_type" not in values
    assert values["source_document_label"] == ["Statement"]


def test_discovered_file_inherits_parent_context_from_previous_catalog(tmp_path):
    store = initialize(tmp_path)
    parent = "https://example.gov/page"
    child = "https://example.gov/statement.pdf"
    a = Archive(store, "first")
    rebuild_catalog(
        store,
        a.captures,
        seeds=[
            dict(
                url=parent,
                native={"documentType": "Hearing Notice"},
                context={
                    "eventId": 123,
                    "congress": 119,
                    "chamber": "House",
                    "committees": [{"systemCode": "hsif00"}],
                },
            )
        ],
        workers=1,
    )
    a = Archive(store, "later")
    a.record(
        response(parent, b"<html></html>", "text/html"),
        outcome="saved",
        links=[dict(url=child, parent_url=parent, text="Statement")],
    )
    a.save()
    rebuild_catalog(store, a.captures, workers=1)
    row = next(r for r in table(store).to_pylist() if r["source_url"] == child)
    assert row["source_committee_code"] == ["hsif00"]
    assert row["source_meeting_id"] == ["123"]
    assert row.get("source_document_type") is None
    assert row["source_document_label"] == ["Statement"]


def test_recurring_catalog_preserves_body_evidence_without_reading_unchanged_bodies(tmp_path):
    from test_document_evidence import retained
    store = initialize(tmp_path)
    url = 'https://www.congress.gov/119/meeting/house/123/documents/HHRG-119-IF00-WList-20250101.pdf'
    name = 'house_123_documents_HHRG_119_IF00_WList_20250101_pdf'
    rows = [retained(tmp_path, '123.xml', f'<committee-meeting meeting-id="HMKP123"><file doc-url="{url}"/></committee-meeting>'.encode()),
            retained(tmp_path, name, b'%PDF-1.4\n'),
            retained(tmp_path, '124.xml', b'<witness-list meeting-id="HMKP124"/>')]
    index.write_filename_metadata(tmp_path, rows, workers=1)
    for key in (FILENAMES, DOCUMENTS):
        store.objects[key] = selected_path(tmp_path / key).read_bytes()
    for row in rows:
        store.objects[row['body_key']] = (tmp_path / row['body_key']).read_bytes()
    before = table(store).to_pylist()
    original_read = store.read
    reads = []
    store.read = lambda key: reads.append(key) or original_read(key)
    a = Archive(store, 'refresh')
    rebuild_catalog(store, a.captures, workers=1)
    after = table(store).to_pylist()
    assert before == after
    assert not any(key.startswith('bodies/') for key in reads)


def test_new_numeric_xml_capture_is_read_from_injected_store(tmp_path):
    store = initialize(tmp_path)
    a = Archive(store, 'new-xml')
    url = 'https://docs.house.gov/meetings/123.xml'
    r = response(url, b'<witness-list meeting-id="HMKP123"/>')
    r['response_headers']['content-type'] = 'application/xml'
    a.record(r, outcome='saved', links=[])
    a.save()
    rebuild_catalog(store, a.captures, workers=1, inspect_bodies=True)
    row = next(r for r in table(store).to_pylist() if r['filename']=='123.xml')
    assert row['document_kind'] == ['witness-list']
    assert row['document_kind_source'] == ['content']
    assert row['source_record_identifier'] == ['HMKP123']
