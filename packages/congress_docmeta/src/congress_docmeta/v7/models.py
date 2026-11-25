"""DocMeta V7.1 Pydantic v2 schemas: FRBR/ELI-DL conceptual models, Core Envelope triage, and 5 tight specialists."""

from __future__ import annotations

from copy import deepcopy
from difflib import SequenceMatcher
from enum import StrEnum
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

STRICT_CONFIG = ConfigDict(extra="forbid")

_ISO_DATE_RE = re.compile(r"^\d{4}(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?)?$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INVISIBLE_FORMAT_RE = re.compile(r"[\u202a-\u202e\u2066-\u2069\u200e\u200f\ufeff\u00ad]")


def _norm_ws(value: str) -> str:
    return " ".join(_INVISIBLE_FORMAT_RE.sub("", value).split())


def _ocr_fuzzy_similar(norm_val: str, norm_span: str) -> bool:
    """Permit clean OCR spell-correction when SpanRef is already anchored in DOC_TEXT.

    Rejects unrelated names and unmentioned acronym expansions (e.g., IRS -> Internal Revenue Service)
    by requiring high whole-string similarity and matching token counts without expansion.
    """
    if min(len(norm_val), len(norm_span)) < 5:
        return False
    val_toks = [tok.strip(".,;:()\"'") for tok in norm_val.split() if tok.strip(".,;:()\"'")]
    span_toks = [tok.strip(".,;:()\"'") for tok in norm_span.split() if tok.strip(".,;:()\"'")]
    if not val_toks or len(val_toks) != len(span_toks):
        return False
    if SequenceMatcher(None, norm_val, norm_span).ratio() < 0.78:
        return False
    return all(SequenceMatcher(None, vt, st).ratio() >= 0.70 for vt, st in zip(val_toks, span_toks))


def _text_matches_span(value: str, span_quote: str) -> bool:
    """Return True if value matches, reorders, or cleanly OCR-repairs span_quote."""
    norm_val = _norm_ws(value).casefold()
    norm_span = _norm_ws(span_quote).casefold()
    if not norm_val or not norm_span:
        return False
    if norm_val == norm_span or norm_val in norm_span:
        return True
    # Allow "Last, First" vs "First Last" ordering in spans when all non-trivial tokens match.
    val_tokens = [tok.strip(".,;:()\"'") for tok in norm_val.split() if tok.strip(".,;:()\"'")]
    span_tokens = {tok.strip(".,;:()\"'") for tok in norm_span.split() if tok.strip(".,;:()\"'")}
    if bool(val_tokens) and all(tok in span_tokens for tok in val_tokens):
        return True
    return _ocr_fuzzy_similar(norm_val, norm_span)


class DocStatus(StrEnum):
    """Orthogonal document usability and triage status (absorbs V6.5 error_or_non_document)."""

    usable = "usable"
    cover_or_toc = "cover_or_toc"
    govinfo_wrapper = "govinfo_wrapper"
    index_or_listing = "index_or_listing"
    catalog_xml = "catalog_xml"
    stub_or_blank = "stub_or_blank"
    error_or_block = "error_or_block"
    ocr_unreadable = "ocr_unreadable"


class MediaFormat(StrEnum):
    """Orthogonal document layout/medium (replaces slides_or_visual and event_web_page as genres)."""

    prose = "prose"
    slides = "slides"
    web_page = "web_page"
    table_or_form = "table_or_form"


class SpecialistFamily(StrEnum):
    """Five decomposed V7 Stage-2 specialist extraction families."""

    event_logistics = "event_logistics"
    testimony_bio_disclosure = "testimony_bio_disclosure"
    transcript_vote_attendance = "transcript_vote_attendance"
    correspondence_qfr_oversight = "correspondence_qfr_oversight"
    legislation_report_fiscal = "legislation_report_fiscal"


class PrimaryGenre(StrEnum):
    """14 orthogonal V7 primary document genres partitioned across 5 specialist families."""

    # 1. event_logistics
    hearing_or_markup_notice = "hearing_or_markup_notice"
    hearing_memo_or_witness_list = "hearing_memo_or_witness_list"
    # 2. testimony_bio_disclosure
    witness_testimony = "witness_testimony"
    member_statement = "member_statement"
    witness_biography = "witness_biography"
    truth_in_testimony = "truth_in_testimony"
    # 3. transcript_vote_attendance
    hearing_transcript = "hearing_transcript"
    committee_vote_or_action = "committee_vote_or_action"
    # 4. correspondence_qfr_oversight
    qfr_correspondence = "qfr_correspondence"
    oversight_or_committee_letter = "oversight_or_committee_letter"
    external_submission_or_comment = "external_submission_or_comment"
    # 5. legislation_report_fiscal
    bill_or_amendment = "bill_or_amendment"
    committee_or_agency_report = "committee_or_agency_report"
    budget_or_cost_estimate = "budget_or_cost_estimate"


GENRE_TO_FAMILY: dict[PrimaryGenre, SpecialistFamily] = {
    PrimaryGenre.hearing_or_markup_notice: SpecialistFamily.event_logistics,
    PrimaryGenre.hearing_memo_or_witness_list: SpecialistFamily.event_logistics,
    PrimaryGenre.witness_testimony: SpecialistFamily.testimony_bio_disclosure,
    PrimaryGenre.member_statement: SpecialistFamily.testimony_bio_disclosure,
    PrimaryGenre.witness_biography: SpecialistFamily.testimony_bio_disclosure,
    PrimaryGenre.truth_in_testimony: SpecialistFamily.testimony_bio_disclosure,
    PrimaryGenre.hearing_transcript: SpecialistFamily.transcript_vote_attendance,
    PrimaryGenre.committee_vote_or_action: SpecialistFamily.transcript_vote_attendance,
    PrimaryGenre.qfr_correspondence: SpecialistFamily.correspondence_qfr_oversight,
    PrimaryGenre.oversight_or_committee_letter: SpecialistFamily.correspondence_qfr_oversight,
    PrimaryGenre.external_submission_or_comment: SpecialistFamily.correspondence_qfr_oversight,
    PrimaryGenre.bill_or_amendment: SpecialistFamily.legislation_report_fiscal,
    PrimaryGenre.committee_or_agency_report: SpecialistFamily.legislation_report_fiscal,
    PrimaryGenre.budget_or_cost_estimate: SpecialistFamily.legislation_report_fiscal,
}

FAMILY_TO_GENRES: dict[SpecialistFamily, tuple[PrimaryGenre, ...]] = {
    family: tuple(genre for genre, mapped in GENRE_TO_FAMILY.items() if mapped == family)
    for family in SpecialistFamily
}


class Chamber(StrEnum):
    """Congressional or originating institutional chamber."""

    house = "house"
    senate = "senate"
    joint = "joint"
    commission = "commission"
    executive_or_external = "executive_or_external"


class PersonaRole(StrEnum):
    """Functional role of an active document actor."""

    witness = "witness"
    author_or_speaker = "author_or_speaker"
    chair = "chair"
    ranking_member = "ranking_member"
    presiding = "presiding"
    questioner = "questioner"
    sponsor = "sponsor"
    cosponsor = "cosponsor"
    amendment_offeror = "amendment_offeror"
    nominee = "nominee"
    introducer = "introducer"
    sender = "sender"
    recipient = "recipient"
    signatory = "signatory"
    staff = "staff"
    party_or_investigator = "party_or_investigator"


class EntityType(StrEnum):
    """Actor category for personas."""

    member = "member"
    gov_official = "gov_official"
    military_officer = "military_officer"
    judicial_or_exec_nominee = "judicial_or_exec_nominee"
    non_gov_person = "non_gov_person"
    staff = "staff"
    organization = "organization"


class EventType(StrEnum):
    """Congressional sitting or proceeding type."""

    hearing = "hearing"
    field_hearing = "field_hearing"
    nomination_hearing = "nomination_hearing"
    markup = "markup"
    business_meeting = "business_meeting"
    roundtable_or_briefing = "roundtable_or_briefing"
    floor_or_other = "floor_or_other"


class VenueKind(StrEnum):
    """Sitting location classification."""

    capitol_room = "capitol_room"
    field_site = "field_site"
    virtual = "virtual"
    hybrid = "hybrid"


class CorrespondenceDirection(StrEnum):
    """Directional flow on correspondence, QFRs, invitations, and oversight filings."""

    committee_to_witness = "committee_to_witness"
    witness_to_committee = "witness_to_committee"
    congress_to_agency = "congress_to_agency"
    agency_to_congress = "agency_to_congress"
    member_to_committee = "member_to_committee"
    committee_to_member = "committee_to_member"
    external_to_committee = "external_to_committee"
    foreign_gov_to_congress = "foreign_gov_to_congress"
    internal_exhibit_chain = "internal_exhibit_chain"


class SpanRef(BaseModel):
    """Exact verbatim character-offset evidence anchor into the document text slice."""

    model_config = STRICT_CONFIG

    quote: str = Field(..., min_length=1, description="Exact non-empty substring from document text.")
    start: int = Field(..., ge=0, description="Zero-based inclusive start character offset.")
    end: int = Field(..., gt=0, description="Zero-based exclusive end character offset.")

    @field_validator("quote")
    @classmethod
    def _quote_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("SpanRef.quote must contain non-whitespace characters.")
        return value

    @model_validator(mode="after")
    def _check_offsets(self) -> SpanRef:
        if self.end <= self.start:
            raise ValueError(f"SpanRef.end ({self.end}) must be strictly greater than start ({self.start}).")
        return self


class PersonaEntry(BaseModel):
    """Grounded actor entry shared across specialist extractors and conceptual records."""

    model_config = STRICT_CONFIG

    name: str = Field(..., min_length=1, description="Actor name as stated in text without honorifics/degrees.")
    name_span: SpanRef | None = Field(
        default=None,
        description="Required verbatim span anchor for usable specialist extraction.",
    )
    role: PersonaRole
    entity_type: EntityType
    title: str | None = None
    org: str | None = None
    org_span: SpanRef | None = None
    party_state: str | None = None
    creds: str | None = None
    on_behalf_of: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("PersonaEntry.name must not be blank.")
        return value

    @model_validator(mode="after")
    def _check_spans(self) -> PersonaEntry:
        if self.name_span is not None and not _text_matches_span(self.name, self.name_span.quote):
            raise ValueError(f"PersonaEntry.name {self.name!r} is not grounded in name_span {self.name_span.quote!r}.")
        if self.org_span is not None:
            if not self.org or not self.org.strip():
                raise ValueError("PersonaEntry.org must be populated when org_span is provided.")
            if not _text_matches_span(self.org, self.org_span.quote):
                raise ValueError(f"PersonaEntry.org {self.org!r} is not grounded in org_span {self.org_span.quote!r}.")
        return self


def _require_persona_name_spans(personas: list[PersonaEntry], field_name: str) -> None:
    for idx, persona in enumerate(personas):
        if persona.name_span is None:
            raise ValueError(f"{field_name}[{idx}] ({persona.name!r}) requires name_span in specialist extraction.")


# ---------------------------------------------------------------------------
# FRBR & ELI-DL Conceptual Domain Models (Future Scaffolding; Unpopulated in V7.3)
# ---------------------------------------------------------------------------
# Note: V7.3 emits per-document extraction observations only; archive SQL
# (`document-versions.sql`, `meeting-records-resolved.sql`) remains authoritative
# for document editions and committee sittings while these classes stay unpopulated.


class WorkRecord(BaseModel):
    """FRBR Group 1 Work: future conceptual scaffolding (unpopulated in V7.3 per-document outputs)."""

    model_config = STRICT_CONFIG

    work_id: str = Field(..., min_length=1)
    title: str | None = None
    primary_genre: PrimaryGenre | None = None
    status: DocStatus = DocStatus.usable
    congress: int | None = Field(default=None, ge=1, le=130)
    chamber: Chamber | None = None
    committees: list[str] = Field(default_factory=list)
    creators: list[PersonaEntry] = Field(default_factory=list)
    activity_id: str | None = None

    @model_validator(mode="after")
    def _check_work_status(self) -> WorkRecord:
        if self.status != DocStatus.usable and self.primary_genre is not None:
            raise ValueError("Non-usable WorkRecord must have primary_genre=None.")
        return self


class ExpressionRecord(BaseModel):
    """FRBR Group 1 Expression: future conceptual scaffolding (unpopulated in V7.3; document-versions.sql owns editions)."""

    model_config = STRICT_CONFIG

    expression_id: str = Field(..., min_length=1)
    work_id: str = Field(..., min_length=1)
    language: str = Field(default="en", min_length=2)
    media_format: MediaFormat | None = None
    version_label: str | None = None
    doc_date: str | None = None
    is_packet: bool = False
    contains_genres: list[PrimaryGenre] = Field(default_factory=list)
    supersedes_expression_id: str | None = None

    @model_validator(mode="after")
    def _check_packet(self) -> ExpressionRecord:
        if not self.is_packet and self.contains_genres:
            raise ValueError("ExpressionRecord.contains_genres must be empty when is_packet is False.")
        return self


class ManifestationRecord(BaseModel):
    """FRBR Group 1 Manifestation: future conceptual scaffolding (unpopulated in V7.3 per-document outputs)."""

    model_config = STRICT_CONFIG

    manifestation_id: str = Field(..., min_length=1)
    expression_id: str = Field(..., min_length=1)
    body_sha256: str = Field(..., pattern=_SHA256_RE.pattern)
    media_type: str | None = None
    byte_size: int | None = Field(default=None, ge=0)
    source_url: str | None = None
    source_filename: str | None = None
    link_key_hex: str | None = None
    text_sha256: str | None = Field(default=None, pattern=_SHA256_RE.pattern)


class ForeseenActivity(BaseModel):
    """EU ELI-DL ForeseenActivity: future conceptual scaffolding (unpopulated in V7.3; meeting-records-resolved.sql owns sittings)."""

    model_config = STRICT_CONFIG

    activity_id: str = Field(..., min_length=1)
    event_id: str | None = None
    event_type: EventType
    title: str | None = None
    scheduled_date: str | None = None
    scheduled_time: str | None = None
    venue_kind: VenueKind | None = None
    venue: str | None = None
    chamber: Chamber | None = None
    congress: int | None = Field(default=None, ge=1, le=130)
    committees: list[str] = Field(default_factory=list)
    foreseen_status: Literal["scheduled", "rescheduled", "postponed", "cancelled", "unknown"] = "scheduled"
    notice_work_ids: list[str] = Field(default_factory=list)


class RealizedActivity(BaseModel):
    """EU ELI-DL Activity: future conceptual scaffolding (unpopulated in V7.3; meeting-records-resolved.sql owns sittings)."""

    model_config = STRICT_CONFIG

    activity_id: str = Field(..., min_length=1)
    foreseen_activity_id: str | None = None
    event_id: str | None = None
    event_type: EventType
    title: str | None = None
    realized_date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    venue_kind: VenueKind | None = None
    venue: str | None = None
    chamber: Chamber | None = None
    congress: int | None = Field(default=None, ge=1, le=130)
    committees: list[str] = Field(default_factory=list)
    outcome_status: Literal["held", "recessed", "adjourned", "not_held", "unknown"] = "held"
    members_present: list[str] = Field(default_factory=list)
    transcript_work_ids: list[str] = Field(default_factory=list)


class SubmissionRecord(BaseModel):
    """UK Parliament Submission lifecycle: future conceptual scaffolding (unpopulated in V7.3 per-document outputs)."""

    model_config = STRICT_CONFIG

    submission_id: str = Field(..., min_length=1)
    work_id: str = Field(..., min_length=1)
    submission_kind: Literal[
        "oral_testimony",
        "written_testimony",
        "truth_in_testimony",
        "qfr_response",
        "public_comment",
        "compelled_production",
        "agency_report",
        "other",
    ]
    demand_type: Literal[
        "invitation",
        "rule_xi_requirement",
        "qfr_request",
        "subpoena",
        "statutory_mandate",
        "call_for_evidence",
        "unsolicited",
        "unknown",
    ] = "unknown"
    demand_work_id: str | None = None
    activity_id: str | None = None
    submitted_by: list[PersonaEntry] = Field(default_factory=list)
    submitted_to_committees: list[str] = Field(default_factory=list)
    submitted_date: str | None = None
    due_date: str | None = None
    disposition: Literal["admitted", "entered_in_record", "pending", "rejected", "withheld", "unknown"] = "unknown"
    subpoena_or_compelled: bool = False


# ---------------------------------------------------------------------------
# Stage 1: Core Envelope Triage Model
# ---------------------------------------------------------------------------


class CoreEnvelopeExtraction(BaseModel):
    """Stage 1 Core Envelope classification and bibliographic extraction (rationale-first)."""

    model_config = STRICT_CONFIG

    rationale: str = Field(
        ...,
        min_length=1,
        max_length=480,
        description="Concise CRANE/SLOT reasoning citing document cues before classification.",
    )
    status: DocStatus
    media_format: MediaFormat | None = None
    is_packet: bool = False
    contains_genres: list[PrimaryGenre] = Field(default_factory=list)
    primary_genre: PrimaryGenre | None = None
    specialist_family: SpecialistFamily | None = None
    subkind: str | None = None
    verbatim_title: str | None = None
    title_span: SpanRef | None = None
    doc_date: str | None = None
    date_spans: list[SpanRef] = Field(default_factory=list)
    chamber: Chamber | None = None
    congress: int | None = Field(default=None, ge=1, le=130)
    committees: list[str] = Field(default_factory=list)
    subcommittees: list[str] = Field(default_factory=list)
    gist: str | None = Field(default=None, max_length=220)
    topics: list[str] = Field(default_factory=list)

    @field_validator("rationale")
    @classmethod
    def _rationale_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("CoreEnvelopeExtraction.rationale must not be blank.")
        return value

    @field_validator("doc_date")
    @classmethod
    def _check_doc_date(cls, value: str | None) -> str | None:
        if value is not None and not _ISO_DATE_RE.fullmatch(value):
            raise ValueError(f"doc_date must be YYYY, YYYY-MM, or YYYY-MM-DD when set; got {value!r}.")
        return value

    @model_validator(mode="after")
    def _check_core_invariants(self) -> CoreEnvelopeExtraction:
        if self.status != DocStatus.usable:
            if self.primary_genre is not None:
                raise ValueError(f"primary_genre must be None when status={self.status.value}.")
            if self.specialist_family is not None:
                raise ValueError(f"specialist_family must be None when status={self.status.value}.")
            if self.is_packet:
                raise ValueError(f"is_packet must be False when status={self.status.value}.")
            if self.contains_genres:
                raise ValueError(f"contains_genres must be empty when status={self.status.value}.")
        else:
            if self.primary_genre is None:
                raise ValueError("primary_genre is required when status='usable'.")
            expected_family = GENRE_TO_FAMILY[self.primary_genre]
            if self.specialist_family != expected_family:
                raise ValueError(
                    f"specialist_family ({self.specialist_family}) must equal "
                    f"{expected_family.value} for primary_genre={self.primary_genre.value}."
                )
            if self.media_format is None:
                raise ValueError("media_format is required when status='usable'.")

        if not self.is_packet and self.contains_genres:
            raise ValueError("contains_genres must be empty when is_packet is False.")
        if self.is_packet:
            if not self.contains_genres:
                raise ValueError("contains_genres must be non-empty when is_packet is True.")
            if self.primary_genre not in self.contains_genres:
                raise ValueError("contains_genres must include primary_genre when is_packet is True.")

        if self.title_span is not None:
            if not self.verbatim_title or not self.verbatim_title.strip():
                raise ValueError("verbatim_title must be non-empty when title_span is provided.")
            if _norm_ws(self.title_span.quote) != _norm_ws(self.verbatim_title):
                raise ValueError(
                    f"title_span.quote ({self.title_span.quote!r}) must match "
                    f"verbatim_title ({self.verbatim_title!r})."
                )
        return self


# ---------------------------------------------------------------------------
# Stage 2: 5 Tight Specialist Extraction Models
# ---------------------------------------------------------------------------


class EventLogisticsExtraction(BaseModel):
    """Specialist 1: hearing_or_markup_notice & hearing_memo_or_witness_list."""

    model_config = STRICT_CONFIG

    rationale: str = Field(..., min_length=1, max_length=480)
    event_type: EventType | None = None
    event_title: str | None = None
    event_title_span: SpanRef | None = None
    event_date: str | None = None
    event_date_span: SpanRef | None = None
    event_time: str | None = None
    venue_kind: VenueKind | None = None
    venue: str | None = None
    venue_span: SpanRef | None = None
    witnesses: list[PersonaEntry] = Field(default_factory=list)
    due_date: str | None = None
    bill_refs: list[str] = Field(default_factory=list)

    @field_validator("rationale")
    @classmethod
    def _rationale_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("EventLogisticsExtraction.rationale must not be blank.")
        return value

    @model_validator(mode="after")
    def _check_event_grounding(self) -> EventLogisticsExtraction:
        _require_persona_name_spans(self.witnesses, "witnesses")
        if self.event_title_span is not None:
            if not self.event_title or _norm_ws(self.event_title_span.quote) != _norm_ws(self.event_title):
                raise ValueError("event_title_span must match event_title.")
        if self.event_date_span is not None and not self.event_date:
            raise ValueError("event_date must be populated when event_date_span is provided.")
        if self.venue_span is not None:
            if not self.venue or not _text_matches_span(self.venue, self.venue_span.quote):
                raise ValueError("venue_span must ground venue.")
        return self


class TestimonyBioDisclosureExtraction(BaseModel):
    """Specialist 2: witness_testimony, member_statement, witness_biography & truth_in_testimony."""

    model_config = STRICT_CONFIG

    rationale: str = Field(..., min_length=1, max_length=480)
    personas: list[PersonaEntry] = Field(default_factory=list)
    issuer_org: str | None = None
    issuer_org_span: SpanRef | None = None
    disclosure_has_grants_or_contracts: bool | None = None
    disclosure_amounts: list[str] = Field(default_factory=list)
    disclosure_spans: list[SpanRef] = Field(default_factory=list)
    prior_roles: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    event_title: str | None = None
    event_date: str | None = None
    bill_refs: list[str] = Field(default_factory=list)

    @field_validator("rationale")
    @classmethod
    def _rationale_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("TestimonyBioDisclosureExtraction.rationale must not be blank.")
        return value

    @model_validator(mode="after")
    def _check_testimony_grounding(self) -> TestimonyBioDisclosureExtraction:
        _require_persona_name_spans(self.personas, "personas")
        if self.issuer_org_span is not None:
            if not self.issuer_org or not _text_matches_span(self.issuer_org, self.issuer_org_span.quote):
                raise ValueError("issuer_org_span must ground issuer_org.")
        if self.disclosure_amounts and not self.disclosure_spans:
            raise ValueError("disclosure_spans must be populated whenever disclosure_amounts is non-empty.")
        return self


class TranscriptVoteAttendanceExtraction(BaseModel):
    """Specialist 3: hearing_transcript & committee_vote_or_action."""

    model_config = STRICT_CONFIG

    rationale: str = Field(..., min_length=1, max_length=480)
    event_type: EventType | None = None
    event_title: str | None = None
    event_title_span: SpanRef | None = None
    event_date: str | None = None
    venue: str | None = None
    presiding_or_witnesses: list[PersonaEntry] = Field(default_factory=list)
    members_present: list[str] = Field(default_factory=list)
    members_present_spans: list[SpanRef] = Field(default_factory=list)
    staff_present: list[str] = Field(default_factory=list)
    staff_present_spans: list[SpanRef] = Field(default_factory=list)
    action_summary: str | None = None
    vote_tallies: list[str] = Field(default_factory=list)
    bill_refs: list[str] = Field(default_factory=list)

    @field_validator("rationale")
    @classmethod
    def _rationale_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("TranscriptVoteAttendanceExtraction.rationale must not be blank.")
        return value

    @model_validator(mode="after")
    def _check_transcript_grounding(self) -> TranscriptVoteAttendanceExtraction:
        _require_persona_name_spans(self.presiding_or_witnesses, "presiding_or_witnesses")
        if self.event_title_span is not None:
            if not self.event_title or _norm_ws(self.event_title_span.quote) != _norm_ws(self.event_title):
                raise ValueError("event_title_span must match event_title.")
        if self.members_present and not self.members_present_spans:
            raise ValueError("members_present_spans must be populated when members_present is non-empty.")
        if self.staff_present and not self.staff_present_spans:
            raise ValueError("staff_present_spans must be populated when staff_present is non-empty.")
        return self


class CorrespondenceQfrOversightExtraction(BaseModel):
    """Specialist 4: qfr_correspondence, oversight_or_committee_letter & external_submission_or_comment."""

    model_config = STRICT_CONFIG

    rationale: str = Field(..., min_length=1, max_length=480)
    correspondence_direction: CorrespondenceDirection | None = None
    senders: list[PersonaEntry] = Field(default_factory=list)
    recipients: list[PersonaEntry] = Field(default_factory=list)
    issuer_org: str | None = None
    issuer_org_span: SpanRef | None = None
    signatory_count: int | None = Field(default=None, ge=1)
    due_date: str | None = None
    due_date_span: SpanRef | None = None
    subpoena_or_compelled: bool = False
    bill_refs: list[str] = Field(default_factory=list)

    @field_validator("rationale")
    @classmethod
    def _rationale_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("CorrespondenceQfrOversightExtraction.rationale must not be blank.")
        return value

    @model_validator(mode="after")
    def _check_correspondence_grounding(self) -> CorrespondenceQfrOversightExtraction:
        _require_persona_name_spans(self.senders, "senders")
        _require_persona_name_spans(self.recipients, "recipients")
        if self.issuer_org_span is not None:
            if not self.issuer_org or not _text_matches_span(self.issuer_org, self.issuer_org_span.quote):
                raise ValueError("issuer_org_span must ground issuer_org.")
        if self.due_date_span is not None and not self.due_date:
            raise ValueError("due_date must be populated when due_date_span is provided.")
        return self


class LegislationReportFiscalExtraction(BaseModel):
    """Specialist 5: bill_or_amendment, committee_or_agency_report & budget_or_cost_estimate."""

    model_config = STRICT_CONFIG

    rationale: str = Field(..., min_length=1, max_length=480)
    short_titles: list[str] = Field(default_factory=list)
    short_title_spans: list[SpanRef] = Field(default_factory=list)
    issuer_org: str | None = None
    issuer_org_span: SpanRef | None = None
    sponsors_or_offerors: list[PersonaEntry] = Field(default_factory=list)
    fiscal_years: list[str] = Field(default_factory=list)
    bill_refs: list[str] = Field(default_factory=list)
    statute_or_rule_refs: list[str] = Field(default_factory=list)
    action_summary: str | None = None

    @field_validator("rationale")
    @classmethod
    def _rationale_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LegislationReportFiscalExtraction.rationale must not be blank.")
        return value

    @model_validator(mode="after")
    def _check_legislation_grounding(self) -> LegislationReportFiscalExtraction:
        _require_persona_name_spans(self.sponsors_or_offerors, "sponsors_or_offerors")
        if self.short_titles and not self.short_title_spans:
            raise ValueError("short_title_spans must be populated when short_titles is non-empty.")
        if self.issuer_org_span is not None:
            if not self.issuer_org or not _text_matches_span(self.issuer_org, self.issuer_org_span.quote):
                raise ValueError("issuer_org_span must ground issuer_org.")
        return self


SPECIALIST_MODELS: dict[SpecialistFamily, type[BaseModel]] = {
    SpecialistFamily.event_logistics: EventLogisticsExtraction,
    SpecialistFamily.testimony_bio_disclosure: TestimonyBioDisclosureExtraction,
    SpecialistFamily.transcript_vote_attendance: TranscriptVoteAttendanceExtraction,
    SpecialistFamily.correspondence_qfr_oversight: CorrespondenceQfrOversightExtraction,
    SpecialistFamily.legislation_report_fiscal: LegislationReportFiscalExtraction,
}


# ---------------------------------------------------------------------------
# Strict JSON Schema Helpers (Claude --json-schema & Codex --output-schema)
# ---------------------------------------------------------------------------


_OPENAI_UNSUPPORTED_KEYWORDS = frozenset(
    {
        "default",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
        "uniqueItems",
    }
)


def _enforce_strict_node(node: Any, *, openai_strict: bool) -> Any:
    if isinstance(node, list):
        return [_enforce_strict_node(item, openai_strict=openai_strict) for item in node]
    if not isinstance(node, dict):
        return node

    out: dict[str, Any] = {}
    for key, val in node.items():
        if openai_strict and key in _OPENAI_UNSUPPORTED_KEYWORDS:
            continue
        out[key] = _enforce_strict_node(val, openai_strict=openai_strict)

    if openai_strict and "$ref" in out:
        # OpenAI strict mode forbids sibling keywords alongside $ref.
        return {"$ref": out["$ref"]}

    is_object_node = out.get("type") == "object" or "properties" in out
    if is_object_node:
        out["additionalProperties"] = False
        if openai_strict and isinstance(out.get("properties"), dict):
            out["required"] = list(out["properties"].keys())

    return out


def strict_json_schema(model_cls: type[BaseModel], *, openai_strict: bool = False) -> dict[str, Any]:
    """Build a strict JSON Schema dict compatible with Claude CLI and Codex CLI.

    - Always sets ``additionalProperties: false`` recursively on all objects and ``$defs``.
    - When ``openai_strict=True``, adds every property key to ``required`` on all object nodes,
      strips OpenAI-unsupported validation keywords (``default``, ``minLength``, ``maxLength``,
      ``minimum``, ``maximum``, ``exclusiveMinimum``, ``pattern``, etc.), and removes sibling
      keywords on ``$ref`` nodes as required by OpenAI/Codex strict structured outputs.
    """
    raw = deepcopy(model_cls.model_json_schema())
    strict = _enforce_strict_node(raw, openai_strict=openai_strict)
    if "$defs" in strict and isinstance(strict["$defs"], dict):
        strict["$defs"] = {
            name: _enforce_strict_node(defn, openai_strict=openai_strict)
            for name, defn in strict["$defs"].items()
        }
    return strict


# ---------------------------------------------------------------------------
# Deterministic Text-Slice Span Grounding Helpers
# ---------------------------------------------------------------------------


def verify_span_in_text(span: SpanRef, text: str, *, normalize_ws: bool = False) -> bool:
    """Verify that span offsets point to span.quote inside text."""
    if span.start < 0 or span.end > len(text) or span.end <= span.start:
        return False
    sliced = text[span.start : span.end]
    if normalize_ws:
        return _norm_ws(sliced) == _norm_ws(span.quote)
    return sliced == span.quote


def _iter_span_refs(value: Any, path: str = "") -> list[tuple[str, SpanRef]]:
    found: list[tuple[str, SpanRef]] = []
    if isinstance(value, SpanRef):
        found.append((path, value))
    elif isinstance(value, BaseModel):
        for field_name in value.__class__.model_fields:
            child = getattr(value, field_name)
            child_path = f"{path}.{field_name}" if path else field_name
            found.extend(_iter_span_refs(child, child_path))
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            found.extend(_iter_span_refs(item, f"{path}[{idx}]"))
    return found


def verify_grounded_extraction(
    core: CoreEnvelopeExtraction,
    specialist: BaseModel | None,
    text: str,
    *,
    normalize_ws: bool = False,
) -> list[str]:
    """Verify all SpanRefs and grounding invariants against source text.

    Returns an empty list when all checks pass, or a list of human-readable failure messages.
    """
    errors: list[str] = []

    if core.status != DocStatus.usable and specialist is not None:
        errors.append(f"Non-usable status {core.status.value!r} must not have a specialist extraction.")

    if core.status == DocStatus.usable:
        if core.doc_date is not None and not core.date_spans:
            errors.append("CoreEnvelopeExtraction.date_spans must be non-empty when doc_date is set on usable docs.")
        if specialist is not None and core.specialist_family is not None:
            expected_cls = SPECIALIST_MODELS[core.specialist_family]
            if not isinstance(specialist, expected_cls):
                errors.append(
                    f"Specialist model {type(specialist).__name__} does not match "
                    f"expected {expected_cls.__name__} for family {core.specialist_family.value!r}."
                )

    for path, span in _iter_span_refs(core, "core"):
        if not verify_span_in_text(span, text, normalize_ws=normalize_ws):
            errors.append(f"Ungrounded span at {path}: [{span.start}:{span.end}] != {span.quote!r}.")

    if specialist is not None:
        for path, span in _iter_span_refs(specialist, "specialist"):
            if not verify_span_in_text(span, text, normalize_ws=normalize_ws):
                errors.append(f"Ungrounded span at {path}: [{span.start}:{span.end}] != {span.quote!r}.")

    return errors


__all__ = [
    "Chamber",
    "CoreEnvelopeExtraction",
    "CorrespondenceDirection",
    "DocStatus",
    "EntityType",
    "EventLogisticsExtraction",
    "EventType",
    "ExpressionRecord",
    "FAMILY_TO_GENRES",
    "ForeseenActivity",
    "GENRE_TO_FAMILY",
    "LegislationReportFiscalExtraction",
    "ManifestationRecord",
    "MediaFormat",
    "PersonaEntry",
    "PersonaRole",
    "PrimaryGenre",
    "RealizedActivity",
    "SPECIALIST_MODELS",
    "SpanRef",
    "SpecialistFamily",
    "SubmissionRecord",
    "TestimonyBioDisclosureExtraction",
    "TranscriptVoteAttendanceExtraction",
    "VenueKind",
    "WorkRecord",
    "strict_json_schema",
    "verify_grounded_extraction",
    "verify_span_in_text",
]
