"""Occurrence accounting must retain ambiguity, role evidence and original records."""
import csv
import gzip
from hashlib import sha256
import json
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from measure.legacy_witness_occurrences import (
    FILES, HouseEvidence, agrees, disposition, load_legacy, run, scope,
)


def native(key='tribe', **changes):
    return dict(witness_key=key, source='house_xml', event_id=100520,
                package_id=None, page_url=None, name='W. Ron Allen',
                position='Chairman', organization='Tribe', panel='1',
                on_behalf_of=None, location=None, witness_type=None, bioguide_id=None,
                testified=None, superseded_by=None, record_sha=b'x' * 32,
                source_locator='house_xml:panel[1]/witness[1]', **changes)


def legacy(**changes):
    return dict(source='house_xml', origin='calendar', fields=dict(
        event_id='100520', name='W. Ron Allen', position='Chairman',
        organization='Tribe', **changes))


def test_distinct_roles_do_not_satisfy_each_other():
    row = native()
    row['position'] = 'Commissioner'
    assert disposition(legacy(), [row])['status'] == 'source_fields_differ'


def test_identical_thin_rows_do_not_choose_between_distinct_representations():
    first, second = native('first'), native('second')
    second['on_behalf_of'] = 'Tribal Interior Budget Council'
    result = disposition(legacy(), [first, second])
    assert result['status'] == 'ambiguous_source_occurrence'
    assert result['matched_keys'] == ['first', 'second']
    assert disposition(legacy(behalf_of='Tribal Interior Budget Council'), [first, second])['matched_keys'] == ['second']


def test_a_matching_person_at_a_different_event_is_not_migrated():
    row = native()
    row['event_id'] = None
    assert disposition(legacy(), [row])['status'] == 'retained_without_legacy_event_binding'
    row['event_id'] = 100521
    assert disposition(legacy(), [row])['status'] == 'retained_without_legacy_event_binding'


def test_superseded_rows_are_reported_separately():
    row = native()
    row['superseded_by'] = 'successor'
    assert disposition(legacy(), [row])['status'] == 'candidate_historical_field_match'


def test_missing_source_and_missing_role_are_not_invented_causes():
    assert disposition(legacy(), [])['status'] == 'no_selected_same_name_source_occurrence'
    assert scope(dict(legacy(), source='mods', origin='CHRG-A')) == ('mods', 'CHRG-A')
    assert scope(dict(legacy(), source='senate_page', origin='https://senate/page')) == ('senate_page', 'https://senate/page')
    assert scope(legacy()) == ('house_xml', '100520')


def test_participation_and_panel_are_preserved():
    row = native()
    row['testified'] = False
    assert agrees(legacy(testified='No'), row)
    assert not agrees(legacy(testified='Yes'), row)
    assert not agrees(legacy(testified='No, but took Oath'), row)
    assert not agrees(legacy(panel='2'), row)


def test_missing_mirror_body_does_not_claim_source_unavailable(tmp_path):
    evidence = HouseEvidence(tmp_path).occurrence(dict(native(), record_sha='ab' * 32))
    assert evidence['state'] == 'not_located_in_local_mirror'


def test_bad_source_bytes_refuse_and_unusable_xml_is_named(tmp_path):
    raw = b'not XML'
    digest = sha256(raw).hexdigest()
    path = tmp_path / 'bodies/sha256' / digest[:2] / (digest + '.gz')
    path.parent.mkdir(parents=True)
    path.write_bytes(gzip.compress(raw))
    assert HouseEvidence(tmp_path).read(digest)['state'] == 'read_unusable_xml'
    path.write_bytes(gzip.compress(b'changed'))
    with pytest.raises(ValueError, match='Corrupt retained source'):
        HouseEvidence(tmp_path).read(digest)


def test_all_input_records_survive_and_changed_frozen_inputs_refuse(tmp_path):
    pins = {}
    for filename in FILES:
        (tmp_path / filename).write_text('event_id,name,source\n100520,Allen,docs.house.gov\n100520,Allen,docs.house.gov\n')
        pins[filename] = sha256((tmp_path / filename).read_bytes()).hexdigest()
    rows = load_legacy(tmp_path, pins)
    assert len(rows) == len({r['record_id'] for r in rows}) == 6
    (tmp_path / FILES[0]).write_text('changed')
    with pytest.raises(ValueError, match='Frozen input changed'):
        load_legacy(tmp_path, pins)


@pytest.mark.parametrize('raw,reason', [
    ('<witness-list><panel sort-order="1"><witness remove-date="2026-01-01"><lastname>Removed</lastname></witness><witness><lastname>Active</lastname></witness></panel></witness-list>', 'removed_witness'),
    ('<witness-list><panel sort-order="2"><witness><lastname>Second</lastname></witness></panel><panel sort-order="1"><witness><lastname>First</lastname></witness></panel></witness-list>', 'unproved_panel_order'),
    ('<witness-list><panel sort-order="1" remove-date="2026-01-01"><witness/></panel><panel sort-order="2"><witness/></panel></witness-list>', 'removed_panel'),
    ('<witness-list><panel sort-order="1"><witness id="source-id"/></panel></witness-list>', 'id_based_locator'),
    ('<witness-list><panel sort-order="1"><witness witness-id="source-id"/></panel></witness-list>', 'id_based_locator'),
])
def test_unproved_raw_positions_never_attach_another_witness(tmp_path, raw, reason):
    body = raw.encode()
    body_sha = sha256(body).hexdigest()
    path = tmp_path / 'bodies/sha256' / body_sha[:2] / (body_sha + '.gz')
    path.parent.mkdir(parents=True)
    path.write_bytes(gzip.compress(body))
    reader = HouseEvidence(tmp_path)
    row = dict(native(), record_sha=body_sha)
    result = reader.occurrence(row)
    assert result['state'] == 'read_unqualified_locator'
    assert result['literal'] is None
    assert reason in result['reasons']
    assert reader.read(body_sha)['occurrences'] == {}
    # An ID locator is also explicit uncertainty, never a fabricated position.
    row['source_locator'] = 'house_xml:id[source-id]'
    assert reader.occurrence(row)['literal'] is None
    assert reader.bytes_read == len(body)


@pytest.mark.parametrize('repeats', [1, 2])
@pytest.mark.parametrize('wrong_raw_role', [False, True])
def test_end_to_end_conserves_records_and_reports_missing_role_link(tmp_path, repeats, wrong_raw_role):
    data, release, mirror = (tmp_path / name for name in ('data', 'release', 'mirror'))
    data.mkdir()
    release.mkdir()
    pins = {}
    for filename in FILES:
        with (data / filename).open('w') as stream:
            writer = csv.DictWriter(stream, fieldnames=['event_id', 'name', 'position', 'organization', 'source'])
            writer.writeheader()
            if filename == FILES[0]:
                for _ in range(repeats):
                    writer.writerow(dict(event_id='100520', name='W. Ron Allen', position='Chairman',
                                         organization='Tribe', source='docs.house.gov'))
        pins[filename] = sha256((data / filename).read_bytes()).hexdigest()
    frozen = tmp_path / 'frozen.json'
    frozen.write_text(json.dumps(dict(input_sha256=pins)))
    raw = b'''<witness-list><panel sort-order="1"><witness><position>Chairman</position><organization>Tribe</organization>
      <witness-documents><witness-document><type>WS</type><files>
        <file doc-url="https://house/statement.pdf" doc-type="PDF"/>
      </files></witness-document></witness-documents></witness></panel></witness-list>'''
    if wrong_raw_role:
        raw = raw.replace(b'<position>Chairman</position>', b'<position>Wrong role</position>')
    body_sha = sha256(raw).hexdigest()
    body = mirror / 'bodies/sha256' / body_sha[:2] / (body_sha + '.gz')
    body.parent.mkdir(parents=True)
    body.write_bytes(gzip.compress(raw))
    row = native()
    row['record_sha'] = bytes.fromhex(body_sha)
    pq.write_table(pa.Table.from_pylist([row]), release / 'witnesses.parquet')
    pq.write_table(pa.table(dict(filename=['wrong-role.pdf', 'right.pdf'], hidden=[False, False],
                                witness_keys=[['tribe'], ['other']])), release / 'list.parquet')
    pq.write_table(pa.table(dict(list_row=[0, 1], url=['https://house/other.pdf', 'https://house/statement.pdf'])), release / 'sources.parquet')
    files = [dict(name=p.name, size=p.stat().st_size, sha256=sha256(p.read_bytes()).hexdigest()) for p in release.iterdir()]
    (release / 'manifest.json').write_text(json.dumps(dict(release_id='candidate', files=files)))
    out = tmp_path / 'out'
    result = run(SimpleNamespace(data=data, release=release, mirror=mirror, frozen_ledger=frozen, output=out))
    assert result['input_records'] == sum(result['dispositions'].values()) == repeats
    status = 'candidate_active_field_match' if repeats == 1 else 'repeated_input_occurrence_requires_review'
    assert result['dispositions'][status] == repeats
    assert result['proven_duplicate_input_records'] == 0
    occurrence = json.loads((out / 'occurrences.jsonl').read_text())
    assert occurrence['source_links_not_exactly_linked'] == [dict(url='https://house/statement.pdf', type='WS', format='PDF')]
    assert occurrence['raw']['state'] == 'read_locator_found'
    assert occurrence['published_document_rows_without_source_link'] == [0]
    assert occurrence['raw_field_differences'] == (['position'] if wrong_raw_role else [])
    assert result['source_occurrences_with_raw_field_differences'] == int(wrong_raw_role)
    assert result['raw_house_bodies_read'] == 1
    # A changed candidate file cannot inherit a successful comparison.
    (release / 'sources.parquet').write_bytes(b'changed')
    with pytest.raises(ValueError, match='Candidate asset differs'):
        run(SimpleNamespace(data=data, release=release, mirror=mirror, frozen_ledger=frozen, output=tmp_path / 'bad'))
