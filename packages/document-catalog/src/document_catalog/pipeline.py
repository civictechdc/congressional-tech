"""One writer owns a run; bounded worker processes own distinct source documents."""

from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import json
import multiprocessing
from pathlib import Path
import uuid

from .capture import capture
from .config import load_config
from .grouping import group_pages
from .geometry import overlap
from .inputs import discover, ingest
from .layout import model_identity, predict
from .observations import anchors, recognize, text_quality
from .plans import coverage, structural_plan, validate_batch
from .reviews import layer_reviews, validate_review_batch
from .store import Store, atomic_json, catalog_lock, identity, now, versions


def process_document(arguments):
    root, document, config, environment, model, retry = arguments
    store = Store(root)
    document = deepcopy(document)
    document["attempts"], hits, calls = [], 0, 0
    pages = []
    if document["status"] == "unsupported_format":
        document.update(page_count=None, page_ids=[])
        document["context_sha256"] = identity({"source_sha256": document["source_sha256"], "status": document["status"]})
        return document, pages, {"cache_hits": 0, "new_attempts": 0}

    def stage(name, inputs, settings, produce):
        nonlocal hits, calls
        receipt, ref, cached = store.stage(name, inputs, settings, environment, produce, retry)
        document["attempts"].append(ref)
        hits += int(cached)
        calls += int(not cached)
        return receipt, ref

    receipt, capture_ref = stage("capture", document["source"], config["capture"], lambda: capture(store, document, config["capture"]))
    if receipt["status"] == "failed":
        document.update(status="capture_failed", error=receipt["error"], page_count=None, page_ids=[])
    else:
        for captured in receipt["data"]["pages"]:
            page = deepcopy(captured)
            page["capture_attempt"] = capture_ref
            page["issues"] = []
            if page["status"] != "captured":
                page["issues"].append("capture_failed")
                page["evidence_sha256"] = identity(page)
                pages.append(page)
                continue
            observation_inputs = {"capture_attempt": capture_ref, "page_id": page["page_id"], "image": page["image"],
                                  "native_sha256": identity(page["lines"])}
            text_receipt, text_ref = stage("text", observation_inputs, config["ocr"], lambda: recognize(store, page, config["ocr"]))
            page["text_attempt"] = text_ref
            if text_receipt["status"] == "success":
                page["text"] = text_receipt["data"]
            else:
                page["text"] = {"status": "failed", "error": text_receipt["error"], "lines": page["lines"],
                                "text_source": "native_unverified_fallback", "needs_recognition": True,
                                "quality": text_quality("\n".join(line["text"] for line in page["lines"]))}
                page["issues"].append("ocr_failed")
            if page["text"].get("needs_recognition"):
                page["issues"].append("recognition_needed")
            if page["text"]["quality"]["flags"]:
                page["issues"].append("text_quality_symptoms")
            if not page["text"]["lines"]:
                page["issues"].append("empty_text_nonblank" if page["render_grayscale_variance"] > 1 else "blank_candidate")
            layout_receipt, layout_ref = stage("layout", {"image": page["image"], "model": model}, config["layout"],
                                                lambda: predict(store, page, config["layout"], model))
            page["layout_attempt"] = layout_ref
            page["layout"] = layout_receipt["data"] if layout_receipt["status"] == "success" else {
                "status": "failed", "regions": [], "error": layout_receipt["error"]}
            if page["layout"]["status"] == "failed":
                page["issues"].append("layout_failed")
            page["anchors"] = anchors(page["text"]["lines"], config["category"])
            page["semantic_role"] = "unknown"
            page["evidence_sha256"] = identity({k: v for k, v in page.items() if k != "anchors"})
            pages.append(page)
        document.update(status="partial" if any(p["issues"] and p["issues"] != ["blank_candidate"] for p in pages) else "processed",
                        page_count=receipt["data"]["page_count"], page_ids=[p["page_id"] for p in pages])
    document["context_sha256"] = identity({"source_sha256": document["source_sha256"], "pages": [(p["page_id"], p["evidence_sha256"]) for p in pages],
                                          "status": document["status"]})
    return document, pages, {"cache_hits": hits, "new_attempts": calls}


def summarize(catalog):
    docs, pages, entries = catalog["documents"], catalog["pages"], catalog["source_entries"]
    statuses = Counter(d["status"] for d in docs)
    source_statuses = Counter(e["status"] for e in entries)
    issue_counts = Counter(issue for page in pages for issue in page.get("issues", []))
    partial = any(d["status"] != "processed" for d in docs) or bool(source_statuses["source_failed"])
    return {"status": "no_matches" if not docs and not source_statuses["source_failed"] else ("partial" if partial else "processed"),
        "source_entries": len(entries), "documents": len(docs), "pages": len(pages), "document_statuses": dict(statuses),
        "source_statuses": dict(source_statuses), "page_issues": dict(issue_counts), "groups": len(catalog["groups"]),
        "automatic_unknown_roles": sum(p.get("semantic_role", "unknown") == "unknown" for p in pages),
        "semantic_sections": sum(len(p["sections"]) for p in catalog["plans"]),
        "unresolved_plan_pages": sum(len(p["unresolved_pages"]) for p in catalog["plans"]),
        "review_judgments": len(catalog["reviews"]), "accuracy": "not_established"}


def derive(catalog):
    by_id = {page["page_id"]: page for page in catalog["pages"]}
    plans = {plan["document_id"]: plan for plan in catalog["plans"]}
    for plan in catalog["plans"]:
        plan.update(coverage(plan))
    layer_reviews(catalog)
    profiles, fixtures = [], []
    for group in catalog["groups"]:
        prompt_counts = Counter(a["anchor_id"] for pid in group["members"] for a in by_id[pid].get("anchors", []))
        schemas = sorted({a["schema_ref"] for pid in group["members"] for a in by_id[pid].get("anchors", []) if a.get("schema_ref")})
        profiles.append({"profile_candidate_id": "profile-" + group["group_id"], "group_id": group["group_id"],
                         "status": "candidate_unverified", "schema_refs": schemas, "prompt_occurrences": dict(prompt_counts),
                         "evidence": "geometry group and configured prompt proposals; no field-accuracy claim"})
        for representative in group["representatives"]:
            page = by_id[representative["page_id"]]
            fixtures.append({"fixture_id": identity({"group": group["group_id"], "page": page["page_id"]}),
                "group_id": group["group_id"], **representative, "document_id": page["document_id"],
                "source_sha256": page["source_sha256"], "image": page.get("image"),
                "page_evidence_sha256": page["evidence_sha256"], "plan_context_sha256": plans[page["document_id"]]["context_sha256"],
                "schema_refs": schemas, "expected_fields": None, "gold_status": "unlabeled"})
    for plan in catalog["plans"]:
        for section in plan["sections"]:
            fixtures.append({"fixture_id": identity({"document": plan["document_id"], "section": section}),
                "document_id": plan["document_id"], "source_sha256": plan["source_sha256"], "section_id": section["section_id"],
                "parts": section["parts"], "schema_refs": [section["schema_ref"]] if section.get("schema_ref") else [],
                "reason": "imported_section_plan", "provenance": plan["provenance"], "expected_fields": None, "gold_status": "unlabeled"})
    section_groups = {}
    for plan in catalog["plans"]:
        for section in plan["sections"]:
            shape = [{"bbox_grid": [round(v * catalog["config"]["grouping"]["grid_size"]) for v in part["bbox"]],
                      "anchors": sorted({a["anchor_id"] for a in by_id[part["page_id"]].get("anchors", [])
                                         if overlap(a["bbox"], part["bbox"])})}
                     for part in section["parts"]]
            gid = "sg-" + identity(shape)
            group = section_groups.setdefault(gid, {"section_group_id": gid, "status": "section_pattern_candidate", "shape": shape,
                "method": "ordered part geometry quantized to configured grid plus stable prompt evidence; semantic roles excluded", "members": []})
            group["members"].append({"document_id": plan["document_id"], "section_id": section["section_id"],
                "section_sha256": identity(section), "plan_context_sha256": plan["context_sha256"], "schema_ref": section.get("schema_ref"),
                "provenance_kind": plan["provenance"]["kind"], "judgment_history": plan["judgment_history"]})
    catalog["section_groups"] = list(section_groups.values())
    for document in catalog["documents"]:
        if not document["page_ids"]:
            fixtures.append({"fixture_id": identity({"document": document["document_id"], "status": document["status"]}),
                "document_id": document["document_id"], "source_sha256": document["source_sha256"], "source": document["source"],
                "reason": document["status"], "format": document["format"], "expected_fields": None, "gold_status": "unlabeled"})
    for group in catalog["section_groups"]:
        profiles.append({"profile_candidate_id": "profile-" + group["section_group_id"], "section_group_id": group["section_group_id"],
                         "status": "section_candidate_unverified", "schema_refs": sorted({m["schema_ref"] for m in group["members"] if m["schema_ref"]}),
                         "supporting_sections": group["members"], "expected_fields": None})
    catalog["profile_candidates"], catalog["fixtures"] = profiles, fixtures
    catalog["summary"] = summarize(catalog)
    catalog["summary"].update(section_groups=len(catalog["section_groups"]),
        section_provenance_counts=dict(Counter(plan["provenance"]["kind"] for plan in catalog["plans"] for _ in plan["sections"])),
        review_application_states=dict(Counter(j["application_state"] for j in catalog["reviews"])))


def load_catalog(root):
    store = Store(root)
    current = json.loads((store.root / "current.json").read_text())
    return store, store.json(current["catalog"]), current


def publish(store, catalog):
    from .exports import export_catalog
    derive(catalog)
    catalog_ref = store.put_json(catalog)
    from .validation import validate_catalog
    validation = validate_catalog(store, catalog)
    if not validation["valid"]:
        raise ValueError(f"Catalog validation failed before publication: {validation['errors']}")
    export_path, export_manifest = export_catalog(store, catalog, catalog_ref)
    current = {"catalog": catalog_ref, "export_path": export_path, "export_manifest": export_manifest, "catalog_id": catalog["catalog_id"]}
    atomic_json(store.root / "current.json", current)
    return current


def run(paths, output, config=None, manifest=None, workers=2, retry_failed=False):
    if not isinstance(workers, int) or not 1 <= workers <= 32:
        raise ValueError("workers must be between 1 and 32")
    config = load_config(config)
    output = Path(output).resolve()
    for supplied in paths:
        path = Path(supplied).resolve()
        if path.is_dir() and output.is_relative_to(path):
            raise ValueError("Catalog output must be outside discovered input directories")
    with catalog_lock(output):
        store, environment = Store(output), versions()
        sources = discover(paths, manifest)
        documents, entries = ingest(store, sources, config)
        model = model_identity(config["layout"])
        args = [(str(output), doc, config, environment, model, retry_failed) for doc in documents]
        if workers == 1:
            processed = list(map(process_document, args))
        else:
            with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
                processed = list(pool.map(process_document, args, chunksize=1))
        documents = [item[0] for item in processed]
        pages = [page for item in processed for page in item[1]]
        plans = [structural_plan(doc, [p for p in pages if p["document_id"] == doc["document_id"]], config["category"])
                 for doc in documents if doc["page_count"] is not None]
        catalog = {"version": 1, "catalog_id": uuid.uuid4().hex, "created_at": now(), "config": config, "environment": environment,
            "source_entries": entries, "documents": documents, "pages": pages, "plans": plans,
            "groups": group_pages(pages, config["grouping"], config["category"]), "reviews": [], "plan_imports": [],
            "invocation": {"workers": workers, "retry_failed": retry_failed,
                "cache_hits": sum(item[2]["cache_hits"] for item in processed), "new_attempts": sum(item[2]["new_attempts"] for item in processed)}}
        # Carry history across reruns, but only apply judgments/plans whose
        # measured context still matches. Stale judgments remain visible.
        if (output / "current.json").exists():
            _, prior, previous = load_catalog(output)
            catalog["previous_catalog"] = previous["catalog"]
            catalog["reviews"] = prior["reviews"]
            catalog["plan_imports"] = prior["plan_imports"]
            previous_plans = {p["document_id"]: p for p in prior["plans"]}
            for index, plan in enumerate(catalog["plans"]):
                old = previous_plans.get(plan["document_id"])
                if old and old["context_sha256"] == plan["context_sha256"]:
                    catalog["plans"][index] = old
        return publish(store, catalog)


def import_plans(root, batch):
    if isinstance(batch, (str, Path)):
        batch = json.loads(Path(batch).read_text())
    with catalog_lock(root):
        store, catalog, current = load_catalog(root)
        validate_batch(batch, catalog, current["catalog"]["sha256"])
        # Whole-batch validation occurs before any persisted mutation.
        batch_ref = store.put_json(batch)
        plans = {plan["document_id"]: plan for plan in catalog["plans"]}
        for imported in batch["plans"]:
            existing = plans[imported["document_id"]]
            history = existing["judgment_history"] + [{"batch": batch_ref, "kind": batch["provenance"]["kind"]}]
            # A later model prediction cannot silently displace a manual plan.
            if existing["provenance"]["kind"] == "manual" and batch["provenance"]["kind"] == "model":
                existing["judgment_history"] = history
                continue
            existing.update({"sections": imported["sections"], "unresolved_pages": imported["unresolved_pages"],
                             "provenance": batch["provenance"], "judgment_history": history,
                             "status": "manual_plan" if batch["provenance"]["kind"] == "manual" else "model_proposed_sections"})
        catalog["plan_imports"].append(batch_ref)
        catalog.update(catalog_id=uuid.uuid4().hex, created_at=now(), previous_catalog=current["catalog"])
        return publish(store, catalog)


def review(root, batch):
    if isinstance(batch, (str, Path)):
        batch = json.loads(Path(batch).read_text())
    with catalog_lock(root):
        store, catalog, current = load_catalog(root)
        validate_review_batch(batch, catalog, current["catalog"]["sha256"])
        ref = store.put_json(batch)
        for index, judgment in enumerate(batch["judgments"]):
            catalog["reviews"].append({**judgment, "judgment_id": identity({"batch": ref, "index": index}),
                                       "reviewer": batch["reviewer"], "method": batch["method"],
                                       "created_at": batch["created_at"], "batch": ref})
        catalog.update(catalog_id=uuid.uuid4().hex, created_at=now(), previous_catalog=current["catalog"])
        return publish(store, catalog)
