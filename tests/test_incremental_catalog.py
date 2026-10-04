"""The routine update reuses completed work without dropping raw source context."""
from catalog_test_helpers import selected_path

from copy import deepcopy

import pyarrow as pa
import pytest

from congress_api.retention import document_index as index
from congress_api.retention.raw_archive import Archive, STATE_KEY, decode_table
from congress_api.retention.raw_catalog import rebuild_catalog
from test_raw_catalog import table
from test_raw_rebuild import retain
from test_raw_source_sync import MemoryStore


def test_second_update_reads_no_receipts_or_bodies_and_publishes_nothing():
    store = MemoryStore()
    retain(
        store,
        {},
        family="senate/pages",
        source_file="page.html",
        url="https://www.foreign.senate.gov/hearings/example",
        body=b'<html><h2>Hearing Transcript</h2><a href="/opaque.pdf">Download</a></html>',
    )
    rebuild_catalog(store, workers=1)
    before = deepcopy(store.objects)
    original = store.read

    def read(key):
        assert not key.startswith(("receipts/", "bodies/")), key
        return original(key)

    store.read = read
    result = rebuild_catalog(store, workers=1)
    assert result["unchanged"] is True
    assert store.objects == before


def test_delta_joins_new_xml_with_scoped_meeting_receipt_metadata():
    store = MemoryStore()
    retain(
        store,
        {
            "eventId": 1,
            "congress": 119,
            "chamber": "House",
            "committees": [{"systemCode": "hsii00"}],
        },
        family="congress/meetings",
        source_file="meeting.json",
    )
    rebuild_catalog(store, workers=1)
    url = "https://example.gov/opaque.pdf"
    retain(
        store,
        {},
        family="house/witness-xml",
        source_file="witness.xml",
        url="https://docs.house.gov/1.xml",
        body=(
            '<witness-list meeting-id="HMKP1"><panel><witness><firstname>Jane</firstname>'
            '<lastname>Doe</lastname><witness-documents><witness-document type="WS">'
            f'<files><file doc-url="{url}" doc-type="PDF"/></files>'
            "</witness-document></witness-documents></witness></panel></witness-list>"
        ).encode(),
    )
    original = store.read

    def read(key):
        assert not key.startswith("indexes/processing/sources"), key
        return original(key)

    store.read = read
    rebuild_catalog(store, workers=1)
    row = next(r for r in table(store).to_pylist() if r["source_url"] == url)
    assert row["source_committee_code"] == ["hsii00"]
    assert row["source_witness_name"] == ["Jane Doe"]
    assert row["document_kind"] == ["witness-statement"]


def test_filename_cache_independent_of_body_fields_and_negative_cover_is_cached(
    tmp_path, monkeypatch
):
    from congress_api.retention import document_evidence as evidence
    from test_document_evidence import retained

    source = retained(tmp_path, "opaque.pdf", b"%PDF-1.7\n%%EOF")
    (tmp_path / "indexes").mkdir()
    calls = []
    monkeypatch.setattr(
        evidence, "document_cover", lambda body: calls.append(body) or {}
    )
    index.write_filename_metadata(tmp_path, [dict(source)], workers=1, inspect_bodies=True)
    before = pa.parquet.read_table(selected_path(tmp_path / "indexes/document-filenames.parquet"))
    assert len(calls) == 1

    def forbidden(*args, **kwargs):
        pytest.fail("Completed filename/body interpretation was repeated")

    # The fingerprint is deliberately pinned: this tests reuse, not invalidation.
    fingerprint = index.parser_fingerprint()
    monkeypatch.setattr(index, "parser_fingerprint", lambda: fingerprint)
    monkeypatch.setattr(index, "extract", forbidden)
    index.write_filename_metadata(
        tmp_path, [dict(source)], workers=1, previous=before, read_body=forbidden, inspect_bodies=True
    )
    assert len(calls) == 1


def test_saved_download_state_does_not_reload_unchanged_filename_table():
    store = MemoryStore()
    first = Archive(store, "first")
    first.seed({"url": "https://example.gov/a.pdf"})
    first.save()
    original = store.read

    def read(key):
        assert key != "indexes/document-filenames.parquet"
        return original(key)

    store.read = read
    resumed = Archive(store, "second")
    assert resumed.state == {
        row["url"]: row for row in decode_table(store.objects[STATE_KEY]).to_pylist()
    }


def test_parser_change_and_repair_reprocess_retained_sources(monkeypatch):
    from congress_api.retention import raw_catalog

    store = MemoryStore()
    receipt = retain(
        store,
        {
            "eventId": 1,
            "congress": 119,
            "chamber": "House",
            "meetingDocuments": [
                {
                    "url": "https://example.gov/opaque.pdf",
                    "documentType": "Witness Statement",
                }
            ],
        },
        family="congress/meetings",
        source_file="meeting.json",
    )
    rebuild_catalog(store, workers=1)
    original = store.read
    reads = []
    store.read = lambda key: reads.append(key) or original(key)
    monkeypatch.setattr(
        raw_catalog, "source_fingerprint", lambda: "changed-source-parser"
    )
    rebuild_catalog(store, workers=1)
    assert receipt in reads
    reads.clear()
    rebuild_catalog(store, workers=1)
    assert receipt not in reads
    rebuild_catalog(store, workers=1, repair=True)
    assert receipt in reads


def test_filename_rule_change_does_not_replay_source_bodies(monkeypatch):
    store = MemoryStore()
    retain(
        store,
        {},
        family="senate/pages",
        source_file="page.html",
        url="https://www.foreign.senate.gov/hearings/example",
        body=b'<html><h2>Hearing Transcript</h2><a href="/opaque.pdf">Download</a></html>',
    )
    rebuild_catalog(store, workers=1)
    before = table(store).to_pylist()
    original = store.read

    def read(key):
        assert not key.startswith(("receipts/", "bodies/")), key
        return original(key)

    store.read = read
    monkeypatch.setattr(index, "parser_fingerprint", lambda: "changed-filename-parser")
    rebuild_catalog(store, workers=1)
    assert table(store).to_pylist() == before


def test_failed_publication_rebuilds_from_receipts_without_hidden_source_state():
    store = MemoryStore()
    retain(store, {}, family="senate/pages", source_file="page.html",
           url="https://www.foreign.senate.gov/hearings/example",
           body=b'<html><h2>Hearing Transcript</h2><a href="/opaque.pdf">Download</a></html>')
    before = deepcopy(store.objects)
    put = store.put
    def fail(key, *args, **kwargs):
        if key.startswith("catalog-generations/") and key.endswith("/documents.parquet"):
            raise OSError("publication interrupted")
        return put(key, *args, **kwargs)
    store.put = fail
    with pytest.raises(OSError, match="publication interrupted"):
        rebuild_catalog(store, workers=1)
    assert all(store.objects[key] == value for key, value in before.items())
    assert "indexes/catalog.json" not in store.objects
    assert all(key in before or key.startswith("catalog-generations/") for key in store.objects)
    store.put = put
    rebuild_catalog(store, workers=1)
    assert table(store).num_rows > 0
    assert not any(k.startswith('indexes/processing/') for k in store.objects)


def test_incremental_and_full_replay_preserve_the_same_source_values():
    store = MemoryStore()
    original = "https://example.gov/original.pdf"
    final = "https://example.gov/final.pdf"
    retain(
        store,
        {"url": original, "final_url": final, "http_status": 200},
        family="documents",
        source_file="old/receipts.jsonl",
        url=original,
        body=b"%PDF-1.7\n%%EOF",
    )
    rebuild_catalog(store, workers=1)
    retain(
        store,
        {
            "eventId": 1,
            "congress": 119,
            "chamber": "House",
            "meetingDocuments": [
                {"url": original, "documentType": "Witness Statement"}
            ],
        },
        family="congress/meetings",
        source_file="meeting.json",
    )
    rebuild_catalog(store, workers=1)
    incremental = {row["source_id"]: row for row in table(store).to_pylist()}
    rebuild_catalog(store, workers=1, repair=True)
    repaired = {row["source_id"]: row for row in table(store).to_pylist()}
    assert incremental == repaired


def test_capture_checkpoint_detects_changed_prefix_and_ignores_chunking():
    from congress_api.retention.catalog_cache import capture_digest

    a = pa.table({"a": [1, None, 3], "b": ["a", "b", "c"]})
    b = pa.concat_tables([a.slice(0, 1), a.slice(1)])
    assert capture_digest(a) == capture_digest(b)
    c = pa.concat_tables([a, pa.table({"a": [4], "b": ["d"]})])
    assert capture_digest(c.slice(0, 3)) == capture_digest(a)
    assert capture_digest(a.set_column(0, "a", pa.array([1, 2, 3]))) != capture_digest(
        a
    )


def test_unavailable_body_is_retried_when_it_arrives_without_an_index_change():
    store = MemoryStore()
    retain(
        store,
        {},
        family="senate/pages",
        source_file="page.html",
        url="https://www.foreign.senate.gov/hearings/example",
        body=b'<html><h2>Hearing Transcript</h2><a href="/opaque.pdf">Download</a></html>',
    )
    key = next(k for k in store.objects if k.startswith("bodies/"))
    body = store.objects.pop(key)
    rebuild_catalog(store, workers=1)
    store.objects[key] = body
    rebuild_catalog(store, workers=1)
    row = next(
        r
        for r in table(store).to_pylist()
        if r["source_url"] == "https://www.foreign.senate.gov/opaque.pdf"
    )
    assert row["document_kind"] == ["transcript"]


def test_download_state_consumes_new_captures_and_new_catalog_urls():
    from congress_api.retention.raw_archive import encode_table

    store = MemoryStore()
    Archive(store, "first").save()
    url = "https://example.gov/new.pdf"
    retain(
        store,
        {"url": url},
        family="documents",
        source_file="capture.json",
        url=url,
        body=b"%PDF-1.7\n%%EOF",
    )
    names = pa.table(
        {
            "source_url": ["https://example.gov/queued.pdf"],
            "body_key": pa.array([None], pa.string()),
            "format": pa.array([None], pa.list_(pa.string())),
            "http_status": pa.array([None], pa.list_(pa.string())),
            "media_type": pa.array([None], pa.list_(pa.string())),
        }
    )
    store.objects["indexes/document-filenames.parquet"] = encode_table(names)
    archive = Archive(store, "second")
    assert archive.state[url]["outcome"] == "retained"
    assert archive.state["https://example.gov/queued.pdf"]["outcome"] == "pending"


def test_new_retained_capture_supersedes_saved_pending_attempt():
    store = MemoryStore()
    url = "https://example.gov/later.pdf"
    old = Archive(store, "first")
    old.seed({"url": url})
    old.save()
    retain(
        store,
        {"url": url},
        family="documents",
        source_file="capture.json",
        url=url,
        body=b"%PDF-1.7\n%%EOF",
    )
    new = Archive(store, "second")
    assert new.state[url]["outcome"] == "retained"
    assert new.state[url]["body_key"]


def test_late_meeting_metadata_enriches_previously_retained_xml_links():
    store = MemoryStore()
    url = "https://example.gov/late.pdf"
    retain(
        store,
        {},
        family="house/witness-xml",
        source_file="witness.xml",
        url="https://docs.house.gov/1.xml",
        body=(
            '<witness-list meeting-id="HMKP1"><panel><witness><firstname>Jane</firstname>'
            '<lastname>Doe</lastname><witness-documents><witness-document type="WS">'
            f'<files><file doc-url="{url}" doc-type="PDF"/></files>'
            "</witness-document></witness-documents></witness></panel></witness-list>"
        ).encode(),
    )
    rebuild_catalog(store, workers=1)
    retain(
        store,
        {
            "eventId": 1,
            "congress": 119,
            "chamber": "House",
            "committees": [{"systemCode": "hsii00"}],
        },
        family="congress/meetings",
        source_file="meeting.json",
    )
    rebuild_catalog(store, workers=1)
    row = next(r for r in table(store).to_pylist() if r["source_url"] == url)
    assert row["source_committee_code"] == ["hsii00"]
    assert row["source_witness_name"] == ["Jane Doe"]


def test_new_imported_filename_rows_are_not_hidden_by_a_previous_checkpoint(tmp_path):
    store = MemoryStore()
    rebuild_catalog(store, workers=1)
    (tmp_path / "indexes").mkdir()
    index.write_filename_metadata(
        tmp_path,
        [
            dict(
                body_key=None,
                filename="new.pdf",
                source_url="https://example.gov/new.pdf",
            )
        ],
        workers=1,
    )
    from congress_api.retention.catalog_publication import read_catalog, publish_catalog
    publish_catalog(store, selected_path(tmp_path / "indexes/document-filenames.parquet"), selected_path(tmp_path / "indexes/documents.parquet"),
                    previous=read_catalog(store))
    rebuild_catalog(store, workers=1)
    assert any(row["filename"] == "new.pdf" for row in table(store).to_pylist())


def test_late_context_does_not_choose_between_congresses_or_replace_link_parent():
    context = index.DocumentSources()
    url = "https://example.gov/paper.pdf"
    page = "https://docs.house.gov/1.xml"
    context.add_url(
        url,
        {
            "source_meeting_id": ["1"],
            "source_chamber": ["House"],
            "source_page_url": [page],
            "source_original_page_url": [page],
        },
    )
    for congress in (118, 119):
        context.add_meeting(
            {
                "eventId": 1,
                "congress": congress,
                "chamber": "House",
                "_url": f"https://api.congress.gov/{congress}/1",
                "committees": [{"systemCode": f"committee-{congress}"}],
            }
        )
    context.refresh_meeting_context()
    assert not context.for_url(url).get("source_committee_code")
    scoped = "https://example.gov/scoped.pdf"
    context.add_url(
        scoped,
        {
            "source_meeting_id": ["1"],
            "source_chamber": ["House"],
            "source_congress": ["119"],
            "source_page_url": [page],
            "source_original_page_url": [page],
        },
    )
    context.refresh_meeting_context()
    row = context.for_url(scoped)
    assert row["source_committee_code"] == ["committee-119"]
    assert row["source_original_page_url"] == [page]


def test_explicit_repair_ignores_unreadable_derived_checkpoints():
    store = MemoryStore()
    retain(store, {'url': 'https://example.gov/a.pdf'}, family='documents', source_file='capture.json',
           url='https://example.gov/a.pdf', body=b'%PDF-1.7\n%%EOF')
    rebuild_catalog(store, workers=1)
    before = table(store).to_pylist()
    for name in ('sources', 'filenames', 'bodies'):
        store.objects[f'indexes/processing/{name}.parquet'] = b'incomplete derived cache'
    rebuild_catalog(store, workers=1, repair=True)
    assert table(store).to_pylist() == before


def test_catalog_ignores_obsolete_processing_tables():
    store = MemoryStore()
    for name in ('sources', 'filenames'):
        store.objects[f'indexes/processing/{name}.parquet'] = b'obsolete'
    original = store.read
    def read(key):
        assert key not in ('indexes/processing/sources.parquet', 'indexes/processing/filenames.parquet')
        return original(key)
    store.read = read
    rebuild_catalog(store, workers=1)
    assert not any(k.startswith('indexes/processing/') for k in store.writes)


def test_default_rebuild_uses_receipts_and_names_without_opening_document_bodies():
    store = MemoryStore()
    url = 'https://example.gov/12345.pdf'
    retain(store, {'eventId': 1, 'congress': 119, 'chamber': 'House',
                   'meetingDocuments': [{'url': url, 'documentType': 'Witness Statement'}]},
           family='congress/meetings', source_file='meeting.json')
    retain(store, {'url': url, 'media_type': 'application/pdf'}, family='documents',
           source_file='capture.json', url=url, body=b'%PDF-1.7\n%%EOF')
    read = store.read
    def metadata_only(key):
        assert not key.startswith(('bodies/', 'indexes/processing/sources',
                                   'indexes/processing/filenames')), key
        return read(key)
    store.read = metadata_only
    rebuild_catalog(store, workers=1)
    row, = table(store).to_pylist()
    assert row['document_kind'] == ['witness-statement']
    assert row['source_document_type'] == ['Witness Statement']
    from congress_api.retention.catalog_publication import read_catalog, MANIFEST_KEY
    snapshot = read_catalog(store)
    assert {key for key in store.writes} == {
        snapshot.manifest['files']['filenames']['key'], snapshot.manifest['files']['documents']['key'], MANIFEST_KEY}


def test_explicit_body_inspection_preserves_readings_on_later_metadata_only_update(monkeypatch):
    from congress_api.retention import document_evidence as evidence
    store = MemoryStore()
    url = 'https://example.gov/opaque.pdf'
    retain(store, {'url': url}, family='documents', source_file='capture.json',
           url=url, body=b'%PDF-1.7\n%%EOF')
    monkeypatch.setattr(evidence, 'document_cover', lambda _: {
        'content_document_kind': ['hearing-transcript'], 'content_citation': ['S. Hrg. 119-1']})
    rebuild_catalog(store, workers=1)
    assert table(store).to_pylist()[0]['document_kind'] is None
    rebuild_catalog(store, workers=1, inspect_bodies=True)
    inspected = table(store).to_pylist()[0]
    assert inspected['content_citation'] == ['S. Hrg. 119-1']
    original = store.read
    def no_body_read(key):
        assert not key.startswith('bodies/'), key
        return original(key)
    store.read = no_body_read
    monkeypatch.setattr(index, 'parser_fingerprint', lambda: 'new-filename-rules')
    monkeypatch.setattr(index, 'evidence_fingerprint', lambda: 'new-body-reader')
    rebuild_catalog(store, workers=1)
    row, = table(store).to_pylist()
    assert row['content_citation'] == ['S. Hrg. 119-1']
    assert row['document_kind'] == inspected['document_kind']
    rebuild_catalog(store, workers=1, repair=True)
    row, = table(store).to_pylist()
    assert row['content_citation'] == ['S. Hrg. 119-1']


def test_same_filename_does_not_transfer_content_facts_to_replacement_bytes(tmp_path):
    from test_document_evidence import retained
    (tmp_path / 'indexes').mkdir()
    old = retained(tmp_path, '123.xml', b'<witness-list meeting-id="HMKP1"/>')
    index.write_filename_metadata(tmp_path, [old], workers=1, inspect_bodies=True)
    before = pa.parquet.read_table(selected_path(tmp_path / 'indexes/document-filenames.parquet'))
    new = {**old, 'body_key': 'different-bytes'}
    index.write_filename_metadata(tmp_path, [new], workers=1, previous=before)
    row, = pa.parquet.read_table(selected_path(tmp_path / 'indexes/document-filenames.parquet')).to_pylist()
    assert row.get('source_record_type') is None
    assert row.get('source_record_identifier') is None


def test_periodic_result_checkpoint_saves_completed_negative_readings():
    from congress_api.retention.catalog_cache import result_checkpoint, load_results
    store = MemoryStore()
    now = [0]
    results = {}
    save = result_checkpoint(store, 'bodies', 'reader-v1', ('reader', 'body_key'), results,
                             interval=60, clock=lambda: now[0])
    results[('cover', 'retained-body')] = {}
    now[0] = 60
    save()
    assert load_results(store, 'bodies', 'reader-v1', ('reader', 'body_key')) == results
    writes = len(store.writes)
    now[0] = 120
    save()
    assert len(store.writes) == writes
    assert ('cover', 'missing-body') not in results


def test_explicit_source_kind_avoids_unnecessary_pdf_read(tmp_path):
    source = dict(filename='opaque.pdf', source_url='https://example.gov/opaque.pdf',
                  body_key='retained-pdf', source_document_type=['Witness Statement'])
    (tmp_path / 'indexes').mkdir()
    def forbidden(key):
        pytest.fail(f'Already typed document unnecessarily downloaded: {key}')
    index.write_filename_metadata(tmp_path, [source], workers=1, read_body=forbidden)
    row, = pa.parquet.read_table(selected_path(tmp_path / 'indexes/document-filenames.parquet')).to_pylist()
    assert row['document_kind'] == ['witness-statement']
    assert row['document_kind_source'] == ['source_document_type']


def test_source_kind_does_not_skip_structured_xml_evidence(tmp_path):
    from test_document_evidence import retained
    body = (b'<amendment-doc amend-type="house-amendment" amend-degree="first">'
            b'<amendment-form><legis-num>H.R. 123</legis-num></amendment-form>'
            b'<amendment-body/></amendment-doc>')
    source = retained(tmp_path, 'opaque.xml', body)
    source['source_document_type'] = ['Committee Amendment']
    (tmp_path / 'indexes').mkdir()
    index.write_filename_metadata(tmp_path, [source], workers=1, inspect_bodies=True)
    row, = pa.parquet.read_table(selected_path(tmp_path / 'indexes/document-filenames.parquet')).to_pylist()
    assert row.get('content_amendment_degree') == ['first']
    assert row['content_legis_num'] == ['H.R. 123']
    assert row['source_document_type'] == ['Committee Amendment']


def test_filters_derive_from_paired_occurrences_without_inventing_legacy_pairings():
    context = index.DocumentSources()
    url = 'https://example.gov/shared.pdf'
    context.add_url(url, {'source_document_type': ['Witness Statement', 'Legacy label'],
                         'source_occurrences': [{'source_document_type': ['Witness Statement'],
                                                 'source_page_url': ['https://example.gov/meeting']}]})
    context.add_url(url, {'source_page_url': ['https://example.gov/another'], 'source_document_type': ['Report']})
    context.extra_filters[url]['source_document_type'].add('Unpaired')
    expected = context.for_url(url)
    assert expected['source_document_type'] == ['Legacy label', 'Report', 'Unpaired', 'Witness Statement']
    assert not any('Legacy label' in o.get('source_document_type', []) for o in expected['source_occurrences'])
    restored = index.DocumentSources()
    restored.add_url(url, expected)
    assert restored.for_url(url) == expected
    assert all(isinstance(v, set) for v in restored.by_url[url].values())


def test_missing_body_is_attempted_once_per_run_across_aliases(tmp_path):
    (tmp_path / 'indexes').mkdir()
    calls = []
    rows = [dict(filename=name, source_url=f'https://example.gov/{name}', body_key='missing')
            for name in ('opaque-a.pdf', 'opaque-b.pdf')]
    index.write_filename_metadata(tmp_path, rows, workers=1, read_body=lambda key: calls.append(key), inspect_bodies=True)
    assert calls == ['missing']


def test_known_oversized_body_does_not_need_downloading_to_apply_read_limit():
    from congress_api.retention.raw_archive import CAPTURES_KEY, encode_table
    store = MemoryStore()
    body = b'%PDF-1.7\n' + b'x' * (16 * 1024**2)
    retain(store, {}, family='documents', source_file='opaque.pdf',
           url='https://example.gov/opaque.pdf', body=body)
    captures = table(store, CAPTURES_KEY)
    captures = captures.set_column(captures.schema.get_field_index('bytes'), 'bytes', pa.array([len(body)]))
    store.objects[CAPTURES_KEY] = encode_table(captures)
    read = store.read
    def metadata_only(key):
        assert not key.startswith('bodies/'), 'Known oversized body was fetched only to discard it'
        return read(key)
    store.read = metadata_only
    result = rebuild_catalog(store, workers=1)
    assert result['rows'] >= 1
    assert table(store).schema.metadata[b'deferred_body_reads'] == b'0'
    assert rebuild_catalog(store, workers=1)['unchanged'] is True
