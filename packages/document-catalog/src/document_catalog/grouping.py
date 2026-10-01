"""Deterministic geometry-based candidate groups; never proven templates.

Greedy radius groups keep a fixed first exemplar to avoid chaining distant
layouts through intermediate pages. Vectorized blocks bound temporary memory.
Filled-in words and uncertain semantic role labels are excluded entirely.
"""

import numpy as np

from .store import identity


def feature(page, config, anchor_ids):
    grid = config["grid_size"]
    regions = page.get("layout", {}).get("regions", [])
    boxes = [r["bbox"] for r in regions] or [line["bbox"] for line in page.get("text", {}).get("lines", [])]
    boxes += [d["bbox"] for d in page.get("drawings", []) if d["bbox"]]
    if not boxes and not page.get("drawings"):
        return None
    occupancy = np.zeros((grid, grid), dtype=float)
    for left, top, right, bottom in boxes:
        x0, x1 = int(left * grid), min(grid, max(int(left * grid) + 1, int(np.ceil(right * grid))))
        y0, y1 = int(top * grid), min(grid, max(int(top * grid) + 1, int(np.ceil(bottom * grid))))
        occupancy[y0:y1, x0:x1] = 1
    for drawing in page.get("drawings", []):
        for x, y in drawing["endpoints"]:
            if 0 <= x <= 1 and 0 <= y <= 1:
                occupancy[min(grid - 1, int(y * grid)), min(grid - 1, int(x * grid))] = 1
    # Occupied cells have equal weight regardless of a text line's contents.
    geometry = occupancy.ravel() / grid
    prompts = np.zeros(len(anchor_ids), dtype=float)
    hits = {a["anchor_id"] for a in page.get("anchors", [])}
    for index, name in enumerate(anchor_ids):
        prompts[index] = float(name in hits)
    if len(prompts):
        prompts *= config["anchor_weight"] / np.sqrt(len(prompts))
    aspect = page["size_points"][0] / page["size_points"][1]
    return np.concatenate([geometry, [min(3, aspect) * 0.2], prompts])


def group_pages(pages, config, category):
    anchors = sorted(a["id"] for a in category["anchors"])
    groups, exemplars, vectors = [], [], {}
    for page in sorted(pages, key=lambda p: p["page_id"]):
        vector = feature(page, config, anchors) if page["status"] == "captured" else None
        if vector is None:
            groups.append({"members": [page["page_id"]], "kind": "unknown", "exemplar": page["page_id"]})
            continue
        vectors[page["page_id"]] = vector
        best = None
        distance = float("inf")
        for start in range(0, len(exemplars), 1024):
            block = exemplars[start:start + 1024]
            distances = np.linalg.norm(np.stack([item[1] for item in block]) - vector, axis=1)
            index = int(np.argmin(distances))
            if float(distances[index]) < distance:
                best, distance = block[index][0], float(distances[index])
        if best is not None and distance <= config["distance_threshold"]:
            groups[best]["members"].append(page["page_id"])
        else:
            exemplars.append((len(groups), vector))
            groups.append({"members": [page["page_id"]], "kind": "candidate", "exemplar": page["page_id"]})
    by_id = {p["page_id"]: p for p in pages}
    for group in groups:
        members = group["members"]
        group["group_id"] = "g-" + identity({"members": members, "config": config})
        group["context_sha256"] = identity({"members": [(pid, by_id[pid]["evidence_sha256"]) for pid in members], "config": config})
        group["status"] = "unknown" if group["kind"] == "unknown" else ("singleton_candidate" if len(members) == 1 else "layout_candidate")
        group["method"] = "fixed-exemplar-radius; occupancy geometry plus configured prompt presence"
        group["excludes"] = ["filled_text", "semantic_role"]
        group["representatives"] = [{"page_id": group["exemplar"], "reason": "fixed_exemplar"}]
        if group["kind"] != "unknown":
            center = vectors[group["exemplar"]]
            edge = max(members, key=lambda pid: float(np.linalg.norm(vectors[pid] - center)))
            group["maximum_exemplar_distance"] = float(np.linalg.norm(vectors[edge] - center))
            if edge != group["exemplar"]:
                group["representatives"].append({"page_id": edge, "reason": "furthest_layout_edge"})
        # Retain every page with an explicit processing/quality issue, even if
        # its geometry resembles an otherwise ordinary group.
        for pid in members:
            page = by_id[pid]
            reasons = page.get("issues", [])
            if reasons and pid not in {r["page_id"] for r in group["representatives"]}:
                group["representatives"].append({"page_id": pid, "reason": "quality_or_processing_edge", "issues": reasons})
    return groups
