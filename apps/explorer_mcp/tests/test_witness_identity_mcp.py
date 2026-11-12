"""MCP witness_key_map resolution (ct-46f3) and retained Congress.gov listing_status (ct-960v) tests."""
from datetime import date
import shutil

import duckdb
import pytest

from congressional_explorer_mcp.citations import text_citation
from congressional_explorer_mcp.models import ExplorerError
from congressional_explorer_mcp.passage_reader import resolve_passage
from congressional_explorer_mcp.reader import Reader
from congressional_explorer_mcp.release import literal, prepare

from conftest import manifest


@pytest.fixture
def identity_release(phase2, tmp_path):
    root = tmp_path / 'release'
    shutil.copytree(phase2.parent, root)
    with duckdb.connect() as db:
        db.execute(f"""COPY (
            SELECT *, 'listed'::VARCHAR AS listing_status, NULL::DATE AS last_listed_on,
                   NULL::DATE AS unlisted_since, NULL::VARCHAR AS unlisted_by_record_sha,
                   CASE WHEN witness_key IN ('appearance-1','appearance-2','mods-appearance-1') THEN 'aa11bb22cc33dd44'
                        WHEN witness_key = 'member-appearance-1' THEN 'A000001'
                        ELSE 'ee55ff6677889900' END AS person_key
            FROM read_parquet({literal(root / 'witnesses.parquet')})
            UNION ALL
            SELECT 'unlisted-appearance-1', 'meeting:1', 335321::BIGINT, NULL, NULL,
                   'Dropped Witness', NULL, NULL, 'Advisor', 'Energy Council', NULL, NULL, 'Panel A',
                   1::SMALLINT, 9::SMALLINT, 'public', false, NULL, NULL, NULL, NULL,
                   'no_longer_listed', DATE '2026-10-20', DATE '2026-10-25', repeat('e', 64),
                   'ff00112233445566'
        ) TO {literal(root / 'witnesses.parquet')} (FORMAT PARQUET)""")
        db.execute(f"""COPY (
            SELECT * FROM read_parquet({literal(root / 'witness_key_map.parquet')})
            UNION ALL
            SELECT 'ambig-appearance-1', NULL, 'ambiguous', 'occurrence', ['appearance-1', 'appearance-2'], 'meeting:1', 'congress_gov'
            UNION ALL
            SELECT 'gone-appearance-1', NULL, 'unresolved', NULL, []::VARCHAR[], 'page:1', 'senate_page'
        ) TO {literal(root / 'witness_key_map.parquet')} (FORMAT PARQUET)""")
        db.execute(f"""COPY (
            SELECT 'aa11bb22cc33dd44' AS person_key, NULL::VARCHAR AS bioguide_id, 'Alex Smith' AS name,
                   ['Alex Smith', 'A. Smith'] AS name_variants, 'Transit Lab' AS organization,
                   ['Transit Lab'] AS organizations, ['Director'] AS positions, ['Lt. Gen.'] AS ranks,
                   'name_organization' AS grouping_basis, 2::INTEGER AS appearance_count,
                   2::INTEGER AS hearing_count, DATE '2025-01-10' AS first_seen_date,
                   DATE '2025-02-10' AS last_seen_date, ['appearance-1', 'appearance-2'] AS witness_keys
            UNION ALL
            SELECT 'A000001', 'A000001', 'Sam Example', ['The Honorable Sam Example'], NULL,
                   []::VARCHAR[], []::VARCHAR[], []::VARCHAR[], 'bioguide', 1::INTEGER, 1::INTEGER,
                   DATE '2025-03-01', DATE '2025-03-01', ['member-appearance-1']
        ) TO {literal(root / 'people.parquet')} (FORMAT PARQUET)""")
        db.execute(f"""COPY (
            SELECT 'old-person-000001' AS old_person_key, 'aa11bb22cc33dd44' AS person_key,
                   'unambiguous' AS status, 'regrouped' AS kind, NULL::VARCHAR AS decision_id,
                   repeat('1', 64) AS last_release_id, []::VARCHAR[] AS candidate_keys
            UNION ALL
            SELECT 'ambig-person-0001', NULL, 'ambiguous', 'split', NULL, repeat('1', 64),
                   ['aa11bb22cc33dd44', 'ee55ff6677889900']
            UNION ALL
            SELECT 'gone-person-00001', NULL, 'unresolved', NULL, NULL, repeat('1', 64), []::VARCHAR[]
        ) TO {literal(root / 'person_aliases.parquet')} (FORMAT PARQUET)""")
    return manifest(root)


def test_get_entity_and_search_documents_resolve_through_witness_key_map(identity_release, tmp_path):
    selection = prepare(tmp_path / 'cache', identity_release, archive_origin='https://archive.fixture.test')
    reader = Reader(selection, scratch=str(tmp_path / 'q'))
    try:
        rec = reader.get_entity({'table': 'witnesses', 'id': 'old-appearance-1'})
        assert rec['redirected_from'] == 'old-appearance-1'
        assert rec['rows'][0]['witness_key'] == 'appearance-1'

        docs = reader.get_entity({'table': 'witnesses', 'id': 'old-appearance-1', 'section': 'documents'})
        assert docs['redirected_from'] == 'old-appearance-1'
        assert len(docs['rows']) == 1

        searched = reader.search_documents({'witness_key': 'old-appearance-1'})
        assert searched['redirected_witness_key'] == {'from': 'old-appearance-1', 'to': 'appearance-1'}
        assert [r['list_row'] for r in searched['rows']] == [0]

        with pytest.raises(ExplorerError, match='ambiguous.*appearance-1.*appearance-2'):
            reader.get_entity({'table': 'witnesses', 'id': 'ambig-appearance-1'})

        with pytest.raises(ExplorerError, match='no longer published.*unresolved'):
            reader.get_entity({'table': 'witnesses', 'id': 'gone-appearance-1'})
    finally:
        reader.close()


@pytest.mark.anyio
async def test_resolve_passage_accepts_prior_witness_key_through_witness_key_map(identity_release, tmp_path):
    from congressional_explorer_mcp.citations import validate_witness_claim
    selection = prepare(tmp_path / 'cache', identity_release, archive_origin='https://archive.fixture.test')
    reader = Reader(selection, scratch=str(tmp_path / 'q'))
    try:
        docs = reader.search_documents({'witness_key': 'appearance-1'})
        link_key = docs['rows'][0]['reference']['link_key']
        target = reader.document_body_target({'link_key': link_key, 'release_id': reader.release_id})
        assert 'appearance-1' in target['witness_keys']
        assert 'old-appearance-1' in target.get('prior_witness_keys', [])
        validate_witness_claim(target, 'old-appearance-1', 'source_association')
    finally:
        reader.close()


def test_hearing_bundle_includes_retained_no_longer_listed_witness(identity_release, tmp_path):
    selection = prepare(tmp_path / 'cache', identity_release)
    reader = Reader(selection, scratch=str(tmp_path / 'q'))
    try:
        bundle = reader.get_hearing_bundle({'event_id': 335321, 'include': ['witnesses']})
        by_key = {r['witness_key']: r for r in bundle['sections']['witnesses']['rows']}
        assert by_key['appearance-1']['listing_status'] == 'listed'
        assert by_key['unlisted-appearance-1']['listing_status'] == 'no_longer_listed'
        assert str(by_key['unlisted-appearance-1']['unlisted_since']) == '2026-10-25'
        assert 'No longer listed by Congress.gov since 2026-10-25' in str(by_key['unlisted-appearance-1'].get('listing_note', ''))
    finally:
        reader.close()


def test_people_search_documents_and_person_aliases(identity_release, tmp_path):
    selection = prepare(tmp_path / 'cache', identity_release, archive_origin='https://archive.fixture.test')
    reader = Reader(selection, scratch=str(tmp_path / 'q'))
    try:
        by_name = reader.search_entities({'table': 'people', 'text': 'Alex Smith'})
        assert [r['person_key'] for r in by_name['rows']] == ['aa11bb22cc33dd44']

        by_org = reader.search_entities({'table': 'people', 'text': 'Transit Lab'})
        assert [r['person_key'] for r in by_org['rows']] == ['aa11bb22cc33dd44']

        rec = reader.get_entity({'table': 'people', 'id': 'old-person-000001'})
        assert rec['redirected_from'] == 'old-person-000001'
        assert rec['rows'][0]['person_key'] == 'aa11bb22cc33dd44'
        assert rec['rows'][0]['grouping_basis'] == 'name_organization'

        docs = reader.get_entity({'table': 'people', 'id': 'old-person-000001', 'section': 'documents'})
        assert docs['redirected_from'] == 'old-person-000001'
        assert [r['list_row'] for r in docs['rows']] == [0]

        with pytest.raises(ExplorerError, match='ambiguous.*aa11bb22cc33dd44.*ee55ff6677889900'):
            reader.get_entity({'table': 'people', 'id': 'ambig-person-0001'})

        with pytest.raises(ExplorerError, match='no longer published.*unresolved'):
            reader.get_entity({'table': 'people', 'id': 'gone-person-00001'})
    finally:
        reader.close()
