"""Sitting Members of Congress acting officially are Member appearances, not witnesses (ct-kw85), run from the
maintained Member appearance steps and the witnesses export over hand rows.

Each row stands for a case the owner decided or the identity rule must refuse: a Member at a Member Day, a Senator
introducing a nominee, a sponsor before another chamber's committee, a former Member (the word alone, and the ended
term alone), a non-Member with a sitting Member's name, a Member with no term dates, the hearing's own nominee, two
sitting Members of one name, a nickname the members data holds, an abbreviated first name with a former namesake,
'Representative of' an organization, a state commission chair with an initial, a state legislature, 'Rep.' alone,
a district code, a name with nothing else, a seat's holder named only by family name (at large, and a district),
a seat stated beside a state legislature, a bare initial in the members data (C. Cox) and in the row's own
reading (JD Vance), an initial another sitting Member shares, 'ranking House Member', 'Representatives in
Congress', a name alone at a Member Day hearing and at a Former Members Day hearing, a co-chair of a listed
congressional commission, a namesake at a commission the list does not hold, and committee members' own opening
statements (on the hearing's committee, on its parent, on a print's committee) beside an opening statement by a
Member off the committee, a committee member's testimony and an opening statement before the rosters begin.
"""
import json
import os
from pathlib import Path

import pytest

from congress_api.retention.provenance import json_input, list_of, run_job
from docspec_client.client import NativeDatasets
from congress_api.retention.provenance import struct
from viewer_publication.archive_model import REGISTRIES, SPICY_SCHEMAS, WITNESSES_SQL

ROOT = Path(__file__).parents[3]
STEPS = ('member-terms', 'witness-member-facts', 'witness-member-names', 'witness-member-candidates', 'witness-member-rows',
         'witness-member-mentions', 'witness-member-seats', 'witness-member-tiers', 'witness-member-decisions', 'entity-rosters',
         'witness-member-committees', 'witness-members')
STEP_NAMES = {'entity-rosters': 'roster_seats'}

# bioguide, first, last, nickname, term type, state, start, end
MEMBERS = [
    ('S000001', 'Ann', 'Sitting', None, 'rep', 'TX', '2019-01-03', '2027-01-03'),
    ('K000001', 'Jerry', 'Kansan', None, 'sen', 'KS', '2011-01-05', '2029-01-03'),
    ('B000001', 'Bill', 'Sponsor', None, 'rep', 'CA', '2015-01-06', '2027-01-03'),
    ('F000001', 'Fred', 'Former', None, 'rep', 'OH', '1995-01-04', '2011-01-03'),
    ('E000001', 'John', 'Edwards', None, 'sen', 'NC', '1999-01-06', '2005-01-03'),
    ('E000002', 'Thomas', 'Edwards', 'Chet', 'rep', 'TX', '1991-01-03', '2011-01-03'),
    ('N000001', 'Nora', 'Noterms', None, 'rep', 'WA', None, None),
    ('P000001', 'Mike', 'Pompeo', None, 'rep', 'KS', '2011-01-05', '2017-01-23'),
    ('B000002', 'Brian', 'Namesake', None, 'rep', 'CA', '2001-01-03', '2013-01-03'),
    ('R000001', 'Mike', 'Rogers', None, 'rep', 'AL', '2003-01-07', '2027-01-03'),
    ('R000002', 'Mike', 'Rogers', None, 'rep', 'MI', '2001-01-03', '2015-01-03'),
    ('M000001', 'Mary', 'Miller', None, 'rep', 'IL', '2021-01-03', '2027-01-03'),
    ('M000002', 'Mariannette', 'Miller-Meeks', None, 'rep', 'IA', '2021-01-03', '2027-01-03'),
    ('C000002', 'William', 'Clay', 'Bill', 'rep', 'MO', '1969-01-03', '2001-01-03'),   # the father
    ('C000003', 'Wm.', 'Clay', None, 'rep', 'MO', '2001-01-03', '2021-01-03'),         # the son, abbreviated
    ('S000003', 'Victor', 'Snyder', 'Vic', 'rep', 'AR', '1997-01-07', '2011-01-03'),
    ('J000003', 'Ron', 'Johnson', None, 'sen', 'WI', '2011-01-05', '2029-01-03'),
    ('N000002', 'Mike', 'Noel', None, 'rep', 'UT', '2015-01-06', '2027-01-03'),
    ('D000003', 'Rodney', 'Davis', None, 'rep', 'IL', '2013-01-03', '2023-01-03'),
    ('H000003', 'Debra', 'Haaland', 'Deb', 'rep', 'NM', '2019-01-03', '2021-03-16'),
    ('T000003', 'Glenn', 'Thompson', None, 'rep', 'PA', '2009-01-06', '2027-01-03'),
    ('P000003', 'Earl', 'Pomeroy', None, 'rep', 'ND', '1993-01-05', '2011-01-03'),
    ('C000004', 'J.', 'Correa', None, 'rep', 'CA', '2017-01-03', '2027-01-03'),
    ('C000005', 'C.', 'Cox', None, 'rep', 'CA', '1989-01-03', '2005-08-02'),
    ('V000005', 'James David', 'Vance', 'J.D.', 'sen', 'OH', '2023-01-03', '2029-01-03'),
    ('W000005', 'J.', 'Walker', None, 'rep', 'NC', '2001-01-03', '2011-01-03'),
    ('W000006', 'James', 'Walker', None, 'rep', 'NC', '2001-01-03', '2011-01-03'),
    ('W000007', 'Timothy', 'Walz', None, 'rep', 'MN', '2007-01-04', '2019-01-03'),
    ('S000005', 'F.', 'Sensenbrenner', None, 'rep', 'WI', '1979-01-15', '2021-01-03'),
    ('K000005', 'Angus', 'King', None, 'sen', 'ME', '2013-01-03', '2025-01-03'),
    ('W000008', 'Joe', 'Wilson', None, 'rep', 'SC', '2001-12-18', '2027-01-03'),
    ('W000009', 'Jackie', 'Walorski', None, 'rep', 'IN', '2013-01-03', '2019-01-03'),
    ('P000005', 'Collin', 'Peterson', None, 'rep', 'MN', '1991-01-03', '2021-01-03'),
    ('S000007', 'Austin', 'Scott', None, 'rep', 'GA', '2011-01-05', '2027-01-03'),
    ('K000009', 'Marcy', 'Kaptur', None, 'rep', 'OH', '1983-01-03', '2027-01-03'),
]
# Pinned roster seats (Congress, committee, Member): Peterson sits on the full committee only, Scott on a subcommittee too.
SEATS = [(114, 'hsag00', 'W000009'), (114, 'hsag00', 'P000005'), (114, 'hsag00', 'S000007'), (114, 'hsag22', 'S000007'),
         (115, 'hsag00', 'P000005'), (116, 'hsap00', 'K000009')]
# What prints' own MODS state (package_mods_facts): held dates, committee codes, committee members.
PRINTS = {'CHRG-rivers': (['2010-03-02'], [], []), 'CHRG-114hhrg99999': (['2016-02-01'], [], []),
          'CHRG-115hhrg88888': (['2017-02-28'], ['hsag00'], []),
          'CHRG-110hhrg77777': (['2008-03-01'], ['hsag00'], ['P000005']), 'CHRG-110hhrg77776': (['2008-03-02'], ['hsag00'], ['W000009'])}
COMMITTEES = {9030: ['hsag00'], 9031: ['hsag22'], 9032: ['hsif00'], 9033: ['hsag00'], 9034: ['hsag00']}
DISTRICTS = {'P000003': 0, 'C000004': 46}  # House seats the seat rule reads; 0 is at large
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
    (9013, '2019-09-11', 'Ferguson'),
    (9014, '2000-03-16', 'Korea'),
    (9015, '2011-04-13', 'Taxes'),
    (9016, '2018-05-09', 'Lands'),
    (9017, '2020-03-10', 'Member Day'),
    (9018, '2019-07-16', 'H.R. 2414'),
    (9019, '2023-03-01', 'Committee Funding'),
    (9020, '2006-05-10', 'Farm policy'),
    (9021, '2019-04-30', 'Veterans'),
    (9022, '2001-06-28', 'Trade with Russia'),
    (9023, '2023-03-09', 'Rail safety'),
    (9024, '2016-01-12', 'Human rights in China'),
    (9025, '2006-06-14', 'Communications'),
    (9026, '2005-03-01', 'Textiles'),
    (9027, '2019-05-01', 'Former Members Day Hearing: Speaking from Experience'),
    (9028, '2020-02-11', 'Cybersecurity'),
    (9029, '2008-04-15', 'Veterans health'),
    (9030, '2015-03-01', 'Nutrition assistance'),
    (9031, '2015-04-01', 'Subcommittee on commodities'),
    (9032, '2019-06-01', 'Member Day Hearing'),
    (9033, '2015-05-01', 'Farm credit'),
    (9034, '2008-05-01', 'Farm bill'),
]
# witness_key: (source, event_id, package_id, name, position, organization, witness_type, bioguide_id, superseded_by)
ROWS = {
    'member-day': ('congress_gov', 9001, None, 'The Honorable Ann Sitting', 'Member of Congress', None, None, None, None),
    'senator-introducing': ('mods', 9003, None, 'Jerry Kansan',
                            'a U.S. Senator from the State of Kansas presenting Pat Judge a Nominee to be District Judge', None, None, None, None),
    'sponsor': ('senate_page', 9004, None, 'Bill Sponsor', 'a Representative in Congress from the State of California', None, None, None, None),
    # Each guard alone: the word 'former' beside a sitting term, and an ended term with no such word.
    'says-former-while-sitting': ('mods', 9005, None, 'Ann Sitting', 'former Member of Congress', 'Rivers Association', None, None, None),
    'term-ended-without-the-word': ('mods', 9005, None, 'Fred Former', 'a Representative in Congress from Ohio', None, None, None, None),
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
    'nickname-from-members-data': ('mods', 9012, None, 'Chet Edwards', 'a Representative in Congress from the State of Texas',
                                   None, None, None, None),
    'abbreviated-son-not-father': ('mods', 9013, None, 'William Lacy Clay', 'a Representative in Congress from the State of Missouri',
                                   None, None, None, None),
    'representative-of-an-organization': ('mods', 9014, None, 'Vic Snyder', 'Representative of Asia Foundation/Korea', None, None, None, None),
    'initial-and-state-commission': ('mods', 9015, None, 'R. Bruce Johnson', 'Chairman, Utah State Tax Commission', None, None, None, None),
    'state-legislature-by-name': ('mods', 9016, None, 'Mike Noel', 'Representative', 'Utah House of Representatives', None, None, None),
    'rep-alone': ('congress_gov', 9017, None, 'Rodney Davis', 'Rep.', None, None, None, None),
    'district-code': ('house_xml', 9018, None, 'The Honorable Debra Haaland', '(NM-01)', None, None, None, None),
    'name-and-nothing-else': ('congress_gov', 9019, None, 'The Honorable Glenn Thompson', None, None, None, None, None),
    'prepared-statement': ('mods', 9001, None, 'Ann Sitting', 'a Representative in Congress from Texas, prepared statement', None,
                           'member_statement', None, None),
    'outside-witness': ('congress_gov', 9001, None, 'Dr. Ada Lovelace', 'Professor', 'University', None, None, None),
    'seat-at-large': ('mods', 9020, None, 'Page Pomeroy', 'The Honorable Earl (ND-At Large)', 'Congressman, U.S. House of Representatives',
                      None, None, None),
    'seat-district': ('mods', 9021, None, 'Lou Correa', 'U.S. House of Representatives', '46th District; California', None, None, None),
    'seat-in-a-state-legislature': ('mods', 9021, None, 'Juan Correa', 'Member, 46th District', 'California Assembly', None, None, None),
    'initial-in-members-data': ('mods', 9022, None, 'Christopher Cox', 'a Representative in Congress from the State of California',
                                None, None, None, None),
    'initial-in-the-row': ('senate_page', 9023, None, 'JD Vance', 'United States Senator', 'The State of Ohio', None, None, None),
    'initial-another-member-shares': ('mods', 9026, None, 'John Walker', 'a Representative in Congress from North Carolina', None,
                                      None, None, None),
    'ranking-house-member': ('mods', 9024, None, 'Timothy J. Walz', 'ranking House Member', 'Congressional-Executive Commission on China',
                             None, None, None),
    'representatives-in-congress': ('mods', 9025, None, 'F. James Sensenbrenner', 'Jr.',
                                    'a Representatives in Congress from the State of Wisconsin', None, None, None),
    'member-day-name-alone': ('house_xml', 9001, None, 'The Honorable Ann Sitting', None, None, None, None, None),
    'former-members-day-name-alone': ('house_xml', 9027, None, 'The Honorable Ann Sitting', None, None, None, None, None),
    'listed-commission': ('mods', 9028, None, 'Angus S. King Jr.', 'Co-Chair', 'Cyberspace Solarium Commission', None, None, None),
    'commission-not-listed': ('mods', 9029, None, 'Joseph L. Wilson', 'Deputy Director',
                              'Veterans Affairs and Rehabilitation Commission, American Legion', None, None, None),
    'committee-opening': ('mods', 9030, None, 'Jackie Walorski', 'a Representative in Congress from Indiana', 'opening statement',
                          None, None, None),
    'parent-committee-opening': ('mods', 9031, None, 'Collin C. Peterson', 'a Representative in Congress from Minnesota',
                                 'opening statement', None, None, None),
    'print-committee-opening': ('mods', None, 'CHRG-114hhrg99999', 'Austin Scott', 'a Representative in Congress from Georgia',
                                'opening statement', None, None, None),
    'opening-off-the-committee': ('mods', 9032, None, 'Marcy Kaptur', 'a Representative in Congress from the State of Ohio',
                                  'opening statement', None, None, None),
    'committee-member-testifies': ('mods', 9033, None, 'Jackie Walorski', 'a Representative in Congress from Indiana', None,
                                   None, None, None),
    'opening-before-the-rosters': ('mods', 9034, None, 'Collin C. Peterson', 'a Representative in Congress from Minnesota',
                                   'opening statement', None, None, None),
    'print-code-opening': ('mods', None, 'CHRG-115hhrg88888', 'Collin C. Peterson', 'a Representative in Congress from Minnesota',
                           'opening statement', None, None, None),
    'print-list-opening': ('mods', None, 'CHRG-110hhrg77777', 'Collin C. Peterson', 'a Representative in Congress from Minnesota',
                           'opening statement', None, None, None),
    'print-list-omits-the-member': ('mods', None, 'CHRG-110hhrg77776', 'Collin C. Peterson',
                                    'a Representative in Congress from Minnesota', 'opening statementt', None, None, None),
}


@pytest.fixture(scope='module')
def result(tmp_path_factory):
    work = tmp_path_factory.mktemp('members')
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    inputs = [
        json_input(work, 'spicy_members', [dict(bioguide_id=b, name_first=f, name_last=l, name_nickname=n) for b, f, l, n, *_ in MEMBERS],
                   bioguide_id='Utf8', name_first='Utf8', name_last='Utf8', name_nickname='Utf8'),
        json_input(work, 'spicy_member_terms', [dict(bioguide_id=b, term_type=t, term_state=s, term_district=DISTRICTS.get(b), term_party=None,
                                                     term_start=start, term_end=end) for b, _f, _l, _n, t, s, start, end in MEMBERS],
                   bioguide_id='Utf8', term_type='Utf8', term_state='Utf8', term_district='Int32', term_party='Utf8',
                   term_start='Utf8', term_end='Utf8'),
        json_input(work, 'meetings_input', [dict(event_id=e, meeting_date=d, title=t,
                                                 committees=[dict(system_code=c, role=None) for c in COMMITTEES.get(e, [])])
                                            for e, d, t in MEETINGS],
                   event_id='Int64', meeting_date='Utf8', title='Utf8', committees=list_of(struct(system_code='Utf8', role='Utf8'))),
        json_input(work, 'spicy_committee_assignments', [
            {**{k: None for k in SPICY_SCHEMAS['spicy_committee_assignments']}, 'congress': c, 'system_code': code, 'bioguide_id': b,
             'chamber': 'house'} for c, code, b in SEATS], **SPICY_SCHEMAS['spicy_committee_assignments']),
        json_input(work, 'committee_codes', json.loads((ROOT / 'model/registries/committee-codes.json').read_text()),
                   **REGISTRIES['committee_codes']),
        json_input(work, 'document_packages', [dict(component='print-1', package_id='CHRG-114hhrg99999')],
                   component='Utf8', package_id='Utf8'),
        json_input(work, 'document_metadata', [dict(component='print-1', committee_keys=['hsag00'], meeting_keys=[])],
                   component='Utf8', committee_keys=list_of('Utf8'), meeting_keys=list_of('Utf8')),
        json_input(work, 'congressional_commissions',
                   json.loads((ROOT / 'model/registries/congressional-commissions.json').read_text()),
                   **REGISTRIES['congressional_commissions']),
        json_input(work, 'package_mods_facts', [dict(package_id=p, held_dates=h, title=p, committees=c, committee_members=m)
                                                for p, (h, c, m) in PRINTS.items()],
                   package_id='Utf8', held_dates=list_of('Utf8'), title='Utf8', committees=list_of('Utf8'),
                   committee_members=list_of('Utf8')),
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
        dict(name='meetings_resolved', sql='SELECT event_id,cast(meeting_date AS DATE) AS meeting_date,title,committees FROM meetings_input',
             materialize=True),
        dict(name='appearance_records_resolved', sql="""SELECT witness_key,
            CASE WHEN event_id IS NOT NULL THEN 'meeting:'||cast(event_id AS VARCHAR) ELSE 'package:'||package_id END AS occasion,source,
            arrow_cast(decode(repeat('ab',32),'hex'),'FixedSizeBinary(32)') AS record_sha,source||':witness[1]' AS source_locator,
            repeat('c',64) AS context_key,event_id,package_id,cast(NULL AS VARCHAR) AS page_url,name,position,organization,
            cast(NULL AS VARCHAR) AS on_behalf_of,cast(NULL AS VARCHAR) AS location,cast(NULL AS VARCHAR) AS panel,
            cast(NULL AS SMALLINT) AS panel_order,cast(NULL AS SMALLINT) AS display_order,witness_type,cast(NULL AS BOOLEAN) AS testified,
            bioguide_id FROM appearance_rows""", materialize=True),
        dict(name='witness_precedence', sql='SELECT witness_key,superseded_by FROM precedence_rows', materialize=True),
        *[dict(name=STEP_NAMES.get(n, n.replace('-', '_')), sql=sql(n), materialize=True) for n in STEPS],
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
    ('nickname-from-members-data', ('member', 'E000002', 'name_state')),  # Chet is Thomas Edwards's own nickname
    ('abbreviated-son-not-father', ('member', 'C000003', 'name_state')),   # the father's ended term does not block
    ('rep-alone', ('member', 'D000003', 'name_chamber')),
    ('district-code', ('member', 'H000003', 'name_state')),
    ('introducing-a-namesake', ('member', 'B000002', 'name_state')),  # the title names James Namesake, not Brian
    ('seat-at-large', ('member', 'P000003', 'seat')),                 # a garbled heading: no first name to agree
    ('seat-district', ('member', 'C000004', 'seat')),                 # J. Luis Correa: the members data has no 'Luis'
    ('initial-in-members-data', ('member', 'C000005', 'initial')),
    ('initial-in-the-row', ('member', 'V000005', 'initial')),         # 'JD' is a first name here, not a credential
    ('ranking-house-member', ('member', 'W000007', 'name_role')),
    ('representatives-in-congress', ('member', 'S000005', 'name_state')),
    ('member-day-name-alone', ('member', 'S000001', 'member_day')),
    ('listed-commission', ('member', 'K000005', 'name_role')),       # the registry lists the Solarium Commission
    ('opening-off-the-committee', ('member', 'K000009', 'name_state')),   # an Appropriations member at Energy and Commerce
    ('committee-member-testifies', ('member', 'W000009', 'name_state')),  # no opening statement
    ('opening-before-the-rosters', ('member', 'P000005', 'name_state')),  # no rosters and no print member list
    ('print-list-omits-the-member', ('member', 'P000005', 'name_state')),  # the print's own list does not hold him
])
def test_sitting_members_acting_officially_are_member_appearances(result, key, expected):
    assert decided(result)[key] == expected


@pytest.mark.parametrize('key', ['says-former-while-sitting', 'term-ended-without-the-word', 'non-member-namesake', 'no-term-dates',
                                 'prepared-statement', 'outside-witness', 'representative-of-an-organization',
                                 'initial-and-state-commission', 'state-legislature-by-name', 'name-and-nothing-else',
                                 'seat-in-a-state-legislature', 'former-members-day-name-alone', 'commission-not-listed'])
def test_these_stay_witnesses_or_statements(result, key):
    assert key not in decided(result)


@pytest.mark.parametrize('key,expected', [
    ('committee-opening', ('statement', 'W000009', 'name_state')),
    ('parent-committee-opening', ('statement', 'P000005', 'name_state')),  # a full committee member at its subcommittee
    ('print-committee-opening', ('statement', 'S000007', 'name_state')),   # the print's own document names the committee
    ('print-code-opening', ('statement', 'P000005', 'name_state')),       # only the print's own MODS committee code does
    ('print-list-opening', ('statement', 'P000005', 'name_state')),       # before the rosters: the print's member list
])
def test_a_committee_members_own_opening_statement_is_a_member_statement(result, key, expected):
    assert decided(result)[key] == expected
    row = next(r for r in result['witnesses'] if r['witness_key'] == key)
    assert (row['witness_type'], row['matched_bioguide_id']) == ('member_statement', expected[1])


def test_the_hearings_own_nominee_stays_a_witness(result):
    assert decided(result)['own-nomination'] == ('nominee', None, None)


def test_two_sitting_members_of_one_name_resolve_to_no_match(result):
    assert decided(result)['two-sitting-rogers'] == ('ambiguous', None, None)
    # J. Walker and James Walker sit for North Carolina: an initial singles out no one.
    assert decided(result)['initial-another-member-shares'] == ('ambiguous', None, None)


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
