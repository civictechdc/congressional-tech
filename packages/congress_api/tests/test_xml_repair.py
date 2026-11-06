"""House XML recovery preserves literal content and refuses invented structure."""
from hashlib import sha256
import xml.etree.ElementTree as ET

import pytest

from congress_api.parsers.house_xml import parse_house_meeting, parse_house_witnesses
from congress_api.parsers.xml import parse_xml
from congress_api.parsers.xml_repair import parse_xml_with_repairs


@pytest.mark.parametrize('payload', [
    b'<x>A &amp; B &#38; &#x26;</x>',
    b'<x><![CDATA[A & B]]><!-- & --></x>',
    b'<?note A & B?><x a="&quot;">A</x>',
    b'\xef\xbb\xbf<x/>',
    b'<!DOCTYPE x [<!ENTITY known "A &amp; B">]><x>&known;</x>',
])
def test_valid_xml_is_unchanged(payload):
    result = parse_xml_with_repairs(payload)
    assert result.normalized_bytes == payload and result.repairs == ()
    assert result.original_sha256 == result.normalized_sha256 == sha256(payload).hexdigest()


def test_literal_ampersands_are_repaired_only_in_text_and_quoted_attributes():
    original = b'''<?note & ?><x a="A & B > C &" b='D & E'>A & B &amp; C &#38;<![CDATA[D & E]]><!-- F & G --></x>'''
    expected = b'''<?note & ?><x a="A &amp; B > C &amp;" b='D &amp; E'>A &amp; B &amp; C &#38;<![CDATA[D & E]]><!-- F & G --></x>'''
    with pytest.raises(ET.ParseError):
        parse_xml(original)  # recovery is opt-in, not a global change
    result = parse_xml_with_repairs(original)
    assert result.normalized_bytes == expected
    assert result.root.attrib == {'a': 'A & B > C &', 'b': 'D & E'}
    assert result.root.text == 'A & B & C &D & E'
    assert result.repairs == (('literal_ampersand', 4),)
    assert result.original_sha256 == sha256(original).hexdigest()
    assert result.normalized_sha256 == sha256(expected).hexdigest()
    repeated = parse_xml_with_repairs(result.normalized_bytes)
    assert repeated.repairs == () and repeated.normalized_bytes == expected


@pytest.mark.parametrize('payload', [
    b'<x>A & B',                         # truncation, even after a repairable character
    b'<x>A & B</y>',                     # broken nesting
    b'<x>&unknown;</x>',                 # no entity meaning is guessed
    b'<x>&amp</x>',                      # incomplete entity-like spelling
    b'<x>&#xyz;</x>',                    # invalid numeric reference
    b'<x>A\x00 & B</x>',                # controls are never dropped
    b'<x>A & B<!-- unfinished',
    b'<x>A & B<![CDATA[unfinished',
    b'<!DOCTYPE x [<!ENTITY a "A & B">]><x>&a;</x>',
    b'<x bad&="value"/>',               # attribute names are never rewritten
    b'<x>\xff & B</x>',                 # no encoding guess
])
def test_unsupported_damage_stays_unreadable(payload):
    with pytest.raises(ET.ParseError):
        parse_xml_with_repairs(payload)


@pytest.mark.parametrize('parse, payload, tag', [
    (parse_house_meeting, b'<committee-meeting meeting-id="HHRG1"><heading>A & B</heading></committee-meeting>', 'heading'),
    (parse_house_witnesses, b'<witness-list meeting-id="HHRG1"><note>A & B</note></witness-list>', 'note'),
])
def test_typed_house_xml_keeps_the_acquired_bytes(parse, payload, tag):
    parsed = parse(payload)
    assert parsed.find(tag).text == 'A & B'
    assert parsed.raw_content.body_bytes() == payload


def test_repaired_wrong_root_uses_the_same_tree_for_appearance_classification():
    from congress_api.lake.appearance_records import extract_house_xml_observation
    observation = extract_house_xml_observation(
        b'<committee-meeting meeting-id="HHRG118888"><heading>A & B</heading></committee-meeting>')
    assert observation['event_id'] == 118888
    assert observation['collection_state'] == 'absent' and observation['appearances'] == []
