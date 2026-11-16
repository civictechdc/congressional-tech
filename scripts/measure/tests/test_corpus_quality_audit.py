"""Offline unit and end-to-end integration tests for `corpus_quality` (`core`, `provenance_validator`, CLI)."""
from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from viewer_publication.corpus_quality.core import (
    DEFAULT_STOPWORDS,
    extract_header_footer_windows,
    iter_word_ngrams,
    load_corpus_rows,
    structural_shingles,
    unwrap_archive_url,
    url_path_template,
)
from viewer_publication.corpus_quality.provenance_validator import (
    resolve_host_committee_code,
    validate_dataset_provenance,
)

ROOT = Path(__file__).resolve().parents[3]
_CLI_SPEC = importlib.util.spec_from_file_location(
    "corpus_quality_audit",
    ROOT / "scripts" / "measure" / "corpus_quality_audit.py",
)
assert _CLI_SPEC is not None and _CLI_SPEC.loader is not None
audit_cli = importlib.util.module_from_spec(_CLI_SPEC)
_CLI_SPEC.loader.exec_module(audit_cli)


def _lk_bytes(idx: int) -> bytes:
    return idx.to_bytes(8, "big")


def _sb_bytes(tag: str) -> bytes:
    return sha256(tag.encode("utf-8")).digest()


def _doc_key_for_lk(lk: bytes) -> str:
    return sha256(lk).hexdigest()


def _write_release_fixture(
    target_dir: Path,
    records: list[dict[str, Any]],
    *,
    witness_keys: list[str] | None = None,
    bill_ids: list[str] | None = None,
) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    detail_rows = []
    list_rows = []
    source_rows = []

    for idx, rec in enumerate(records):
        lk = rec.get("link_key", _lk_bytes(idx + 1))
        sb = rec.get("saved_body", _sb_bytes(f"body-{idx}"))
        fn = rec.get("filename", f"doc_{idx}.pdf")
        dkind = rec.get("document_kind", ["hearing-transcript"])
        ckeys = rec.get("committee_keys", ["hsju00"])
        cong = rec.get("congress", 118)
        ddate = rec.get("document_date", "2023-05-10")
        dk = rec.get("date_kind", "captured")
        dstat = rec.get("document_date_status", "accepted")
        dsrc = rec.get("document_date_source", "filename")
        txt = rec.get("selected_text", "COMMITTEE ON THE JUDICIARY\n118th Congress\nHearing body text.")

        detail_rows.append(
            {
                "link_key": lk,
                "saved_body": sb,
                "saved_suffix": ".pdf",
                "package_id": rec.get("package_id"),
                "filename": fn,
                "title": rec.get("title", fn),
                "document_kind": dkind,
                "document_family": ["committee"],
                "committee_keys": ckeys,
                "chambers": rec.get("chambers", ["house"]),
                "congress": cong,
                "format": "pdf",
                "document_date": ddate,
                "date_kind": dk,
                "document_date_status": dstat,
                "document_date_source": dsrc,
                "meeting_keys": rec.get("meeting_keys", []),
                "measure_keys": rec.get("measure_keys", []),
                "bioguide_ids": rec.get("bioguide_ids", []),
                "witness_keys": rec.get("witness_keys", []),
                "selected_text": txt,
            }
        )
        list_rows.append(
            {
                "filename": fn,
                "title": rec.get("title", fn),
                "document_kind": dkind,
                "document_family": ["committee"],
                "committee_keys": ckeys,
                "chambers": rec.get("chambers", ["house"]),
                "congress": cong,
                "format": "pdf",
                "document_date": ddate,
                "date_kind": dk,
                "document_date_status": dstat,
                "meeting_keys": rec.get("meeting_keys", []),
                "measure_keys": rec.get("measure_keys", []),
                "bioguide_ids": rec.get("bioguide_ids", []),
                "witness_keys": rec.get("witness_keys", []),
            }
        )
        if rec.get("url") or rec.get("listed_on"):
            source_rows.append(
                {
                    "list_row": idx,
                    "ordinal": 0,
                    "url": rec.get("url"),
                    "listed_on": rec.get("listed_on"),
                    "member_path": rec.get("member_path"),
                    "link_text": rec.get("link_text", "View PDF"),
                }
            )

    detail_schema = pa.schema(
        [
            ("link_key", pa.binary(8)),
            ("saved_body", pa.binary(32)),
            ("saved_suffix", pa.string()),
            ("package_id", pa.string()),
            ("filename", pa.string()),
            ("title", pa.string()),
            ("document_kind", pa.list_(pa.string())),
            ("document_family", pa.list_(pa.string())),
            ("committee_keys", pa.list_(pa.string())),
            ("chambers", pa.list_(pa.string())),
            ("congress", pa.int16()),
            ("format", pa.string()),
            ("document_date", pa.string()),
            ("date_kind", pa.string()),
            ("document_date_status", pa.string()),
            ("document_date_source", pa.string()),
            ("meeting_keys", pa.list_(pa.string())),
            ("measure_keys", pa.list_(pa.string())),
            ("bioguide_ids", pa.list_(pa.string())),
            ("witness_keys", pa.list_(pa.string())),
            ("selected_text", pa.string()),
        ]
    )
    pq.write_table(pa.Table.from_pylist(detail_rows, schema=detail_schema), target_dir / "detail.parquet")
    pq.write_table(pa.Table.from_pylist(list_rows), target_dir / "list.parquet")
    if source_rows:
        pq.write_table(pa.Table.from_pylist(source_rows), target_dir / "sources.parquet")
    if witness_keys is not None:
        pq.write_table(
            pa.Table.from_pylist([{"witness_key": wk} for wk in witness_keys]),
            target_dir / "witnesses.parquet",
        )
    if bill_ids is not None:
        pq.write_table(
            pa.Table.from_pylist([{"bill_id": bid} for bid in bill_ids]),
            target_dir / "bills.parquet",
        )


def _write_docmeta_fixture(
    dm_dir: Path,
    *,
    completed: list[dict[str, Any]],
    queue: list[dict[str, Any]],
    aliases: list[dict[str, Any]],
) -> None:
    dm_dir.mkdir(parents=True, exist_ok=True)
    comp_schema = pa.schema(
        [
            ("link_key", pa.binary(8)),
            ("doc_key", pa.string()),
            ("saved_body", pa.binary(32)),
            ("package_id", pa.string()),
            ("disposition", pa.string()),
            ("v6_route", pa.string()),
            ("zero_llm_source", pa.string()),
            ("filename", pa.string()),
            ("effective_format", pa.string()),
            ("primary_kind", pa.string()),
            ("status", pa.string()),
            ("congress", pa.int64()),
            ("chamber", pa.string()),
            ("committees", pa.list_(pa.string())),
            ("docmeta_json", pa.string()),
            ("strict_v4_valid", pa.bool_()),
        ]
    )
    queue_schema = pa.schema(
        [
            ("link_key", pa.binary(8)),
            ("doc_key", pa.string()),
            ("saved_body", pa.binary(32)),
            ("package_id", pa.string()),
            ("disposition", pa.string()),
            ("v6_route", pa.string()),
            ("filename", pa.string()),
            ("effective_format", pa.string()),
            ("text_source", pa.string()),
            ("p12_raw_text", pa.string()),
            ("p12_clean_text", pa.string()),
            ("locked_primary_kind", pa.string()),
            ("grammar_lock_source", pa.string()),
        ]
    )
    alias_schema = pa.schema(
        [
            ("link_key", pa.binary(8)),
            ("doc_key", pa.string()),
            ("saved_body", pa.binary(32)),
            ("package_id", pa.string()),
            ("disposition", pa.string()),
            ("sub_disposition", pa.string()),
            ("v6_route", pa.string()),
            ("filename", pa.string()),
            ("effective_format", pa.string()),
            ("canonical_link_key", pa.binary(8)),
            ("canonical_doc_key", pa.string()),
            ("canonical_partition_bucket", pa.string()),
            ("canonical_v6_route", pa.string()),
        ]
    )
    pq.write_table(pa.Table.from_pylist(completed, schema=comp_schema), dm_dir / "completed_no_llm_v6_1.parquet")
    pq.write_table(pa.Table.from_pylist(queue, schema=queue_schema), dm_dir / "llm_queue_v6_1.parquet")
    pq.write_table(pa.Table.from_pylist(aliases, schema=alias_schema), dm_dir / "sha_dup_alias_v6_1.parquet")


def test_core_text_window_ngrams_shingles_and_url_templates() -> None:
    sample = "\n".join(
        [
            "TRUTH IN TESTIMONY DISCLOSURE FORM",
            "118th Congress",
            "Witness Name: Jane Doe",
            "[x] Nongovernmental entity",
            *(f"Body line {i} discussing H.R. 1234 on 2024-05-16." for i in range(30)),
            "Footer nav: Committee on the Judiciary | Washington, DC",
        ]
    )
    win = extract_header_footer_windows(sample, max_header_lines=4, max_footer_lines=2)
    hdr, ftr = extract_header_footer_windows(sample, max_header_lines=4, max_footer_lines=2)
    assert hdr == win.header
    assert ftr == win.footer
    assert "TRUTH IN TESTIMONY" in win.header
    assert "Washington, DC" in win.footer

    ng_explicit = list(iter_word_ngrams("Truth in Testimony Disclosure Form", n=(1, 3), stopwords=DEFAULT_STOPWORDS))
    ng_ranged = list(
        iter_word_ngrams("Truth in Testimony Disclosure Form", ngram_range=(1, 3), stopwords=DEFAULT_STOPWORDS)
    )
    assert "truth in testimony" in ng_explicit
    assert "truth in testimony" in ng_ranged
    assert "in" not in ng_explicit

    sh = structural_shingles(sample)
    assert "shape:checkbox_form" in sh
    assert any(tok.startswith("hdr:") for tok in sh)

    wrapped = (
        "https://web.archive.org/web/20231109123000id_/"
        "https://docs.house.gov/meetings/JU/JU00/20200516/110999/HHRG-116-JU00-TTF-DoeJ-20200516.pdf"
    )
    cu, wk, ts = unwrap_archive_url(wrapped)
    assert wk == "wayback"
    assert ts == "20231109123000"
    assert cu.startswith("https://docs.house.gov/meetings/JU/")
    assert url_path_template(wrapped) == "docs.house.gov/meetings/{cmt2}/{subcode}/{yyyymmdd}/{id}/{hhrg_slug}.pdf"
    assert resolve_host_committee_code(None, wrapped) == "hsju00"


def test_provenance_validator_clean_conservation_and_hres_allowance(tmp_path: Path) -> None:
    tdir = tmp_path / "published"
    dmdir = tmp_path / "docmeta"
    lk1, lk2, lk3 = _lk_bytes(1), _lk_bytes(2), _lk_bytes(3)
    sb1, sb2 = _sb_bytes("b1"), _sb_bytes("b2")

    _write_release_fixture(
        tdir,
        [
            {
                "link_key": lk1,
                "saved_body": sb1,
                "filename": "BILLS-118hres100rh.pdf",
                "document_kind": ["legislation"],
                "committee_keys": ["hsru00"],
                "congress": 118,
                "document_date": "2023-03-10",
                "measure_keys": ["118-hres-100"],
                "url": "https://rules.house.gov/bill/118/hres-100",
                "selected_text": "118TH CONGRESS 1ST SESSION H. RES. 100 Providing for consideration...",
            },
            {
                "link_key": lk2,
                "saved_body": sb2,
                "filename": "HHRG-118-JU00-Wstate-DoeJ-20230510.pdf",
                "document_kind": ["witness-statement"],
                "committee_keys": ["hsju00"],
                "congress": 118,
                "document_date": "2023-05-10",
                "witness_keys": ["wk-doe"],
                "url": "https://docs.house.gov/meetings/JU/JU00/20230510/115000/HHRG-118-JU00-Wstate-DoeJ-20230510.pdf",
                "selected_text": "Statement of Dr. Jane Doe before the Committee on the Judiciary",
            },
            {
                "link_key": lk3,
                "saved_body": sb1,
                "filename": "BILLS-118hres100rh-copy.pdf",
                "document_kind": ["legislation"],
                "committee_keys": ["hsru00"],
                "congress": 118,
                "document_date": "2023-03-10",
                "measure_keys": ["118-hres-100"],
                "url": "https://rules.house.gov/bill/118/hres-100-copy",
            },
        ],
        witness_keys=["wk-doe"],
        bill_ids=["118-hres-100"],
    )

    _write_docmeta_fixture(
        dmdir,
        completed=[
            {
                "link_key": lk1,
                "doc_key": _doc_key_for_lk(lk1),
                "saved_body": sb1,
                "package_id": "BILLS-118hres100rh",
                "disposition": "upstream_spicydocs",
                "v6_route": "zero_llm_complete",
                "zero_llm_source": "spicydocs_bills_parquet_bill_or_draft",
                "filename": "BILLS-118hres100rh.pdf",
                "effective_format": "pdf",
                "primary_kind": "bill_or_draft",
                "status": "usable",
                "congress": 118,
                "chamber": "house",
                "committees": ["House Committee on Rules"],
                "docmeta_json": json.dumps(
                    {
                        "status": "usable",
                        "primary_kind": "bill_or_draft",
                        "congress": 118,
                        "chamber": "house",
                        "committees": ["House Committee on Rules"],
                        "refs": ["H. Res. 100"],
                    }
                ),
                "strict_v4_valid": True,
            }
        ],
        queue=[
            {
                "link_key": lk2,
                "doc_key": _doc_key_for_lk(lk2),
                "saved_body": sb2,
                "package_id": None,
                "disposition": "target_extractable",
                "v6_route": "llm_locked_kind",
                "filename": "HHRG-118-JU00-Wstate-DoeJ-20230510.pdf",
                "effective_format": "pdf",
                "text_source": "sraw_p12",
                "p12_raw_text": "Statement of Dr. Jane Doe",
                "p12_clean_text": "Statement of Dr. Jane Doe",
                "locked_primary_kind": "witness_statement",
                "grammar_lock_source": "cover_lock",
            }
        ],
        aliases=[
            {
                "link_key": lk3,
                "doc_key": _doc_key_for_lk(lk3),
                "saved_body": sb1,
                "package_id": "BILLS-118hres100rh",
                "disposition": "sha_dup_alias",
                "sub_disposition": "duplicate_of_completed",
                "v6_route": "sha_dup_alias",
                "filename": "BILLS-118hres100rh-copy.pdf",
                "effective_format": "pdf",
                "canonical_link_key": lk1,
                "canonical_doc_key": _doc_key_for_lk(lk1),
                "canonical_partition_bucket": "completed_no_llm",
                "canonical_v6_route": "zero_llm_complete",
            }
        ],
    )

    rows = load_corpus_rows(tdir, docmeta_dir=dmdir)
    assert len(rows) == 3
    assert rows[2].is_alias is True
    assert rows[2].docmeta_primary_kind == "bill_or_draft"

    rep = validate_dataset_provenance(tdir, docmeta_dir=dmdir, rows=rows)
    assert rep.passed_gate is True
    assert rep.docmeta_conservation_summary is not None
    assert rep.docmeta_conservation_summary["conserved_exact"] is True
    assert rep.hsru00_summary["docmeta_hsru_floor_author_leaks"] == 0


def test_provenance_validator_catches_leaks_traps_boundaries_and_conservation_faults(tmp_path: Path) -> None:
    tdir = tmp_path / "bad_published"
    dmdir = tmp_path / "bad_docmeta"
    lk1, lk2, lk3 = _lk_bytes(10), _lk_bytes(11), _lk_bytes(12)
    sb1, sb2, sb3 = _sb_bytes("bad1"), _sb_bytes("bad2"), _sb_bytes("bad3")

    _write_release_fixture(
        tdir,
        [
            # Row 0: Rules Committee Print floor-hosted HR bill misattributed to Rules + Wayback crawl date leak
            {
                "link_key": lk1,
                "saved_body": sb1,
                "filename": "BILLS-116hr5000ih.pdf",
                "document_kind": ["legislation"],
                "committee_keys": ["hsru00"],
                "congress": 116,
                "document_date": "2024-07-19",
                "date_kind": "captured",
                "document_date_status": "accepted",
                "document_date_source": "url",
                "measure_keys": ["116-hr-9999-missing"],
                "url": "https://web.archive.org/web/20240719081500/https://docs.house.gov/billsthisweek/20191028/BILLS-116hr5000ih.pdf",
                "selected_text": "RULES COMMITTEE PRINT 116-35\nText of H.R. 5000",
            },
            # Row 1: Odd-year Jan 2 Noon-Jan-3 off-by-one (2021-01-02 is 116th Congress, NOT 117th!) + CMS upload date leak + persona shortfall + orphan witness
            {
                "link_key": lk2,
                "saved_body": sb2,
                "filename": "HHRG-116-VR00-TTF-SmithA-20210102.pdf",
                "document_kind": ["testimony-disclosure"],
                "committee_keys": [],
                "congress": 117,
                "document_date": "2021-01-02",
                "date_kind": "captured",
                "document_date_status": "accepted",
                "witness_keys": ["wk-missing"],
                "url": "https://veterans.house.gov/wp-content/uploads/2024/08/HHRG-116-VR00-TTF-SmithA-20210102.pdf",
                "selected_text": "Truth in Testimony Disclosure Form",
            },
            # Row 2: Invalid Congress (> 130) + unreferenced row missing from docmeta partitions
            {
                "link_key": lk3,
                "saved_body": sb3,
                "filename": "BILLS-1152823ih.pdf",
                "document_kind": ["legislation"],
                "committee_keys": [],
                "congress": 1152,
                "document_date": "2017-06-08",
                "url": "https://naturalresources.house.gov/files/BILLS-1152823ih.pdf",
            },
        ],
        witness_keys=["wk-valid-only"],
        bill_ids=["116-hr-5000"],
    )

    # Deliberately omit lk3 from partitions (conservation failure) & point alias to non-existent canonical lk
    _write_docmeta_fixture(
        dmdir,
        completed=[
            {
                "link_key": lk1,
                "doc_key": _doc_key_for_lk(lk1),
                "saved_body": sb1,
                "package_id": None,
                "disposition": "target_extractable",
                "v6_route": "zero_llm_complete",
                "zero_llm_source": "test",
                "filename": "BILLS-116hr5000ih.pdf",
                "effective_format": "pdf",
                "primary_kind": "bill_or_draft",
                "status": "usable",
                "congress": 117,  # Mismatches BILLS-116 slug!
                "chamber": "house",
                "committees": ["House Committee on Rules"],
                "docmeta_json": json.dumps(
                    {
                        "status": "usable",
                        "primary_kind": "bill_or_draft",
                        "doc_date": "2024-07-19",
                        "congress": 117,
                        "committees": ["House Committee on Rules"],
                        "refs": [],
                    }
                ),
                "strict_v4_valid": True,
            },
            {
                "link_key": lk2,
                "doc_key": _doc_key_for_lk(lk2),
                "saved_body": sb2,
                "package_id": None,
                "disposition": "target_extractable",
                "v6_route": "zero_llm_complete",
                "zero_llm_source": "test",
                "filename": "HHRG-116-VR00-TTF-SmithA-20210102.pdf",
                "effective_format": "pdf",
                "primary_kind": "truth_in_testimony_disclosure",
                "status": "usable",
                "congress": 117,  # Off-by-one on 2021-01-02!
                "chamber": "house",
                "committees": ["House Committee on Veterans' Affairs"],
                "docmeta_json": json.dumps(
                    {
                        "status": "usable",
                        "primary_kind": "truth_in_testimony_disclosure",
                        "doc_date": "2024-08-15",  # Leaked /wp-content/uploads/2024/08/!
                        "congress": 117,
                        "personas": [],
                    }
                ),
                "strict_v4_valid": False,  # Invalid strict_v4_valid!
            },
        ],
        queue=[],
        aliases=[
            {
                "link_key": _lk_bytes(99),  # Orphan link_key + broken canonical target!
                "doc_key": _doc_key_for_lk(_lk_bytes(99)),
                "saved_body": sb3,
                "package_id": None,
                "disposition": "sha_dup_alias",
                "sub_disposition": "dup",
                "v6_route": "sha_dup_alias",
                "filename": "orphan.pdf",
                "effective_format": "pdf",
                "canonical_link_key": _lk_bytes(888),
                "canonical_doc_key": _doc_key_for_lk(_lk_bytes(888)),
                "canonical_partition_bucket": "completed_no_llm",
                "canonical_v6_route": "zero_llm_complete",
            }
        ],
    )

    rep = validate_dataset_provenance(tdir, docmeta_dir=dmdir)
    assert rep.passed_gate is False
    codes = {f.code for f in rep.findings}
    assert "prov_hsru00_floor_author_leak" in codes
    assert "prov_wayback_crawl_date_leak" in codes
    assert "prov_cms_upload_folder_date_leak" in codes
    assert "prov_bills_slug_congress_mismatch" in codes
    assert "prov_invalid_congress_range" in codes
    assert "prov_orphan_witness_key" in codes
    assert "prov_witness_persona_shortfall" in codes
    assert "prov_orphan_measure_key" in codes
    assert "prov_bill_measure_ref_shortfall" in codes
    assert "docmeta_orphan_link_key" in codes
    assert "docmeta_broken_sha_dup_alias_target" in codes
    assert "docmeta_invalid_or_null_record" in codes


def test_end_to_end_corpus_quality_audit_cli_and_bio_override(tmp_path: Path) -> None:
    base_dir = tmp_path / "base_tables"
    cand_dir = tmp_path / "cand_tables"
    dm_dir = tmp_path / "docmeta_v6_1"

    records: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    queue: list[dict[str, Any]] = []

    # 6 genuine biographies
    for i in range(6):
        lk = _lk_bytes(100 + i)
        sb = _sb_bytes(f"bio-{i}")
        fn = f"HHRG-118-JU00-Bio-Witness{i}-20230510.pdf"
        txt = (
            f"BIOGRAPHY OF DR. WITNESS {i}\n"
            "Professor of Law at Georgetown University. Ph.D. Harvard, B.A. Yale. "
            "Published extensively on constitutional law and federal courts."
        )
        records.append(
            {
                "link_key": lk,
                "saved_body": sb,
                "filename": fn,
                "document_kind": ["witness-biography"],
                "committee_keys": ["hsju00"],
                "congress": 118,
                "url": f"https://docs.house.gov/meetings/JU/JU00/20230510/115000/{fn}",
                "selected_text": txt,
            }
        )
        queue.append(
            {
                "link_key": lk,
                "doc_key": _doc_key_for_lk(lk),
                "saved_body": sb,
                "package_id": None,
                "disposition": "target_extractable",
                "v6_route": "llm_locked_kind",
                "filename": fn,
                "effective_format": "pdf",
                "text_source": "sraw_p12",
                "p12_raw_text": txt,
                "p12_clean_text": txt,
                "locked_primary_kind": "witness_biography",
                "grammar_lock_source": "bio_confirmed",
            }
        )

    # 6 genuine Truth-in-Testimony disclosures + 2 mislabeled `-Bio-` files that are actually TTFs!
    for i in range(8):
        lk = _lk_bytes(200 + i)
        sb = _sb_bytes(f"ttf-{i}")
        is_mislabeled_bio = i >= 6
        fn = (
            f"HHRG-118-JU00-Bio-Mislabeled{i}-20230510.pdf"
            if is_mislabeled_bio
            else f"HHRG-118-JU00-TTF-Witness{i}-20230510.pdf"
        )
        txt = (
            "TRUTH IN TESTIMONY DISCLOSURE FORM\n"
            "118th Congress\n"
            "False Statements Act Certification under 18 U.S.C. 1001.\n"
            "Witness Disclosure Requirement — nongovernmental entity federal grants and contracts."
        )
        records.append(
            {
                "link_key": lk,
                "saved_body": sb,
                "filename": fn,
                "document_kind": ["witness-biography"] if is_mislabeled_bio else ["testimony-disclosure"],
                "committee_keys": ["hsju00"],
                "congress": 118,
                "url": f"https://docs.house.gov/meetings/JU/JU00/20230510/115000/{fn}",
                "selected_text": txt,
            }
        )
        completed.append(
            {
                "link_key": lk,
                "doc_key": _doc_key_for_lk(lk),
                "saved_body": sb,
                "package_id": None,
                "disposition": "target_extractable",
                "v6_route": "zero_llm_complete",
                "zero_llm_source": "zero_llm_truth_in_testimony_disclosure",
                "filename": fn,
                "effective_format": "pdf",
                "primary_kind": "truth_in_testimony_disclosure",
                "status": "usable",
                "congress": 118,
                "chamber": "house",
                "committees": ["House Committee on the Judiciary"],
                "docmeta_json": json.dumps(
                    {
                        "status": "usable",
                        "primary_kind": "truth_in_testimony_disclosure",
                        "congress": 118,
                        "chamber": "house",
                        "committees": ["House Committee on the Judiciary"],
                        "personas": [{"name": f"Witness {i}"}],
                    }
                ),
                "strict_v4_valid": True,
            }
        )

    # 4 unmapped tail notices so tail_clusters forms a clean cluster
    for i in range(4):
        lk = _lk_bytes(300 + i)
        sb = _sb_bytes(f"tail-{i}")
        fn = f"notice_{i}.pdf"
        txt = (
            "NOTICE OF FULL COMMITTEE HEARING\n"
            "COMMITTEE ON OVERSIGHT AND ACCOUNTABILITY\n"
            "118th Congress\n"
            "DATE: May 16, 2024\nTIME: 10:00 a.m.\nPLACE: 2154 Rayburn House Office Building"
        )
        records.append(
            {
                "link_key": lk,
                "saved_body": sb,
                "filename": fn,
                "document_kind": ["other"],
                "committee_keys": [],
                "congress": 118,
                "url": f"https://oversight.house.gov/hearing/{fn}",
                "selected_text": txt,
            }
        )
        queue.append(
            {
                "link_key": lk,
                "doc_key": _doc_key_for_lk(lk),
                "saved_body": sb,
                "package_id": None,
                "disposition": "target_extractable",
                "v6_route": "llm_open_kind",
                "filename": fn,
                "effective_format": "pdf",
                "text_source": "sraw_p12",
                "p12_raw_text": txt,
                "p12_clean_text": txt,
                "locked_primary_kind": None,
                "grammar_lock_source": None,
            }
        )

    _write_release_fixture(base_dir, records[:14])
    _write_release_fixture(cand_dir, records)
    _write_docmeta_fixture(dm_dir, completed=completed, queue=queue, aliases=[])

    out_json = tmp_path / "out" / "report.json"
    out_md = tmp_path / "out" / "report.md"
    out_pkt = tmp_path / "out" / "packet.json"

    rc = audit_cli.main(
        [
            "--tables",
            str(cand_dir),
            "--docmeta-dir",
            str(dm_dir),
            "--base-tables",
            str(base_dir),
            "--seed",
            "20261116",
            "--per-stratum",
            "4",
            "--output-json",
            str(out_json),
            "--output-md",
            str(out_md),
            "--audit-packet-out",
            str(out_pkt),
            "--strict-gate",
        ]
    )
    assert rc == 0
    assert out_json.is_file()
    assert out_md.is_file()
    assert out_pkt.is_file()

    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert report["provenance_gate_passed"] is True
    assert report["release_gate"]["passed"] is True
    assert report["provenance"]["docmeta_conservation_summary"]["conserved_exact"] is True
    assert report["tail_clusters"]["target_tail_rows"] >= 4
    assert len(report["tail_clusters"]["clusters"]) >= 1

    md_text = out_md.read_text(encoding="utf-8")
    assert "# Corpus Quality & Dataset Validation Report" in md_text
    assert "## 3. Unmapped-Tail & Emergent-Template Clustering" in md_text

    pkt = json.loads(out_pkt.read_text(encoding="utf-8"))
    assert pkt["seed"] == 20261116
    assert pkt["total_rows"] == 18
    assert pkt["sample_size"] > 0
