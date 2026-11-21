"""Body reconciliation uses fresh versions and falls back to exact bytes."""
from copy import deepcopy
import gzip
import hashlib
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from corpus_recovery.inventory import reconcile, run


class Client:
    def __init__(self, raw):
        self.data = gzip.compress(raw, mtime=0)
        self.gets = self.heads = 0

    def head_object(self, **kwargs):
        self.heads += 1
        return dict(ETag=hashlib.md5(self.data).hexdigest(), ContentLength=len(self.data))

    def get_object(self, **kwargs):
        self.gets += 1
        return dict(self.head_object(**kwargs), Body=io.BytesIO(self.data))


def setup(raw=b'current exact body'):
    sha = hashlib.sha256(raw).hexdigest()
    key = f'bodies/sha256/{sha[:2]}/{sha}.gz'
    client = Client(raw)
    return SimpleNamespace(client=client, bucket='test'), {key: dict(sha256=sha, bytes=len(raw))}, key


def test_full_then_prior_reuses_only_fresh_matching_version():
    store, inventory, key = setup()
    first = reconcile(store, inventory)
    assert first['results'][key]['status'] == 'verified_exact_body'
    assert store.client.gets == 1
    assert reconcile(store, inventory, prior=first)['results'][key]['verification'].startswith('prior_full')
    assert store.client.gets == 1
    store.client.data = gzip.compress(b'current exact body', compresslevel=1, mtime=23)
    assert reconcile(store, inventory, prior=first)['results'][key]['verification'] == 'full_body_sha256'
    assert store.client.gets == 2


@pytest.mark.parametrize('change', [dict(sha256='wrong'), dict(raw_bytes=1), dict(stored_sha256='broken'), dict(stored_bytes=True)])
def test_corrupt_prior_falls_back_to_full_bytes(change):
    store, inventory, key = setup()
    prior = reconcile(store, inventory)
    prior['results'][key].update(change)
    assert reconcile(store, inventory, prior=prior)['results'][key]['status'] == 'verified_exact_body'
    assert store.client.gets == 2


def test_current_wrong_body_is_conflict():
    store, inventory, key = setup()
    store.client.data = gzip.compress(b'wrong retained body', mtime=0)
    assert reconcile(store, inventory)['results'][key]['status'] == 'conflict'


def test_unknown_read_failure_stays_unresolved():
    store, inventory, key = setup()
    store.client.get_object = Mock(side_effect=TimeoutError('uncertain'))
    assert reconcile(store, inventory)['results'][key]['status'] == 'unresolved'


def test_pinned_prior_rejects_changed_file_before_network(tmp_path):
    prior = tmp_path / 'prior.json'
    prior.write_text('{}')
    args = SimpleNamespace(batch=tmp_path, prior=prior, prior_sha256='wrong')
    with patch('corpus_recovery.inventory.sealed_inputs', return_value=({}, {}, {})):
        with pytest.raises(ValueError, match='Prior evidence digest mismatch'):
            run(args)


@pytest.fixture
def source_roles(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts/measure"))
    import reconcile_ct_en4n_source_roles

    return reconcile_ct_en4n_source_roles


def test_inventory_requires_every_distinct_sha_and_rejects_legitimate_sources(source_roles):
    ids = [hashlib.sha256(str(i).encode()).hexdigest() for i in range(455)]
    expected = {sha: "incomplete_pdf" for sha in ids}
    rows = [dict(body_sha256=sha, bucket=expected[sha], live={"export": None}) for sha in ids]
    assert sum(source_roles.verify_partition(rows, expected, {}).values()) == 455
    with pytest.raises(ValueError, match="identity partition"):
        source_roles.verify_partition(rows[:-1] + rows[:1], expected, {})
    with pytest.raises(ValueError, match="classification"):
        source_roles.verify_partition([dict(rows[0], bucket="empty_stub"), *rows[1:]], expected, {})
    with pytest.raises(ValueError, match="legitimate control"):
        source_roles.verify_partition(rows, expected, {ids[0]: "legitimate_zip_container"})
    with pytest.raises(ValueError, match="delivered as text"):
        source_roles.verify_partition(
            [dict(rows[0], live={"export": {"text_sha256": "digest"}}), *rows[1:]], expected, {}
        )


@pytest.mark.parametrize(
    "role",
    [
        "valid-structured-meeting-metadata-control",
        "valid-meeting-landing-control",
        "statute_viewer",
        "atom_feed",
        "legitimate_zip_container",
    ],
)
def test_false_error_label_on_reviewed_source_is_rejected(source_roles, role):
    sha = "reviewed-control"
    expected = {"statute_viewer": "wrapper", "atom_feed": "feed"}.get(role)
    exclusion = {sha: {"source_role": expected}} if expected else {}
    state = {"export": None, "documents": [{"hidden": False, "format": "zip"}]}
    source_roles.verify_control(sha, {"role": role}, state, exclusion)
    with pytest.raises(ValueError, match="false-positive"):
        source_roles.verify_control(sha, {"role": role}, state, {sha: {"source_role": "error_response"}})


def test_public_valid_empty_control_requires_both_visible_document_and_empty_export(source_roles):
    control = dict(
        role="reviewed_valid_empty_reading",
        expected_visible_documents=1,
        expected_text_sha256=source_roles.EMPTY,
    )
    valid = dict(documents=[{"hidden": False}], export={"text_sha256": source_roles.EMPTY})
    source_roles.verify_control("empty", control, valid, {})
    for loss in [dict(documents=[], export=None), dict(valid, documents=[{"hidden": True}])]:
        with pytest.raises(ValueError, match="control exposure"):
            source_roles.verify_control("empty", control, loss, {})
    with pytest.raises(ValueError, match="text digest"):
        source_roles.verify_control("empty", control, dict(valid, export=None), {})


def test_quoted_error_requires_reviewed_text_digest(source_roles):
    digest = hashlib.sha256(b'The witness quoted "Access Denied" in testimony.').hexdigest()
    control = dict(
        role="ordinary_document_quoting_error_language",
        expected_visible_documents=1,
        expected_text_sha256=digest,
    )
    valid = dict(documents=[{"hidden": False}], export={"text_sha256": digest})
    source_roles.verify_control("quote", control, valid, {})
    for other in [source_roles.EMPTY, hashlib.sha256(b"different nonempty text").hexdigest()]:
        with pytest.raises(ValueError, match="text digest"):
            source_roles.verify_control("quote", control, dict(valid, export={"text_sha256": other}), {})
    with pytest.raises(ValueError, match="control exposure"):
        source_roles.verify_control("quote", control, dict(documents=[], export=None), {})


@pytest.mark.parametrize(
    ("kind", "role"),
    [
        ("embedded_house_meeting_fallback", "house_meeting_listing_member"),
        ("retained_senate_listing_security_response", "senate_hearings_listing"),
    ],
)
def test_listing_handoff_resolves_target_without_dispatching_a_document(source_roles, kind, role):
    prior = dict(
        source_urls=[],
        targets=[],
        recovery_open=True,
        needs_refetch=None,
        recovery_state="needs_capture_history_review",
        capture_history={"status": "missing_url"},
    )
    fact = dict(
        kind=kind, source_url="https://example.org/hearings", url_basis="receipt", http_requested_url=None
    )
    row = source_roles.recovery_record(prior, fact, "error_response", {fact["source_url"]: {"captures": []}})
    assert row["recovery_state"] == "listing_identified_no_document_target"
    assert row["source_role"] == role and row["needs_refetch"] is False
    assert row["next_action"] == "retain_listing_evidence"
    (target,) = row["targets"]
    assert row["source_urls"] == [target["requested_target"]] == [fact["source_url"]]
    assert target["http_requested_url"] is None and not target["dispatch_enabled"]
    assert row["document_fetch_eligibility"] == target["document_fetch_eligibility"] == "no_document_target"


def test_pdf_signature_in_html_or_zip_is_not_a_truncated_pdf(source_roles):
    from pdf_source_structure import truncated_header

    header = b"%PDF-1.4\n1 0 obj\n<</Linearized 1 /L 43652/N 4>>"
    assert truncated_header(header, 1553) == 43652
    assert truncated_header(header, 43652) is None
    for prefix in [b"<html>quoting ", b"<?xml?>", b"PK\x03\x04", b"WARC/1.0\r\n"]:
        assert truncated_header(prefix + header, 1553) is None


def test_missed_error_and_public_copy_checks_are_independent(source_roles):
    hard = dict(
        body_sha256="playlist",
        bucket="missing_recording_playlist",
        capture_history=[{"http_status": 404}],
        live={"export": None, "documents": [], "alternates": [], "recoveries": []},
    )
    soft = dict(
        body_sha256="html",
        bucket="publisher_html_error_at_pdf_target",
        capture_history=[{"http_status": 200}],
        live={
            "export": None,
            "documents": [{"hidden": False, "doc_id": "public-link", "saved_body": "html"}],
            "alternates": [],
            "recoveries": [],
        },
        exclusion={"source_role": "error_response"},
    )
    source_roles.check_missed_errors([hard, soft])
    result = source_roles.public_copy_control([hard, soft], {})
    assert not result["passed"]
    assert result["default_list_visible"] == result["detail_downloads"] == 1
    with pytest.raises(ValueError, match="soft HTML error"):
        source_roles.check_missed_errors([hard, dict(soft, exclusion=None)])
    with pytest.raises(ValueError, match="HTTP failure"):
        source_roles.check_missed_errors([dict(hard, live=soft["live"]), soft])


def test_public_copy_check_counts_wrappers_and_hidden_detail_downloads(source_roles):
    def source(key, bucket, *docs, **fields):
        return dict(
            body_sha256=key,
            bucket=bucket,
            live={
                "documents": [dict(doc_id=doc_id, hidden=hidden, saved_body=key) for doc_id, hidden in docs],
                "alternates": [],
                "recoveries": [],
            },
            **fields,
        )

    walling = "20568d1abba1b309"
    rows = [source(str(i), "damaged_pdf", (str(i), False)) for i in range(21)]
    rows.append(source("walling-body", "damaged_pdf", (walling, False)))
    rows[-1]["live"]["recoveries"] = [dict(rows[-1]["live"]["documents"][0])]
    wrappers = {}
    for payload, wrapper in [
        ("359e3b8b6b844d69", "6eea94ddc3e78724"),
        ("82867326cf8750a2", "b6aaf0d8fdba71e2"),
    ]:
        rows.append(source(payload, "error_response", (payload, False)))
        wrappers[wrapper] = source(
            wrapper, "archive_wrapper_of_error_response", (wrapper, False), payload_sha256=payload
        )
    # Bakst and Mitchell have distinct document identities and the same error body.
    for keys in [
        ("85afe0532f6c8e0b",),
        ("a3002f39e37a6384",),
        ("90bd27046786ab4e",),
        ("8b408d366abfb89d", "e8c6aced18461017"),
    ]:
        row = source(keys[0], "publisher_html_error_at_pdf_target", *((key, True) for key in keys))
        row["live"]["recoveries"] = [dict(doc) for doc in row["live"]["documents"]]
        rows.append(row)

    check = source_roles.public_copy_control(rows, wrappers)
    assert (check["default_list_visible"], check["detail_downloads"], check["passed"]) == (26, 31, False)
    by_key = {d["doc_id"]: d for d in check["records"]}
    assert [d["kind"] for d in by_key[walling]["downloads"]] == ["primary"]
    assert {
        k for k, d in by_key.items() if d["detail_download_available"] and not d["default_list_visible"]
    } == {"85afe0532f6c8e0b", "a3002f39e37a6384", "90bd27046786ab4e", "8b408d366abfb89d", "e8c6aced18461017"}
    for wrapper, r in wrappers.items():
        assert by_key[wrapper]["default_list_visible"] and by_key[wrapper]["detail_download_available"]
        assert by_key[wrapper]["recovery_payload_sha256"] == r["payload_sha256"]
    assert len({d["recovery_payload_sha256"] for d in check["records"]}) == len(rows)
    hidden_rows, hidden_wrappers = deepcopy((rows, wrappers))
    for row in [*hidden_rows, *hidden_wrappers.values()]:
        for field in ("documents", "recoveries"):
            for doc in row["live"][field]:
                doc["hidden"] = True
    hidden = source_roles.public_copy_control(hidden_rows, hidden_wrappers)
    assert (hidden["default_list_visible"], hidden["detail_downloads"], hidden["passed"]) == (0, 31, False)
    assert hidden["default_list_passed"] and not hidden["detail_downloads_passed"]
    for row in [*rows, *wrappers.values()]:
        # Removing the invalid primaries from detail.parquet removes their saved-body
        # joins. recoveries.parquet still joins all six bodies to the same pages.
        row["live"]["documents"].clear()
        for doc in row["live"]["recoveries"]:
            doc["saved_body"] = None
    cleared = source_roles.public_copy_control(rows, wrappers)
    assert (cleared["default_list_visible"], cleared["detail_downloads"], cleared["passed"]) == (1, 6, False)
    assert {d["doc_id"] for d in cleared["records"]} == {
        "85afe0532f6c8e0b", "a3002f39e37a6384", "90bd27046786ab4e",
        "8b408d366abfb89d", "e8c6aced18461017", walling,
    }
    assert all([link["kind"] for link in d["downloads"]] == ["recovery"] for d in cleared["records"])


def test_alternate_and_recovery_on_the_same_detail_page(source_roles):
    page = dict(doc_id="page", saved_body="qualified-primary", hidden=True)
    alternate = dict(
        body_sha256="a", bucket="damaged_pdf", live=dict(documents=[], alternates=[page], recoveries=[])
    )
    recovery = dict(
        body_sha256="b", bucket="damaged_pdf", live=dict(documents=[], alternates=[], recoveries=[page])
    )
    rows = [alternate, recovery]

    def check(expected):
        result = source_roles.public_copy_control(rows, {})
        assert result["passed"] == (not expected)
        assert result["detail_downloads"] == len(result["records"]) == int(bool(expected))
        assert [(d["kind"], d["body_sha256"]) for p in result["records"] for d in p["downloads"]] == expected

    check([("alternate", "a"), ("recovery", "b")])
    page["saved_body"] = None
    check([("recovery", "b")])
    recovery["live"]["recoveries"].clear()
    check([])
    page["saved_body"] = "qualified-primary"
    check([("alternate", "a")])


def test_handoff_replaces_obsolete_associations_and_labels_their_releases(source_roles):
    stale = dict(link_key="11eb671c53675b03", hidden=False, saved_kind="original")
    row = dict(
        body_sha256="damaged", release_associations=[stale], release_associations_20261117=[dict(stale, title="old")]
    )
    prior_ids = {"release_associations": "first", "release_associations_20261117": "second"}
    live = dict(documents=[], alternates=[], recoveries=[])
    handoff = source_roles.handoff_associations(row, live, prior_ids)
    assert handoff["release_id"] == source_roles.RELEASE
    assert handoff["release_associations"] == []
    assert handoff["prior_release_associations"] == [
        dict(release_id="first", associations=[stale]),
        dict(release_id="second", associations=row["release_associations_20261117"]),
    ]
    for field in live:
        live[field].append(dict(doc_id=field, saved_body="damaged" if field == "documents" else "other"))
    current = source_roles.handoff_associations(row, live, prior_ids)["release_associations"]
    assert [(d["link_key"], d["association_type"], d["body_sha256"], d["saved_body"]) for d in current] == [
        ("documents", "primary", "damaged", "damaged"),
        ("alternates", "alternate", "damaged", "other"),
        ("recoveries", "recovery", "damaged", "other"),
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_bullet",
        "truncated_tail",
        "page_offset",
        "version",
        "duplicate_reading",
        "hidden_document",
        "wrong_saved_body",
    ],
)
def test_cleanup_readback_rejects_planted_losses_and_identity_changes(monkeypatch, mutation):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts/measure"))
    from reconcile_ct_kfsd_cleanup import verify_selected

    first = "• Amendment to committee rules\n"
    text = first + "VerDate 2016\nThe testimony continues."
    raw = text.encode()
    offsets = [0, len(first.encode())]
    digest = hashlib.sha256(raw)
    sha = hashlib.sha256(b"retained PDF").digest()
    row = dict(
        body_sha=sha,
        parser="pdf_text",
        parser_version="reviewed",
        text=text,
        text_sha256=digest.digest(),
        page_offsets=offsets,
    )
    live = dict(
        documents=[{"saved_body": sha.hex(), "hidden": False}],
        export=dict(text_sha256=digest.hexdigest(), page_offsets=offsets),
        readings=[dict(parser="pdf_text", parser_version="reviewed", status="completed", error_type=None)],
    )
    sample = dict(row)
    verify_selected(row, live, digest.hexdigest(), "reviewed", sample)
    if mutation == "missing_bullet":
        sample["text"] = text.removeprefix(first)
    elif mutation == "truncated_tail":
        sample["text"] = text.split("The testimony")[0]
    elif mutation == "page_offset":
        live["export"]["page_offsets"] = [0, len(first)]
    elif mutation == "version":
        live["readings"][0]["parser_version"] = "unreviewed"
    elif mutation == "duplicate_reading":
        live["readings"] *= 2
    elif mutation == "hidden_document":
        live["documents"][0]["hidden"] = True
    else:
        live["documents"][0]["saved_body"] = "different"
    with pytest.raises(ValueError):
        verify_selected(row, live, digest.hexdigest(), "reviewed", sample)
