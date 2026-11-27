"""Offline ODCS v3.2.0 DataContract export, RefSpec URN binding, Parquet parity, and drift gate tests."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import shutil

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from viewer_publication import archive_odcs
from viewer_publication.archive_model_profile import _definition_hashes
from viewer_publication.archive_schema import build_schema

ROOT = Path(__file__).resolve().parents[3]


def test_committed_contracts_match_exported_contracts_and_pass_check_drift():
    errors = archive_odcs.check_drift()
    assert errors == [], errors
    assert archive_odcs.main(['--check']) == 0


def test_all_35_archive_tables_exported_deterministically():
    schema = build_schema()
    expected_tables = [f['name'].removesuffix('.parquet') for f in schema['files']]
    assert len(expected_tables) == 35

    first = archive_odcs.export_odcs_contracts()
    second = archive_odcs.export_odcs_contracts()
    assert first == second

    bundle = first['bundle_contract']
    assert bundle['apiVersion'] == 'v3.2.0'
    assert bundle['kind'] == 'DataContract'
    assert bundle['id'] == 'urn:congressional-tech:archive:release'
    assert [obj['name'] for obj in bundle['schema']] == expected_tables
    assert set(first['table_contracts']) == set(expected_tables)

    by_name = {obj['name']: obj for obj in bundle['schema']}
    for table in schema['files']:
        tname = table['name'].removesuffix('.parquet')
        obj = by_name[tname]
        assert [p['name'] for p in obj['properties']] == [c['name'] for c in table['columns']]
        for prop, col in zip(obj['properties'], table['columns'], strict=True):
            assert prop['required'] is (not col['nullable']), f'{tname}.{col["name"]}'
        if table['identity']['kind'] == 'primary_key':
            pks = [p['name'] for p in sorted(
                (p for p in obj['properties'] if p.get('primaryKey')),
                key=lambda p: p['primaryKeyPosition'],
            )]
            assert pks == table['identity']['fields'], tname
        else:
            assert not any(p.get('primaryKey') for p in obj['properties'])


def test_canonical_refspec_and_spicycongress_urn_bindings():
    exported = archive_odcs.export_odcs_contracts()
    urn_bindings = exported['urn_bindings']
    concepts = urn_bindings['concepts']

    expected_concepts = {
        'urn:ddk:legislative:concept:bill-id',
        'urn:ddk:legislative:concept:bioguide-id',
        'urn:ddk:legislative:concept:committee-code',
        'urn:ddk:legislative:concept:event-id',
        'urn:ddk:gpo:concept:package-id',
        'urn:ddk:legislative:concept:roll-call-id',
        'urn:ddk:fec:concept:candidate-id',
        'urn:ddk:entity:concept:org-id',
        'urn:ddk:entity:concept:person-id',
        'urn:refspec:agency-registry:anchor',
        'urn:congressional-tech:concept:link-key',
        'urn:congressional-tech:concept:witness-key',
        'urn:congressional-tech:concept:video-key',
        'urn:congressional-tech:concept:nomination-id',
        'urn:congressional-tech:concept:measure-key',
    }
    assert expected_concepts <= set(concepts)

    def _bound(urn: str) -> set[tuple[str, str]]:
        return {(b['table'], b['path']) for b in concepts[urn]['bindings']}

    assert ('bills', 'bill_id') in _bound('urn:ddk:legislative:concept:bill-id')
    assert ('bill_actions', 'bill_id') in _bound('urn:ddk:legislative:concept:bill-id')
    assert ('roll_call_votes', 'bill_id') in _bound('urn:ddk:legislative:concept:bill-id')
    assert ('members', 'bioguide_id') in _bound('urn:ddk:legislative:concept:bioguide-id')
    assert ('witnesses', 'matched_bioguide_id') in _bound('urn:ddk:legislative:concept:bioguide-id')
    assert ('committees', 'system_code') in _bound('urn:ddk:legislative:concept:committee-code')
    assert ('meetings', 'committees[].system_code') in _bound('urn:ddk:legislative:concept:committee-code')
    assert ('meetings', 'event_id') in _bound('urn:ddk:legislative:concept:event-id')
    assert ('list', 'meeting_keys[]') in _bound('urn:ddk:legislative:concept:event-id')
    assert ('detail', 'package_id') in _bound('urn:ddk:gpo:concept:package-id')
    assert ('people', 'person_key') in _bound('urn:ddk:entity:concept:person-id')
    assert ('witnesses', 'person_key') in _bound('urn:ddk:entity:concept:person-id')
    assert ('organizations', 'org_id') in _bound('urn:ddk:entity:concept:org-id')
    assert ('organization_ids', 'org_id') in _bound('urn:ddk:entity:concept:org-id')
    assert ('organization_redirects', 'old_org_id') in _bound('urn:ddk:entity:concept:org-id')
    assert ('organizations', 'anchor') in _bound('urn:refspec:agency-registry:anchor')

    refspec_manifest = json.loads((ROOT / 'model/jobs/refspec/refspec.json').read_text(encoding='utf-8'))
    spicy_manifest = json.loads((ROOT / 'model/jobs/spicy-regs/spicy-regs.json').read_text(encoding='utf-8'))
    assert urn_bindings['refspec']['releaseKey'] == refspec_manifest['release']['key']
    assert urn_bindings['refspec']['viewId'].startswith('urn:ref:agency-registry-view:')
    assert urn_bindings['spicyRegs']['generations'] == spicy_manifest['generations']


def test_odcs_schema_validation_rejects_mutations():
    exported = archive_odcs.export_odcs_contracts()
    bundle = deepcopy(exported['bundle_contract'])
    expected_tables = {obj['name'] for obj in bundle['schema']}
    assert archive_odcs.validate_odcs_contract(bundle, expected_tables=expected_tables) == []

    bad_api = deepcopy(bundle)
    bad_api['apiVersion'] = 'v3.0.0'
    assert any('apiVersion' in e for e in archive_odcs.validate_odcs_contract(bad_api))

    bad_kind = deepcopy(bundle)
    bad_kind['kind'] = 'DataProduct'
    assert any('kind' in e for e in archive_odcs.validate_odcs_contract(bad_kind))

    bad_missing_table = deepcopy(bundle)
    bad_missing_table['schema'].pop()
    assert any('Missing tables' in e for e in archive_odcs.validate_odcs_contract(bad_missing_table, expected_tables=expected_tables))

    bad_pk = deepcopy(bundle)
    bad_pk['schema'][1]['properties'][0]['required'] = False
    assert any('primaryKey must have required=True' in e for e in archive_odcs.validate_odcs_contract(bad_pk))

    bad_rel = deepcopy(bundle)
    links_obj = next(obj for obj in bad_rel['schema'] if obj['name'] == 'retired_links')
    links_obj['relationships'][0]['from'] = 'retired_links.link_key[]'
    assert any('relationship shorthand' in e for e in archive_odcs.validate_odcs_contract(bad_rel))


def test_arrow_conversion_and_parquet_parity_round_trip(tmp_path):
    exported = archive_odcs.export_odcs_contracts()
    by_name = {obj['name']: obj for obj in exported['bundle_contract']['schema']}

    for tname, obj in by_name.items():
        pa_schema = archive_odcs.odcs_object_to_arrow_schema(obj, pa)
        assert list(pa_schema.names) == [p['name'] for p in obj['properties']], tname

    # Round-trip representative tables covering fixed[8], fixed[32], timestamps, dates, ints, lists, structs.
    sample_rows = {
        'links': [{'link_key': b'12345678', 'list_row': 0}],
        'corrections': [{
            'original_url': 'https://example.gov/a.pdf',
            'rejected_body': b'x' * 32,
            'decision_id': 'dec-1',
            'decided_at': datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc),
            'recovered_url': None,
            'identity_note': 'wrong copy',
        }],
        'organizations': [{
            'org_id': 'org-1',
            'display_name': 'Department of Example',
            'kind': 'government',
            'taxonomy_parent': 'Executive',
            'taxonomy_category': 'Agency',
            'parent_org_id': None,
            'appearance_count': 4,
            'bag_keys': ['bag-1'],
            'string_keys': ['str-1'],
            'anchor': 'fr_agency:1',
            'has_conflict': False,
        }],
        'rosters': [{
            'congress': 119,
            'system_code': 'hsju00',
            'bioguide_id': 'P000197',
            'role': 'Member',
            'rank': 1,
            'title': None,
            'party': 'D',
        }],
        'committees': [{
            'system_code': 'hsju00',
            'name': 'Committee on the Judiciary',
            'chamber': 'house',
            'committee_type': 'standing',
            'parent_system_code': None,
            'names': [{'name': 'Committee on the Judiciary', 'start': date(1977, 1, 1), 'end': None}],
            'website': 'https://judiciary.house.gov',
            'is_current': True,
        }],
    }

    for tname, rows in sample_rows.items():
        obj = by_name[tname]
        pa_schema = archive_odcs.odcs_object_to_arrow_schema(obj, pa)
        pq_path = tmp_path / f'{tname}.parquet'
        pq.write_table(pa.Table.from_pylist(rows, schema=pa_schema), pq_path)
        assert archive_odcs.compare_parquet_schema_parity(obj, pq_path, check_order=True, check_nullability=True) == []

    # Verify drift detection rejects missing col, extra col, wrong type, order diff, nullability diff.
    links_obj = by_name['links']
    links_schema = archive_odcs.odcs_object_to_arrow_schema(links_obj, pa)
    assert any('missing columns' in issue for issue in archive_odcs.compare_parquet_schema_parity(
        links_obj, pa.schema([links_schema.field(0)]),
    ))
    assert any('unexpected columns' in issue for issue in archive_odcs.compare_parquet_schema_parity(
        links_obj, links_schema.append(pa.field('extra', pa.string())),
    ))
    assert any('type mismatch' in issue for issue in archive_odcs.compare_parquet_schema_parity(
        links_obj, pa.schema([pa.field('link_key', pa.string(), nullable=False), links_schema.field(1)]),
    ))
    assert any('column order differs' in issue for issue in archive_odcs.compare_parquet_schema_parity(
        links_obj, pa.schema([links_schema.field(1), links_schema.field(0)]), check_order=True,
    ))
    assert archive_odcs.compare_parquet_schema_parity(
        links_obj, pa.schema([links_schema.field(1), links_schema.field(0)]), check_order=False,
    ) == []
    assert any('nullability mismatch' in issue for issue in archive_odcs.compare_parquet_schema_parity(
        links_obj, pa.schema([pa.field('link_key', pa.binary(8), nullable=True), links_schema.field(1)]), check_nullability=True,
    ))


def test_frozen_archive_contract_fixture_parity():
    fixture_dir = ROOT / 'model/fixtures/archive-contract/current'
    exported = archive_odcs.export_odcs_contracts()
    by_name = {obj['name']: obj for obj in exported['bundle_contract']['schema']}
    # Legacy fixture tables whose column lists exactly match current release-schema.json:
    for tname in ('committees', 'links', 'recoveries', 'sources', 'urls'):
        issues = archive_odcs.compare_parquet_schema_parity(
            by_name[tname],
            fixture_dir / f'{tname}.parquet',
            check_order=True,
            check_nullability=False,
        )
        assert issues == [], (tname, issues)


def test_cli_check_and_drift_detection(tmp_path, capsys):
    contracts_dir = tmp_path / 'contracts'
    assert archive_odcs.main(['--output-dir', str(contracts_dir)]) == 0
    assert archive_odcs.main(['--check', '--output-dir', str(contracts_dir)]) == 0

    # Mutate a committed table contract to simulate drift and verify --check refuses.
    meetings_path = contracts_dir / 'tables/meetings.odcs.json'
    doc = json.loads(meetings_path.read_text(encoding='utf-8'))
    doc['schema'][0]['properties'][0]['customProperties'] = []
    meetings_path.write_text(json.dumps(doc), encoding='utf-8')
    assert archive_odcs.main(['--check', '--output-dir', str(contracts_dir)]) == 1
    captured = capsys.readouterr()
    assert 'Contract drift detected' in captured.err

    # Restore and test stale extra table detection.
    archive_odcs.main(['--output-dir', str(contracts_dir)])
    shutil.copyfile(meetings_path, contracts_dir / 'tables/rogue_table.odcs.json')
    assert archive_odcs.main(['--check', '--output-dir', str(contracts_dir)]) == 1


def test_archive_schema_remains_single_owner_without_model_hash_churn():
    hashes = _definition_hashes(ROOT)
    assert 'packages/viewer_publication/src/viewer_publication/archive_schema.py' in hashes
    assert 'packages/viewer_publication/src/viewer_publication/archive_odcs.py' not in hashes
    assert not any(k.startswith('model/contracts/') for k in hashes)
