"""Browser pages preserve graph discovery and encoded artifact integrity."""
import gzip
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_explorer_export import native, run, write_meetings
from committee_explorer.browser import package, verify, MEDIA_TYPE
from committee_explorer.query import write_queries
from committee_meeting.common import Ref, ReportedTime
from committee_meeting.committees import CommitteeTerm
from committee_meeting.issues import DataIssue
from committee_meeting.materials import DocumentDetails, Material, MaterialLink, MaterialVersion, Representation
from committee_meeting.meetings import Appearance, ConveningCommittee, Meeting, MeetingOccurrence, RecordedName
from committee_meeting.provenance import Citation, Provenance


def files(tmp_path, manifest):
    root=tmp_path/'public';ptr=json.loads((root/'CURRENT.json').read_text());base=(root/ptr['manifest_path']).parent
    return base, {p.schema_name:p for p in manifest.partitions}


def test_query_rows_share_coverage_states_and_resolve_inverse_relationships(tmp_path):
    row=native();row['videos']=[{'url':'https://www.youtube.com/watch?v=abcdefghijk'}]
    manifest,catalog=run(tmp_path,write_meetings(tmp_path,[row]))
    base,parts=files(tmp_path,manifest)
    query=json.loads((base/parts['committee_explorer.queries'].path).read_text())
    page=next(p for p in query['partitions'] if p['kind']=='meeting')
    meeting=json.loads((base/page['path']).read_text())['rows'][0]
    assert meeting['evidence_states']['recording']=='reported'
    assert 'Alex Smith' in meeting['search_text']
    assert query['committee_labels'][meeting['committee_ids'][0]]
    root=json.loads((base/parts['committee_explorer.relations'].path).read_text())
    key='meeting/'+meeting['id'];bucket=hashlib.sha256(key.encode()).hexdigest()[:2]
    related=json.loads((base/root['buckets'][bucket]).read_text())['relations'][key]
    assert {'occurrence','appearance','material_link'} <= {r['kind'] for r in related}
    ids={(r.kind,r.id) for r in catalog.records}
    assert all((r['kind'],r['id']) in ids for r in related)


def test_browser_package_is_small_encoded_and_independently_verifiable(tmp_path):
    manifest,_=run(tmp_path,write_meetings(tmp_path,[native()]))
    browser=tmp_path/'browser';m,size=package(tmp_path/'public',browser)
    _,base,verified=verify(browser)
    assert verified==m
    assert all(p.role!='download' and p.media_type==MEDIA_TYPE for p in m.partitions)
    assert all(p.path.endswith('.data') and not p.path.endswith('.gz') for p in m.partitions)
    parts={p.path:p for p in m.partitions}
    assert all('catalog' not in p.path for p in m.partitions)
    query=next(p for p in m.partitions if p.schema_name=='committee_explorer.queries')
    root=json.loads(gzip.decompress((base/query.path).read_bytes()))
    assert all(p['path'] in parts for p in root['partitions'])
    locations=next(p for p in m.partitions if p.schema_name=='committee_explorer.locations')
    root=json.loads(gzip.decompress((base/locations.path).read_bytes()))
    for bucket in root['buckets'].values():
        values=json.loads(gzip.decompress((base/bucket).read_bytes()))['locations']
        assert all(path in parts for path in values.values())
    pointer=(browser/'CURRENT.json').read_bytes()
    with pytest.raises(ValueError,match='budget'):
        package(tmp_path/'public',browser,max_bytes=1)
    assert (browser/'CURRENT.json').read_bytes()==pointer
    target=base/m.partitions[0].path;target.write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='differs'):
        verify(browser)


EVIDENCE = Provenance(basis='reported', citations=(Citation(source=Ref(kind='source_record', id='source')),))


def scope_fixture(label, congress=119, chamber='house', committee_name='Committee on Testing'):
    committee = CommitteeTerm(id='committee-' + label, committee=Ref(kind='committee', id='identity-' + label),
                              congress=congress or 119, chamber=chamber, name=committee_name, provenance=EVIDENCE)
    meeting = Meeting(id='meeting-' + label, congress=congress, chamber=chamber,
                      committees=(ConveningCommittee(committee=Ref(kind=committee.kind, id=committee.id), provenance=EVIDENCE),),
                      provenance=EVIDENCE)
    occurrence = MeetingOccurrence(id='occurrence-' + label, meeting=Ref(kind=meeting.kind, id=meeting.id),
                                   scheduled_start=ReportedTime(date=date(2026, 9, 20)), provenance=EVIDENCE)
    return [committee, meeting, occurrence]


def query_rows(records):
    written = {}
    def write(path, data, *args, **kwargs):
        written[path] = data
    write_queries(SimpleNamespace(records=records), {(r.kind, r.id) for r in records}, write)
    rows = {row['id']: row for path, data in written.items() if path.startswith('queries/') for row in data['rows']}
    return rows, written['indexes/queries.json']


def link(label, material, subject):
    return MaterialLink(id=label, material=Ref(kind='material', id=material.id),
                        subject=Ref(kind=subject.kind, id=subject.id), provenance=EVIDENCE)


def test_material_and_issues_inherit_unique_appearance_meeting_scope_regardless_of_record_order():
    committee, meeting, occurrence = scope_fixture('one')
    appearance = Appearance(id='witness', meeting=Ref(kind='meeting', id=meeting.id),
                            name=RecordedName(display='Listed witness'), provenance=EVIDENCE)
    material = Material(id='statement', details=DocumentDetails(category='statement'), provenance=EVIDENCE)
    version = MaterialVersion(id='version', material=Ref(kind='material', id=material.id), provenance=EVIDENCE)
    representation = Representation(id='file', version=Ref(kind='material_version', id=version.id), provenance=EVIDENCE)
    issues = [DataIssue(id='issue-' + subject.id, subject=Ref(kind=subject.kind, id=subject.id), category='unverified',
                        summary='Review retained source', detected_at=datetime(2026, 9, 27, tzinfo=timezone.utc), provenance=EVIDENCE)
              for subject in (material, representation)]
    records = [*issues, material, version, representation, appearance, committee, meeting, occurrence,
               link('appearance-link', material, appearance), link('occurrence-link', material, occurrence)]
    rows, _ = query_rows(records)
    reversed_rows, _ = query_rows(list(reversed(records)))
    for subject in (material, *issues):
        row = rows[subject.id]
        assert row == reversed_rows[subject.id]
        assert (row['congress'], row['chamber'], row['meeting_id'], row['date'], row['committee_ids']) == (
            119, 'house', meeting.id, '2026-09-20', [committee.id])
    # These are the fields used by the browser's date and committee filters.
    assert [r['id'] for r in rows.values() if r['kind'] == 'material' and committee.id in r['committee_ids']
            and '2026-09-01' <= r['date'] <= '2026-09-30'] == [material.id]


@pytest.mark.parametrize('other_congress,other_chamber,expected_congress,expected_chamber', [
    (119, 'house', 119, 'house'), (118, 'house', None, 'house'),
    (119, 'senate', 119, 'unknown'), (None, 'unknown', None, 'unknown'),
])
def test_shared_material_retains_supported_committees_without_inventing_unique_meeting_or_date(
        other_congress, other_chamber, expected_congress, expected_chamber):
    first = scope_fixture('first')
    second = scope_fixture('second', other_congress, other_chamber)
    material = Material(id='shared-volume', details=DocumentDetails(), provenance=EVIDENCE)
    rows, _ = query_rows([material, *first, *second, link('first-link', material, first[1]), link('second-link', material, second[1])])
    row = rows[material.id]
    assert (row['congress'], row['chamber']) == (expected_congress, expected_chamber)
    assert row['meeting_id'] is None and row['date'] is None
    assert row['committee_ids'] == [first[0].id, second[0].id]


def test_direct_committee_material_scope_and_missing_name_are_readable():
    committee = scope_fixture('unnamed', committee_name=None)[0]
    material = Material(id='committee-document', details=DocumentDetails(), provenance=EVIDENCE)
    rows, index = query_rows([material, committee, link('committee-link', material, committee)])
    assert rows[material.id]['committee_ids'] == [committee.id]
    assert (rows[material.id]['congress'], rows[material.id]['chamber']) == (119, 'house')
    assert rows[material.id]['meeting_id'] is None and rows[material.id]['date'] is None
    assert rows[committee.id]['title'] == 'Committee name not recorded'
    assert index['committee_labels'][committee.id] == 'Committee name not recorded'
