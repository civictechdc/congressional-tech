"""Measured structural plans and strict, source-grounded semantic-plan import.

Unconfigured semantic sections stay empty. Anchor boxes mark prompts, never
answer extents. Imported sections can span regions or pages, with explicit
continuation evidence. Schema references bind future extraction; they do not
run or validate field extraction.
"""

from .geometry import overlap, valid_box
from .store import identity


def structural_plan(document, pages, category):
    regions, order = [], []
    for page in pages:
        candidates = page.get("layout", {}).get("regions", [])
        source = "docling_prediction"
        if not candidates:
            candidates = page.get("text", {}).get("lines", [])
            source = page.get("text", {}).get("text_source", "unknown")
        current = []
        for item in candidates:
            region = {"region_id": f"{page['page_id']}:{item['id']}", "page_id": page["page_id"],
                      "bbox": item["bbox"], "source": source, "source_item_id": item["id"],
                      "layout_label": item.get("label"), "semantic_role": None,
                      "bounds_meaning": "observed_text_or_predicted_layout_region"}
            current.append(region)
        current.sort(key=lambda r: (r["bbox"][1], r["bbox"][0], r["region_id"]))
        regions.extend(current)
        order.extend(r["region_id"] for r in current)
    context = identity({"source_sha256": document["source_sha256"], "category": category,
                        "pages": [(p["page_id"], p["evidence_sha256"]) for p in pages]})
    return {"version": 1, "document_id": document["document_id"], "source_sha256": document["source_sha256"],
        "context_sha256": context, "status": "semantic_sections_unresolved", "provenance": {"kind": "automatic_measurements"},
        "regions": regions, "reading_order": order,
        "drawing_primitives": [{"page_id": p["page_id"], "drawings": p.get("drawings", [])} for p in pages if p.get("drawings")],
        "reading_order_method": "page order then top/left coordinates; candidate only, columns may need review",
        "page_sequence": [p["page_id"] for p in pages],
        "page_relationships": [{"from_page": left["page_id"], "to_page": right["page_id"],
                                "relation": "adjacent_in_source", "semantic_continuation": "unknown"} for left, right in zip(pages, pages[1:])],
        "role_proposals": [{"page_id": p["page_id"], **a} for p in pages for a in p.get("anchors", [])],
        "sections": [], "unresolved_pages": [p["page_id"] for p in pages], "judgment_history": []}


def nonempty(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} requires a nonempty string")


def validate_provenance(provenance):
    if not isinstance(provenance, dict) or provenance.get("kind") not in {"model", "manual"}:
        raise ValueError("Plan provenance.kind must be model or manual")
    for field in ["actor", "method", "created_at"]:
        nonempty(provenance.get(field), f"provenance.{field}")
    if provenance["kind"] == "model":
        for field in ["provider", "model", "prompt"]:
            nonempty(provenance.get(field), f"provenance.{field}")
        if "raw_output" not in provenance or provenance["raw_output"] is None:
            raise ValueError("Model plan requires retained raw_output")


def validate_plan(plan, catalog):
    if not isinstance(plan, dict):
        raise ValueError("Each plan must be an object")
    documents = {d["document_id"]: d for d in catalog["documents"]}
    baseline = {p["document_id"]: p for p in catalog["plans"]}
    doc_id = plan.get("document_id")
    if doc_id not in baseline or doc_id not in documents:
        raise ValueError("Plan references an unknown document")
    original = baseline[doc_id]
    for field in ["source_sha256", "context_sha256"]:
        if plan.get(field) != original[field]:
            raise ValueError(f"Plan {field} is stale or incorrect")
    pages = {p["page_id"]: p for p in catalog["pages"] if p["document_id"] == doc_id}
    known_refs = {}
    for pid, page in pages.items():
        known_refs[pid] = {i["id"]: i["bbox"] for i in page.get("text", {}).get("lines", [])}
        known_refs[pid].update({i["id"]: i["bbox"] for i in page.get("layout", {}).get("regions", [])})
    sections = plan.get("sections")
    unresolved = plan.get("unresolved_pages")
    if not isinstance(sections, list) or not isinstance(unresolved, list) or any(pid not in pages for pid in unresolved):
        raise ValueError("Plans require sections and valid unresolved_pages arrays")
    if len(unresolved) != len(set(unresolved)):
        raise ValueError("Duplicate unresolved page")
    section_ids, covered = set(), set()
    category = catalog["config"]["category"]
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("Each section must be an object")
        sid = section.get("section_id")
        nonempty(sid, "section_id")
        if sid in section_ids:
            raise ValueError("Duplicate section_id")
        section_ids.add(sid)
        if section.get("role") is not None and section["role"] not in category["roles"]:
            raise ValueError("Section role is absent from category configuration")
        if section.get("schema_ref") is not None and section["schema_ref"] not in category["schemas"]:
            raise ValueError("Section schema_ref is absent from category configuration")
        parts = section.get("parts")
        if not isinstance(parts, list) or not parts:
            raise ValueError("Section requires at least one part")
        positions = []
        for part in parts:
            if not isinstance(part, dict):
                raise ValueError("Each section part must be an object")
            pid, box = part.get("page_id"), part.get("bbox")
            if pid not in pages or pages[pid]["status"] != "captured" or not valid_box(box):
                raise ValueError("Section part has an invalid page or box")
            refs = part.get("evidence_refs")
            if not isinstance(refs, list) or not refs or len(refs) != len(set(refs)):
                raise ValueError("Every section part requires distinct source evidence_refs")
            if any(ref not in known_refs[pid] or not overlap(box, known_refs[pid][ref]) for ref in refs):
                raise ValueError("Section part evidence must exist and intersect its bounds")
            positions.append((pages[pid]["page_number"], box[1], box[0]))
            covered.add(pid)
        if [p[0] for p in positions] != sorted(p[0] for p in positions):
            raise ValueError("Section parts must follow source page order; within-page order is supplied explicitly")
        if len({(p["page_id"], tuple(p["bbox"])) for p in parts}) != len(parts):
            raise ValueError("Duplicate section part bounds")
        page_numbers = sorted({position[0] for position in positions})
        if page_numbers != list(range(page_numbers[0], page_numbers[-1] + 1)):
            raise ValueError("Section continuation cannot skip source pages")
        links = section.get("continuations", [])
        expected = {(i, i + 1) for i in range(len(parts) - 1)}
        actual = set()
        for link in links:
            if not isinstance(link, dict):
                raise ValueError("Each continuation must be an object")
            pair = (link.get("from_part"), link.get("to_part"))
            if pair not in expected or pair in actual:
                raise ValueError("Continuation links must connect each adjacent part exactly once")
            nonempty(link.get("reason"), "continuation reason")
            for field in ["from_evidence_refs", "to_evidence_refs"]:
                target = parts[pair[0 if field.startswith("from") else 1]]
                refs = link.get(field)
                if not isinstance(refs, list) or not refs or any(ref not in target["evidence_refs"] for ref in refs):
                    raise ValueError("Continuation evidence must refer to both connected parts")
            actual.add(pair)
        if actual != expected:
            raise ValueError("Every additional section part requires continuation evidence")
    if covered | set(unresolved) != set(pages):
        raise ValueError("Every page must have a section or remain explicitly unresolved")
    # Attachment parentage is a directed, acyclic relationship within this source.
    parents = {}
    for section in sections:
        parent = section.get("parent_section_id")
        if parent is not None:
            if parent not in section_ids or parent == section["section_id"] or section.get("relation") not in {"attachment", "subsection"}:
                raise ValueError("Invalid section parent/relation")
            parents[section["section_id"]] = parent
    for sid in parents:
        seen, current = set(), sid
        while current in parents:
            if current in seen:
                raise ValueError("Section parent cycle")
            seen.add(current)
            current = parents[current]
    return plan


def validate_batch(batch, catalog, catalog_sha256):
    if not isinstance(batch, dict) or batch.get("version") != 1 or batch.get("base_catalog_sha256") != catalog_sha256:
        raise ValueError("Plan batch version/base_catalog_sha256 is missing or stale")
    validate_provenance(batch.get("provenance"))
    plans = batch.get("plans")
    if not isinstance(plans, list) or not plans:
        raise ValueError("Plan batch requires a nonempty plans array")
    if not all(isinstance(plan, dict) for plan in plans):
        raise ValueError("Each plan must be an object")
    ids = [plan.get("document_id") for plan in plans]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate document plans in batch")
    for plan in plans:
        validate_plan(plan, catalog)
    return batch


def coverage(plan):
    """Measure unassigned source regions separately from an imported plan's status."""
    parts = [part for section in plan["sections"] for part in section["parts"]]
    unassigned = []
    for region in plan["regions"]:
        box = region["bbox"]
        area = (box[2] - box[0]) * (box[3] - box[1])
        # This conservative check requires one part to contain the observed
        # region. It never double-counts overlaps to manufacture coverage.
        if not any(part["page_id"] == region["page_id"] and overlap(box, part["bbox"]) >= area * 0.95 for part in parts):
            unassigned.append(region["region_id"])
    return {"unassigned_region_ids": unassigned,
            "segmentation_completeness": "unresolved" if unassigned or plan["unresolved_pages"] else "observed_regions_assigned",
            "scope": "Coverage of measured/predicted regions only; blank areas and missed detector content are not proof of complete segmentation."}
