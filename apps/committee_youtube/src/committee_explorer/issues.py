"""Documented issue resolutions. Missing observations never close issues."""
from datetime import datetime
from committee_meeting import Catalog
from committee_meeting.issues import IssueResolution


def apply_decisions(catalog, rows, context):
    records = {(r.kind, r.id): r for r in catalog.records}
    sources = list(catalog.sources)
    seen = set()
    for row in rows:
        issue_id = row["issue_id"]
        if issue_id in seen:
            raise ValueError(f"Repeated issue decision: {issue_id}")
        seen.add(issue_id)
        key = ("data_issue", issue_id)
        if key not in records:
            raise ValueError(f"Decision refers to unknown issue: {issue_id}")
        if row.get("status") not in ("resolved", "dismissed"):
            raise ValueError("Issue decision status must be resolved or dismissed")
        source = context.source(issue_id, row)
        sources.append(source)
        decided = datetime.fromisoformat(row["decided_at"]) if row.get("decided_at") else context.now
        resolution = IssueResolution(decided_at=decided, explanation=row["explanation"], provenance=context.evidence(source, basis="curated"))
        records[key] = type(records[key]).model_validate(records[key].model_copy(update={"status": row["status"], "resolution": resolution}))
    return Catalog.model_construct(sources=tuple(sources), records=tuple(records[k] for k in sorted(records))).check_graph()
