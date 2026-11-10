"""The Member appearance raw check reads its own way and flags each of the six planted wrong values (ct-kw85).

Hand rows: a Member rightly retyped (Reyes), an outside witness with a sitting Senator's name (Johnson of Corning),
the hearing's own nominee (Pompeo), a former Member (Campbell), a Member whose namesake also sits (French Hill beside
Katie Hill), two Levins, the publisher's own IDs in both directions, and rows the check cannot read.
"""
import importlib.util
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).parents[3]
spec = importlib.util.spec_from_file_location('member_appearances_raw_check', ROOT / 'scripts/measure/member_appearances_raw_check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

MEMBERS = [  # bioguide, first, last, nickname, (term type, state, start, end)
    ('R000170', 'Silvestre', 'Reyes', None, ('rep', 'TX', '1997-01-07', '2013-01-03')),
    ('J000177', 'Tim', 'Johnson', None, ('sen', 'SD', '1997-01-07', '2015-01-03')),
    ('P000602', 'Mike', 'Pompeo', None, ('rep', 'KS', '2011-01-05', '2017-01-23')),
    ('C000077', 'Ben', 'Campbell', None, ('sen', 'CO', '1993-01-05', '2005-01-03')),
    ('H001072', 'J.', 'Hill', 'French', ('rep', 'AR', '2015-01-06', '2027-01-03')),
    ('H001087', 'Katie', 'Hill', None, ('rep', 'CA', '2019-01-03', '2019-11-03')),
    ('L000263', 'Sander', 'Levin', None, ('rep', 'MI', '1983-01-03', '2019-01-03')),
    ('L000261', 'Carl', 'Levin', None, ('sen', 'MI', '1979-01-15', '2015-01-03')),
    ('W000789', 'Heather', 'Wilson', None, ('rep', 'NM', '1998-06-25', '2009-01-03')),
    ('B001257', 'Gus', 'Bilirakis', None, ('rep', 'FL', '2007-01-04', '2027-01-03')),
    ('C001049', 'Wm.', 'Clay', None, ('rep', 'MO', '2001-01-03', '2021-01-03')),
]
MEETINGS = [(1, '2007-05-01', 'Border security'), (2, '2013-09-24', 'Black carbon'),
            (3, '2017-01-12', 'Nomination of Mike Pompeo to be Director of the Central Intelligence Agency'),
            (4, '2017-07-07', 'Public lands'), (5, '2019-09-10', 'Banking'), (6, '2009-04-01', 'Trade'),
            (7, '2015-04-23', 'Health'), (8, '2025-02-05', 'Defense'), (9, None, 'Undated'), (10, '2019-09-11', 'Ferguson')]
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
    'undated': ('mods', 9, 'Silvestre Reyes', 'a Representative in Congress from the State of Texas', None, None, None, False, None),
    'letter': ('mods', 1, 'Letter from the Sheriff', None, None, None, 'record_material', False, None),
}
PLANTS = {
    'member left a witness': ('reyes', None),
    'outside witness retyped': ('johnson', 'J000177'),
    'nominee retyped': ('pompeo', 'P000602'),
    'former Member retyped': ('campbell', 'C000077'),
    'ambiguous name resolved to the other Member': ('hill', 'H001087'),
    'wrong one of two': ('levin', 'L000261'),
}


def tables(tmp_path):
    other = pa.struct([('first', pa.string()), ('last', pa.string()), ('nickname', pa.string())])
    pq.write_table(pa.table(dict(bioguide_id=[m[0] for m in MEMBERS], name_first=[m[1] for m in MEMBERS],
                                 name_last=[m[2] for m in MEMBERS], name_nickname=[m[3] for m in MEMBERS],
                                 other_names=pa.array([[] for _ in MEMBERS], pa.list_(other)))), tmp_path / 'members.parquet')
    pq.write_table(pa.table(dict(bioguide_id=[m[0] for m in MEMBERS], term_type=[m[4][0] for m in MEMBERS],
                                 term_state=[m[4][1] for m in MEMBERS], term_start=[m[4][2] for m in MEMBERS],
                                 term_end=[m[4][3] for m in MEMBERS])), tmp_path / 'terms.parquet')
    pq.write_table(pa.table(dict(event_id=[m[0] for m in MEETINGS], meeting_date=pa.array(
        [None if m[1] is None else __import__('datetime').date.fromisoformat(m[1]) for m in MEETINGS], pa.date32()),
        title=[m[2] for m in MEETINGS])), tmp_path / 'meetings.parquet')
    keys = list(WITNESSES)
    col = lambda i: [WITNESSES[k][i] for k in keys]
    pq.write_table(pa.table(dict(witness_key=keys, source=col(0), event_id=col(1), package_id=[None] * len(keys), name=col(2),
                                 position=col(3), organization=col(4), on_behalf_of=[None] * len(keys), location=[None] * len(keys),
                                 bioguide_id=col(5), superseded_by=[None] * len(keys),
                                 witness_type=['member_appearance' if WITNESSES[k][7] else WITNESSES[k][6] for k in keys],
                                 matched_bioguide_id=col(8))), tmp_path / 'witnesses.parquet')


def run(tmp_path, plant=False):
    tables(tmp_path)
    args = ['--witnesses', str(tmp_path / 'witnesses.parquet'), '--members', str(tmp_path / 'members.parquet'),
            '--terms', str(tmp_path / 'terms.parquet'), '--meetings', str(tmp_path / 'meetings.parquet'),
            '--output', str(tmp_path / 'out.json')]
    parser_args = check.argparse.Namespace(witnesses=args[1], members=args[3], terms=args[5], meetings=args[7], output=args[9],
                                           decisions=None, prints=None, plant=plant)
    return check.run(parser_args)


def test_the_published_decisions_raise_no_flag_and_the_publisher_labels_agree(tmp_path):
    out = run(tmp_path)
    assert out['flagged'] == []
    assert out['publisher_examples'] == {'expected member, published member': 1, 'expected witness, published witness': 1}
    assert out['not_read'] == {'record entry': 1, 'no hearing date': 1, 'superseded rows (not judged as left)': 0}


def test_each_planted_wrong_value_is_flagged(tmp_path):
    run(tmp_path)
    con = check.duckdb.connect()
    names, spans, by_family = check.load_members(con, tmp_path / 'members.parquet', tmp_path / 'terms.parquet')
    rows = check.read_rows(con, tmp_path / 'witnesses.parquet', None, tmp_path / 'meetings.parquet', None)
    decided = {k: (r['retyped'], r['matched']) for k, r in rows.items()}
    baseline, _p, _n = check.judge(rows, decided, names, spans, by_family)
    results = check.plant_results(rows, decided, baseline, PLANTS, names, spans, by_family)
    assert all(v.startswith('caught') for v in results.values()), results
    assert 'left a witness' in results['member left a witness']
    assert "the hearing's own nominee" in results['nominee retyped']
    assert 'no term covers the date' in results['former Member retyped']
    assert 'first name differs' in results['ambiguous name resolved to the other Member']


def test_a_publisher_label_contradicted_either_way_is_flagged(tmp_path):
    tables(tmp_path)
    con = check.duckdb.connect()
    names, spans, by_family = check.load_members(con, tmp_path / 'members.parquet', tmp_path / 'terms.parquet')
    rows = check.read_rows(con, tmp_path / 'witnesses.parquet', None, tmp_path / 'meetings.parquet', None)
    decided = {k: (r['retyped'], r['matched']) for k, r in rows.items()}
    decided['publisher-sitting'] = (False, None)
    decided['publisher-former'] = (True, 'W000789')
    flags, publisher, _n = check.judge(rows, decided, names, spans, by_family)
    assert flags['publisher-sitting'] == 'publisher id in office, left a witness'
    assert flags['publisher-former'] == 'publisher id not in office or nominee, retyped'
    assert publisher == {(True, False): 1, (False, True): 1}
