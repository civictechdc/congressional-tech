import sys
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .assessments import Assessment
from .committees import Channel, Committee, CommitteeTerm
from .common import Model, Ref
from .graph import CatalogGraph
from .issues import DataIssue
from .legislation import Amendment, AmendmentGroup, LegislativeItem, MeetingSubject, Vote
from .materials import Material, MaterialLink, MaterialRelation, MaterialVersion, Representation
from .meetings import Appearance, Meeting, MeetingOccurrence, Panel, Person
from .provenance import Citation, SourceRecord
from .publication import SCHEMA_VERSION, SchemaVersion

DomainRecord = Annotated[
    Committee | CommitteeTerm | Channel
    | Meeting | MeetingOccurrence | Panel | Person | Appearance
    | Material | MaterialVersion | Representation | MaterialLink | MaterialRelation
    | LegislativeItem | MeetingSubject | Amendment | AmendmentGroup | Vote
    | Assessment | DataIssue,
    Field(discriminator="kind"),
]


def _references(value):
    """Visit typed model fields, never interpret arbitrary source payload as links."""
    if isinstance(value, Ref):
        yield value
    elif isinstance(value, Model):
        for name in type(value).model_fields:
            yield from _references(getattr(value, name))
        if isinstance(value, Material):
            for m_id in value.meeting_ids:
                yield Ref(kind="meeting", id=m_id)
            for a_id in value.appearance_ids:
                yield Ref(kind="appearance", id=a_id)
            for c_id in value.committee_ids:
                yield Ref(kind="committee_term", id=c_id)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _references(item)


def _pointer_exists(document, pointer: str) -> bool:
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(document, dict) and token in document:
            document = document[token]
        elif isinstance(document, list) and token.isdigit() and int(token) < len(document):
            document = document[int(token)]
        else:
            return False
    return True


class Catalog(Model):
    """An export's complete set of records and evidence.

    Validate this set before partitioning for the site. A single record may refer
    outside its detail file; do not treat that file as a complete Catalog.
    Identity is (kind, id). Provider identifiers are aliases, not primary keys.
    """

    schema_version: SchemaVersion = SCHEMA_VERSION
    scope: Literal["complete"] = "complete"
    sources: tuple[SourceRecord, ...] = ()
    records: tuple[DomainRecord, ...] = ()

    @property
    def graph(self) -> CatalogGraph:
        return CatalogGraph(self)

    def neighbors(
        self,
        node: Ref | tuple[str, str],
        *,
        relation: str | None = None,
        direction: Literal["out", "in", "both"] = "both",
    ) -> list[Ref]:
        return self.graph.neighbors(node, relation=relation, direction=direction)

    def ancestors(
        self,
        node: Ref | tuple[str, str],
        *,
        relation: str | None = "derived_from",
    ) -> list[Ref]:
        return self.graph.ancestors(node, relation=relation)

    def lineage(self, node: Ref | tuple[str, str]) -> list[Ref]:
        return self.graph.lineage(node)

    @property
    def cited_json_pointers(self) -> dict[str, str | tuple[str, ...]]:
        return getattr(self, "_cited_json_pointers", {})

    @model_validator(mode="after")
    def check_graph(self):
        return self.check_graph_with({})

    def check_graph_with(self, external_sources, cited_pointers: dict[str, str | tuple[str, ...]] | None = None):
        """Validate this catalog where some cited source observations are stored elsewhere.

        ``external_sources`` maps ("source_record", id) to a SourceRecord that is
        part of the same export but not held in ``sources``. Membership must be
        cheap; a check loads a record only when it reads its fields. An external
        identity may not repeat one in this catalog.
        """
        index = {}
        has_lazy_sources = hasattr(self.sources, "source_ids") and hasattr(self.sources, "get_by_id")
        has_lazy_records = hasattr(self.records, "has_key") and hasattr(self.records, "get_by_key")
        source_ids = self.sources.source_ids() if has_lazy_sources else None

        if has_lazy_sources:
            for sid in source_ids:
                if ("source_record", sid) in external_sources:
                    raise ValueError(f"duplicate record identity: {('source_record', sid)}")
        else:
            for item in self.sources:
                key = (item.kind, item.id)
                if key in index or key in external_sources:
                    raise ValueError(f"duplicate record identity: {key}")
                index[key] = item

        if has_lazy_records:
            for key in self.records.iter_keys():
                if key in index or key in external_sources or (source_ids is not None and key[0] == "source_record" and key[1] in source_ids):
                    raise ValueError(f"duplicate record identity: {key}")
        else:
            for item in self.records:
                key = (item.kind, item.id)
                if key in index or key in external_sources or (source_ids is not None and key[0] == "source_record" and key[1] in source_ids):
                    raise ValueError(f"duplicate record identity: {key}")
                index[key] = item

        def has_key(key):
            if key in index or key in external_sources:
                return True
            if has_lazy_records and self.records.has_key(key):
                return True
            return source_ids is not None and key[0] == "source_record" and key[1] in source_ids

        def resolve(ref):
            key = (ref.kind, ref.id)
            if key in index:
                return index[key]
            if has_lazy_records and self.records.has_key(key):
                return self.records.get_by_key(key)
            if source_ids is not None and key[0] == "source_record" and key[1] in source_ids:
                return self.sources.get_by_id(key[1])
            return external_sources[key]

        def require(condition, message):
            if not condition:
                raise ValueError(message)

        term_meta = {}
        meeting_congress = {}
        occurrence_meeting = {}
        panel_scope = {}
        version_material = {}
        version_supersedes = {}
        amendment_meta = {}
        amendment_group_meeting = {}
        issue_checks = []
        collected_pointers: dict[str, str | tuple[str, ...]] = {}

        def _check_refs(val, owner_kind, owner_id):
            if isinstance(val, Ref):
                key = (val.kind, val.id)
                require(has_key(key), f"{owner_kind}/{owner_id}: missing {val.kind}/{val.id}")
            elif isinstance(val, Citation):
                sref = val.source
                require(has_key((sref.kind, sref.id)), f"{owner_kind}/{owner_id}: missing {sref.kind}/{sref.id}")
                if val.selector_type == "json_pointer" and val.selector is not None:
                    sel = sys.intern(val.selector)
                    cur = collected_pointers.get(sref.id)
                    if cur is None:
                        collected_pointers[sref.id] = sel
                    elif isinstance(cur, str):
                        if cur != sel:
                            collected_pointers[sref.id] = (cur, sel)
                    elif sel not in cur:
                        collected_pointers[sref.id] = (*cur, sel)
            elif isinstance(val, Model):
                for fname in type(val).model_fields:
                    _check_refs(getattr(val, fname), owner_kind, owner_id)
                if isinstance(val, Material):
                    for m_id in val.meeting_ids:
                        require(has_key(("meeting", m_id)), f"{owner_kind}/{owner_id}: missing meeting/{m_id}")
                    for a_id in val.appearance_ids:
                        require(has_key(("appearance", a_id)), f"{owner_kind}/{owner_id}: missing appearance/{a_id}")
                    for c_id in val.committee_ids:
                        require(has_key(("committee_term", c_id)), f"{owner_kind}/{owner_id}: missing committee_term/{c_id}")
            elif isinstance(val, (tuple, list)):
                for elem in val:
                    _check_refs(elem, owner_kind, owner_id)

        if hasattr(self.records, "iter_kind"):
            priority_kinds = (
                "committee_term",
                "meeting",
                "occurrence",
                "panel",
                "appearance",
                "material_version",
                "material_link",
                "amendment",
                "amendment_group",
                "vote",
                "data_issue",
                "material_relation",
            )
            all_kinds = set(self.records.kinds()) if hasattr(self.records, "kinds") else set()
            ordered_kinds = [k for k in priority_kinds if k in all_kinds] + sorted(all_kinds - set(priority_kinds))
            records_iter = (item for k in ordered_kinds for item in self.records.iter_kind(k))
        else:
            records_iter = iter(self.records)

        for item in records_iter:
            _check_refs(item, item.kind, item.id)
            paths = [e.path for e in item.field_evidence]
            require(len(paths) == len(set(paths)), f"{item.id}: duplicate field evidence paths")
            if paths:
                document = item.model_dump(mode="json")
                for path in paths:
                    require(_pointer_exists(document, path), f"{item.id}: field evidence path does not exist: {path}")

            if isinstance(item, DataIssue) and item.field_path:
                issue_checks.append((item.id, item.subject, item.field_path))
            elif isinstance(item, CommitteeTerm):
                term_meta[item.id] = (item.congress, item.parent)
            elif isinstance(item, Meeting):
                meeting_congress[item.id] = item.congress
                committees = [c.committee.id for c in item.committees]
                require(len(committees) == len(set(committees)), f"{item.id}: repeated convening committee")
                for comm_id in committees:
                    term_congress = term_meta[comm_id][0] if comm_id in term_meta else resolve(Ref(kind="committee_term", id=comm_id)).congress
                    require(item.congress is None or term_congress == item.congress, f"{item.id}: committee Congress differs")
            elif isinstance(item, MeetingOccurrence):
                occurrence_meeting[item.id] = item.meeting
            elif isinstance(item, Panel):
                panel_scope[item.id] = (item.meeting, item.occurrence)
                if item.occurrence:
                    occ_meeting = occurrence_meeting[item.occurrence.id] if item.occurrence.id in occurrence_meeting else resolve(Ref(kind="occurrence", id=item.occurrence.id)).meeting
                    require(occ_meeting == item.meeting, f"{item.id}: occurrence belongs to another meeting")
            elif isinstance(item, Appearance):
                if item.occurrence:
                    occ_meeting = occurrence_meeting[item.occurrence.id] if item.occurrence.id in occurrence_meeting else resolve(Ref(kind="occurrence", id=item.occurrence.id)).meeting
                    require(occ_meeting == item.meeting, f"{item.id}: occurrence belongs to another meeting")
                if item.panel:
                    p_meeting, p_occ = panel_scope[item.panel.id] if item.panel.id in panel_scope else (resolve(Ref(kind="panel", id=item.panel.id)).meeting, resolve(Ref(kind="panel", id=item.panel.id)).occurrence)
                    require(p_meeting == item.meeting, f"{item.id}: panel belongs to another meeting")
                    require(not (p_occ and item.occurrence) or p_occ == item.occurrence, f"{item.id}: panel and appearance have different occurrences")
            elif isinstance(item, MaterialVersion):
                version_material[item.id] = item.material.id
                if item.supersedes:
                    version_supersedes[item.id] = item.supersedes
            elif isinstance(item, MaterialLink):
                if item.version:
                    ver_mat_id = version_material[item.version.id] if item.version.id in version_material else resolve(Ref(kind="material_version", id=item.version.id)).material.id
                    require(ver_mat_id == item.material.id, f"{item.id}: linked version belongs to another material")
            elif isinstance(item, Amendment):
                amendment_meta[item.id] = (item.meeting, item.target)
                if item.occurrence:
                    occ_meeting = occurrence_meeting[item.occurrence.id] if item.occurrence.id in occurrence_meeting else resolve(Ref(kind="occurrence", id=item.occurrence.id)).meeting
                    require(occ_meeting == item.meeting, f"{item.id}: occurrence belongs to another meeting")
            elif isinstance(item, AmendmentGroup):
                amendment_group_meeting[item.id] = item.meeting
                require(len(item.members) == len(set(m.id for m in item.members)), f"{item.id}: repeated group member")
                for member in item.members:
                    m_meeting = amendment_meta[member.id][0] if member.id in amendment_meta else resolve(Ref(kind="amendment", id=member.id)).meeting
                    require(m_meeting == item.meeting, f"{item.id}: group member belongs to another meeting")
            elif isinstance(item, Vote):
                if item.occurrence:
                    occ_meeting = occurrence_meeting[item.occurrence.id] if item.occurrence.id in occurrence_meeting else resolve(Ref(kind="occurrence", id=item.occurrence.id)).meeting
                    require(occ_meeting == item.meeting, f"{item.id}: occurrence belongs to another meeting")
                if item.committee:
                    m_congress = meeting_congress[item.meeting.id] if item.meeting.id in meeting_congress else resolve(item.meeting).congress
                    c_congress = term_meta[item.committee.id][0] if item.committee.id in term_meta else resolve(item.committee).congress
                    require(m_congress is None or c_congress == m_congress, f"{item.id}: voting committee Congress differs")
                if item.subject and item.subject.kind in ("amendment", "amendment_group"):
                    if item.subject.kind == "amendment" and item.subject.id in amendment_meta:
                        s_meeting = amendment_meta[item.subject.id][0]
                    elif item.subject.kind == "amendment_group" and item.subject.id in amendment_group_meeting:
                        s_meeting = amendment_group_meeting[item.subject.id]
                    else:
                        s_meeting = resolve(item.subject).meeting
                    require(s_meeting == item.meeting, f"{item.id}: vote subject belongs to another meeting")
            elif isinstance(item, MaterialRelation):
                require(item.subject != item.related, f"{item.id}: relationship cannot target itself")

        for issue_id, subject_ref, field_path in issue_checks:
            require(
                _pointer_exists(resolve(subject_ref).model_dump(mode="json"), field_path),
                f"{issue_id}: issue field path does not exist: {field_path}",
            )
        for term_id, (congress, parent_ref) in term_meta.items():
            if parent_ref:
                parent_congress = term_meta[parent_ref.id][0] if parent_ref.id in term_meta else resolve(parent_ref).congress
                require(parent_congress == congress, f"{term_id}: parent committee is from another Congress")
        for ver_id, supersedes_ref in version_supersedes.items():
            ver_mat_id = version_material[ver_id]
            prev_mat_id = version_material[supersedes_ref.id] if supersedes_ref.id in version_material else resolve(supersedes_ref).material.id
            require(prev_mat_id == ver_mat_id, f"{ver_id}: superseded version belongs to another material")
        for amd_id, (amd_meeting, target_ref) in amendment_meta.items():
            if target_ref and target_ref.kind == "amendment":
                t_meeting = amendment_meta[target_ref.id][0] if target_ref.id in amendment_meta else resolve(target_ref).meeting
                require(t_meeting == amd_meeting, f"{amd_id}: target amendment belongs to another meeting")

        for kind_name, attribute, next_map in (
            ("committee_term", "parent", {tid: p for tid, (_, p) in term_meta.items()}),
            ("material_version", "supersedes", version_supersedes),
            ("amendment", "target", {aid: t for aid, (_, t) in amendment_meta.items()}),
        ):
            completed = set()
            for item_id in next_map:
                seen, cur_id = set(), item_id
                while cur_id not in completed:
                    require(cur_id not in seen, f"{item_id}: cycle in {attribute}")
                    seen.add(cur_id)
                    ref = next_map.get(cur_id)
                    if not ref or ref.kind != kind_name:
                        break
                    cur_id = ref.id
                completed.update(seen)

        if cited_pointers is not None:
            cited_pointers.update(collected_pointers)
        self._cited_json_pointers = collected_pointers
        return self
