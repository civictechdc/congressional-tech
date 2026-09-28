"""Reuse the originating appearance when inventory repeats a source witness row."""
from collections import defaultdict


def reuse_appearances(items, assembly):
    def key(record):
        affiliation = record.affiliation
        return (record.meeting.id, record.name.display, record.roles,
                affiliation.position if affiliation else None,
                affiliation.organization_name if affiliation else None)

    known = defaultdict(list)
    for record in assembly.records.values():
        if record.kind == 'appearance':
            known[key(record)].append(record)
    sources = dict(assembly.sources)
    for record in items:
        if record.kind == 'source_record':
            sources[record.kind, record.id] = record
        elif record.kind == 'appearance':
            origin = sources['source_record', record.provenance.citations[0].source.id].payload
            provider = {'docs.house.gov': 'docs.house.gov', 'senate committee page': 'senate.committees'}.get(origin.get('source'))
            candidates = []
            for existing in known[key(record)]:
                # A recovered row is a lossy copy of this provider's observation.
                # Matching names alone, or matching a different provider, is insufficient.
                if any(sources['source_record', citation.source.id].provider == provider
                       for citation in existing.provenance.citations):
                    candidates.append(existing)
            if len(candidates) == 1:
                existing = candidates[0]
                # Preserve panel, on-behalf-of, location and other source facts.
                citations = {c.model_dump_json(): c for c in (*existing.provenance.citations, *record.provenance.citations)}
                record = existing.model_copy(update={'provenance': existing.provenance.model_copy(
                    update={'citations': tuple(citations.values())})})
            else:
                known[key(record)].append(record)
        yield record
