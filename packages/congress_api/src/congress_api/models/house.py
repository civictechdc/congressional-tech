"""House XML nodes and the retained XML/HTML parser output.

Publisher codes, dates and malformed URLs remain literal strings. Concrete
attribute/field models describe known data; ordered XML children preserve all
repeated and unknown elements. Original bytes live in ``source_bodies``.
"""
from typing import Annotated, Literal, cast

from pydantic import Field, field_validator

from .base import SourceModel
from .content import RawContent
from .xml import XmlAttributes, XmlElement


class HouseDatedAttributes(XmlAttributes):
    add_date: str = Field(default='', alias='add-date')
    publish_date: str = Field(default='', alias='publish-date')
    remove_date: str = Field(default='', alias='remove-date')
    user: str = ''


class HouseMeetingAttributes(XmlAttributes):
    congress_num: str = Field(default='', alias='congress-num')
    session_num: str = Field(default='', alias='session-num')
    meeting_id: str = Field(default='', alias='meeting-id')
    meeting_type: str = Field(default='', alias='meeting-type')
    create_date: str = Field(default='', alias='create-date')
    orig_publish_date: str = Field(default='', alias='orig-publish-date')
    update_date: str = Field(default='', alias='update-date')
    floor_creator: str = Field(default='', alias='floor-creator')


class HouseFileAttributes(HouseDatedAttributes):
    doc_url: str = Field(default='', alias='doc-url')
    doc_type: str = Field(default='', alias='doc-type')


class HouseDocumentAttributes(HouseDatedAttributes):
    type: str = ''


class HouseWitnessAttributes(HouseDatedAttributes):
    display_order: str = Field(default='', alias='display-order')
    witness_type: str = Field(default='', alias='witness-type')
    testified: str = ''


class HousePanelAttributes(HouseDatedAttributes):
    sort_order: str = Field(default='', alias='sort-order')


class HouseWitnessListAttributes(XmlAttributes):
    meeting_id: str = Field(default='', alias='meeting-id')
    create_date: str = Field(default='', alias='create-date')


class HouseCommitteeAttributes(XmlAttributes):
    id: str = ''
    parent_id: str = Field(default='', alias='parent-id')
    parent_name: str = Field(default='', alias='parent-name')


class HouseDateAttributes(XmlAttributes):
    date: str = ''
    publish_date: str = Field(default='', alias='publish-date')
    user: str = ''


class HouseStateAttributes(XmlAttributes):
    postal_code: str = Field(default='', alias='postal-code')


class HouseExplanatoryAttributes(XmlAttributes):
    doc_modified: str = Field(default='', alias='doc-modified')


class HouseMeetingDateFields(SourceModel):
    calendar_date: str = Field(default='', alias='calendar-date')
    start_time: str = Field(default='', alias='start-time')
    end_time: str = Field(default='', alias='end-time')


class HouseCapitolLocationFields(SourceModel):
    room: str = ''
    building: str = ''
    zip_suffix: str = Field(default='', alias='zip-suffix')


class HouseFilenameFields(SourceModel):
    amdt_num: str = Field(default='', alias='amdt-num')
    amdt_type: str = Field(default='', alias='amdt-type')
    bioguide_id: str = Field(default='', alias='bioguideID')
    considered: str = ''
    description: str = ''
    doc_type: str = Field(default='', alias='doc-type')
    enbloc_num: str = Field(default='', alias='enbloc-num')
    legis_num: str = Field(default='', alias='legis-num')
    legis_stage: str = Field(default='', alias='legis-stage')
    part_num: str = Field(default='', alias='part-num')
    short_desc: str = Field(default='', alias='short-desc')
    time_frame: str = Field(default='', alias='timeFrame')
    type: str = ''
    update_num: str = Field(default='', alias='update-num')
    version_num: str = Field(default='', alias='version-num')
    vote_num: str = Field(default='', alias='vote-num')


class HouseWitnessFields(SourceModel):
    honorific: str = ''
    firstname: str = ''
    middlename: str = ''
    lastname: str = ''
    suffix: str = ''
    retired: str = ''
    position: str = ''
    organization: str = ''
    location: str = ''
    behalf_of: str = Field(default='', alias='behalf-of')
    witness_type: str = Field(default='', alias='witness-type')
    testified: str = ''
    bioguide_id: str = Field(default='', alias='bioguideID')


class HouseXMLNode(XmlElement):
    @field_validator('children', mode='before')
    @classmethod
    def restore_typed_children(cls, children):
        return [XML_MODELS.get(child.get('tag'), HouseXMLNode).model_validate(child) if isinstance(child, dict) else child
                for child in children]


def text_fields(node: XmlElement, model: type[SourceModel]) -> SourceModel:
    """First scalar reading for consumers; repeated originals stay in children."""
    fields = {}
    for name, field in model.model_fields.items():
        key = field.alias or name
        if (child := node.find(key)) is not None:
            fields[key] = child.text
    return model.model_validate(fields)


class HouseFileXML(HouseXMLNode):
    tag: Literal['file']
    attributes: HouseFileAttributes


class HouseDocumentXML(HouseXMLNode):
    tag: Literal['meeting-document', 'witness-document']
    attributes: HouseDocumentAttributes

    @property
    def files(self) -> list[HouseFileXML]:
        return cast(list[HouseFileXML], self.findall('files/file'))

    @property
    def filename_fields(self) -> HouseFilenameFields:
        node = self.find('filename-metadata')
        return cast(HouseFilenameFields, text_fields(node, HouseFilenameFields)) if node is not None else HouseFilenameFields()


class HouseWitnessXML(HouseXMLNode):
    tag: Literal['witness']
    attributes: HouseWitnessAttributes

    @property
    def fields(self) -> HouseWitnessFields:
        return cast(HouseWitnessFields, text_fields(self, HouseWitnessFields))

    @property
    def documents(self) -> list[HouseDocumentXML]:
        return cast(list[HouseDocumentXML], self.findall('witness-documents/witness-document'))


class HousePanelXML(HouseXMLNode):
    tag: Literal['panel']
    attributes: HousePanelAttributes

    @property
    def witnesses(self) -> list[HouseWitnessXML]:
        return cast(list[HouseWitnessXML], self.findall('witness'))


class HouseCommitteeXML(HouseXMLNode):
    tag: Literal['committee-name']
    attributes: HouseCommitteeAttributes


class HouseDateXML(HouseXMLNode):
    tag: Literal['publish-date', 'update-date']
    attributes: HouseDateAttributes


class HouseStateXML(HouseXMLNode):
    tag: Literal['state']
    attributes: HouseStateAttributes

    @property
    def fullname(self) -> str:
        return self.findtext('state-fullname', '')


class HouseFieldLocationFields(SourceModel):
    building_name: str = Field(default='', alias='building-name')
    street_address: str = Field(default='', alias='street-address')
    city: str = ''
    state: HouseStateXML | None = None
    zip: str = ''


class HouseExplanatoryXML(HouseXMLNode):
    tag: Literal['explanatory-notes']
    attributes: HouseExplanatoryAttributes


class HouseMeetingDetailsXML(HouseXMLNode):
    tag: Literal['meeting-details']

    @property
    def title(self) -> str:
        return self.findtext('meeting-title', '')

    @property
    def date(self) -> HouseMeetingDateFields | None:
        node = self.find('meeting-date')
        return cast(HouseMeetingDateFields, text_fields(node, HouseMeetingDateFields)) if node is not None else None

    @property
    def committees(self) -> list[HouseCommitteeXML]:
        return cast(list[HouseCommitteeXML], self.findall('committees/committee-name'))

    @property
    def subcommittees(self) -> list[HouseCommitteeXML]:
        return cast(list[HouseCommitteeXML], self.findall('subcommittees/committee-name'))

    @property
    def capitol_location(self) -> HouseCapitolLocationFields | None:
        node = self.find('meeting-location/capitol-complex')
        return cast(HouseCapitolLocationFields, text_fields(node, HouseCapitolLocationFields)) if node is not None else None

    @property
    def field_location(self) -> HouseFieldLocationFields | None:
        node = self.find('meeting-location/field')
        if node is None:
            return None
        fields = {}
        for name, field in HouseFieldLocationFields.model_fields.items():
            key = field.alias or name
            if (child := node.find(key)) is not None:
                fields[key] = child if name == 'state' else child.text
        return HouseFieldLocationFields.model_validate(fields)


class HouseMeetingXML(HouseXMLNode):
    tag: Literal['committee-meeting']
    attributes: HouseMeetingAttributes
    raw_content: RawContent | None = None

    @property
    def details(self) -> HouseMeetingDetailsXML | None:
        return cast(HouseMeetingDetailsXML | None, self.find('meeting-details'))

    @property
    def documents(self) -> list[HouseDocumentXML]:
        return cast(list[HouseDocumentXML], self.findall('meeting-documents/meeting-document'))


class HouseWitnessListXML(HouseXMLNode):
    tag: Literal['witness-list']
    attributes: HouseWitnessListAttributes
    raw_content: RawContent | None = None

    @property
    def panels(self) -> list[HousePanelXML]:
        return cast(list[HousePanelXML], self.findall('panel'))


XML_MODELS = {'committee-meeting': HouseMeetingXML, 'witness-list': HouseWitnessListXML,
              'meeting-document': HouseDocumentXML, 'witness-document': HouseDocumentXML,
              'file': HouseFileXML, 'witness': HouseWitnessXML, 'panel': HousePanelXML,
              'committee-name': HouseCommitteeXML, 'meeting-details': HouseMeetingDetailsXML,
              'publish-date': HouseDateXML, 'update-date': HouseDateXML,
              'state': HouseStateXML, 'explanatory-notes': HouseExplanatoryXML}




class HtmlMetadata(SourceModel):
    attributes: dict[str, str]


class HouseFileObservation(SourceModel):
    url: str
    format: str
    active: bool
    selector: str | None = None
    metadata: XmlElement | HtmlMetadata


class HouseDocumentGroup(SourceModel):
    source: Literal['meeting_xml', 'witness_xml', 'html']
    selector: str
    source_order: int
    active: bool
    description: str
    type: str | None = None
    legacy_kind: str | None = None
    owning_witness_selector: str | None = None
    metadata: XmlElement | HtmlMetadata
    files: list[HouseFileObservation]


class HousePanelObservation(SourceModel):
    selector: str
    source_order: int
    sort_order: str
    active: bool
    metadata: XmlElement


class HouseWitnessObservation(SourceModel):
    name: str
    active: bool
    source_order: int
    selector: str | None = None
    panel_selector: str | None = None
    display_order: str | None = None
    metadata: XmlElement | None = None
    source: Literal['html'] | None = None
    position: str | None = None
    organization: str | None = None
    panel: str | None = None


class HouseEvidence(SourceModel):
    schema_version: str
    meeting_metadata: HouseMeetingXML | None
    witness_list_metadata: HouseWitnessListXML | None
    document_groups: list[HouseDocumentGroup]
    panels: list[HousePanelObservation]
    witness_observations: list[HouseWitnessObservation]
    html: str | None = None
    limitations: list[str]


class HouseWitnessRow(SourceModel):
    name: str
    position: str = ''
    organization: str = ''
    panel: str = ''
    honorific: str = ''
    first: str = ''
    middle: str = ''
    last: str = ''
    suffix: str = ''
    retired: str = ''
    location: str = ''
    behalf_of: str = ''
    witness_type: str = ''
    testified: str = ''
    bioguide_id: str = ''


class HouseActionRow(SourceModel):
    kind: Literal['amendment', 'vote']
    bill: str
    number: str
    sponsor_bioguide: str
    amendment_type: str
    enbloc: str
    description: str
    url: str


class HouseParsedRecord(SourceModel):
    documents: list[Annotated[tuple[str, str, str, list[str]], Field(strict=False)]]
    witnesses: list[HouseWitnessRow]
    amendments: list[HouseActionRow]
    xml_update: str
    status: Literal['xml', 'page', 'absent']
    witness_status: Literal['present', 'absent', 'unfetched']
    evidence: HouseEvidence
    source_bodies: dict[str, RawContent] = Field(default_factory=dict)
