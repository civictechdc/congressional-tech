"""Evidence bytes from failed responses must not suppress a future download."""

import json
import pyarrow as pa
import pytest
from congress_api.retention.raw_archive import (
    Archive,
    CAPTURE_SCHEMA,
    STATE_KEY,
    encode_table,
)
from test_raw_source_sync import MemoryStore, response

URL = "https://www.govinfo.gov/content/pkg/CHRG-118hhrg56269/pdf/CHRG-118hhrg56269.pdf"


def test_incomplete_prior_response_is_not_a_retained_source_when_repairing():
    store = MemoryStore()
    a = Archive(store, "seed")
    partial = response(URL, b"%PDF-1.4\npartial")
    partial.update(complete=False, error="body_error")
    failed = dict(
        requested_url=URL,
        url=URL,
        complete=False,
        retrieved_at=partial["retrieved_at"],
        transport="zyte",
        provider_http_status=520,
        error="provider_http_error",
        prior_attempts=[partial],
    )
    a.record(failed, outcome="request_failed", links=[])
    a.save()
    old = store.read(STATE_KEY)
    loaded = Archive(store, "repair", repair=True)
    assert loaded.state[URL]["outcome"] == "request_failed"
    assert loaded.state[URL]["body_key"] is None
    assert old and any(k.startswith("bodies/") for k in store.objects)


@pytest.mark.parametrize("resolution,pointer", [
    ("request_failed", ["content", "body"]),
    ("saved", ["prior_attempts", 0, "content", "body"]),
])
def test_indexed_failed_capture_never_seeds_retained_body(resolution, pointer):
    store = MemoryStore()
    a = Archive(store, "seed")
    key = a.put_body(b"%PDF-1.4\npartial")
    store.objects["indexes/captures.parquet"] = encode_table(
        pa.Table.from_pylist(
            [
                dict(
                    family="documents",
                    context_url=URL,
                    body_key=key,
                    sha256=key.rsplit("/", 1)[-1][:-3],
                    http_status=200,
                    fidelity="exact-bytes",
                    reference_kind="capture",
                    resolution=resolution,
                    pointer_json=json.dumps(pointer),
                    retrieved_at="2026-10-05",
                )
            ],
            schema=CAPTURE_SCHEMA,
        )
    )
    loaded = Archive(store, "load")
    assert loaded.state[URL]["outcome"] == "pending"
    assert not loaded.state[URL].get("body_key")


def test_catalog_partial_alias_does_not_replace_failed_download_state():
    store = MemoryStore()
    a = Archive(store, "seed")
    failed = dict(
        requested_url=URL,
        url=URL,
        complete=False,
        retrieved_at="2026-10-05T23:37:00+00:00",
        error="request_error",
    )
    a.record(failed, outcome="request_failed", links=[])
    a.save()
    key = a.put_body(b"%PDF-1.4\npartial")
    store.objects["indexes/document-filenames.parquet"] = encode_table(
        pa.Table.from_pylist(
            [
                dict(
                    source_url=URL,
                    body_key=key,
                    format=["pdf"],
                    http_status=["200"],
                    media_type=["application/pdf"],
                )
            ]
        )
    )
    loaded = Archive(store, "load")
    assert loaded.state[URL]["outcome"] == "request_failed"
    assert loaded.state[URL]["body_key"] is None
