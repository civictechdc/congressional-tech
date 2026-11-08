"""Bounded readiness checks for ss-ehci input; these seats are synthetic, not source history."""
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

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
    directory.mkdir()
    outputs = [parquet_output(directory, name, 'SELECT * FROM ' + name,
                              ['congress', 'system_code', 'bioguide_id'] if name == 'rosters' else
                              ['bioguide_id'] if name == 'members' else ['system_code'])
               for name in ('rosters', 'members', 'committees')]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        run_job(directory, engine, inputs=_inputs(directory, assignments), outputs=outputs,
                steps=[dict(name=name, sql=(ROOT / 'model/sql' / ('entity-' + name + '.sql')).read_text(),
                            materialize=True) for name in ('rosters', 'members', 'committees')])
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
