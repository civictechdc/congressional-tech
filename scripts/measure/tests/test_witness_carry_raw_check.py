"""Bidirectional raw check tests for ct-46f3 witness carry and witness_key_map."""
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import witness_carry_raw_check as carry_check  # noqa: E402


def _stage_carry_fixture(tmp_path: Path):
    mirror = tmp_path / 'mirror'
    before_dir = tmp_path / 'before'
    after_dir = tmp_path / 'after'
    before_dir.mkdir(parents=True)
    after_dir.mkdir(parents=True)

    cg_before_obj = {
        'committeeMeeting': {
            'eventId': '118500',
            'witnesses': [
                {'name': 'Ms. Clara Alpha', 'position': 'Chair', 'organization': 'Alpha Org'},
                {'name': 'Mr. David Beta', 'position': 'Counsel', 'organization': 'Beta Org'},
                {'name': 'Mr. Jon Typo-Smyth', 'position': 'Analyst', 'organization': 'Gamma Org'},
            ],
        },
    }
    cg_after_obj = {
        'committeeMeeting': {
            'eventId': '118500',
            'witnesses': [
                {'name': 'Mr. David Beta', 'position': 'Counsel', 'organization': 'Beta Org'},
                {'name': 'Ms. Clara Alpha', 'position': 'Chair', 'organization': 'Alpha Org'},
                {'name': 'Mr. Jonathan Typo-Smith', 'position': 'Analyst', 'organization': 'Gamma Org'},
            ],
        },
    }
    line1 = json.dumps(cg_before_obj, separators=(',', ':')).encode()
    line2 = json.dumps(cg_after_obj, separators=(',', ':')).encode()
    sha_cg1 = sha256(line1).hexdigest()
    sha_cg2 = sha256(line2).hexdigest()

    rec_file = mirror / 'receipts/congress/meetings/2026-11-10/slice.jsonl'
    rec_file.parent.mkdir(parents=True, exist_ok=True)
    rec_file.write_bytes(line1 + b'\n' + line2 + b'\n')

    mods_xml = (
        b'<mods xmlns="http://www.loc.gov/mods/v3">'
        b'<extension><witness>Hon. Evelyn Print, Director, Print Bureau</witness></extension>'
        b'</mods>'
    )
    sha_mods = sha256(mods_xml).hexdigest()
    mods_body = mirror / 'bodies/sha256' / sha_mods[:2] / f'{sha_mods}.gz'
    mods_body.parent.mkdir(parents=True, exist_ok=True)
    mods_body.write_bytes(gzip.compress(mods_xml))

    before_witnesses = [
        {
            'witness_key': '1111aaaa1111aaaa',
            'occasion': 'meeting:118500',
            'event_id': 118500,
            'package_id': None,
            'source': 'congress_gov',
            'record_sha': bytes.fromhex(sha_cg1),
            'source_locator': 'congress_gov:witness[1]',
            'name': 'Ms. Clara Alpha',
            'position': 'Chair',
            'organization': 'Alpha Org',
        },
        {
            'witness_key': '2222bbbb2222bbbb',
            'occasion': 'meeting:118500',
            'event_id': 118500,
            'package_id': None,
            'source': 'congress_gov',
            'record_sha': bytes.fromhex(sha_cg1),
            'source_locator': 'congress_gov:witness[2]',
            'name': 'Mr. David Beta',
            'position': 'Counsel',
            'organization': 'Beta Org',
        },
        {
            'witness_key': '3333cccc3333cccc',
            'occasion': 'meeting:118500',
            'event_id': 118500,
            'package_id': None,
            'source': 'congress_gov',
            'record_sha': bytes.fromhex(sha_cg1),
            'source_locator': 'congress_gov:witness[3]',
            'name': 'Mr. Jon Typo-Smyth',
            'position': 'Analyst',
            'organization': 'Gamma Org',
        },
        {
            'witness_key': '4444dddd4444dddd',
            'occasion': 'package:CHRG-118hhrg500',
            'event_id': None,
            'package_id': 'CHRG-118hhrg500',
            'source': 'mods',
            'record_sha': bytes.fromhex(sha_mods),
            'source_locator': 'mods:witness[1]',
            'name': 'Hon. Evelyn Print',
            'position': 'Director',
            'organization': 'Print Bureau',
        },
    ]
    before_map = [
        {
            'old_key': '0000999900009999',
            'witness_key': '3333cccc3333cccc',
            'status': 'unambiguous',
            'basis': 'locator',
            'candidate_keys': [],
        },
    ]

    # After: Clara and David swap display positions on re-fetch yet keep their keys via Tier 2;
    # Evelyn's print binds to meeting:118500 yet keeps her key via Tier 1;
    # Jon Typo-Smyth -> Jonathan Typo-Smith mints 5555eeee5555eeee and maps 3333cccc + 1-hop 00009999 -> 5555eeee!
    after_witnesses = [
        {
            'witness_key': '2222bbbb2222bbbb',
            'occasion': 'meeting:118500',
            'event_id': 118500,
            'package_id': None,
            'source': 'congress_gov',
            'record_sha': bytes.fromhex(sha_cg2),
            'source_locator': 'congress_gov:witness[1]',
            'name': 'Mr. David Beta',
            'position': 'Counsel',
            'organization': 'Beta Org',
        },
        {
            'witness_key': '1111aaaa1111aaaa',
            'occasion': 'meeting:118500',
            'event_id': 118500,
            'package_id': None,
            'source': 'congress_gov',
            'record_sha': bytes.fromhex(sha_cg2),
            'source_locator': 'congress_gov:witness[2]',
            'name': 'Ms. Clara Alpha',
            'position': 'Chair',
            'organization': 'Alpha Org',
        },
        {
            'witness_key': '5555eeee5555eeee',
            'occasion': 'meeting:118500',
            'event_id': 118500,
            'package_id': None,
            'source': 'congress_gov',
            'record_sha': bytes.fromhex(sha_cg2),
            'source_locator': 'congress_gov:witness[3]',
            'name': 'Mr. Jonathan Typo-Smith',
            'position': 'Analyst',
            'organization': 'Gamma Org',
        },
        {
            'witness_key': '4444dddd4444dddd',
            'occasion': 'meeting:118500',
            'event_id': 118500,
            'package_id': 'CHRG-118hhrg500',
            'source': 'mods',
            'record_sha': bytes.fromhex(sha_mods),
            'source_locator': 'mods:witness[1]',
            'name': 'Hon. Evelyn Print',
            'position': 'Director',
            'organization': 'Print Bureau',
        },
    ]
    after_map = [
        {
            'old_key': '3333cccc3333cccc',
            'witness_key': '5555eeee5555eeee',
            'status': 'unambiguous',
            'basis': 'locator',
            'candidate_keys': [],
        },
        {
            'old_key': '0000999900009999',
            'witness_key': '5555eeee5555eeee',
            'status': 'unambiguous',
            'basis': 'locator',
            'candidate_keys': [],
        },
    ]

    map_schema = pa.schema([
        ('old_key', pa.string()),
        ('witness_key', pa.string()),
        ('status', pa.string()),
        ('basis', pa.string()),
        ('candidate_keys', pa.list_(pa.string())),
    ])
    pq.write_table(pa.Table.from_pylist(before_witnesses), before_dir / 'witnesses.parquet')
    pq.write_table(pa.Table.from_pylist(before_map, schema=map_schema), before_dir / 'witness_key_map.parquet')
    pq.write_table(pa.Table.from_pylist(after_witnesses), after_dir / 'witnesses.parquet')
    pq.write_table(pa.Table.from_pylist(after_map, schema=map_schema), after_dir / 'witness_key_map.parquet')
    return before_dir, after_dir, mirror


def test_clean_carry_reads_raw_json_and_mods_bytes_and_catches_all_three_plants(tmp_path):
    before_dir, after_dir, mirror = _stage_carry_fixture(tmp_path)
    out = tmp_path / 'carry-report.json'
    report = carry_check.main([
        '--before', str(before_dir),
        '--after', str(after_dir),
        '--mirror', str(mirror),
        '--plant',
        '--output', str(out),
    ])
    assert report['flag_count'] == 0
    assert report['counts']['before_raw_bytes_read'] == 4
    assert report['counts']['after_raw_bytes_read'] == 4
    assert report['counts']['carried_witness_keys'] == 3
    assert report['counts']['newly_mapped_witness_keys'] == 1
    assert report['counts']['carried_map_rows'] == 1
    assert report['plants']['swapped_keys']['caught'] is True
    assert report['plants']['dropped_map_row']['caught'] is True
    assert report['plants']['unchanged_entry_rekeyed']['caught'] is True
    assert report['unread_raw_records'] == []


def test_swapped_keys_with_shared_given_or_family_name_are_flagged(tmp_path):
    before_dir, after_dir, _ = _stage_carry_fixture(tmp_path)
    before_w = pq.read_table(before_dir / 'witnesses.parquet').to_pylist()
    after_w = pq.read_table(after_dir / 'witnesses.parquet').to_pylist()
    after_m = pq.read_table(after_dir / 'witness_key_map.parquet').to_pylist()
    empty_store = carry_check.RawEntryStore(None)

    # Shared given name ('Mr. John Alpha' vs 'Mr. John Beta') with swapped witness_keys must fire swapped_witness_key
    b_given = [dict(r) for r in before_w]
    a_given = [dict(r) for r in after_w]
    b_given[0]['name'] = 'Mr. John Alpha'   # 1111aaaa
    b_given[1]['name'] = 'Mr. John Beta'    # 2222bbbb
    a_given[0]['name'] = 'Mr. John Alpha'   # 2222bbbb (swapped!)
    a_given[1]['name'] = 'Mr. John Beta'    # 1111aaaa (swapped!)
    res_given = carry_check.evaluate(b_given, [], a_given, after_m, empty_store)
    assert res_given['flags_by_kind'].get('swapped_witness_key') == 2

    # Shared family name ('Robert Smith Sr.' vs 'James Smith Jr.') with swapped witness_keys must fire swapped_witness_key
    b_fam = [dict(r) for r in before_w]
    a_fam = [dict(r) for r in after_w]
    b_fam[0]['name'] = 'Robert Smith Sr.'   # 1111aaaa
    b_fam[1]['name'] = 'James Smith Jr.'    # 2222bbbb
    a_fam[0]['name'] = 'Robert Smith Sr.'   # 2222bbbb (swapped!)
    a_fam[1]['name'] = 'James Smith Jr.'    # 1111aaaa (swapped!)
    res_fam = carry_check.evaluate(b_fam, [], a_fam, after_m, empty_store)
    assert res_fam['flags_by_kind'].get('swapped_witness_key') == 2
