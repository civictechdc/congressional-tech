"""The transcript appearance raw check (ct-sfra) reads speaker turns and the members present, flags both directions
and catches each of its four plants on hand rows."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

SPEC = importlib.util.spec_from_file_location('transcript_appearance_raw_check',
                                              Path(__file__).parents[1] / 'transcript_appearance_raw_check.py')
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)

PRINT = """<html><body><pre>
                        WEDNESDAY, APRIL 25, 2012

    The subcommittee met, pursuant to call, at 10:00 a.m.
    Members present: Representatives Thompson, Pingree, G.K.
Butterfield, and Peterson (ex officio).
    Also present: Representative Noem.
    Staff present: John Konya.

    Mr. Thompson. Good morning. I recognize Mrs. Noem.
    Mrs. NOEM. Thank you, Mr. Chairman.
    Senator Gorton. I thank the committee.
    Mr. Groat [continuing]. The survey found the disease.
    Mr. Butterfield of North Carolina. I yield back.
    Senator Reid. I thank the chairman.
    Mr. Valenti. Thank you.
    [Whereupon, at 4:15 p.m., the subcommittee was adjourned.]
</pre></body></html>"""
ROWS = [
    # witness_key, name, position, organization, type now, type before, matched Member
    ('noem', 'Kristi L. Noem', 'a Representative in Congress', None, 'member_appearance', 'member_appearance', 'N1'),
    ('gorton', 'Slade Gorton', 'a U.S. Senator', 'prepared statement', 'member_statement', None, 'G1'),
    ('mccollum', 'Bill McCollum', 'a Representative in Congress', 'prepared statement', 'member_statement', None, 'M1'),
    ('pingree', 'Chellie Pingree', 'a Representative in Congress', 'opening statement', 'member_appearance', None, 'P1'),
    ('thompson', 'Glenn Thompson', 'a Representative in Congress', 'opening statement', 'member_statement', 'member_appearance',
     'T1'),
    ('reid', 'Harry Reid', 'a U.S. Senator', 'statement', 'member_appearance', 'member_appearance', 'R1'),
    ('quiet-entry', 'Jo Paper', 'Director', None, 'statement_for_record', 'statement_for_record', None),
    ('valenti', 'Jack Valenti', 'President', None, None, 'statement_for_record', None),
    ('quiet-member', 'Ann Quiet', 'a Representative in Congress', 'prepared statement', 'member_appearance', 'member_appearance',
     'Q1'),
    ('groat', 'Charles G. Groat', 'Director', 'U.S. Geological Survey', 'statement_for_record', 'statement_for_record', None),
    ('abbott', 'Dona Abbott', 'Vice President', None, None, 'statement_for_record', None),
    ('butterfield', 'G.K. Butterfield', 'a Representative in Congress', 'prepared statement', 'member_statement', None, 'B1'),
    ('witness', 'Ann Lee', 'Professor', None, None, None, None),
    ('elsewhere', 'Ann Other', 'Professor', None, 'statement_for_record', 'statement_for_record', None),
]


def write(tmp_path, rows=ROWS):
    sha = hashlib.sha256(PRINT.encode()).hexdigest()
    (tmp_path / 'bodies' / sha[:2]).mkdir(parents=True)
    (tmp_path / 'bodies' / sha[:2] / f'{sha}.gz').write_bytes(gzip.compress(PRINT.encode()))
    pq.write_table(pa.table(dict(context_url=['https://www.govinfo.gov/content/pkg/CHRG-112hhrg1/html/CHRG-112hhrg1.htm'],
                                 sha256=[sha], stored_sha256=[None])), tmp_path / 'captures.parquet')
    for name, index in (('witnesses', 4), ('before', 5)):
        table = dict(witness_key=[r[0] for r in rows], source=['mods'] * len(rows),
                     package_id=['CHRG-112hhrg1' if r[0] != 'elsewhere' else 'CHRG-112hhrg2' for r in rows],
                     name=[r[1] for r in rows], position=[r[2] for r in rows], organization=[r[3] for r in rows],
                     on_behalf_of=[None] * len(rows), location=[None] * len(rows),
                     witness_type=pa.array([r[index] for r in rows], pa.string()),
                     matched_bioguide_id=pa.array([r[6] for r in rows], pa.string()))
        pq.write_table(pa.table(table), tmp_path / f'{name}.parquet')


def run(tmp_path, *extra):
    out = tmp_path / 'out.json'
    assert check.main(['--witnesses', str(tmp_path / 'witnesses.parquet'), '--before', str(tmp_path / 'before.parquet'),
                       '--captures', str(tmp_path / 'captures.parquet'), '--bodies', str(tmp_path / 'bodies'),
                       '--output', str(out), *extra]) == 0
    return json.loads(out.read_text())


def test_turns_and_members_present_are_read_in_the_checks_own_words():
    spoke, present = check.transcript_facts(PRINT)
    assert {'thompson', 'noem', 'gorton', 'groat', 'butterfield'} <= spoke and 'mccollum' not in spoke
    assert present == {'thompson', 'pingree', 'butterfield', 'peterson'}  # not Noem ('Also present') nor staff


def test_both_directions_are_flagged_and_every_row_not_read_is_counted(tmp_path):
    write(tmp_path)
    report = run(tmp_path)
    flags = {k: v['flag'] for k, v in report['flagged'].items()}
    assert flags == {'gorton': 'statement_spoke',          # spoke, not a member present: testified
                     'pingree': 'committee_appearance',    # a member present, her opening statement taken as testimony
                     'groat': 'entry_spoke',                # a record entry who spoke
                     'abbott': 'promoted_silent',           # promoted from a record entry, never spoke
                     'quiet-member': 'appearance_silent'}   # kept an appearance, never spoke (a lead)
    # McCollum (silent statement), Thompson and Butterfield (members present) and Noem (spoke) agree; the plain witness
    # is out of scope; the other print has no transcript held.
    assert report['agree'] == {'member_statement': 3, 'member_appearance': 2, 'statement_for_record': 1, 'witness': 1}
    assert report['not_read'] == {'no transcript held': 1}


def test_each_plant_is_laid_from_the_rules_side_and_its_misses_are_named(tmp_path):
    # Rows chosen by the run's own types and words, never by turns: kept appearances whose words name a statement (Reid,
    # and Quiet, who never spoke), record entries in both runs (Groat, who spoke, and Paper), rows the run promoted
    # (Valenti, and Abbott, who never spoke) and an opening the run made a statement (Thompson). Planted on a person who
    # spoke or stayed silent where the check cannot tell, the wrong value is missed, by name.
    write(tmp_path)
    plants = run(tmp_path, '--plant')['plants']
    assert {name: (p['eligible'], p['caught'], [m['key'] for m in p['missed']]) for name, p in plants.items()} == {
        'testifying member typed member_statement': (2, 1, ['quiet-member']),
        'submission typed witness': (2, 1, ['groat']),
        'answerer who testified typed statement_for_record': (2, 1, ['abbott']),
        'committee member heading taken for testimony': (1, 1, []),
    }
