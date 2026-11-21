"""Regression tests for DocMeta remediation tickets `ct-s9l2`, `ct-2cig`, `ct-pzaz`, and `ct-0zry`."""

from __future__ import annotations

import datetime
import gzip
import json
from pathlib import Path
import subprocess
import sys

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.lake.meeting_records import _HOUSE_SELECT_CODES, normalize_house_committee_code
from house_naming import load_guide

from congress_docmeta import (
    DEFAULT_DOCMETA_BATCH_SIZE,
    DEFAULT_MLX_CACHE_LIMIT_GB,
    DEFAULT_MLX_MEMORY_LIMIT_GB,
    HOUSE_CLERK_2LETTER_TO_CODE,
    apply_mlx_limits,
    build_release_sidecar,
    cli as docmeta_cli,
    cover_locks_v6 as cl6,
    eval_blind as eb,
    gold,
    mlx_limits_scope,
    provenance_rules_v5 as pr5,
    pythonic_v6 as pv6,
    relational_rules_v6 as rv6,
    resolve_default_docmeta_batch_size,
    resolve_default_mlx_limits,
    strict_validate_v4,
)


def test_mlx_limits_scope_and_cli_defaults():
    """`ct-s9l2` + 24 GiB Base M5 auto-sizing: omitted flags auto-size at runtime; explicit overrides win."""
    ev_args = eb.build_parser().parse_args(["--out", "/tmp/unused.json"])
    assert ev_args.memory_limit_gb is None
    assert ev_args.cache_limit_gb is None
    assert ev_args.b_slots is None

    sw_args = docmeta_cli.build_parser().parse_args(["docmeta-sweep", "in.parquet", "out.parquet"])
    assert sw_args.memory_limit_gb is None
    assert sw_args.cache_limit_gb is None
    assert sw_args.b_slots is None

    # Explicit overrides win unconditionally (and `--batch-size` aliases `--b-slots`).
    sw_over = docmeta_cli.build_parser().parse_args(
        ["docmeta-sweep", "in.parquet", "out.parquet", "--memory-limit-gb", "20.0", "--cache-limit-gb", "1.5", "--batch-size", "128"]
    )
    assert sw_over.memory_limit_gb == 20.0
    assert sw_over.cache_limit_gb == 1.5
    assert sw_over.b_slots == 128

    assert resolve_default_mlx_limits(24) == (19.2, 1.5)
    assert resolve_default_mlx_limits(16) == (12.8, 1.5)
    assert resolve_default_mlx_limits(48) == (DEFAULT_MLX_MEMORY_LIMIT_GB, DEFAULT_MLX_CACHE_LIMIT_GB) == (24.0, 2.0)
    assert resolve_default_mlx_limits(0) == (DEFAULT_MLX_MEMORY_LIMIT_GB, DEFAULT_MLX_CACHE_LIMIT_GB) == (24.0, 2.0)
    assert resolve_default_docmeta_batch_size(24) == 128
    assert resolve_default_docmeta_batch_size(48) == DEFAULT_DOCMETA_BATCH_SIZE == 256
    assert resolve_default_docmeta_batch_size(0) == DEFAULT_DOCMETA_BATCH_SIZE == 256

    class FakeMX:
        def __init__(self) -> None:
            self.mem = 48 << 30
            self.cache = 16 << 30
            self.calls: list[tuple[str, int]] = []

        def set_memory_limit(self, val: int) -> int:
            prev, self.mem = self.mem, int(val)
            self.calls.append(("mem", int(val)))
            return prev

        def set_cache_limit(self, val: int) -> int:
            prev, self.cache = self.cache, int(val)
            self.calls.append(("cache", int(val)))
            return prev

    fake = FakeMX()
    with mlx_limits_scope(memory_limit_gb=24.0, cache_limit_gb=2.0, mx_module=fake) as applied:
        assert applied["memory_limit_bytes"] == 24 << 30
        assert applied["cache_limit_bytes"] == 2 << 30
        assert fake.mem == 24 << 30
        assert fake.cache == 2 << 30
    assert fake.mem == 48 << 30
    assert fake.cache == 16 << 30

    disabled = apply_mlx_limits(memory_limit_gb=0.0, cache_limit_gb=-1.0, mx_module=fake)
    assert disabled["memory_limit_bytes"] is None
    assert disabled["cache_limit_bytes"] is None


def test_r4_vice_chair_and_comma_name_dedup():
    """`ct-2cig` Item 1: Vice/Co-Chairs are never labeled `chair`, and comma suffixes do not duplicate personas."""
    assert rv6.salutation_chair_personas_v6(
        "Thank you, Vice Chairman Feinstein and Members of the Subcommittee."
    ) == []
    assert rv6.salutation_chair_personas_v6(
        "Good morning Chairman Pallone, Vice Chairman John Barrasso, and Ranking Member Rodgers."
    ) == [("chair", "Pallone"), ("ranking_member", "Rodgers")]

    existing = [
        {"name": "Rebecca Thompson", "role": "witness", "entity_type": "non_gov_person"},
        {"name": "Bill Pascrell, Jr.", "role": "chair", "entity_type": "member"},
    ]
    merged = rv6.add_text_grounded_personas_v6(
        existing,
        primary_kind="witness_statement",
        text="Chairman Pascrell, Ranking Member Kelly, thank you for the opportunity to testify.",
        additive_only=True,
    )
    assert [p["name"] for p in merged] == ["Rebecca Thompson", "Bill Pascrell, Jr.", "Kelly"]

    letter = [{"name": "Robert S. Mueller, III", "role": "recipient", "entity_type": "gov_official"}]
    merged_letter = rv6.add_text_grounded_personas_v6(
        letter,
        primary_kind="oversight_letter",
        text="The Honorable Robert S. Mueller, III\nDirector, Federal Bureau of Investigation",
        additive_only=True,
    )
    assert len(merged_letter) == 1


def test_r7_subcommittee_lookup_uses_half_open_congress_bounds():
    """`ct-2cig` Item 2: `start_year < y_end` and `end_year > y_start` keeps 118th subcommittees renamed in 2025."""
    lookup = {
        "subcommittees_meta": {
            "hsag03": {
                "name": "House Subcommittee on Nutrition and Foreign Agriculture",
                "names": [
                    {"name": "House Subcommittee on Nutrition and Foreign Agriculture", "start_year": 2025, "end_year": None},
                    {"name": "House Subcommittee on Nutrition, Foreign Agriculture, and Horticulture", "start_year": 2023, "end_year": 2025},
                    {"name": "Subcommittee on Nutrition, Oversight, and Department Operations", "start_year": 2019, "end_year": 2023},
                ],
            }
        }
    }
    assert (
        rv6.subcommittee_code_to_canonical_v6("hsag03", congress=118, lookup=lookup)
        == "House Subcommittee on Nutrition, Foreign Agriculture, and Horticulture"
    )
    assert (
        rv6.subcommittee_code_to_canonical_v6("hsag03", congress=117, lookup=lookup)
        == "Subcommittee on Nutrition, Oversight, and Department Operations"
    )
    kept = rv6.ground_subcommittees_v6(
        ["Subcommittee on Nutrition, Foreign Agriculture, and Horticulture"],
        text="Testimony before the House Committee on Agriculture.",
        committee_codes=["hsag03"],
        congress=118,
        lookup=lookup,
    )
    assert kept == ["Subcommittee on Nutrition, Foreign Agriculture, and Horticulture"]


def test_govinfo_chrg_and_cover_lock_misfire_guards():
    """`ct-2cig` Item 3: CECC annual-report reprints and markup transcripts do not receive wrong genre locks."""
    cecc_text = (
        "U.S. GOVERNMENT PRINTING OFFICE\nWORKER RIGHTS\nREPRINTED FROM THE 2007 ANNUAL REPORT OF THE "
        "CONGRESSIONAL-EXECUTIVE COMMISSION ON CHINA\nONE HUNDRED TENTH CONGRESS"
    )
    lid, lpk, lsrc = cl6.resolve_govinfo_pkg_lock_v6(
        "CHRG-110jhrg40482", ["published-hearing"], filename="CHRG-110jhrg40482.pdf", text=cecc_text
    )
    assert (lid, lpk, lsrc) == ("govinfo_chrg_reprint_report_v6", "committee_report", "govinfo_chrg_reprint_report_v6")
    assert cl6.reconcile_queue_lock_v6(
        "hearing_transcript", "govinfo_chrg_pkg_lock", "govinfo_chrg_pkg_lock",
        filename="CHRG-110jhrg40482.pdf", text=cecc_text,
    )[0] == "committee_report"

    # Real hearing on an annual report stays `hearing_transcript`
    irs_hearing = "1998 ANNUAL REPORT OF THE INTERNAL REVENUE SERVICE TAXPAYER ADVOCATE\nHEARING BEFORE THE SUBCOMMITTEE ON OVERSIGHT"
    assert cl6.resolve_govinfo_pkg_lock_v6(
        "CHRG-105hhrg49634", ["published-hearing"], filename="CHRG-105hhrg49634.pdf", text=irs_hearing
    )[1] == "hearing_transcript"

    # Markup transcript of an oversight plan is NOT locked to `oversight_plan`
    markup_txt = (
        "Diversified Reporting Services, Inc.\nRPTS EUELL\nMARKUP OF AUTHORIZATION AND OVERSIGHT PLAN OF THE "
        "COMMITTEE ON ENERGY AND COMMERCE, 119TH CONGRESS\nThe committee met, pursuant to call, at 10:37 a.m."
    )
    assert cl6.detect_cover_lock_v6(filename="HMKP-119-IF00-Transcript-20250225.pdf", text=markup_txt) == (None, None, None)
    assert cl6.reconcile_queue_lock_v6(
        "oversight_plan", "cover_lock_v6", "oversight_plan_cover_v6",
        filename="HMKP-119-IF00-Transcript-20250225.pdf", text=markup_txt,
    ) == (None, None, None)

    # Press release with `letter_of_support` in link/filename is not locked to `nomination_or_support_letter`
    pr_txt = "NEWSROOM\nFOR IMMEDIATE RELEASE\nNAB Congratulates Adam Candeub on DOJ Antitrust Nomination"
    assert pr5.detect_provenance_link_anchor(
        ["Letter of Support"], filename="candeub_letter_of_support_-_nap_press_release.pdf", text=pr_txt
    )[:2] == (None, None)


def test_eval_blind_scorer_fixes_and_legacy_side_by_side():
    """`ct-2cig` Item 4: role-aware dates, false-positive scalars, normalized subcommittees, and 1-to-1 personas."""
    base = {"status": "usable", "primary_kind": "witness_statement", "chamber": "house"}

    # 1. Wrong person with same surname scores 0; two Smiths predicted once scores 66.7 (not 100)
    s_wrong_first = eb.score(
        [{**base, "personas": [{"name": "Jane Smith", "role": "witness", "entity_type": "non_gov_person"}]}],
        [{**base, "personas": [{"name": "John Smith", "role": "witness", "entity_type": "non_gov_person"}]}],
        [True],
    )["metrics"]
    assert s_wrong_first["personas_name_f1"] == 0.0

    s_two_smiths = eb.score(
        [{**base, "personas": [{"name": "John Smith", "role": "witness", "entity_type": "member"}]}],
        [{**base, "personas": [
            {"name": "John Smith", "role": "witness", "entity_type": "member"},
            {"name": "Adam Smith", "role": "witness", "entity_type": "member"},
        ]}],
        [True],
    )["metrics"]
    assert s_two_smiths["personas_name_f1"] == 66.7

    # 2. Accents, `Last, First`, `(R-TX)`, middle-initial `L. Dodaro`, and `Liz` <-> `Elizabeth` match cleanly
    for pn, gn in (
        ("Smith (R-TX)", "Lamar Smith"),
        ("Smith, Lamar", "Lamar Smith"),
        ("Lamar Smith, Chairman", "Lamar Smith"),
        ("Nydia Velazquez", "Nydia Velázquez"),
        ("Ben Ray Luján", "Ben Ray Lujan"),
        ("L. Dodaro", "Gene L. Dodaro"),
        ("Liz Dickinson", "Elizabeth Dickinson"),
    ):
        m = eb.score(
            [{**base, "personas": [{"name": pn, "role": "witness", "entity_type": "member"}]}],
            [{**base, "personas": [{"name": gn, "role": "witness", "entity_type": "member"}]}],
            [True],
        )["metrics"]
        assert m["personas_name_f1"] == 100.0, (pn, gn, m)

    # 3. Swapping `doc_date` and `event_date` scores 0 (legacy scored 100)
    pred_swapped = {**base, "doc_date": "2020-01-02", "event_date": "2020-01-05"}
    gold_swapped = {**base, "doc_date": "2020-01-05", "event_date": "2020-01-02"}
    assert eb.score([pred_swapped], [gold_swapped], [True])["metrics"]["dates_f1"] == 0.0
    assert eb.score_legacy([pred_swapped], [gold_swapped], [True])["metrics"]["dates_f1"] == 100.0

    # 4. Predicting `congress` when gold omits `congress` is penalized
    assert eb.score([{**base, "congress": 118}], [base], [True])["metrics"]["congress_acc"] == 0.0

    # 5. Subcommittee punctuation, `&`, and `the` normalize to 100.0
    assert eb.score(
        [{**base, "subcommittees": ["House Energy & Commerce Subcommittee on the Environment, Manufacturing & Critical Materials"]}],
        [{**base, "subcommittees": ["Subcommittee on Environment, Manufacturing, and Critical Materials"]}],
        [True],
    )["metrics"]["subcommittees_f1"] == 100.0


def test_single_committee_table_owner_and_no_hardcoded_user_paths():
    """`ct-pzaz`: single owner inside congress_docmeta, parity with house_naming & meeting_records, no `/Users/` literals."""
    assert pr5.HOUSE_CLERK_2LETTER_TO_CODE is rv6.HOUSE_CLERK_2LETTER_TO_CODE_V6
    assert HOUSE_CLERK_2LETTER_TO_CODE is rv6.HOUSE_CLERK_2LETTER_TO_CODE_V6
    for k, v in pv6.HOUSE_SELECT_2LETTER_EXTRA_V6.items():
        assert rv6.HOUSE_CLERK_2LETTER_TO_CODE_V6[k.upper()] == v

    # Every modern House select stem in `meeting_records._HOUSE_SELECT_CODES` maps identically in DocMeta
    for stem in _HOUSE_SELECT_CODES:
        assert rv6.HOUSE_CLERK_2LETTER_TO_CODE_V6[stem.upper()] == normalize_house_committee_code(stem)

    # Every 2-letter folder stem in `house_naming` guide (`XX00`) is mapped in DocMeta, and House stems match `normalize_house_committee_code`
    guide = load_guide()
    joint_or_comm = {"EC": "jsec00", "HL": "jcse00", "IT": "jstx00", "JL": "jslc00", "JP": "jspr00", "JR": "jsdf00"}
    for folder_code in guide["committees"]:
        if len(folder_code) == 4 and folder_code.endswith("00"):
            c2 = folder_code[:2].upper()
            assert c2 in rv6.HOUSE_CLERK_2LETTER_TO_CODE_V6
            if c2 in joint_or_comm:
                assert rv6.HOUSE_CLERK_2LETTER_TO_CODE_V6[c2] == joint_or_comm[c2]
            else:
                assert rv6.HOUSE_CLERK_2LETTER_TO_CODE_V6[c2] == normalize_house_committee_code(folder_code)

    src_root = Path(rv6.__file__).resolve().parent
    for py_file in src_root.rglob("*.py"):
        txt = py_file.read_text(encoding="utf-8")
        assert "/Users/mikewolfd" not in txt, f"Hardcoded user path in {py_file}"


def test_release_parameterized_sidecar_builder_and_stdlib_import(tmp_path: Path):
    """`ct-0zry`: `build_release_sidecar` builds the 3 sidecar parts for an arbitrary release with R4-R8 and conservation."""
    # 1. `/usr/bin/python3 -B -I -S` stdlib isolation check on `sidecar_builder`
    src_dir = str(Path(rv6.__file__).resolve().parents[1])
    proc = subprocess.run(
        ["/usr/bin/python3", "-B", "-I", "-S", "-c", f"import sys; sys.path.insert(0, {src_dir!r}); import congress_docmeta.sidecar_builder"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr

    # 2. Construct a synthetic 4-row release (1 TTF zero-LLM bypass w/ address, 1 open queue doc, 1 exact SHA dup, 1 excluded body)
    rel_dir = tmp_path / "release"
    rel_dir.mkdir()
    (rel_dir / "manifest.json").write_text(json.dumps({"release_id": "f" * 64}), encoding="utf-8")

    sb_ttf = b"\x01" * 32
    sb_open = b"\x02" * 32
    sb_excl = b"\x03" * 32

    detail_rows = [
        {
            "link_key": b"\x00" * 7 + b"\x01",
            "saved_body": sb_ttf,
            "saved_suffix": ".pdf",
            "saved_media_type": "application/pdf",
            "package_id": None,
            "description": None,
            "main_content": None,
            "selected_text": None,
            "filename": "HHRG-118-JU00-TTF-SmithJ-20230510.pdf",
            "title": "Truth in Testimony Disclosure Form - Jane Smith",
            "document_kind": ["truth-in-testimony"],
            "committee_keys": ["hsju00"],
            "chambers": ["house"],
            "congress": 118,
            "format": "pdf",
            "document_date": datetime.date(2023, 5, 10),
            "meeting_keys": ["118-house-1001"],
            "measure_keys": [],
            "bioguide_ids": [],
            "witness_keys": ["w-smith"],
        },
        {
            "link_key": b"\x00" * 7 + b"\x02",
            "saved_body": sb_open,
            "saved_suffix": ".pdf",
            "saved_media_type": "application/pdf",
            "package_id": "CHRG-110jhrg40482",
            "description": None,
            "main_content": None,
            "selected_text": None,
            "filename": "CHRG-110jhrg40482.pdf",
            "title": "Worker Rights Annual Report Reprint",
            "document_kind": ["published-hearing"],
            "committee_keys": ["jcpk00"],
            "chambers": ["joint"],
            "congress": 110,
            "format": "pdf",
            "document_date": datetime.date(2007, 10, 10),
            "meeting_keys": [],
            "measure_keys": [],
            "bioguide_ids": [],
            "witness_keys": [],
        },
        {
            "link_key": b"\x00" * 7 + b"\x03",
            "saved_body": sb_open,  # exact SHA duplicate of row 1 -> `sha_dup_alias`
            "saved_suffix": ".pdf",
            "saved_media_type": "application/pdf",
            "package_id": "CHRG-110jhrg40482",
            "description": None,
            "main_content": None,
            "selected_text": None,
            "filename": "CHRG-110jhrg40482-copy.pdf",
            "title": "Worker Rights Copy",
            "document_kind": ["published-hearing"],
            "committee_keys": ["jcpk00"],
            "chambers": ["joint"],
            "congress": 110,
            "format": "pdf",
            "document_date": datetime.date(2007, 10, 10),
            "meeting_keys": [],
            "measure_keys": [],
            "bioguide_ids": [],
            "witness_keys": [],
        },
        {
            "link_key": b"\x00" * 7 + b"\x04",
            "saved_body": sb_excl,
            "saved_suffix": ".html",
            "saved_media_type": "text/html",
            "package_id": None,
            "description": None,
            "main_content": None,
            "selected_text": None,
            "filename": "404.html",
            "title": "Page Not Found",
            "document_kind": [],
            "committee_keys": ["hsag00"],
            "chambers": ["house"],
            "congress": 118,
            "format": "html",
            "document_date": None,
            "meeting_keys": [],
            "measure_keys": [],
            "bioguide_ids": [],
            "witness_keys": [],
        },
    ]
    pq.write_table(pa.Table.from_pylist(detail_rows), rel_dir / "detail.parquet")
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "event_id": "118-house-1001",
                    "chamber": "house",
                    "title": "Oversight of Artificial Intelligence",
                    "meeting_date": datetime.date(2023, 5, 10),
                    "meeting_type": "Hearing",
                    "sittings": [{"room": "2141", "building": "Rayburn House Office Building", "address": None, "place": None}],
                    "committees": ["hsju00"],
                    "congress": 118,
                    "not_held": False,
                }
            ]
        ),
        rel_dir / "meetings.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "witness_key": "w-smith",
                    "name": "Ms. Jane Smith",
                    "rank": None,
                    "credentials": None,
                    "position": "Executive Director",
                    "organization": "Civic Policy Institute",
                    "on_behalf_of": None,
                    "location": "1200 Pennsylvania Avenue NW, Washington, DC 20004",
                    "panel": 1,
                    "panel_order": 1,
                    "witness_type": "Non-Government",
                    "bioguide_id": None,
                    "matched_bioguide_id": None,
                    "person_key": None,
                }
            ]
        ),
        rel_dir / "witnesses.parquet",
    )

    bt_dir = tmp_path / "ssot"
    bt_dir.mkdir()
    ttf_text = (
        "Enclosure 3\n"
        "Committee on the Judiciary\n"
        "U.S. House of Representatives\n"
        'Witness Disclosure Requirement - "Truth in Testimony"\n'
        "Required by House Rule XI, Clause 2(g)(5)\n"
        "1. Your Name:\n"
        "Jane Smith\n"
        "2. Are you testifying on behalf of the Federal, or a State or local government entity?\n"
        "No\n"
        "3. Are you testifying on behalf of an entity that is not a government entity?\n"
        "Yes\n"
        "Civic Policy Institute\n"
        "4. Other than yourself, please list which entity or entities you are representing:\n"
        "Civic Policy Institute\n"
        "5. Please list any Federal grants or contracts (including subgrants or subcontracts) "
        "that you or the entity(ies) you represent have received on or after October 1, 2020:\n"
        "None\n"
        "6. Signature of Witness: Jane Smith Date: 05/10/2023\n"
    )
    reprint_text = (
        "U.S. GOVERNMENT PRINTING OFFICE\nWORKER RIGHTS\n"
        "REPRINTED FROM THE 2007 ANNUAL REPORT OF THE CONGRESSIONAL-EXECUTIVE COMMISSION ON CHINA\n"
        "ONE HUNDRED TENTH CONGRESS"
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"saved_body": sb_ttf, "text": ttf_text, "page_offsets": [0]},
                {"saved_body": sb_open, "text": reprint_text, "page_offsets": [0]},
            ],
            schema=pa.schema([("saved_body", pa.binary(32)), ("text", pa.string()), ("page_offsets", pa.list_(pa.int32()))]),
        ),
        bt_dir / "export.parquet",
    )

    sel_gz = tmp_path / "selection.json.gz"
    sel_gz.write_bytes(
        gzip.compress(
            json.dumps(
                {"excluded_bodies": [{"body_sha256": sb_excl.hex(), "source_role": "error_response", "reason": "HTTP 404 shell"}]}
            ).encode("utf-8")
        )
    )

    out_dir = tmp_path / "sidecar_out"
    manifest = build_release_sidecar(rel_dir, out_dir, body_text_export_dir=bt_dir, selection_path=sel_gz)
    assert manifest["counts"] == {
        "total_rows": 4,
        "completed_no_llm": 2,
        "llm_queue": 1,
        "sha_dup_alias": 1,
    }

    comp = pq.read_table(out_dir / "completed_no_llm.parquet").to_pylist()
    assert len(comp) == 2
    for row in comp:
        ok, errs = strict_validate_v4(row["docmeta_json"])
        assert ok is True and not errs

    queue = pq.read_table(out_dir / "llm_queue.parquet").to_pylist()
    assert len(queue) == 1
    assert queue[0]["locked_primary_kind"] == "committee_report"
    assert queue[0]["grammar_lock_source"] == "govinfo_chrg_reprint_report_v6"

    alias = pq.read_table(out_dir / "sha_dup_alias.parquet").to_pylist()
    assert len(alias) == 1
    assert alias[0]["canonical_link_key_hex"] == (b"\x00" * 7 + b"\x02").hex()
    assert alias[0]["canonical_partition_bucket"] == "llm_queue"
