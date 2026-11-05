"""Consumer fixtures: canonical archive files plus the normative phase 2 entity shapes."""
from hashlib import sha256, md5
from copy import deepcopy
import json
from pathlib import Path
import shutil

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congressional_explorer_mcp.release import encoded, prepare, literal
from congressional_explorer_mcp.reader import Reader

REPO = Path(__file__).resolve().parents[3]
CURRENT = REPO / 'model/fixtures/archive-contract/current'


def manifest(root, shards=None):
    shards = shards or {}
    files = []
    for path in sorted(root.iterdir()):
        if path.name == 'manifest.json' or path.suffix not in ('.json', '.parquet'):
            continue
        data = path.read_bytes()
        files.append(dict(name=path.name, sha256=sha256(data).hexdigest(), md5=md5(data).hexdigest(),
            size=len(data), rows=pq.read_metadata(path).num_rows if path.suffix == '.parquet' else 0,
            producer='mcp-test', coverage={'gaps': ['Synthetic phase 2 reader fixture']}, **shards.get(path.name, {})))
    value = dict(schema_version=1, files=files)
    value['release_id'] = sha256(encoded([1, [[f[k] for k in ('name', 'sha256', 'size', 'rows')] for f in files]])).hexdigest()
    (root / 'manifest.json').write_bytes(encoded(value))
    return root / 'manifest.json'


def replace_rows(root, name, update):
    path = root / f'{name}.parquet'
    table = pq.read_table(path)
    rows = table.to_pylist()
    update(rows)
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)


@pytest.fixture(scope='module')
def phase2(tmp_path_factory):
    root = tmp_path_factory.mktemp('phase2') / 'release'
    shutil.copytree(CURRENT, root)
    def link(rows):
        rows[0].update(congress=119, committee_keys=['hsif00'], measure_keys=['119-hr-1', '119-pn-730-2'],
                       meeting_keys=['118001', '335321'],
                       witness_keys=['appearance-1', '0001497931f99cd1'], bioguide_ids=['A000001'], document_kind=['agenda'])
        rows[4].update(version_keys=[])
    replace_rows(root, 'list', link)
    def meeting(rows):
        rows[0].update(committees=[dict(system_code='hsif00', role='host')], subject_keys=['119-hr-1', '119-pn-730-2'],
            transcripts=[dict(package_id='CHRG-118hhrg1', list_row=0)],
            videos=[dict(name='Hearing video', url='https://video.example/1', video_key='youtube:abc')])
        m2 = deepcopy(rows[0])
        m2.update(event_id=335321, transcripts=[], videos=[])
        rows.append(m2)
    replace_rows(root, 'meetings', meeting)
    replace_rows(root, 'detail', lambda rows: rows[1].update(package_id='CHRG-118hhrg1'))
    with duckdb.connect() as db:
        def write(name, sql):
            db.execute(f'COPY ({sql}) TO {literal(root / (name+".parquet"))} (FORMAT PARQUET)')
        write('witnesses', """SELECT 'appearance-'||i AS witness_key,'meeting:'||i AS occasion,
            CASE WHEN i=1 THEN 335321::BIGINT ELSE (118000+i)::BIGINT END AS event_id,
            CASE WHEN i=2 THEN 'CHRG-118hhrg1' END AS package_id,NULL::VARCHAR AS page_url,
            'Alex Smith' AS name,'Director' AS position,'Transit Lab' AS organization,
            NULL::VARCHAR AS on_behalf_of,NULL::VARCHAR AS location,'Panel A' AS panel,
            1::SMALLINT AS panel_order,i::SMALLINT AS display_order,'public' AS witness_type,
            true AS testified,NULL::VARCHAR AS bioguide_id,NULL::VARCHAR AS superseded_by FROM range(1,3) t(i)
            UNION ALL
            SELECT * FROM (VALUES
                ('0001497931f99cd1','page:1',NULL::BIGINT,NULL::VARCHAR,NULL::VARCHAR,'Jordan Taylor','Counsel','Policy Group',NULL::VARCHAR,NULL::VARCHAR,NULL::VARCHAR,NULL::SMALLINT,1::SMALLINT,'public',NULL::BOOLEAN,NULL::VARCHAR,NULL::VARCHAR),
                ('0000b43c099edbc2','package:1',NULL::BIGINT,'CHRG-118hhrg1',NULL::VARCHAR,'Jordan Taylor','Counsel','Policy Group',NULL::VARCHAR,NULL::VARCHAR,NULL::VARCHAR,NULL::SMALLINT,2::SMALLINT,'public',NULL::BOOLEAN,NULL::VARCHAR,NULL::VARCHAR),
                ('mods-appearance-1','package:2',335321::BIGINT,'CHRG-118hhrg1',NULL::VARCHAR,'A. Smith','Director','Transit Lab',NULL::VARCHAR,NULL::VARCHAR,NULL::VARCHAR,NULL::SMALLINT,1::SMALLINT,'public',NULL::BOOLEAN,NULL::VARCHAR,'appearance-1')
            )""")
        write('witness_key_map', """SELECT 'old-appearance-1' AS old_key,'appearance-1' AS witness_key,
            'unambiguous' AS status,'occurrence' AS basis,[]::VARCHAR[] AS candidate_keys,
            'meeting:1' AS occasion,'senate_page' AS source""")
        write('recordings', """SELECT 'youtube:abc' AS video_key,[118001::BIGINT, 335321::BIGINT] AS event_ids,
            [struct_pack(body:=unhex(repeat('55',32)),suffix:='.gz',format:='vtt',language:='en',production:='automatic')] AS tracks""")
        write('committees', """SELECT 'hsif00' AS system_code,'Energy and Commerce' AS name,'house' AS chamber,
            'standing' AS committee_type,NULL::VARCHAR AS parent_system_code,
            [struct_pack(name:='Interstate Commerce',start:=DATE '1947-01-03',"end":=DATE '1974-12-31')] AS names,
            'https://committee.example' AS website,true AS is_current""")
        write('members', """SELECT 'A000001' AS bioguide_id,'Sam Example' AS name,
            [struct_pack(chamber:='house',state:='NY',district:=1::SMALLINT,party:='I',start:=DATE '2025-01-03',"end":=DATE '2027-01-03')] AS terms,
            struct_pack(lis:=NULL::VARCHAR,opensecrets:='N1',govtrack:='1',icpsr:='1',wikidata:='Q1',fec:=['H1','H2']) AS cross_ids""")
        write('rosters', """SELECT 113::SMALLINT AS congress,'hsif00' AS system_code,'A000001' AS bioguide_id,
            'Member' AS title,5::SMALLINT AS rank,'I' AS party
            UNION ALL SELECT 119::SMALLINT AS congress,'hsif00' AS system_code,'A000001' AS bioguide_id,
            'Member' AS title,3::SMALLINT AS rank,'I' AS party""")
        write('bills', """SELECT '119-hr-1' AS bill_id,'Transit Funding Act' AS title,'One Big Beautiful Bill Act' AS short_title,
            'A000001' AS sponsor_bioguide_id,DATE '2025-01-03' AS introduced,DATE '2025-02-01' AS latest_action_date,
            'Reported' AS latest_action_text,'reported' AS stage,'Transportation' AS policy_area,
            '119-1' AS public_law_number,42::INTEGER AS cosponsor_count,
            [struct_pack(bill_id:='119-s-1',title:='Companion Transit Act',relationship_types:=['Companion bill'])] AS related_bills,
            ['hsif00'] AS committees,
            [struct_pack(publication_id:='CBO1',date:=DATE '2025-01-15',description:='Cost estimate')] AS cbo_estimates,
            [struct_pack(vote_id:='119-h-1',basis:='vote_record',chamber:='house',date:=DATE '2025-02-01',question:='On passage',result:='Passed',yea:=220::SMALLINT,nay:=210::SMALLINT)] AS floor_votes,
            [struct_pack(amendment_id:='119-hamdt-1',purpose:='Add transit safety',sponsor_bioguide_id:='A000001',latest_action_date:=DATE '2025-02-01',latest_action_text:='Agreed')] AS amendments,
            [struct_pack(system_code:='hsif00',activity:='Reported',date:=DATE '2025-02-01')] AS committee_activities""")
        write('nominations', """SELECT '119-pn-730-2' AS nomination_id,'Transit administrator' AS description,
            'Transportation' AS organization,DATE '2025-01-03' AS received,DATE '2025-02-01' AS latest_action_date,
            'Confirmed' AS latest_action_text,['hsif00'] AS committees,['CHRG-118hhrg1'] AS transcripts,
            [struct_pack(vote_id:='119-s-1',date:=DATE '2025-02-01',question:='Confirmation',result:='Confirmed',yea:=70::SMALLINT,nay:=30::SMALLINT)] AS floor_votes
            UNION ALL
            SELECT '119-pn-11-12' AS nomination_id,'Deputy administrator' AS description,
            'Transportation' AS organization,DATE '2025-01-03' AS received,DATE '2025-02-01' AS latest_action_date,
            'Confirmed' AS latest_action_text,['hsif00'] AS committees,['CHRG-118hhrg1'] AS transcripts,
            [] AS floor_votes""")
        write('videos', """SELECT 'youtube:free' AS video_key,'@AgRepublicans' AS handle,'Unmatched upload' AS title,TIMESTAMP '2025-01-03 00:00:00' AS published_at""")
        write('recording_matches', """SELECT 'a' AS match_id,'event' AS subject_kind,'115538' AS subject_id,115538::BIGINT AS event_id,NULL::VARCHAR AS package_id,'youtube:abc' AS video_key,NULL::VARCHAR AS url,'publisher_link' AS basis,
            'linked' AS decision,100::SMALLINT AS score,'unknown' AS recording_scope,'asserted' AS status,NULL::VARCHAR AS note,'fixture' AS source_ref,
            [struct_pack(event_id:=115538::BIGINT,basis:='direct_event',scope:='event')] AS meeting_links""")
        write('meeting_coverage', """SELECT 118001::BIGINT AS event_id,'recording' AS aspect,'present' AS state""")
        write('channels', """SELECT '@AgRepublicans' AS handle,'UC1' AS channel_id,'hsag00' AS system_code,'Agriculture' AS committee_label,
            'primary' AS role,'House Agriculture Republicans' AS title,true AS uploads_scan_complete,'curated_directory' AS mapping_basis""")
        write('committee_records', """SELECT 'rec-1' AS record_key,118001::BIGINT AS event_id,'amendment' AS kind,'H.R. 1' AS bill,
            'Substitute amendment agreed by voice vote' AS source_description,0::INTEGER AS ordinal""")
        write('url_variants', """SELECT 'https://fixture.test/a' AS canonical_url,'http://fixture.test/a' AS variant_url""")
        write('future_data', "SELECT 'new published column' AS future_field,42.123456789012345678::DECIMAL(38,18) AS amount")
    # Read only the producer-owned JSON. The MCP runtime has no producer dependency.
    (root / 'schema.json').write_bytes((REPO / 'model/registries/release-schema.json').read_bytes())
    return manifest(root)


@pytest.fixture(scope='module')
def selection(phase2, tmp_path_factory):
    return prepare(tmp_path_factory.mktemp('selected'), phase2, archive_origin='https://archive.example')


@pytest.fixture
def reader(selection):
    reader = Reader(selection)
    reader.db.execute(
        'CREATE TEMP TABLE _list_base AS SELECT * FROM "list"; '
        'CREATE OR REPLACE VIEW "list" AS SELECT * FROM _list_base '
        'UNION ALL SELECT * REPLACE (8 AS list_row, true AS hidden) FROM _list_base WHERE list_row=3'
    )
    try:
        yield reader
    finally:
        reader.close()


@pytest.fixture(scope='module')
def linked_transcripts(phase2, tmp_path_factory):
    """Indirect transcripts, repeated paths and a hidden document in native shapes."""
    root = tmp_path_factory.mktemp('linked-transcripts') / 'release'
    shutil.copytree(phase2.parent, root)
    hidden = []
    def documents(rows):
        hidden.extend(i for i, row in enumerate(rows) if row['hidden'])
        for i in (1, 2):
            rows[i].update(measure_keys=[], document_kind=['published-hearing'], hidden=False,
                           meeting_keys=['118001', '118002'] if i == 1 else ['118001'])
    replace_rows(root, 'list', documents)
    def meetings(rows):
        rows[0]['transcripts'] = [dict(package_id='CHRG-118hhrg1', list_row=i) for i in (1, 1, 2, hidden[0])]
        other = deepcopy(rows[0])
        other.update(event_id=118002, transcripts=[dict(package_id='CHRG-118hhrg1', list_row=1)])
        rows[:] = [rows[0], other]
    replace_rows(root, 'meetings', meetings)
    return manifest(root)


def pytest_addoption(parser):
    parser.addoption('--native-fixture-root', help='Retained output directory of the producer phase 2 fixture runner')
