"""Documented issue resolutions. Missing observations never close issues."""
from datetime import datetime
from committee_meeting import Catalog
from committee_meeting.issues import IssueResolution


def apply_decisions(catalog, rows, context, retained=None):
    """``retained`` maps (kind, id) to sources the catalog cites but issue history holds."""
    retained = {} if retained is None else retained
    lazy_records = hasattr(catalog.records, "get_by_key") and hasattr(catalog.records, "with_additional")
    records = {} if lazy_records else {(r.kind, r.id): r for r in catalog.records}
    lazy_sources = hasattr(catalog.sources, "get_by_id") and hasattr(catalog.sources, "with_additional")
    sources = {} if lazy_sources else {source.id: source for source in catalog.sources}
    seen = set()
    for row in rows:
        issue_id = row["issue_id"]
        if issue_id in seen:
            raise ValueError(f"Repeated issue decision: {issue_id}")
        seen.add(issue_id)
        key = ("data_issue", issue_id)
        existing_issue = catalog.records.get_by_key(key) if lazy_records else records.get(key)
        if existing_issue is None:
            raise ValueError(f"Decision refers to unknown issue: {issue_id}")
        if row.get("status") not in ("resolved", "dismissed"):
            raise ValueError("Issue decision status must be resolved or dismissed")
        source = context.source(issue_id, row)
        # A replayed decision's source may be retained only by issue history; it
        # stays there and is published from there.
        previous = sources.get(source.id)
        if previous is None and lazy_sources:
            previous = catalog.sources.get_by_id(source.id)
        if previous is None:
            previous = retained.get((source.kind, source.id))
        if previous is not None:
            # Replaying the same retained decision is the same observation.
            # Keep its original import time; never replace different evidence.
            if previous.model_dump(exclude={'imported_at'}) != source.model_dump(exclude={'imported_at'}):
                raise ValueError(f"Conflicting issue decision source: {source.id}")
            source = previous
        else:
            sources[source.id] = source
        decided = datetime.fromisoformat(row["decided_at"]) if row.get("decided_at") else source.imported_at or context.now
        resolution = IssueResolution(decided_at=decided, explanation=row["explanation"], provenance=context.evidence(source, basis="curated"))
        records[key] = type(existing_issue).model_validate(existing_issue.model_copy(update={"status": row["status"], "resolution": resolution}))
    new_sources = catalog.sources.with_additional(sources.values()) if lazy_sources else tuple(sources.values())
    new_records = catalog.records.with_additional(records.values()) if lazy_records else tuple(records[k] for k in sorted(records))
    return Catalog.model_construct(sources=new_sources,
                                   records=new_records).check_graph_with(retained)
