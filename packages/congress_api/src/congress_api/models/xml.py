"""Ordered XML element structure shared by source-specific models.

Expanded namespace names, attributes, repeated children, order, text and tails
survive parsing. Source families supply concrete node/attribute models; unknown
publisher elements remain XML nodes, not untyped dictionaries. Source owners
retain RawContent separately for lexical details such as comments and prefixes.
"""
from collections.abc import Iterator, Mapping
import re
from xml.etree.ElementTree import Element

from pydantic import Field, SerializeAsAny

from .base import SourceModel


class XmlAttributes(SourceModel):
    __pydantic_extra__: dict[str, str] = Field(init=False)


class XmlElement(SourceModel):
    tag: str
    attributes: SerializeAsAny[XmlAttributes] = Field(default_factory=XmlAttributes)
    text: str = ""
    tail: str = ""
    children: list[SerializeAsAny['XmlElement']] = Field(default_factory=list)

    @property
    def attrib(self) -> dict[str, str]:
        return self.attributes.source_dict()

    def get(self, key: str, default=None):
        return self.attrib.get(key, default)

    def findall(self, path: str) -> list['XmlElement']:
        """Direct child paths, using expanded names when namespaces are present."""
        nodes = [self]
        for tag in re.findall(r'(?:\{[^}]*\})?[^/]+', path):
            if tag == '.':
                continue
            nodes = [child for node in nodes for child in node.children if child.tag == tag]
        return nodes

    def find(self, path: str) -> 'XmlElement | None':
        return next(iter(self.findall(path)), None)

    def findtext(self, path: str, default=None):
        found = self.find(path)
        return found.text if found is not None else default

    def iter(self, tag: str | None = None) -> Iterator['XmlElement']:
        if tag is None or self.tag == tag:
            yield self
        for child in self.children:
            yield from child.iter(tag)

    def itertext(self) -> Iterator[str]:
        if self.text:
            yield self.text
        for child in self.children:
            yield from child.itertext()
            if child.tail:
                yield child.tail


def xml_element(element: Element, models: Mapping[str, type[XmlElement]] | None = None) -> XmlElement:
    model = (models or {}).get(element.tag, XmlElement)
    return model(tag=element.tag, attributes=element.attrib, text=element.text or '', tail=element.tail or '',
                 children=[xml_element(child, models) for child in element])


def parse_xml_element(data: bytes | str) -> XmlElement:
    from congress_api.xml import parse_xml
    return xml_element(parse_xml(data))
