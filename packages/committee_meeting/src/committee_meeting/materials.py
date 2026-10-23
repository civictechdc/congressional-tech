"""Materials, their embedded files, and supported links to proceedings."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import Chamber, Count, Model, PositiveInt, Ref, ReportedTime, Seconds, Sha256, Text, WebUrl
from .provenance import Record, RetainedContent

DocumentCategory = Literal[
    "transcript", "statement", "biography", "disclosure", "questions_for_record",
    "responses_for_record", "notice", "agenda", "amendment", "vote", "report",
    "bill_text", "witness_list", "hearing_record", "committee_print", "supporting", "errata", "other", "unknown",
]

TextCategory = Literal["transcript", "captions", "translation", "summary", "other", "unknown"]

MaterialRole = Literal[
    "recording", "transcript", "captions", "statement", "biography", "disclosure",
    "questions_for_record", "responses_for_record", "notice", "agenda", "amendment",
    "vote_record", "supporting", "other", "unknown",
]


class DocumentDetails(Model):
    type: Literal["document"] = "document"
    category: DocumentCategory = "unknown"


class RecordingDetails(Model):
    type: Literal["recording"] = "recording"
    medium: Literal["video", "audio", "unknown"] = "unknown"
    coverage: Literal["full", "clip", "compilation", "unknown"] = "unknown"
    provider: Text | None = None
    channel: Ref[Literal["channel"]] | None = None


class TextDetails(Model):
    """A distinct text product, including captions and generated transcripts."""

    type: Literal["text"] = "text"
    category: TextCategory = "unknown"
    production: Literal["publisher", "human", "automatic", "mixed", "unknown"] = "unknown"


class ContentSchema(Model):
    name: Text
    version: Text
    url: WebUrl | None = None


class PayloadArtifactBase(Model):
    """Shared fields and digest validator for payload artifacts/encodings."""

    format_label: str | None = None
    media_type: str | None = None
    encoding: str | None = None
    byte_size: Count | None = None
    sha256: Sha256 | None = None
    saved_copy_sha256: Sha256 | None = None
    saved_filename: str | None = None
    retained: RetainedContent | None = None
    content_schema: ContentSchema | None = None

    @model_validator(mode="after")
    def retained_digest_matches(self):
        if self.retained and self.sha256 and self.retained.sha256 != self.sha256:
            raise ValueError(f"{'representation' if getattr(self, 'kind', None) == 'representation' else 'file'} and retained content must have the same digest")
        return self


class MaterialFile(PayloadArtifactBase):
    """An embedded file/encoding of a material, including viewer-data saved copies."""

    url: WebUrl | None = None
    resolved_url: WebUrl | None = None
    role: Literal["landing", "download", "player", "stream", "api", "other", "unknown"] = "unknown"
    usable: bool | None = None
    recovery_status: Literal["captured", "recovered", "group_recovered", "error_page", "unverified"] | None = None
    version_label: str | None = None
    published_at: ReportedTime | None = None
    duration_seconds: Seconds | None = None


class Material(Record):
    """One described work/recording/track with embedded files and Explorer/Viewer metadata."""

    kind: Literal["material"] = "material"
    title: str | None = None
    congress: PositiveInt | None = None
    chamber: Chamber = "unknown"
    proceeding_dates: tuple[ReportedTime, ...] = ()
    # Type, category, provider and channel live only here; a copy beside it
    # could disagree after source records are merged field by field.
    details: Annotated[DocumentDetails | RecordingDetails | TextDetails, Field(discriminator="type")] = DocumentDetails()
    document_type: str | None = None
    source_document_groups: tuple[str, ...] = ()
    published_at: ReportedTime | None = None
    source_modified_at: ReportedTime | None = None
    generated_at: ReportedTime | None = None
    languages: tuple[Text, ...] = ()
    duration_seconds: Seconds | None = None
    page_count: Count | None = None
    files: tuple[MaterialFile, ...] = ()
    meeting_ids: tuple[Text, ...] = ()
    appearance_ids: tuple[Text, ...] = ()
    committee_ids: tuple[Text, ...] = ()
    action_ids: tuple[Text, ...] = ()


class MaterialVersion(Record):
    """An edition or revision of a material, retained when distinct editions require separate identity."""

    kind: Literal["material_version"] = "material_version"
    material: Ref[Literal["material"]]
    label: str | None = None
    supersedes: Ref[Literal["material_version"]] | None = None
    published_at: ReportedTime | None = None
    source_modified_at: ReportedTime | None = None
    generated_at: ReportedTime | None = None
    languages: tuple[Text, ...] = ()
    duration_seconds: Seconds | None = None
    page_count: Count | None = None


class MaterialLocation(Model):
    url: WebUrl
    role: Literal["landing", "download", "player", "stream", "api", "other", "unknown"] = "unknown"


class Representation(Record, PayloadArtifactBase):
    """A standalone file/encoding record when tracked independently of Material.files."""

    kind: Literal["representation"] = "representation"
    version: Ref[Literal["material_version"]]
    locations: tuple[MaterialLocation, ...] = ()


def representation_files(representation, *, version_label=None, published_at=None, duration_seconds=None):
    """The embedded files equivalent to a standalone representation, one per location.

    A retained body without a public location is still a file of the material.
    """
    values = dict(media_type=representation.media_type, format_label=representation.format_label,
                  encoding=representation.encoding, byte_size=representation.byte_size, sha256=representation.sha256,
                  saved_copy_sha256=representation.saved_copy_sha256, saved_filename=representation.saved_filename,
                  retained=representation.retained, content_schema=representation.content_schema,
                  version_label=version_label, published_at=published_at, duration_seconds=duration_seconds)
    if not representation.locations:
        return (MaterialFile(**values),)
    return tuple(MaterialFile(url=location.url, role=location.role, **values) for location in representation.locations)


class MaterialLink(Record):
    """A material's role for a subject. The same material can serve many subjects."""

    kind: Literal["material_link"] = "material_link"
    material: Ref[Literal["material"]]
    version: Ref[Literal["material_version"]] | None = None
    subject: Ref[Literal[
        "meeting", "occurrence", "appearance", "committee_term", "legislative_item",
        "amendment", "amendment_group", "vote",
    ]]
    role: MaterialRole = "unknown"
    coverage: Literal["full", "partial", "unknown"] = "unknown"


class MaterialRelation(Record):
    """A directed relationship between particular materials or material versions."""

    kind: Literal["material_relation"] = "material_relation"
    subject: Ref[Literal["material", "material_version"]]
    related: Ref[Literal["material", "material_version"]]
    relation: Literal["derived_from", "transcribes", "translation_of", "corrects", "part_of", "alternate_of"]
