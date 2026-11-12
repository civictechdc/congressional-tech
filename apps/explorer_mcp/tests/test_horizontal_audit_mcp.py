"""Horizontal raw-data audit Explorer MCP regressions (cat2-pkk1, P0-2, P1-4, P1-5, P1-7, P2-10d, F2, F5)."""
from contextlib import closing
import json
import re
import shutil

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congressional_explorer_mcp.models import ExplorerError
from congressional_explorer_mcp.reader import LIST_TEXT_FIELDS, TEXT_FIELDS, Reader
from congressional_explorer_mcp.release import literal, prepare
from conftest import manifest, replace_rows


def test_witness_record_sha_blob_renders_lowercase_hex_across_mcp_surfaces(phase2, tmp_path):
    """P1-4: witnesses.record_sha BLOB renders 64-char lowercase hex in get_hearing_bundle, get_entity, and search_entities."""
    root = tmp_path / 'release'
    shutil.copytree(phase2.parent, root)
    expected_hex = '01ea11d7ba78f88d5b4bd784e8eee54c843553db0031d69b0a7dbe5b259d1ba3'
    with duckdb.connect() as db:
        db.execute(f"""COPY (
            SELECT * REPLACE ('General'::VARCHAR AS rank, 'USA'::VARCHAR AS credentials),
                   unhex('{expected_hex}') AS record_sha
            FROM read_parquet({literal(root / 'witnesses.parquet')})
        ) TO {literal(root / 'witnesses.parquet')} (FORMAT PARQUET)""")
        db.execute(f"""COPY (
            SELECT person_key, bioguide_id, name,
                   CASE WHEN person_key='aa11bb22cc33dd44' THEN 'General' END AS rank,
                   CASE WHEN person_key='aa11bb22cc33dd44' THEN ['General', 'Lieutenant General'] ELSE []::VARCHAR[] END AS ranks,
                   CASE WHEN person_key='aa11bb22cc33dd44' THEN 'USA' END AS credentials,
                   name_variants, organization, organizations, positions, grouping_basis,
                   appearance_count, hearing_count, first_seen_date, last_seen_date, witness_keys
            FROM read_parquet({literal(root / 'people.parquet')})
        ) TO {literal(root / 'people.parquet')} (FORMAT PARQUET)""")
    with closing(Reader(prepare(tmp_path / 'sel', manifest(root)))) as reader:
        bundle = reader.get_hearing_bundle({'event_id': 335321, 'include': ['witnesses']})
        w_rows = bundle['sections']['witnesses']['rows']
        assert w_rows
        for row in w_rows:
            assert re.fullmatch(r'[0-9a-f]{64}', row['record_sha'])
            assert row['record_sha'] == expected_hex

        ent = reader.get_entity({'table': 'witnesses', 'id': 'appearance-1'})['rows'][0]
        assert ent['record_sha'] == expected_hex
        ent_sliced = reader.get_entity({'table': 'witnesses', 'id': 'appearance-1', 'fields': ['record_sha', 'rank']})['rows'][0]
        assert ent_sliced['record_sha'] == expected_hex
        assert ent_sliced['rank'] == 'General'

        searched = reader.search_entities({'table': 'witnesses', 'text': 'General'})['rows']
        assert searched and all(r['record_sha'] == expected_hex for r in searched)

        people_by_rank = reader.search_entities({'table': 'people', 'text': 'Lieutenant General'})['rows']
        assert [r['person_key'] for r in people_by_rank] == ['aa11bb22cc33dd44']


def test_text_fields_include_identity_note_rank_and_credentials(phase2, tmp_path):
    """Wave 4 + Wave 5 handoff: TEXT_FIELDS includes identity_note, rank, credentials; LIST_TEXT_FIELDS includes ranks."""
    assert {'identity_note', 'rank', 'credentials'} <= set(TEXT_FIELDS)
    assert 'ranks' in set(LIST_TEXT_FIELDS)

    root = tmp_path / 'release'
    shutil.copytree(phase2.parent, root)
    pq.write_table(
        pa.table({
            'correction_id': ['corr-1'],
            'identity_note': ['Replaces corrupt upstream scan of Senate jacket 40547'],
        }),
        root / 'corrections.parquet',
    )
    schema = json.loads((root / 'schema.json').read_text())
    schema['files'].append(dict(
        name='corrections.parquet',
        columns=[
            dict(name='correction_id', type='string', meaning='Correction ID', nullable=False),
            dict(name='identity_note', type='string', meaning='Identity note', nullable=True),
        ],
        gaps=[],
        purpose='Published corrections',
        row_meaning='One correction',
        identity=dict(fields=['correction_id'], scope='published identifier', validation='fixture', kind='primary_key'),
        nullability='fixture',
    ))
    (root / 'schema.json').write_text(json.dumps(schema))
    with closing(Reader(prepare(tmp_path / 'sel', manifest(root)))) as reader:
        found = reader.search_entities({'table': 'corrections', 'text': 'jacket 40547'})['rows']
        assert [r['correction_id'] for r in found] == ['corr-1']


def test_all_five_document_kind_synonym_groups_match_equivalently(phase2, tmp_path):
    """F2: All 5 published document_kind synonym pairs return identical search_documents results."""
    pairs = [
        ('witness-statement', 'testimony'),
        ('committee-amendment', 'amendment'),
        ('witness-biography', 'biography'),
        ('member-statement', 'opening-statement'),
        ('committee-transcript', 'transcript'),
    ]
    root = tmp_path / 'release'
    shutil.copytree(phase2.parent, root)
    listed = pq.read_table(root / 'list.parquet').to_pylist()
    while len(listed) < 10:
        listed.append(dict(listed[-1]))
    # Write 10 list/detail rows: one per word across the 5 synonym pairs
    flat_words = [w for pair in pairs for w in pair]
    list_schema = pq.read_schema(root / 'list.parquet')
    detail_rows = pq.read_table(root / 'detail.parquet').to_pylist()
    while len(detail_rows) < 10:
        detail_rows.append(dict(detail_rows[-1], link_key=bytes([len(detail_rows) + 1]) * 8))
    detail_schema = pq.read_schema(root / 'detail.parquet')
    for idx, word in enumerate(flat_words):
        listed[idx] = dict(listed[idx], document_kind=[word], hidden=False)
    pq.write_table(pa.Table.from_pylist(listed[:10], schema=list_schema), root / 'list.parquet')
    pq.write_table(pa.Table.from_pylist(detail_rows[:10], schema=detail_schema), root / 'detail.parquet')

    with closing(Reader(prepare(tmp_path / 'sel', manifest(root)))) as reader:
        for idx, (canonical, alias) in enumerate(pairs):
            rows_a = [r['list_row'] for r in reader.search_documents({'document_kind': canonical})['rows']]
            rows_b = [r['list_row'] for r in reader.search_documents({'document_kind': alias})['rows']]
            assert rows_a == rows_b == [2 * idx, 2 * idx + 1], (canonical, alias)


def test_bare_m3u8_without_caption_resources_reports_advertised_not_archived_and_dedups_recordings(phase2, tmp_path):
    """P0-2 & P2-10d: bare m3u8 without retained caption_resources is excluded from readable captions
    and reports archived=0 / advertised_not_archived; recordings excludes congress.gov/event/ HTML URLs and dedups video_key."""
    root = tmp_path / 'release'
    shutil.copytree(phase2.parent, root)
    (root / 'caption_resources.parquet').unlink()
    with duckdb.connect() as db:
        db.execute(f"""COPY (
            SELECT * REPLACE(
                338384::BIGINT AS event_id,
                [struct_pack(source:='captions', package_id:=NULL::VARCHAR, list_row:=NULL::INTEGER,
                             formats:=['m3u8'], video_key:='senate:ag051226', language:='en', production:='live')] AS transcripts
            )
            FROM read_parquet({literal(root / 'meetings.parquet')}) WHERE event_id=118001
        ) TO {literal(root / 'meetings.parquet')} (FORMAT PARQUET)""")
        db.execute(f"""COPY (
            SELECT 'senate:ag051226' AS video_key, [338384::BIGINT] AS event_ids,
                   [struct_pack(body:=unhex(repeat('aa', 32)), suffix:='.gz', format:='m3u8', language:='en', production:='live')] AS tracks
        ) TO {literal(root / 'recordings.parquet')} (FORMAT PARQUET)""")
        db.execute(f"""COPY (
            SELECT 338384::BIGINT AS event_id, 'captions' AS aspect, 'present' AS state,
                   'videos.has_caption,recordings.tracks' AS basis, 1::INTEGER AS count, NULL::VARCHAR AS reason
        ) TO {literal(root / 'meeting_coverage.parquet')} (FORMAT PARQUET)""")
        db.execute(f"""COPY (
            SELECT 'm-low' AS match_id, 'event' AS subject_kind, '338384' AS subject_id, 338384::BIGINT AS event_id,
                   NULL::VARCHAR AS package_id, 'youtube:ZS8XQIeEgTo' AS video_key,
                   'https://www.youtube.com/watch?v=ZS8XQIeEgTo' AS url, 'video_states_event_id' AS basis,
                   'linked' AS decision, 95::SMALLINT AS score, 'unknown' AS recording_scope, 'asserted' AS status,
                   NULL::VARCHAR AS note, 'fixture' AS source_ref,
                   [struct_pack(event_id:=338384::BIGINT, basis:='video_states_event_id', scope:='event')] AS meeting_links
            UNION ALL
            SELECT 'm-high', 'event', '338384', 338384::BIGINT, NULL, 'youtube:ZS8XQIeEgTo',
                   'https://www.youtube.com/watch?v=ZS8XQIeEgTo', 'publisher_link', 'linked', 100::SMALLINT,
                   'unknown', 'asserted', NULL, 'fixture',
                   [struct_pack(event_id:=338384::BIGINT, basis:='publisher_link', scope:='event')]
            UNION ALL
            SELECT 'm-html', 'event', '338384', 338384::BIGINT, NULL, NULL::VARCHAR,
                   'https://www.congress.gov/event/117th-Congress/house-event/114136', 'publisher_link', 'linked', 100::SMALLINT,
                   'unknown', 'asserted', NULL, 'fixture',
                   [struct_pack(event_id:=338384::BIGINT, basis:='publisher_link', scope:='event')]
        ) TO {literal(root / 'recording_matches.parquet')} (FORMAT PARQUET)""")

    with closing(Reader(prepare(tmp_path / 'sel', manifest(root)))) as reader:
        inv = reader.transcript_inventory({'event_id': 338384, 'kind': 'captions'})
        assert inv['rows'] == []
        assert inv['captions'] == {'advertised': True, 'archived': 0, 'basis': 'advertised_not_archived'}

        bundle = reader.get_hearing_bundle({'event_id': 338384, 'include': ['meeting', 'captions', 'recordings']})
        assert bundle['sections']['meeting']['rows'][0]['captions'] == {
            'advertised': True, 'archived': 0, 'basis': 'advertised_not_archived',
        }
        assert bundle['sections']['captions']['rows'] == []
        recs = bundle['sections']['recordings']['rows']
        assert len(recs) == 1
        assert recs[0]['video_key'] == 'youtube:ZS8XQIeEgTo'
        assert recs[0]['score'] == 100
        assert recs[0]['basis'] == 'publisher_link'


def test_partitioned_nomination_urls_and_english_congress_ordinals(phase2, tmp_path):
    """P1-7: pending_nominations preserves partition numbers (/1022/10) and formats 1st/2nd/3rd Congress ordinals."""
    root = tmp_path / 'release'
    shutil.copytree(phase2.parent, root)
    with duckdb.connect() as db:
        db.execute(f"""COPY (
            SELECT '119-pn-1022-10' AS nomination_id, 'Mark Cruz, of Oregon' AS description,
                   'Department of Health and Human Services' AS organization,
                   DATE '2025-09-02' AS received, DATE '2025-10-15' AS latest_action_date,
                   'Placed on Senate Executive Calendar.' AS latest_action_text,
                   ['slia00'] AS committees, []::VARCHAR[] AS transcripts,
                   []::STRUCT(vote_id VARCHAR, date DATE, question VARCHAR, result VARCHAR, yea SMALLINT, nay SMALLINT)[] AS floor_votes
            UNION ALL
            SELECT '102-pn-45', 'Earlier Nominee', 'Department of State',
                   DATE '1991-03-01', DATE '1991-04-01', 'Referred to Committee.',
                   ['ssfr00'], []::VARCHAR[], []
        ) TO {literal(root / 'nominations.parquet')} (FORMAT PARQUET)""")
        db.execute(f"""COPY (
            SELECT * REPLACE('101-hr-5' AS bill_id, DATE '1989-01-03' AS introduced)
            FROM read_parquet({literal(root / 'bills.parquet')})
            UNION ALL
            SELECT * REPLACE('103-s-12' AS bill_id, DATE '1993-01-21' AS introduced)
            FROM read_parquet({literal(root / 'bills.parquet')})
            UNION ALL
            SELECT * REPLACE('111-hr-9' AS bill_id, DATE '2009-01-06' AS introduced)
            FROM read_parquet({literal(root / 'bills.parquet')})
        ) TO {literal(root / 'bills.parquet')} (FORMAT PARQUET)""")

    with closing(Reader(prepare(tmp_path / 'sel', manifest(root)))) as reader:
        noms = {
            r['nomination_id']: r['publisher_url']
            for r in reader.run_research_query({'name': 'pending_nominations'})['rows']
        }
        assert noms['119-pn-1022-10'] == 'https://www.congress.gov/nomination/119th-congress/1022/10'
        assert noms['102-pn-45'] == 'https://www.congress.gov/nomination/102nd-congress/45'

        bills = {
            r['bill_id']: r['publisher_url']
            for r in reader.run_research_query({'name': 'recent_bills'})['rows']
        }
        assert bills['101-hr-5'] == 'https://www.congress.gov/bill/101st-congress/house-bill/5'
        assert bills['103-s-12'] == 'https://www.congress.gov/bill/103rd-congress/senate-bill/12'
        assert bills['111-hr-9'] == 'https://www.congress.gov/bill/111th-congress/house-bill/9'


def test_superseded_witness_key_redirects_and_prepared_testimony_canonicalizes_keys(phase2, tmp_path):
    """P1-5: get_entity/search_documents redirect superseded witness_keys, and prepared_testimony deduplicates to canonical witness_keys."""
    root = tmp_path / 'release'
    shutil.copytree(phase2.parent, root)
    def add_superseded(rows):
        rows[0].update(
            document_kind=['witness-statement'],
            meeting_keys=['335321'],
            witness_keys=['appearance-1', 'mods-appearance-1'],
            hidden=False,
        )
    replace_rows(root, 'list', add_superseded)
    with closing(Reader(prepare(tmp_path / 'sel', manifest(root)))) as reader:
        ent = reader.get_entity({'table': 'witnesses', 'id': 'mods-appearance-1'})
        assert ent['redirected_from'] == 'mods-appearance-1'
        assert ent['rows'][0]['witness_key'] == 'appearance-1'

        bundle = reader.get_hearing_bundle({'event_id': 335321, 'include': ['witnesses', 'prepared_testimony']})
        roster_keys = {w['witness_key'] for w in bundle['sections']['witnesses']['rows']}
        stmt_rows = bundle['sections']['prepared_testimony']['rows']
        assert stmt_rows
        assert stmt_rows[0]['witness_keys'] == ['appearance-1']
        assert set(stmt_rows[0]['witness_keys']) <= roster_keys


def test_retired_link_removal_error_names_resolved_part_filenames(phase2, tmp_path):
    """F5: retired multi-part notice resolves address_versions hex keys to human-readable filenames from links+list."""
    root = tmp_path / 'release'
    shutil.copytree(phase2.parent, root)
    def name_parts(rows):
        rows[0]['filename'] = 'CHRG-115hhrg24725-pt1.pdf'
        rows[1]['filename'] = 'CHRG-115hhrg24725-pt2.pdf'
    replace_rows(root, 'list', name_parts)
    links = pq.read_table(root / 'links.parquet').to_pylist()
    k1 = next(r['link_key'].hex() for r in links if r['list_row'] == 0)
    k2 = next(r['link_key'].hex() for r in links if r['list_row'] == 1)
    with duckdb.connect() as db:
        db.execute(f"""COPY (
            SELECT unhex('cb0383af1fd10c1e') AS link_key,
                   NULL::BLOB AS successor_key,
                   repeat('e', 64) AS last_release_id,
                   'CHRG-115hhrg24725.pdf' AS last_filename,
                   [unhex('{k1}'), unhex('{k2}')] AS address_versions
        ) TO {literal(root / 'retired_links.parquet')} (FORMAT PARQUET)""")

    with closing(Reader(prepare(tmp_path / 'sel', manifest(root)))) as reader:
        with pytest.raises(ExplorerError) as exc_info:
            reader.get_document({'link_key': 'cb0383af1fd10c1e', 'release_id': reader.release_id})
        msg = str(exc_info.value)
        assert f'{k1} (CHRG-115hhrg24725-pt1.pdf)' in msg
        assert f'{k2} (CHRG-115hhrg24725-pt2.pdf)' in msg


def test_multihop_superseded_witness_keys_canonicalized_across_document_and_transcript_surfaces(phase2, tmp_path):
    """WARNING 3: search_documents, get_document(summary/selected_text), document_body_target, and transcript_inventory
    all canonicalize and deduplicate multi-hop superseded witness_keys."""
    root = tmp_path / 'release'
    shutil.copytree(phase2.parent, root)
    with duckdb.connect() as db:
        db.execute(f"""COPY (
            SELECT * FROM read_parquet({literal(root / 'witnesses.parquet')})
            UNION ALL
            SELECT * REPLACE('mods-hop-0' AS witness_key, 'mods-appearance-1' AS superseded_by)
            FROM read_parquet({literal(root / 'witnesses.parquet')}) WHERE witness_key='mods-appearance-1'
        ) TO {literal(root / 'witnesses.parquet')} (FORMAT PARQUET)""")
        db.execute(f"""COPY (
            SELECT 'prior-canon-key' AS old_key, 'appearance-1' AS witness_key, 'unambiguous' AS status,
                   'locator' AS basis, []::VARCHAR[] AS candidate_keys, 'meeting:335321' AS occasion, 'congress_gov' AS source
        ) TO {literal(root / 'witness_key_map.parquet')} (FORMAT PARQUET)""")

    def update_list(rows):
        rows[0].update(
            document_kind=['committee-transcript'],
            meeting_keys=['335321'],
            witness_keys=['mods-hop-0', 'mods-appearance-1', 'appearance-1'],
            hidden=False,
        )
    replace_rows(root, 'list', update_list)

    def update_meetings(rows):
        for r in rows:
            if r['event_id'] == 335321:
                r['transcripts'] = [{
                    'source': 'committee_transcript',
                    'package_id': None,
                    'list_row': 0,
                    'formats': ['html'],
                    'video_key': None,
                    'language': None,
                    'production': None,
                }]
    replace_rows(root, 'meetings', update_meetings)

    # Ensure detail/documents row 0 also exposes selected_text for selected_text() verification
    with duckdb.connect() as db:
        detail_cols = {r[0] for r in db.execute(f"DESCRIBE SELECT * FROM read_parquet({literal(root / 'detail.parquet')})").fetchall()}
        if 'selected_text' in detail_cols:
            db.execute(f"""COPY (
                SELECT * REPLACE(
                    CASE WHEN list_row=0 THEN 'Transcript body text for witness canonicalization.' ELSE selected_text END AS selected_text,
                    CASE WHEN list_row=0 THEN struct_pack(
                        text_available:=true, selector:='main', reader_version:='v1',
                        text_sha256:=repeat('ab', 32)
                    ) ELSE main_content END AS main_content
                )
                FROM read_parquet({literal(root / 'detail.parquet')})
            ) TO {literal(root / 'detail.parquet')} (FORMAT PARQUET)""")

    with closing(Reader(prepare(tmp_path / 'sel', manifest(root)))) as reader:
        doc_rows = reader.search_documents({'meeting_key': '335321'})['rows']
        row0 = next(r for r in doc_rows if r['list_row'] == 0)
        link_key = row0['reference']['link_key']

        summary = reader.get_document({'release_id': reader.release_id, 'link_key': link_key, 'section': 'summary'})['rows'][0]
        assert summary['witness_keys'] == ['appearance-1']

        target = reader.document_body_target({'release_id': reader.release_id, 'link_key': link_key})
        assert target['witness_keys'] == ['appearance-1']
        assert target['prior_witness_keys'] == ['prior-canon-key']

        if 'selected_text' in reader.schemas.get('documents', {}):
            sel = reader.get_document({'release_id': reader.release_id, 'link_key': link_key, 'section': 'selected_text'})
            assert sel['witness_keys'] == ['appearance-1']

        inv = reader.transcript_inventory({'event_id': 335321})
        t_row = next(r for r in inv['rows'] if r['kind'] in ('official', 'committee'))
        assert t_row['witness_keys'] == ['appearance-1']

