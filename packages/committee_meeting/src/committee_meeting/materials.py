"""Materials, their editions and files, and supported links to proceedings."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import Chamber, Count, Extent, Model, PositiveInt, Ref, ReportedTime, Seconds, Sha256, Text, WebUrl
from .provenance import Record, RetainedContent


class DocumentDetails(Model):
    type: Literal["document"] = "document"
    category: Literal[
        "transcript", "statement", "biography", "disclosure", "questions_for_record",
        "responses_for_record", "notice", "agenda", "amendment", "vote", "report",
        "bill_text", "witness_list", "hearing_record", "supporting", "errata", "other", "unknown",
    ] = "unknown"


class RecordingDetails(Model):
    type: Literal["recording"] = "recording"
    medium: Literal["video", "audio", "unknown"] = "unknown"
    coverage: Literal["full", "clip", "compilation", "unknown"] = "unknown"
    provider: Text | None = None
    channel: Ref[Literal["channel"]] | None = None


class TextDetails(Model):
    """A distinct text product, including captions and generated transcripts."""

    type: Literal["text"] = "text"
    category: Literal["transcript", "captions", "translation", "summary", "other", "unknown"] = "unknown"
    production: Literal["publisher", "human", "automatic", "mixed", "unknown"] = "unknown"


class Material(Record):
    """One described work/recording/track; it may have no accessible file or meeting."""

    kind: Literal["material"] = "material"
    title: str | None = None
    congress: PositiveInt | None = None
    chamber: Chamber = "unknown"
    proceeding_dates: tuple[ReportedTime, ...] = ()
    details: Annotated[DocumentDetails | RecordingDetails | TextDetails, Field(discriminator="type")]


class MaterialVersion(Record):
    """An edition or revision of a material, not a new version on every crawl."""

    kind: Literal["material_version"] = "material_version"
    material: Ref[Literal["material"]]
    label: str | None = None
    supersedes: Ref[Literal["material_version"]] | None = None
    published_at: ReportedTime | None = None
    source_modified_at: ReportedTime | None = None
    generated_at: ReportedTime | None = None
    languages: tuple[Text, ...] = ()  # BCP 47 tags when known; preserve raw labels in evidence.
    duration_seconds: Seconds | None = None
    page_count: Count | None = None


class MaterialLocation(Model):
    url: WebUrl
    role: Literal["landing", "download", "player", "stream", "api", "other", "unknown"] = "unknown"


class XmlRoot(Model):
    """Actual XML root metadata; amendment-doc is not an amendment identifier."""

    local_name: Text
    namespace: str | None = None


class ContentSchema(Model):
    name: Text
    version: Text
    url: WebUrl | None = None


class Representation(Record):
    """A file/encoding of one version; a reported URL does not prove fetched bytes.

    Different formats can encode the same version. Share a representation across
    source listings only with evidence of identity; identical basenames do not
    establish it. Locations retain exact provider URLs, never guessed suffixes.
    """

    kind: Literal["representation"] = "representation"
    version: Ref[Literal["material_version"]]
    locations: tuple[MaterialLocation, ...] = ()
    media_type: str | None = None
    format_label: str | None = None
    encoding: str | None = None
    byte_size: Count | None = None
    sha256: Sha256 | None = None
    retained: RetainedContent | None = None
    xml_root: XmlRoot | None = None
    content_schema: ContentSchema | None = None

    @model_validator(mode="after")
    def retained_digest_matches(self):
        if self.retained and self.sha256 and self.retained.sha256 != self.sha256:
            raise ValueError("representation and retained content must have the same digest")
        return self


class MaterialLink(Record):
    """A material's role for a subject. The same material can serve many subjects."""

    kind: Literal["material_link"] = "material_link"
    material: Ref[Literal["material"]]
    version: Ref[Literal["material_version"]] | None = None
    subject: Ref[Literal[
        "meeting", "occurrence", "appearance", "committee_term", "legislative_item",
        "amendment", "amendment_group", "vote",
    ]]
    role: Literal[
        "recording", "transcript", "captions", "statement", "biography", "disclosure",
        "questions_for_record", "responses_for_record", "notice", "agenda", "amendment",
        "vote_record", "supporting", "other", "unknown",
    ] = "unknown"
    coverage: Literal["full", "partial", "unknown"] = "unknown"  # For this subject, not the whole file.
    extent: Extent | None = None

    @model_validator(mode="after")
    def locate_exact_version(self):
        if self.extent is not None and self.version is None:
            raise ValueError("a page/time extent requires an exact material version")
        return self


class MaterialRelation(Record):
    """A directed relationship between particular material versions.

    Example: generated transcript subject -> recording related, derived_from.
    Standalone printed transcripts do not require this relationship.
    """

    kind: Literal["material_relation"] = "material_relation"
    subject: Ref[Literal["material_version"]]
    related: Ref[Literal["material_version"]]
    relation: Literal["derived_from", "transcribes", "translation_of", "corrects", "part_of", "alternate_of"]
    subject_extent: Extent | None = None
    related_extent: Extent | None = None


class SpeakerAttribution(Record):
    """Optional bridge from a transcript's local speaker key to an appearance.

    Transcript turns and text remain in the existing body schema. A local speaker
    can be unresolved; do not allocate a Person just to fill this reference.
    """

    kind: Literal["speaker_attribution"] = "speaker_attribution"
    representation: Ref[Literal["representation"]]
    speaker_key: Text
    appearance: Ref[Literal["appearance"]]
