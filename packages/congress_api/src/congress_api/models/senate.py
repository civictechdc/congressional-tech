"""Senate committee HTML extractions and native WordPress hearing records.

Strings retain publisher spelling, URLs and dates. HTML attributes are named by
publishers and remain string maps; the surrounding records have explicit shapes.
"""
from datetime import date
from typing import Annotated

from pydantic import BeforeValidator, Field, JsonValue, TypeAdapter

from .base import SourceModel
from .content import RawContent


def _source_tuple(value):
    # JSON stores the existing positional source rows as arrays.
    return tuple(value) if isinstance(value, list) else value


DocumentRow = Annotated[tuple[str, str, str], BeforeValidator(_source_tuple)]  # kind, label, URL
ListingValue = Annotated[tuple[str, str], BeforeValidator(_source_tuple)]  # date, title


class SenateWitness(SourceModel):
    name: str
    position: str = ""
    organization: str = ""
    page: str = ""


class WitnessField(SourceModel):
    class_name: str = Field(alias="class")
    text: str


class WitnessCard(SourceModel):
    layout: str
    name: str
    text: str
    attributes: dict[str, str]
    fields: list[WitnessField]
    location: str | None = None
    panel: str | None = None


class DocumentMetadata(SourceModel):
    labels: list[str]
    attributes: list[dict[str, str]]
    container_attributes: list[dict[str, str]]
    witness_indexes: list[Annotated[int, Field(ge=0)]]


class EmbeddedMedia(SourceModel):
    tag: str
    attributes: dict[str, str]


class SourceLink(SourceModel):
    text: str
    attributes: dict[str, str]


class InlineScript(SourceModel):
    attributes: dict[str, str]
    text: str


class PageText(SourceModel):
    text: str
    attributes: dict[str, str]


class PageMetadata(SourceModel):
    text: str = ""
    media: list[EmbeddedMedia] = Field(default_factory=list)
    video_messages: list[PageText] = Field(default_factory=list)
    heading_prefixes: list[PageText] = Field(default_factory=list)
    meta: list[dict[str, str]] = Field(default_factory=list)
    structured_data: list[str] = Field(default_factory=list)
    links: list[SourceLink] = Field(default_factory=list)
    media_scripts: list[InlineScript] = Field(default_factory=list)


class SenateEvent(SourceModel):
    title: str
    date: str
    date_text: str
    type: str
    url: str


class AttachmentFile(SourceModel):
    kind: str
    label: str
    url: str


class RequestReceipt(SourceModel):
    url: str
    started_at: str
    completed_at: str | None = None
    status_code: int | None = None
    outcome: str | None = None
    error: str | None = None
    detected_format: str | None = None
    content_type: str | None = None
    raw_body: RawContent | None = None


class SenateCheck(SourceModel):
    mode: str
    started_at: str | None = None
    completed_at: str | None = None
    outcome: str | None = None
    receipts: list[RequestReceipt] = Field(default_factory=list)
    error: str | None = None


class CacheReplay(SourceModel):
    cache_file: str
    raw_sha256: str
    parsed_at: str
    parser_version: int
    acquisition_time: str | None = None
    basis: str
    media_scripts_parsed_at: str | None = None


class MatchDetail(SourceModel):
    method: str
    evidence: list[str] | None = None
    identifiers: list[str] | None = None
    committee_codes: list[str] | None = None
    event_date: str | None = None
    native_api_url: str | None = None
    native_bill_ids: list[ListingValue] | None = None
    native_event_id: str | None = None
    native_title: str | None = None
    page_bill_ids: list[ListingValue] | None = None
    reason: str | None = None
    shared_transcript_packages: list[str] | None = None
    version: str | None = None


class SenatePage(SourceModel):
    title: str
    lines: list[str]
    witnesses: list[SenateWitness]
    documents: list[DocumentRow]
    raw_html: RawContent | None = None
    document_labels: dict[str, str] = Field(default_factory=dict)
    document_metadata: dict[str, DocumentMetadata] = Field(default_factory=dict)
    witness_metadata: dict[str, WitnessCard] = Field(default_factory=dict)
    page_metadata: PageMetadata | None = None
    event: SenateEvent | None = None
    attachments: dict[str, list[AttachmentFile]] = Field(default_factory=dict)
    attachment_sources: dict[str, RawContent] = Field(default_factory=dict)
    absent: bool = False
    status: str | None = None
    checked: str | None = None
    version: str = ""
    parser_version: int | None = None
    events: list[str] = Field(default_factory=list)
    candidate_events: list[str] = Field(default_factory=list)
    match_details: dict[str, MatchDetail] = Field(default_factory=dict)
    retrieved_at: str | None = None
    imported_at: str | None = None
    last_check: SenateCheck | None = None
    observation_check: SenateCheck | None = None
    cache_replay: CacheReplay | None = None


class ListingRow(SourceModel):
    day: date
    url: str
    title: str


class CollectionScope(SourceModel):
    since: str
    through: str
    basis: str


class SenateSite(SourceModel):
    pages: dict[str, SenatePage] = Field(default_factory=dict)
    listings: dict[str, ListingValue] = Field(default_factory=dict)
    versions: dict[str, str] = Field(default_factory=dict)
    source_bodies: dict[str, RawContent] = Field(default_factory=dict)
    wordpress: bool | None = None
    form: str | None = None
    from_0: bool | None = None
    checked: str | None = None
    imported_at: str | None = None
    status: str | None = None
    collection_scope: CollectionScope | None = None
    last_check: SenateCheck | None = None
    last_attempt: SenateCheck | None = None


class WordPressLink(SourceModel):
    href: str
    name: str | None = None
    templated: bool | None = None


class WordPressSchemaNode(SourceModel):
    type: str | None = Field(default=None, alias="@type")
    id: str | None = Field(default=None, alias="@id")
    url: str | None = None
    name: str | None = None
    is_part_of: "WordPressSchemaNode | None" = Field(default=None, alias="isPartOf")
    breadcrumb: "WordPressSchemaNode | None" = None
    in_language: str | None = Field(default=None, alias="inLanguage")
    items: list["WordPressSchemaNode"] | None = Field(default=None, alias="itemListElement")
    position: int | None = None
    item: str | None = None
    description: str | None = None
    publisher: "WordPressSchemaNode | None" = None
    alternate_name: str | None = Field(default=None, alias="alternateName")
    actions: list["WordPressSchemaNode"] | None = Field(default=None, alias="potentialAction")
    target: "WordPressSchemaNode | None" = None
    url_template: str | None = Field(default=None, alias="urlTemplate")
    query_input: "WordPressSchemaNode | None" = Field(default=None, alias="query-input")
    value_required: bool | None = Field(default=None, alias="valueRequired")
    value_name: str | None = Field(default=None, alias="valueName")
    logo: "WordPressSchemaNode | None" = None
    image: "WordPressSchemaNode | None" = None
    content_url: str | None = Field(default=None, alias="contentUrl")
    width: int | None = None
    height: int | None = None
    caption: str | None = None
    same_as: list[str] | None = Field(default=None, alias="sameAs")


class WordPressSchema(SourceModel):
    context: str = Field(alias="@context")
    graph: list[WordPressSchemaNode] = Field(alias="@graph")


class WordPressRobots(SourceModel):
    index: str
    follow: str
    max_snippet: str | None = Field(default=None, alias="max-snippet")
    max_image_preview: str | None = Field(default=None, alias="max-image-preview")
    max_video_preview: str | None = Field(default=None, alias="max-video-preview")


class WordPressImage(SourceModel):
    width: int
    height: int
    url: str
    type: str


class WordPressSEO(SourceModel):
    title: str
    robots: WordPressRobots
    og_locale: str
    og_type: str
    og_title: str
    og_url: str
    og_site_name: str
    og_image: list[WordPressImage] | None = None
    twitter_card: str
    twitter_site: str
    canonical: str | None = None
    schema_data: WordPressSchema = Field(alias="schema")


class WordPressType(SourceModel):
    rest_base: str = ""
    description: str | None = None
    hierarchical: bool | None = None
    has_archive: bool | str | None = None
    name: str | None = None
    slug: str | None = None
    icon: str | None = None
    taxonomies: list[str] | None = None
    rest_namespace: str | None = None
    template: list[JsonValue] | None = None
    template_lock: bool | str | None = None
    yoast_head: str | None = None
    yoast_head_json: WordPressSEO | None = None
    links: dict[str, list[WordPressLink]] = Field(default_factory=dict, alias="_links")


class WordPressTitle(SourceModel):
    rendered: str
    raw: str | None = None


class WordPressWitness(SourceModel):
    witness_name: str = ""
    witness_title: str = ""
    witness_agency: str = ""
    witness_location: str | None = None
    witness_note: str | None = None
    testimony: str = ""
    testimony_2: str = ""
    testimony_3: str = ""
    testimony_4: str = ""
    testimony_file: str | int = ""
    testimony_file_2: str | int = ""
    testimony_file_3: str | int = ""
    testimony_file_4: str | int = ""


class WordPressMemberStatement(SourceModel):
    member_name: str = ""
    member_first_name: str = ""
    member_last_name: str = ""
    member_title: str = ""
    member_party: str = ""
    member_state: str = ""
    member_statement: str | int = ""
    member_statement_2: str = ""
    member_file_path: str = ""
    testimony: str = ""
    testimony_2: str = ""


class WordPressFile(SourceModel):
    file_link: str | int


class WordPressRelatedLinkValue(SourceModel):
    title: str
    url: str
    target: str


class WordPressRelatedLink(SourceModel):
    link: WordPressRelatedLinkValue


class WordPressHearingFields(SourceModel):
    status: str | None = None
    committee_type: str | list[str] | None = None
    committee: str | bool | None = None
    hearing_date_time: str | None = None
    hearing_date_override: bool | None = None
    hearing_date_override_text: str | None = None
    hearing_end_date_time: str | None = None
    hearing_location: str | None = None
    hearing_room: str | None = None
    hearing_agenda: str | None = None
    hearing_transcript: str | int | None = None
    hearing_transcript_import: str | None = None
    live_start: str | None = None
    live_end: str | None = None
    archive_stream_name: str | None = None
    archive_offset: str | None = None
    archive_stt: str | None = None
    import_id: str | None = None
    local_time: str | None = None
    related_files: str | None = None
    related_files_list: list[WordPressFile] | None = None
    related_files_list_embargoed: list[WordPressFile] | None = None
    related_links: list[WordPressRelatedLink] | None = None
    member_statements: list[WordPressMemberStatement] | None = None
    witness_1: list[WordPressWitness] | None = None
    witness_2: list[WordPressWitness] | None = None
    witness_3: list[WordPressWitness] | None = None
    witness_4: list[WordPressWitness] | None = None
    panel_1_legacy_data: str | None = None
    panel_2_legacy_data: str | None = None
    panel_3_legacy_data: str | None = None
    panel_4_legacy_data: str | None = None
    show_files: bool | None = None
    show_links: bool | None = None
    show_local_time: bool | None = None
    show_member_list: bool | None = None
    show_witness_list: bool | None = None
    show_panel_1: bool | None = None
    show_panel_2: bool | None = None
    show_panel_3: bool | None = None
    show_panel_4: bool | None = None
    show_panel_labels: bool | None = None


class WordPressPost(SourceModel):
    link: str
    title: WordPressTitle
    date: str | None = None
    acf: WordPressHearingFields | Annotated[list[JsonValue], Field(max_length=0)] | None = None


WORDPRESS_TYPES = TypeAdapter(dict[str, WordPressType])
WORDPRESS_POSTS = TypeAdapter(list[WordPressPost])
SENATE_SITES = TypeAdapter(dict[str, SenateSite])
