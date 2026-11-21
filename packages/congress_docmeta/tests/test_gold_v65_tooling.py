"""Tests for DocMeta V6.5 gold normalization, contract verification, SSOT loading, and review viewer (`ct-2uc9`)."""

from __future__ import annotations

import hashlib
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import types
import urllib.error
import urllib.request

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_docmeta import eval_blind, gold, training_pairs
from congress_docmeta.atomic_validator_v6 import resolve_docmeta_validators_dir
from congress_docmeta.gold_v65 import gold_contract as gc
from congress_docmeta.gold_v65 import gold_gate_v6_2 as gg
from congress_docmeta.gold_v65 import normalize_gold_v6_5 as ng
from congress_docmeta.gold_v65 import split_v65
from congress_docmeta.gold_v65.paths import (
    PACKAGE_DATA_DIR,
    resolve_docmeta_v6_data_dir,
    resolve_docmeta_v65_dir,
    resolve_package_fallback,
)
from congress_docmeta.gold_v65.viewer import build_bundle
from congress_docmeta.gold_v65.viewer.serve import make_handler


def test_v65_paths_and_packaged_metadata_resolve_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    explicit = resolve_docmeta_v65_dir(str(tmp_path / "custom_v65"))
    assert explicit == (tmp_path / "custom_v65").resolve()

    monkeypatch.setenv("DOCMETA_V65_DIR", str(tmp_path / "env_v65"))
    assert resolve_docmeta_v65_dir() == (tmp_path / "env_v65").resolve()
    monkeypatch.delenv("DOCMETA_V65_DIR", raising=False)
    monkeypatch.delenv("DOCMETA_VALIDATORS_DIR", raising=False)
    monkeypatch.delenv("DOCMETA_V6_DATA_DIR", raising=False)

    assert resolve_docmeta_v65_dir().name == "docmeta-v65-raretypes-20261118"
    assert resolve_docmeta_validators_dir() == resolve_docmeta_v6_data_dir() / "atomic_validators"

    missing_cache = tmp_path / "absent.json"
    for fname in (
        "docmeta_gold_conventions.schema.json",
        "adjudications.jsonl",
        "coordinator_adjudications.jsonl",
        "heldout_v6_4_183_link_keys.json",
        "split_v6_5_manifest.json",
        "MANIFEST.json",
    ):
        resolved = resolve_package_fallback(missing_cache, fname)
        assert resolved == PACKAGE_DATA_DIR / fname
        assert resolved.is_file()


def test_gold_contract_overlay_and_d15_signal_check() -> None:
    overlay = gc.load_overlay()
    assert overlay["allOf"]
    rulings, problems = gc.load_adjudications()
    assert len(rulings) >= 20 and not problems

    manifest = json.loads((PACKAGE_DATA_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["check"]["status"] == "pass"
    assert manifest["check"]["blocking_errors"] == 0
    assert (manifest.get("docmeta") or {}).get("max_personas") == 26

    # D15: removing an unstated value from an original label must fail unless logged in signal
    lk = "deadbeef00000001"
    orig_lab = {"status": "usable", "text_quality": "native", "congress": 117, "primary_kind": "witness_statement",
                "composed_title": "Statement", "gist": "Test.", "topics": ["oversight"]}
    new_lab = {"status": "usable", "text_quality": "native", "primary_kind": "witness_statement",
               "composed_title": "Statement", "gist": "Test.", "topics": ["oversight"]}
    row = gc.Row(lk=lk, split="train", source="synthetic.jsonl", line=1, raw={"link_key_hex": lk},
                 label=new_lab, filename="h.pdf", text="Statement of witness.")
    ctx_missing = gc.Ctx(label_errors={}, signal={}, cache={"original_labels": {lk: orig_lab}})
    checked, errs = gc.check_signal([row], ctx_missing)
    assert checked == 1 and lk in errs
    ctx_ok = gc.Ctx(label_errors={}, signal={lk: [{"field": "congress", "value": 117, "source": "known"}]},
                    cache={"original_labels": {lk: orig_lab}})
    checked2, errs2 = gc.check_signal([row], ctx_ok)
    assert checked2 == 1 and errs2 == {}


def test_c2_held_ruling_is_skipped_and_replacements_emit_d15_signals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lk = "0011223344556677"
    so_path = tmp_path / "second_opinion_rulings.jsonl"
    held_path = tmp_path / "second_opinion_held.jsonl"
    rulings = [
        {
            "link_key_hex": lk,
            "n": 1,
            "ruling": "apply",
            "field": "committees",
            "final_value": ["House Committee on Appropriations"],
            "quote": "Subcommittee on Defense",
            "first_reviewer": {"field": "committees", "type": "wrong_removal", "label_value": None},
        },
        {
            "link_key_hex": lk,
            "n": 2,
            "ruling": "apply",
            "field": "congress",
            "final_value": 118,
            "quote": "118th Congress",
            "first_reviewer": {"field": "congress", "type": "wrong", "label_value": 117},
        },
        {
            "link_key_hex": lk,
            "n": 3,
            "ruling": "apply",
            "field": "personas[0].title",
            "final_value": "Chair",
            "quote": "Chair Jane Doe",
            "first_reviewer": {"field": "personas[0].title", "type": "wrong", "label_value": {"name": "Jane Doe"}},
        },
    ]
    held_rows = [{"link_key_hex": lk, "n": 1, "held_reason": "P03_committees_stated: test hold"}]
    so_path.write_text("".join(json.dumps(r) + "\n" for r in rulings), encoding="utf-8")
    held_path.write_text("".join(json.dumps(r) + "\n" for r in held_rows), encoding="utf-8")

    monkeypatch.setattr(ng, "SECOND_OPINION", so_path)
    monkeypatch.setattr(ng, "SECOND_OPINION_HELD", held_path)
    monkeypatch.setattr(ng, "_DATA", {})
    monkeypatch.setattr(ng, "_HELD_C2_CACHE", {})
    monkeypatch.setattr(ng, "ENABLED", set(ng.ENABLED) | {"C2"})

    raw_row = {
        "messages": [
            {
                "role": "user",
                "content": "Advisory known metadata: {\"congress\":118}\nFilename: h.pdf\nText:\n118th Congress hearing statement by Chair Jane Doe.",
            },
            {"role": "assistant", "content": "{}"},
        ],
        "link_key_hex": lk,
        "saved_body_hex": "aa" * 32,
        "parser": "pdf_text",
    }
    cx = ng.Ctx("old", raw_row, {"text": "118th Congress hearing statement by Chair Jane Doe.", "known": "{\"congress\":117}", "filename": "h.pdf", "in_queue": True, "alt_text": None})
    cx.__dict__["_signal"] = []

    assert [r["n"] for r in ng._c2_active(cx)] == [2, 3]

    lab = {
        "status": "usable",
        "text_quality": "native",
        "congress": 117,
        "primary_kind": "witness_statement",
        "personas": [{"name": "Jane Doe", "title": "Director", "role": "witness", "entity_type": "non_gov_person"}],
        "composed_title": "Statement of Jane Doe",
        "gist": "Jane Doe testifies before Congress.",
        "topics": ["oversight"],
    }
    note = ng.c2_second_opinion_rulings(lab, cx)
    assert note is not None
    assert "committees" not in lab
    assert lab["congress"] == 118
    assert lab["personas"][0]["title"] == "Chair"
    assert cx.__dict__["_c2"][0] == {"n": 1, "status": "held_for_owner", "reason": "P03_committees_stated: test hold"}

    sig_pairs = {(s["field"], s["value"], s.get("kept_as")) for s in cx.__dict__["_signal"]}
    assert ("congress", 117, 118) in sig_pairs
    assert ("personas.title", "Director", "Chair") in sig_pairs


def test_gold_v65_split_filtering_and_sha_verification(tmp_path: Path) -> None:
    def _row(lk: str, split: str, kind: str) -> dict:
        user = f"Advisory known metadata: <NONE>\nFilename: {lk}.pdf\nText:\nDocument text for {lk}."
        ans = {
            "status": "usable",
            "text_quality": "native",
            "primary_kind": kind,
            "composed_title": f"Document {lk}",
            "gist": f"Summary of document {lk}.",
            "topics": ["oversight"],
        }
        return {
            "messages": [{"role": "user", "content": user}, {"role": "assistant", "content": json.dumps(ans)}],
            "saved_body_hex": lk.ljust(64, "0"),
            "link_key_hex": lk,
            "split": split,
        }

    ssot = tmp_path / "docmeta_gold_v6_5.jsonl"
    sample_rows = [
        _row("1111111111111111", "train", "witness_statement"),
        _row("2222222222222222", "heldout_v6_4", "hearing_transcript"),
        _row("3333333333333333", "test_gapfill", "treaty_document"),
        _row("4444444444444444", "excluded", "other"),
        _row("5555555555555555", "blind_val48", "bill_or_draft"),
        _row("6666666666666666", "blind_docs8", "committee_report"),
    ]
    ssot.write_text("".join(json.dumps(r) + "\n" for r in sample_rows), encoding="utf-8")
    manifest = tmp_path / "MANIFEST.json"
    sha = hashlib.sha256(ssot.read_bytes()).hexdigest()
    manifest.write_text(json.dumps({"ssot": {"sha256": sha}, "check": {"status": "pass"}}), encoding="utf-8")

    assert gold.verify_v65_ssot_sha256(ssot, manifest)["ssot"]["sha256"] == sha

    parsed_default, _ = gold.parse_gold_rows(ssot, (), queue_parquet=tmp_path / "absent.parquet")
    assert [r["link_key_hex"] for r in parsed_default] == ["1111111111111111", "2222222222222222"]
    val_idx, _ = gold.select_val_indices(parsed_default)
    assert val_idx == {1}

    parsed_gf, _ = gold.parse_gold_rows(
        ssot, (), queue_parquet=tmp_path / "absent.parquet", allowed_splits=frozenset({"test_gapfill"})
    )
    assert [r["link_key_hex"] for r in parsed_gf] == ["3333333333333333"]

    ssot.write_text(ssot.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        gold.verify_v65_ssot_sha256(ssot, manifest)


def test_viewer_server_serves_bundle_and_persists_reviews(tmp_path: Path) -> None:
    (tmp_path / "data" / "docs").mkdir(parents=True)
    (tmp_path / "data" / "index.json").write_text(json.dumps([{"key": "abcd"}]), encoding="utf-8")
    (tmp_path / "data" / "docs" / "abcd.json").write_text(json.dumps({"key": "abcd", "ok": True}), encoding="utf-8")

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(data_dir=tmp_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(f"{base}/") as resp:
            assert resp.status == 200
            assert "DocMeta" in resp.read().decode("utf-8", errors="ignore")
        with urllib.request.urlopen(f"{base}/data/index.json") as resp:
            assert resp.status == 200
            assert json.loads(resp.read().decode("utf-8")) == [{"key": "abcd"}]
        with urllib.request.urlopen(f"{base}/data/docs/abcd.json") as resp:
            assert resp.status == 200
            assert json.loads(resp.read().decode("utf-8")) == {"key": "abcd", "ok": True}

        req = urllib.request.Request(
            f"{base}/api/review",
            data=json.dumps({"key": "abcd", "verdict": "apply", "field": "committees", "note": "confirmed"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            assert json.loads(resp.read().decode("utf-8"))["ok"] is True

        with urllib.request.urlopen(f"{base}/style.css") as resp:
            assert resp.status == 200

        for bad_path in ("/../secret.txt", "/%2e%2e/secret.txt", "/serve.py"):
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(f"{base}{bad_path}")
            assert exc_info.value.code == 404

        with urllib.request.urlopen(f"{base}/api/reviews") as resp:
            reviews = json.loads(resp.read().decode("utf-8"))
            assert len(reviews) == 1
            assert reviews[0]["key"] == "abcd"
            assert reviews[0]["verdict"] == "apply"
    finally:
        server.shutdown()
        server.server_close()


def test_gold_gate_v6_2_resolves_v65_shards_and_consolidate_default_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    v65_dir = tmp_path / "v65"
    v6_dir = tmp_path / "v6"
    (v65_dir / "outputs_2000").mkdir(parents=True)
    (v65_dir / "shards_2000").mkdir(parents=True)
    (v6_dir / "lookups_and_gold").mkdir(parents=True)

    val48_p = v6_dir / "lookups_and_gold" / "eval_val48_v4_gold.json"
    docs8_p = v6_dir / "lookups_and_gold" / "eval_docs8_v4_gold.json"
    val48_p.write_text("[]", encoding="utf-8")
    docs8_p.write_text("[]", encoding="utf-8")
    absent = v6_dir / "lookups_and_gold" / "absent"

    for attr in (
        "TRAIN360_PATH",
        "TRAIN58_PATH",
        "TARGET_GOLD_PATH",
        "GAP500_GOLD_PATH",
        "REHYDRATED360_GOLD_PATH",
        "COMPLETE_V6_3_GOLD_PATH",
        "RESIDUAL160_GOLD_PATH",
        "COMPLETE_V6_4_GOLD_PATH",
        "DET_V6_1_PATH",
        "DET_V6_2_PATH",
    ):
        monkeypatch.setattr(gg, attr, absent)
    monkeypatch.setattr(gg, "VAL48_PATH", val48_p)
    monkeypatch.setattr(gg, "DOCS8_PATH", docs8_p)
    monkeypatch.setenv("DOCMETA_V65_DIR", str(v65_dir))

    (v65_dir / "shards_2000" / "shard_32_store.json").write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "link_key_hex": "aa" * 8,
                        "saved_body_hex": "bb" * 32,
                        "doc_key": "doc-s32",
                        "filename": "s32_witness.pdf",
                        "window_text": "Witness testimony before subcommittee on energy oversight.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (v65_dir / "outputs_2000" / "gold_shard_32.jsonl").write_text(
        json.dumps(
            {
                "link_key_hex": "cc" * 8,
                "saved_body_hex": "dd" * 32,
                "messages": [
                    {
                        "role": "user",
                        "content": "Advisory known metadata: <NONE>\nFilename: s32_gold.pdf\nText:\nStatement from shard thirty two.",
                    },
                    {"role": "assistant", "content": "{}"},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    forb = gg.load_forbidden_sets(include_prior_58=False, include_prior_shards_32_36=True)
    assert ("aa" * 8) in forb["prior_link_keys"]
    assert ("bb" * 32) in forb["prior_shas"]
    assert ("cc" * 8) in forb["prior_link_keys"]
    assert ("dd" * 32) in forb["prior_shas"]

    cand_label = {
        "status": "usable",
        "text_quality": "native",
        "primary_kind": "witness_statement",
        "composed_title": "Testimony of Pat Lee",
        "gist": "Pat Lee outlines oversight recommendations for Congress.",
        "topics": ["oversight"],
    }
    cand_path = tmp_path / "candidate.jsonl"
    cand_path.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "Advisory known metadata: <NONE>\nFilename: pat_lee.pdf\nText:\nStatement of Pat Lee before the oversight subcommittee.",
                    },
                    {"role": "assistant", "content": json.dumps(cand_label)},
                ],
                "saved_body_hex": "12" * 32,
                "link_key_hex": "34" * 8,
                "parser": "pdf_text",
                "parser_version": "56" * 32,
                "text_sha256": "78" * 32,
                "stratum": "rare_test",
                "reviewer_id": "test_rev",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert gg.main(["consolidate", str(cand_path)]) == 0
    default_out = v65_dir / "outputs_2000" / "train_v6_5_raretypes_hydrogen_high.jsonl"
    assert default_out.is_file()
    out_rows = [json.loads(line) for line in default_out.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(out_rows) == 1 and out_rows[0]["link_key_hex"] == ("34" * 8)


def test_split_v65_stratified_split(tmp_path: Path) -> None:
    out_dir = tmp_path / "outputs_2000"
    out_dir.mkdir(parents=True)

    def _row(idx: int, label: dict) -> str:
        return json.dumps(
            {
                "link_key_hex": f"{idx:016x}",
                "saved_body_hex": f"{idx:064x}",
                "messages": [
                    {"role": "user", "content": f"Advisory known metadata: <NONE>\nFilename: d{idx}.pdf\nText:\nBody {idx}."},
                    {"role": "assistant", "content": json.dumps(label)},
                ],
            }
        )

    s32_rows = [
        _row(1, {"status": "usable", "primary_kind": "treaty_document"}),
        _row(2, {"status": "usable", "primary_kind": "qfr_request"}),
        _row(3, {"status": "usable", "primary_kind": "qfr_request"}),
        _row(4, {"status": "usable", "primary_kind": "committee_report"}),
        _row(5, {"status": "usable", "primary_kind": "committee_report"}),
        _row(6, {"status": "usable", "primary_kind": "committee_report"}),
        _row(7, {"status": "usable", "primary_kind": "committee_report"}),
    ]
    s36_rows = [
        _row(8, {"status": "stub_or_blank"}),
        _row(9, {"status": "stub_or_blank"}),
    ]
    (out_dir / "gold_shard_32.jsonl").write_text("\n".join(s32_rows) + "\n", encoding="utf-8")
    (out_dir / "gold_shard_36.jsonl").write_text("\n".join(s36_rows) + "\n", encoding="utf-8")

    assert split_v65.main(["--v65-dir", str(tmp_path)]) == 0
    lookups = tmp_path / "lookups_and_gold"
    manifest = json.loads((lookups / "split_v6_5_manifest.json").read_text(encoding="utf-8"))
    assert manifest["train"] == 6
    assert manifest["test"] == 3
    assert manifest["strata"]["rare|treaty_document"] == {"train": 1, "test": 0}
    assert manifest["strata"]["rare|qfr_request"] == {"train": 1, "test": 1}
    assert manifest["strata"]["rare|committee_report"] == {"train": 3, "test": 1}
    assert manifest["strata"]["unseen_cluster|status:stub_or_blank"] == {"train": 1, "test": 1}
    first_test = (lookups / "eval_v6_5_gapfill_test.jsonl").read_text(encoding="utf-8")
    assert split_v65.main(["--v65-dir", str(tmp_path)]) == 0
    assert (lookups / "eval_v6_5_gapfill_test.jsonl").read_text(encoding="utf-8") == first_test


def test_c2_try_one_all_branches_and_accounting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _base_lab() -> dict:
        return ng.canon(
            {
                "status": "usable",
                "text_quality": "native",
                "congress": 118,
                "primary_kind": "witness_statement",
                "committees": ["House Committee on Appropriations", "House Committee on Budget"],
                "personas": [
                    {
                        "name": "Alice Smith",
                        "title": "Director",
                        "role": "witness",
                        "entity_type": "non_gov_person",
                        "education": ["B.A., State U", "J.D., Law U"],
                    },
                    {"name": "Bob Jones", "role": "chair", "entity_type": "member"},
                ],
                "disclosure": {
                    "has_federal_grants": True,
                    "federal_grants": ["DOE Grant G-1"],
                },
                "composed_title": "Statement of Alice Smith",
                "gist": "Alice Smith testifies before Congress.",
                "topics": ["oversight"],
            }
        )

    # 1. Indexed whole-person removal with missing label_value must not drop all personas (Warning 2)
    lab, st, reason, _, _ = ng._c2_try_one(
        _base_lab(),
        {
            "n": 1,
            "ruling": "apply",
            "field": "personas[2]",
            "final_value": None,
            "first_reviewer": {"type": "wrong_removal", "label_value": None},
        },
    )
    assert st == "not_applied" and "personas[2]" in (reason or "")
    assert len(lab["personas"]) == 2

    # 2. Whole-person dict replacement requires matching label_value surname when mutating (Warning 2)
    _, st_bad_dict, _, _, _ = ng._c2_try_one(
        _base_lab(),
        {
            "n": 2,
            "ruling": "apply",
            "field": "personas[0]",
            "final_value": {"name": "Alice Smith", "title": "Chair", "role": "witness", "entity_type": "non_gov_person"},
            "first_reviewer": {"type": "missing", "label_value": None},
        },
    )
    assert st_bad_dict == "not_applied"

    lab_dict_ok, st_dict_ok, _, _, sig_dict = ng._c2_try_one(
        _base_lab(),
        {
            "n": 3,
            "ruling": "apply",
            "field": "personas[0]",
            "final_value": {"name": "Alice Smith", "title": "Chair", "role": "witness", "entity_type": "non_gov_person"},
            "first_reviewer": {"type": "wrong", "label_value": {"name": "Alice Smith"}},
        },
    )
    assert st_dict_ok == "applied"
    assert lab_dict_ok["personas"][0]["title"] == "Chair"
    assert ("personas.title", "Director", "Alice Smith", "Chair") in sig_dict

    # 3. Whole personas list replace and whole personas list removal
    lab_plist, st_plist, _, _, sig_plist = ng._c2_try_one(
        _base_lab(),
        {
            "n": 4,
            "ruling": "apply",
            "field": "personas",
            "final_value": [{"name": "Alice Smith", "role": "witness", "entity_type": "non_gov_person"}],
            "first_reviewer": {"type": "wrong", "label_value": _base_lab()["personas"]},
        },
    )
    assert st_plist == "applied" and len(lab_plist["personas"]) == 1
    assert any(s[0] == "personas.name" and s[1] == "Bob Jones" for s in sig_plist)

    lab_premove, st_premove, _, _, sig_premove = ng._c2_try_one(
        _base_lab(),
        {
            "n": 5,
            "ruling": "apply",
            "field": "personas",
            "final_value": None,
            "first_reviewer": {"type": "wrong_removal", "label_value": None},
        },
    )
    assert st_premove == "applied" and "personas" not in lab_premove
    assert {s[1] for s in sig_premove} == {"Alice Smith", "Bob Jones"}

    # 4. Indexed persona subfield item + list subfield removal signal unpacking
    lab_ed, st_ed, _, _, sig_ed = ng._c2_try_one(
        _base_lab(),
        {
            "n": 6,
            "ruling": "apply",
            "field": "personas[0].education[0]",
            "final_value": "B.S., State U",
            "quote": "Alice Smith earned B.A., State U",
            "first_reviewer": {"type": "wrong", "label_value": "B.A., State U"},
        },
    )
    assert st_ed == "applied" and lab_ed["personas"][0]["education"][0] == "B.S., State U"
    assert ("personas.education", "B.A., State U", "Alice Smith", "B.S., State U") in sig_ed

    lab_ed_drop, st_ed_drop, _, _, sig_ed_drop = ng._c2_try_one(
        _base_lab(),
        {
            "n": 7,
            "ruling": "apply",
            "field": "personas[0].education",
            "final_value": None,
            "quote": "Alice Smith earned B.A., State U",
            "first_reviewer": {"type": "wrong_removal", "label_value": ["B.A., State U", "J.D., Law U"]},
        },
    )
    assert st_ed_drop == "applied" and "education" not in lab_ed_drop["personas"][0]
    assert {s[1] for s in sig_ed_drop} == {"B.A., State U", "J.D., Law U"}

    # 5. C2_LIST_FIELDS + indexed list field
    lab_idx_list, st_idx_list, _, _, sig_idx_list = ng._c2_try_one(
        _base_lab(),
        {
            "n": 8,
            "ruling": "apply",
            "field": "committees[0]",
            "final_value": None,
            "first_reviewer": {"type": "wrong_removal", "label_value": "House Committee on Appropriations"},
        },
    )
    assert st_idx_list == "applied" and lab_idx_list["committees"] == ["House Committee on Budget"]
    assert ("committees", "House Committee on Appropriations", None, None) in sig_idx_list

    lab_full_list, st_full_list, _, _, sig_full_list = ng._c2_try_one(
        _base_lab(),
        {
            "n": 9,
            "ruling": "apply",
            "field": "committees",
            "final_value": ["Senate Committee on Finance"],
            "first_reviewer": {"type": "wrong", "label_value": _base_lab()["committees"]},
        },
    )
    assert st_full_list == "applied" and lab_full_list["committees"] == ["Senate Committee on Finance"]
    assert len(sig_full_list) == 2

    # 6. Nested disclosure field + list removal
    lab_disc, st_disc, _, _, sig_disc = ng._c2_try_one(
        _base_lab(),
        {
            "n": 10,
            "ruling": "apply",
            "field": "disclosure.has_federal_grants",
            "final_value": False,
            "first_reviewer": {"type": "wrong", "label_value": True},
        },
    )
    assert st_disc == "applied" and lab_disc["disclosure"]["has_federal_grants"] is False
    assert ("disclosure.has_federal_grants", True, None, False) in sig_disc

    lab_disc_drop, st_disc_drop, _, _, sig_disc_drop = ng._c2_try_one(
        _base_lab(),
        {
            "n": 11,
            "ruling": "apply",
            "field": "disclosure.federal_grants",
            "final_value": None,
            "first_reviewer": {"type": "wrong_removal", "label_value": ["DOE Grant G-1"]},
        },
    )
    assert st_disc_drop == "applied" and "federal_grants" not in lab_disc_drop["disclosure"]
    assert sig_disc_drop == [("disclosure.federal_grants", "DOE Grant G-1", None, None)]

    # 7. Status change to stub_or_blank cascades primary_kind on valid non-usable transition, and blocks unusable flips
    lab_stub, st_stub, _, _, sig_stub = ng._c2_try_one(
        {
            "status": "error_or_block",
            "text_quality": "native",
            "error_reason": "HTTP 403",
            "primary_kind": "other",
        },
        {
            "n": 12,
            "ruling": "apply",
            "field": "status",
            "final_value": "stub_or_blank",
            "first_reviewer": {"type": "wrong", "label_value": "error_or_block"},
        },
    )
    assert st_stub == "applied" and lab_stub["status"] == "stub_or_blank" and "primary_kind" not in lab_stub
    assert ("primary_kind", "other", None, None) in sig_stub

    lab_blocked, st_blocked, blocked_reason, _, _ = ng._c2_try_one(
        _base_lab(),
        {
            "n": 13,
            "ruling": "apply",
            "field": "status",
            "final_value": "stub_or_blank",
            "first_reviewer": {"type": "wrong", "label_value": "usable"},
        },
    )
    assert st_blocked == "not_applied" and "non_usable" in (blocked_reason or "")
    assert lab_blocked["status"] == "usable"

    # 8. Accounting in c2_second_opinion_rulings: reject -> rejected_by_ruling, unsupported -> not_applied
    lk = "9988776655443322"
    so_path = tmp_path / "so.jsonl"
    held_path = tmp_path / "held.jsonl"
    so_path.write_text(
        json.dumps({"link_key_hex": lk, "n": 1, "ruling": "reject", "field": "status", "final_value": "stub_or_blank"})
        + "\n"
        + json.dumps({"link_key_hex": lk, "n": 2, "ruling": "apply", "field": "unknown_field", "final_value": "x"})
        + "\n",
        encoding="utf-8",
    )
    held_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(ng, "SECOND_OPINION", so_path)
    monkeypatch.setattr(ng, "SECOND_OPINION_HELD", held_path)
    monkeypatch.setattr(ng, "_DATA", {})
    monkeypatch.setattr(ng, "_HELD_C2_CACHE", {})
    cx = ng.Ctx("old", {"messages": [{"role": "user", "content": ""}, {"role": "assistant", "content": "{}"}], "link_key_hex": lk, "saved_body_hex": "ee" * 32, "parser": "pdf_text"}, {"text": "Hello", "known": None, "filename": "a.pdf", "in_queue": True, "alt_text": None})
    lab_acct = _base_lab()
    assert ng.c2_second_opinion_rulings(lab_acct, cx) is None
    assert cx.__dict__["_c2"] == [
        {"n": 1, "status": "rejected_by_ruling", "reason": None},
        {"n": 2, "status": "not_applied", "reason": "unsupported field 'unknown_field'"},
    ]


def test_gold_unsplit_and_downstream_eval_training_wiring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _row(lk: str, kind: str, split: str | None = None) -> dict:
        row: dict = {
            "messages": [
                {
                    "role": "user",
                    "content": f"Advisory known metadata: <NONE>\nFilename: {lk}.pdf\nText:\nBody text for document {lk}.",
                },
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "status": "usable",
                            "text_quality": "native",
                            "primary_kind": kind,
                            "composed_title": f"Document {lk}",
                            "gist": f"Summary of document {lk} for Congress.",
                            "topics": ["oversight"],
                        }
                    ),
                },
            ],
            "saved_body_hex": lk.ljust(64, "0"),
            "link_key_hex": lk,
        }
        if split is not None:
            row["split"] = split
        return row

    # Unsplit (V6.4-style) rows must NEVER leak into explicit split queries (Warning 1)
    unsplit_jsonl = tmp_path / "v64_unsplit.jsonl"
    unsplit_rows = [
        _row("aaaa000000000001", "witness_statement"),
        _row("aaaa000000000002", "hearing_transcript"),
        _row("aaaa000000000003", "treaty_document"),
    ]
    unsplit_jsonl.write_text("".join(json.dumps(r) + "\n" for r in unsplit_rows), encoding="utf-8")
    empty_gf, _ = gold.parse_gold_rows(
        unsplit_jsonl, (), queue_parquet=tmp_path / "absent.parquet", allowed_splits=frozenset({"test_gapfill"})
    )
    assert empty_gf == []
    kept_default, _ = gold.parse_gold_rows(unsplit_jsonl, (), queue_parquet=tmp_path / "absent.parquet")
    assert len(kept_default) == 3

    keys_json = tmp_path / "heldout_keys.json"
    keys_json.write_text(json.dumps({"link_key_hex": ["aaaa000000000002"]}), encoding="utf-8")
    v_idx, _ = gold.select_val_indices(kept_default, heldout_keys_json=keys_json)
    assert v_idx == {1}

    # Downstream V6.5 SSOT -> gold.load_and_prepare_v64_splits, eval_blind.load_sweep_sets, training_pairs
    ssot = tmp_path / "docmeta_gold_v6_5.jsonl"
    ssot_rows = [
        _row("1111000000000001", "witness_statement", "train"),
        _row("2222000000000002", "hearing_transcript", "heldout_v6_4"),
        _row("3333000000000003", "treaty_document", "test_gapfill"),
    ]
    ssot.write_text("".join(json.dumps(r) + "\n" for r in ssot_rows), encoding="utf-8")

    pq_path = tmp_path / "queue.parquet"
    pq.write_table(
        pa.table(
            {
                "link_key_hex": ["2222000000000002", "3333000000000003"],
                "filename": ["val.pdf", "gf.pdf"],
                "p12_raw_text": ["Validation hearing transcript.", "Gapfill treaty text."],
                "p12_clean_text": ["Validation hearing transcript.", "Gapfill treaty text."],
                "known_json": ["{}", "{}"],
                "effective_format": ["pdf", "pdf"],
            }
        ),
        pq_path,
    )
    absent = tmp_path / "absent.json"
    monkeypatch.setattr(gold, "DEFAULT_QUEUE_PARQUET", pq_path)
    monkeypatch.setattr(eval_blind, "DEFAULT_VAL48_JSON", absent)
    monkeypatch.setattr(eval_blind, "DEFAULT_DOCS8_JSON", absent)
    monkeypatch.setattr(training_pairs, "DEFAULT_VAL48_JSON", absent)
    monkeypatch.setattr(training_pairs, "DEFAULT_DOCS8_JSON", absent)

    sweep = eval_blind.load_sweep_sets(["valid_sweep", "test_gapfill_sweep"], gold_jsonl=ssot)
    assert [g["primary_kind"] for g in sweep["valid_sweep"][1]] == ["hearing_transcript"]
    assert [g["primary_kind"] for g in sweep["test_gapfill_sweep"][1]] == ["treaty_document"]

    class _StubTokenizer:
        def apply_chat_template(self, msgs, tokenize=False, add_generation_prompt=False, enable_thinking=False):
            out = "".join(f"<{m['role']}>{m['content']}</{m['role']}>" for m in msgs)
            return out + ("<assistant>" if add_generation_prompt else "")

        def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
            return [ord(ch) % 97 + 1 for ch in text]

        def decode(self, ids: list[int]) -> str:
            return "x" * len(ids)

    stub_tok = _StubTokenizer()
    train_items, val_items, split_stats = gold.load_and_prepare_v64_splits(ssot, absent, absent, stub_tok)
    assert len(train_items) == 2  # 1 base + 1 rare-tail view (<30 count)
    assert len(val_items) == 1
    assert split_stats["train_docs_base"] == 1

    fake_mlx_lm = types.ModuleType("mlx_lm")
    fake_utils = types.ModuleType("mlx_lm.utils")
    fake_utils.load_tokenizer = lambda _snap: stub_tok  # type: ignore[attr-defined]
    fake_mlx_lm.utils = fake_utils  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlx_lm", fake_mlx_lm)
    monkeypatch.setitem(sys.modules, "mlx_lm.utils", fake_utils)

    out_pairs = tmp_path / "out" / "PAIRS.json"
    assert training_pairs.main(["--base-snap", str(tmp_path / "snap"), "--gold-jsonl", str(ssot), "--out", str(out_pairs)]) == 0
    payload = json.loads(out_pairs.read_text(encoding="utf-8"))
    wire_cfg = json.loads((out_pairs.parent / "docmeta_wire_config.json").read_text(encoding="utf-8"))
    assert payload["stats"]["gold_jsonl"] == str(ssot)
    assert payload["stats"]["gold_sha256"] == hashlib.sha256(ssot.read_bytes()).hexdigest()
    assert payload["stats"]["gold_contract_version"] == gc.CONTRACT_VERSION
    assert wire_cfg["max_personas"] == 26


def test_viewer_build_bundle_surfaces_needs_owner(tmp_path: Path) -> None:
    v65 = tmp_path / "v65"
    v6 = tmp_path / "v6"
    (v65 / "ssot").mkdir(parents=True)
    (v65 / "lookups_and_gold").mkdir(parents=True)
    (v65 / "contract").mkdir(parents=True)
    (v65 / "raw_review_20261118" / "full").mkdir(parents=True)
    (v6 / "parquets_v6_2").mkdir(parents=True)

    lk = "faceb00c00000001"
    (v65 / "ssot" / "docmeta_gold_v6_5.jsonl").write_text(
        json.dumps(
            {
                "link_key_hex": lk,
                "saved_body_hex": "ab" * 32,
                "split": "train",
                "parser": "pdf_text",
                "messages": [
                    {
                        "role": "user",
                        "content": "Context:\nAdvisory known metadata: <NONE>\nFilename: sample.pdf\nText:\nBody text.",
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "status": "usable",
                                "primary_kind": "witness_statement",
                                "composed_title": "Sample Statement",
                                "gist": "Sample testimony.",
                                "topics": ["oversight"],
                            }
                        ),
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (v65 / "lookups_and_gold" / "second_opinion_rulings.jsonl").write_text(
        json.dumps(
            {
                "link_key_hex": lk,
                "n": 2,
                "field": "primary_kind",
                "final_value": "other",
                "quote": "quoted",
                "why": "ambiguous",
                "confidence": "medium",
                "first_reviewer": {"type": "wrong", "label_value": "witness_statement"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (v65 / "lookups_and_gold" / "second_opinion_held.jsonl").write_text(
        json.dumps(
            {
                "link_key_hex": lk,
                "n": 1,
                "field": "committees",
                "held_reason": "P03_committees_stated",
                "quote": "Committee on Budget",
                "final_value": ["House Committee on Budget"],
                "why": "needs owner",
                "confidence": "high",
                "first_reviewer": {"type": "wrong_removal", "label_value": None},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (v65 / "lookups_and_gold" / "second_opinion_applied.jsonl").write_text(
        json.dumps(
            {
                "link_key_hex": lk,
                "n": 2,
                "field": "primary_kind",
                "status": "not_applied",
                "reason": "schema validation failed",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    build_bundle.main(["--v65-dir", str(v65), "--v6-dir", str(v6)])
    index_rows = json.loads((v65 / "viewer" / "data" / "index.json").read_text(encoding="utf-8"))
    assert len(index_rows) == 1
    assert index_rows[0]["needs_owner_count"] == 2
    assert index_rows[0]["has_open_findings"] is True
    doc_payload = json.loads((v65 / "viewer" / "data" / "docs" / f"{lk}.json").read_text(encoding="utf-8"))
    assert doc_payload["known"] == "<NONE>"
    rules_by_status = [(f["rule"], f["status"]) for f in doc_payload["findings"]]
    assert rules_by_status == [("C2_held", "needs_owner"), ("C2_not_applied", "needs_owner")]


@pytest.mark.skipif(not gold.DEFAULT_V65_SSOT_JSONL.is_file(), reason="Sealed V6.5 SSOT cache not present")
def test_local_sealed_v65_ssot_verifies_when_present() -> None:
    assert gold.DEFAULT_GOLD_JSONL == gold.DEFAULT_V65_SSOT_JSONL
    assert gc.verify_manifest(require_pass=True) == []
    assert len(gc.load_heldout_keys()) == 183
