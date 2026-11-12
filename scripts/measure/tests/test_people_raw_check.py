"""Bidirectional raw check tests for ct-ha10 people and person_aliases."""
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import people_raw_check as people_check  # noqa: E402


def _stage_people_fixture(tmp_path: Path):
    before_dir = tmp_path / 'before'
    release_dir = tmp_path / 'release'
    before_dir.mkdir(parents=True)
    release_dir.mkdir(parents=True)

    members = [
        {'bioguide_id': 'A000370', 'name_first': 'Alma', 'name_last': 'Adams'},
    ]
    meetings = [
        {'event_id': 1001, 'meeting_date': '2024-03-10'},
        {'event_id': 1002, 'meeting_date': '2025-06-15'},
    ]
    witnesses = [
        {
            'witness_key': 'w_mem_1',
            'person_key': 'A000370',
            'occasion': 'meeting:1001',
            'event_id': 1001,
            'name': 'Rep. Alma S. Adams',
            'organization': 'U.S. House of Representatives',
            'position': 'Representative',
            'witness_type': 'member_appearance',
            'bioguide_id': 'A000370',
            'matched_bioguide_id': 'A000370',
            'superseded_by': None,
        },
        {
            'witness_key': 'w_jane_1',
            'person_key': 'pk_jane_alpha',
            'occasion': 'meeting:1001',
            'event_id': 1001,
            'name': 'Dr. Jane M. Doe',
            'organization': 'Alpha Energy Institute',
            'position': 'Director',
            'witness_type': 'non_government',
            'bioguide_id': None,
            'matched_bioguide_id': None,
            'superseded_by': None,
        },
        {
            'witness_key': 'w_jane_2',
            'person_key': 'pk_jane_alpha',
            'occasion': 'meeting:1002',
            'event_id': 1002,
            'name': 'Dr. Jane M. Doe',
            'organization': 'Alpha Energy Institute',
            'position': 'Senior Director',
            'witness_type': 'non_government',
            'bioguide_id': None,
            'matched_bioguide_id': None,
            'superseded_by': None,
        },
        {
            'witness_key': 'w_jane_sup',
            'person_key': 'pk_jane_alpha',
            'occasion': 'meeting:1002',
            'event_id': 1002,
            'name': 'Doe, Jane M.',
            'organization': 'Alpha Energy Institute',
            'position': 'Senior Director',
            'witness_type': 'non_government',
            'bioguide_id': None,
            'matched_bioguide_id': None,
            'superseded_by': 'w_jane_2',
        },
        {
            'witness_key': 'w_other_1',
            'person_key': 'pk_other_beta',
            'occasion': 'meeting:1002',
            'event_id': 1002,
            'name': 'Mr. Carlos Rivera',
            'organization': 'Beta Grid Council',
            'position': 'President',
            'witness_type': 'non_government',
            'bioguide_id': None,
            'matched_bioguide_id': None,
            'superseded_by': None,
        },
    ]
    people = [
        {
            'person_key': 'A000370',
            'bioguide_id': 'A000370',
            'name': 'Rep. Alma S. Adams',
            'grouping_basis': 'bioguide',
            'witness_keys': ['w_mem_1'],
        },
        {
            'person_key': 'pk_jane_alpha',
            'bioguide_id': None,
            'name': 'Dr. Jane M. Doe',
            'grouping_basis': 'name_organization',
            'witness_keys': ['w_jane_1', 'w_jane_2'],
        },
        {
            'person_key': 'pk_other_beta',
            'bioguide_id': None,
            'name': 'Mr. Carlos Rivera',
            'grouping_basis': 'singleton',
            'witness_keys': ['w_other_1'],
        },
    ]
    before_people = [
        people[0],
        {
            'person_key': 'pk_jane_old_singleton',
            'bioguide_id': None,
            'name': 'Dr. Jane M. Doe',
            'grouping_basis': 'singleton',
            'witness_keys': ['w_jane_1'],
        },
    ]
    aliases = [
        {
            'old_person_key': 'pk_jane_old_singleton',
            'person_key': 'pk_jane_alpha',
            'status': 'unambiguous',
            'kind': 'merged',
            'candidate_keys': [],
        },
    ]

    members_pq = tmp_path / 'members.parquet'
    pq.write_table(pa.Table.from_pylist(members), members_pq)
    pq.write_table(pa.Table.from_pylist(before_people), before_dir / 'people.parquet')
    pq.write_table(pa.Table.from_pylist(people), release_dir / 'people.parquet')
    pq.write_table(pa.Table.from_pylist(witnesses), release_dir / 'witnesses.parquet')
    pq.write_table(pa.Table.from_pylist(meetings), release_dir / 'meetings.parquet')
    pq.write_table(pa.Table.from_pylist(aliases), release_dir / 'person_aliases.parquet')
    return release_dir, before_dir, members_pq, people, witnesses, meetings, aliases, before_people, members


def test_clean_people_release_passes_both_directions_and_catches_all_three_plants(tmp_path):
    release_dir, before_dir, members_pq, *_ = _stage_people_fixture(tmp_path)
    out = tmp_path / 'people-report.json'
    report = people_check.main([
        '--release', str(release_dir),
        '--before', str(before_dir),
        '--members', str(members_pq),
        '--plant',
        '--output', str(out),
    ])
    assert report['flag_count'] == 0
    assert report['counts']['carried_person_keys'] == 1
    assert report['counts']['aliased_person_keys'] == 1
    assert report['plants']['cross_org_merge']['caught'] is True
    assert report['plants']['conflicting_middle_merge']['caught'] is True
    assert report['plants']['missed_exact_merge']['caught'] is True


def test_flags_lost_person_key_suffix_conflict_and_superseded_mismatch(tmp_path):
    _, _, _, people, witnesses, meetings, _, before_people, members = _stage_people_fixture(tmp_path)
    # Drop alias -> lost_person_key; break superseded inheritance; plant Jr. vs Sr. suffix conflict
    w_bad = [dict(w) for w in witnesses]
    w_bad[1]['name'] = 'Dr. Jane M. Doe, Jr.'
    w_bad[2]['name'] = 'Dr. Jane M. Doe, Sr.'
    w_bad[3]['person_key'] = 'pk_other_beta'
    res = people_check.evaluate(people, w_bad, meetings, alias_rows=[], before_people=before_people, member_rows=members)
    assert res['flags_by_kind'] == {
        'superseded_person_key_mismatch': 1,
        'conflicting_middle_or_suffix': 1,
        'lost_person_key': 1,
    }


def test_raw_mods_dates_spelled_out_middle_names_member_terms_and_alias_carry(tmp_path):
    import gzip
    from hashlib import sha256

    release_dir, before_dir, members_pq, people, witnesses, meetings, aliases, before_people, members = _stage_people_fixture(tmp_path)

    # Stage a raw MODS XML body with placeholder '1933-03-01' + valid '2009-12-09' heldDates
    mods_bytes = (
        b'<mods><originInfo><dateIssued>2009-12-09</dateIssued></originInfo>'
        b'<extension><heldDate>1933-03-01</heldDate><heldDate>2009-12-09</heldDate>'
        b'<congCommittee><witness>Ben Shelly</witness></congCommittee></extension></mods>'
    )
    mods_sha = sha256(mods_bytes).hexdigest()
    bodies_dir = tmp_path / 'bodies/sha256' / mods_sha[:2]
    bodies_dir.mkdir(parents=True)
    (bodies_dir / f'{mods_sha}.gz').write_bytes(gzip.compress(mods_bytes))

    # Add MODS witness + person with corrupted 1933 first_seen_date -> must flag person_date_bounds_mismatch & implausible_date_span
    w_ext = [dict(w) for w in witnesses] + [
        {
            'witness_key': 'w_mods_1',
            'person_key': 'pk_jane_alpha',
            'occasion': 'package:CHRG-111shrg57186',
            'event_id': None,
            'package_id': 'CHRG-111shrg57186',
            'source': 'mods',
            'record_sha': bytes.fromhex(mods_sha),
            'source_locator': 'mods:witness[1]',
            'name': 'Dr. Jane M. Doe',
            'organization': 'Alpha Energy Institute',
            'position': 'Director',
            'witness_type': 'non_government',
            'bioguide_id': None,
            'matched_bioguide_id': None,
            'superseded_by': None,
        },
    ]
    p_ext = [dict(p) for p in people]
    p_ext[1] = {
        **p_ext[1],
        'witness_keys': ['w_jane_1', 'w_jane_2', 'w_mods_1'],
        'first_seen_date': '1933-03-01',
        'last_seen_date': '2025-06-15',
    }
    # Spelled-out same-initial conflicting middle names ('Jane Marie Doe' vs 'Jane Michelle Doe')
    w_ext[1]['name'] = 'Dr. Jane Marie Doe'
    w_ext[2]['name'] = 'Dr. Jane Michelle Doe'
    # Member outside term (>50y) and dropped before_alias
    terms = [{'bioguide_id': 'A000370', 'term_start': '1950-01-03', 'term_end': '1955-01-03'}]
    before_aliases = [{'old_person_key': 'pk_prior_alias', 'person_key': 'A000370', 'status': 'unambiguous', 'kind': 'merged', 'candidate_keys': []}]

    raw_store = people_check.RawPeopleStore(bodies_dirs=[tmp_path / 'bodies/sha256'], wanted_shas={mods_sha})
    res = people_check.evaluate(
        p_ext, w_ext, meetings, aliases, before_people, members,
        before_aliases=before_aliases, term_rows=terms, raw_store=raw_store,
    )
    assert res['counts']['raw_mods_witnesses_read'] == 1
    assert res['flags_by_kind'] == {
        'person_date_bounds_mismatch': 1,
        'conflicting_middle_or_suffix': 1,
        'implausible_date_span': 1,
        'member_outside_term': 1,
        'dropped_person_alias_row': 1,
    }
