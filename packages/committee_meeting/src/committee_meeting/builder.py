"""Ergonomic CatalogBuilder for constructing product-first committee meeting records."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from .assessments import Assessment
from .catalog import Catalog, DomainRecord
from .committees import Channel, Committee, CommitteeTerm
from .common import Chamber, DateRange, Identifier, Location, PositiveInt, Ref, ReportedTime, Seconds
from .graph import Edge, EdgeRelation
from .issues import DataIssue
from .materials import (
    DocumentDetails,
    Material,
    MaterialCategory,
    MaterialFile,
    MaterialLink,
    MaterialRole,
    RecordingDetails,
    TextDetails,
)
from .meetings import Affiliation, Appearance, ConveningCommittee, Meeting, MeetingSitting, RecordedName
from .provenance import Citation, FieldEvidence, Method, Provenance, RetainedContent, SourceRecord


def _default_ids(kind: str, key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"congressional-tech:committee-meeting:{kind}:{key}"))


class CatalogBuilder:
    """Fluent builder that manages ID allocation, source records, domain records, and edges."""

    def __init__(
        self,
        *,
        provider: str = "default",
        input_id: str | None = None,
        now: datetime | None = None,
        ids: Callable[[str, str], str] | None = None,
    ):
        self.provider = provider
        self.input_id = input_id
        self.now = now or datetime.now(timezone.utc)
        self.ids = ids or _default_ids
        self._sources: dict[str, SourceRecord] = {}
        self._records: dict[tuple[str, str], DomainRecord] = {}

    def _provenance(
        self,
        source: SourceRecord | Ref[Literal["source_record"]] | str | Provenance,
        *,
        selector: str | None = None,
        basis: Literal["reported", "observed", "derived", "inferred", "curated"] = "reported",
        method: Method | tuple[str, str] | None = None,
        explanation: str | None = None,
    ) -> Provenance:
        if isinstance(source, Provenance):
            return source
        src_id = source.id if isinstance(source, (SourceRecord, Ref)) else source
        method_obj = Method(name=method[0], version=method[1]) if isinstance(method, tuple) else method
        sel_type = "json_pointer" if selector else None
        return Provenance(
            citations=(Citation(source=Ref(kind="source_record", id=src_id), selector_type=sel_type, selector=selector),),
            basis=basis,
            method=method_obj,
            explanation=explanation,
        )

    def add(self, record: SourceRecord | DomainRecord):
        if isinstance(record, SourceRecord):
            self._sources[record.id] = record
        else:
            self._records[(record.kind, record.id)] = record
        return record

    def extend(self, records: Iterable[SourceRecord | DomainRecord]):
        for rec in records:
            self.add(rec)
        return self

    def source(
        self,
        key: str,
        payload=None,
        *,
        provider: str | None = None,
        scheme: str | None = None,
        url: str | None = None,
        retrieved_at: datetime | None = None,
        source_modified_at: ReportedTime | None = None,
        retained: RetainedContent | None = None,
    ) -> SourceRecord:
        prov = provider or self.provider
        src_id = self.ids("source_record", f"{prov}:{key}")
        rec = SourceRecord(
            id=src_id,
            provider=prov,
            identifier=Identifier(scheme=scheme or prov, value=key),
            input_snapshot_id=self.input_id,
            url=url,
            retrieved_at=retrieved_at,
            imported_at=self.now,
            source_modified_at=source_modified_at,
            payload=payload,
            retained=retained,
        )
        self._sources[rec.id] = rec
        return rec

    def committee_term(
        self,
        key: str,
        *,
        congress: PositiveInt,
        chamber: Chamber = "unknown",
        name: str | None = None,
        committee_code: str | None = None,
        committee_level: Literal["full", "subcommittee", "unknown"] = "unknown",
        committee_type: str = "unknown",
        source_committee_type: str | None = None,
        parent: Ref[Literal["committee_term"]] | str | None = None,
        committee: Ref[Literal["committee"]] | str | None = None,
        active: DateRange | None = None,
        website: str | None = None,
        identifiers: tuple[Identifier, ...] = (),
        source: SourceRecord | Ref[Literal["source_record"]] | str | Provenance,
        selector: str | None = None,
    ) -> Ref[Literal["committee_term"]]:
        prov = self._provenance(source, selector=selector)
        if committee is None:
            comm_id = self.ids("committee", key)
            if ("committee", comm_id) not in self._records:
                self.add(Committee(id=comm_id, label=name or committee_code or key, provenance=prov))
            comm_ref = Ref(kind="committee", id=comm_id)
        else:
            comm_ref = committee if isinstance(committee, Ref) else Ref(kind="committee", id=committee)

        parent_ref = (
            None if parent is None
            else (parent if isinstance(parent, Ref) else Ref(kind="committee_term", id=parent))
        )
        term_id = self.ids("committee_term", f"{congress}:{key}")
        term = CommitteeTerm(
            id=term_id,
            committee=comm_ref,
            congress=congress,
            name=name,
            chamber=chamber,
            committee_code=committee_code,
            committee_level=committee_level,
            committee_type=committee_type,
            source_committee_type=source_committee_type,
            parent=parent_ref,
            active=active,
            website=website,
            identifiers=identifiers,
            provenance=prov,
        )
        self.add(term)
        return Ref(kind="committee_term", id=term.id)

    def meeting(
        self,
        key: str,
        *,
        title: str | None = None,
        congress: PositiveInt | None = None,
        congress_session: Literal[1, 2, 3] | None = None,
        chamber: Chamber = "unknown",
        meeting_type: str = "unknown",
        source_type: str | None = None,
        status: str = "unknown",
        source_status: str | None = None,
        access: str = "unknown",
        scheduled_start: ReportedTime | None = None,
        scheduled_end: ReportedTime | None = None,
        actual_start: ReportedTime | None = None,
        actual_end: ReportedTime | None = None,
        location: Location | None = None,
        occurrences: Iterable[MeetingSitting] = (),
        committees: Iterable[ConveningCommittee | Ref[Literal["committee_term"]] | str] = (),
        identifiers: tuple[Identifier, ...] = (),
        field_evidence: tuple[FieldEvidence, ...] = (),
        source: SourceRecord | Ref[Literal["source_record"]] | str | Provenance,
        selector: str | None = None,
    ) -> Ref[Literal["meeting"]]:
        prov = self._provenance(source, selector=selector)
        conv_list: list[ConveningCommittee] = []
        for c in committees:
            if isinstance(c, ConveningCommittee):
                conv_list.append(c)
            elif isinstance(c, Ref):
                conv_list.append(ConveningCommittee(committee=c, provenance=prov))
            else:
                conv_list.append(ConveningCommittee(committee=Ref(kind="committee_term", id=c), provenance=prov))
        m_id = self.ids("meeting", key)
        rec = Meeting(
            id=m_id,
            title=title,
            congress=congress,
            congress_session=congress_session,
            chamber=chamber,
            meeting_type=meeting_type,
            source_type=source_type,
            status=status,
            source_status=source_status,
            access=access,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            actual_start=actual_start,
            actual_end=actual_end,
            location=location,
            occurrences=tuple(occurrences),
            committees=tuple(conv_list),
            identifiers=identifiers,
            field_evidence=field_evidence,
            provenance=prov,
        )
        self.add(rec)
        return Ref(kind="meeting", id=rec.id)

    def appearance(
        self,
        key: str,
        *,
        meeting: Ref[Literal["meeting"]] | str,
        name: RecordedName | str,
        roles: Iterable[str] = ("witness",),
        participation: str = "listed",
        position: str | None = None,
        organization_name: str | None = None,
        on_behalf_of: str | None = None,
        location: str | None = None,
        panel_label: str | None = None,
        panel_order: int | None = None,
        person_bioguide_id: str | None = None,
        order: int | None = None,
        source: SourceRecord | Ref[Literal["source_record"]] | str | Provenance,
        selector: str | None = None,
    ) -> Ref[Literal["appearance"]]:
        prov = self._provenance(source, selector=selector)
        m_ref = meeting if isinstance(meeting, Ref) else Ref(kind="meeting", id=meeting)
        rec_name = name if isinstance(name, RecordedName) else RecordedName(display=name)
        aff = (
            Affiliation(
                position=position,
                organization_name=organization_name,
                on_behalf_of=on_behalf_of,
                location=location,
            )
            if any((position, organization_name, on_behalf_of, location))
            else None
        )
        app_id = self.ids("appearance", key)
        rec = Appearance(
            id=app_id,
            meeting=m_ref,
            panel_label=panel_label,
            panel_order=panel_order,
            person_bioguide_id=person_bioguide_id,
            name=rec_name,
            roles=tuple(roles),
            participation=participation,
            affiliation=aff,
            position=position,
            organization_name=organization_name,
            on_behalf_of=on_behalf_of,
            location=location,
            order=order,
            provenance=prov,
        )
        self.add(rec)
        return Ref(kind="appearance", id=rec.id)

    def material(
        self,
        key: str,
        *,
        title: str | None = None,
        material_type: Literal["document", "recording", "text"] = "document",
        category: MaterialCategory = "unknown",
        document_type: str | None = None,
        source_document_groups: Iterable[str] = (),
        congress: PositiveInt | None = None,
        chamber: Chamber = "unknown",
        proceeding_dates: Iterable[ReportedTime] = (),
        provider: str | None = None,
        channel: Ref[Literal["channel"]] | None = None,
        published_at: ReportedTime | None = None,
        source_modified_at: ReportedTime | None = None,
        generated_at: ReportedTime | None = None,
        duration_seconds: Seconds | None = None,
        page_count: int | None = None,
        production: Literal["publisher", "human", "automatic", "mixed", "unknown"] = "unknown",
        files: Iterable[MaterialFile] = (),
        meetings: Iterable[Ref[Literal["meeting"]] | str] = (),
        appearances: Iterable[Ref[Literal["appearance"]] | str] = (),
        committees: Iterable[Ref[Literal["committee_term"]] | str] = (),
        actions: Iterable[Ref | str] = (),
        role: MaterialRole | None = None,
        identifiers: tuple[Identifier, ...] = (),
        field_evidence: tuple[FieldEvidence, ...] = (),
        source: SourceRecord | Ref[Literal["source_record"]] | str | Provenance,
        selector: str | None = None,
    ) -> Ref[Literal["material"]]:
        prov = self._provenance(source, selector=selector)
        if material_type == "recording":
            details = RecordingDetails(medium="video", provider=provider, channel=channel)
        elif material_type == "text":
            t_cat = category if category in ("transcript", "captions", "translation", "summary", "other", "unknown") else "unknown"
            details = TextDetails(category=t_cat, production=production)
        else:
            d_cat = category if category not in ("captions", "translation", "summary") else "other"
            details = DocumentDetails(category=d_cat)

        m_ids = tuple(m.id if isinstance(m, Ref) else m for m in meetings)
        a_ids = tuple(a.id if isinstance(a, Ref) else a for a in appearances)
        c_ids = tuple(c.id if isinstance(c, Ref) else c for c in committees)
        act_ids = tuple(ac.id if isinstance(ac, Ref) else ac for ac in actions)

        mat_id = self.ids("material", key)
        rec = Material(
            id=mat_id,
            title=title,
            congress=congress,
            chamber=chamber,
            proceeding_dates=tuple(proceeding_dates),
            details=details,
            document_type=document_type,
            source_document_groups=tuple(source_document_groups),
            published_at=published_at,
            source_modified_at=source_modified_at,
            generated_at=generated_at,
            duration_seconds=duration_seconds,
            page_count=page_count,
            files=tuple(files),
            meeting_ids=m_ids,
            appearance_ids=a_ids,
            committee_ids=c_ids,
            action_ids=act_ids,
            identifiers=identifiers,
            field_evidence=field_evidence,
            provenance=prov,
        )
        self.add(rec)
        mat_ref = Ref(kind="material", id=rec.id)

        link_role = role or (
            "recording" if material_type == "recording"
            else (category if category in (
                "transcript", "captions", "statement", "biography", "disclosure",
                "questions_for_record", "responses_for_record", "notice", "agenda", "amendment", "supporting",
            ) else "supporting")
        )
        for m_id in m_ids:
            self.add(MaterialLink(
                id=self.ids("material_link", f"{key}:meeting:{m_id}"),
                material=mat_ref,
                subject=Ref(kind="meeting", id=m_id),
                role=link_role,
                provenance=prov,
            ))
        for a_id in a_ids:
            self.add(MaterialLink(
                id=self.ids("material_link", f"{key}:appearance:{a_id}"),
                material=mat_ref,
                subject=Ref(kind="appearance", id=a_id),
                role=link_role,
                provenance=prov,
            ))
        for c_id in c_ids:
            self.add(MaterialLink(
                id=self.ids("material_link", f"{key}:committee:{c_id}"),
                material=mat_ref,
                subject=Ref(kind="committee_term", id=c_id),
                role=link_role,
                provenance=prov,
            ))
        return mat_ref

    def edge(
        self,
        key: str,
        *,
        source_node: Ref,
        target_node: Ref,
        relation: EdgeRelation = "attaches_to",
        role: str | None = None,
        coverage: Literal["full", "partial", "unknown"] = "unknown",
        metadata: dict[str, str | int | float | bool | None] | None = None,
        source: SourceRecord | Ref[Literal["source_record"]] | str | Provenance,
        selector: str | None = None,
    ) -> Ref[Literal["edge"]]:
        prov = self._provenance(source, selector=selector)
        edge_id = self.ids("edge", key)
        rec = Edge(
            id=edge_id,
            source=source_node,
            target=target_node,
            relation=relation,
            role=role,
            coverage=coverage,
            metadata=metadata or {},
            provenance=prov,
        )
        self.add(rec)
        return Ref(kind="edge", id=rec.id)

    def build(self) -> Catalog:
        return Catalog(
            sources=tuple(self._sources.values()),
            records=tuple(self._records.values()),
        )
