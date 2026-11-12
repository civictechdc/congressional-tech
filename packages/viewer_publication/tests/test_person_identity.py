"""Witness identity slice 2 (ct-ha10): people, person_aliases, person_key on witnesses, Gate 1 & export refusal."""
from datetime import date
import hashlib
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets

from archive_job_fixture import spicy_input
from test_witness_identity import _cg_json, _pdf_bytes, _stage_raw


def _spicy_people_fixture():
    return spicy_input(
        spicy_committees=[dict(
            system_code='hsif00', name='Energy and Commerce', chamber='house', committee_type='standing',
            parent_system_code=None, website_url='https://energycommerce.house.gov', is_current=True, history=[],
        )],
        spicy_members=[
            dict(
                bioguide_id='A000370', name_first='Alma', name_last='Adams', name_nickname=None,
                lis_id=None, opensecrets_id=None, govtrack_id=None, icpsr_id=None, wikidata_id=None, fec_ids=[],
            ),
            dict(
                bioguide_id='C001075', name_first='Bill', name_last='Cassidy', name_nickname=None,
                lis_id=None, opensecrets_id=None, govtrack_id=None, icpsr_id=None, wikidata_id=None, fec_ids=[],
            ),
        ],
        spicy_member_terms=[
            dict(
                bioguide_id='A000370', term_type='rep', term_state='NC', term_district=12,
                term_party='Democrat', term_start='2023-01-03', term_end='2025-01-03',
            ),
            dict(
                bioguide_id='C001075', term_type='sen', term_state='LA', term_district=None,
                term_party='Republican', term_start='2021-01-03', term_end='2027-01-03',
            ),
        ],
    )


def _mrow(eid, *, updated='2026-10-20T00:00:00Z', date_str='2024-05-01', title=None, jackets=()):
    t = title or f'Hearing {eid}'
    return dict(
        event_id=str(eid), chamber='house', congress=118, session=2, updated=updated, title=t,
        meeting_date=date_str, meeting_type='HHRG', status='Scheduled', sittings=[],
        committees=[dict(system_code='hsif00', name='Energy and Commerce', chamber='house', role='host')],
        subject_keys=[], transcript_jackets=list(jackets), videos=[],
        document_urls=[], document_references=[],
        collection_states=dict(
            sittings='present', committees='present', subject_keys='empty',
            transcript_jackets='present' if jackets else 'empty', videos='empty', document_urls='empty',
        ),
        access='open', access_basis='default', not_held=False, title_key=t.lower(), reschedule_candidate=False,
    )


def _expected_person_v1(name_key: str, org_key: str, mid: str = '', suf: str = '') -> str:
    payload = json.dumps(['person-v1', name_key, org_key, mid, suf], separators=(',', ':')).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def _expected_singleton_v1(witness_key: str) -> str:
    payload = json.dumps(['person-singleton-v1', witness_key], separators=(',', ':')).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def test_person_grouping_tiers_guards_singletons_and_superseded_inheritance(tmp_path):
    """ct-ha10: Members by Bioguide (publisher & matched_bioguide_id), non-Members by exact normalized
    name + FULL normalized organization with middle/suffix guards, singletons on empty org or unusable name,
    superseded rows inheriting target person_key, and record entries / unmatched member_appearance NULL."""
    from viewer_publication.archive_model import build_release

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    sha = lambda b: hashlib.sha256(b).hexdigest()

    cg_901 = _cg_json(901, '2026-10-20T00:00:00Z', 'h901')
    cg_902 = _cg_json(902, '2026-10-20T00:00:00Z', 'h902')
    cg_903 = _cg_json(903, '2026-10-20T00:00:00Z', 'h903')
    mods_903 = b'<mods><titleInfo><title>Hearing 903 Print</title></titleInfo></mods>'
    mods_111 = b'<mods><titleInfo><title>111th Print With Placeholder Date</title></titleInfo></mods>'
    doc_901 = _pdf_bytes('testimony-901')

    captures = [
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/901?format=json', data=cg_901, format='json', family='congress/meetings'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/902?format=json', data=cg_902, format='json', family='congress/meetings'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/903?format=json', data=cg_903, format='json', family='congress/meetings'),
        dict(url='https://www.govinfo.gov/metadata/pkg/CHRG-118hhrg90301/mods.xml', data=mods_903, format='xml', family='govinfo/mods'),
        dict(url='https://www.govinfo.gov/metadata/pkg/CHRG-111shrg57186/mods.xml', data=mods_111, format='xml', family='govinfo/mods'),
        dict(url='https://docs.house.gov/meetings/IF/IF00/20240501/901/HHRG-118-IF00-Wstate-OReillySmithJ-20240501.pdf', data=doc_901, format='pdf', suffix='.pdf'),
    ]

    meetings = [
        dict(record_sha=sha(cg_901), source='congress_gov', meetings=[_mrow(901, date_str='2024-05-01')]),
        dict(record_sha=sha(cg_902), source='congress_gov', meetings=[_mrow(902, date_str='2024-06-15')]),
        dict(record_sha=sha(cg_903), source='congress_gov', meetings=[_mrow(903, date_str='2024-07-10', jackets=['90301'])]),
    ]

    appearances = [
        dict(record_sha=sha(cg_901), source='congress_gov', event_id=901, collection_state='present', appearances=[
            # 1. Publisher Bioguide Member -> person_key = 'A000370'
            dict(source_locator='cg:1', bioguide_id='A000370', name_key='alma adams', name='Rep. Alma S. Adams', given='Alma', family='Adams', position='Representative', organization='U.S. House of Representatives', display_order=1),
            # 2. Matched Bioguide Member (ct-kw85: U.S. Senator Bill Cassidy, M.D.) -> person_key = 'C001075'
            dict(source_locator='cg:2', name_key='bill cassidy', name='Hon. Bill Cassidy, M.D.', given='Bill', family='Cassidy', position='U.S. Senator from Louisiana', organization='United States Senate', display_order=2),
            # 3. Exact normalized name + org with accents, apostrophe, particle, honorific, parenthetical, leading "The"
            dict(source_locator='cg:3', name_key='jose de oreilly', name="Dr. José De O'Reilly (Ret.), Ph.D.", given='Jose', family="De O'Reilly", position='Senior Fellow', organization='The Brookings Institution', display_order=3,
                 document_urls=['https://docs.house.gov/meetings/IF/IF00/20240501/901/HHRG-118-IF00-Wstate-OReillySmithJ-20240501.pdf']),
            # 4. Surname-first inversion: "Williams, James A." at RAND Corporation
            dict(source_locator='cg:4', name_key='james williams', name='Williams, James A.', given='James', family='Williams', position='Analyst', organization='RAND Corporation', display_order=4),
            # 5. Same name at sub-unit A (must NOT merge with sub-unit B on 902!)
            dict(source_locator='cg:5', name_key='john miller', name='John Miller', given='John', family='Miller', position='Director', organization='Department of Energy, Office of Science', display_order=5),
            # 6. Middle-initial guard (single stated initial 'm' merges with unstated on 902)
            dict(source_locator='cg:6', name_key='elena vance', name='Elena M. Vance', given='Elena', family='Vance', position='Lead', organization='Grid Lab', display_order=6),
            # 7. Middle-initial guard (competing initials 'a' vs 'b' vs unstated -> 3 distinct people!)
            dict(source_locator='cg:7', name_key='robert a cho', name='Robert A. Cho', given='Robert', family='Cho', position='Counsel', organization='Civic Policy Center', display_order=7),
            dict(source_locator='cg:8', name_key='robert b cho', name='Robert B. Cho', given='Robert', family='Cho', position='Counsel', organization='Civic Policy Center', display_order=8),
            # 8. Suffix guard (single stated 'jr' merges with unstated on 902)
            dict(source_locator='cg:9', name_key='henry alvarez jr', name='Henry Alvarez, Jr.', given='Henry', family='Alvarez', position='Chair', organization='Port Authority', display_order=9),
            # 9. Suffix guard (competing 'jr' vs 'sr' vs unstated -> 3 distinct people!)
            dict(source_locator='cg:10', name_key='thomas bell jr', name='Thomas Bell, Jr.', given='Thomas', family='Bell', position='Partner', organization='Harbor Group', display_order=10),
            # 10. Empty organization -> singleton (never merges even with identical name on 902!)
            dict(source_locator='cg:11', name_key='dana scully', name='Dana Scully', given='Dana', family='Scully', position='Physician', organization=None, display_order=11),
            # 11. Unusable name (trailing single-letter surname initial "John S.") -> singleton!
            dict(source_locator='cg:12', name_key='john s', name='John S.', given='John', family='S', position='Resident', organization='Neighborhood Assn', display_order=12),
            # 12. Record entry -> person_key IS NULL!
            dict(source_locator='cg:13', name_key='letter writer', name='Letter Writer', given='Letter', family='Writer', witness_type='statement_for_record', organization='Civic League', display_order=13),
            # 13. Surnames matching prefix titles ('Judge', 'Vice', 'Major') must NOT be stripped at end of name!
            dict(source_locator='cg:14', name_key='kathryn judge', name='Ms. Kathryn Judge', given='Kathryn', family='Judge', position='Professor', organization='Columbia Law School', display_order=14),
            dict(source_locator='cg:15', name_key='charles a vice', name='Vice Admiral Charles A. Vice, Jr.', given='Charles', family='Vice', position='Commissioner', organization='Kentucky Department of Financial Institutions', display_order=15),
            dict(source_locator='cg:16', name_key='matthew major', name='Dr. Matthew Major, Ph.D.', given='Matthew', family='Major', position='Researcher', organization='Northwestern University', display_order=16),
            # 14. Placeholder / bare-suffix orgs ('WITNESS', 'Inc.') stay singleton!
            dict(source_locator='cg:17', name_key='sam gregory', name='Mr. Sam Gregory', given='Sam', family='Gregory', position='Director', organization='WITNESS', display_order=17),
            dict(source_locator='cg:18', name_key='bert ely', name='Bert Ely', given='Bert', family='Ely', position='Consultant', organization='Inc.', display_order=18),
        ]),
        dict(record_sha=sha(cg_902), source='congress_gov', event_id=902, collection_state='present', appearances=[
            # Publisher Bioguide again -> same 'A000370'
            dict(source_locator='cg:1', bioguide_id='A000370', name_key='alma adams', name='Alma Adams', given='Alma', family='Adams', position='Member', organization=None, display_order=1),
            # Matches #3: surname-first with particle & folded accent + lowercase org without "The"
            dict(source_locator='cg:2', name_key='jose de oreilly', name="De O'Reilly, Jose", given='Jose', family="De O'Reilly", position='Director', organization='brookings institution.', display_order=2),
            # Matches #4: normal order "James A. Williams" at RAND Corporation
            dict(source_locator='cg:3', name_key='james williams', name='James A. Williams', given='James', family='Williams', position='Senior Analyst', organization='RAND Corporation', display_order=3),
            # Sub-unit B -> MUST STAY DISTINCT from sub-unit A!
            dict(source_locator='cg:4', name_key='john miller', name='John Miller', given='John', family='Miller', position='Director', organization='Department of Energy, Loan Programs Office', display_order=4),
            # Matches #6 (unstated middle initial joins single stated 'm')
            dict(source_locator='cg:5', name_key='elena vance', name='Elena Vance', given='Elena', family='Vance', position='Lead', organization='Grid Lab', display_order=5),
            # Competing middle initial #7: unstated Robert Cho stays apart from BOTH A and B!
            dict(source_locator='cg:6', name_key='robert cho', name='Robert Cho', given='Robert', family='Cho', position='Counsel', organization='Civic Policy Center', display_order=6),
            # Matches #8 (unstated suffix joins single stated 'jr')
            dict(source_locator='cg:7', name_key='henry alvarez', name='Henry Alvarez', given='Henry', family='Alvarez', position='Chair', organization='Port Authority', display_order=7),
            # Competing suffix #9: Sr. and unstated stay apart from Jr. and each other!
            dict(source_locator='cg:8', name_key='thomas bell sr', name='Thomas Bell, Sr.', given='Thomas', family='Bell', position='Partner', organization='Harbor Group', display_order=8),
            dict(source_locator='cg:9', name_key='thomas bell', name='Thomas Bell', given='Thomas', family='Bell', position='Partner', organization='Harbor Group', display_order=9),
            # Empty org again -> distinct singleton!
            dict(source_locator='cg:10', name_key='dana scully', name='Dana Scully', given='Dana', family='Scully', position='Physician', organization='   ', display_order=10),
            # Unusable name again -> distinct singleton!
            dict(source_locator='cg:11', name_key='john s', name='John S.', given='John', family='S', position='Resident', organization='Neighborhood Assn', display_order=11),
            # Unmatched member_appearance (publisher typo Bioguide not in spicy_members) -> person_key IS NULL!
            dict(source_locator='cg:12', name_key='unknown legislator', name='Rep. Unknown Legislator', given='Unknown', family='Legislator', witness_type='member_appearance', bioguide_id='KOOO395', position='U.S. Representative', organization='U.S. House of Representatives', display_order=12),
            # Matches #13 (surnames Judge, Vice, Major)
            dict(source_locator='cg:13', name_key='kathryn judge', name='Judge Kathryn Judge', given='Kathryn', family='Judge', position='Professor', organization='Columbia Law School', display_order=13),
            dict(source_locator='cg:14', name_key='charles a vice', name='Charles A. Vice', given='Charles', family='Vice', position='Commissioner', organization='Kentucky Department of Financial Institutions', display_order=14),
            dict(source_locator='cg:15', name_key='matthew major', name='Matthew Major', given='Matthew', family='Major', position='Researcher', organization='Northwestern University', display_order=15),
            # Placeholder / bare-suffix orgs ('WITNESS', 'Inc') stay distinct singletons!
            dict(source_locator='cg:16', name_key='sam gregory', name='Mr. Sam Gregory', given='Sam', family='Gregory', position='Director', organization='WITNESS', display_order=16),
            dict(source_locator='cg:17', name_key='bert ely', name='Bert Ely', given='Bert', family='Ely', position='Consultant', organization='Inc', display_order=17),
        ]),
        # Hearing 903: Congress.gov (priority 2) supersedes MODS print (priority 3, empty org) -> MODS row inherits CG person_key!
        dict(record_sha=sha(cg_903), source='congress_gov', event_id=903, collection_state='present', appearances=[
            dict(source_locator='cg:1', name_key='elena vance', name='Elena M. Vance', given='Elena', family='Vance', position='Lead', organization='Grid Lab', display_order=1),
        ]),
        dict(record_sha=sha(mods_903), source='mods', package_id='CHRG-118hhrg90301', held_dates=['2024-07-10'], title='Hearing 903', collection_state='present', appearances=[
            dict(source_locator='mods:1', name_key='elena vance', name='Elena Vance', given='Elena', family='Vance', position='Lead', organization=None, display_order=1),
        ]),
        # Multi-date MODS print (e.g. CHRG-111shrg57186 with upstream '1933-03-01' placeholder alongside '2009-12-09')
        # must choose the Congress-window heldDate rather than lexicographically earliest placeholder!
        dict(record_sha=sha(mods_111), source='mods', package_id='CHRG-111shrg57186', held_dates=['1933-03-01', '2009-12-09'], title='111th Print', collection_state='present', appearances=[
            dict(source_locator='mods:1', name_key='ben shelly', name='Ben Shelly', given='Ben', family='Shelly', position='Vice President', organization='Navajo Nation', display_order=1),
        ]),
    ]

    staged = _stage_raw(tmp_path / 'stage', engine, captures)
    out = tmp_path / 'rel'
    build_release(
        **staged, engine=engine, output=out, scratch=tmp_path / 'scratch',
        meeting_records=meetings, appearance_records=appearances,
        spicy_regs=_spicy_people_fixture(), include_entities=True,
    )

    assert (out / 'people.parquet').exists()
    assert (out / 'person_aliases.parquet').exists()

    witnesses = pq.read_table(out / 'witnesses.parquet').to_pylist()
    people = {r['person_key']: r for r in pq.read_table(out / 'people.parquet').to_pylist()}
    aliases = pq.read_table(out / 'person_aliases.parquet').to_pylist()
    assert aliases == []

    by_loc = {(r['occasion'], r['source'], r['source_locator']): r for r in witnesses}

    # 1 & 2. Members by publisher & matched Bioguide
    assert by_loc[('meeting:901', 'congress_gov', 'cg:1')]['person_key'] == 'A000370'
    assert by_loc[('meeting:902', 'congress_gov', 'cg:1')]['person_key'] == 'A000370'
    assert people['A000370']['grouping_basis'] == 'bioguide'
    assert people['A000370']['bioguide_id'] == 'A000370'
    assert people['A000370']['hearing_count'] == 2

    assert by_loc[('meeting:901', 'congress_gov', 'cg:2')]['matched_bioguide_id'] == 'C001075'
    assert by_loc[('meeting:901', 'congress_gov', 'cg:2')]['person_key'] == 'C001075'
    assert people['C001075']['grouping_basis'] == 'bioguide'

    # 3. José De O'Reilly at The Brookings Institution
    pk_jose = _expected_person_v1('jose de oreilly', 'brookings institution', '', '')
    assert by_loc[('meeting:901', 'congress_gov', 'cg:3')]['person_key'] == pk_jose
    assert by_loc[('meeting:902', 'congress_gov', 'cg:2')]['person_key'] == pk_jose
    assert people[pk_jose]['grouping_basis'] == 'name_organization'
    assert people[pk_jose]['hearing_count'] == 2
    assert people[pk_jose]['first_seen_date'] == date(2024, 5, 1)
    assert people[pk_jose]['last_seen_date'] == date(2024, 6, 15)

    # 4. Williams, James A. == James A. Williams at RAND Corporation
    pk_williams = _expected_person_v1('james williams', 'rand corporation', 'a', '')
    assert by_loc[('meeting:901', 'congress_gov', 'cg:4')]['person_key'] == pk_williams
    assert by_loc[('meeting:902', 'congress_gov', 'cg:3')]['person_key'] == pk_williams

    # 5. Full organization preserved (sub-unit A != sub-unit B)
    pk_miller_a = by_loc[('meeting:901', 'congress_gov', 'cg:5')]['person_key']
    pk_miller_b = by_loc[('meeting:902', 'congress_gov', 'cg:4')]['person_key']
    assert pk_miller_a != pk_miller_b

    # 6 & 903. Elena M. Vance + Elena Vance + superseded 903 MODS row all share pk_elena!
    pk_elena = _expected_person_v1('elena vance', 'grid lab', 'm', '')
    assert by_loc[('meeting:901', 'congress_gov', 'cg:6')]['person_key'] == pk_elena
    assert by_loc[('meeting:902', 'congress_gov', 'cg:5')]['person_key'] == pk_elena
    assert by_loc[('meeting:903', 'congress_gov', 'cg:1')]['person_key'] == pk_elena
    assert by_loc[('meeting:903', 'mods', 'mods:1')]['superseded_by'] == by_loc[('meeting:903', 'congress_gov', 'cg:1')]['witness_key']
    assert by_loc[('meeting:903', 'mods', 'mods:1')]['person_key'] == pk_elena
    assert people[pk_elena]['hearing_count'] == 3
    assert people[pk_elena]['appearance_count'] == 3

    # 7. Competing middle initials split into 3 distinct people (a, b, '')
    pk_cho_a = by_loc[('meeting:901', 'congress_gov', 'cg:7')]['person_key']
    pk_cho_b = by_loc[('meeting:901', 'congress_gov', 'cg:8')]['person_key']
    pk_cho_u = by_loc[('meeting:902', 'congress_gov', 'cg:6')]['person_key']
    assert len({pk_cho_a, pk_cho_b, pk_cho_u}) == 3
    assert pk_cho_a == _expected_person_v1('robert cho', 'civic policy center', 'a', '')
    assert pk_cho_b == _expected_person_v1('robert cho', 'civic policy center', 'b', '')
    assert pk_cho_u == _expected_person_v1('robert cho', 'civic policy center', '', '')

    # 8. Single stated suffix 'jr' joins unstated
    pk_henry = _expected_person_v1('henry alvarez', 'port authority', '', 'jr')
    assert by_loc[('meeting:901', 'congress_gov', 'cg:9')]['person_key'] == pk_henry
    assert by_loc[('meeting:902', 'congress_gov', 'cg:7')]['person_key'] == pk_henry

    # 9. Competing suffixes split into 3 distinct people (jr, sr, '')
    pk_bell_jr = by_loc[('meeting:901', 'congress_gov', 'cg:10')]['person_key']
    pk_bell_sr = by_loc[('meeting:902', 'congress_gov', 'cg:8')]['person_key']
    pk_bell_u = by_loc[('meeting:902', 'congress_gov', 'cg:9')]['person_key']
    assert len({pk_bell_jr, pk_bell_sr, pk_bell_u}) == 3

    # 10 & 11. Singletons never merge
    w_scully_1 = by_loc[('meeting:901', 'congress_gov', 'cg:11')]
    w_scully_2 = by_loc[('meeting:902', 'congress_gov', 'cg:10')]
    assert w_scully_1['person_key'] == _expected_singleton_v1(w_scully_1['witness_key'])
    assert w_scully_2['person_key'] == _expected_singleton_v1(w_scully_2['witness_key'])
    assert w_scully_1['person_key'] != w_scully_2['person_key']
    assert people[w_scully_1['person_key']]['grouping_basis'] == 'singleton'

    w_johns_1 = by_loc[('meeting:901', 'congress_gov', 'cg:12')]
    w_johns_2 = by_loc[('meeting:902', 'congress_gov', 'cg:11')]
    assert w_johns_1['person_key'] == _expected_singleton_v1(w_johns_1['witness_key'])
    assert w_johns_1['person_key'] != w_johns_2['person_key']

    # 12. Record entry and unmatched member_appearance have NULL person_key
    assert by_loc[('meeting:901', 'congress_gov', 'cg:13')]['person_key'] is None
    assert by_loc[('meeting:902', 'congress_gov', 'cg:12')]['witness_type'] == 'member_appearance'
    assert by_loc[('meeting:902', 'congress_gov', 'cg:12')]['person_key'] is None

    # 13. Surnames matching prefix titles ('Judge', 'Vice', 'Major') merge properly
    pk_judge = _expected_person_v1('kathryn judge', 'columbia law school', '', '')
    assert by_loc[('meeting:901', 'congress_gov', 'cg:14')]['person_key'] == pk_judge
    assert by_loc[('meeting:902', 'congress_gov', 'cg:13')]['person_key'] == pk_judge
    assert people[pk_judge]['grouping_basis'] == 'name_organization'

    pk_vice = _expected_person_v1('charles vice', 'kentucky department of financial institutions', 'a', 'jr')
    assert by_loc[('meeting:901', 'congress_gov', 'cg:15')]['person_key'] == pk_vice
    assert by_loc[('meeting:902', 'congress_gov', 'cg:14')]['person_key'] == pk_vice

    pk_major = _expected_person_v1('matthew major', 'northwestern university', '', '')
    assert by_loc[('meeting:901', 'congress_gov', 'cg:16')]['person_key'] == pk_major
    assert by_loc[('meeting:902', 'congress_gov', 'cg:15')]['person_key'] == pk_major

    # 14. Placeholder / bare-suffix orgs ('WITNESS', 'Inc') stay singletons
    w_greg_1 = by_loc[('meeting:901', 'congress_gov', 'cg:17')]
    w_greg_2 = by_loc[('meeting:902', 'congress_gov', 'cg:16')]
    assert w_greg_1['person_key'] == _expected_singleton_v1(w_greg_1['witness_key'])
    assert w_greg_2['person_key'] == _expected_singleton_v1(w_greg_2['witness_key'])
    assert w_greg_1['person_key'] != w_greg_2['person_key']
    assert people[w_greg_1['person_key']]['grouping_basis'] == 'singleton'

    w_ely_1 = by_loc[('meeting:901', 'congress_gov', 'cg:18')]
    w_ely_2 = by_loc[('meeting:902', 'congress_gov', 'cg:17')]
    assert w_ely_1['person_key'] == _expected_singleton_v1(w_ely_1['witness_key'])
    assert w_ely_2['person_key'] == _expected_singleton_v1(w_ely_2['witness_key'])
    assert w_ely_1['person_key'] != w_ely_2['person_key']

    # 15. Multi-date MODS print chooses Congress-consistent date ('2009-12-09'), ignoring '1933-03-01' placeholder
    pk_shelly = _expected_person_v1('ben shelly', 'navajo nation', '', '')
    assert by_loc[('package:CHRG-111shrg57186', 'mods', 'mods:1')]['person_key'] == pk_shelly
    assert people[pk_shelly]['first_seen_date'] == date(2009, 12, 9)
    assert people[pk_shelly]['last_seen_date'] == date(2009, 12, 9)


def test_person_aliases_across_releases_gate_and_lost_person_key_refusal(tmp_path):
    """ct-ha10: disappeared person_keys emit unambiguous/ambiguous/unresolved person_aliases,
    carry 1 hop, leave person_aliases if re-published, pass Gate 1 on Congress.gov updates,
    and refuse export before manifest.json when a prior person_key is lost."""
    from viewer_publication.archive_model import build_release
    from viewer_publication.release_comparison import compare
    from viewer_publication.release_gate import automatic_causes, prior_links, verdict

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    sha = lambda b: hashlib.sha256(b).hexdigest()

    cg_950_r1 = _cg_json(950, '2026-10-20T00:00:00Z', 'r1')
    cg_951_r1 = _cg_json(951, '2026-10-20T00:00:00Z', 'r1')
    cg_950_r2 = _cg_json(950, '2026-10-25T00:00:00Z', 'r2')
    cg_951_r2 = _cg_json(951, '2026-10-25T00:00:00Z', 'r2')

    doc_950 = _pdf_bytes('testimony-950')
    r1_caps = [
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/950?format=json', data=cg_950_r1, format='json', family='congress/meetings', retrieved_at='2026-10-20T12:00:00Z', receipt_key='receipts/documents/2026-10-20/r1.jsonl.gz'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/951?format=json', data=cg_951_r1, format='json', family='congress/meetings', retrieved_at='2026-10-20T12:00:00Z', receipt_key='receipts/documents/2026-10-20/r1.jsonl.gz'),
        dict(url='https://docs.house.gov/meetings/IF/IF00/20240501/950/HHRG-118-IF00-Wstate-OswaldC-20240501.pdf', data=doc_950, format='pdf', suffix='.pdf', retrieved_at='2026-10-20T12:00:00Z', receipt_key='receipts/documents/2026-10-20/r1.jsonl.gz'),
    ]
    m_r1 = [
        dict(record_sha=sha(cg_950_r1), source='congress_gov', meetings=[_mrow(950, date_str='2024-05-01')]),
        dict(record_sha=sha(cg_951_r1), source='congress_gov', meetings=[_mrow(951, date_str='2024-05-10')]),
    ]
    a_r1 = [
        dict(record_sha=sha(cg_950_r1), source='congress_gov', event_id=950, collection_state='present', appearances=[
            # Clara Oswald has typo org "Grid Co" on 950 -> fixed to "Grid Corp" on r2 (unambiguous regroup/merge!)
            dict(source_locator='cg:1', name_key='clara oswald', name='Clara Oswald', given='Clara', family='Oswald', position='VP', organization='Grid Co', display_order=1),
            # Sam Carter has middle initial A on 950, unstated on 951 -> merged under mid='a' in r1!
            # On r2, 951 is updated to "Sam B. Carter" -> prior pk_sam_a keeps 950, wait: what if r1 had TWO unstated Sam Carters (merged as mid='') and on r2 950 becomes "Sam A. Carter" and 951 becomes "Sam B. Carter"?
            # YES! Then mid='' disappears completely and splits across pk_sam_a and pk_sam_b -> status='ambiguous', kind='split'!
            dict(source_locator='cg:2', name_key='sam carter', name='Sam Carter', given='Sam', family='Carter', position='Engineer', organization='Deep Space Lab', display_order=2),
        ]),
        dict(record_sha=sha(cg_951_r1), source='congress_gov', event_id=951, collection_state='present', appearances=[
            dict(source_locator='cg:1', name_key='sam carter', name='Sam Carter', given='Sam', family='Carter', position='Engineer', organization='Deep Space Lab', display_order=1),
        ]),
    ]

    staged_r1 = _stage_raw(tmp_path / 'stage-r1', engine, r1_caps)
    rel1 = tmp_path / 'rel-1'
    build_release(
        **staged_r1, engine=engine, output=rel1, scratch=tmp_path / 'scratch-1',
        meeting_records=m_r1, appearance_records=a_r1,
        spicy_regs=_spicy_people_fixture(), include_entities=True,
    )
    rel1_manifest = json.loads((rel1 / 'manifest.json').read_text())
    p_r1 = {r['name']: r for r in pq.read_table(rel1 / 'people.parquet').to_pylist()}
    old_clara_pk = p_r1['Clara Oswald']['person_key']
    old_sam_pk = p_r1['Sam Carter']['person_key']

    # Inject a pre-existing 1-hop alias row into rel1/person_aliases.parquet pointing at old_clara_pk
    # AND a historical unresolved alias row to verify 1-hop carry!
    alias_schema = pq.read_schema(rel1 / 'person_aliases.parquet')
    seed_aliases = pa.Table.from_pylist([
        dict(old_person_key='0011223344556677', person_key=old_clara_pk, status='unambiguous',
             kind='regrouped', decision_id=None, last_release_id='0' * 64, candidate_keys=[]),
        dict(old_person_key='8899aabbccddeeff', person_key=None, status='unresolved',
             kind=None, decision_id=None, last_release_id='0' * 64, candidate_keys=[]),
    ], schema=alias_schema)
    pq.write_table(seed_aliases, rel1 / 'person_aliases.parquet')
    # Re-seal rel1 manifest after seeding person_aliases
    from viewer_publication.archive_format import release_identity
    adata = (rel1 / 'person_aliases.parquet').read_bytes()
    for f in rel1_manifest['files']:
        if f['name'] == 'person_aliases.parquet':
            f['size'] = len(adata)
            f['rows'] = 2
            f['sha256'] = hashlib.sha256(adata).hexdigest()
    rel1_manifest['release_id'] = release_identity(rel1_manifest['schema_version'], rel1_manifest['files'])
    (rel1 / 'manifest.json').write_text(json.dumps(rel1_manifest, indent=2) + '\n')

    # Read 2: Clara Oswald's org updated to "Grid Corp" on 950; Sam Carter updated to Sam A. Carter (950) and Sam B. Carter (951)
    r2_caps = r1_caps + [
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/950?format=json', data=cg_950_r2, format='json', family='congress/meetings', retrieved_at='2026-10-25T12:00:00Z', receipt_key='receipts/documents/2026-10-25/r2.jsonl.gz'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/951?format=json', data=cg_951_r2, format='json', family='congress/meetings', retrieved_at='2026-10-25T12:00:00Z', receipt_key='receipts/documents/2026-10-25/r2.jsonl.gz'),
    ]
    m_r2 = m_r1 + [
        dict(record_sha=sha(cg_950_r2), source='congress_gov', meetings=[_mrow(950, updated='2026-10-25T00:00:00Z', date_str='2024-05-01')]),
        dict(record_sha=sha(cg_951_r2), source='congress_gov', meetings=[_mrow(951, updated='2026-10-25T00:00:00Z', date_str='2024-05-10')]),
    ]
    a_r2 = a_r1 + [
        dict(record_sha=sha(cg_950_r2), source='congress_gov', event_id=950, collection_state='present', appearances=[
            dict(source_locator='cg:1', name_key='clara oswald', name='Clara Oswald', given='Clara', family='Oswald', position='VP', organization='Grid Corp', display_order=1),
            dict(source_locator='cg:2', name_key='sam carter', name='Sam A. Carter', given='Sam', family='Carter', position='Engineer', organization='Deep Space Lab', display_order=2),
        ]),
        dict(record_sha=sha(cg_951_r2), source='congress_gov', event_id=951, collection_state='present', appearances=[
            dict(source_locator='cg:1', name_key='sam carter', name='Sam B. Carter', given='Sam', family='Carter', position='Engineer', organization='Deep Space Lab', display_order=1),
        ]),
    ]

    staged_r2 = _stage_raw(tmp_path / 'stage-r2', engine, r2_caps)
    p12, r12 = prior_links(rel1, [], tmp_path / 'ledger-12')
    rel2 = tmp_path / 'rel-2'
    build_release(
        **staged_r2, engine=engine, output=rel2, scratch=tmp_path / 'scratch-2',
        meeting_records=m_r2, appearance_records=a_r2,
        spicy_regs=_spicy_people_fixture(), include_entities=True,
        prior_links=p12, base_retired=r12,
        base_release_id=rel1_manifest['release_id'],
    )

    people_r2 = {r['person_key']: r for r in pq.read_table(rel2 / 'people.parquet').to_pylist()}
    aliases_r2 = {r['old_person_key']: r for r in pq.read_table(rel2 / 'person_aliases.parquet').to_pylist()}

    new_clara_pk = _expected_person_v1('clara oswald', 'grid corp', '', '')
    new_sam_a = _expected_person_v1('sam carter', 'deep space lab', 'a', '')
    new_sam_b = _expected_person_v1('sam carter', 'deep space lab', 'b', '')
    assert {new_clara_pk, new_sam_a, new_sam_b} <= set(people_r2)

    # Unambiguous regrouped alias for old_clara_pk + 1-hop carry of 0011223344556677 -> new_clara_pk!
    assert aliases_r2[old_clara_pk]['status'] == 'unambiguous'
    assert aliases_r2[old_clara_pk]['person_key'] == new_clara_pk
    assert aliases_r2[old_clara_pk]['kind'] == 'regrouped'
    assert aliases_r2[old_clara_pk]['last_release_id'] == rel1_manifest['release_id']
    assert aliases_r2['0011223344556677']['status'] == 'unambiguous'
    assert aliases_r2['0011223344556677']['person_key'] == new_clara_pk
    assert aliases_r2['8899aabbccddeeff']['status'] == 'unresolved'

    # Ambiguous split alias for old_sam_pk!
    assert aliases_r2[old_sam_pk]['status'] == 'ambiguous'
    assert aliases_r2[old_sam_pk]['person_key'] is None
    assert aliases_r2[old_sam_pk]['kind'] == 'split'
    assert aliases_r2[old_sam_pk]['candidate_keys'] == sorted([new_sam_a, new_sam_b])

    # Gate 1: unambiguous regrouped person on Congress.gov update is verified; ambiguous split requires review (stops)!
    report = compare(rel1, rel2)
    failing_files = {(g['file'], g['group']) for g in report['failing'] if g['file'] != 'url_state.parquet'}
    assert ('people.parquet', 'removed keys') in failing_files  # old_sam_pk turned ambiguous -> stops for review!

    # Also verify pure unambiguous Congress.gov person org fix passes Gate 1 + automatic_causes + verdict unattended!
    cg_960_r1 = _cg_json(960, '2026-10-20T00:00:00Z', 'r1')
    cg_960_r2 = _cg_json(960, '2026-10-25T00:00:00Z', 'r2')
    doc_960 = _pdf_bytes('testimony-960')
    u1_caps = [
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/960?format=json', data=cg_960_r1, format='json', family='congress/meetings', retrieved_at='2026-10-20T12:00:00Z', receipt_key='receipts/documents/2026-10-20/u1.jsonl.gz'),
        dict(url='https://docs.house.gov/meetings/IF/IF00/20240501/960/HHRG-118-IF00-Wstate-OswaldC-20240501.pdf', data=doc_960, format='pdf', suffix='.pdf', retrieved_at='2026-10-20T12:00:00Z', receipt_key='receipts/documents/2026-10-20/u1.jsonl.gz'),
    ]
    u2_caps = u1_caps + [dict(url='https://api.congress.gov/v3/committee-meeting/118/house/960?format=json', data=cg_960_r2, format='json', family='congress/meetings', retrieved_at='2026-10-25T12:00:00Z', receipt_key='receipts/documents/2026-10-25/u2.jsonl.gz')]
    st_u1 = _stage_raw(tmp_path / 'st-u1', engine, u1_caps)
    st_u2 = _stage_raw(tmp_path / 'st-u2', engine, u2_caps)
    rel_u1, rel_u2 = tmp_path / 'rel-u1', tmp_path / 'rel-u2'
    build_release(
        **st_u1, engine=engine, output=rel_u1, scratch=tmp_path / 'sc-u1',
        meeting_records=[dict(record_sha=sha(cg_960_r1), source='congress_gov', meetings=[_mrow(960)])],
        appearance_records=[dict(record_sha=sha(cg_960_r1), source='congress_gov', event_id=960, collection_state='present', appearances=[
            dict(source_locator='cg:1', name_key='clara oswald', name='Clara Oswald', given='Clara', family='Oswald', position='VP', organization='Grid Co', display_order=1),
        ])],
        spicy_regs=_spicy_people_fixture(), include_entities=True,
    )
    pu, ru = prior_links(rel_u1, [], tmp_path / 'ledger-u')
    u1_id = json.loads((rel_u1 / 'manifest.json').read_text())['release_id']
    build_release(
        **st_u2, engine=engine, output=rel_u2, scratch=tmp_path / 'sc-u2',
        meeting_records=[
            dict(record_sha=sha(cg_960_r1), source='congress_gov', meetings=[_mrow(960)]),
            dict(record_sha=sha(cg_960_r2), source='congress_gov', meetings=[_mrow(960, updated='2026-10-25T00:00:00Z')]),
        ],
        appearance_records=[
            dict(record_sha=sha(cg_960_r1), source='congress_gov', event_id=960, collection_state='present', appearances=[
                dict(source_locator='cg:1', name_key='clara oswald', name='Clara Oswald', given='Clara', family='Oswald', position='VP', organization='Grid Co', display_order=1),
            ]),
            dict(record_sha=sha(cg_960_r2), source='congress_gov', event_id=960, collection_state='present', appearances=[
                dict(source_locator='cg:1', name_key='clara oswald', name='Clara Oswald', given='Clara', family='Oswald', position='VP', organization='Grid Corp', display_order=1),
            ]),
        ],
        spicy_regs=_spicy_people_fixture(), include_entities=True,
        prior_links=pu, base_retired=ru, base_release_id=u1_id,
    )
    rep_u = compare(rel_u1, rel_u2)
    assert [g for g in rep_u['failing'] if g['file'] != 'url_state.parquet'] == []
    ag, ar = automatic_causes(
        rep_u, rel_u1, rel_u2, engine=engine,
        captures=dict(kind='parquet', path=str(st_u2['captures'])),
        live_receipt_keys=['receipts/documents/2026-10-20/u1.jsonl.gz'],
        candidate_receipt_keys=['receipts/documents/2026-10-20/u1.jsonl.gz', 'receipts/documents/2026-10-25/u2.jsonl.gz'],
        read_receipt=lambda k: (tmp_path / 'st-u2' / 'raw' / k).read_bytes(),
        work=tmp_path / 'auto-u',
    )
    assert ar == []
    assert verdict(rep_u, dict(base_release_id=rep_u['base_release'], candidate_release_id=rep_u['candidate_release'], groups=ag))[0] == []

    # Export refusal: a lost prior person_key missing from both people and person_aliases fails publication_checks
    # and refuses build_release before manifest.json is written!
    import shutil
    from viewer_publication.archive_model_profile import ROOT, _definition_hashes
    from viewer_publication.archive_schema import build_schema, publication_checks
    from congress_api.retention.provenance import run_job
    schema = build_schema()
    schema['files'] = [t for t in schema['files'] if t['name'] in ('people.parquet', 'person_aliases.parquet')]
    prior_pp = tmp_path / 'phantom_prior_people.parquet'
    pq.write_table(pa.Table.from_pylist([dict(person_key='deadbeefcafebabe')]), prior_pp)
    res_check = run_job(
        tmp_path / 'check-refusal', engine,
        inputs=[
            dict(name='people_export', kind='parquet', path=str(rel_u2 / 'people.parquet')),
            dict(name='person_aliases_export', kind='parquet', path=str(rel_u2 / 'person_aliases.parquet')),
            dict(name='prior_people', kind='parquet', path=str(prior_pp)),
            dict(name='base_person_aliases', kind='parquet', path=str(rel_u2 / 'person_aliases.parquet')),
        ],
        steps=[
            dict(name='ordered', sql='SELECT 0 AS list_row'),
            dict(name='details', sql='SELECT 0 AS list_row,cast(NULL AS VARCHAR) AS link_key'),
            dict(name='links', sql="SELECT 0 AS list_row,'present-link' AS link_key"),
        ],
        outputs=[],
        queries=publication_checks(schema, {'people', 'person_aliases'}, keyed_documents=False,
                                   input_names={'prior_people', 'base_person_aliases'}),
    )
    found_counts = res_check['relationship_invariants'][0]
    assert found_counts['lost_person_keys'] == 1

    # Also prove build_release refuses before manifest.json if person-aliases.sql drops an alias row!
    broken_root = tmp_path / 'broken-root'
    for relative in _definition_hashes(ROOT):
        target = broken_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    pa_sql = broken_root / 'model/sql/person-aliases.sql'
    pa_sql.write_text('SELECT * FROM (\n' + pa_sql.read_text().rstrip().rstrip(';') + '\n) WHERE false\n')
    bad_out = tmp_path / 'rel-bad-out'
    with pytest.raises(ValueError, match='Release key invariant failed'):
        build_release(
            **st_u2, engine=engine, output=bad_out, scratch=tmp_path / 'sc-bad',
            meeting_records=[
                dict(record_sha=sha(cg_960_r1), source='congress_gov', meetings=[_mrow(960)]),
                dict(record_sha=sha(cg_960_r2), source='congress_gov', meetings=[_mrow(960, updated='2026-10-25T00:00:00Z')]),
            ],
            appearance_records=[
                dict(record_sha=sha(cg_960_r1), source='congress_gov', event_id=960, collection_state='present', appearances=[
                    dict(source_locator='cg:1', name_key='clara oswald', name='Clara Oswald', given='Clara', family='Oswald', position='VP', organization='Grid Co', display_order=1),
                ]),
                dict(record_sha=sha(cg_960_r2), source='congress_gov', event_id=960, collection_state='present', appearances=[
                    dict(source_locator='cg:1', name_key='clara oswald', name='Clara Oswald', given='Clara', family='Oswald', position='VP', organization='Grid Corp', display_order=1),
                ]),
            ],
            spicy_regs=_spicy_people_fixture(), include_entities=True,
            prior_links=pu, base_retired=ru, base_release_id=u1_id,
            root=broken_root,
        )
    assert not (bad_out / 'manifest.json').exists()


def test_military_rank_and_credentials_propagate_without_column_collision(tmp_path):
    """Wave 3 rank/credentials pass through occurrence_ordinal, witnesses.parquet, and people.parquet (P0-3a/b),
    and pre-Wave-3 Parquet appearance_records lacking rank/credentials still build cleanly."""
    from viewer_publication.archive_model import build_release

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    cg_970 = _cg_json(970, '2026-10-20T00:00:00Z', 'r1')
    cg_971 = _cg_json(971, '2026-10-22T00:00:00Z', 'r1')
    doc_970 = _pdf_bytes('testimony-970')
    sha = lambda b: hashlib.sha256(b).hexdigest()

    staged = _stage_raw(tmp_path / 'stage-rank', engine, [
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/970?format=json', data=cg_970, format='json', family='congress/meetings', retrieved_at='2026-10-20T12:00:00Z'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/971?format=json', data=cg_971, format='json', family='congress/meetings', retrieved_at='2026-10-22T12:00:00Z'),
        dict(url='https://docs.house.gov/meetings/IF/IF00/20240501/970/HHRG-118-IF00-Wstate-NakasoneP-20240501.pdf', data=doc_970, format='pdf', suffix='.pdf'),
    ])
    meetings = [
        dict(record_sha=sha(cg_970), source='congress_gov', meetings=[_mrow(970, date_str='2020-03-04')]),
        dict(record_sha=sha(cg_971), source='congress_gov', meetings=[_mrow(971, date_str='2023-03-08')]),
    ]
    appearances = [
        dict(record_sha=sha(cg_970), source='congress_gov', event_id=970, collection_state='present', appearances=[
            # Earlier appearance as Lieutenant General + two equal unnamed/duplicate entries checking occurrence_ordinal
            dict(source_locator='cg:1', name_key='paul m nakasone', name='Paul M. Nakasone', rank='Lieutenant General', credentials='USA', given='Paul', middle='M.', family='Nakasone', position='Commander', organization='U.S. Cyber Command', display_order=1),
            dict(source_locator='cg:2', name_key='michael l kussman', name='Michael L. Kussman', rank=None, credentials='M.D., M.S. MACP', given='Michael', middle='L.', family='Kussman', position='Under Secretary for Health', organization='Department of Veterans Affairs', display_order=2),
            dict(source_locator='cg:3', name_key='michael l kussman', name='Michael L. Kussman', rank=None, credentials='M.D., M.S. MACP', given='Michael', middle='L.', family='Kussman', position='Under Secretary for Health', organization='Department of Veterans Affairs', display_order=3),
        ]),
        dict(record_sha=sha(cg_971), source='congress_gov', event_id=971, collection_state='present', appearances=[
            # Later appearance promoted to General
            dict(source_locator='cg:1', name_key='paul m nakasone', name='Paul M. Nakasone', rank='General', credentials='USA', given='Paul', middle='M.', family='Nakasone', position='Commander', organization='U.S. Cyber Command', display_order=1),
        ]),
    ]

    rel_out = tmp_path / 'rel-rank'
    build_release(
        **staged, engine=engine, output=rel_out, scratch=tmp_path / 'sc-rank',
        meeting_records=meetings, appearance_records=appearances,
        spicy_regs=_spicy_people_fixture(), include_entities=True,
    )

    witnesses = pq.read_table(rel_out / 'witnesses.parquet').to_pylist()
    by_loc = {(w['occasion'], w['source_locator']): w for w in witnesses}
    assert by_loc[('meeting:970', 'cg:1')]['rank'] == 'Lieutenant General'
    assert by_loc[('meeting:970', 'cg:1')]['credentials'] == 'USA'
    assert by_loc[('meeting:971', 'cg:1')]['rank'] == 'General'
    assert by_loc[('meeting:970', 'cg:2')]['credentials'] == 'M.D., M.S. MACP'
    # Duplicate occurrences on 970 received distinct witness_keys via occurrence_ordinal
    assert by_loc[('meeting:970', 'cg:2')]['witness_key'] != by_loc[('meeting:970', 'cg:3')]['witness_key']

    people = {p['name']: p for p in pq.read_table(rel_out / 'people.parquet').to_pylist()}
    nakasone = people['Paul M. Nakasone']
    assert nakasone['rank'] == 'General'
    assert nakasone['ranks'] == ['General', 'Lieutenant General']
    assert nakasone['credentials'] == 'USA'
    assert nakasone['hearing_count'] == 2

    kussman = people['Michael L. Kussman']
    assert kussman['rank'] is None
    assert kussman['ranks'] == []
    assert kussman['credentials'] == 'M.D., M.S. MACP'

    # Also verify pre-Wave-3 Parquet appearance_records (without rank/credentials struct fields) builds cleanly
    cg_app_ver = staged['parser_versions']['appearance_records']['congress_gov']
    legacy_app_parquet = tmp_path / 'legacy_appearance_records.parquet'
    pq.write_table(pa.Table.from_pylist([
        dict(
            record_sha=bytes.fromhex(sha(cg_970)),
            parser_version=cg_app_ver,
            status='completed',
            error_type=None,
            source='congress_gov',
            event_id=970,
            package_id=None,
            declared_base=None,
            collection_state='present',
            appearances=[dict(
                source_locator='cg:1', name_key='jane doe', name='Jane Doe', honorific=None,
                given='Jane', middle=None, family='Doe', suffix=None, position='Director',
                organization='Civic Lab', on_behalf_of=None, location=None, panel=None,
                panel_order=1, display_order=1, witness_type=None, testified=True,
                bioguide_id=None, document_links=[],
            )],
        ),
        dict(
            record_sha=bytes.fromhex(sha(cg_971)),
            parser_version=cg_app_ver,
            status='completed',
            error_type=None,
            source='congress_gov',
            event_id=971,
            package_id=None,
            declared_base=None,
            collection_state='empty',
            appearances=[],
        ),
    ]), legacy_app_parquet)
    legacy_out = tmp_path / 'rel-legacy-parquet'
    build_release(
        **staged, engine=engine, output=legacy_out, scratch=tmp_path / 'sc-legacy-parquet',
        meeting_records=meetings, appearance_records=legacy_app_parquet,
        spicy_regs=_spicy_people_fixture(), include_entities=True,
    )
    legacy_w = pq.read_table(legacy_out / 'witnesses.parquet').to_pylist()
    assert len(legacy_w) == 1
    assert legacy_w[0]['rank'] is None and legacy_w[0]['credentials'] is None


def test_source_priority_selects_higher_ranked_publisher_on_same_hearing_date(tmp_path):
    """BLOCKER 3: Same-date appearances across house_xml (priority 1) and congress_gov (priority 2) select house_xml's
    canonical name/rank/organization even when congress_gov's witness_key sorts lexicographically before house_xml's."""
    from viewer_publication.archive_model import build_release

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    sha = lambda b: hashlib.sha256(b).hexdigest()

    # Pick an event_id pair where congress_gov v3_key < house_xml v3_key so tied priority=99 picks congress_gov!
    cg_eid = None
    k_hxml = hashlib.sha256(json.dumps([
        'witness-appearance-v3', 'meeting:980', 'house_xml', '',
        'dr sarah thornton', 'national energy lab', 'chief scientist', 1,
    ], separators=(',', ':')).encode()).hexdigest()[:16]
    for eid in range(981, 1050):
        k_cg = hashlib.sha256(json.dumps([
            'witness-appearance-v3', f'meeting:{eid}', 'congress_gov', '',
            'thornton sarah', 'national energy lab', 'scientist', 1,
        ], separators=(',', ':')).encode()).hexdigest()[:16]
        if k_cg < k_hxml:
            cg_eid = eid
            break
    assert cg_eid is not None

    hxml_980 = b'<committee-meeting meeting-id="980"><r>1</r></committee-meeting>'
    cg_other = _cg_json(cg_eid, '2026-10-20T00:00:00Z', 'cg')
    doc_pdf = _pdf_bytes('doc-980')
    staged = _stage_raw(tmp_path / 'st-980', engine, [
        dict(url='https://docs.house.gov/meetings/IF/IF00/20240501/980/HMTG-118-IF00-20240501-980.xml', data=hxml_980, format='xml', family='house/meeting-xml'),
        dict(url=f'https://api.congress.gov/v3/committee-meeting/118/house/{cg_eid}?format=json', data=cg_other, format='json', family='congress/meetings'),
        dict(url='https://docs.house.gov/meetings/IF/IF00/20240501/980/doc.pdf', data=doc_pdf, format='pdf', suffix='.pdf'),
    ])
    meetings = [
        dict(record_sha=sha(hxml_980), source='house_xml', meetings=[dict(
            event_id='980', chamber='house', congress=118, session=2, updated='2024-05-01T10:00:00Z',
            title='Energy Hearing 980', meeting_date='2024-05-01', meeting_type='HHRG', status='Scheduled',
            sittings=[], committees=[dict(system_code='hsif00', name='Energy and Commerce', chamber='house', role='host')],
            subject_keys=[], transcript_jackets=[], videos=[], document_urls=[], document_references=[],
            collection_states=dict(sittings='present', committees='present', subject_keys='empty', transcript_jackets='empty', videos='empty', document_urls='empty'),
            access='open', access_basis='default', not_held=False, title_key='energy hearing 980', reschedule_candidate=False,
        )]),
        dict(record_sha=sha(cg_other), source='congress_gov', meetings=[dict(
            event_id=str(cg_eid), chamber='house', congress=118, session=2, updated='2024-05-01T10:00:00Z',
            title=f'Energy Hearing {cg_eid}', meeting_date='2024-05-01', meeting_type='HHRG', status='Scheduled',
            sittings=[], committees=[dict(system_code='hsif00', name='Energy and Commerce', chamber='house', role='host')],
            subject_keys=[], transcript_jackets=[], videos=[], document_urls=[], document_references=[],
            collection_states=dict(sittings='present', committees='present', subject_keys='empty', transcript_jackets='empty', videos='empty', document_urls='empty'),
            access='open', access_basis='default', not_held=False, title_key=f'energy hearing {cg_eid}', reschedule_candidate=False,
        )]),
    ]
    appearances = [
        dict(record_sha=sha(hxml_980), source='house_xml', event_id=980, collection_state='present', appearances=[
            dict(source_locator='hxml:1', name_key='sarah thornton', name='Dr. Sarah Thornton', given='Sarah', family='Thornton', position='Chief Scientist', organization='National Energy Lab', display_order=1),
        ]),
        dict(record_sha=sha(cg_other), source='congress_gov', event_id=cg_eid, collection_state='present', appearances=[
            dict(source_locator='cg:1', name_key='sarah thornton', name='THORNTON, SARAH', given='Sarah', family='Thornton', position='Scientist', organization='NATIONAL ENERGY LAB', display_order=1),
        ]),
    ]
    out = tmp_path / 'out-980'
    build_release(
        **staged, engine=engine, output=out, scratch=tmp_path / 'sc-980',
        meeting_records=meetings, appearance_records=appearances, spicy_regs=_spicy_people_fixture(), include_entities=True,
    )
    people = pq.read_table(out / 'people.parquet').to_pylist()
    thornton = [p for p in people if 'thornton' in p['name'].lower()]
    assert len(thornton) == 1
    assert thornton[0]['name'] == 'Dr. Sarah Thornton'
    assert thornton[0]['organization'] == 'National Energy Lab'


