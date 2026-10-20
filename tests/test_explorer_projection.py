"""Assembled records carry the browser's fields; links and representations stay authoritative."""
from datetime import datetime, timezone

import pyarrow.parquet as pq
import pytest
from committee_explorer.assemble import Assembly
from committee_explorer.browser import verify
from committee_explorer.export import export
from committee_meeting.common import Identifier, Ref
from committee_meeting.materials import DocumentDetails, Material, MaterialLink
from committee_meeting.meetings import Meeting
from committee_meeting.provenance import Citation, Provenance, SourceRecord
from congress_api.adapters import gpo, house
from test_explorer_export import NOW, native, write_meetings
from test_explorer_material_adapters import context, gpo_row


def exported(tmp_path, rows):
    _, catalog = export(meetings=write_meetings(tmp_path, rows), output_dir=tmp_path / 'out',
                        state_dir=tmp_path / 'state', as_of=NOW, format='parquet')
    _, root, _ = verify(tmp_path / 'out')
    tables = {name: {r['id']: r for r in pq.read_table(root / f'{name}.parquet').to_pylist()}
              for name in ('materials', 'meetings', 'committees')}
    return catalog, tables


def test_assembled_fields_agree_with_the_published_tables(tmp_path):
    """The browser tables derive these values from raw payloads; the records now carry them."""
    row = native()
    row['meetingDocuments'] = [{'name': 'Hearing notice', 'documentType': 'Hearing Notice', 'url': 'https://example.org/notice.pdf'}]
    row['witnessDocuments'] = [{'documentType': 'Witness Statement', 'url': 'https://example.org/statement.pdf'},
                               {'documentType': 'Witness Statement', 'url': 'https://example.org/notice.pdf'}]
    row['videos'] = [{'url': 'https://www.youtube.com/watch?v=abcdefghijk'}]
    closed = {**native(), 'eventId': '106246', 'type': 'Meeting', 'title': 'Closed briefing on readiness', 'meetingStatus': 'Canceled'}
    catalog, tables = exported(tmp_path, [row, closed])
    materials = [r for r in catalog.records if r.kind == 'material']
    assert materials
    for material in materials:
        published = tables['materials'][material.id]
        assert sorted(material.meeting_ids) == published['meeting_ids']
        assert sorted(material.appearance_ids) == published['appearance_ids']
        assert sorted({f.url for f in material.files}) == sorted({f['url'] for f in published['files']})
        assert material.document_type == published['document_type']
        assert sorted(set(material.source_document_groups)) == published['source_document_groups']
    assert {(m.document_type, m.source_document_groups) for m in materials if m.details.type == 'document'} == {
        ('Hearing Notice', ('meetingDocuments',)), ('Witness Statement', ('witnessDocuments',)),
        ('Statement', ('meetingDocuments',))}
    assert all(m.meeting_ids for m in materials)
    for meeting in (r for r in catalog.records if r.kind == 'meeting'):
        published = tables['meetings'][meeting.id]
        assert (meeting.access, meeting.status) == (published['access'], published['status'])
        assert meeting.scheduled_start.original == published['scheduled_at']
        assert {'label': 'Source type', 'value': meeting.source_type} in published['facts']
    for term in (r for r in catalog.records if r.kind == 'committee_term'):
        published = tables['committees'][term.id]
        assert (term.committee_code, term.committee_level) == (published['committee_code'], published['committee_level'])


def evidence(source_id):
    return Provenance(citations=(Citation(source=Ref(kind='source_record', id=source_id)),), basis='reported')


def test_repeated_material_collects_groups_files_and_links_without_conflicts():
    sources = [SourceRecord(id=id, provider='test', identifier=Identifier(scheme='test', value=id), payload={})
               for id in ('a', 'b')]
    meeting = Meeting(id='meeting', provenance=evidence('a'))
    first = Material(id='doc', details=DocumentDetails(category='statement'), source_document_groups=('meetingDocuments',),
                     provenance=evidence('a'))
    second = first.model_copy(update={'source_document_groups': ('witnessDocuments',), 'provenance': evidence('b')})
    link = MaterialLink(id='link', material=Ref(kind='material', id='doc'), subject=Ref(kind='meeting', id='meeting'),
                        role='statement', provenance=evidence('b'))
    assembly = Assembly(ids=lambda kind, key: kind + ':' + key, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
    assembly.add([*sources, meeting, first, second, link])
    catalog = assembly.finish()
    material = next(r for r in catalog.records if r.kind == 'material')
    assert material.source_document_groups == ('meetingDocuments', 'witnessDocuments')
    assert material.meeting_ids == ('meeting',)
    assert not any(r.kind == 'data_issue' for r in catalog.records)


def test_house_document_groups_carry_their_publisher_label_and_collection():
    state = {'106245': {'evidence': {'document_groups': [
        {'type': 'WT', 'source': 'witness_xml', 'description': 'Truth in testimony form',
         'files': [{'url': 'https://docs.house.gov/meetings/WT.pdf'}]}]}}}
    records = list(house.records(state, context('docs.house.gov'), meetings={}))
    material, = [r for r in records if r.kind == 'material']
    assert material.document_type == 'Truth in testimony'
    assert material.source_document_groups == ('Witness documents',)


@pytest.mark.parametrize('package,congress,source_type', [
    ('CHRG-109shrg25756', '109', 'Congressional Budget Justification'),
    ('CHRG-118hhrg55711', '118', 'COMMITTEE PRINT'),
])
def test_reviewed_gpo_package_carries_its_reviewed_document_type(package, congress, source_type):
    records = list(gpo.records([gpo_row(package_id=package, congress=congress)], context(),
                               review_context=context('gpo.committee-review')))
    assert next(r for r in records if r.kind == 'material').document_type == source_type
    unreviewed = list(gpo.records([gpo_row()], context(), review_context=context('gpo.committee-review')))
    assert next(r for r in unreviewed if r.kind == 'material').document_type is None
