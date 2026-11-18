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
    content: bytes = b"{}",
    json_data: object = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        status_code=status_code,
        headers=headers or {"Content-Type": "application/json"},
        content=content,
        json=lambda: json_data if json_data is not None else json.loads(content.decode("utf-8")),
    )


def test_fetch_loc_json_rejects_screened_urls_and_challenges():
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

    html_sess = _FakeSession([_fake_resp(200, headers={"Content-Type": "text/html; charset=utf-8"}, content=b"<html>Just a moment</html>")])
    with pytest.raises(RuntimeError, match="Non-JSON Content-Type"):
        MODULE.fetch_loc_json(html_sess, MODULE.LCWA_SEED)
    assert len(html_sess.calls) == 1

    redir_sess = _FakeSession([_fake_resp(302, headers={"Location": "https://webarchive.loc.gov/all/*/x"})])
    with pytest.raises(ValueError, match="non-www.loc.gov"):
        MODULE.fetch_loc_json(redir_sess, MODULE.LCWA_SEED)


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


def test_build_catalog_offline_and_cross_match(tmp_path: Path):
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
    p1 = {
        "results": [item_a],
        "content": {"results": [item_a]},
        "pagination": {"of": 2, "total": 2, "next": "https://www.loc.gov/collections/united-states-congressional-web-archive/?fo=json&sp=2"},
    }
    p2 = {
        "results": [item_a, item_b],
        "pagination": {"of": 2, "total": 2, "next": None},
    }
    (pages_dir / "page-0001.json").write_text(json.dumps(p1), encoding="utf-8")
    (pages_dir / "page-0002.json").write_text(json.dumps(p2), encoding="utf-8")

    with pytest.raises(ValueError, match="Refusing delay"):
        MODULE.build_catalog(out_dir, offline=False, delay=2.0)

    manifest = MODULE.build_catalog(out_dir, offline=True)
    assert manifest["unique_records"] == 2
    assert manifest["pages_collected"] == 2

    coverage = json.loads((out_dir / "domain-coverage.json").read_text(encoding="utf-8"))
    tsv = tmp_path / "g_manifest.tsv"
    tsv.write_text(
        "case\tgroup\tsha256\tbytes\tsha1_b32\tpublisher_last_modified\tdeclared_bytes\trefetch_identical\turls\n"
        "zero-page-08ca05e57e8d\trefetched47\t08ca\t100\tAAA\tTue\t200\tTrue\thttps://oversight.house.gov/wp-content/uploads/2012/01/12-7-11_Testimony.pdf\n"
        "zero-page-missing\trefetched47\ta38b\t100\tBBB\tFri\t200\tTrue\thttps://www.congress.gov/116/meeting/house/110128/documents/HHRG-116-VR03.pdf\n",
        encoding="utf-8",
    )
    inv = tmp_path / "invalid-sources.jsonl"
    inv.write_text(
        json.dumps({"record_id": "body:1", "recovery_open": True, "failure_category": "incomplete_pdf", "source_urls": ["https://oversight.house.gov/wp-content/uploads/2012/01/12-7-11_Testimony.pdf"], "release_associations_20261117": [{"document_date": "2011-12-07"}]})
        + "\n"
        + json.dumps({"record_id": "body:2", "recovery_open": True, "failure_category": "error_response", "source_urls": []})
        + "\n"
        + json.dumps({"record_id": "body:3", "recovery_open": False, "failure_category": "incomplete_pdf", "source_urls": ["https://www.foreign.senate.gov/a.pdf"]})
        + "\n",
        encoding="utf-8",
    )
    overlap_dir = tmp_path / "overlap"
    res = MODULE.cross_match_inventory(
        coverage,
        damaged_manifest=tsv,
        invalid_sources=inv,
        output=overlap_dir,
    )
    assert res["damaged_49_summary"]["lcwa_domain_matched_count"] == 1
    counts = res["invalid_sources_open_summary"]["counts"]
    assert counts["open_total"] == 2
    assert counts["open_matched_lcwa_with_year"] == 1
    assert counts["open_missing_source_url"] == 1
    assert (overlap_dir / "SUMMARY.md").exists()
