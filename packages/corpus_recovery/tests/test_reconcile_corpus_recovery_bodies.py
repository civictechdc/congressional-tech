"""Body reconciliation uses fresh versions and falls back to exact bytes."""
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
        live={"export": None, "documents": []},
    )
    soft = dict(
        body_sha256="html",
        bucket="publisher_html_error_at_pdf_target",
        capture_history=[{"http_status": 200}],
        live={"export": None, "documents": [{"hidden": False, "doc_id": "public-link"}]},
        exclusion={"source_role": "error_response"},
    )
    source_roles.check_missed_errors([hard, soft])
    result = source_roles.public_copy_control([hard, soft])
    assert not result["passed"]
    assert [d["doc_id"] for d in result["unhidden_saved_copies"]] == ["public-link"]
    with pytest.raises(ValueError, match="soft HTML error"):
        source_roles.check_missed_errors([hard, dict(soft, exclusion=None)])
    with pytest.raises(ValueError, match="HTTP failure"):
        source_roles.check_missed_errors([dict(hard, live=soft["live"]), soft])


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
