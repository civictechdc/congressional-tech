"""Parse source XML, including the UTF-8 BOM docs.house.gov sometimes prefixes."""

import xml.etree.ElementTree as ET
from collections.abc import Mapping
from xml.etree.ElementTree import Element

from congress_api.models.xml import XmlElement

MODS_NS = {"m": "http://www.loc.gov/mods/v3"}


def parse_xml(data):
    return ET.fromstring(data.removeprefix(b"\xef\xbb\xbf") if isinstance(data, bytes) else data.removeprefix("\ufeff"))


def mods_elements(root, tag):
    ## Related-item granules repeat hearing metadata; only the root's extensions count.
    return root.findall(f"m:extension/m:{tag}", MODS_NS)


def xml_element(element: Element, models: Mapping[str, type[XmlElement]] | None = None) -> XmlElement:
    model = (models or {}).get(element.tag, XmlElement)
    return model(tag=element.tag, attributes=element.attrib, text=element.text or '', tail=element.tail or '',
                 children=[xml_element(child, models) for child in element])


def parse_xml_element(data: bytes | str) -> XmlElement:
    return xml_element(parse_xml(data))

