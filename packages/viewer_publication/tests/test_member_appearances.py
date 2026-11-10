"""Sitting Members of Congress acting officially are Member appearances, not witnesses (ct-kw85), run from the
maintained member_terms, witness_member_facts and witness_members SQL and the witnesses export over hand rows.

Each row stands for a case the owner decided or the identity rule must refuse: a Member at a Member Day, a Senator
introducing a nominee, a sponsor before another chamber's committee, a former Member for an organization, a
non-Member with a sitting Member's name, a Member with no term dates, the hearing's own nominee, two sitting Members
of one name, and a nickname the members table does not hold.
"""
import os
from pathlib import Path

import pytest

from congress_api.retention.provenance import json_input, list_of, run_job
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model import WITNESSES_SQL

ROOT = Path(__file__).parents[3]

MEMBERS = [
    ('S000001', 'Ann', 'Sitting', 'rep', 'TX', '2019-01-03', '2027-01-03'),
    ('K000001', 'Jerry', 'Kansan', 'sen', 'KS', '2011-01-05', '2029-01-03'),
    ('B000001', 'Bill', 'Sponsor', 'rep', 'CA', '2015-01-06', '2027-01-03'),
    ('F000001', 'Fred', 'Former', 'rep', 'OH', '1995-01-04', '2011-01-03'),
    ('E000001', 'John', 'Edwards', 'sen', 'NC', '1999-01-06', '2005-01-03'),
    ('E000002', 'Thomas', 'Edwards', 'rep', 'TX', '1991-01-03', '2011-01-03'),
    ('N000001', 'Nora', 'Noterms', 'rep', 'WA', None, None),
    ('P000001', 'Mike', 'Pompeo', 'rep', 'KS', '2011-01-05', '2017-01-23'),
    ('B000002', 'Brian', 'Namesake', 'rep', 'CA', '2001-01-03', '2013-01-03'),
    ('R000001', 'Mike', 'Rogers', 'rep', 'AL', '2003-01-07', '2027-01-03'),
    ('R000002', 'Mike', 'Rogers', 'rep', 'MI', '2001-01-03', '2015-01-03'),
    ('M000001', 'Mary', 'Miller', 'rep', 'IL', '2021-01-03', '2027-01-03'),
    ('M000002', 'Mariannette', 'Miller-Meeks', 'rep', 'IA', '2021-01-03', '2027-01-03'),
]
MEETINGS = [
    (9001, '2023-03-01', "Members' Day Hearing"),
    (9002, '2019-05-01', 'Hearing on H.R. 1'),
    (9003, '2013-05-01', 'Nomination of Pat Judge to be United States District Judge for the District of Kansas'),
    (9004, '2020-06-01', 'S. 100, a bill to improve rivers'),
    (9005, '2020-06-02', 'Oversight of rivers'),
    (9006, '2001-05-01', 'Photonics'),
    (9007, '2022-03-01', 'Ports'),
    (9008, '2017-01-12', 'Nomination of Mike Pompeo to be Director of the Central Intelligence Agency'),
    (9009, '2006-11-14', 'Nominations of Hon. James H. Namesake and Hon. Dan Blair'),
    (9010, '2010-03-01', 'Rivers'),
    (9011, '2022-03-16', 'Farms'),
    (9012, '2004-06-08', 'Water'),
]
# witness_key: (source, event_id, package_id, name, position, organization, witness_type, bioguide_id, superseded_by)
ROWS = {
    'member-day': ('congress_gov', 9001, None, 'The Honorable Ann Sitting', 'Member of Congress', None, None, None, None),
    'senator-introducing': ('mods', 9003, None, 'Jerry Kansan',
                            'a U.S. Senator from the State of Kansas presenting Pat Judge a Nominee to be District Judge', None, None, None, None),
    'sponsor': ('senate_page', 9004, None, 'Bill Sponsor', 'a Representative in Congress from the State of California', None, None, None, None),
    'former-for-organization': ('mods', 9005, None, 'Fred Former', 'Former Representative in Congress from Ohio',
                                'President, Rivers Association', None, None, None),
    'non-member-namesake': ('mods', 9006, None, 'John Edwards', 'President and CEO', 'Photonic Sensor', None, None, None),
    'no-term-dates': ('congress_gov', 9007, None, 'The Honorable Nora Noterms', 'Member of Congress', None, None, None, None),
    'own-nomination': ('mods', 9008, None, 'Mike Pompeo', 'a Representative in Congress from the State of Kansas', None, None, None, None),
    'introducing-a-namesake': ('mods', 9009, None, 'Brian Namesake', 'a Representative in Congress from the State of California',
                               None, None, None, None),
    'two-sitting-rogers': ('congress_gov', 9010, None, 'The Honorable Mike Rogers', 'Member of Congress', None, None, None, None),
    'rogers-of-alabama': ('mods', None, 'CHRG-rivers', 'Mike Rogers', 'a Representative in Congress from Alabama', None, None, None, None),
    'given-name-decides': ('congress_gov', 9011, None, 'The Honorable Mary Miller', 'Member of Congress', None, None, None, None),
    'publisher-id': ('house_xml', 9002, None, 'The Honorable Ann Sitting', 'Member of Congress', None, 'Government - Federal', 'S000001', None),
    'same-appearance-in-print': ('mods', 9002, None, 'Ann Sitting', None, None, None, None, 'publisher-id'),
    'nickname-family-and-state': ('mods', 9012, None, 'Chet Edwards', 'a Representative in Congress from the State of Texas',
                                  None, None, None, None),
    'prepared-statement': ('mods', 9001, None, 'Ann Sitting', 'a Representative in Congress from Texas, prepared statement', None,
                           'member_statement', None, None),
    'outside-witness': ('congress_gov', 9001, None, 'Dr. Ada Lovelace', 'Professor', 'University', None, None, None),
}


@pytest.fixture(scope='module')
def result(tmp_path_factory):
    work = tmp_path_factory.mktemp('members')
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    inputs = [
        json_input(work, 'spicy_members', [dict(bioguide_id=b, name_first=f, name_last=l) for b, f, l, *_ in MEMBERS],
                   bioguide_id='Utf8', name_first='Utf8', name_last='Utf8'),
        json_input(work, 'spicy_member_terms', [dict(bioguide_id=b, term_type=t, term_state=s, term_district=None, term_party=None,
                                                     term_start=start, term_end=end) for b, _f, _l, t, s, start, end in MEMBERS],
                   bioguide_id='Utf8', term_type='Utf8', term_state='Utf8', term_district='Int32', term_party='Utf8',
                   term_start='Utf8', term_end='Utf8'),
        json_input(work, 'meetings_input', [dict(event_id=e, meeting_date=d, title=t) for e, d, t in MEETINGS],
                   event_id='Int64', meeting_date='Utf8', title='Utf8'),
        json_input(work, 'package_mods_facts', [dict(package_id='CHRG-rivers', held_dates=['2010-03-02'], title='Rivers')],
                   package_id='Utf8', held_dates=list_of('Utf8'), title='Utf8'),
        json_input(work, 'appearance_rows', [
            dict(witness_key=k, source=s, event_id=e, package_id=p, name=n, position=pos, organization=org, witness_type=t, bioguide_id=b)
            for k, (s, e, p, n, pos, org, t, b, _sup) in ROWS.items()],
            witness_key='Utf8', source='Utf8', event_id='Int64', package_id='Utf8', name='Utf8', position='Utf8',
            organization='Utf8', witness_type='Utf8', bioguide_id='Utf8'),
        json_input(work, 'precedence_rows', [dict(witness_key=k, superseded_by=v[8]) for k, v in ROWS.items() if v[8]],
                   witness_key='Utf8', superseded_by='Utf8'),
    ]
    sql = lambda name: (ROOT / 'model/sql' / (name + '.sql')).read_text()
    steps = [
        dict(name='meetings_resolved', sql='SELECT event_id,cast(meeting_date AS DATE) AS meeting_date,title FROM meetings_input', materialize=True),
        dict(name='appearance_records_resolved', sql="""SELECT witness_key,
            CASE WHEN event_id IS NOT NULL THEN 'meeting:'||cast(event_id AS VARCHAR) ELSE 'package:'||package_id END AS occasion,source,
            arrow_cast(decode(repeat('ab',32),'hex'),'FixedSizeBinary(32)') AS record_sha,source||':witness[1]' AS source_locator,
            repeat('c',64) AS context_key,event_id,package_id,cast(NULL AS VARCHAR) AS page_url,name,position,organization,
            cast(NULL AS VARCHAR) AS on_behalf_of,cast(NULL AS VARCHAR) AS location,cast(NULL AS VARCHAR) AS panel,
            cast(NULL AS SMALLINT) AS panel_order,cast(NULL AS SMALLINT) AS display_order,witness_type,cast(NULL AS BOOLEAN) AS testified,
            bioguide_id FROM appearance_rows""", materialize=True),
        dict(name='witness_precedence', sql='SELECT witness_key,superseded_by FROM precedence_rows', materialize=True),
        *[dict(name=n.replace('-', '_'), sql=sql(n), materialize=True) for n in ('member-terms', 'witness-member-facts', 'witness-member-candidates', 'witness-member-states', 'witness-members')],
    ]
    return run_job(work, engine, inputs=inputs, steps=steps, outputs=[], queries=[
        dict(name='members', sql='SELECT witness_key,outcome,matched_bioguide_id,match_basis FROM witness_members ORDER BY witness_key'),
        dict(name='witnesses', sql=f'SELECT * FROM ({WITNESSES_SQL}) ORDER BY witness_key'),
    ])


def decided(result):
    return {r['witness_key']: (r['outcome'], r['matched_bioguide_id'], r['match_basis']) for r in result['members']}


@pytest.mark.parametrize('key,expected', [
    ('member-day', ('member', 'S000001', 'name_chamber')),
    ('senator-introducing', ('member', 'K000001', 'name_state')),
    ('sponsor', ('member', 'B000001', 'name_state')),
    ('rogers-of-alabama', ('member', 'R000001', 'name_state')),       # a print's heldDate dates it
    ('given-name-decides', ('member', 'M000001', 'name_chamber')),    # Mary Miller, not Mariannette Miller-Meeks
    ('publisher-id', ('member', 'S000001', 'publisher_id')),
    ('same-appearance-in-print', ('member', 'S000001', 'group')),
    ('nickname-family-and-state', ('member', 'E000002', 'family_state')),  # Chet is Thomas Edwards of Texas
    ('introducing-a-namesake', ('member', 'B000002', 'name_state')),  # the title names James Namesake, not Brian
])
def test_sitting_members_acting_officially_are_member_appearances(result, key, expected):
    assert decided(result)[key] == expected


@pytest.mark.parametrize('key', ['former-for-organization', 'non-member-namesake', 'no-term-dates', 'prepared-statement', 'outside-witness'])
def test_these_stay_witnesses_or_statements(result, key):
    assert key not in decided(result)


def test_the_hearings_own_nominee_stays_a_witness(result):
    assert decided(result)['own-nomination'] == ('nominee', None, None)


def test_two_sitting_members_of_one_name_resolve_to_no_match(result):
    assert decided(result)['two-sitting-rogers'] == ('ambiguous', None, None)


def test_the_export_retypes_only_member_rows_and_never_writes_bioguide_id(result):
    rows = {r['witness_key']: r for r in result['witnesses']}
    assert set(rows) == set(ROWS)  # no row and no key moves
    members = {k for k, v in decided(result).items() if v[0] == 'member'}
    assert {k for k, r in rows.items() if r['witness_type'] == 'member_appearance'} == members
    assert rows['publisher-id']['bioguide_id'] == 'S000001' and rows['publisher-id']['matched_bioguide_id'] == 'S000001'
    assert rows['member-day']['bioguide_id'] is None and rows['member-day']['matched_bioguide_id'] == 'S000001'
    assert rows['prepared-statement']['witness_type'] == 'member_statement'
    assert rows['own-nomination']['witness_type'] is None and rows['own-nomination']['matched_bioguide_id'] is None
    assert rows['outside-witness']['match_basis'] is None
