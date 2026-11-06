"""Opt-in XML repairs that preserve text; ordinary XML parsing stays strict.

XML references cannot begin with whitespace or a markup/attribute delimiter
(https://www.w3.org/TR/xml/#sec-references). Only those clearly literal ampersands
are escaped. Entity-like text, declarations and incomplete documents are not guessed.
"""

from dataclasses import dataclass
from hashlib import sha256
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class XMLRepairResult:
    root: ET.Element
    original_sha256: str
    normalized_sha256: str
    normalized_bytes: bytes
    repairs: tuple[tuple[str, int], ...]


def _escape_literal_ampersands(data: bytes) -> tuple[bytes, int]:
    """Visit text and quoted attributes, preserving comments, CDATA and instructions."""
    pieces = []
    start = index = count = 0
    in_tag = False
    quote = None
    while index < len(data):
        if not in_tag and data[index:index + 1] == b'<':
            for opening, closing in ((b'<!--', b'-->'), (b'<![CDATA[', b']]>'), (b'<?', b'?>')):
                if data.startswith(opening, index):
                    end = data.find(closing, index + len(opening))
                    if end < 0:
                        return data, 0
                    index = end + len(closing)
                    break
            else:
                # DTD/entity declarations require a separate policy. Leave them strict.
                if data.startswith(b'<!', index):
                    return data, 0
                in_tag = True
                index += 1
            continue
        char = data[index]
        if in_tag:
            if quote is None:
                if char in (ord('"'), ord("'")):
                    quote = char
                elif char == ord('>'):
                    in_tag = False
                index += 1
                continue
            if char == quote:
                quote = None
                index += 1
                continue
        following = data[index + 1:index + 2]
        delimiters = b' \t\r\n' + (bytes([quote]) if quote is not None else b'<')
        if char == ord('&') and following and following[0] in delimiters:
            pieces.extend((data[start:index], b'&amp;'))
            start = index + 1
            count += 1
        index += 1
    if not count:
        return data, 0
    pieces.append(data[start:])
    return b''.join(pieces), count


def parse_xml_with_repairs(data: bytes | str) -> XMLRepairResult:
    """Strict first, then one bounded lexical repair and a full strict parse.

    The result identifies the original and normalized bytes and the rule/count.
    Failed repairs raise the original syntax error. No partial tree is accepted.
    """
    original = data.encode('utf-8') if isinstance(data, str) else data
    original_sha = sha256(original).hexdigest()
    try:
        root = ET.fromstring(original)
    except ET.ParseError as error:
        # Repair only UTF-8 bytes. Do not infer or replace a source encoding.
        try:
            original.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise error
        normalized, count = _escape_literal_ampersands(original)
        if not count:
            raise
        try:
            root = ET.fromstring(normalized)
        except ET.ParseError:
            raise error
        return XMLRepairResult(root, original_sha, sha256(normalized).hexdigest(), normalized,
                               (('literal_ampersand', count),))
    return XMLRepairResult(root, original_sha, original_sha, original, ())
