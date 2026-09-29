"""Parse GovInfo source bytes into source-owned models, before normalization."""
import html
import re

from congress_api.xml import MODS_NS, mods_elements, parse_xml
from congress_api.models.content import RawContent
from congress_api.models.xml import xml_element
from congress_api.models.gpo import (ModsAgent, ModsBill, ModsCommittee, ModsDocument, ModsMember, ModsName, ModsNominee, ModsRoleTerm,
    GpoTranscriptText, GpoPackageManifest, MetsFile, MetsFileLocation,
    ModsRendition, ModsScope, ModsSerial, ModsSubcommittee, ModsTitle)


def _names(element):
    return [ModsName(**dict(n.attrib), text=n.text) for n in element.findall('m:name', MODS_NS)]


def _member(element):
    return ModsMember(**dict(element.attrib), names=_names(element))


def _scope(element):
    scalar_tags = {
        'search_titles': 'searchTitle', 'preferred_citations': 'preferredCitation',
        'held_dates': 'heldDate', 'congresses': 'congress', 'sessions': 'session',
        'chambers': 'chamber', 'source_types': 'type',
        'event_ids': 'eventId', 'date_ingested': 'dateIngested',
        'document_classes': 'docClass', 'granule_classes': 'granuleClass',
        'errata': 'errata', 'is_errata': 'isErrata', 'is_nomination': 'isNomination', 'witnesses': 'witness',
    }
    return ModsScope(
        attributes=dict(element.attrib), relation_type=element.get('type'),
        titles=[ModsTitle(**dict(t.attrib), title=t.findtext('m:title', None, MODS_NS),
                          subtitle=t.findtext('m:subTitle', None, MODS_NS),
                          partName=t.findtext('m:partName', None, MODS_NS),
                          partNumber=t.findtext('m:partNumber', None, MODS_NS),
                          nonSort=t.findtext('m:nonSort', None, MODS_NS))
                for t in element.findall('m:titleInfo', MODS_NS)],
        **{field: [n.text for n in mods_elements(element, tag)] for field, tag in scalar_tags.items()},
        agents=[ModsAgent(**dict(n.attrib),
            name_parts=[ModsName(**dict(part.attrib), text=part.text) for part in n.findall('m:namePart', MODS_NS)],
            roles=[[ModsRoleTerm(**dict(term.attrib), text=term.text) for term in role.findall('m:roleTerm', MODS_NS)]
                   for role in n.findall('m:role', MODS_NS)])
                for n in element.findall('m:name', MODS_NS)],
        bills=[ModsBill(**dict(b.attrib), text=b.text) for b in mods_elements(element, 'bill')],
        nominees=[ModsNominee(**dict(n.attrib), names=_names(n),
            positions=[position.text for position in n.findall('m:position', MODS_NS)])
                  for n in mods_elements(element, 'nominee')],
        committees=[ModsCommittee(**dict(c.attrib), names=_names(c),
            subcommittees=[ModsSubcommittee(**dict(s.attrib), names=_names(s))
                           for s in c.findall('m:subCommittee', MODS_NS)])
                    for c in mods_elements(element, 'congCommittee')],
        members=[_member(m) for m in mods_elements(element, 'congMember')],
        renditions=[ModsRendition(**dict(u.attrib), url=u.text)
                    for u in element.findall('m:location/m:url', MODS_NS)],
        serials=[ModsSerial(**dict(s.attrib), text=s.text) for s in mods_elements(element, 'congSerial')],
    )


def parse_mods_document(data: str | bytes) -> ModsDocument:
    root = parse_xml(data)
    if root.tag != '{http://www.loc.gov/mods/v3}mods':
        raise ValueError('GovInfo metadata response is not a MODS document')
    return ModsDocument(
        root=_scope(root), related_items=[_scope(p) for p in root.findall('m:relatedItem', MODS_NS)],
        members=[_member(m) for m in root.iter('{http://www.loc.gov/mods/v3}congMember')],
        witnesses=[w.text or '' for w in root.iter('{http://www.loc.gov/mods/v3}witness')],
        xml=xml_element(root), content=RawContent.from_bytes(
            data if isinstance(data, bytes) else data.encode('utf-8'), 'application/xml'),
    )


def parse_transcript_html(data: str | bytes, *, decoded_text: str | None = None) -> GpoTranscriptText:
    """Retain the complete input HTML beside its tag-stripped text.

    HTTP callers supply response bytes and its declared-encoding text together.
    A string-only caller retains exactly that supplied string, not invented
    pre-decoding network bytes.
    """
    raw = data if isinstance(data, bytes) else data.encode('utf-8')
    page = decoded_text if decoded_text is not None else data.decode('utf-8', 'replace') if isinstance(data, bytes) else data
    return GpoTranscriptText(source=RawContent.from_bytes(raw, 'text/html'),
                             text=html.unescape(re.sub(r'<[^>]+>', '', page)))


def parse_package_manifest(data: bytes) -> GpoPackageManifest:
    """Read actual METS file locators without guessing filenames from package IDs.

    A listed file SIZE is publisher metadata, not proof of the captured length.
    Keep it unchanged, along with the complete ordered XML and original bytes.
    """
    root = parse_xml(data)
    ns = '{http://www.loc.gov/METS/}'
    if root.tag != ns + 'mets':
        raise ValueError('GovInfo package file manifest is not a METS document')
    return GpoPackageManifest(
        attributes=dict(root.attrib),
        files=[MetsFile(attributes=dict(file.attrib), locations=[
            MetsFileLocation(attributes=dict(location.attrib),
                href=location.get('{http://www.w3.org/1999/xlink}href'))
            for location in file.findall(ns + 'FLocat')])
            for section in root.findall(ns + 'fileSec') for file in section.iter(ns + 'file')],
        xml=xml_element(root), content=RawContent.from_bytes(data, 'application/xml'),
    )
