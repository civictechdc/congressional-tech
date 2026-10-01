from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys

import fitz
import pytest

from document_catalog.cli import main
from document_catalog.config import load_config
from document_catalog.geometry import valid_box
from document_catalog.grouping import group_pages
from document_catalog.observations import text_quality
from document_catalog.pipeline import import_plans, load_catalog, review, run
from document_catalog.reviews import targets
from document_catalog.store import IntegrityError, Store, canonical, digest
from document_catalog.validation import validate
from document_catalog.vision import normalize


def pdf(path, value="001", rotation=0, pages=2):
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page(width=612, height=792)
        page.insert_text((48, 60), "Laboratory report" if index == 0 else "Laboratory continuation")
        page.insert_text((48, 120), "Sample identification: " + value)
        page.insert_text((48, 300), "Results: measured concentration is 4 mg/L for this specimen.")
        page.insert_text((48, 540), "Quality control: measurements approved after local inspection.")
        page.draw_rect(fitz.Rect(45, 110, 500, 150))
        page.draw_line((45, 330), (500, 330))
        page.set_rotation(rotation)
    doc.save(path)
    doc.close()


@pytest.fixture
def category():
    return load_config({"category": {"id": "laboratory", "version": "1", "roles": ["results", "quality"],
        "anchors": [{"id": "results", "pattern": "^Results:", "role": "results", "schema_ref": "report"}],
        "schemas": {"report": {"format": "json-schema", "uri": "urn:example:lab:v1"}}}, "ocr": {"mode": "never"}})


@pytest.fixture
def catalog(tmp_path, category):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    pdf(inputs / "one.pdf")
    pdf(inputs / "two.pdf", "999")
    root = tmp_path / "catalog"
    run([inputs], root, category, workers=1)
    return inputs, root


def plan_batch(root, kind="model"):
    _, catalog, current = load_catalog(root)
    plan = catalog["plans"][0]
    pages = [p for p in catalog["pages"] if p["document_id"] == plan["document_id"]]
    parts = [{"page_id": p["page_id"], "bbox": [0, 0.2, 1, 0.8],
              "evidence_refs": [next(line["id"] for line in p["text"]["lines"] if line["text"].startswith("Results:"))]} for p in pages]
    section = {"section_id": "measurements", "role": "results", "schema_ref": "report", "parts": parts,
               "continuations": [{"from_part": i, "to_part": i + 1, "reason": "Repeated measured section prompt in adjacent source pages",
                                  "from_evidence_refs": parts[i]["evidence_refs"], "to_evidence_refs": parts[i + 1]["evidence_refs"]}
                                 for i in range(len(parts) - 1)]}
    return {"version": 1, "base_catalog_sha256": current["catalog"]["sha256"],
            "provenance": {"kind": kind, "actor": "fixture-author", "method": "constructed-prediction-fixture", "created_at": "2026-09-30T00:00:00Z",
                           "provider": "test", "model": "fixture-v1", "prompt": "Locate the results section", "raw_output": {"section": section}},
            "plans": [{"document_id": plan["document_id"], "source_sha256": plan["source_sha256"], "context_sha256": plan["context_sha256"],
                       "sections": [section], "unresolved_pages": []}]}


def review_batch(root, target_type="page"):
    _, catalog, current = load_catalog(root)
    (kind, target), context = next((key, value) for key, value in targets(catalog).items() if key[0] == target_type)
    return {"version": 1, "base_catalog_sha256": current["catalog"]["sha256"],
            "reviewer": {"kind": "human", "id": "reviewer-a"}, "method": "visual inspection", "created_at": "2026-09-30T00:00:00Z",
            "judgments": [{"target_type": kind, "target_id": target, "context_sha256": context, "decision": "accept", "reason": "Visible evidence checked"}]}


def test_full_pipeline_generic_geometry_exports_and_resume(catalog):
    inputs, root = catalog
    store, first, current = load_catalog(root)
    assert first["summary"]["pages"] == 4
    assert first["summary"]["automatic_unknown_roles"] == 4
    assert all(p["role_proposals"] for p in first["plans"])
    assert all(p["sections"] == [] for p in first["plans"])
    assert all(p["unassigned_region_ids"] for p in first["plans"])
    assert any(p["drawings"] for p in first["pages"])
    assert any(a["bbox"][1] > 0.25 for p in first["pages"] for a in p["anchors"])
    assert validate(root)["valid"]
    export = root / current["export_path"]
    assert (export / "report.html").read_text().startswith("<!doctype html>")
    assert "data:image/jpeg;base64," in (export / "report.html").read_text()
    import pyarrow.parquet as pq
    assert pq.read_table(export / "pages.parquet").num_rows == 4
    attempts = [ref for doc in first["documents"] for ref in doc["attempts"]]
    run([inputs], root, first["config"], workers=1)
    _, second, _ = load_catalog(root)
    assert second["invocation"]["new_attempts"] == 0
    assert second["invocation"]["cache_hits"] == 10
    assert attempts == [ref for doc in second["documents"] for ref in doc["attempts"]]
    assert (export / "catalog.json").read_bytes() == canonical(first)


def test_dedup_gzip_aliases_unsupported_broken_and_missing(tmp_path):
    one = tmp_path / "one.pdf"
    pdf(one, pages=1)
    zipped = tmp_path / "source.body.gz"
    zipped.write_bytes(gzip.compress(one.read_bytes()))
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\nnot a readable document")
    other = tmp_path / "data.xml"
    other.write_text("<not-a-page/>")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sources": [
        {"path": str(one), "sha256": digest(one.read_bytes()), "bytes": one.stat().st_size},
        {"path": str(zipped), "filename": "alias.pdf"}, {"path": str(broken)}, {"path": str(other)},
        {"path": str(tmp_path / "missing.pdf")},
    ]}))
    root = tmp_path / "out"
    run([], root, {"ocr": {"mode": "never"}}, manifest, workers=1)
    _, cat, _ = load_catalog(root)
    assert len(cat["documents"]) == 3
    assert sorted(d["status"] for d in cat["documents"]) == ["capture_failed", "processed", "unsupported_format"]
    good = next(d for d in cat["documents"] if d["status"] == "processed")
    assert len(good["aliases"]) == 2
    assert good["aliases"][0]["transport_sha256"] != good["aliases"][1]["transport_sha256"]
    assert cat["summary"]["source_statuses"]["source_failed"] == 1
    assert validate(root)["valid"]


def test_no_match_is_exported_and_not_a_missing_document(catalog, tmp_path):
    inputs, _ = catalog
    root = tmp_path / "none"
    run([inputs], root, {"selection": {"filename_regex": "never-match"}}, workers=1)
    _, cat, _ = load_catalog(root)
    assert cat["summary"]["status"] == "no_matches"
    assert cat["source_entries"] and all(e["status"] == "no_match" for e in cat["source_entries"])
    assert cat["pages"] == [] and cat["documents"] == []
    assert validate(root)["valid"]


def test_changed_input_and_config_invalidate_stages(catalog):
    inputs, root = catalog
    _, original, _ = load_catalog(root)
    (inputs / "one.pdf").unlink()
    pdf(inputs / "one.pdf", "changed")
    run([inputs], root, original["config"], workers=1)
    _, changed, _ = load_catalog(root)
    assert changed["invocation"]["new_attempts"] == 5
    assert changed["invocation"]["cache_hits"] == 5
    configuration = deepcopy(original["config"])
    configuration["capture"]["render_width"] = 800
    run([inputs], root, configuration, workers=1)
    _, changed_config, _ = load_catalog(root)
    assert changed_config["invocation"]["new_attempts"] == 10


def test_raw_digest_tamper_is_rejected_on_resume(catalog):
    inputs, root = catalog
    store, cat, _ = load_catalog(root)
    store.path(cat["pages"][0]["native"]["path"]).write_bytes(b"tampered evidence")
    assert not validate(root)["valid"]
    with pytest.raises(IntegrityError):
        run([inputs], root, cat["config"], workers=1)


def test_rotated_geometry_and_blank_drawings(tmp_path):
    source = tmp_path / "rotated.pdf"
    pdf(source, rotation=90, pages=1)
    root = tmp_path / "out"
    run([source], root, {"ocr": {"mode": "never"}}, workers=1)
    _, cat, _ = load_catalog(root)
    page = cat["pages"][0]
    assert page["size_points"] == [792, 612]
    assert page["transform"]["rotation_degrees"] == 90
    assert all(valid_box(line["bbox"]) for line in page["lines"])
    assert any(d["bbox"] is None for d in page["drawings"])


def test_grouping_excludes_values_and_uncertain_roles(catalog):
    _, root = catalog
    _, cat, _ = load_catalog(root)
    before = group_pages(cat["pages"], cat["config"]["grouping"], cat["config"]["category"])
    for page in cat["pages"]:
        page["semantic_role"] = page["page_id"]
        for line in page["text"]["lines"]:
            line["text"] = "totally different filled-in information"
    after = group_pages(cat["pages"], cat["config"]["grouping"], cat["config"]["category"])
    assert [g["members"] for g in before] == [g["members"] for g in after]


def test_plan_import_partial_page_multi_page_and_section_profiles(catalog):
    _, root = catalog
    import_plans(root, plan_batch(root))
    _, cat, _ = load_catalog(root)
    plan = next(p for p in cat["plans"] if p["sections"])
    assert plan["status"] == "model_proposed_sections"
    assert len(plan["sections"][0]["parts"]) == 2
    assert plan["unresolved_pages"] == []
    assert plan["unassigned_region_ids"]  # top-of-page content is still unresolved
    assert plan["segmentation_completeness"] == "unresolved"
    assert cat["section_groups"]
    assert any(p.get("section_group_id") for p in cat["profile_candidates"])
    assert any(f.get("section_id") for f in cat["fixtures"])
    assert validate(root)["valid"]


@pytest.mark.parametrize("damage", ["stale", "duplicate", "box", "missing-link", "bad-evidence", "other-document", "bad-role", "missing-raw", "non-object"])
def test_plan_batch_rejects_before_any_mutation(catalog, damage):
    _, root = catalog
    batch = plan_batch(root)
    if damage == "stale": batch["base_catalog_sha256"] = "0" * 64
    elif damage == "duplicate": batch["plans"].append(deepcopy(batch["plans"][0]))
    elif damage == "box": batch["plans"][0]["sections"][0]["parts"][0]["bbox"] = [0, 0, 2, 1]
    elif damage == "missing-link": batch["plans"][0]["sections"][0]["continuations"] = []
    elif damage == "bad-evidence": batch["plans"][0]["sections"][0]["parts"][0]["evidence_refs"] = ["invented"]
    elif damage == "other-document": batch["plans"][0]["sections"][0]["parts"][0]["page_id"] = "unknown-page"
    elif damage == "bad-role": batch["plans"][0]["sections"][0]["role"] = "not-configured"
    elif damage == "missing-raw": del batch["provenance"]["raw_output"]
    elif damage == "non-object": batch["plans"].append("bad")
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        import_plans(root, batch)
    after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert before == after


def test_review_history_active_superseded_stale_and_model_manual_distinction(catalog):
    inputs, root = catalog
    import_plans(root, plan_batch(root))
    review(root, review_batch(root, "section"))
    second = review_batch(root, "section")
    second["reviewer"] = {"kind": "agent", "id": "agent-review"}
    second["judgments"][0]["decision"] = "uncertain"
    review(root, second)
    _, cat, _ = load_catalog(root)
    assert [j["application_state"] for j in cat["reviews"]] == ["superseded", "active"]
    edited = plan_batch(root, "manual")
    edited["plans"][0]["sections"][0]["parts"][0]["bbox"][3] = 0.9
    import_plans(root, edited)
    _, cat, _ = load_catalog(root)
    assert all(j["application_state"] == "stale" for j in cat["reviews"])
    import_plans(root, plan_batch(root, "model"))
    _, cat, _ = load_catalog(root)
    plan = next(p for p in cat["plans"] if p["sections"])
    assert plan["provenance"]["kind"] == "manual"
    assert plan["sections"][0]["parts"][0]["bbox"][3] == 0.9
    assert len(plan["judgment_history"]) == 3
    run([inputs], root, cat["config"], workers=1)
    _, resumed, _ = load_catalog(root)
    assert resumed["reviews"] == cat["reviews"]
    assert resumed["summary"]["automatic_unknown_roles"] == 4
    assert validate(root)["valid"]


def test_review_batch_validation_is_atomic(catalog):
    _, root = catalog
    batch = review_batch(root)
    batch["judgments"].append(deepcopy(batch["judgments"][0]))
    before = (root / "current.json").read_bytes()
    with pytest.raises(ValueError, match="duplicate"):
        review(root, batch)
    assert (root / "current.json").read_bytes() == before


def test_immutable_atomic_publish_duplicate_workers_and_abandoned_temp(tmp_path, monkeypatch):
    store = Store(tmp_path)
    data = b"a shared page raster" * 100000
    with ThreadPoolExecutor(max_workers=8) as pool:
        refs = list(pool.map(lambda _: store.put(data), range(16)))
    assert all(ref == refs[0] for ref in refs)
    assert store.read(refs[0]) == data
    original = os.link
    def interrupted(source, target):
        raise OSError("simulated interrupted publication")
    monkeypatch.setattr(os, "link", interrupted)
    with pytest.raises(OSError):
        store.put(b"interrupted new bytes")
    assert not list(tmp_path.rglob(".pending-*"))
    monkeypatch.setattr(os, "link", original)
    ref = store.put(b"interrupted new bytes")
    assert store.read(ref) == b"interrupted new bytes"


def test_failed_and_partial_stage_retry_retains_attempts(tmp_path):
    store, attempts = Store(tmp_path), []
    def failing():
        attempts.append(1)
        raise RuntimeError("transient")
    failed, old, cached = store.stage("capture", {}, {}, {}, failing)
    assert failed["status"] == "failed" and not cached
    again, ref, cached = store.stage("capture", {}, {}, {}, failing)
    assert cached and ref == old and len(attempts) == 1
    partial, ref, _ = store.stage("capture", {}, {}, {}, lambda: {"stage_status": "partial", "pages": []}, True)
    assert partial["previous_attempt"] == old
    success, current, _ = store.stage("capture", {}, {}, {}, lambda: {"stage_status": "success", "pages": []}, True)
    assert success["previous_attempt"] == ref and store.json(old) == failed


def test_vision_coordinates_and_encoding_symptoms():
    page = {"image": {"sha256": "expected"}, "render_pixels": [100, 200]}
    raw = {"engine": "apple-vision", "image_sha256": "expected", "render_pixels": [100, 200],
           "observations": [{"text": 'Quoted "value" with\ttab', "confidence": 0.9, "bbox": [0.1, 0.2, 0.4, 0.3]}]}
    line = normalize(raw, page)[0]
    assert line["bbox"] == pytest.approx([0.1, 0.5, 0.5, 0.8])
    assert line["text"] == 'Quoted "value" with\ttab'
    assert text_quality("abc" + "\x01" * 200)["flags"] == ["unexpected_controls"]
    raw["image_sha256"] = "stale"
    with pytest.raises(ValueError): normalize(raw, page)


def test_two_worker_cli_and_partial_exit(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    pdf(inputs / "good.pdf", pages=1)
    (inputs / "unsupported.txt").write_text("not a PDF")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"ocr": {"mode": "never"}}))
    completed = subprocess.run([sys.executable, "-m", "document_catalog", "run", "--input", str(inputs), "--output", str(tmp_path / "out"),
                                "--config", str(config), "--workers", "2"], text=True, capture_output=True,
                               env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")})
    assert completed.returncode == 2, completed.stderr
    assert json.loads(completed.stdout)["summary"]["status"] == "partial"
    assert validate(tmp_path / "out")["valid"]


def test_configuration_rejects_unknowns_and_bad_references():
    with pytest.raises(Exception): load_config({"ocr": {"mode": "tesseract"}})
    with pytest.raises(Exception): load_config({"category": {"anchors": [{"id": "x", "pattern": "x", "role": "undeclared"}]}})


def test_always_ocr_does_not_reuse_native_and_retains_raw(catalog, monkeypatch):
    from document_catalog.observations import recognize
    _, root = catalog
    store, cat, _ = load_catalog(root)
    page = cat["pages"][0]
    calls = []
    def response(*args, **kwargs):
        calls.append(args)
        raw = {"engine": "apple-vision", "image_sha256": page["image"]["sha256"], "render_pixels": page["render_pixels"],
               "observations": [{"text": "Recognized separate evidence", "confidence": 0.8, "bbox": [0.1, 0.1, 0.5, 0.1]}]}
        return subprocess.CompletedProcess(args, 0, json.dumps(raw), "")
    monkeypatch.setattr(subprocess, "run", response)
    result = recognize(store, page, {"mode": "always", "languages": ["en-US"], "timeout_seconds": 1})
    assert len(calls) == 1 and result["text_source"] == "apple-vision"
    assert result["lines"] != page["lines"]
    assert store.json(result["raw"])["image_sha256"] == page["image"]["sha256"]


def test_ocr_failure_retains_unverified_native_and_diagnostic(catalog, monkeypatch):
    import document_catalog.pipeline as pipeline
    inputs, root = catalog
    _, cat, _ = load_catalog(root)
    def response(*args, **kwargs):
        return subprocess.CompletedProcess(args, 17, "", "missing local Vision framework")
    monkeypatch.setattr(subprocess, "run", response)
    configuration = deepcopy(cat["config"])
    configuration["ocr"]["mode"] = "always"
    pipeline.run([inputs], root, configuration, workers=1)
    _, failed, _ = load_catalog(root)
    assert all(p["text"]["text_source"] == "native_unverified_fallback" for p in failed["pages"])
    assert all("exit 17" in p["text"]["error"] and "missing local Vision" in p["text"]["error"] for p in failed["pages"])
    assert all(p["text"]["lines"] == p["lines"] for p in failed["pages"])
    assert failed["summary"]["status"] == "partial"


def test_partial_page_capture_is_retried_only_on_request(tmp_path, monkeypatch):
    import document_catalog.pipeline as pipeline
    source = tmp_path / "source.pdf"
    pdf(source, pages=1)
    root = tmp_path / "out"
    original = pipeline.capture
    count = []
    def transient(store, document, config):
        count.append(1)
        if len(count) == 1:
            return {"stage_status": "partial", "page_count": 1, "pages": [{"page_id": document["document_id"] + ":p1",
                "document_id": document["document_id"], "source_sha256": document["source_sha256"], "page_number": 1,
                "status": "capture_failed", "error": "transient page failure"}]}
        return original(store, document, config)
    monkeypatch.setattr(pipeline, "capture", transient)
    configuration = {"ocr": {"mode": "never"}}
    pipeline.run([source], root, configuration, workers=1)
    pipeline.run([source], root, configuration, workers=1)
    assert len(count) == 1
    pipeline.run([source], root, configuration, workers=1, retry_failed=True)
    _, cat, _ = load_catalog(root)
    assert len(count) == 2
    assert cat["pages"][0]["status"] == "captured"
    assert validate(root)["valid"]


@pytest.mark.skipif(not os.environ.get("DOCUMENT_CATALOG_LIVE_PDF"), reason="Set explicit retained PDF and local model path to exercise providers")
def test_real_local_providers(tmp_path, monkeypatch):
    # pytest's pythonpath setting affects this process only. Make the source
    # package available to the intentionally isolated OCR subprocess as well.
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1] / "src"))
    source = Path(os.environ["DOCUMENT_CATALOG_LIVE_PDF"])
    model = os.environ["DOCUMENT_CATALOG_LOCAL_MODEL"]
    run([source], tmp_path / "live", {"ocr": {"mode": "always"}, "layout": {"provider": "docling", "artifacts_path": model}}, workers=1)
    _, catalog, _ = load_catalog(tmp_path / "live")
    assert catalog["pages"]
    assert all(p["text"]["status"] == "ocr_success" and p["layout"]["status"] == "predicted" for p in catalog["pages"])
    assert validate(tmp_path / "live")["valid"]
