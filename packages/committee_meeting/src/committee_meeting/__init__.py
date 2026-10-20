"""Product-first Committee Explorer model. Domain classes live in the named modules."""
from .builder import CatalogBuilder
from .catalog import Catalog, DomainRecord
from .committees import Channel, Committee, CommitteeTerm
from .graph import CatalogGraph, Edge
from .issues import DataIssue, IssueResolution
from .materials import DocumentDetails, Material, MaterialFile, MaterialLink, RecordingDetails, TextDetails
from .meetings import Affiliation, Appearance, ConveningCommittee, Meeting, MeetingSitting, RecordedName
from .provenance import Citation, FieldEvidence, Method, Provenance, SourceRecord
from .publication import SCHEMA_VERSION, CoverageMetric, PublicationManifest

__all__ = [
    "Affiliation",
    "Appearance",
    "Catalog",
    "CatalogBuilder",
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
    "Edge",
    "FieldEvidence",
    "IssueResolution",
    "Material",
    "MaterialFile",
    "MaterialLink",
    "Meeting",
    "MeetingSitting",
    "Method",
    "Provenance",
    "PublicationManifest",
    "RecordedName",
    "RecordingDetails",
    "SCHEMA_VERSION",
    "SourceRecord",
    "TextDetails",
]
