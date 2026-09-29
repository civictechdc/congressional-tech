"""Congress.gov's XML transport, with its original scalar text and full body."""

from .base import SourceModel
from .content import RawContent
from .xml import XmlElement


class CongressXmlDocument(SourceModel):
    xml: XmlElement
    content: RawContent
