"""Rule, parser and schema tests for `congress_docmeta` (DocMeta V6). Nothing here needs the model."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from congress_docmeta import (
    DOCMETA_V4_SCHEMA_PATH,
    SCHEMA_V4_STR,
    can_fill_from_relational_v6,
    classify_hsru_host_status,
    clean_html_and_cms_v6,
    detect_cover_lock_v6,
    detect_cover_or_sha_lock_v6,
    detect_exact_tier1_signature_v5,
    detect_nominee_opening_override_v6,
    enrich_personas_from_relational_v6,
    extract_citations_and_signals_v6,
    extract_clean_html_v6,
    extract_fiscal_years_v6,
    extract_short_titles_v6,
    load_refspec_oracles_v6,
    load_rosters_lookup_v6,
    post_pass_v6,
    pre_pass_v6,
    repair_bgsdd_mojibake_v6,
    route_batch_anomalies_v6,
    score_docmeta_anomalies_v6,
    strict_validate_v4,
    triage_non_usable_v6,
    try_zero_llm_bypass_v6,
)

REPO_ROOT = Path(__file__).resolve().parents[1]  # this package
SRC_DIR = REPO_ROOT / "src"


def test_pure_stdlib_import_isolation_and_zero_scratch_paths() -> None:
    """Verify `/usr/bin/python3 -B -I -S` imports `congress_docmeta` with zero non-stdlib packages."""
    code = (
        "import importlib, os, pathlib, sys\n"
        "os.environ['DOCMETA_V6_DATA_DIR'] = '/nonexistent/docmeta_v6_data'\n"
        "os.environ['REFSPEC_ROOT'] = '/nonexistent/refspec_root'\n"
        f"sys.path.insert(0, {str(SRC_DIR)!r})\n"
        "import congress_docmeta as dm\n"
        f"pkg_dir = pathlib.Path({str(SRC_DIR / 'congress_docmeta')!r})\n"
        "for p in sorted(pkg_dir.glob('*.py')):\n"
        "    mod_name = 'congress_docmeta' if p.stem == '__init__' else f'congress_docmeta.{p.stem}'\n"
        "    mod = importlib.import_module(mod_name)\n"
        "    for exp in getattr(mod, '__all__', ()):\n"
        "        assert hasattr(mod, exp), f'{mod_name} missing {exp}'\n"
        "for banned in ('mlx', 'numpy', 'pyarrow', 'tokenizers', 'llguidance'):\n"
        "    assert banned not in sys.modules, f'Unexpected third-party import: {banned}'\n"
        "enr, pmeta = dm.pre_pass_v6(None, 'HHRG-118-JU00-Wstate-DoeJ-20230510.pdf', 'Testimony of Jane Doe, May 10, 2023.')\n"
        "assert '118' in enr and pmeta['triage'] is None\n"
    )
    proc = subprocess.run(
        ["/usr/bin/python3", "-B", "-I", "-S", "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert DOCMETA_V4_SCHEMA_PATH.is_file()

    # Static hygiene scan across src/, docs/, tests/
    marker = "".join((".", "gem", "ini"))
    for folder in ("src", "tests"):
        root = REPO_ROOT / folder
        if not root.exists():
            continue
        for file_p in root.rglob("*"):
            if file_p.is_file() and file_p.suffix in (".py", ".md", ".json", ".toml", ".txt"):
                content = file_p.read_text(encoding="utf-8")
                assert marker not in content, f"Forbidden scratch path marker in {file_p}"


def test_tier1_and_cover_lock_signatures() -> None:
    """Verify V5 Tier-1 signatures and V6 cover-lock signatures lock exact `primary_kind` targets."""
    ttf_text = (
        "Truth in Testimony Disclosure Form\n"
        "In accordance with Rule XI, clause 2(g)(5) of the Rules of the House of Representatives\n"
        "Witness Name: Dr. Elena Vance\n"
        "Position/Title: Senior Fellow\n"
        "Witness Representing: Brookings Institution\n"
    )
    sig_id, kind = detect_exact_tier1_signature_v5("HHRG-118-IF16-TTF-VanceE-20230614.pdf", ttf_text)
    assert sig_id is not None
    assert kind == "truth_in_testimony_disclosure"

    # CBO "At a Glance" cost estimate cover lock
    cbo_text = (
        "CONGRESSIONAL BUDGET OFFICE\n"
        "COST ESTIMATE\n"
        "May 14, 2024\n"
        "H.R. 4521, Strengthening Supply Chains Act\n"
        "As ordered reported by the House Committee on Energy and Commerce on April 17, 2024\n"
        "At a Glance\n"
    )
    lock_id, lock_kind, lock_src = detect_cover_or_sha_lock_v6("hr4521.pdf", cbo_text, p12_lines=cbo_text)
    assert lock_kind == "revenue_or_cost_estimate"
    assert lock_id is not None and lock_src is not None

    # GAO report cover lock (>= 500 chars as required by production cover guard)
    gao_text = (
        "United States Government Accountability Office\n"
        "GAO\n"
        "Report to Congressional Requesters\n"
        "March 2024\n"
        "CYBERSECURITY: Federal Agencies Need to Improve Incident Response and Supply Chain Risk Management\n"
        "GAO-24-106123\n"
        "Why GAO Did This Study: Critical infrastructure sectors increasingly rely on interconnected cloud "
        "services and operational technology, requiring coordinated incident reporting across civilian agencies "
        "and timely implementation of statutory cybersecurity directives.\n"
        "What GAO Found: Twenty-three civilian agencies established baseline logging policies, but gaps remain "
        "in automated threat-hunting playbooks and cross-agency vulnerability disclosure workflows.\n"
    )
    _, gao_kind, _ = detect_cover_or_sha_lock_v6("gao-24-106123.pdf", gao_text, p12_lines=gao_text)
    assert gao_kind == "agency_or_gao_crs_report"


def test_cms_time_travel_and_html_script_stripping() -> None:
    """Verify HTML `<script>`/`<style>` removal and CMS navigation time-travel Congress protection."""
    raw_html = (
        "<!DOCTYPE html><html><head>"
        "<script>window.NREUM={}; jQuery.extend(Drupal.settings, {'basePath':'/', 'token':'119th'});</script>"
        "<style>.nav-banner { display:none; }</style></head><body>"
        "<header>Skip to content 119th Congress Majority Internships News Listening To Americans "
        "Activity Hearings Markups Calendar </header>"
        "<main><h1>Hearing on Tax Administration Oversight</h1>"
        "<p>U.S. House of Representatives, Committee on Ways and Means, 114th Congress, June 10, 2015, "
        "1100 Longworth House Office Building, Washington, D.C. Witness panel and opening statements "
        "examining Internal Revenue Service taxpayer services and filing season operations.</p></main></body></html>"
    )
    cleaned_html, stripped_chars = extract_clean_html_v6(raw_html.encode("utf-8"))
    assert stripped_chars > 0
    assert "Drupal.settings" not in cleaned_html
    assert "window.NREUM" not in cleaned_html
    assert "Hearing on Tax Administration Oversight" in cleaned_html

    cms_clean, cms_family, script_stripped = clean_html_and_cms_v6(raw_html, is_html=True)
    assert script_stripped is True
    assert cms_family == "house_ways_and_means_cms"
    assert "119th Congress" not in cms_clean
    assert "114th Congress" in cms_clean

    _, pmeta = pre_pass_v6(
        None,
        "tax-administration-hearing",
        raw_html,
        explicit_format="html",
    )
    assert pmeta["is_html"] is True
    assert pmeta["cms_nav_stripped"] is True

    # Post-pass reconciles hallucinated time-travel Congress 119 -> 114 using nav-stripped text
    fixed_obj, _ = post_pass_v6(
        {
            "status": "usable",
            "text_quality": "native",
            "chamber": "house",
            "congress": 119,
            "committees": ["Committee on Ways and Means"],
            "event_date": "2015-06-10",
            "primary_kind": "event_web_page",
            "composed_title": "Hearing on Tax Administration Oversight",
            "gist": "Ways and Means hearing on IRS filing season operations.",
            "topics": ["tax administration"],
        },
        filename="tax-administration-hearing.html",
        text=raw_html,
    )
    assert fixed_obj["congress"] == 114


def test_bgsddv01_mojibake_repair_and_false_positive_guards() -> None:
    """Verify `BGsddV01` GPO glyph repairs fire accurately without corrupting Yen, Nordic names, or math."""
    mojibake_src = (
        "CHRG-112shrg74112\n"
        "U.S. GOVERNMENT PRINTING OFFICE\n"
        "Flag STAT¥UNUSED in hearings¥markups¥details.aspx and øexisting law omitted¿ "
        "plus ƒnew language≈ under Medicare∂Choice. Æ\n"
    )
    repaired, rules = repair_bgsdd_mojibake_v6(mojibake_src, filename="CHRG-112shrg74112.pdf", is_gpo=True)
    assert "STAT_UNUSED" in repaired
    assert "hearings_markups_details.aspx" in repaired
    assert "[existing law omitted]" in repaired
    assert "[new language]" in repaired
    assert "Medicare+Choice" in repaired
    assert repaired.rstrip().endswith("○")
    assert len(rules) >= 5

    # Must NEVER corrupt real currency, Scandinavian names, or standalone math approximations
    safe_prose = (
        "Witnesses Dr. Lars Jørgensen, Amb. Bjørn Sørensen, and Prof. Erik Møse noted shares "
        "closed at ¥208.50 (US$29.90) with wafer thickness ≈ 30 centimeters."
    )
    untouched, rules_safe = repair_bgsdd_mojibake_v6(safe_prose, filename="witness.pdf", is_gpo=False)
    assert untouched == safe_prose
    assert rules_safe == []


def test_pdf_safe_error_pages_guard_and_waf_html_triage() -> None:
    """Verify `error_pages` WAF detector NEVER flags PDFs titled 'Access Denied', while catching HTML WAFs."""
    pdf_hearing = (
        "Access Denied: Examining Barriers to Broadband Deployment on Federal Lands\n"
        "Hearing before the Subcommittee on Communications and Technology of the "
        "Committee on Energy and Commerce, House of Representatives, One Hundred Eighteenth Congress."
    )
    assert triage_non_usable_v6(pdf_hearing, filename="HHRG-118-IF16-20240410.pdf", explicit_format="pdf") is None

    pdf_cloudflare_hearing = (
        "Attention Required! | Cloudflare Outages, BGP Hijacking, and Federal Network Resilience\n"
        "Testimony of Dr. Alan Rivera before the Senate Committee on Homeland Security and Governmental Affairs, "
        "One Hundred Eighteenth Congress, Second Session, examining enterprise DDoS mitigation and DNS security "
        "across federal civilian agencies."
    )
    assert (
        triage_non_usable_v6(
            pdf_cloudflare_hearing,
            filename="rivera_testimony.pdf",
            raw_html_or_bytes=b"%PDF-1.7 fake header",
        )
        is None
    )

    waf_html = (
        "<!DOCTYPE html><html><head><title>Attention Required! | Cloudflare</title></head>"
        "<body>Sorry, you have been blocked. Cloudflare Ray ID: 8a1b2c3d4e5f</body></html>"
    )
    triaged = triage_non_usable_v6(waf_html, filename="page.html", explicit_format="html")
    assert triaged is not None
    assert triaged["docmeta"]["status"] == "error_or_block"
    ok, err = strict_validate_v4(triaged["docmeta"])
    assert ok, err


def test_host_vs_author_guards_hsru00_sd00x_and_sfrc_nominees() -> None:
    """Verify `hsru00` floor-host stripping, `-SD00x` & whitepaper relational guards, and SFRC nominee guard."""
    # 1. `hsru00` Rules Committee Print floor-host stripping
    rcp_text = (
        "118TH CONGRESS 2D SESSION\n"
        "RULES COMMITTEE PRINT 118-36\n"
        "TEXT OF H.R. 8035, UKRAINE SECURITY SUPPLEMENTAL APPROPRIATIONS ACT, 2024\n"
        "[Showing the text of H.R. 8035 as reported by the Committee on Appropriations.]"
    )
    hsru_status, orig_cmts = classify_hsru_host_status({"cmt": ["hsru00"]}, "BILLS-118hr8035rcp.pdf", rcp_text)
    assert hsru_status == "rules_host"
    assert any("Appropriations" in c.get("name", "") for c in orig_cmts)
    _, pmeta = pre_pass_v6({"cmt": ["hsru00"]}, "BILLS-118hr8035rcp.pdf", rcp_text)
    assert pmeta["hsru_host_stripped"] is True
    rcp_obj, _ = post_pass_v6(
        {
            "status": "usable",
            "text_quality": "native",
            "chamber": "house",
            "congress": 118,
            "committees": ["Committee on Rules"],
            "primary_kind": "bill_or_draft",
            "composed_title": "Rules Committee Print 118-36 — H.R. 8035",
            "gist": "Text of H.R. 8035 supplemental appropriations bill.",
            "topics": ["appropriations"],
        },
        known={"cmt": ["hsru00"]},
        filename="BILLS-118hr8035rcp.pdf",
        text=rcp_text,
    )
    assert "Committee on Rules" not in rcp_obj.get("committees", [])

    # 2. `-SD00x` supplemental exhibits must NEVER stamp relational `witness_keys` as document `author`
    rel_sd_row = {
        "witness_keys": ["wit_001"],
        "rel_witness_name": "John Q. Witness",
        "rel_witnesses": [{"name": "John Q. Witness", "role": "witness", "entity_type": "non_gov_person"}],
        "rel_host_chamber": "house",
        "rel_host_committees": ["Committee on Oversight and Accountability"],
    }
    personas_sd = enrich_personas_from_relational_v6(
        [],
        rel_sd_row,
        "external_report_or_whitepaper",
        filename="HHRG-118-GO00-20240320-SD003.pdf",
        text="Independent Economic Outlook Report by Acme Research Institute, January 2024.",
    )
    assert all(p.get("name") != "John Q. Witness" for p in personas_sd)

    # Host chamber/committee must NOT overwrite external whitepapers or cross-chamber statements
    fills_wp = can_fill_from_relational_v6(
        rel_sd_row,
        "external_report_or_whitepaper",
        filename="HHRG-118-GO00-20240320-SD003.pdf",
        text="Independent Economic Outlook Report by Acme Research Institute.",
    )
    assert fills_wp.get("chamber") is None
    assert not fills_wp.get("committees")

    # 3. SFRC executive/ambassador nominee "Opening Statement" -> `witness_statement`, NEVER `member_opening_statement`
    sfrc_nominee_text = (
        "Statement of the Honorable Mark T. Sullivan\n"
        "Nominee to be Ambassador Extraordinary and Plenipotentiary of the United States of America "
        "to the Republic of Chile\n"
        "Senate Committee on Foreign Relations\n"
        "May 16, 2024\n"
        "Chairman Cardin, Ranking Member Risch, and Members of the Committee, thank you for the opportunity."
    )
    nom_override = detect_nominee_opening_override_v6("sullivan_testimony.pdf", sfrc_nominee_text)
    assert nom_override is not None
    assert nom_override[1] == "witness_statement"
    _, cov_kind, _ = detect_cover_lock_v6("sullivan_testimony.pdf", sfrc_nominee_text)
    assert cov_kind == "witness_statement"


def test_citations_short_titles_fiscal_years_and_refspec_safeguards() -> None:
    """Verify statutory/procedural citations, short titles, fiscal years, and RefSpec TRAP_1/TRAP_2/TRAP_5 guards."""
    leg_text = (
        "1 Be it enacted by the Senate and House of Representatives of the United States of America in Congress assembled,\n"
        "2 SECTION 1. SHORT TITLE.\n"
        '3 This Act may be cited as the "Grid Resilience and Critical Infrastructure Act of 2024".\n'
        "4 SEC. 2. AMENDMENTS.\n"
        "5 (a) Section 552b(c) of title 5, 9 United States Code, and 41 U.S.C. 8302A are amended.\n"
        "6 (b) See Public Law 117-58, 42 U.S.C. 7411, 14 CFR Part 77, 89 FR 12345, H.R. 4366, "
        "Executive Order 14110, GAO-24-105510, and CRS Report R47500 for FY2024 and Fiscal Year 2025.\n"
        "7 Internal path C:\\temp\\E043025.003.xml and Executive Order 99999 must be ignored.\n"
    )
    cits = extract_citations_and_signals_v6(
        leg_text,
        filename="BILLS-118hr9001ih.pdf",
        congress=118,
        primary_kind="bill_or_draft",
        auto_load_oracles=False,
    )
    refs = cits["det_refs"]
    assert any(r.startswith("usc:5 U.S.C. 552b") for r in refs)
    assert any("8302a" in r.lower() for r in refs)
    assert any("117-58" in r for r in refs)
    assert any(r.startswith("cfr:14 C.F.R.") or r.startswith("cfr:14 CFR") for r in refs)
    assert any("14110" in r for r in refs)
    assert not any("43025" in r or "99999" in r for r in refs)
    assert "Grid Resilience and Critical Infrastructure Act of 2024" in extract_short_titles_v6(leg_text)
    assert extract_fiscal_years_v6(leg_text) == [2024, 2025]

    # Verify `post_pass_v6` prunes hallucinated DRN bill numbers, unnumbered H.R. 119, phone IDs, and slug IDs
    raw_llm = {
        "status": "usable",
        "text_quality": "native",
        "congress": 119,
        "primary_kind": "witness_statement",
        "personas": [{"name": "Sarah Jenkins", "role": "witness", "entity_type": "non_gov_person"}],
        "refs": [
            "bill:H.R. 24068",
            "bill:H.R. 119",
            "id:202-225-6371",
            "id:QFR001",
            "bill:H.R. 4366",
        ],
        "composed_title": "Testimony of Sarah Jenkins on H.R. 4366",
        "gist": "Witness testimony supporting H.R. 4366.",
        "topics": ["appropriations"],
    }
    prose = (
        "Draft DRN24068 — 119th Congress discussion draft H.R. ____ and H.R. 4366. "
        "Contact (202) 225-6371."
    )
    clean_obj, _ = post_pass_v6(raw_llm, filename="HHRG-119-AP00-Wstate-JenkinsS-20250304.pdf", text=prose)
    kept_refs = clean_obj.get("refs", [])
    assert "bill:H.R. 4366" in kept_refs
    assert "bill:H.R. 24068" not in kept_refs
    assert "bill:H.R. 119" not in kept_refs
    assert "id:202-225-6371" not in kept_refs
    assert "id:QFR001" not in kept_refs


def test_zero_llm_bypass_v6_and_strict_validate_v4() -> None:
    """Verify 0-GPU-token `try_zero_llm_bypass_v6` synthesis and `strict_validate_v4` causal order checks."""
    ttf_lines = (
        "Enclosure 3\n"
        "Committee on Science, Space, and Technology\n"
        "U.S. House of Representatives\n"
        'Witness Disclosure Requirement - "Truth in Testimony"\n'
        "Required by House Rule XI, Clause 2(g)(5)\n"
        "1. Your Name:\n"
        "Marcus Holloway\n"
        "2. Are you testifying on behalf of the Federal, or a State or local government entity?\n"
        "No\n"
        "3. Are you testifying on behalf of an entity that is not a government entity?\n"
        "Yes\n"
        "Clean Grid Alliance\n"
        "4. Other than yourself, please list which entity or entities you are representing:\n"
        "Clean Grid Alliance\n"
        "5. Please list any Federal grants or contracts (including subgrants or subcontracts) "
        "that you or the entity(ies) you represent have received on or after October 1, 2021:\n"
        "None\n"
        "6. Signature of Witness: Marcus Holloway Date: 05/22/2024\n"
    )
    sig_id, locked_kind = detect_exact_tier1_signature_v5(
        "HHRG-118-SY00-TTF-HollowayM-20240522.pdf",
        ttf_lines,
    )
    assert locked_kind == "truth_in_testimony_disclosure"

    synthesized = try_zero_llm_bypass_v6(
        locked_primary_kind=locked_kind,
        tier1_signature_id=sig_id,
        filename="HHRG-118-SY00-TTF-HollowayM-20240522.pdf",
        text=ttf_lines,
        p12_lines=ttf_lines,
    )
    assert synthesized is not None
    assert synthesized["primary_kind"] == "truth_in_testimony_disclosure"
    assert synthesized["congress"] == 118
    assert "Holloway" in synthesized["personas"][0]["name"]
    ok, err = strict_validate_v4(synthesized)
    assert ok is True and err is None

    # Verify `pre_pass_v6(..., use_zero_llm_bypass=True)` -> `post_pass_v6` end-to-end
    _, pmeta = pre_pass_v6(
        None,
        "HHRG-118-SY00-TTF-HollowayM-20240522.pdf",
        ttf_lines,
        p12_lines=ttf_lines,
        use_zero_llm_bypass=True,
    )
    assert pmeta["zero_llm_docmeta"] is not None
    final_obj, sidecar = post_pass_v6(
        pmeta["zero_llm_docmeta"],
        filename="HHRG-118-SY00-TTF-HollowayM-20240522.pdf",
        text=ttf_lines,
        p12_lines=ttf_lines,
    )
    ok_post, err_post = strict_validate_v4(final_obj)
    assert ok_post is True and err_post is None
    assert sidecar["anomaly_routing"]["has_anomaly"] is False

    # Verify `strict_validate_v4` catches out-of-order causal keys
    bad_order = {
        "text_quality": "native",
        "status": "usable",
        "primary_kind": "witness_statement",
        "composed_title": "Testimony",
        "gist": "Summary.",
        "topics": ["energy"],
    }
    ok_bad, err_bad = strict_validate_v4(bad_order)
    assert ok_bad is False
    assert err_bad is not None and "order" in err_bad




def test_anomaly_router_v6_and_graceful_data_degradation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify `score_docmeta_anomalies_v6` flags true structural/relational errors and degrades cleanly without data."""
    clean_doc = {
        "status": "usable",
        "text_quality": "native",
        "chamber": "house",
        "congress": 118,
        "committees": ["Committee on the Judiciary"],
        "event_date": "2023-05-10",
        "primary_kind": "witness_statement",
        "personas": [{"name": "Jane Smith", "role": "witness", "entity_type": "non_gov_person"}],
        "composed_title": "Testimony of Jane Smith on Judicial Administration",
        "gist": "Jane Smith testifies on federal court administration.",
        "topics": ["federal courts"],
    }
    clean_ctx = {
        "filename": "HHRG-118-JU00-Wstate-SmithJ-20230510.pdf",
        "text": "Statement of Jane Smith before the House Committee on the Judiciary, May 10, 2023.",
        "witness_keys": ["w_smith"],
        "rel_witness_name": "Jane Smith",
        "rel_congress": 118,
        "rel_chamber": "house",
        "rel_committees": ["Committee on the Judiciary"],
    }
    ok_rep = score_docmeta_anomalies_v6(clean_doc, clean_ctx)
    assert ok_rep["has_anomaly"] is False
    assert ok_rep["anomaly_codes"] == []

    # Anomalous doc: missing actor on witness_statement + wrong congress vs 118 slug + invalid USC ref + >10 raw personas
    bad_doc = {
        "status": "usable",
        "text_quality": "native",
        "congress": 112,
        "primary_kind": "witness_statement",
        "refs": ["usc:49 U.S.C. 77"],
        "composed_title": "Testimony",
        "gist": "Summary.",
        "topics": ["oversight"],
    }
    bad_ctx = {
        "filename": "HHRG-118-JU00-Wstate-SmithJ-20230510.pdf",
        "text": "Statement of Jane Smith, May 10, 2023.",
        "raw_persona_count": 14,
        "witness_keys": ["w_smith"],
        "rel_witness_name": "Jane Smith",
        "usc_oracle_invalid_refs": ["usc:49 U.S.C. 77"],
    }
    bad_rep = score_docmeta_anomalies_v6(bad_doc, bad_ctx)
    assert bad_rep["has_anomaly"] is True
    assert bad_rep["escalate_to_teacher"] is True
    assert len(bad_rep["anomaly_codes"]) >= 3

    batch = route_batch_anomalies_v6([clean_doc, bad_doc], [clean_ctx, bad_ctx])
    assert batch["flagged_indices"] == [1]
    assert batch["flagged_count"] == 1

    # Graceful degradation when `DOCMETA_V6_DATA_DIR` and `REFSPEC_ROOT` are absent
    empty_data = tmp_path / "missing_v6_data"
    empty_refspec = tmp_path / "missing_refspec"
    monkeypatch.setenv("DOCMETA_V6_DATA_DIR", str(empty_data))
    monkeypatch.setenv("REFSPEC_ROOT", str(empty_refspec))
    assert load_rosters_lookup_v6() == {}
    empty_oracles = load_refspec_oracles_v6()
    assert empty_oracles.usc_oracle is None
    assert empty_oracles.act_index is None




def test_v6_2_audit_remediations_panel_roles_date_and_rolling_order() -> None:
    """Verify V6.2 schema/engine audit fixes: string `panel`, TOC `questioner`, `date` ordering, Jan 3 noon, and `doc_order`."""
    import datetime

    from congress_docmeta import (
        check_gist_title_grounding_v6,
        disambiguate_persona_roles_v6,
        iso_date_to_congress_v6,
        order_and_validate_docmeta_v6,
        parse_gpo_p3_slice_personas_v6,
        parse_witness_list_personas_v6,
        valid_cong_surnames,
    )

    # 1. Multi-panel witness list produces string `panel` (`"Panel 1"`, `"Panel 2"`)
    wl_text = (
        "WITNESS LIST\n"
        "Panel I\n"
        "The Honorable Jane Roe, Deputy Secretary, Department of Energy\n"
        "Panel II\n"
        "Dr. Alan Turing, Director, National Computing Institute\n"
    )
    wl_personas = parse_witness_list_personas_v6(wl_text)
    assert len(wl_personas) == 2
    assert wl_personas[0]["panel"] == "Panel 1"
    assert wl_personas[1]["panel"] == "Panel 2"

    # 2. GPO p3 TOC slice maps non-opening Members to `"questioner"` (never invalid `"member"`)
    toc_slice = (
        "CONTENTS\n"
        "Opening Statement of Hon. Frank Lucas, Chairman .................... 1\n"
        "Statement of Hon. Zoe Lofgren, a Representative in Congress from the State of California .... 4\n"
        "Prepared Statement of Dr. Alan Turing, Witness ..................... 12\n"
    )
    p3_personas = parse_gpo_p3_slice_personas_v6(toc_slice)
    roles_by_name = {p["name"]: p["role"] for p in p3_personas}
    assert all(p["role"] != "member" for p in p3_personas)
    assert any(r in ("author_or_speaker", "questioner") for r in roles_by_name.values())

    # 3. `zero_llm_bypass_v6` handles `datetime.date` and integer `panel` cleanly (`out[k]`, zero `NameError`)
    ordered = order_and_validate_docmeta_v6(
        {
            "status": "usable",
            "text_quality": "native",
            "congress": 118,
            "doc_date": datetime.date(2024, 5, 14),
            "primary_kind": "witness_list",
            "personas": [
                {
                    "name": "Elena Vance",
                    "role": "witness",
                    "entity_type": "non_gov_person",
                    "panel": 2,
                    "title": datetime.date(2024, 5, 14),
                }
            ],
            "composed_title": "Witness List for May 14, 2024 Hearing",
            "gist": "Witness panel roster for May 14, 2024 hearing.",
            "topics": ["oversight"],
        }
    )
    assert ordered is not None
    assert ordered["personas"][0]["panel"] == "Panel 2"
    assert ordered["personas"][0]["title"] == "2024-05-14"
    ok_ord, err_ord = strict_validate_v4(ordered)
    assert ok_ord is True and err_ord is None

    # 4. Constitutional Congress calendar (`Jan 3` odd-year straddle -> `None`; pre-2001 -> valid)
    assert iso_date_to_congress_v6("2023-01-03") is None
    assert iso_date_to_congress_v6("2023-01-02") == 117
    assert iso_date_to_congress_v6("2023-01-04") == 118
    assert iso_date_to_congress_v6("1999-06-15") == 106

    # 5. Deterministic 0-FP persona role disambiguation (`R1`, `R2`, `R3`) + `@lru_cache` `valid_cong_surnames`
    inv_personas = disambiguate_persona_roles_v6(
        [
            {"name": "Tim Murphy", "role": "chair", "entity_type": "member"},
            {"name": "Michael Brey", "role": "witness", "entity_type": "non_gov_person"},
        ],
        primary_kind="witness_invitation",
        text="Dear Mr. Brey: On behalf of the Subcommittee, we invite you to testify.\nSincerely,\nTim Murphy, Chairman",
    )
    assert inv_personas[0]["role"] == "sender"
    assert inv_personas[1]["role"] == "recipient"

    open_personas = disambiguate_persona_roles_v6(
        [{"name": "John Thune", "role": "witness", "entity_type": "member"}],
        primary_kind="member_opening_statement",
        text="OPENING STATEMENT OF HON. JOHN THUNE, U.S. SENATOR FROM SOUTH DAKOTA",
    )
    assert open_personas[0]["role"] == "author_or_speaker"

    sub_personas = disambiguate_persona_roles_v6(
        [{"name": "Rosa DeLauro", "role": "witness", "entity_type": "member"}],
        primary_kind="external_submission_letter",
        text="Document SUBMITTED FOR THE RECORD BY HON. ROSA DELAURO.",
    )
    assert sub_personas[0]["role"] == "introducer"

    valid_cong_surnames.cache_clear()
    _ = valid_cong_surnames(118)
    _ = valid_cong_surnames(118)
    assert valid_cong_surnames.cache_info().hits >= 1


    # 6. `C0_Stdlib` `check_gist_title_grounding_v6` catches hallucinations & passes faithful summaries
    src_text = (
        "Statement of Dr. Sarah Chen before the House Committee on Science, Space, and Technology, "
        "May '18, examining H.R. 4366 and $25 million in grid modernization research grants."
    )
    good_dm = {
        "status": "usable",
        "text_quality": "native",
        "congress": 115,
        "primary_kind": "witness_statement",
        "personas": [{"name": "Sarah Chen", "role": "witness", "entity_type": "non_gov_person"}],
        "disclosure": {"capacity": "individual", "gov_witness": False, "has_foreign_payments": False},
        "composed_title": "Testimony of Sarah Chen on H.R. 4366 Grid Modernization (2018)",
        "gist": "Sarah Chen testifies on H.R. 4366 and $25 million grid research grants.",
        "topics": ["grid modernization"],
    }
    g_ok = check_gist_title_grounding_v6(good_dm, text=src_text, filename="Exhibit_10_20180522.pdf")
    assert g_ok["is_grounded"] is True

    bad_dm = dict(
        good_dm,
        gist="Mandates $450 billion under H.R. 9912 and discloses substantial foreign grants.",
    )
    g_bad = check_gist_title_grounding_v6(bad_dm, text=src_text, filename="Exhibit_10_20180522.pdf")
    assert g_bad["is_grounded"] is False
    assert g_bad["ungrounded_citations"]
    assert g_bad["ungrounded_modality"]
    anom_bad = score_docmeta_anomalies_v6(bad_dm, {"filename": "Exhibit_10_20180522.pdf", "text": src_text})
    assert "ungrounded_gist_or_title" in anom_bad["anomaly_codes"]






def test_r4_witness_statement_salutation_chair_personas() -> None:
    """R4: the chair / ranking member a witness addresses by name is listed; passing mentions are not."""
    from congress_docmeta.relational_rules_v6 import (
        add_salutation_chair_personas_v6,
        disambiguate_persona_roles_v6,
        salutation_chair_personas_v6,
    )

    assert salutation_chair_personas_v6(
        "Chairman Latta, Ranking Member Matsui, and Members of the Subcommittee, thank you."
    ) == [("chair", "Latta"), ("ranking_member", "Matsui")]
    # A match that runs over the sentence end keeps the name and drops the period and the next word.
    assert salutation_chair_personas_v6(
        "Good morning Chairwoman McMorris Rodgers and Ranking Member Pallone. Thank you for inviting me."
    ) == [("chair", "McMorris Rodgers"), ("ranking_member", "Pallone")]
    assert salutation_chair_personas_v6("Chair DeGette and distinguished members of the Subcommittee") == [
        ("chair", "DeGette")
    ]
    # Not an address: a chair quoted in passing, an unnamed chair, a committee rather than a person.
    assert salutation_chair_personas_v6("As Chairman Powell said last week, inflation remains high.") == []
    assert salutation_chair_personas_v6("Mr. Chairman, Ranking Member, and Members of the Committee") == []

    witness = {"name": "Jennifer A. Manner", "role": "witness", "entity_type": "non_gov_person"}
    sponsor = {"name": "Ginny Brown-Waite", "role": "cosponsor", "entity_type": "member"}
    text = "Chairwoman Herseth-Sandlin, Ranking Member Boozman, and Members of the Subcommittee:"
    added = add_salutation_chair_personas_v6([witness, sponsor], text)
    assert [(p["role"], p["name"]) for p in added] == [
        ("witness", "Jennifer A. Manner"),
        ("chair", "Herseth-Sandlin"),
        ("ranking_member", "Boozman"),
        ("cosponsor", "Ginny Brown-Waite"),
    ]
    # Already listed under a spaced spelling or a fuller name: nothing is duplicated.
    listed = [witness, {"name": "Stephanie Herseth Sandlin", "role": "chair", "entity_type": "member"}]
    assert [p["name"] for p in add_salutation_chair_personas_v6(listed, text)] == [
        "Jennifer A. Manner",
        "Stephanie Herseth Sandlin",
        "Boozman",
    ]
    assert len(add_salutation_chair_personas_v6([witness] * 10, text)) == 10

    # Only witness statements: a letter's addressees are recipients, not chair personas.
    for kind, want in (("witness_statement", 3), ("external_submission_letter", 1)):
        out = disambiguate_persona_roles_v6([witness], primary_kind=kind, text=text)
        assert len(out) == want


def test_r5_bill_sponsor_line_and_r6_letter_addressees() -> None:
    """R5/R6: sponsors and letter addressees named in a fixed form are listed even when the model lists none."""
    from congress_docmeta.relational_rules_v6 import (
        add_text_grounded_personas_v6,
        bill_sponsor_personas_v6,
        disambiguate_persona_roles_v6,
        letter_addressee_personas_v6,
    )

    bill = (
        "115TH CONGRESS\n1ST SESSION H. R. 1719\nIN THE HOUSE OF REPRESENTATIVES\nMARCH 24, 2017\n"
        "Mr. DESAULNIER (for himself, Mr. KING of New York, Mr. MCGOVERN, Ms. DE LA CRUZ, and Mr. VAN DREW) "
        "introduced the following bill; which was referred to the Committee on Natural Resources"
    )
    assert bill_sponsor_personas_v6(bill) == [
        ("sponsor", "Desaulnier"),
        ("cosponsor", "King"),
        ("cosponsor", "McGovern"),
        ("cosponsor", "De La Cruz"),
        ("cosponsor", "Van Drew"),
    ]
    # Discussion-draft placeholders name nobody.
    assert bill_sponsor_personas_v6("Mr. llllll introduced the following bill; which was referred") == []
    assert bill_sponsor_personas_v6("Mr. PANETTA introduced the following bill") == [("sponsor", "Panetta")]

    # A sponsor invented from the title is dropped; a cosponsor mislabelled as sponsor is re-labelled.
    invented = [{"name": "John Muir", "role": "sponsor", "entity_type": "member"}]
    fixed = add_text_grounded_personas_v6(invented, primary_kind="bill_or_draft", text=bill)
    assert [(p["role"], p["name"]) for p in fixed][:2] == [("sponsor", "Desaulnier"), ("cosponsor", "King")]
    assert all(p["name"] != "John Muir" for p in fixed)
    mislabelled = [{"name": "Peter King", "party_state": "NY", "role": "sponsor", "entity_type": "member"}]
    fixed = add_text_grounded_personas_v6(mislabelled, primary_kind="bill_or_draft", text=bill)
    assert (fixed[0]["role"], fixed[0]["name"]) == ("sponsor", "Desaulnier")
    assert {"name": "Peter King", "party_state": "NY", "role": "cosponsor", "entity_type": "member"} in fixed
    assert sum(p["name"].endswith("King") for p in fixed) == 1
    # The rule also runs through the post-pass entry point when the model listed nobody.
    assert len(disambiguate_persona_roles_v6([], primary_kind="bill_or_draft", text=bill)) == 5
    # No sponsor line: the model's personas are left alone.
    assert add_text_grounded_personas_v6(invented, primary_kind="bill_or_draft", text="A BILL\nTo amend") == invented

    letter = (
        "June 7, 2017\n\nThe Honorable Lamar Smith\nChairman\nHouse Committee on Science, Space, and Technology\n"
        "Washington, DC 20515\n\nThe Honorable Janet Yellen\nSecretary\nDepartment of the Treasury\n1500 Pennsylvania "
        "Avenue NW\nWashington, DC 20220\n\nDear Chairman Smith and Secretary Yellen:\nWe write on behalf of"
    )
    assert letter_addressee_personas_v6(letter, to_member=False) == [
        ("member", "Lamar Smith"),
        ("gov_official", "Janet Yellen"),
    ]
    sender = {"name": "Tom Stroup", "role": "sender", "entity_type": "non_gov_person"}
    fixed = add_text_grounded_personas_v6([sender], primary_kind="oversight_letter", text=letter)
    assert [(p["role"], p["entity_type"], p["name"]) for p in fixed] == [
        ("sender", "non_gov_person", "Tom Stroup"),
        ("recipient", "member", "Lamar Smith"),
        ("recipient", "gov_official", "Janet Yellen"),
    ]
    # A committee's letter to a private witness: the addressee is a recipient, not a Member.
    invite = "Ms. Heather Bresch\nChief Executive Officer\nMylan, Inc.\n1000 Mylan Boulevard\n\nDear Ms. Bresch:\n"
    assert letter_addressee_personas_v6(invite, to_member=False) == [("non_gov_person", "Bresch")]
    fixed = add_text_grounded_personas_v6([], primary_kind="witness_invitation", text=invite)
    assert fixed == [{"name": "Bresch", "role": "recipient", "entity_type": "non_gov_person"}]
    # Other kinds are untouched.
    assert add_text_grounded_personas_v6([sender], primary_kind="press_release_or_fact_sheet", text=letter) == [sender]


def test_r7_subcommittee_must_be_named_or_resolve_from_code() -> None:
    """R7: a subcommittee guessed from the advisory committee code is dropped unless page or lookup confirms it."""
    from congress_docmeta.relational_rules_v6 import ground_subcommittees_v6

    lookup = {"subcommittees_meta": {"hsvr09": {"name": "House Veterans' Affairs Subcommittee on Disability Assistance and Memorial Affairs"}}}
    page = "Statement before the Subcommittee on Oversight & Investigations, Committee on Veterans' Affairs"
    kw = {"text": page, "committee_codes": ["hsvr00", "hsvr09"], "congress": 113, "lookup": lookup}

    # Named on the page (`&` and `and` are the same name), or resolved from the code: kept as the model wrote it.
    assert ground_subcommittees_v6(["Subcommittee on Oversight and Investigations"], **kw) == [
        "Subcommittee on Oversight and Investigations"
    ]
    assert ground_subcommittees_v6(["Subcommittee on Disability Assistance and Memorial Affairs"], **kw) == [
        "Subcommittee on Disability Assistance and Memorial Affairs"
    ]
    # Neither: the guess goes, and the lookup's own name is not substituted for it.
    assert ground_subcommittees_v6(["Subcommittee on Health"], **kw) == []
    # A relational fill is trusted without appearing on the page.
    assert ground_subcommittees_v6(["Subcommittee on Health"], trusted=["Subcommittee on Health"], **kw) == [
        "Subcommittee on Health"
    ]
    assert ground_subcommittees_v6(None, **kw) == []


def test_compact_prompt_serializes_known_one_way() -> None:
    """`run_records` hands spaced JSON and the parquet sweep hands compact JSON; the model must see one form."""
    from congress_docmeta.compact_wire_v6 import build_prompt_v6_compact, compact_known_str

    spaced = '{"congress": 117, "cmt": ["ssap00"], "chambers": ["senate"], "date": null}'
    compact = '{"congress":117,"cmt":["ssap00"],"chambers":["senate"],"date":null}'
    assert compact_known_str(spaced) == compact_known_str(compact) == compact
    assert compact_known_str("<NONE>") == "<NONE>"
    assert build_prompt_v6_compact(spaced, "a.pdf", "T") == build_prompt_v6_compact(compact, "a.pdf", "T")
    assert f"Advisory known metadata: {compact}\nFilename: a.pdf\nText:\nT" in build_prompt_v6_compact(spaced, "a.pdf", "T")


def test_compact_wire_round_trip_and_checkpoint_wire_detection(tmp_path: Path) -> None:
    """`DocMetaV6Compact` drops defaults, expands back to a valid V4 object, and a checkpoint names its wire."""
    from congress_docmeta import (
        canonicalize_docmeta_v4,
        detect_checkpoint_wire_format,
        encode_v4_to_compact_v6,
        expand_compact_v6_to_v4,
        validate_docmeta_v4,
    )
    from congress_docmeta.cli import build_parser

    sample_v4 = {
        "status": "usable",
        "text_quality": "native",
        "chamber": "house",
        "congress": 118,
        "committees": ["House Committee on Natural Resources"],
        "doc_date": "2024-06-04",
        "primary_kind": "witness_statement",
        "personas": [{"name": "Raúl Grijalva", "role": "ranking_member", "entity_type": "member"}],
        "refs": ["bill:118:hr:1838"],
        "fiscal_years": [2025],
        "composed_title": "Statement of Ranking Member Raúl Grijalva",
        "gist": "Ranking Member Grijalva outlines water conservation priorities.",
        "topics": ["water", "conservation"],
    }
    comp = encode_v4_to_compact_v6(sample_v4)
    assert "st" not in comp and "tq" not in comp and "rf" not in comp and "fy" not in comp
    exp = canonicalize_docmeta_v4(expand_compact_v6_to_v4(comp))
    ok_v4, err = validate_docmeta_v4(exp)
    assert ok_v4, err
    assert exp["personas"][0]["name"] == "Raúl Grijalva"

    (tmp_path / "docmeta_wire_config.json").write_text('{"wire_format": "compact_v6"}\n', encoding="utf-8")
    assert detect_checkpoint_wire_format(tmp_path) == "compact"
    parsed = build_parser().parse_args(["docmeta-sweep", "in.parquet", "out.parquet", "--wire-format", "compact"])
    assert parsed.wire_format == "compact"


def test_run_records_defaults_match_the_engines_rolling_defaults() -> None:
    """`PythonicEngineV6.run_records` keeps `B_slots=256` and `swa_ring_cap=512`, the engine's `run_rolling` defaults."""
    import inspect

    from congress_docmeta import PythonicEngineV6

    sig = inspect.signature(PythonicEngineV6.run_records).parameters
    assert sig["B_slots"].default == 256
    assert sig["swa_ring_cap"].default == 512
