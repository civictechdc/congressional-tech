"""Decode upstream Congress.gov bodies independently of storage and normalization."""

from .models.congress import CommitteeResponse, CommitteesPage, MeetingResponse, MeetingsPage, parse_response
from .models.congress_xml import CongressXmlDocument
from .models.content import RawContent
from .models.xml import parse_xml_element

CongressResponse = MeetingsPage | MeetingResponse | CommitteesPage | CommitteeResponse | CongressXmlDocument


def parse_congress_xml(data: bytes | str) -> CongressXmlDocument:
    content = data if isinstance(data, bytes) else data.encode("utf-8")
    root = parse_xml_element(content)
    if root.tag != "api-root":
        raise ValueError("Congress.gov XML requires an api-root element")
    return CongressXmlDocument(xml=root, content=RawContent.from_bytes(content, "application/xml"))
