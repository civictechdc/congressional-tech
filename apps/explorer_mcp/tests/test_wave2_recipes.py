"""Composite MCP research recipes: organization_dossier and accountability_documents."""
import asyncio
from contextlib import closing
import shutil

import duckdb
import pytest
from fastmcp import Client

from congressional_explorer_mcp import ARCHIVE_SEARCH_TOOLS, TOOL_NAMES
from congressional_explorer_mcp.models import ExplorerError, MAX_BYTES
from congressional_explorer_mcp.reader import Reader
from congressional_explorer_mcp.release import encoded, literal, prepare
from congressional_explorer_mcp.server import create_server
from conftest import CURRENT, manifest, replace_rows


def test_organization_dossier_resolves_redirects_and_witness_breakdown(phase2, tmp_path):
    root = tmp_path / 'release'
    shutil.copytree(phase2.parent, root)
    with duckdb.connect() as db:
        db.execute(f"""COPY (
            SELECT * FROM read_parquet({literal(root / 'organization_redirects.parquet')})
            UNION ALL
            SELECT '1111cccc2222dddd' AS old_org_id, 'e5b88f10d3d5a5ea' AS org_id, 'merged' AS event, 'rel-2' AS release
        ) TO {literal(root / 'organization_redirects.parquet')} (FORMAT PARQUET)""")
    selected = prepare(tmp_path / 'cache', manifest(root), archive_origin='https://archive.fixture.test')
    with closing(Reader(selected)) as reader:
        dossier_res = reader.run_research_query({'name': 'organization_dossier', 'org_id': '1111CCCC2222DDDD'})
        assert dossier_res['query_name'] == 'organization_dossier'
        assert dossier_res['redirected_from'] == '1111cccc2222dddd'
        assert dossier_res['coverage']['status'] == 'available'
        dossier = dossier_res['rows'][0]
        assert dossier['organization']['org_id'] == 'e5b88f10d3d5a5ea'
        assert dossier['organization']['display_name'] == 'Transit Lab'
        assert dossier['redirected_from'] == '1111cccc2222dddd'
        assert {('wikidata', 'Q999001'), ('bag', '1111111111111111')} <= {
            (item['scheme'], item['value']) for item in dossier['organization_ids']
        }
        wb = dossier['witness_breakdown']
        assert wb['distinct_witnesses'] == 2
        assert wb['distinct_hearings'] == 2
        assert wb['by_field'] == [{'field': 'organization', 'count': 2}]
        assert [c['system_code'] for c in wb['by_committee']] == ['hsif00']
        assert len(wb['appearances']) == 2
        assert [d['list_row'] for d in dossier['documents']] == [0]
        assert len(encoded(dossier_res)) <= MAX_BYTES

        with pytest.raises(ExplorerError, match='requires org_id'):
            reader.run_research_query({'name': 'organization_dossier'})


def test_organization_dossier_legacy_release_reports_unavailable_honestly(tmp_path):
    selected = prepare(tmp_path / 'cache', CURRENT / 'manifest.json')
    with closing(Reader(selected)) as reader:
        res = reader.run_research_query({'name': 'organization_dossier', 'org_id': 'e5b88f10d3d5a5ea'})
        assert res['rows'] == []
        assert res['coverage']['status'] == 'unavailable'
        assert 'organizations' in res['coverage']['missing_tables']


def test_accountability_documents_surfaces_removed_retired_recovered_and_editions(phase2, tmp_path):
    root = tmp_path / 'release'
    shutil.copytree(phase2.parent, root)
    replace_rows(root, 'list', lambda rows: (
        rows[0].update(hidden=True),
        rows[1].update(saved_kind='recovery', version_keys=['edition-a', 'edition-b']),
        rows[2].update(saved_kind='recovery'),
        rows[3].update(hidden=False),
    ))
    with duckdb.connect() as db:
        detail_cols = {r[0] for r in db.execute(f"DESCRIBE SELECT * FROM read_parquet({literal(root / 'detail.parquet')})").fetchall()}
        removed_expr = "CASE WHEN file_row_number=3 THEN DATE '2025-03-10' ELSE NULL::DATE END"
        if 'removed_on' in detail_cols:
            db.execute(f"""COPY (
                SELECT * EXCLUDE(file_row_number) REPLACE({removed_expr} AS removed_on)
                FROM read_parquet({literal(root / 'detail.parquet')}, file_row_number=true)
            ) TO {literal(root / 'detail.parquet')} (FORMAT PARQUET)""")
        else:
            db.execute(f"""COPY (
                SELECT * EXCLUDE(file_row_number), {removed_expr} AS removed_on
                FROM read_parquet({literal(root / 'detail.parquet')}, file_row_number=true)
            ) TO {literal(root / 'detail.parquet')} (FORMAT PARQUET)""")
        db.execute(f"""COPY (
            SELECT unhex('1111222233334444') AS link_key,
                   unhex((SELECT lower(hex(link_key)) FROM read_parquet({literal(root / 'detail.parquet')}, file_row_number=true) WHERE file_row_number=1)) AS successor_key,
                   repeat('a', 64) AS last_release_id,
                   'Old_Statement.pdf' AS last_filename,
                   []::BLOB[] AS address_versions
            UNION ALL
            SELECT unhex('5555666677778888') AS link_key,
                   NULL::BLOB AS successor_key,
                   repeat('b', 64) AS last_release_id,
                   'Vanished_Report.pdf' AS last_filename,
                   []::BLOB[] AS address_versions
        ) TO {literal(root / 'retired_links.parquet')} (FORMAT PARQUET)""")

    selected = prepare(tmp_path / 'cache', manifest(root), archive_origin='https://archive.fixture.test')
    with closing(Reader(selected)) as reader:
        all_rows = []
        cursor = None
        while True:
            page = reader.run_research_query({'name': 'accountability_documents', 'limit': 2, 'cursor': cursor})
            assert page['coverage']['removed_on_published'] is True
            all_rows.extend(page['rows'])
            if not page['has_more']:
                break
            cursor = page['next_cursor']
        kinds = {r['churn_kind'] for r in all_rows}
        assert {'removed_on', 'review_removed', 'recovered_only', 'multi_edition', 'retired_redirected', 'retired_removed'} <= kinds

        removed = reader.run_research_query({'name': 'accountability_documents', 'churn_kind': 'removed'})
        assert {r['churn_kind'] for r in removed['rows']} == {'removed_on', 'review_removed'}
        removed_on_row = next(r for r in removed['rows'] if r['churn_kind'] == 'removed_on')
        assert removed_on_row['removed_on'] == '2025-03-10'
        assert removed_on_row['reference']['link_key']

        retired = reader.run_research_query({'name': 'accountability_documents', 'churn_kind': 'retired'})
        by_key = {r['link_key']: r for r in retired['rows']}
        assert by_key['1111222233334444']['churn_kind'] == 'retired_redirected'
        assert by_key['1111222233334444']['successor_key']
        assert by_key['5555666677778888']['churn_kind'] == 'retired_removed'
        assert by_key['5555666677778888']['successor_key'] is None

        recovered = reader.run_research_query({'name': 'accountability_documents', 'churn_kind': 'recovered'})
        assert recovered['rows'] and all(r['churn_kind'] == 'recovered_only' for r in recovered['rows'])

        editions = reader.run_research_query({'name': 'accountability_documents', 'churn_kind': 'multi_edition'})
        assert editions['rows']
        assert 2 in [r['edition_count'] for r in editions['rows']]
        assert all(r['edition_count'] >= 1 for r in editions['rows'])


def test_mcp_tool_surface_remains_exact_21_tools_and_warm_unchanged(selection):
    assert len(TOOL_NAMES) == 18
    assert len(TOOL_NAMES | ARCHIVE_SEARCH_TOOLS) == 21

    async def run():
        async with Client(create_server(selection)) as client:
            tools = await client.list_tools()
            assert {t.name for t in tools} == TOOL_NAMES
            dossier = (await client.call_tool('run_research_query', {
                'query': {'name': 'organization_dossier', 'org_id': '0000aaaa1111bbbb'}
            })).data
            assert dossier['redirected_from'] == '0000aaaa1111bbbb'
            assert dossier['rows'][0]['organization']['org_id'] == 'e5b88f10d3d5a5ea'

    asyncio.run(run())
