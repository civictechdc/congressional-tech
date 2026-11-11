"""The Member appearance raw check reads its own way and flags each of the nine planted wrong values (ct-kw85).

Hand rows: a Member rightly retyped (Reyes), an outside witness with a sitting Senator's name (Johnson of Corning),
the hearing's own nominee (Pompeo), a former Member (Campbell), a Member whose namesake also sits (French Hill beside
Katie Hill), two Levins, two Mike Rogers told apart by a seat, Member Day rows naming only the Member or a seat, a
seat's holder named only by family name (Pomeroy), a bare initial (C. Cox), a Member Day hearing that also hears an
outside witness, committee members' own opening statements typed Member statements (the print's MODS lists one; before
the 113th Congress the print's own transcript heads the others, in the House form, with a suffix and in the Senate form),
the publisher's own IDs in both directions with another publisher's copy, and rows the check cannot read.
"""
import gzip
import hashlib
import importlib.util
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).parents[3]
spec = importlib.util.spec_from_file_location('member_appearances_raw_check', ROOT / 'scripts/measure/member_appearances_raw_check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

MEMBERS = [  # bioguide, first, last, nickname, (term type, state, start, end, district)
    ('R000170', 'Silvestre', 'Reyes', None, ('rep', 'TX', '1997-01-07', '2013-01-03', '16')),
    ('J000177', 'Tim', 'Johnson', None, ('sen', 'SD', '1997-01-07', '2015-01-03', None)),
    ('P000602', 'Mike', 'Pompeo', None, ('rep', 'KS', '2011-01-05', '2017-01-23', '4')),
    ('C000077', 'Ben', 'Campbell', None, ('sen', 'CO', '1993-01-05', '2005-01-03', None)),
    ('H001072', 'J.', 'Hill', 'French', ('rep', 'AR', '2015-01-06', '2027-01-03', '2')),
    ('H001087', 'Katie', 'Hill', None, ('rep', 'CA', '2019-01-03', '2019-11-03', '25')),
    ('L000263', 'Sander', 'Levin', None, ('rep', 'MI', '1983-01-03', '2019-01-03', '9')),
    ('L000261', 'Carl', 'Levin', None, ('sen', 'MI', '1979-01-15', '2015-01-03', None)),
    ('W000789', 'Heather', 'Wilson', None, ('rep', 'NM', '1998-06-25', '2009-01-03', '1')),
    ('B001257', 'Gus', 'Bilirakis', None, ('rep', 'FL', '2007-01-04', '2027-01-03', '12')),
    ('C001049', 'Wm.', 'Clay', None, ('rep', 'MO', '2001-01-03', '2021-01-03', '1')),
    ('N000189', 'Dan', 'Newhouse', None, ('rep', 'WA', '2015-01-06', '2027-01-03', '4')),
    ('C001114', 'John', 'Curtis', None, ('rep', 'UT', '2017-11-13', '2025-01-03', '3')),
    ('R000575', 'Mike', 'Rogers', None, ('rep', 'AL', '2003-01-07', '2027-01-03', '3')),
    ('R000572', 'Mike', 'Rogers', None, ('rep', 'MI', '2001-01-03', '2015-01-03', '8')),
    ('C000830', 'C.', 'Cox', None, ('rep', 'CA', '1989-01-03', '2005-08-02', '48')),
    ('P000422', 'Earl', 'Pomeroy', None, ('rep', 'ND', '1993-01-05', '2011-01-03', '0')),
    ('J000299', 'Mike', 'Johnson', None, ('rep', 'LA', '2017-01-03', '2027-01-03', '4')),
    ('K000009', 'Marcy', 'Kaptur', None, ('rep', 'OH', '1983-01-03', '2027-01-03', '9')),
    ('D000355', 'John', 'Dingell', None, ('rep', 'MI', '1955-12-13', '2015-01-03', '12')),
    ('P000034', 'Frank', 'Pallone', None, ('rep', 'NJ', '1988-11-08', '2027-01-03', '6')),
    ('B000243', 'Max', 'Baucus', None, ('sen', 'MT', '1978-12-15', '2014-02-06', None)),
]
MEETINGS = [(1, '2007-05-01', 'Border security'), (2, '2013-09-24', 'Black carbon'),
            (3, '2017-01-12', 'Nomination of Mike Pompeo to be Director of the Central Intelligence Agency'),
            (4, '2017-07-07', 'Public lands'), (5, '2019-09-10', 'Banking'), (6, '2009-04-01', 'Trade'),
            (7, '2015-04-23', 'Health'), (8, '2025-02-05', 'Defense'), (9, None, 'Undated'), (10, '2019-09-11', 'Ferguson'),
            (11, '2019-09-20', 'Member Day Hearing'), (12, '2019-06-04', "Members' Day"), (13, '2013-07-09', 'Veterans care'),
            (14, '2001-06-28', 'Trade with Russia'), (15, '2006-05-10', 'Farm policy'), (16, '2026-03-17', 'Member Day'),
            (17, '2024-03-20', 'Energy and Water appropriations'), (18, '2008-03-01', 'Energy and Commerce'),
            (19, '2000-02-03', 'Environment and Public Works')]
# key: (source, event, name, position, organization, publisher id, witness type, published as member, matched)
WITNESSES = {
    'reyes': ('mods', 1, 'Silvestre Reyes', 'a Representative in Congress from the State of Texas', None, None, None, True, 'R000170'),
    'johnson': ('mods', 2, 'Timothy V. Johnson', 'Director of Emerging Technologies', 'Corning Environmental Technologies', None, None, False, None),
    'pompeo': ('mods', 3, 'Mike Pompeo', 'a Representative in Congress from the State of Kansas', None, None, None, False, None),
    'campbell': ('mods', 4, 'Ben Nighthorse Campbell', 'U.S. Senator from Colorado', None, None, None, False, None),
    'hill': ('mods', 5, 'French J. Hill', 'U.S. House of Representatives', None, None, None, True, 'H001072'),
    'levin': ('mods', 6, 'Sander M. Levin', 'a Representative in Congress from the State of Michigan', None, None, None, True, 'L000263'),
    'publisher-sitting': ('house_xml', 7, 'The Honorable Gus M. Bilirakis', 'Member of Congress', None, 'B001257', None, True, 'B001257'),
    'publisher-former': ('house_xml', 8, 'The Honorable Heather Wilson', 'President', 'University of Texas at El Paso', 'W000789', None, False, None),
    'clay': ('mods', 10, 'William Lacy Clay', 'a Representative in Congress from the State of Missouri', None, None, None, True, 'C001049'),
    'publisher-copy': ('congress_gov', 7, 'The Honorable Gus Bilirakis', 'Member of Congress', None, None, None, True, 'B001257'),
    'newhouse': ('congress_gov', 11, 'The Honorable Dan Newhouse', None, None, None, None, True, 'N000189'),
    'curtis': ('house_xml', 12, 'The Honorable John R. Curtis', None, 'Utah, 3d District', None, None, True, 'C001114'),
    'rogers': ('mods', 13, 'Mike Rogers', 'U.S. House of Representatives', '3rd District, Alabama', None, None, True, 'R000575'),
    'cox': ('mods', 14, 'Christopher Cox', 'a Representative in Congress from the State of California', None, None, None, True, 'C000830'),
    'pomeroy': ('mods', 15, 'Page Pomeroy', 'The Honorable Earl (ND-At Large)', 'Congressman, U.S. House of Representatives',
                None, None, True, 'P000422'),
    'outside-at-member-day': ('house_xml', 16, 'Mr. Kel McClanahan', 'Executive Director', 'National Security Counselors',
                              None, None, False, None),
    'namesake-at-member-day': ('house_xml', 16, 'Mr. Mike Johnson', None, None, None, None, False, None),
    'kaptur-opening': ('mods', 17, 'Marcy Kaptur', 'a Representative in Congress from the State of Ohio', 'opening statement', None,
                       'member_statement', False, 'K000009'),
    'dingell-early-opening': ('mods', 18, 'John D. Dingell', 'a Representative in Congress from the State of Michigan',
                              'opening statement', None, 'member_statement', False, 'D000355'),
    'pallone-early-opening': ('mods', 18, 'Frank Pallone, Jr.', 'a Representative in Congress from the State of New Jersey',
                              'opening statement', None, 'member_statement', False, 'P000034'),
    'baucus-early-opening': ('mods', 19, 'Max Baucus', 'U.S. Senator from the State of Montana', 'opening statement', None,
                             'member_statement', False, 'B000243'),
    'undated': ('mods', 9, 'Silvestre Reyes', 'a Representative in Congress from the State of Texas', None, None, None, False, None),
    'letter': ('mods', 1, 'Letter from the Sheriff', None, None, None, 'record_material', False, None),
}
BASIS = {'publisher-sitting': 'publisher_id', 'publisher-copy': 'name_chamber', 'pomeroy': 'seat', 'cox': 'initial'}
SUPERSEDED = {'publisher-copy': 'publisher-sitting'}
PLANTS = {
    'member left a witness': ('reyes', None),
    'outside witness retyped': ('johnson', 'J000177'),
    'nominee retyped': ('pompeo', 'P000602'),
    'former Member retyped': ('campbell', 'C000077'),
    'ambiguous name resolved to the other Member': ('hill', 'H001087'),
    'wrong one of two': ('levin', 'L000261'),
    'Member Day row naming only the Member left a witness': ('newhouse', None),
    'Member Day row stating only a seat left a witness': ('curtis', None),
    'wrong one of two on a seat row': ('rogers', 'R000572'),
    'outside namesake at a Member Day hearing retyped': ('namesake-at-member-day', 'J000299'),
    "committee member's opening statement left an appearance": ('kaptur-opening', 'K000009'),
    'a Member Day testimony typed a statement': ('newhouse', ('statement', 'N000189')),
    "committee member's opening statement left an appearance, before the rosters": ('dingell-early-opening', 'D000355'),
    "a Senator's opening statement left an appearance, before the rosters": ('baucus-early-opening', 'B000243'),
}
PACKAGES = {'dingell-early-opening': 'CHRG-110hhrg77777', 'pallone-early-opening': 'CHRG-110hhrg77777',
            'baucus-early-opening': 'CHRG-106shrg77778'}
# The prints' own GovInfo HTML transcripts, as the captures table names them: the House form, a suffix before it, and
# the Senate prints' form without 'A'.
TRANSCRIPTS = {'CHRG-110hhrg77777': '<p>OPENING STATEMENT OF HON. JOHN D. DINGELL, A REPRESENTATIVE IN\n CONGRESS FROM MICHIGAN</p>'
                                    '<p>OPENING STATEMENT OF HON. FRANK PALLONE, JR., A REPRESENTATIVE IN CONGRESS FROM THE STATE'
                                    ' OF NEW JERSEY</p>',
               'CHRG-106shrg77778': '<p>OPENING STATEMENT OF HON. MAX BAUCUS, U.S. SENATOR FROM THE STATE OF MONTANA</p>'}
# The prints' own MODS: the committee members each lists (congMember role COMMMEMBER).
PRINT_MEMBERS = {'kaptur-opening': ['K000009', 'A000055']}


def tables(tmp_path):
    other = pa.struct([('first', pa.string()), ('last', pa.string()), ('nickname', pa.string())])
    pq.write_table(pa.table(dict(bioguide_id=[m[0] for m in MEMBERS], name_first=[m[1] for m in MEMBERS],
                                 name_last=[m[2] for m in MEMBERS], name_nickname=[m[3] for m in MEMBERS],
                                 other_names=pa.array([[] for _ in MEMBERS], pa.list_(other)))), tmp_path / 'members.parquet')
    pq.write_table(pa.table(dict(bioguide_id=[m[0] for m in MEMBERS], term_type=[m[4][0] for m in MEMBERS],
                                 term_state=[m[4][1] for m in MEMBERS], term_start=[m[4][2] for m in MEMBERS],
                                 term_end=[m[4][3] for m in MEMBERS], term_district=[m[4][4] for m in MEMBERS])),
                   tmp_path / 'terms.parquet')
    pq.write_table(pa.table(dict(event_id=[m[0] for m in MEETINGS], meeting_date=pa.array(
        [None if m[1] is None else __import__('datetime').date.fromisoformat(m[1]) for m in MEETINGS], pa.date32()),
        title=[m[2] for m in MEETINGS])), tmp_path / 'meetings.parquet')
    keys = list(WITNESSES)
    col = lambda i: [WITNESSES[k][i] for k in keys]
    pq.write_table(pa.table(dict(witness_key=keys, source=col(0), event_id=col(1), package_id=[PACKAGES.get(k) for k in keys], name=col(2),
                                 position=col(3), organization=col(4), on_behalf_of=[None] * len(keys), location=[None] * len(keys),
                                 bioguide_id=col(5), superseded_by=[SUPERSEDED.get(k) for k in keys],
                                 witness_type=['member_appearance' if WITNESSES[k][7] else WITNESSES[k][6] for k in keys],
                                 matched_bioguide_id=col(8),
                                 match_basis=[BASIS.get(k, 'name_state') if WITNESSES[k][7] or WITNESSES[k][8] else None for k in keys],
                                 record_sha=[hashlib.sha256(k.encode()).digest() for k in keys])),
                   tmp_path / 'witnesses.parquet')
    captures = []
    for package, html in TRANSCRIPTS.items():
        digest = hashlib.sha256(html.encode()).hexdigest()
        body = tmp_path / 'bodies' / digest[:2] / f'{digest}.gz'
        body.parent.mkdir(parents=True, exist_ok=True)
        body.write_bytes(gzip.compress(html.encode()))
        captures.append(dict(context_url=f'https://www.govinfo.gov/content/pkg/{package}/html/{package}.htm', sha256=digest,
                             stored_sha256=None))
    pq.write_table(pa.Table.from_pylist(captures, schema=pa.schema([('context_url', pa.string()), ('sha256', pa.string()),
                                                                     ('stored_sha256', pa.string())])), tmp_path / 'captures.parquet')
    for key, members in PRINT_MEMBERS.items():
        digest = hashlib.sha256(key.encode()).hexdigest()
        body = tmp_path / 'bodies' / digest[:2] / f'{digest}.gz'
        body.parent.mkdir(parents=True, exist_ok=True)
        body.write_bytes(gzip.compress(('<mods><extension>' + ''.join(
            f'<congMember bioGuideId="{b}" chamber="H" congress="118" role="COMMMEMBER"/>' for b in members)
            + '</extension></mods>').encode()))


def run(tmp_path, plant=False):
    tables(tmp_path)
    args = ['--witnesses', str(tmp_path / 'witnesses.parquet'), '--members', str(tmp_path / 'members.parquet'),
            '--terms', str(tmp_path / 'terms.parquet'), '--meetings', str(tmp_path / 'meetings.parquet'),
            '--output', str(tmp_path / 'out.json')]
    parser_args = check.argparse.Namespace(witnesses=args[1], members=args[3], terms=args[5], meetings=args[7], output=args[9],
                                           decisions=None, prints=None, plant=plant, mods_bodies=tmp_path / 'bodies',
                                           captures=tmp_path / 'captures.parquet')
    return check.run(parser_args)


def read(tmp_path):
    tables(tmp_path)
    con = check.duckdb.connect()
    ref = check.Reference(con, tmp_path / 'members.parquet', tmp_path / 'terms.parquet')
    rows = check.read_rows(con, tmp_path / 'witnesses.parquet', None, tmp_path / 'meetings.parquet', None)
    return ref, rows, {k: ('statement' if r['statement'] else r['retyped'], r['matched']) for k, r in rows.items()}


def test_the_published_decisions_raise_no_flag_and_the_publisher_labels_agree(tmp_path):
    out = run(tmp_path)
    assert out['flagged'] == []
    assert out['publisher_rows'] == {'expected member, published member': 1, 'expected witness, published witness': 1}
    assert out['cross_publisher']['totals'] == {'same Member': 1}
    assert out['not_read'] == {'record entry': 1, 'no hearing date': 1, 'superseded rows (not judged as left)': 0}


def test_the_seat_and_initial_readings_name_the_member(tmp_path):
    ref, rows, decided = read(tmp_path)
    check.judge(rows, decided, ref)
    assert rows['pomeroy']['found'] == {'P000422': 'seat'}
    assert rows['cox']['found'] == {'C000830': 'initial'}
    assert rows['rogers']['found'] == {'R000575': 'name'}  # the seat's state leaves one Mike Rogers


def test_each_planted_wrong_value_is_flagged(tmp_path):
    ref, rows, decided = read(tmp_path)
    baseline, _p, _n = check.judge(rows, decided, ref, tmp_path / 'bodies', tmp_path / 'captures.parquet')
    results = check.plant_results(rows, decided, baseline, PLANTS, ref)
    assert all(v.startswith('caught') for v in results.values()), results
    assert 'left a witness' in results['member left a witness']
    assert "the hearing's own nominee" in results['nominee retyped']
    assert 'no term covers the date' in results['former Member retyped']
    assert 'first name differs' in results['ambiguous name resolved to the other Member']
    assert results['Member Day row naming only the Member left a witness'] == 'caught: left a witness: names sitting N000189'
    assert results['Member Day row stating only a seat left a witness'] == 'caught: left a witness: names sitting C001114'
    assert results['wrong one of two on a seat row'].endswith('(names R000575; matched R000572)')
    assert "a committee member's own opening statement (the print lists them)" in results[
        "committee member's opening statement left an appearance"]
    assert results['a Member Day testimony typed a statement'] == 'caught: statement: no opening statement in its words (matched N000189)'
    assert "a committee member's own opening statement (the transcript heads it)" in results[
        "committee member's opening statement left an appearance, before the rosters"]
    assert "a committee member's own opening statement (the transcript heads it)" in results[
        "a Senator's opening statement left an appearance, before the rosters"]
    # Only because the hearing also hears an outside witness: the row alone cannot tell the namesake from the Member.
    assert 'a name alone at a Member Day hearing that also hears outside witnesses' in results[
        'outside namesake at a Member Day hearing retyped']


def test_another_publishers_copy_is_graded_against_the_publisher_id(tmp_path):
    ref, rows, decided = read(tmp_path)
    check.judge(rows, decided, ref)
    rows['publisher-copy']['basis'] = 'group'
    assert check.cross_publisher(rows, decided, ref)['totals'] == {'silent: matched only through the appearance': 1}
    rows['publisher-copy']['basis'] = 'name_chamber'
    decided['publisher-copy'] = (True, 'H001072')
    assert check.cross_publisher(rows, decided, ref)['totals'] == {'DIFFERENT Member': 1}


def test_a_publisher_label_contradicted_either_way_is_flagged(tmp_path):
    ref, rows, decided = read(tmp_path)
    decided['publisher-sitting'] = (False, None)
    decided['publisher-former'] = (True, 'W000789')
    flags, publisher, _n = check.judge(rows, decided, ref)
    assert flags['publisher-sitting'] == 'publisher id in office, left a witness'
    assert flags['publisher-former'] == 'publisher id not in office or nominee, retyped'
    assert publisher == {(True, False): 1, (False, True): 1}
