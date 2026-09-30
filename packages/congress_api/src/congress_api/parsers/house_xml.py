"""House raw XML parsing, independent of saved-state and output formats."""

from typing import cast
from xml.etree.ElementTree import Element

from congress_api.models.content import RawContent
from congress_api.models.house import XML_MODELS, HouseMeetingXML, HouseWitnessListXML
from congress_api.parsers.xml import parse_xml, xml_element


def _parse_house_xml[T: HouseMeetingXML | HouseWitnessListXML](
    root: bytes | str | Element | T, model: type[T], tag: str,
) -> T:
    if isinstance(root, model):
        return root
    raw = root if isinstance(root, bytes) else root.encode('utf-8') if isinstance(root, str) else None
    if raw is not None:
        root = parse_xml(raw)
    if root.tag != tag:
        raise ValueError(f'Expected a House {tag} XML document')
    result = cast(T, xml_element(root, XML_MODELS))
    if raw is not None:
        result.raw_content = RawContent.from_bytes(raw, 'application/xml')
    return result


def parse_house_meeting(root: bytes | str | Element | HouseMeetingXML) -> HouseMeetingXML:
    return _parse_house_xml(root, HouseMeetingXML, 'committee-meeting')


def parse_house_witnesses(root: bytes | str | Element | HouseWitnessListXML) -> HouseWitnessListXML:
    return _parse_house_xml(root, HouseWitnessListXML, 'witness-list')
