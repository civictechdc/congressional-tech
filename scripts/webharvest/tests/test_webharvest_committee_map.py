"""Check archive URL preservation and source-backed committee lookup."""
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("webharvest_map", ROOT / "scripts/webharvest/webharvest_committee_map.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize(("embedded", "expected", "style"), [
    ("https://science.house.gov/", "https://science.house.gov/", "explicit_scheme"),
    ("http:/science.house.gov/", "http://science.house.gov/", "single_slash_scheme"),
    ("science.house.gov/", "http://science.house.gov/", "omitted_scheme_assumed_http"),
])
def test_legacy_replay_forms(embedded, expected, style):
    prefix = "https://www.webharvest.gov/congress109th/20061114000000/"
    row = MODULE.split_replay(prefix + embedded)
    assert row["original_url"] == expected
    assert row["embedded_url_literal"] == embedded
    assert row["embedded_url_style"] == style
    assert row["redirect_prefix"] == prefix


@pytest.fixture
def mapping():
    return json.loads((ROOT / "docs/data/webharvest-committees/map.json").read_text())


def test_exact_lookup_preserves_case_escaping_query_and_drops_fragment(mapping):
    target = "https://energycommerce.house.gov/A%20B/Doc.PDF?download=1&value=%2F#page=2"
    results = MODULE.lookup(mapping, target, congress=118)
    assert len(results) == 1
    assert results[0]["candidate_url"] == (
        "https://www.webharvest.gov/congress118th/20241107041104/" + target.split("#")[0]
    )
    assert results[0]["match_basis"] == "exact_domain"
    assert results[0]["availability"] == "unverified"


def test_www_is_explicit_and_never_guesses_a_renamed_committee(mapping):
    target = "https://www.agriculture.house.gov/file.pdf"
    assert MODULE.lookup(mapping, target, congress=118) == []
    result, = MODULE.lookup(mapping, target, congress=118, include_www=True)
    assert result["match_basis"] == "www_variant"
    assert result["target_url"] == "https://agriculture.house.gov/file.pdf"
    assert MODULE.lookup(mapping, "https://oversightdemocrats.house.gov/file.pdf", include_www=True) == []


def test_scheme_variant_is_labelled_and_original_retained(mapping):
    result = MODULE.lookup(mapping, "http://agriculture.house.gov/file.pdf", congress=118)
    assert {r["match_basis"] for r in result} == {"exact_domain", "exact_domain+listed_scheme_variant"}
    assert {r["target_url"] for r in result} == {
        "http://agriculture.house.gov/file.pdf", "https://agriculture.house.gov/file.pdf"
    }


def test_shared_domain_deduplicates_candidates_but_keeps_source_records(mapping):
    result, = MODULE.lookup(mapping, "https://cha.house.gov/file.pdf", congress=118)
    assert len(result["map_record_ids"]) == 3  # Administration, Library, Printing.


def test_every_retained_source_reproduces_map_and_digest(mapping):
    directory = ROOT / "docs/data/webharvest-committees"
    manifest = json.loads((directory / "manifest.json").read_text())
    observed = []
    for source in manifest["sources"]:
        raw = (directory / source["file"]).read_bytes()
        assert MODULE.sha256(raw) == source["sha256"]
        rows, discovered = MODULE.parse_page(raw, source["url"])
        assert len(rows) == source["entries"]
        assert len(discovered) == 20
        observed.extend(rows)
    expected = [{k: v for k, v in row.items() if k != "id"} for row in mapping["records"]]
    sort_key = lambda row: (row["congress"], row["chamber"], row["domain"], row["committee"])
    assert sorted(observed, key=sort_key) == expected
    assert manifest["congresses"] == list(range(109, 119))
    assert manifest["pages"] == 20


def test_backlog_join_uses_explicit_exclusions_and_reports_unmatched(mapping, tmp_path):
    targets = tmp_path / "targets.csv"
    targets.write_text("url\nhttps://agriculture.house.gov/file.pdf\nhttps://agriculture.house.gov/recovered.pdf\nhttps://unknown.example/file.pdf\nhttps://agriculture.house.gov/download?id=1\n")
    excluded = tmp_path / "recovered.json"
    excluded.write_text(json.dumps({"https://agriculture.house.gov/recovered.pdf": {"valid": True}}))
    summary = MODULE.join_targets(mapping, targets, tmp_path / "out", [excluded])
    assert summary["counts"]["excluded_recovered_urls"] == 1
    assert summary["counts"]["remaining_pdf_suffix_urls"] == 2
    assert summary["counts"]["pdf_urls_with_candidates"] == 1
    assert summary["counts"]["pdf_urls_without_domain_match"] == 1
    assert summary["counts"]["non_pdf_suffix_urls"] == 1


def test_rate_limit_page_cannot_become_an_empty_successful_map():
    with pytest.raises(ValueError, match="content"):
        MODULE.parse_page(b"<html><body>Rate limit reached</body></html>", MODULE.SEED)


def test_cross_congress_link_is_rejected():
    raw = b'<div class="content"><h2>Standing</h2><div><h3>Science</h3><a href="https://webharvest.gov/congress117th/3/https://science.house.gov/">Science</a></div></div>'
    with pytest.raises(ValueError, match="Cross-Congress"):
        MODULE.parse_page(raw, MODULE.SEED)


@pytest.mark.parametrize(("status", "body", "outcome"), [
    (200, b"<title>Rate limit reached</title>", "rate_limited"),
    (429, b"", "rate_limited"),
    (200, b"<title>Session Verification</title>", "access_blocked"),
    (200, b"<title>Normal page</title>", "unresolved_response"),
])
def test_proxy_200_does_not_turn_block_pages_into_captures(status, body, outcome):
    result = MODULE.classify_redirect("https://webharvest.gov/congress118th/3/https://agriculture.house.gov/", status, {}, body)
    assert result["outcome"] == outcome
    assert "resolved_prefix" not in result


def test_archive_redirect_keeps_observed_timestamp_and_rejects_external_target():
    url = "https://webharvest.gov/congress118th/3/https://agriculture.house.gov/"
    location = "https://webharvest.gov/congress118th/20241231225425/https://agriculture.house.gov/"
    result = MODULE.classify_redirect(url, 302, {"location": location})
    assert result["outcome"] == "capture_redirect_observed"
    assert result["resolved_prefix"] == "https://webharvest.gov/congress118th/20241231225425/"
    assert MODULE.classify_redirect(url, 302, {"location": "https://example.org/"})["outcome"] == "redirect_outside_collection"
