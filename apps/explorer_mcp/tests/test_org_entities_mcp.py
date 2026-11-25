"""MCP organization entity lookup, search, appearances, and 1-hop organization_redirects tests (ct-lvdf)."""
import shutil

import duckdb
import pytest

from congressional_explorer_mcp.models import ExplorerError
from congressional_explorer_mcp.reader import Reader
from congressional_explorer_mcp.release import literal, prepare

from conftest import CURRENT, manifest


def test_organization_search_get_appearances_and_one_hop_redirect(phase2, tmp_path):
    root = tmp_path / 'release'
    shutil.copytree(phase2.parent, root)
    with duckdb.connect() as db:
        db.execute(f"""COPY (
            SELECT * FROM read_parquet({literal(root / 'organization_redirects.parquet')})
            UNION ALL
            SELECT '1111cccc2222dddd' AS old_org_id, 'e5b88f10d3d5a5ea' AS org_id, 'split_from' AS event, 'rel-2' AS release
        ) TO {literal(root / 'organization_redirects.parquet')} (FORMAT PARQUET)""")
    selected = prepare(tmp_path / 'cache', manifest(root), archive_origin='https://archive.fixture.test')
    reader = Reader(selected, scratch=str(tmp_path / 'q'))
    try:
        # Search by display_name and by external organization_ids value
        by_name = reader.search_entities({'table': 'organizations', 'text': 'Transit Lab'})
        assert [r['org_id'] for r in by_name['rows']] == ['e5b88f10d3d5a5ea']

        by_ext = reader.search_entities({'table': 'organizations', 'text': 'Q999001'})
        assert [r['org_id'] for r in by_ext['rows']] == ['e5b88f10d3d5a5ea']

        # Filter by Ban-Park-You category
        by_tax = reader.search_entities({'table': 'organizations', 'filters': {'taxonomy_parent': 'research'}})
        assert [r['org_id'] for r in by_tax['rows']] == ['e5b88f10d3d5a5ea']

        # Live organization lookup returns organization_ids and appearances (following witness_organizations.witness_key)
        live = reader.get_entity({'table': 'organizations', 'id': 'e5b88f10d3d5a5ea'})
        assert 'redirected_from' not in live
        org = live['rows'][0]
        assert org['display_name'] == 'Transit Lab'
        assert org['taxonomy_parent'] == 'research'
        assert org['taxonomy_category'] == 'think_tank_and_university'
        assert {('wikidata', 'Q999001'), ('bag', '1111111111111111')} <= {
            (item['scheme'], item['value']) for item in org['organization_ids']
        }
        assert [a['witness_key'] for a in org['appearances']] == ['appearance-2', 'appearance-1']
        assert all(a['field'] == 'organization' and a['raw_text'] == 'Transit Lab' for a in org['appearances'])

        # Compact fields projection stays strict (no injected nested fields)
        compact = reader.get_entity({'table': 'organizations', 'id': 'e5b88f10d3d5a5ea', 'fields': ['org_id', 'display_name']})
        assert compact['rows'] == [{'org_id': 'e5b88f10d3d5a5ea', 'display_name': 'Transit Lab'}]

        # Documents linked through witness_organizations.witness_key
        docs = reader.get_entity({'table': 'organizations', 'id': 'e5b88f10d3d5a5ea', 'section': 'documents'})
        assert [r['list_row'] for r in docs['rows']] == [0]

        # 1-hop retired org_id redirect returns redirected_from and resolves to live row
        redirected = reader.get_entity({'table': 'organizations', 'id': '1111CCCC2222DDDD'})
        assert redirected['redirected_from'] == '1111cccc2222dddd'
        assert redirected['rows'][0]['org_id'] == 'e5b88f10d3d5a5ea'
        assert redirected['rows'][0]['display_name'] == 'Transit Lab'
        assert len(redirected['rows'][0]['appearances']) == 2

        redirected_docs = reader.get_entity({'table': 'organizations', 'id': '0000aaaa1111bbbb', 'section': 'documents'})
        assert redirected_docs['redirected_from'] == '0000aaaa1111bbbb'
        assert [r['list_row'] for r in redirected_docs['rows']] == [0]

        # Unknown org_id raises ExplorerError
        with pytest.raises(ExplorerError, match='absent from this release'):
            reader.get_entity({'table': 'organizations', 'id': 'deadbeef00001111'})
    finally:
        reader.close()


def test_legacy_release_without_org_tables_fails_explicitly(tmp_path):
    reader = Reader(prepare(tmp_path / 'cache', CURRENT / 'manifest.json'))
    try:
        with pytest.raises(ExplorerError, match='not published in this release'):
            reader.get_entity({'table': 'organizations', 'id': 'e5b88f10d3d5a5ea'})
        with pytest.raises(ExplorerError, match='not published in this release'):
            reader.search_entities({'table': 'organizations', 'text': 'Transit'})
    finally:
        reader.close()


def test_org_get_entity_truncates_within_max_bytes(phase2, tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from congressional_explorer_mcp.models import MAX_BYTES
    from congressional_explorer_mcp.release import encoded

    root = tmp_path / 'huge-org-release'
    shutil.copytree(phase2.parent, root)
    org_id = 'a1b2c3d4e5f60708'
    pq.write_table(pa.table({
        'org_id': pa.array([org_id], type=pa.string()),
        'display_name': pa.array(['Massive Coalition'], type=pa.string()),
        'kind': pa.array(['coalition'], type=pa.string()),
        'taxonomy_parent': pa.array(['advocacy'], type=pa.string()),
        'taxonomy_category': pa.array(['public_interest_and_nonprofit'], type=pa.string()),
        'parent_org_id': pa.array([None], type=pa.string()),
        'appearance_count': pa.array([60], type=pa.int64()),
        'bag_keys': pa.array([['bag-huge']], type=pa.list_(pa.string())),
        'string_keys': pa.array([['str-huge']], type=pa.list_(pa.string())),
        'anchor': pa.array(['bag:bag-huge'], type=pa.string()),
        'has_conflict': pa.array([False], type=pa.bool_()),
    }), root / 'organizations.parquet')
    pq.write_table(pa.table({
        'org_id': pa.array([org_id, org_id], type=pa.string()),
        'scheme': pa.array(['bag', 'wikidata'], type=pa.string()),
        'value': pa.array(['bag-huge', 'Q42'], type=pa.string()),
    }), root / 'organization_ids.parquet')
    pq.write_table(pa.table({
        'old_org_id': pa.array([], type=pa.string()),
        'release': pa.array([], type=pa.string()),
        'org_id': pa.array([], type=pa.string()),
        'event': pa.array([], type=pa.string()),
    }), root / 'organization_redirects.parquet')
    n_apps = 60
    big_text = 'Coalition Statement ' + ('x' * 2400)
    pq.write_table(pa.table({
        'witness_key': pa.array([f'wk-{i:03d}' for i in range(n_apps)], type=pa.string()),
        'name': pa.array([f'Witness {i}' for i in range(n_apps)], type=pa.string()),
        'position': pa.array(['Director'] * n_apps, type=pa.string()),
        'organization': pa.array([big_text] * n_apps, type=pa.string()),
        'on_behalf_of': pa.array([big_text] * n_apps, type=pa.string()),
        'occasion': pa.array(['Annual Oversight Hearing'] * n_apps, type=pa.string()),
        'event_id': pa.array([118100 + i for i in range(n_apps)], type=pa.int64()),
        'package_id': pa.array([f'CHRG-118hhrg{i:03d}' for i in range(n_apps)], type=pa.string()),
        'witness_type': pa.array(['public'] * n_apps, type=pa.string()),
        'superseded_by': pa.array([None] * n_apps, type=pa.string()),
    }), root / 'witnesses.parquet')
    pq.write_table(pa.table({
        'witness_key': pa.array([f'wk-{i:03d}' for i in range(n_apps)], type=pa.string()),
        'field': pa.array(['organization'] * n_apps, type=pa.string()),
        'org_id': pa.array([org_id] * n_apps, type=pa.string()),
        'bag_key': pa.array(['bag-huge'] * n_apps, type=pa.string()),
        'string_key': pa.array(['str-huge'] * n_apps, type=pa.string()),
        'raw_text': pa.array([big_text] * n_apps, type=pa.string()),
    }), root / 'witness_organizations.parquet')
    manifest_path = manifest(root)
    reader = Reader(prepare(tmp_path / 'cache', manifest_path))
    try:
        res = reader.get_entity({'table': 'organizations', 'id': org_id})
        # Same response budget check enforced by worker._run before sending on the pipe.
        assert len(encoded(res)) <= MAX_BYTES
        row = res['rows'][0]
        assert row['organization_ids_truncated'] is False
        assert row['appearances_truncated'] is True
        assert 0 < len(row['appearances']) < n_apps
    finally:
        reader.close()
