"""Recurring acquisition must preserve bytes, provenance and retryable failures."""

import gzip
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.acquisition.raw_sync import run_sync
from congress_api.parsers.archive_links import related_links, allowed_url
from congress_api.retention.raw_archive import Archive, CAPTURE_SCHEMA, encode_table
from congress_api.models.content import RawContent


class MemoryStore:
    def __init__(self):
        self.objects = {
            "indexes/captures.parquet": encode_table(
                pa.Table.from_pylist([], schema=CAPTURE_SCHEMA)
            )
        }
        self.writes = []

    def read(self, key):
        return self.objects.get(key)

    def put(self, key, body, *, immutable=False):
        if immutable and key in self.objects:
            assert self.objects[key] == body
            return
        self.objects[key] = body
        self.writes.append(key)

    def keys(self, prefix):
        return sorted(k for k in self.objects if k.startswith(prefix))


def response(url, body, media="application/pdf", status=200, **extra):
    return dict(
        requested_url=url,
        url=url,
        http_status=status,
        response_headers={"content-type": media},
        response_header_items=[{"name": "content-type", "value": media}],
        complete=True,
        retrieved_at="2026-10-01T00:00:00+00:00",
        content=RawContent.from_bytes(body, media).source_dict(),
        **extra,
    )


def test_capture_links_and_resume_without_repeating_successes():
    store = MemoryStore()
    calls = []
    url = "https://example.gov/download/statement"
    pdf = "https://example.gov/statement.pdf"

    def fetch(u):
        calls.append(u)
        return (
            response(
                u, b'<html><a href="/statement.pdf">Download</a></html>', "text/html"
            )
            if u == url
            else response(u, b"%PDF-1.7\ncontent\n%%EOF")
        )

    run_sync(
        Archive(store, "first"),
        [{"url": url, "context": {"committee": "hsru00"}}],
        fetch=fetch,
        limit=10,
        workers=2,
    )
    assert set(calls) == {url, pdf}
    receipts = [
        json.loads(line)
        for k, v in store.objects.items()
        if k.startswith("receipts/")
        for line in gzip.decompress(v).splitlines()
    ]
    assert any(
        r["record"].get("links", [{}])[0].get("url") == pdf
        for r in receipts
        if r["record"].get("links")
    )
    assert all(
        "body" not in str(r["record"].get("content", {}))
        or r["record"]["content"]["body"] is None
        for r in receipts
    )
    keys_before = store.keys("receipts/")
    calls.clear()
    run_sync(Archive(store, "second"), [{"url": url}], fetch=fetch, limit=10, workers=2)
    assert calls == []
    assert store.keys("receipts/") == keys_before


def test_200_challenge_and_failed_provider_do_not_become_saved_documents():
    store = MemoryStore()
    u = "https://example.gov/a.pdf"
    run_sync(
        Archive(store, "failure"),
        [{"url": u}],
        fetch=lambda u: response(
            u, b"<html><title>Just a moment</title></html>", "application/pdf"
        ),
        limit=1,
    )
    state = Archive(store, "read").state
    assert state[u]["outcome"] == "challenge"
    assert state[u]["next_attempt_at"]
    assert state[u]["body_key"]


def test_saved_html_is_scanned_without_an_upstream_refetch():
    store = MemoryStore()
    a = Archive(store, "seed")
    u = "https://example.gov/wrapper"
    a.record(
        response(
            u, b'<html><a download href="/file.pdf">Statement</a></html>', "text/html"
        ),
        outcome="retained",
        links=[],
        scanned=False,
    )
    a.save()
    calls = []

    def fetch(url):
        calls.append(url)
        return response(url, b"%PDF-1.7\n%%EOF")

    run_sync(Archive(store, "scan"), [], fetch=fetch, limit=2)
    assert calls == ["https://example.gov/file.pdf"]


def test_receipt_recovery_after_interrupted_index_publication():
    store = MemoryStore()
    a = Archive(store, "interrupted")
    u = "https://example.gov/a.pdf"
    a.record(response(u, b"%PDF-1.7\n%%EOF"), outcome="saved", links=[])
    a.flush()
    # Body and receipt reached storage, but neither table did.
    b = Archive(store, "retry")
    assert b.state[u]["outcome"] == "saved"
    calls = []
    run_sync(b, [{"url": u}], fetch=lambda u: calls.append(u), limit=1)
    assert calls == []
    rows = pq.read_table(
        pa.BufferReader(store.read("indexes/captures.parquet"))
    ).to_pylist()
    assert len(rows) == 1
    assert rows[0]["context_url"] == u


def test_attempt_budget_leaves_discovered_links_for_the_next_run():
    store = MemoryStore()
    u = "https://example.gov/a"
    child = "https://example.gov/b.pdf"
    run_sync(
        Archive(store, "one"),
        [{"url": u}],
        fetch=lambda u: response(
            u, b'<html><a href="b.pdf">Download</a></html>', "text/html"
        ),
        limit=1,
    )
    assert Archive(store, "check").state[child]["outcome"] == "pending"


def test_related_xml_keeps_native_attributes_and_ignores_video_bytes():
    links = related_links(
        b'<root><file doc-url="/a.pdf" doc-type="BR"/><url>https://example.gov/b.xml</url><file doc-url="/film.mp4"/></root>',
        "https://example.gov/root.xml",
        "xml",
    )
    assert [r["url"] for r in links] == [
        "https://example.gov/a.pdf",
        "https://example.gov/b.xml",
    ]
    assert links[0]["attributes"]["doc-type"] == "BR"
    assert not allowed_url("http://127.0.0.1/secrets.pdf")
    assert not allowed_url("https://example.gov/file.mp4")
    assert not allowed_url("https://api.congress.gov/v3/foo?api_key=secret")


def test_retry_delay_and_original_absence_receipt_survive_later_success():
    store = MemoryStore()
    u = "https://example.gov/a.pdf"
    calls = []
    run_sync(
        Archive(store, "not-found"),
        [{"url": u}],
        fetch=lambda u: response(u, b"missing", status=404),
        limit=1,
    )
    a = Archive(store, "later")
    assert a.state[u]["http_status"] == 404
    run_sync(a, [], fetch=lambda u: calls.append(u), limit=1)
    assert calls == []
    a.state[u]["next_attempt_at"] = "2020-01-01T00:00:00+00:00"
    a.save()
    run_sync(
        Archive(store, "recovered"),
        [],
        fetch=lambda u: response(u, b"%PDF-1.7\n%%EOF"),
        limit=1,
    )
    rows = pq.read_table(
        pa.BufferReader(store.read("indexes/captures.parquet"))
    ).to_pylist()
    assert [r["http_status"] for r in rows] == [404, 200]


def test_unknown_legacy_status_is_not_rewritten_as_200_during_replay():
    store = MemoryStore()
    a = Archive(store, "legacy")
    u = "https://example.gov/a.pdf"
    a.record(
        response(u, b"%PDF-1.7\n%%EOF", status=None),
        outcome="retained",
        links=[],
        scanned=False,
    )
    a.save()
    run_sync(
        Archive(store, "replay"),
        [],
        fetch=lambda _: pytest.fail("Existing body should be read"),
        limit=1,
    )
    rows = pq.read_table(
        pa.BufferReader(store.read("indexes/captures.parquet"))
    ).to_pylist()
    assert {r["http_status"] for r in rows} == {None}


def test_replay_preserves_unknown_capture_date_and_saved_text_fidelity():
    store = MemoryStore()
    a = Archive(store, "legacy")
    u = "https://example.gov/transcript.txt"
    body = b"Previously extracted transcript text"
    key = a.put_body(body)
    digest = RawContent.from_bytes(body, "text/plain").sha256
    store.objects["indexes/captures.parquet"] = encode_table(
        pa.Table.from_pylist(
            [
                dict(
                    family="documents",
                    context_url=u,
                    body_key=key,
                    sha256=digest,
                    fidelity="saved-text",
                    media_type="text/plain",
                    http_status=None,
                )
            ],
            schema=CAPTURE_SCHEMA,
        )
    )
    run_sync(
        Archive(store, "replay"),
        [],
        fetch=lambda _: pytest.fail("Existing text should be read"),
        limit=1,
    )
    rows = pq.read_table(
        pa.BufferReader(store.read("indexes/captures.parquet"))
    ).to_pylist()
    assert len(rows) == 2
    assert {r["retrieved_at"] for r in rows} == {None}
    assert {r["fidelity"] for r in rows} == {"saved-text"}
    assert rows[-1]["capture_date"] == "undated"
    assert Archive(store, "read").state[u]["checked_at"]


def test_filename_alias_cannot_mix_body_identity_or_replace_better_capture():
    store = MemoryStore()
    a = Archive(store, "seed")
    u = "https://example.gov/a.pdf"
    rows = []
    for body, date in [
        (b"%PDF-1.7\nnew\n%%EOF", "2026-09-30"),
        (b"%PDF-1.7\nold\n%%EOF", "2026-09-01"),
    ]:
        key = a.put_body(body)
        digest = RawContent.from_bytes(body, "application/pdf").sha256
        rows.append(
            dict(
                family="documents",
                context_url=u,
                body_key=key,
                sha256=digest,
                media_type="application/pdf",
                http_status=200,
                retrieved_at=date,
                fidelity="exact-bytes",
            )
        )
    store.objects["indexes/captures.parquet"] = encode_table(
        pa.Table.from_pylist(rows, schema=CAPTURE_SCHEMA)
    )
    store.objects["indexes/document-filenames.parquet"] = encode_table(
        pa.Table.from_pylist(
            [
                dict(
                    source_url=u,
                    body_key=rows[-1]["body_key"],
                    format=["pdf"],
                    http_status=["200"],
                    media_type=["application/pdf"],
                )
            ]
        )
    )
    loaded = Archive(store, "read")
    assert loaded.state[u]["body_key"] == rows[0]["body_key"]
    assert loaded.state[u]["sha256"] == rows[0]["sha256"]
    assert loaded.body(loaded.state[u]) == b"%PDF-1.7\nnew\n%%EOF"


def test_pipeline_seed_shapes_retain_context_and_all_xml_variants():
    from congress_api.parsers.archive_links import json_links

    raw = {
        "eventId": 123,
        "congress": 119,
        "committees": [{"systemCode": "hsru00"}],
        "meetingDocuments": [
            {
                "url": "https://example.gov/a.pdf",
                "documentType": "Witness Statement",
                "newField": "kept",
            }
        ],
        "urls": [
            "https://docs.house.gov/meeting.xml",
            "https://docs.house.gov/witness.xml",
        ],
    }
    links = list(json_links(raw, "pipeline.json"))
    assert len(links) == 3
    assert links[0]["native"]["newField"] == "kept"
    assert all(link["context"]["committees"] == raw["committees"] for link in links)


def test_s3_failure_after_state_write_recovers_capture_index_without_refetch():
    class FailIndexOnce(MemoryStore):
        failed = False

        def put(self, key, body, **kwargs):
            if key == "indexes/captures.parquet" and not self.failed:
                self.failed = True
                raise OSError("simulated index upload failure")
            return super().put(key, body, **kwargs)

    store = FailIndexOnce()
    u = "https://example.gov/a.pdf"
    with pytest.raises(OSError):
        run_sync(
            Archive(store, "interrupted"),
            [{"url": u}],
            fetch=lambda u: response(u, b"%PDF-1.7\n%%EOF"),
            limit=1,
        )
    run_sync(
        Archive(store, "recovered"),
        [],
        fetch=lambda _: pytest.fail("Published receipt should recover"),
        limit=1,
    )
    assert (
        len(pq.read_table(pa.BufferReader(store.read("indexes/captures.parquet")))) == 1
    )


def test_same_body_deduplicates_and_provider_keeps_publisher_status():
    import base64

    store = MemoryStore()
    u = "https://example.gov/a.pdf"
    raw = b"Forbidden"
    r = response(
        u,
        raw,
        status=403,
        provider_http_status=200,
        provider_response={
            "statusCode": 403,
            "httpResponseBody": base64.b64encode(raw).decode(),
        },
    )
    run_sync(Archive(store, "blocked"), [{"url": u}], fetch=lambda _: r, limit=1)
    assert len(store.keys("bodies/")) == 1
    rows = pq.read_table(
        pa.BufferReader(store.read("indexes/captures.parquet"))
    ).to_pylist()
    assert len(rows) == 2 and {row["http_status"] for row in rows} == {403}
    assert {row["family"] for row in rows} == {"documents"}


def test_provider_authorization_failure_drains_inflight_receipts():
    import threading

    barrier = threading.Barrier(2)
    store = MemoryStore()

    def fetch(url):
        barrier.wait(timeout=2)
        return dict(
            requested_url=url,
            url=url,
            retrieved_at="2026-10-01T00:00:00+00:00",
            complete=False,
            error="provider_http_error",
            provider_http_status=401,
            provider_response={"detail": "Unauthorized"},
        )

    with pytest.raises(RuntimeError, match="authorization failed"):
        run_sync(
            Archive(store, "auth"),
            [{"url": f"https://example.gov/{i}.pdf"} for i in range(3)],
            fetch=fetch,
            workers=2,
            limit=3,
        )
    records = [
        json.loads(line)
        for k, v in store.objects.items()
        if k.startswith("receipts/")
        for line in gzip.decompress(v).splitlines()
    ]
    assert len(records) == 2
    assert all(r["record"]["provider_http_status"] == 401 for r in records)


def test_retained_body_limit_defers_without_reading_or_refetching():
    store = MemoryStore()
    a = Archive(store, "large")
    u = "https://example.gov/large.pdf"
    a.record(
        response(u, b"%PDF-1.7\n" + b"x" * 4096 + b"%%EOF"),
        outcome="retained",
        links=[],
        scanned=False,
    )
    a.save()
    read = store.read

    def no_body_read(key):
        if key.startswith("bodies/"):
            pytest.fail("Known oversized body should not be loaded")
        return read(key)

    store.read = no_body_read
    run_sync(
        Archive(store, "inspect"),
        [],
        fetch=lambda _: pytest.fail("No refetch"),
        limit=1,
        max_bytes=1024,
    )
    state = Archive(store, "later").state[u]
    assert state["outcome"] == "inspection_deferred"
    assert state["body_key"] and not state["links_scanned"]
    assert state["attempts"] == 1  # Original capture only; inspection isn't HTTP.
    assert state["next_attempt_at"]
    run_sync(
        Archive(store, "cooldown"), [], fetch=lambda _: pytest.fail("Not due"), limit=1
    )


def test_malformed_subtitle_playlist_is_retained_and_does_not_stop_batch():
    store = MemoryStore()
    urls = ["https://example.gov/a.m3u8", "https://example.gov/b.pdf"]

    def fetch(url):
        return (
            response(url, b"#EXTM3U\n\xff", "application/vnd.apple.mpegurl")
            if url.endswith("m3u8")
            else response(url, b"%PDF-1.7\n%%EOF")
        )

    run_sync(
        Archive(store, "malformed"), [{"url": u} for u in urls], fetch=fetch, limit=2
    )
    state = Archive(store, "check").state
    assert state[urls[0]]["outcome"] == "parse_failed"
    assert state[urls[0]]["body_key"] and state[urls[0]]["next_attempt_at"]
    assert state[urls[1]]["outcome"] == "saved"
