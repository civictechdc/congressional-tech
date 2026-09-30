"""Decode upstream Congress.gov bodies independently of storage and normalization."""

from .models.congress import CommitteeMeeting, CommitteeResponse, CommitteesPage, MeetingResponse, MeetingsPage, parse_response
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


# Only known meeting list containers and integer fields are interpreted. Every
# original value, attribute and unknown node remains in _source_xml.
_MEETING_LISTS = {
    ('committees',): 'item', ('witnesses',): 'item', ('videos',): 'item',
    ('meetingDocuments',): 'item', ('witnessDocuments',): 'item',
    ('continuations',): 'item', ('hearingTranscript',): 'item',
    ('relatedItems', 'bills'): 'bill', ('relatedItems', 'treaties'): 'item',
    ('relatedItems', 'nominations'): 'item',
}
_MEETING_INTEGERS = {
    ('congress',), ('hearingTranscript', '*', 'jacketNumber'),
    ('relatedItems', 'bills', '*', 'congress'),
    ('relatedItems', 'treaties', '*', 'congress'), ('relatedItems', 'treaties', '*', 'number'),
    ('relatedItems', 'nominations', '*', 'congress'), ('relatedItems', 'nominations', '*', 'number'),
}


def meeting_from_xml(source: CongressXmlDocument) -> CommitteeMeeting:
    """Interpret a retained XML meeting for existing readers without losing bytes.

    This is not a JSON response: _source_xml marks the interpretation and retains
    its evidence. Unknown values stay literal. Malformed known structures fail
    instead of silently dropping children or flattening repeated scalar fields.
    """
    meetings = source.xml.findall('committeeMeeting')
    if len(meetings) != 1:
        raise ValueError('Congress.gov XML must contain exactly one committeeMeeting')

    def value(node, path=()):
        if path in _MEETING_LISTS:
            if node.text.strip() or any(child.tag != _MEETING_LISTS[path] or child.tail.strip() for child in node.children):
                raise ValueError(f'Unexpected XML list structure at {path}')
            return [value(child, (*path, '*')) for child in node.children]
        if path in {('location',), ('relatedItems',)} and not node.children and not node.text.strip():
            return {}
        if node.children:
            result = {}
            for child in node.children:
                if child.tag in result:
                    raise ValueError(f'Repeated XML field at {(*path, child.tag)}')
                result[child.tag] = value(child, (*path, child.tag))
            return result
        if path in _MEETING_INTEGERS:
            text = node.text.strip()
            if not text.isascii() or not text.isdecimal():
                raise ValueError(f'Invalid XML integer at {path}')
            return int(text)
        return node.text

    fields = value(meetings[0])
    fields['_source_xml'] = source.content.source_dict()
    return CommitteeMeeting.model_validate(fields)
