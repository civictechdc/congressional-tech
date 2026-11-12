"""Unit tests for witness_ranks_credentials_raw_check.py across all 4 sources and both directions."""
from __future__ import annotations

import gzip
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "witness_ranks_credentials_raw_check",
    ROOT / "scripts/measure/witness_ranks_credentials_raw_check.py",
)
check = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(check)


def _write_body(raw_root: Path, payload: bytes) -> str:
    digest = sha256(payload).hexdigest()
    target = raw_root / digest[:2] / f"{digest}.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(gzip.compress(payload))
    return digest


def _occ(locator: str, name: str | None, *, rank: str | None = None, credentials: str | None = None) -> dict:
    return {
        "source_locator": locator,
        "name": name,
        "rank": rank,
        "credentials": credentials,
        "position": "Director",
        "organization": "Example Agency",
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    raw_root = tmp_path / "raw"
    receipts_root = tmp_path / "receipts"
    receipts_root.mkdir(parents=True, exist_ok=True)

    mods_sha = _write_body(
        raw_root,
        (
            b'<mods xmlns="http://www.loc.gov/mods/v3">'
            b"<witness>Lieutenant General Paul M. Nakasone, USA, Commander</witness>"
            b"<witness>Bhattacharya, Jay, M.D., Ph.D., Professor, Stanford University</witness>"
            b"<witness>Garrett, Major, Chief Washington Correspondent</witness>"
            b"</mods>"
        ),
    )
    senate_sha = _write_body(
        raw_root,
        b"<html><body><h3>Rear Admiral Nancy Knight, M.D., USPHS (Ret.)</h3><div>Director</div></body></html>",
    )
    house_sha = _write_body(
        raw_root,
        (
            b"<committee-meeting><witnesses>"
            b"<witness><first-name>COLONEL JOHN</first-name><last-name>SMITH</last-name>"
            b"<suffix>USAF (Ret.)</suffix></witness>"
            b"</witnesses></committee-meeting>"
        ),
    )
    cgov_line = json.dumps(
        {"witnesses": [{"name": "The Honorable Robert Califf, M.D."}]},
    ).encode()
    cgov_sha = sha256(cgov_line).hexdigest()
    (receipts_root / "batch.jsonl.gz").write_bytes(gzip.compress(cgov_line + b"\n"))

    before_rows = [
        {
            "source": "mods",
            "record_sha": bytes.fromhex(mods_sha),
            "package_id": "CHRG-1",
            "event_id": None,
            "appearances": [
                _occ("mods:witness[1]", "Paul M. Nakasone"),
                _occ("mods:witness[2]", "Jay Bhattacharya"),
                _occ("mods:witness[3]", "Major Garrett"),
            ],
        },
        {
            "source": "senate_page",
            "record_sha": bytes.fromhex(senate_sha),
            "package_id": None,
            "event_id": None,
            "appearances": [_occ("senate_page:witness[1]", "Nancy Knight")],
        },
        {
            "source": "house_xml",
            "record_sha": bytes.fromhex(house_sha),
            "package_id": None,
            "event_id": "118001",
            "appearances": [_occ("house_xml:witness[1]", "COLONEL JOHN SMITH")],
        },
        {
            "source": "congress_gov",
            "record_sha": bytes.fromhex(cgov_sha),
            "package_id": None,
            "event_id": "118002",
            "appearances": [_occ("congress_gov:witness[1]", "The Honorable Robert Califf, M.D.")],
        },
    ]

    after_rows = [
        {
            "source": "mods",
            "record_sha": bytes.fromhex(mods_sha),
            "package_id": "CHRG-1",
            "event_id": None,
            "appearances": [
                _occ("mods:witness[1]", "Paul M. Nakasone", rank="Lieutenant General", credentials="USA"),
                _occ("mods:witness[2]", "Jay Bhattacharya", credentials="M.D., Ph.D."),
                _occ("mods:witness[3]", "Major Garrett"),
            ],
        },
        {
            "source": "senate_page",
            "record_sha": bytes.fromhex(senate_sha),
            "package_id": None,
            "event_id": None,
            "appearances": [
                _occ("senate_page:witness[1]", "Nancy Knight", rank="Rear Admiral", credentials="M.D., USPHS (Ret.)")
            ],
        },
        {
            "source": "house_xml",
            "record_sha": bytes.fromhex(house_sha),
            "package_id": None,
            "event_id": "118001",
            "appearances": [_occ("house_xml:witness[1]", "JOHN SMITH", rank="COLONEL", credentials="USAF (Ret.)")],
        },
        {
            "source": "congress_gov",
            "record_sha": bytes.fromhex(cgov_sha),
            "package_id": None,
            "event_id": "118002",
            "appearances": [_occ("congress_gov:witness[1]", "Robert Califf", credentials="M.D.")],
        },
    ]

    before_pq = tmp_path / "before.parquet"
    after_pq = tmp_path / "after.parquet"
    pq.write_table(pa.Table.from_pylist(before_rows), before_pq)
    pq.write_table(pa.Table.from_pylist(after_rows), after_pq)
    return before_pq, after_pq, raw_root, receipts_root


def test_clean_four_source_extraction_passes_and_preserves_given_name_major(tmp_path: Path) -> None:
    before_pq, after_pq, raw_root, receipts_root = _fixture(tmp_path)
    out_json = tmp_path / "out.json"
    rc = check.main(
        [
            "--before", str(before_pq),
            "--after", str(after_pq),
            "--raw-root", str(raw_root),
            "--receipts-root", str(receipts_root),
            "--output", str(out_json),
        ]
    )
    res = json.loads(out_json.read_text())
    assert rc == 0 and res["status"] == "passed"
    assert res["counts"]["totals"] == {
        "records": 4,
        "occurrences": 6,
        "rank": 3,
        "credentials": 5,
        "removed": 0,
    }


@pytest.mark.parametrize(
    ("plant_kind", "expected_flag"),
    [
        ("rank-in-name", "rank_in_name"),
        ("credential-dropped", "credential_dropped"),
        ("ungrounded-rank", "rank_not_in_raw"),
        ("ungrounded-credential", "credential_not_in_raw"),
    ],
)
def test_each_plant_is_flagged_in_both_directions(tmp_path: Path, plant_kind: str, expected_flag: str) -> None:
    before_pq, after_pq, raw_root, receipts_root = _fixture(tmp_path)
    out_json = tmp_path / "out.json"
    rc = check.main(
        [
            "--before", str(before_pq),
            "--after", str(after_pq),
            "--raw-root", str(raw_root),
            "--receipts-root", str(receipts_root),
            "--output", str(out_json),
            "--plant", plant_kind,
        ]
    )
    res = json.loads(out_json.read_text())
    assert rc == 1 and res["status"] == "failed"
    assert res["planted"][0]["flagged"] is True
    assert res["failed"][expected_flag] >= 1


def test_civil_title_in_rank_suffix_in_credentials_and_removals_fail(tmp_path: Path) -> None:
    before_pq, after_pq, raw_root, receipts_root = _fixture(tmp_path)
    rows = pq.read_table(after_pq).to_pylist()
    rows[0]["appearances"][0]["rank"] = "The Honorable"
    rows[0]["appearances"][1]["credentials"] = "Jr."
    rows[0]["appearances"].pop(2)  # drop Major Garrett -> removal!
    pq.write_table(pa.Table.from_pylist(rows), after_pq)

    out_json = tmp_path / "out.json"
    rc = check.main(
        [
            "--before", str(before_pq),
            "--after", str(after_pq),
            "--raw-root", str(raw_root),
            "--receipts-root", str(receipts_root),
            "--output", str(out_json),
        ]
    )
    res = json.loads(out_json.read_text())
    assert rc == 1
    assert res["failed"]["civil_title_in_rank"] == 1
    assert res["failed"]["suffix_in_credentials"] == 1
    assert res["failed"]["removed"] == 1
