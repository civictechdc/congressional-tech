"""House raw XML parsing, independent of saved-state and output formats."""
from typing import cast
from xml.etree.ElementTree import Element

from congress_api.models.content import RawContent
from congress_api.models.house import HouseMeetingXML, HouseWitnessListXML, XML_MODELS
from congress_api.models.xml import xml_element


def parse_house_meeting(root: bytes | str | Element | HouseMeetingXML) -> HouseMeetingXML:
    if isinstance(root, HouseMeetingXML):
        return root
    raw = root if isinstance(root, bytes) else root.encode('utf-8') if isinstance(root, str) else None
    if raw is not None:
        from congress_api.xml import parse_xml
        root = parse_xml(raw)
    if root.tag != 'committee-meeting':
        raise ValueError('Expected a House committee-meeting XML document')
    result = cast(HouseMeetingXML, xml_element(root, XML_MODELS))
    if raw is not None:
        result.raw_content = RawContent.from_bytes(raw, 'application/xml')
    return result


def parse_house_witnesses(root: bytes | str | Element | HouseWitnessListXML) -> HouseWitnessListXML:
    if isinstance(root, HouseWitnessListXML):
        return root
    raw = root if isinstance(root, bytes) else root.encode('utf-8') if isinstance(root, str) else None
    if raw is not None:
        from congress_api.xml import parse_xml
        root = parse_xml(raw)
    if root.tag != 'witness-list':
        raise ValueError('Expected a House witness-list XML document')
    result = cast(HouseWitnessListXML, xml_element(root, XML_MODELS))
    if raw is not None:
        result.raw_content = RawContent.from_bytes(raw, 'application/xml')
    return result
