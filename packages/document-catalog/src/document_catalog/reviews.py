"""Immutable review batches. Human and agent judgments never erase measurements."""

from .plans import nonempty
from .store import identity


def targets(catalog):
    result = {}
    for page in catalog["pages"]:
        result[("page", page["page_id"])] = page["evidence_sha256"]
    for document in catalog["documents"]:
        result[("document", document["document_id"])] = document["context_sha256"]
    for group in catalog["groups"]:
        result[("group", group["group_id"])] = group["context_sha256"]
    for plan in catalog["plans"]:
        for section in plan["sections"]:
            result[("section", plan["document_id"] + ":" + section["section_id"])] = identity({
                "plan_context": plan["context_sha256"], "section": section, "provenance": plan["provenance"]})
    return result


def validate_review_batch(batch, catalog, catalog_sha256):
    if not isinstance(batch, dict) or batch.get("version") != 1 or batch.get("base_catalog_sha256") != catalog_sha256:
        raise ValueError("Review batch version/base_catalog_sha256 is missing or stale")
    reviewer = batch.get("reviewer")
    if not isinstance(reviewer, dict) or reviewer.get("kind") not in {"human", "agent"}:
        raise ValueError("reviewer.kind must be human or agent")
    nonempty(reviewer.get("id"), "reviewer.id")
    nonempty(batch.get("method"), "method")
    nonempty(batch.get("created_at"), "created_at")
    judgments = batch.get("judgments")
    if not isinstance(judgments, list) or not judgments:
        raise ValueError("Review batch requires judgments")
    known, seen = targets(catalog), set()
    for judgment in judgments:
        if not isinstance(judgment, dict):
            raise ValueError("Each review judgment must be an object")
        key = (judgment.get("target_type"), judgment.get("target_id"))
        if key not in known or key in seen:
            raise ValueError("Unknown or duplicate review target")
        seen.add(key)
        if judgment.get("context_sha256") != known[key]:
            raise ValueError("Review target context is stale")
        if judgment.get("decision") not in {"accept", "reject", "uncertain"}:
            raise ValueError("Review decision must be accept, reject or uncertain")
        nonempty(judgment.get("reason"), "judgment.reason")
    return batch


def layer_reviews(catalog):
    known, latest = targets(catalog), {}
    for judgment in catalog["reviews"]:
        key = (judgment["target_type"], judgment["target_id"])
        if known.get(key) != judgment["context_sha256"]:
            judgment["application_state"] = "stale"
        else:
            if key in latest:
                latest[key]["application_state"] = "superseded"
            judgment["application_state"] = "active"
            latest[key] = judgment
    catalog["review_targets"] = [{"target_type": key[0], "target_id": key[1], "context_sha256": value} for key, value in sorted(known.items())]
