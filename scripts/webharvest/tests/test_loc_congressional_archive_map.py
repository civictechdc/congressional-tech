"""Tests for LoC Congressional Web Archive catalog map and safety guards."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "loc_congressional_archive_map",
    ROOT / "scripts/webharvest/loc_congressional_archive_map.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class _FakeSession:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, headers=None, timeout=None, allow_redirects=False):  # noqa: ANN001
        self.calls.append((url, {"headers": headers, "allow_redirects": allow_redirects}))
        if not self._responses:
            raise AssertionError("Unexpected extra HTTP call")
        return self._responses.pop(0)


def _fake_resp(
    status_code: int,
    *,
    headers: dict[str, str] | None = None,
    content: bytes = b'{"results": []}',
    json_data: object = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        status_code=status_code,
        headers=headers or {"Content-Type": "application/json"},
        content=content,
        json=lambda: json_data if json_data is not None else json.loads(content.decode("utf-8")),
    )


def test_fetch_loc_json_rejects_screened_urls_challenges_retry_after_and_paces_redirects(monkeypatch):
    session = _FakeSession([])
    with pytest.raises(ValueError, match="non-www.loc.gov"):
        MODULE.fetch_loc_json(session, "https://webarchive.loc.gov/all/*/https://oversight.house.gov/")
    with pytest.raises(ValueError, match="without fo=json"):
        MODULE.fetch_loc_json(session, "https://www.loc.gov/collections/united-states-congressional-web-archive/")
    assert session.calls == []

    for status in (429, 403):
        s = _FakeSession([_fake_resp(status, headers={"Content-Type": "text/html"}, content=b"blocked")])
        with pytest.raises(RuntimeError, match=f"HTTP {status}"):
            MODULE.fetch_loc_json(s, MODULE.LCWA_SEED)
        assert len(s.calls) == 1

    cf_sess = _FakeSession([_fake_resp(200, headers={"Content-Type": "application/json", "CF-Mitigated": "challenge"})])
    with pytest.raises(RuntimeError, match="Cloudflare mitigation"):
        MODULE.fetch_loc_json(cf_sess, MODULE.LCWA_SEED)
    assert len(cf_sess.calls) == 1

    # Retry-After must abort on ANY status (including 200 and 302)
    ra_200 = _FakeSession([_fake_resp(200, headers={"Content-Type": "application/json", "Retry-After": "30"})])
    with pytest.raises(RuntimeError, match="Retry-After"):
        MODULE.fetch_loc_json(ra_200, MODULE.LCWA_SEED)
    assert len(ra_200.calls) == 1

    ra_302 = _FakeSession([_fake_resp(302, headers={"Location": MODULE.LCWA_SEED, "Retry-After": "10"})])
    with pytest.raises(RuntimeError, match="Retry-After"):
        MODULE.fetch_loc_json(ra_302, MODULE.LCWA_SEED)
    assert len(ra_302.calls) == 1

    html_sess = _FakeSession([_fake_resp(200, headers={"Content-Type": "text/html; charset=utf-8"}, content=b"<html>Just a moment</html>")])
    with pytest.raises(RuntimeError, match="Non-JSON Content-Type"):
        MODULE.fetch_loc_json(html_sess, MODULE.LCWA_SEED)
    assert len(html_sess.calls) == 1

    bad_results = _FakeSession([_fake_resp(200, content=b'{"pagination": {}}')])
    with pytest.raises(RuntimeError, match="list 'results'"):
        MODULE.fetch_loc_json(bad_results, MODULE.LCWA_SEED)

    redir_sess = _FakeSession([_fake_resp(302, headers={"Location": "https://webarchive.loc.gov/all/*/x"})])
    with pytest.raises(ValueError, match="non-www.loc.gov"):
        MODULE.fetch_loc_json(redir_sess, MODULE.LCWA_SEED)

    # Same-host valid redirect must pace hops with delay
    sleeps: list[float] = []
    monkeypatch.setattr(MODULE.time, "sleep", lambda sec: sleeps.append(sec))
    ok_redir = _FakeSession([
        _fake_resp(302, headers={"Location": "https://www.loc.gov/collections/united-states-congressional-web-archive/?fo=json&c=100&sp=1&v=2"}),
        _fake_resp(200, content=b'{"results": []}'),
    ])
    payload, _, meta = MODULE.fetch_loc_json(ok_redir, MODULE.LCWA_SEED, delay=6.5)
    assert payload == {"results": []}
    assert len(ok_redir.calls) == 2
    assert sleeps == [6.5]
    assert meta["final_url"].endswith("&v=2")


def test_normalize_scope_and_metadata_parsing():
    s1 = MODULE.normalize_scope("oversight.house.gov/ (domain)")
    assert s1["host"] == "oversight.house.gov"
    assert s1["path_prefix"] == "/"
    assert s1["scope_note"] == "domain"

    s2 = MODULE.normalize_scope("www.house.gov/reform/ (domain)")
    assert s2["host"] == "www.house.gov"
    assert s2["path_prefix"] == "/reform/"

    s3 = MODULE.normalize_scope("docs.house.gov/meetings/GO/GO00/20210512/HHRG-117.pdf (domain)")
    assert s3["host"] == "docs.house.gov"
    assert s3["path_prefix"] == "/meetings/GO/GO00/20210512/HHRG-117.pdf"

    raw_item = {
        "id": "http://www.loc.gov/item/lcwa00hsgo00/",
        "url": "https://www.loc.gov/item/lcwa00hsgo00/",
        "title": "House Committee on Oversight and Reform",
        "dates": ["[1997 TO 1997]", "[2002 TO 2020]"],
        "partof": ["112th congress", "111th congress", "united states congressional web archive"],
        "item": {
            "scopes": ["oversight.house.gov/ (domain)", "www.house.gov/reform/ (domain)"],
            "source_url": ["https://oversight.house.gov/"],
            "subject_headings": ["United States. Congress (116th : 2019-2020)"],
        },
        "resources": [{"url": "https://webarchive.loc.gov/all/*/https://oversight.house.gov/"}],
    }
    norm = MODULE.normalize_catalog_item(raw_item)
    assert norm["item_id"] == "lcwa00hsgo00"
    assert norm["year_ranges"] == [{"start": 1997, "end": 1997}, {"start": 2002, "end": 2020}]
    assert norm["congresses"] == [111, 112, 116]


def test_path_prefix_www_and_year_lookup_precision():
    records = [
        MODULE.normalize_catalog_item(
            {
                "url": "https://www.loc.gov/item/lcwa00hsgo00/",
                "title": "Oversight",
                "dates": ["[2002 TO 2020]"],
                "partof": ["112th congress"],
                "item": {
                    "scopes": ["www.house.gov/reform/ (domain)", "oversight.house.gov/ (domain)"],
                    "source_url": [],
                },
                "resources": [],
            }
        )
    ]
    coverage = MODULE.build_domain_coverage(records, generated_at="2026-11-18T00:00:00Z")

    ok = MODULE.lookup_url(coverage, "https://house.gov/reform/uploads/file.pdf", year=2011)
    assert ok["matched"] is True
    assert ok["matches"][0]["match_basis"] == "www_variant+path_prefix"

    wrong_committee = MODULE.lookup_url(coverage, "https://www.house.gov/judiciary/file.pdf", year=2011)
    assert wrong_committee["matched"] is False

    out_of_range = MODULE.lookup_url(coverage, "https://oversight.house.gov/test.pdf", year=2025)
    assert out_of_range["matched"] is False


def test_build_catalog_sidecar_verification_completeness_and_cross_match(tmp_path: Path):
    out_dir = tmp_path / "catalog"
    pages_dir = out_dir / "pages"
    pages_dir.mkdir(parents=True)

    item_a = {
        "url": "https://www.loc.gov/item/lcwa00hsgo00/",
        "title": "Oversight",
        "dates": ["[2002 TO 2020]"],
        "partof": ["112th congress"],
        "item": {"scopes": ["oversight.house.gov/ (domain)"], "source_url": ["https://oversight.house.gov/"]},
        "resources": [{"url": "https://webarchive.loc.gov/all/*/https://oversight.house.gov/"}],
    }
    item_b = {
        "url": "https://www.loc.gov/item/lcwa00senfrc00/",
        "title": "Foreign Relations",
        "dates": ["[2005 TO 2024]"],
        "partof": ["118th congress"],
        "item": {"scopes": ["www.foreign.senate.gov/ (domain)"], "source_url": []},
        "resources": [],
    }
    p2_url = "https://www.loc.gov/collections/united-states-congressional-web-archive/?fo=json&sp=2"
    p1 = {
        "results": [item_a],
        "pagination": {"of": 2, "total": 2, "next": p2_url},
    }
    p2 = {
        "results": [item_a, item_b],
        "pagination": {"of": 2, "total": 2, "next": None},
    }
    p1_bytes = json.dumps(p1).encode("utf-8")
    p2_bytes = json.dumps(p2).encode("utf-8")
    (pages_dir / "page-0001.json").write_bytes(p1_bytes)
    (pages_dir / "page-0002.json").write_bytes(p2_bytes)
    p1_meta = json.dumps({"requested_url": MODULE.LCWA_SEED, "sha256": MODULE.sha256_bytes(p1_bytes)})
    p2_meta = json.dumps({"requested_url": p2_url, "sha256": MODULE.sha256_bytes(p2_bytes)})
    (pages_dir / "page-0001.meta.json").write_text(p1_meta, encoding="utf-8")
    (pages_dir / "page-0002.meta.json").write_text(p2_meta, encoding="utf-8")

    with pytest.raises(ValueError, match="Refusing delay"):
        MODULE.build_catalog(out_dir, offline=False, delay=2.0)

    # Capped run marks complete=False with max_pages_reached
    partial_manifest = MODULE.build_catalog(out_dir, offline=True, max_pages=1)
    assert partial_manifest["complete"] is False
    assert partial_manifest["incomplete_reason"] == "max_pages_reached"

    # Missing sidecar on any cached page is refused before admitting the page
    (pages_dir / "page-0002.meta.json").unlink()
    with pytest.raises(ValueError, match="Missing required sidecar"):
        MODULE.build_catalog(out_dir, offline=True)
    (pages_dir / "page-0002.meta.json").write_text(p2_meta, encoding="utf-8")

    # Full run with verified sidecars marks complete=True
    manifest = MODULE.build_catalog(out_dir, offline=True)
    assert manifest["complete"] is True
    assert manifest["all_pages_sidecar_verified"] is True
    assert manifest["incomplete_reason"] is None
    assert manifest["unique_records"] == 2
    assert manifest["pages_collected"] == 2

    # Corrupted sidecar digest or URL mismatch fails fast
    (pages_dir / "page-0001.meta.json").write_text(
        json.dumps({"requested_url": MODULE.LCWA_SEED, "sha256": "0" * 64}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="digest mismatch"):
        MODULE.build_catalog(out_dir, offline=True)
    (pages_dir / "page-0001.meta.json").write_text(
        json.dumps({"requested_url": "https://www.loc.gov/other/?fo=json", "sha256": MODULE.sha256_bytes(p1_bytes)}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="URL mismatch"):
        MODULE.build_catalog(out_dir, offline=True)
    (pages_dir / "page-0001.meta.json").write_text(p1_meta, encoding="utf-8")

    coverage = json.loads((out_dir / "domain-coverage.json").read_text(encoding="utf-8"))

    # Missing required inputs or explicitly supplied optional files fail fast
    with pytest.raises(FileNotFoundError, match="damaged_manifest"):
        MODULE.cross_match_inventory(
            coverage,
            damaged_manifest=tmp_path / "missing.tsv",
            invalid_sources=tmp_path / "missing.jsonl",
            output=tmp_path / "fail_out",
        )

    tsv = tmp_path / "g_manifest.tsv"
    tsv.write_text(
        "case\tgroup\tsha256\tbytes\tsha1_b32\tpublisher_last_modified\tdeclared_bytes\trefetch_identical\turls\n"
        "zero-page-reuter\trefetched47\t05fc\t116736\tAAA\tTue\t297535\tTrue\thttps://oversight.house.gov/wp-content/uploads/2012/01/20090519Reuter.pdf\n"
        "zero-page-boushey\trefetched47\t65b6\t100\tAAA\tTue\t200\tTrue\thttps://oversight.house.gov/wp-content/uploads/2012/01/9-13-2011_BousheyTestimony.pdf\n"
        "zero-page-howle\trefetched47\t25b3\t337920\tAAA\tTue\t507030\tTrue\thttps://oversight.house.gov/wp-content/uploads/2012/01/20100305Howle1.pdf\n"
        "zero-page-locqueued\trefetched47\t08ca\t100\tBBB\tTue\t200\tTrue\thttps://oversight.house.gov/wp-content/uploads/2012/01/12-7-11_Testimony.pdf\n"
        "zero-page-missing\trefetched47\ta38b\t100\tCCC\tFri\t200\tTrue\thttps://www.congress.gov/116/meeting/house/110128/documents/HHRG-116-VR03.pdf\n",
        encoding="utf-8",
    )
    inv_dummy = tmp_path / "dummy.jsonl"
    inv_dummy.write_text("", encoding="utf-8")
    for kw in (
        {"non_loc_results": tmp_path / "absent_non_loc.json"},
        {"hearing_prints": tmp_path / "absent_prints.json"},
        {"remaining_loc_targets": tmp_path / "absent_loc.json"},
    ):
        with pytest.raises(FileNotFoundError):
            MODULE.cross_match_inventory(
                coverage,
                damaged_manifest=tsv,
                invalid_sources=inv_dummy,
                output=tmp_path / "fail_opt",
                **kw,
            )

    # pagination.next=None when pages_collected < reported_total_pages marks complete=False
    inc_dir = tmp_path / "inc_catalog"
    (inc_dir / "pages").mkdir(parents=True)
    inc_bytes = json.dumps({"results": [item_a], "pagination": {"of": 200, "total": 3, "next": None}}).encode("utf-8")
    (inc_dir / "pages/page-0001.json").write_bytes(inc_bytes)
    (inc_dir / "pages/page-0001.meta.json").write_text(
        json.dumps({"requested_url": MODULE.LCWA_SEED, "sha256": MODULE.sha256_bytes(inc_bytes)}),
        encoding="utf-8",
    )
    inc_manifest = MODULE.build_catalog(inc_dir, offline=True)
    assert inc_manifest["complete"] is False
    assert inc_manifest["incomplete_reason"] == "fewer_pages_than_reported_total"
    # Non-LoC results: 2nd Howle candidate has exact prefix + exact declared length vs 1st's 8B prefix
    non_loc = tmp_path / "results.json"
    non_loc.write_text(json.dumps([
        {
            "case": "zero-page-howle",
            "damaged_bytes": 337920,
            "declared_bytes": 507030,
            "lead_kind": "webharvest_renamed",
            "candidate_url": "https://webharvest.gov/alt/TESTIMONY-Howle.pdf",
            "operation_id": "op_weak",
            "fetched_bytes": 526788,
            "receipt_outcome": "stored",
            "qualification_status": "qualified",
            "identity_status": "candidate_qualified_pending_source_acceptance",
            "shared_prefix": {"shared_prefix_bytes": 8},
            "pages": 25,
            "receipt_key": "r1",
        },
        {
            "case": "zero-page-howle",
            "damaged_bytes": 337920,
            "declared_bytes": 507030,
            "lead_kind": "webharvest_renamed",
            "candidate_url": "https://webharvest.gov/exact/20100305Howle.pdf",
            "operation_id": "op_exact",
            "fetched_bytes": 507030,
            "receipt_outcome": "stored",
            "qualification_status": "qualified",
            "identity_status": "candidate_qualified_pending_source_acceptance",
            "shared_prefix": {"shared_prefix_bytes": 337920},
            "pages": 25,
            "receipt_key": "r2",
        },
    ]), encoding="utf-8")
    remaining_loc = tmp_path / "remaining_loc.json"
    remaining_loc.write_text(json.dumps([{"case_id": "zero-page-locqueued"}]), encoding="utf-8")

    # Open inventory testing known-year overlap, upload-path-only overlap, unknown-year, year-mismatch, and matched-only host crediting
    inv = tmp_path / "invalid-sources.jsonl"
    inv.write_text(
        "\n".join([
            # Known year overlap + extra unmatched alias host (must NOT credit unmatched.example.gov!)
            json.dumps({
                "record_id": "body:known_overlap",
                "recovery_open": True,
                "failure_category": "incomplete_pdf",
                "source_urls": [
                    "https://oversight.house.gov/wp-content/uploads/2012/01/12-7-11_Testimony.pdf",
                    "https://unmatched.example.gov/alias.pdf",
                ],
                "release_associations_20261117": [{"document_date": "2011-12-07"}],
            }),
            # CMS upload-path-only year (must NOT be inflated into known_year_overlap!)
            json.dumps({
                "record_id": "body:upload_only",
                "recovery_open": True,
                "failure_category": "incomplete_pdf",
                "source_urls": ["https://oversight.house.gov/wp-content/uploads/2012/01/Schimmel_Testimony_Boral_Bricks.pdf"],
                "release_associations_20261117": [],
            }),
            # Unknown year on matched host
            json.dumps({
                "record_id": "body:unknown_year",
                "recovery_open": True,
                "failure_category": "incomplete_pdf",
                "source_urls": ["https://www.foreign.senate.gov/download/s-3492-as-reported04"],
                "release_associations_20261117": [],
            }),
            # Known year outside LCWA range (2025 > 2020)
            json.dumps({
                "record_id": "body:year_mismatch",
                "recovery_open": True,
                "failure_category": "error_response",
                "source_urls": ["https://oversight.house.gov/wp-content/uploads/2025/01/new.pdf"],
                "release_associations_20261117": [{"document_date": "2025-01-10"}],
            }),
            # Missing source URLs
            json.dumps({"record_id": "body:no_url", "recovery_open": True, "failure_category": "error_response", "source_urls": []}),
            # Closed record ignored
            json.dumps({"record_id": "body:closed", "recovery_open": False, "failure_category": "incomplete_pdf", "source_urls": ["https://www.foreign.senate.gov/a.pdf"]}),
        ]) + "\n",
        encoding="utf-8",
    )

    overlap_dir = tmp_path / "overlap"
    res = MODULE.cross_match_inventory(
        coverage,
        damaged_manifest=tsv,
        invalid_sources=inv,
        output=overlap_dir,
        non_loc_results=non_loc,
        remaining_loc_targets=remaining_loc,
    )

    # Best Howle candidate selected (337920B exact prefix, not 8B); Reuter (YYYYMMDD) & Boushey (M-D-YYYY) extract filename years over 2012 upload dir
    reuter_row = next(r for r in res["damaged_49_rows"] if r["case"] == "zero-page-reuter")
    assert reuter_row["year_hint"] == 2009
    assert reuter_row["year_hint_source"] == "url_filename_date"
    boushey_row = next(r for r in res["damaged_49_rows"] if r["case"] == "zero-page-boushey")
    assert boushey_row["year_hint"] == 2011
    assert boushey_row["year_hint_source"] == "url_filename_date"
    # Directory date must NOT override filename date in final path component
    assert MODULE._extract_year_with_source(
        "https://oversight.house.gov/9-13-2012-hearing/11-2-11_Testimony.pdf"
    ) == (2011, "url_filename_date")
    howle_row = next(r for r in res["damaged_49_rows"] if r["case"] == "zero-page-howle")
    assert howle_row["selected_non_loc"]["operation_id"] == "op_exact"
    assert howle_row["selected_non_loc"]["shared_prefix_bytes"] == 337920

    # queued_for_loc_browser_capture stays visible in unresolved_or_non_qualified_highlight
    unresolved_cases = {r["case"] for r in res["unresolved_or_non_qualified_highlight"]}
    assert "zero-page-locqueued" in unresolved_cases
    assert "zero-page-missing" in unresolved_cases
    assert "zero-page-howle" not in unresolved_cases

    # Exact year breakdown (1 known overlap, 1 upload-path-only overlap, 1 unknown year, 1 year mismatch)
    counts = res["invalid_sources_open_summary"]["counts"]
    assert counts["open_total"] == 5
    assert counts["open_missing_source_url"] == 1
    assert counts["open_matched_lcwa_host_any_year"] == 4
    assert counts["open_matched_lcwa_known_year_overlap"] == 1
    assert counts["open_matched_lcwa_upload_path_year_overlap"] == 1
    assert counts["open_matched_lcwa_unknown_year"] == 1
    assert counts["open_matched_lcwa_year_mismatch"] == 1

    # Host crediting excludes unmatched alias host
    matched_hosts = res["invalid_sources_open_summary"]["matched_lcwa_hosts"]
    assert matched_hosts == {"oversight.house.gov": 3, "www.foreign.senate.gov": 1}
    assert "unmatched.example.gov" not in matched_hosts
    assert (overlap_dir / "SUMMARY.md").exists()
