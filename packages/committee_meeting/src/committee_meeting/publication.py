"""Reproducible static exports. These are publication metadata, not crawler state."""
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from .common import Count, DateRange, Model, PositiveInt, Sha256, Text
from .provenance import Method, RetainedContent

SCHEMA_VERSION = "0.1.0-draft.2"
SchemaVersion = Literal["0.1.0-draft.2"]


class InputSnapshot(Model):
    id: Text
    provider: Text
    artifact: RetainedContent
    revision: str | None = None  # Git commit, upstream snapshot ID, etc.
    coverage: DateRange | None = None  # Subject dates represented; not retrieval dates.
    first_observed_at: AwareDatetime | None = None
    last_observed_at: AwareDatetime | None = None
    imported_at: AwareDatetime | None = None
    last_attempt_at: AwareDatetime | None = None
    last_attempt_status: Literal["succeeded", "partial", "failed", "not_run", "unknown"] = "unknown"
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def ordered_observations(self):
        if self.first_observed_at and self.last_observed_at and self.first_observed_at > self.last_observed_at:
            raise ValueError("observation range is reversed")
        return self


class ExportPartition(Model):
    path: Text  # Relative to the manifest; serving layout belongs to the app.
    media_type: Text = "application/json"  # Decoders use this, not filename extensions.
    role: Literal["index", "details", "sources", "coverage", "download", "search"]
    schema_name: Text
    schema_version: Text
    sha256: Sha256
    byte_size: Count
    record_count: Count
    congress: PositiveInt | None = None


class SourceScope(Model):
    """Coverage of an intended source family, including one never collected.

    Unlike InputSnapshot this does not require an artifact that does not exist.
    Unknown population size stays unknown; it is not a zero denominator.
    """

    provider: Text
    scope: Text
    coverage: DateRange | None = None
    status: Literal["included", "partial", "not_collected", "not_supported", "failed", "unknown"]
    input_snapshot_ids: tuple[Text, ...] = ()
    explanation: Text

    @model_validator(mode="after")
    def included_has_input(self):
        if self.status in ("included", "partial") and not self.input_snapshot_ids:
            raise ValueError("included/partial source scope requires an input snapshot")
        return self


class PublicationManifest(Model):
    schema_version: SchemaVersion = SCHEMA_VERSION
    publication_id: Text
    generated_at: AwareDatetime
    producer: Method
    inputs: Annotated[tuple[InputSnapshot, ...], Field(min_length=1)]
    source_scopes: tuple[SourceScope, ...] = ()  # Empty means scope has not been described.
    partitions: tuple[ExportPartition, ...] = ()
    previous_publication_id: str | None = None
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def unique_inputs_and_paths(self):
        if len({item.id for item in self.inputs}) != len(self.inputs):
            raise ValueError("input snapshot IDs must be unique")
        if len({item.path for item in self.partitions}) != len(self.partitions):
            raise ValueError("partition paths must be unique")
        input_ids = {item.id for item in self.inputs}
        if any(id not in input_ids for scope in self.source_scopes for id in scope.input_snapshot_ids):
            raise ValueError("source scope references an unknown input snapshot")
        return self


class CoverageMetric(Model):
    """A published count with a stated population; never an unexplained percent."""

    id: Text
    label: Text
    unit: Literal["meeting", "occurrence", "material", "representation", "appearance", "source_record"]
    population: Text  # Readable eligibility rules, including statuses and date window.
    method: Method  # Versioned counting/deduplication rule owned by the exporter.
    input_snapshot_ids: Annotated[tuple[Text, ...], Field(min_length=1)]
    numerator: Count
    denominator: Count
    evidence_basis: Literal["confirmed", "inferred", "mixed"]
    unknown: Count | None = None  # A subset of the denominator, when measured.
    scope: str | None = None

    @model_validator(mode="after")
    def bounded_counts(self):
        if self.numerator > self.denominator:
            raise ValueError("numerator exceeds denominator")
        if self.unknown is not None and self.numerator + self.unknown > self.denominator:
            raise ValueError("available and unknown counts exceed denominator")
        return self
