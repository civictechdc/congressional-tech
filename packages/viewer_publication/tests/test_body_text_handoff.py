"""The text handoff keeps release coverage and measurement identities explicit."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from viewer_publication.body_text_export import file_facts, footer_sha256
from viewer_publication.body_text_quality import reconcile_measurements
from viewer_publication.body_text_ssot import BodyTextSSOT


def _pin(path):
    facts = file_facts(path)
    return {"path": str(path), "sha256": facts["sha256"], "size": facts["size"]}


def _files(tmp_path):
    bodies = [sha256(str(i).encode()).digest() for i in range(3)]
    export = tmp_path / "export.parquet"
    pq.write_table(pa.table({
        "saved_body": pa.array(bodies[:1], pa.binary(32)), "text": ["Actual statement"],
        "page_offsets": [[0]], "text_sha256": [sha256(b"Actual statement").digest()],
    }), export)
    detail = tmp_path / "detail.parquet"
    pq.write_table(pa.table({
        "link_key": [b"a", b"b", b"c"], "saved_body": pa.array(bodies, pa.binary(32)),
        "filename": ["a.pdf", "error.html", "c.docx"], "title": ["A", "B", "C"],
        "format": ["pdf", "html", "docx"], "congress": [118, 118, 118],
        "chambers": [["house"]]*3, "committee_keys": [["hsag00"]]*3,
        "document_date": ["2024-01-01"]*3,
    }), detail)
    facts = file_facts(export)
    pointer = {"sha256": facts["sha256"], "bytes": facts["size"], "rows": 1,
               "footer_sha256": footer_sha256(export), "release_id": "old-release",
               "detail": _pin(detail)}
    (tmp_path / "current.json").write_text(json.dumps(pointer))
    return bodies, detail, pointer


def _handoff(tmp_path, bodies, detail, pointer, statuses=None):
    coverage = tmp_path / "coverage.parquet"
    pq.write_table(pa.table({"body_sha256": [body.hex() for body in bodies],
                            "text_status": statuses or ["available", "excluded", "unsupported"][:len(bodies)],
                            "text_sha256": [sha256(b"Actual statement").hexdigest(), None, None][:len(bodies)]}), coverage)
    path = tmp_path / "handoff.json"
    path.write_text(json.dumps({"version": 1, "export_sha256": pointer["sha256"],
                               "source_release_id": pointer["release_id"], "release_id": "new-release",
                               "export_pointer": _pin(tmp_path / "current.json"),
                               "detail": _pin(detail), "coverage": _pin(coverage)}))
    return path


def test_consumer_preserves_missing_rows_and_requires_detail_binding(tmp_path):
    _, detail, _ = _files(tmp_path)
    reader = BodyTextSSOT(tmp_path)
    rows = list(reader.iter_serenedb_documents(detail))
    assert len(rows) == 3
    assert [row["text_status"] for row in rows] == ["available", "missing", "missing"]
    assert rows[1]["text"] is None
    table = pq.read_table(detail)
    pq.write_table(table.set_column(2, "filename", pa.array(["different.pdf", "error.html", "c.docx"])), detail)
    with pytest.raises(ValueError, match="detail/release"):
        list(reader.iter_serenedb_documents(detail))


def test_legacy_export_requires_explicit_reconciled_handoff(tmp_path):
    bodies, detail, pointer = _files(tmp_path)
    del pointer["detail"]
    (tmp_path / "current.json").write_text(json.dumps(pointer))
    reader = BodyTextSSOT(tmp_path)
    with pytest.raises(ValueError, match="no detail binding"):
        list(reader.iter_serenedb_documents(detail))
    handoff = _handoff(tmp_path, bodies, detail, pointer)
    rows = list(reader.iter_serenedb_documents(detail, handoff=handoff))
    assert [row["text_status"] for row in rows] == ["available", "excluded", "unsupported"]
    assert all(row["release_id"] == "new-release" for row in rows)
    windows = list(reader.iter_docmeta_windows(detail, handoff=handoff))
    assert windows[1]["p12_text"] is None
    assert windows[1]["full_text_chars"] is None


@pytest.mark.parametrize("wrong", ["source_release_id", "export_sha256"])
def test_consumer_rejects_wrong_handoff_generation(tmp_path, wrong):
    bodies, detail, pointer = _files(tmp_path)
    handoff = _handoff(tmp_path, bodies, detail, pointer)
    value = json.loads(handoff.read_text())
    value[wrong] = "wrong"
    handoff.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="does not bind"):
        list(BodyTextSSOT(tmp_path).iter_serenedb_documents(detail, handoff=handoff))


def test_held_output_is_explicit_and_not_returned_as_searchable_text(tmp_path):
    bodies, detail, pointer = _files(tmp_path)
    handoff = _handoff(tmp_path, bodies, detail, pointer, ["held", "excluded", "unsupported"])
    row = next(BodyTextSSOT(tmp_path).iter_serenedb_documents(detail, handoff=handoff))
    assert row["text_status"] == "held"
    assert row["text"] is None and row["text_sha256"] is None


def test_planted_wrong_selected_digest_is_rejected(tmp_path):
    bodies, detail, pointer = _files(tmp_path)
    handoff = _handoff(tmp_path, bodies, detail, pointer)
    coverage = tmp_path / "coverage.parquet"
    table = pq.read_table(coverage)
    pq.write_table(table.set_column(2, "text_sha256", pa.array(["wrong", None, None])), coverage)
    value = json.loads(handoff.read_text())
    value["coverage"] = _pin(coverage)
    handoff.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="Selected text digest"):
        list(BodyTextSSOT(tmp_path).iter_serenedb_documents(detail, handoff=handoff))


def test_reconciliation_reads_referenced_identity_and_preserves_history(tmp_path):
    measured = tmp_path / "measurements.parquet"
    identities = [{"body_sha256": str(i), "parser": "pdf_text", "parser_version": "old",
                   "text_sha256": "original", "text_bytes": 10,
                   "band": "review_first" if i == 3 else "no_obvious_failure_detected"} for i in range(4)]
    pq.write_table(pa.Table.from_pylist(identities), measured)
    rows = [dict(row, current_measurement_available=True, measurement_file=str(measured),
                 measurement_band="no_obvious_failure_detected", measurement_family="pdf",
                 measured_text_bytes=10, known_valid_empty=False) for row in identities]
    rows[0]["parser_version"] = "new"
    rows[0]["text_sha256"] = "repaired"
    rows[1]["measured_text_bytes"] = 20
    state, output, history = [tmp_path / name for name in ["state.parquet", "fixed.parquet", "history.jsonl"]]
    pq.write_table(pa.Table.from_pylist(rows), state)
    result = reconcile_measurements(state, output, history)
    assert result["claimed_current"] == 4
    assert result["verified_current"] == 1
    assert result["invalidated"] == 3
    assert result["measurement_band_differs"] == 1
    after = pq.read_table(output).to_pylist()
    assert after[0]["parser_version"] == "new" and after[0]["text_sha256"] == "repaired"
    assert after[0]["measurement_file"] is None
    assert after[1]["measured_text_bytes"] is None
    assert after[2] == rows[2]
    old = [json.loads(line)["previous_state"] for line in history.read_text().splitlines()]
    assert old == [rows[0], rows[1], rows[3]]
    assert pq.read_table(state).to_pylist() == rows
    with pytest.raises(FileExistsError):
        reconcile_measurements(state, output, history)


def test_planted_missing_coverage_row_is_rejected(tmp_path):
    bodies, detail, pointer = _files(tmp_path)
    handoff = _handoff(tmp_path, bodies[:2], detail, pointer)
    with pytest.raises(ValueError, match="omits a release body"):
        list(BodyTextSSOT(tmp_path).iter_serenedb_documents(detail, handoff=handoff))


def test_changed_pointer_cannot_borrow_retained_handoff_identity(tmp_path):
    bodies, detail, pointer = _files(tmp_path)
    handoff = _handoff(tmp_path, bodies, detail, pointer)
    pointer["sha256"] = "a"*64
    (tmp_path/"current.json").write_text(json.dumps(pointer))
    value = json.loads(handoff.read_text())
    value["export_sha256"] = pointer["sha256"]
    handoff.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="export pointer"):
        list(BodyTextSSOT(tmp_path).iter_serenedb_documents(detail, handoff=handoff))
    with pytest.raises(ValueError, match="Export sha256 mismatch"):
        BodyTextSSOT(tmp_path, verify_file_sha256=True)


def test_empty_output_cannot_be_claimed_available(tmp_path):
    bodies, detail, pointer = _files(tmp_path)
    export = tmp_path/"export.parquet"
    table = pq.read_table(export)
    table = table.set_column(1, "text", pa.array([""]))
    table = table.set_column(3, "text_sha256", pa.array([sha256(b"").digest()]))
    pq.write_table(table, export)
    facts = file_facts(export)
    pointer.update(sha256=facts["sha256"], bytes=facts["size"], footer_sha256=footer_sha256(export))
    (tmp_path/"current.json").write_text(json.dumps(pointer))
    handoff = _handoff(tmp_path, bodies, detail, pointer)
    coverage = tmp_path/"coverage.parquet"
    table = pq.read_table(coverage).set_column(2, "text_sha256", pa.array([sha256(b"").hexdigest(), None, None]))
    pq.write_table(table, coverage)
    value = json.loads(handoff.read_text()); value["coverage"] = _pin(coverage)
    handoff.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="unqualified empty"):
        list(BodyTextSSOT(tmp_path).iter_serenedb_documents(detail, handoff=handoff))


def test_release_preparation_binds_source_inventory_and_retained_integrity(tmp_path):
    source = Path(__file__).parents[3]/"scripts/measure/prepare_body_text_handoff.py"
    spec = importlib.util.spec_from_file_location("prepare_body_text_handoff", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bodies, detail, pointer = _files(tmp_path)
    selection = tmp_path/"selection.json"
    selection.write_text(json.dumps({"excluded_bodies": [
        {"body_sha256": bodies[1].hex(), "source_role": "error_response"}]}))
    pointer["selection"] = _pin(selection)
    (tmp_path/"current.json").write_text(json.dumps(pointer))
    qualification = tmp_path/"qualification.md"
    qualification.write_text("Source review remains scoped to the reviewed pages.\n")
    def old_pin(path):
        value = _pin(path)
        value["bytes"] = value.pop("size")
        return value
    source_handoff = tmp_path/"source-handoff.json"
    source_handoff.write_text(json.dumps(dict(release_id="old-release", selection=old_pin(selection),
        qualification=old_pin(qualification), catalog_pins={})))
    manifest = tmp_path/"manifest.json"
    manifest.write_text(json.dumps(dict(release_id="new-release", files=[dict(name="detail.parquet", **_pin(detail))])))
    quality = tmp_path/"quality.parquet"
    pq.write_table(pa.table({"body_sha256": [bodies[0].hex()], "parser": ["pdf_text"],
        "parser_version": ["a"*64], "text_sha256": [sha256(b"Actual statement").hexdigest()],
        "source_excluded_from_prose": [False], "known_held_bad_output": [False],
        "known_valid_empty": [False], "current_state": ["completed"],
        "quality_scope": ["identity only"], "current_measurement_available": [False]}), quality)
    inventory = tmp_path/"inventory.jsonl"
    inventory.write_text(json.dumps(dict(body_sha256="different-original",
        duplicate_wrapper_body_sha256=[bodies[1].hex()]))+"\n")
    inventory_manifest = tmp_path/"inventory-manifest.json"
    inventory_manifest.write_text(json.dumps(dict(inventory=old_pin(inventory))))
    verification = tmp_path/"verification.json"
    retained = dict(pointer, all_row_sha256_verified=True)
    verification.write_text(json.dumps(dict(export_parquet=retained)))
    arguments = dict(export=tmp_path, source_handoff=source_handoff, release_manifest=manifest,
        detail=detail, quality_state=quality, inventory_manifest=inventory_manifest,
        export_verification=verification)
    result = module.prepare(**arguments, output=tmp_path/"prepared")
    assert result["counts"] == {"available": 1, "excluded": 1, "unsupported": 1}
    assert result["source_qualification"] == _pin(qualification)
    assert result["recovery_inventory"]["error_exclusions_reconciled"] is True
    assert result["export_integrity"]["full_file_hash_verified_this_run"] is False
    assert result["export_integrity"]["retained_verification"] == _pin(verification)
    rows = list(BodyTextSSOT(tmp_path).iter_serenedb_documents(detail, handoff=tmp_path/"prepared/handoff.json"))
    assert [row["text_status"] for row in rows] == ["available", "excluded", "unsupported"]
    retained["sha256"] = "a"*64
    verification.write_text(json.dumps(dict(export_parquet=retained)))
    with pytest.raises(ValueError, match="different export"):
        module.prepare(**arguments, output=tmp_path/"wrong-export")
    inventory.write_text(json.dumps(dict(body_sha256="different-original"))+"\n")
    inventory_manifest.write_text(json.dumps(dict(inventory=old_pin(inventory))))
    with pytest.raises(ValueError, match="missing from recovery inventory"):
        module.prepare(**arguments, output=tmp_path/"lost-obligation")
