"""Author current rich reader inputs before the native release job runs.

These are synthetic domain records, not converted or patched release files.
Frozen native IPC schemas supply physical types; DDK checks the eventual output.
"""
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).parents[3]
DAY = date(2024, 5, 1)
EVENT = 118001
VIDEO = 'youtube:fixture-transit'


def occurrence(locator, **facts):
    record_sha, context = '11'*32, 'cc'*32
    key = sha256(json.dumps(['witness-occurrence-v2', 'meeting:118001', 'congress_gov',
        record_sha, locator, context], separators=(',', ':')).encode()).hexdigest()[:16]
    return dict(witness_key=key, occasion='meeting:118001', source='congress_gov',
        record_sha=bytes.fromhex(record_sha), source_locator=locator, context_key=context,
        event_id=EVENT, panel='1', panel_order=1, testified=True, **facts)


JANE = occurrence('witness/1', name='Dr. Jane Smith', position='Director',
    organization='National Transit Institute', display_order=1)
ADAM = occurrence('witness/2', name='Adam Smith', position='Representative',
    organization='U.S. House of Representatives', bioguide_id='S000510', display_order=2)


def records():
    return {
        'meetings': [dict(event_id=EVENT, chamber='house', chamber_basis='source', congress=118,
            title='Transportation infrastructure hearing', meeting_date=DAY, meeting_type='Hearing',
            session=2, status='held', sittings=[dict(start=datetime(2024, 5, 1, 14, tzinfo=timezone.utc),
                room='2167', building='Rayburn')],
            committees=[dict(system_code='hspw00', role='lead')],
            subject_keys=['118-hr-1234', '118-pn-730-2'], transcripts=[],
            videos=[dict(name='Hearing recording', url='https://www.youtube.com/watch?v=fixture-transit',
                         video_key=VIDEO)], not_held=False)],
        'committees': [
            dict(system_code='hspw00', name='House Committee on Transportation and Infrastructure',
                chamber='house', committee_type='standing', is_current=True,
                website='https://transportation.house.gov/', names=[
                    dict(name='House Committee on Transportation and Infrastructure',
                         start=date(1995, 1, 3), end=None),
                    dict(name='House Committee on Public Works and Transportation',
                         start=date(1975, 1, 3), end=date(1995, 1, 2))]),
            dict(system_code='hspw12', name='Subcommittee on Highways and Transit', chamber='house',
                committee_type='subcommittee', parent_system_code='hspw00', is_current=True,
                names=[dict(name='Subcommittee on Highways and Transit', start=date(2023, 1, 3), end=None)])],
        'witnesses': [JANE, ADAM],
        'members': [
            dict(bioguide_id='S000510', name='Adam Smith', terms=[dict(chamber='house', state='WA',
                district=9, party='D', start=date(2023, 1, 3), end=date(2025, 1, 3))],
                cross_ids=dict(fec=['H6WA09025'])),
            dict(bioguide_id='G000546', name='Sam Graves', terms=[dict(chamber='house', state='MO',
                district=6, party='R', start=date(2023, 1, 3), end=date(2025, 1, 3))],
                cross_ids=dict(fec=['H0MO06073']))],
        'rosters': [
            dict(congress=118, system_code='hspw00', bioguide_id='G000546', title='Chair', rank=1, party='R'),
            dict(congress=118, system_code='hspw00', bioguide_id='S000510', title='Member', rank=2, party='D')],
        'bills': [dict(bill_id='118-hr-1234', title='To modernize surface transportation.',
            short_title='Surface Transportation Modernization Act', sponsor_bioguide_id='S000510',
            introduced=date(2023, 2, 1), latest_action_date=DAY, latest_action_text='Hearing held.',
            stage='introduced', policy_area='Transportation', cosponsor_count=2, related_bills=[],
            committees=['hspw00'], cbo_estimates=[dict(publication_id='fixture-1234', date=DAY,
                description='Estimated transportation spending')],
            floor_votes=[dict(vote_id='118-house-2024-100', basis='vote_record', chamber='house', date=DAY,
                question='On Passage', result='Passed', yea=300, nay=100)],
            amendments=[dict(amendment_id='118-hamdt-1', purpose='Transit reporting',
                sponsor_bioguide_id='S000510', latest_action_date=DAY, latest_action_text='Agreed to.')],
            committee_activities=[dict(system_code='hspw00', activity='Hearing', date=DAY)])],
        'nominations': [dict(nomination_id='118-pn-730-2', description='Jane Doe, to be Administrator.',
            organization='Department of Transportation', received=date(2023, 6, 1),
            latest_action_date=DAY, latest_action_text='Confirmed by the Senate.',
            committee_activities=None, committees=[], transcripts=[],
            floor_votes=[dict(vote_id='118-senate-2024-101', date=DAY, question='On the Nomination',
                result='Confirmed', yea=55, nay=44)])],
        'recordings': [dict(video_key=VIDEO, event_ids=[EVENT], tracks=[dict(body=b'\x99'*32,
            suffix='.gz', format='vtt', language='en', production='manual')])],
        'videos': [dict(video_key=VIDEO, handle='@Transport', channel_id='fixture-transport',
            system_code='hspw00', title='Transportation infrastructure hearing',
            source_description='Synthetic hearing recording',
            published_at=datetime(2024, 5, 1, 14, tzinfo=timezone.utc),
            video_published_at=datetime(2024, 5, 1, 14, tzinfo=timezone.utc),
            duration_seconds=5420, available=True, has_caption=True,
            details_checked_at=datetime(2024, 5, 2, tzinfo=timezone.utc),
            stated_event_ids=[EVENT], record_sha=b'\x55'*32)],
    }


def author_entity_inputs(directory):
    """Write only fixture inputs; the retained native job writes every release table."""
    directory.mkdir(parents=True, exist_ok=False)
    source = ROOT/'model/fixtures/reader-entities'
    declared = json.loads((source/'schemas.json').read_text())['schemas']
    tables = records()
    assert tables.keys() == declared.keys()
    files = {}
    for name, rows in tables.items():
        pin = declared[name]
        raw = (source/pin['path']).read_bytes()
        assert len(raw) == pin['bytes'] and sha256(raw).hexdigest() == pin['sha256']
        schema = pa.ipc.read_schema(pa.BufferReader(raw))
        path = directory/(name+'.parquet')
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
        files[name] = path
    document = json.loads((ROOT/'model/fixtures/hand-release.json').read_text())
    agenda, excerpt = document['documents'][0], document['documents'][2]
    agenda.update(congress=118, chambers=['house'], committee_keys=['hspw00', 'hspw12'],
        measure_keys=['118-hr-1234', '118-pn-730-2'], bioguide_ids=['S000510'],
        witness_keys=[JANE['witness_key'], ADAM['witness_key']])
    excerpt.update(congress=118, chambers=['house'], committee_keys=['hspw00'],
        meeting_keys=[str(EVENT)], witness_keys=[JANE['witness_key']])
    document['witnesses'] = []
    document['witness_key_map'] = []
    document['expected']['witnesses'] = dict(jane=JANE['witness_key'], adam=ADAM['witness_key'])
    path = directory/'documents.json'
    path.write_text(json.dumps(document, indent=2)+'\n')
    return path, files
