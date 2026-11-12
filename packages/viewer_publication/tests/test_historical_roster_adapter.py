"""Bounded readiness checks for ss-ehci input; these seats are synthetic, not source history."""
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from congress_api.lake.model_sql import model_steps
from congress_api.retention.provenance import json_input, parquet_output, run_job
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model import SPICY_SCHEMAS, registry_inputs

ROOT = Path(__file__).parents[3]
HISTORY = tuple(range(113, 119))
#: The directory source labels committee_assignments carries for 113th-118th seats (ss-ehci).
LABELS = dict(congress_basis='directory', edition_date='2014-02-18', source_granule='CDIR-2014-02-18-HOUSECOMMITTEES',
              source_line='12', position_basis='printed', printed_entry='Fixture (TX)', entry_label=None)
EXPECTED_LABELS = dict(LABELS, edition_date=__import__('datetime').date(2014, 2, 18))


def _inputs(directory, assignments):
    terms = [
        dict(bioguide_id='A000001', term_party='Democrat', term_start='2013-01-03', term_end='2019-01-03'),
        dict(bioguide_id='A000001', term_party='Republican', term_start='2019-01-03', term_end='2025-01-03'),
        dict(bioguide_id='B000002', term_party='Republican', term_start='2011-01-03', term_end='2013-01-03'),
        dict(bioguide_id='B000002', term_party='Independent', term_start='2013-01-03', term_end='2025-01-03'),
        dict(bioguide_id='C000003', term_party='Democrat', term_start='2013-01-03', term_end='2025-01-03'),
        dict(bioguide_id='D000004', term_party='Republican', term_start='2013-01-03', term_end='2025-01-03'),
        dict(bioguide_id='E000005', term_party='Democrat', term_start='2011-01-03', term_end='2013-01-03'),
        dict(bioguide_id='F000006', term_party='Democrat', term_start='2021-01-03', term_end='2023-01-03'),
        dict(bioguide_id='G000007', term_party='Republican', term_start='2025-01-03', term_end='2027-01-03'),
        dict(bioguide_id='H000008', term_party='Democrat', term_start='2023-01-03', term_end='2024-06-30'),
        dict(bioguide_id='H000008', term_party='Republican', term_start='2024-06-30', term_end='2025-01-03'),
        dict(bioguide_id='I000009', term_party='Republican', term_start='2023-01-03', term_end=None),
        dict(bioguide_id='J000010', term_party='Democrat', term_start='2023-01-03', term_end='unreadable'),
        # A single term-level assertion can omit party changes within that term.
        dict(bioguide_id='K000011', term_party='Independent', term_start='2019-01-03', term_end='2025-01-03'),
    ]
    members = [dict(bioguide_id=key, name_first='Fixture', name_last=key)
               for key in ('A000001', 'B000002', 'C000003', 'D000004',
                           'E000005', 'F000006', 'G000007', 'H000008', 'I000009', 'J000010', 'K000011')]
    committees = [dict(system_code=key, name='Fixture ' + key, chamber=chamber,
                       committee_type='Standing', is_current=False)
                  for key, chamber in (('HLIG00', 'House'), ('SSFI00', 'Senate'))]
    tables = dict(spicy_committee_assignments=assignments, spicy_member_terms=terms,
                  spicy_members=members, spicy_committees=committees)
    return registry_inputs(directory / 'registries') + [
        json_input(directory, name, rows, **SPICY_SCHEMAS[name]) for name, rows in tables.items()]


def _build(directory, assignments):
    # The entity steps with every model step they read (members reads member_terms), as the model orders them.
    directory.mkdir()
    outputs = [parquet_output(directory, name, 'SELECT * FROM entity_' + name,
                              ['congress', 'system_code', 'bioguide_id'] if name == 'rosters' else
                              ['bioguide_id'] if name == 'members' else ['system_code'])
               for name in ('rosters', 'members', 'committees')]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        run_job(directory, engine, inputs=_inputs(directory, assignments), outputs=outputs,
                steps=model_steps(['entity-rosters', 'entity-members', 'entity-committees'], root=ROOT, materialize=True))
    return directory


@pytest.fixture(scope='module')
def historical(tmp_path_factory):
    assignments = [dict(congress=congress, session='2', system_code=code, bioguide_id=member,
                        position=title, rank=1, party=party, chamber=chamber,
                        is_subcommittee=parent is not None, parent_system_code=parent,
                        committee_name='Fixture ' + code, **LABELS)
                   for congress in HISTORY
                   for code, member, title, party, chamber, parent in (
                       ('HSIG00', 'A000001', 'Chair', None, 'House', None),
                       ('HSIG00', 'B000002', 'Ranking Member', None, 'House', None),
                       ('HSIG01', 'C000003', 'Vice Chair', 'Independent', 'House', 'HSIG00'),
                       ('SSFI00', 'D000004', 'Chair', None, 'Senate', None),
                       ('SSFI01', 'D000004', 'Vice Chair', None, 'Senate', 'SSFI00'),
                   )]
    root = tmp_path_factory.mktemp('historical-roster')
    return _build(root / 'populated', assignments)


def test_historical_seats_preserve_congress_leadership_and_supplied_party(historical):
    rows = pq.read_table(historical / 'rosters.parquet').to_pylist()
    expected = [dict(congress=congress, system_code=code, bioguide_id=member, title=title,
                     rank=1, party=party, **EXPECTED_LABELS)
                for congress in HISTORY
                for code, member, title, party in (
                    ('hlig00', 'A000001', 'Chair', None),
                    ('hlig00', 'B000002', 'Ranking Member', None),
                    ('hlig01', 'C000003', 'Vice Chair', 'Independent'),
                    ('ssfi00', 'D000004', 'Chair', None),
                    ('ssfi01', 'D000004', 'Vice Chair', None),
                )]
    assert rows == expected
    assert len({(r['congress'], r['system_code'], r['bioguide_id']) for r in rows}) == len(rows)


def test_historical_seats_resolve_members_committees_and_subcommittee_parents(historical):
    rows = pq.read_table(historical / 'rosters.parquet').to_pylist()
    members = {r['bioguide_id'] for r in pq.read_table(historical / 'members.parquet').to_pylist()}
    committees = {r['system_code']: r for r in pq.read_table(historical / 'committees.parquet').to_pylist()}
    assert {r['bioguide_id'] for r in rows} <= members
    assert {r['system_code'] for r in rows} <= committees.keys()
    for child, parent in (('hlig01', 'hlig00'), ('ssfi01', 'ssfi00')):
        assert committees[child]['committee_type'] == 'subcommittee'
        assert committees[child]['parent_system_code'] == parent
        assert parent in committees


@pytest.mark.parametrize('congress', (116, 117, 118))
def test_published_roster_recipe_returns_historical_leadership(historical, congress):
    # Use the published reader's exact SQL against only the fixture exports.
    import duckdb
    schema = json.loads((ROOT / 'model/registries/release-schema.json').read_text())
    recipe = next(r for r in schema['recipes'] if r['id'] == 'committee_roster')
    with duckdb.connect() as connection:
        for table in recipe['requires']:
            connection.read_parquet(str(historical / (table + '.parquet'))).create_view(table)
        result = connection.execute(recipe['sql'], ['hlig00', congress]).fetchall()
        assert [(r[0], r[1], r[3], r[5]) for r in result] == [
            (congress, 'hlig00', 'A000001', 'Chair'),
            (congress, 'hlig00', 'B000002', 'Ranking Member'),
        ]
        assert all(r[2] and r[4] for r in result)
        assert connection.execute(recipe['sql'], ['hlig00', 112]).fetchall() == []


def test_service_terms_and_committee_references_do_not_create_missing_history(tmp_path):
    directory = _build(tmp_path / 'absent', [])
    assert pq.read_table(directory / 'members.parquet').num_rows == 11
    assert pq.read_table(directory / 'committees.parquet').num_rows == 2
    assert pq.read_table(directory / 'rosters.parquet').num_rows == 0


def test_missing_source_party_is_not_inferred_from_service_terms(tmp_path):
    # Dates, open terms and agreement between term assertions cannot establish
    # party at the roster observation. One assertion may hide mid-term changes.
    assignments = [dict(congress=118, system_code='SSFI00', bioguide_id=member,
                        position='Member', rank=rank, party=None)
                   for rank, member in enumerate(('E000005', 'F000006', 'G000007', 'H000008',
                                                  'I000009', 'J000010'), 1)]
    assignments += [dict(congress=congress, system_code='SSFI00', bioguide_id='K000011',
                         position='Chair', rank=1, party=None) for congress in (116, 117)]
    directory = _build(tmp_path / 'party-boundaries', assignments)
    rows = pq.read_table(directory / 'rosters.parquet').to_pylist()
    assert [(r['congress'], r['bioguide_id'], r['party']) for r in rows] == [
        (116, 'K000011', None), (117, 'K000011', None),
        (118, 'E000005', None), (118, 'F000006', None), (118, 'G000007', None),
        (118, 'H000008', None), (118, 'I000009', None), (118, 'J000010', None),
    ]


def test_a_directory_defined_task_force_resolves_under_its_committee(tmp_path):
    # The 114th House Financial Services task force has no Congress.gov code; its seats name a directory code.
    seats = [dict(congress=114, system_code=code, bioguide_id='D000004', position=None, rank=1, party=None,
                  chamber='house', is_subcommittee=parent is not None, parent_system_code=parent,
                  committee_name=name, **dict(LABELS, entry_label=label))
             for code, parent, name, label in (
                 ('hsba00', None, 'Financial Services', None),
                 ('hsba00-tf-terrorism-financing', 'hsba00', 'Task Force to Investigate Terrorism Financing',
                  'no_congress_gov_code'))]
    directory = _build(tmp_path / 'task-force', seats)
    committees = {r['system_code']: r for r in pq.read_table(directory / 'committees.parquet').to_pylist()}
    force = committees['hsba00-tf-terrorism-financing']
    assert (force['committee_type'], force['parent_system_code'], force['name']) == (
        'task force', 'hsba00', 'Task Force to Investigate Terrorism Financing')
    rosters = pq.read_table(directory / 'rosters.parquet').to_pylist()
    assert {r['system_code'] for r in rosters} <= committees.keys()
    assert {r['system_code']: r['entry_label'] for r in rosters} == {
        'hsba00': None, 'hsba00-tf-terrorism-financing': 'no_congress_gov_code'}


def test_departed_before_edition_seat_is_labelled_after_departure(tmp_path):
    """ct-sh1i: Directory seats printed after a member's service ended carry entry_label='after_departure'."""
    directory = tmp_path / 'departed'
    directory.mkdir()
    terms = [
        # Departed before 2018-10-29 edition (e.g. McCain 2018-08-25)
        dict(bioguide_id='M000303', term_party='Republican', term_start='2017-01-03', term_end='2018-08-25'),
        # Serving on 2018-10-29 edition
        dict(bioguide_id='I000024', term_party='Republican', term_start='2015-01-06', term_end='2021-01-03'),
        # Unreadable term_end must not invent after_departure
        dict(bioguide_id='J000010', term_party='Democrat', term_start='2017-01-03', term_end='unreadable'),
        # Departed in 115th, returned in 117th -> still departed on 2018-10-29
        dict(bioguide_id='R000001', term_party='Republican', term_start='2017-01-03', term_end='2018-05-01'),
        dict(bioguide_id='R000001', term_party='Republican', term_start='2021-01-03', term_end='2023-01-03'),
    ]
    members = [dict(bioguide_id=k, name_first='Fixture', name_last=k)
               for k in ('M000303', 'I000024', 'J000010', 'R000001')]
    committees = [dict(system_code='SSAS00', name='Armed Services', chamber='Senate',
                       committee_type='Standing', is_current=True)]
    ed_labels = dict(LABELS, edition_date='2018-10-29', source_granule='CDIR-2018-10-29-SENATECOMMITTEES')
    assignments = [
        dict(congress=115, session='2', system_code='SSAS00', bioguide_id='M000303', position='Chair', rank=1,
             party='Republican', chamber='Senate', **ed_labels),
        dict(congress=115, session='2', system_code='SSAS00', bioguide_id='I000024', position=None, rank=2,
             party='Republican', chamber='Senate', **ed_labels),
        dict(congress=115, session='2', system_code='SSAS00', bioguide_id='J000010', position=None, rank=1,
             party='Democrat', chamber='Senate', **ed_labels),
        dict(congress=115, session='2', system_code='SSAS00', bioguide_id='R000001', position=None, rank=3,
             party='Republican', chamber='Senate', **dict(ed_labels, entry_label='corrected', printed_entry='R (XX)')),
        dict(congress=115, session='2', system_code='SSAS01', bioguide_id='R000001', position=None, rank=2,
             party='Republican', chamber='Senate', is_subcommittee=True, parent_system_code='SSAS00',
             committee_name='Airland', **ed_labels),
    ]
    tables = dict(spicy_committee_assignments=assignments, spicy_member_terms=terms,
                  spicy_members=members, spicy_committees=committees)
    inputs = registry_inputs(directory / 'registries') + [
        json_input(directory, name, rows, **SPICY_SCHEMAS[name]) for name, rows in tables.items()]
    outputs = [parquet_output(directory, 'rosters', 'SELECT * FROM entity_rosters',
                              ['congress', 'system_code', 'bioguide_id'])]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        run_job(directory, engine, inputs=inputs, outputs=outputs,
                steps=model_steps(['entity-rosters'], root=ROOT, materialize=True))
    rows = {(r['system_code'], r['bioguide_id']): r for r in pq.read_table(directory / 'rosters.parquet').to_pylist()}
    assert rows[('ssas00', 'M000303')]['entry_label'] == 'after_departure'
    assert rows[('ssas00', 'I000024')]['entry_label'] is None
    assert rows[('ssas00', 'J000010')]['entry_label'] is None
    assert rows[('ssas00', 'R000001')]['entry_label'] == 'corrected'
    assert rows[('ssas01', 'R000001')]['entry_label'] == 'after_departure'


def test_unprinted_source_rank_stays_absent_and_mixed_118th_uses_single_dated_snapshot(tmp_path):
    """ct-sh1i: unprinted ranks stay None; mixed 118th committees keep one dated chamber-file snapshot."""
    import datetime
    import duckdb
    assignments = [
        # Mixed 118th House Rules: stale 2024-04-25 directory-manual Chair + complete 2024-05-01 archived file
        dict(congress=118, session='2', system_code='HSRU00', bioguide_id='A000001', position='Chair', rank=1,
             party='Republican', chamber='House', congress_basis='directory-manual', edition_date='2024-04-25',
             source_granule='CDIR-2024-04-25', source_line='10:1', position_basis='printed', printed_entry=None, entry_label=None),
        dict(congress=118, session='2', system_code='HSRU00', bioguide_id='D000004', position='Chair', rank=1,
             party='Republican', chamber='House', congress_basis='file', edition_date=None,
             source_granule='https://web.archive.org/web/20240501161500id_/https://clerk.house.gov/xml/lists/MemberData.xml',
             source_line=None, position_basis=None, printed_entry=None, entry_label=None),
        # Directory-manual-only Senate subcommittee stays published with its 2024-04-25 edition_date
        dict(congress=118, session='2', system_code='SSFI01', bioguide_id='C000003', position='Chair', rank=1,
             party='Democrat', chamber='Senate', is_subcommittee=True, parent_system_code='SSFI00',
             committee_name='Health Care', congress_basis='directory-manual', edition_date='2024-04-25',
             source_granule='CDIR-2024-04-25', source_line='20:1', position_basis='printed', printed_entry=None, entry_label=None),
        # Archived Senate standing committee has unprinted ranks (None) and Wayback capture date 2024-09-11
        dict(congress=118, session='2', system_code='SSFI00', bioguide_id='A000001', position=None, rank=None,
             party='Democrat', chamber='Senate', congress_basis='caller', edition_date=None,
             source_granule='https://web.archive.org/web/20240911154349id_/https://www.senate.gov/legislative/LIS_MEMBER/cvc_member_data.xml',
             source_line=None, position_basis=None, printed_entry=None, entry_label=None),
        dict(congress=118, session='2', system_code='SSFI00', bioguide_id='C000003', position='Chairman', rank=None,
             party='Democrat', chamber='Senate', congress_basis='caller', edition_date=None,
             source_granule='https://web.archive.org/web/20240911154349id_/https://www.senate.gov/legislative/LIS_MEMBER/cvc_member_data.xml',
             source_line=None, position_basis=None, printed_entry=None, entry_label=None),
        # Joint committee keeps both House (file) and Senate (caller) halves
        dict(congress=118, session='2', system_code='JSEC00', bioguide_id='B000002', position='Vice Chair', rank=1,
             party='Independent', chamber='House', committee_name='Joint Economic', congress_basis='file', edition_date=None,
             source_granule='https://web.archive.org/web/20240501161500id_/https://clerk.house.gov/xml/lists/MemberData.xml',
             source_line=None, position_basis=None, printed_entry=None, entry_label=None),
        dict(congress=118, session='2', system_code='JSEC00', bioguide_id='D000004', position='Chairman', rank=None,
             party='Republican', chamber='Senate', committee_name='Joint Economic', congress_basis='caller', edition_date=None,
             source_granule='https://web.archive.org/web/20240911154349id_/https://www.senate.gov/legislative/LIS_MEMBER/cvc_member_data.xml',
             source_line=None, position_basis=None, printed_entry=None, entry_label=None),
    ]
    directory = _build(tmp_path / 'mixed-118', assignments)
    rows = pq.read_table(directory / 'rosters.parquet').to_pylist()
    by_comm = {}
    for r in rows:
        by_comm.setdefault(r['system_code'], []).append(r)

    # hsru00 dropped stale directory-manual A000001 and dated D000004 from Wayback URL
    assert [(r['bioguide_id'], r['congress_basis'], r['edition_date'], r['rank']) for r in by_comm['hsru00']] == [
        ('D000004', 'file', datetime.date(2024, 5, 1), 1),
    ]
    # ssfi01 kept directory-manual snapshot
    assert [(r['bioguide_id'], r['congress_basis'], r['edition_date'], r['rank']) for r in by_comm['ssfi01']] == [
        ('C000003', 'directory-manual', datetime.date(2024, 4, 25), 1),
    ]
    # ssfi00 kept unprinted ranks as None and dated 2024-09-11
    assert [(r['bioguide_id'], r['title'], r['rank'], r['edition_date']) for r in by_comm['ssfi00']] == [
        ('A000001', None, None, datetime.date(2024, 9, 11)),
        ('C000003', 'Chairman', None, datetime.date(2024, 9, 11)),
    ]
    # jsec00 kept both House and Senate halves
    assert [(r['bioguide_id'], r['congress_basis'], r['edition_date'], r['rank']) for r in by_comm['jsec00']] == [
        ('B000002', 'file', datetime.date(2024, 5, 1), 1),
        ('D000004', 'caller', datetime.date(2024, 9, 11), None),
    ]

    schema = json.loads((ROOT / 'model/registries/release-schema.json').read_text())
    recipe = next(r for r in schema['recipes'] if r['id'] == 'committee_roster')
    with duckdb.connect() as connection:
        for table in recipe['requires']:
            connection.read_parquet(str(directory / (table + '.parquet'))).create_view(table)
        ssfi = connection.execute(recipe['sql'], ['ssfi00', 118]).fetchall()
        # Leadership (C000003 Chairman) sorts ahead of untitled member (A000001) when rank is NULL
        assert [(r[3], r[5], r[6]) for r in ssfi] == [('C000003', 'Chairman', None), ('A000001', None, None)]


def test_after_departure_respects_directory_basis_congress_end_and_mid_congress_gap(tmp_path):
    """P2-3 (ct-sh1i):
    1. Post-Congress directory edition_date (>= Jan 3 end of Congress) is not stamped after_departure.
    2. Wayback file/caller chamber snapshots are not stamped after_departure.
    3. A mid-Congress service gap (resigned early, re-elected later in the same Congress) IS stamped after_departure
       when the directory edition falls inside the gap."""
    from congress_api.retention.provenance import json_input, parquet_output, run_job
    from congress_api.lake.model_sql import model_steps
    from docspec_client.client import NativeDatasets
    from viewer_publication.archive_model import REGISTRIES, SPICY_SCHEMAS
    import os

    directory = tmp_path / 'gap-and-bounds'
    directory.mkdir()
    inputs = [
        json_input(directory, 'committee_codes',
                   json.loads((ROOT / 'model/registries/committee-codes.json').read_text()),
                   **REGISTRIES['committee_codes']),
        json_input(directory, 'spicy_member_terms', [
            # P000001 served full 115th (ended 2019-01-03), did not return in 116th; directory printed 2019-01-05
            dict(bioguide_id='P000001', term_type='sen', term_state='AZ', term_district=None,
                 term_party='Republican', term_start='2013-01-03', term_end='2019-01-03'),
            # W000002 resigned 2018-05-01, listed on a 2018-09-01 Wayback caller snapshot (not a Directory)
            dict(bioguide_id='W000002', term_type='sen', term_state='MS', term_district=None,
                 term_party='Republican', term_start='2013-01-03', term_end='2018-05-01'),
            # G000003 resigned 2017-06-01, won special election 2018-11-15; directory edition 2018-07-01 is in the gap!
            dict(bioguide_id='G000003', term_type='rep', term_state='PA', term_district=1,
                 term_party='Democrat', term_start='2017-01-03', term_end='2017-06-01'),
            dict(bioguide_id='G000003', term_type='rep', term_state='PA', term_district=1,
                 term_party='Democrat', term_start='2018-11-15', term_end='2019-01-03'),
        ], **SPICY_SCHEMAS['spicy_member_terms']),
        json_input(directory, 'spicy_committee_assignments', [
            dict(congress=115, session='2', system_code='SSAS00', bioguide_id='P000001', position='Member', rank=2,
                 party='Republican', chamber='Senate', congress_basis='directory', edition_date='2019-01-05',
                 source_granule='CDIR-2019-01-05', source_line='1:1', position_basis='printed', printed_entry=None, entry_label=None),
            dict(congress=115, session='2', system_code='SSFI00', bioguide_id='W000002', position='Member', rank=None,
                 party='Republican', chamber='Senate', congress_basis='caller', edition_date=None,
                 source_granule='https://web.archive.org/web/20180901120000id_/https://www.senate.gov/cvc.xml',
                 source_line=None, position_basis=None, printed_entry=None, entry_label=None),
            dict(congress=115, session='2', system_code='HSAG00', bioguide_id='G000003', position='Member', rank=5,
                 party='Democrat', chamber='House', congress_basis='directory', edition_date='2018-07-01',
                 source_granule='CDIR-2018-07-01', source_line='2:1', position_basis='printed', printed_entry=None, entry_label=None),
        ], **SPICY_SCHEMAS['spicy_committee_assignments']),
    ]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        run_job(directory, engine, inputs=inputs,
                outputs=[parquet_output(directory, 'rosters', 'SELECT * FROM entity_rosters', ['congress', 'system_code', 'rank', 'bioguide_id'])],
                steps=model_steps(['entity-rosters'], root=ROOT, materialize=True))
    got = {r['bioguide_id']: r['entry_label'] for r in pq.read_table(directory / 'rosters.parquet').to_pylist()}
    assert got['P000001'] is None
    assert got['W000002'] is None
    assert got['G000003'] == 'after_departure'
