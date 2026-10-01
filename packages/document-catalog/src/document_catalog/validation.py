"""Check identity, retained bytes, accounting, geometry and section consistency."""

from collections import Counter

from .geometry import valid_box
from .plans import coverage, validate_plan
from .store import identity


def validate_catalog(store, catalog):
    errors = []
    try:
        store.verify_refs(catalog)
    except Exception as exc:
        errors.append(f"Evidence integrity: {exc}")
    docs = {d["document_id"]: d for d in catalog["documents"]}
    pages = {p["page_id"]: p for p in catalog["pages"]}
    entries = {e["source_entry_id"]: e for e in catalog["source_entries"]}
    if len(docs) != len(catalog["documents"]) or len(pages) != len(catalog["pages"]) or len(entries) != len(catalog["source_entries"]):
        errors.append("Duplicate document/page/source identity")
    for entry in entries.values():
        if entry["status"] == "ingested" and entry["document_id"] not in docs:
            errors.append("Ingested source entry lacks document")
    for doc in docs.values():
        if doc["source_sha256"] != doc["source"]["sha256"] or doc["document_id"] != "d-" + doc["source_sha256"]:
            errors.append("Document identity differs from source bytes")
        if any(e not in entries or entries[e]["document_id"] != doc["document_id"] for e in doc["source_entries"]):
            errors.append("Document alias/source-entry accounting mismatch")
        actual = sorted((p for p in pages.values() if p["document_id"] == doc["document_id"]), key=lambda p: p["page_number"])
        if [p["page_id"] for p in actual] != doc["page_ids"]:
            errors.append("Document page sequence differs from page catalog")
        if doc["page_count"] is not None and [p["page_number"] for p in actual] != list(range(1, doc["page_count"] + 1)):
            errors.append("Document page count/sequence is incomplete")
    for page in pages.values():
        if page["document_id"] not in docs:
            errors.append("Page references unknown document")
        if page["status"] != "captured":
            continue
        if page["source_sha256"] != docs[page["document_id"]]["source_sha256"]:
            errors.append("Page source digest mismatch")
        for row in page["lines"] + page["text"]["lines"] + page["layout"]["regions"] + page["anchors"]:
            if not valid_box(row["bbox"]):
                errors.append(f"Invalid page box: {page['page_id']}")
        if identity({k: v for k, v in page.items() if k not in {"anchors", "evidence_sha256"}}) != page["evidence_sha256"]:
            errors.append("Page evidence digest mismatch")
    membership = Counter(pid for group in catalog["groups"] for pid in group["members"])
    if set(membership) != set(pages) or any(n != 1 for n in membership.values()):
        errors.append("Each page must belong to exactly one candidate/unknown group")
    for group in catalog["groups"]:
        if any(rep["page_id"] not in group["members"] for rep in group["representatives"]):
            errors.append("Representative is not a group member")
    plan_ids = [plan["document_id"] for plan in catalog["plans"]]
    if len(set(plan_ids)) != len(plan_ids) or set(plan_ids) != {d["document_id"] for d in docs.values() if d["page_count"] is not None}:
        errors.append("Plan/document accounting mismatch")
    for plan in catalog["plans"]:
        try:
            validate_plan(plan, catalog)
            if any(plan.get(key) != value for key, value in coverage(plan).items()):
                errors.append("Plan region coverage differs from measured coverage")
        except Exception as exc:
            errors.append(f"Invalid section plan: {exc}")
    return {"version": 1, "valid": not errors, "errors": errors,
            "checks": ["source and artifact digests", "aliases and source accounting", "page completeness",
                       "normalized geometry", "group membership", "section bounds/references/continuations", "unassigned regions"],
            "does_not_prove": ["OCR accuracy", "semantic accuracy", "proven templates", "field extraction accuracy"]}


def validate(root):
    from .pipeline import load_catalog
    store, catalog, current = load_catalog(root)
    result = validate_catalog(store, catalog)
    try:
        manifest = store.json(current["export_manifest"])
        for ref in manifest["files"]:
            store.read(ref)
    except Exception as exc:
        result["valid"] = False
        result["errors"].append(f"Export integrity: {exc}")
    result["summary"] = catalog["summary"]
    return result
