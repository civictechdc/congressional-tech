"""Committee Explorer model. Domain classes live in the named modules."""
from .catalog import Catalog, DomainRecord
from .committees import Channel, Committee, CommitteeTerm
from .graph import CatalogGraph
from .issues import DataIssue, IssueResolution
from .materials import DocumentDetails, Material, MaterialFile, MaterialLink, MaterialVersion, RecordingDetails, Representation, TextDetails
from .meetings import Affiliation, Appearance, ConveningCommittee, Meeting, MeetingOccurrence, MeetingSitting, RecordedName
from .provenance import Citation, FieldEvidence, Method, Provenance, SourceRecord
from .publication import SCHEMA_VERSION, CoverageMetric, PublicationManifest

__all__ = [
    "Affiliation",
    "Appearance",
    "Catalog",
    "CatalogGraph",
    "Channel",
    "Citation",
    "Committee",
    "CommitteeTerm",
    "ConveningCommittee",
    "CoverageMetric",
    "DataIssue",
    "DocumentDetails",
    "DomainRecord",
    "FieldEvidence",
    "IssueResolution",
    "Material",
    "MaterialFile",
    "MaterialLink",
    "MaterialVersion",
    "Meeting",
    "MeetingOccurrence",
    "MeetingSitting",
    "Method",
    "Provenance",
    "PublicationManifest",
    "RecordedName",
    "RecordingDetails",
    "Representation",
    "SCHEMA_VERSION",
    "SourceRecord",
    "TextDetails",
]
