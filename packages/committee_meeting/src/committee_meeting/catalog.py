"""Complete-catalog validation, separate from validating an individual record."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .assessments import Assessment
from .committees import Channel, Committee, CommitteeChannel, CommitteeMembership, CommitteeRelation, CommitteeTerm
from .common import Model, Ref
from .legislation import Amendment, AmendmentGroup, LegislativeItem, MeetingSubject, Vote
from .issues import DataIssue
from .materials import Material, MaterialLink, MaterialRelation, MaterialVersion, Representation, SpeakerAttribution
from .meetings import Appearance, Meeting, MeetingOccurrence, MeetingRelation, Organization, Panel, Person
from .provenance import SourceRecord
from .publication import SCHEMA_VERSION, SchemaVersion

DomainRecord = Annotated[
    Committee | CommitteeTerm | CommitteeRelation | Channel | CommitteeChannel | CommitteeMembership
    | Meeting | MeetingOccurrence | MeetingRelation | Panel | Person | Organization | Appearance
    | Material | MaterialVersion | Representation | MaterialLink | MaterialRelation | SpeakerAttribution
    | LegislativeItem | MeetingSubject | Amendment | AmendmentGroup | Vote | Assessment | DataIssue,
    Field(discriminator="kind"),
]


def _references(value):
    """Visit typed model fields, never interpret arbitrary source payload as links."""
    if isinstance(value, Ref):
        yield value
    elif isinstance(value, Model):
        for name in type(value).model_fields:
            yield from _references(getattr(value, name))
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

    @model_validator(mode="after")
    def check_graph(self):
        index = {}
        for item in (*self.sources, *self.records):
            key = (item.kind, item.id)
            if key in index:
                raise ValueError(f"duplicate record identity: {key}")
            index[key] = item

        def resolve(ref):
            return index[(ref.kind, ref.id)]

        def require(condition, message):
            if not condition:
                raise ValueError(message)

        for item in self.records:
            for ref in _references(item):
                require((ref.kind, ref.id) in index, f"{item.kind}/{item.id}: missing {ref.kind}/{ref.id}")
            paths = [e.path for e in item.field_evidence]
            require(len(paths) == len(set(paths)), f"{item.id}: duplicate field evidence paths")
            if paths:
                document = item.model_dump(mode="json")
                for path in paths:
                    require(_pointer_exists(document, path), f"{item.id}: field evidence path does not exist: {path}")

        for item in self.records:
            if isinstance(item, DataIssue) and item.field_path:
                require(_pointer_exists(resolve(item.subject).model_dump(mode="json"), item.field_path),
                        f"{item.id}: issue field path does not exist: {item.field_path}")
            if isinstance(item, CommitteeTerm) and item.parent:
                parent = resolve(item.parent)
                require(parent.congress == item.congress, f"{item.id}: parent committee is from another Congress")
            if isinstance(item, Meeting):
                committees = [c.committee.id for c in item.committees]
                require(len(committees) == len(set(committees)), f"{item.id}: repeated convening committee")
                for association in item.committees:
                    term = resolve(association.committee)
                    require(item.congress is None or term.congress == item.congress, f"{item.id}: committee Congress differs")

            # A child cannot quietly acquire another proceeding's panel or sitting.
            if isinstance(item, (Panel, Appearance, Amendment, Vote)) and item.occurrence:
                occurrence = resolve(item.occurrence)
                require(occurrence.meeting == item.meeting, f"{item.id}: occurrence belongs to another meeting")
            if isinstance(item, Appearance) and item.panel:
                panel = resolve(item.panel)
                require(panel.meeting == item.meeting, f"{item.id}: panel belongs to another meeting")
                require(not (panel.occurrence and item.occurrence) or panel.occurrence == item.occurrence,
                        f"{item.id}: panel and appearance have different occurrences")

            if isinstance(item, MaterialVersion) and item.supersedes:
                previous = resolve(item.supersedes)
                require(previous.material == item.material, f"{item.id}: superseded version belongs to another material")
            if isinstance(item, MaterialLink) and item.version:
                require(resolve(item.version).material == item.material, f"{item.id}: linked version belongs to another material")
                if item.extent:
                    require(resolve(item.extent.representation).version == item.version,
                            f"{item.id}: extent file belongs to another version")
            if isinstance(item, MaterialRelation):
                for extent, version in ((item.subject_extent, item.subject), (item.related_extent, item.related)):
                    if extent:
                        require(resolve(extent.representation).version == version,
                                f"{item.id}: extent file belongs to another version")
            if isinstance(item, Amendment) and item.target and item.target.kind == "amendment":
                require(resolve(item.target).meeting == item.meeting, f"{item.id}: target amendment belongs to another meeting")
            if isinstance(item, AmendmentGroup):
                require(len(item.members) == len(set(m.id for m in item.members)), f"{item.id}: repeated group member")
                for member in item.members:
                    require(resolve(member).meeting == item.meeting, f"{item.id}: group member belongs to another meeting")
            if isinstance(item, Vote):
                if item.committee:
                    meeting = resolve(item.meeting)
                    require(meeting.congress is None or resolve(item.committee).congress == meeting.congress,
                            f"{item.id}: voting committee Congress differs")
                if item.subject and item.subject.kind in ("amendment", "amendment_group"):
                    require(resolve(item.subject).meeting == item.meeting, f"{item.id}: vote subject belongs to another meeting")
                people = [b.person.id for b in item.ballots if b.person]
                require(len(people) == len(set(people)), f"{item.id}: duplicate ballot for person")
            if isinstance(item, (MeetingRelation, MaterialRelation)):
                require(item.subject != item.related, f"{item.id}: relationship cannot target itself")
            if isinstance(item, CommitteeRelation):
                require(item.predecessor != item.successor, f"{item.id}: committee relationship cannot target itself")

        # Parent/revision/amendment chains must be finite. Uncertain equivalence
        # relations are deliberately not interpreted as transitive identity merges.
        for cls, attribute in ((CommitteeTerm, "parent"), (MaterialVersion, "supersedes"), (Amendment, "target")):
            completed = set()
            for item in self.records:
                if not isinstance(item, cls):
                    continue
                seen, current = set(), item
                while current.id not in completed:
                    require(current.id not in seen, f"{item.id}: cycle in {attribute}")
                    seen.add(current.id)
                    ref = getattr(current, attribute)
                    if not ref or ref.kind != item.kind:
                        break
                    current = resolve(ref)
                completed.update(seen)
        return self
