"""Assemble source-owned records; retain disagreements and open issue history."""
from collections.abc import Mapping, MutableMapping
import json

from committee_meeting import Catalog
from committee_meeting.catalog import DomainRecord, _references
from committee_meeting.issues import DataIssue, IssueResolution
from committee_meeting.provenance import AlternativeValue, FieldEvidence, Method, Provenance, SourceRecord
from committee_meeting.common import Ref
from pydantic import TypeAdapter, ValidationError

from .collector_labels import collector_placeholder_conflict


_DOMAIN_RECORD = TypeAdapter(DomainRecord)


def validated(record):
    """Validate one record, including nested instances changed with model_copy."""
    try:
        return SourceRecord.model_validate(record) if isinstance(record, SourceRecord) else _DOMAIN_RECORD.validate_python(record)
    except ValidationError as error:
        # A source payload can be large. Errors must not reproduce input data.
        raise ValueError(str(error.errors(include_input=False, include_url=False)[:10])) from None


class _ValidatedRecords(MutableMapping):
    """Every replacement, including a caller's model_copy, crosses validation."""

    def __init__(self, *, sources=False):
        self._records = {}
        self._sources = sources

    def __getitem__(self, key):
        return self._records[key]

    def __setitem__(self, key, record):
        record = validated(record)
        if key != (record.kind, record.id) or isinstance(record, SourceRecord) != self._sources:
            raise ValueError("Assembly record does not match its identity or collection")
        self._records[key] = record

    def __delitem__(self, key):
        del self._records[key]

    def __iter__(self):
        return iter(self._records)

    def __len__(self):
        return len(self._records)


class Assembly:
    def __init__(self, previous=None, *, ids=None, now=None):
        self.sources = _ValidatedRecords(sources=True)
        self.records = _ValidatedRecords()
        self.current = set()
        self.previous = previous
        self.ids, self.now = ids, now

    def add(self, items):
        for item in items:
            into = self.sources if isinstance(item, SourceRecord) else self.records
            key = (item.kind, item.id)
            old = into.get(key)
            if old is not None and old != item and not isinstance(item, SourceRecord):
                citations = {c.model_dump_json(): c for c in (*old.provenance.citations, *item.provenance.citations)}
                ev = item.provenance.model_copy(update={"citations": tuple(citations[k] for k in sorted(citations))})
                old_fields = {f.path: f for f in old.field_evidence}
                incoming_fields = {f.path: f for f in item.field_evidence}
                fields = dict(old_fields)
                for path, field in incoming_fields.items():
                    alternatives = {a.model_dump_json(): a for a in (
                        *(old_fields[path].alternatives if path in old_fields else ()), *field.alternatives)}
                    fields[path] = field.model_copy(update={"alternatives": tuple(alternatives.values())})
                updates = {}
                for name in type(item).model_fields:
                    if name in ("id", "kind", "provenance", "field_evidence"):
                        continue
                    before, after = getattr(old, name), getattr(item, name)
                    if before == after:
                        continue
                    if after is None or after == "" or after == ():
                        updates[name] = before
                        if "/" + name in old_fields:
                            fields["/" + name] = old_fields["/" + name]
                        else:
                            fields.pop("/" + name, None)
                    elif before is not None and before != "" and before != ():
                        if name == "identifiers":
                            updates[name] = tuple({v.model_dump_json(): v for v in (*before, *after)}.values())
                        elif not isinstance(item, DataIssue):
                            if item.kind == "occurrence" and name == "access" and before == "unknown":
                                continue  # Filling absent access is not a source disagreement.
                            path = "/" + name
                            alternatives = list(fields[path].alternatives) if path in fields else []
                            alt = AlternativeValue(value=old.model_dump(mode="json")[name],
                                                   provenance=old_fields[path].selected if path in old_fields else old.provenance)
                            if all(a.value != alt.value for a in alternatives):
                                alternatives.append(alt)
                            selected = incoming_fields.get(path)
                            fields[path] = FieldEvidence(path=path, selected=selected.selected if selected else item.provenance,
                                                         alternatives=tuple(alternatives), selection_reason=selected.selection_reason if selected
                                                         else "Later record in deterministic source order; alternatives retained.")
                item = item.model_copy(update={**updates, "provenance": ev, "field_evidence": tuple(fields.values())})
            into[key] = item
            self.current.add(key)

    def _review_old_label_conflict(self, issue, previous):
        """Record a lasting correction to a known collector-generated conflict."""
        if (self.now is None or issue.status != "open" or issue.category != "conflicting"
                or issue.subject.kind != "material_version" or issue.field_path != "/label"
                or (issue.kind, issue.id) in self.current):
            return issue
        subject_key = (issue.subject.kind, issue.subject.id)
        current = self.records.get(subject_key)
        if current is not None and any(field.path == "/label" and field.alternatives for field in current.field_evidence):
            return issue  # A current disagreement needs its own review.
        previous_version = previous.get(subject_key)
        field = next((field for field in previous_version.field_evidence if field.path == "/label" and field.alternatives), None) if previous_version else None
        if field is None:
            return issue
        values = [previous_version.label, *(alternative.value for alternative in field.alternatives)]
        if not collector_placeholder_conflict(values):
            return issue
        evidence = (issue.provenance, previous_version.provenance, field.selected,
                    *(alternative.provenance for alternative in field.alternatives))
        citations = {citation.model_dump_json(): citation for provenance in evidence for citation in provenance.citations}
        resolution = IssueResolution(
            decided_at=self.now,
            explanation=("Collectors assigned different internal edition labels. This is not evidence of a disagreement in source content. "
                         f"Original selected value: {json.dumps(values[0])}. Original alternatives: {json.dumps(values[1:])}."),
            provenance=Provenance(citations=tuple(citations[key] for key in sorted(citations)), basis="derived",
                                 method=Method(name="committee-explorer.dismiss-collector-label-conflict", version="1"),
                                 explanation=field.selection_reason),
        )
        return issue.model_copy(update={"status": "dismissed", "resolution": resolution})

    def finish(self):
        if self.ids:
            for record in list(self.records.values()):
                for field in record.field_evidence:
                    if not field.alternatives:
                        continue
                    issue = DataIssue(id=self.ids("data_issue", f"conflict|{record.kind}|{record.id}|{field.path}"),
                                      subject=Ref(kind=record.kind, id=record.id), field_path=field.path, category="conflicting",
                                      summary=f"Sources disagree about {field.path.lstrip('/')}", detected_at=self.now,
                                      provenance=Provenance(citations=record.provenance.citations, basis="derived", method=Method(name="committee-explorer.compare-fields", version="1")))
                    self.records[(issue.kind, issue.id)] = issue
                    self.current.add((issue.kind, issue.id))
        # An unchecked/missing source does not resolve a previous issue. Keep its
        # supporting graph so every retained issue remains inspectable.
        if self.previous is not None:
            # Production uses a disk-backed Mapping; Catalog compatibility is
            # useful for small callers but must not load a previous full export.
            previous = self.previous if isinstance(self.previous, Mapping) else {
                (v.kind, v.id): v for values in (self.previous.sources, self.previous.records) for v in values}
            issues = previous.iter_issues() if hasattr(previous, "iter_issues") else (v for k, v in previous.items() if k[0] == "data_issue")
            seen = set()
            for issue in issues:
                issue = self._review_old_label_conflict(issue, previous)
                pending = [issue]
                while pending:
                    old = pending.pop()
                    key = (old.kind, old.id)
                    if key in seen:
                        continue
                    seen.add(key)
                    into = self.sources if isinstance(old, SourceRecord) else self.records
                    if key not in into:
                        into[key] = old
                    elif isinstance(old, DataIssue):
                        now = into[key]
                        # Preserve original detection/evidence. A current finding
                        # can reopen a closed issue; disappearance never closes it.
                        citations = {c.model_dump_json(): c for c in (*old.provenance.citations, *now.provenance.citations)}
                        provenance = now.provenance.model_copy(update={"citations": tuple(citations[k] for k in sorted(citations))})
                        into[key] = now.model_copy(update={"detected_at": old.detected_at, "provenance": provenance})
                    for reference in _references(old):
                        refkey = (reference.kind, reference.id)
                        if refkey not in seen:
                            try:
                                pending.append(previous[refkey])
                            except KeyError:
                                raise ValueError(f"Issue history is missing {reference.kind}/{reference.id}") from None
        # Every record crossed validated() individually. Constructing the tuples
        # must not ask Pydantic to copy the entire corpus a second time. The full
        # graph validator still checks all links, ownership rules and cycles.
        catalog = Catalog.model_construct(sources=tuple(self.sources[k] for k in sorted(self.sources)),
                                          records=tuple(self.records[k] for k in sorted(self.records)))
        return catalog.check_graph()
