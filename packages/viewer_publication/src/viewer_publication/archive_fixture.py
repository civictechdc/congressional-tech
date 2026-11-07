"""Author the reader acceptance release with the maintained native writer."""
from hashlib import sha256
import json
from pathlib import Path

from congress_api.retention.provenance import (list_of as _list,
    struct as _struct, json_input as _json_input)
from viewer_publication.archive_format import (EMPTY_STRINGS, EMPTY_ALTERNATES,
    _step, _binary, _normal, _empty_struct, TS, MEETING_DICTIONARY,
    NULL_MEETING_DOCUMENT_REFERENCES)


def _body(byte):
    return f"repeat(lpad(to_hex(cast({byte} AS BIGINT)),2,'0'),32)"


def fixture_auxiliary():
    """Author current reader tables; the fixture has no capture attempts."""
    sittings = _empty_struct(start=TS, end=TS, place='cast(NULL AS VARCHAR)', room='cast(NULL AS VARCHAR)',
        building='cast(NULL AS VARCHAR)', address='cast(NULL AS VARCHAR)')
    committees = _empty_struct(system_code='cast(NULL AS VARCHAR)', role='cast(NULL AS VARCHAR)')
    transcripts = _empty_struct(source='cast(NULL AS VARCHAR)', package_id='cast(NULL AS VARCHAR)', list_row='cast(NULL AS INT)', formats=EMPTY_STRINGS,
                                video_key='cast(NULL AS VARCHAR)', language='cast(NULL AS VARCHAR)', production='cast(NULL AS VARCHAR)')
    videos = _empty_struct(name='cast(NULL AS VARCHAR)', url='cast(NULL AS VARCHAR)', video_key='cast(NULL AS VARCHAR)')
    names = _empty_struct(name='cast(NULL AS VARCHAR)', start='cast(NULL AS DATE)', end='cast(NULL AS DATE)')
    return [
        ('meetings', f"""WITH keys AS (SELECT try_cast(unnest(meeting_keys) AS BIGINT) AS event_id FROM ordered),
            meta AS (SELECT *,true AS has_detail FROM meeting_input UNION ALL SELECT event_id,cast(NULL AS VARCHAR) AS chamber,
                cast(NULL AS VARCHAR) AS title,cast(NULL AS DATE) AS meeting_date,false AS has_detail FROM keys WHERE event_id IS NOT NULL)
            SELECT event_id,max(chamber) AS chamber,
                CASE WHEN max(chamber) IS NOT NULL THEN 'source' WHEN bool_or(has_detail) THEN 'source_chamber_unknown'
                     ELSE 'meeting_detail_missing' END AS chamber_basis,
                max(title) AS title,max(meeting_date) AS meeting_date,
                cast(NULL AS VARCHAR) AS meeting_type,cast(NULL AS SMALLINT) AS session,cast(NULL AS VARCHAR) AS status,
                {sittings} AS sittings,{committees} AS committees,{EMPTY_STRINGS} AS subject_keys,
                {transcripts} AS transcripts,{videos} AS videos,cast(NULL AS SMALLINT) AS congress,{TS} AS congress_gov_updated,
                cast(NULL AS VARCHAR) AS house_xml_updated,cast(NULL AS VARCHAR) AS congress_gov_meeting_type,
                cast(NULL AS VARCHAR) AS access,cast(NULL AS VARCHAR) AS access_basis,cast(NULL AS BOOLEAN) AS not_held,cast(NULL AS BIGINT) AS rescheduled_to,cast(NULL AS VARCHAR) AS rescheduled_basis,
                {NULL_MEETING_DOCUMENT_REFERENCES} AS document_references FROM meta GROUP BY event_id""", ['event_id'],
            MEETING_DICTIONARY),
        ('committees', f"""SELECT system_code,name,chamber,cast(NULL AS VARCHAR) AS committee_type,
            cast(NULL AS VARCHAR) AS parent_system_code,{names} AS names,cast(NULL AS VARCHAR) AS website,
            cast(NULL AS BOOLEAN) AS is_current FROM committee_input""", ['system_code'], ['chamber', 'committee_type', 'parent_system_code']),
        ('witnesses', f"""SELECT witness_key,occasion,source,{_binary('record_sha', 32)} AS record_sha,
            source_locator,context_key,event_id,package_id,page_url,name,position,organization,
            on_behalf_of,location,panel,panel_order,display_order,witness_type,testified,bioguide_id,
            superseded_by FROM hand_witnesses""",
            ['occasion', 'panel_order', 'display_order', 'witness_key'],
            ['occasion', 'source', 'witness_type', 'bioguide_id']),
        ('witness_key_map', 'SELECT old_key,witness_key,status,basis,candidate_keys,occasion,source FROM hand_witness_key_map',
            ['old_key'], ['occasion', 'source', 'status', 'basis']),
        ('url_state', f"""SELECT cast(NULL AS VARCHAR) AS requested_url,cast(NULL AS INT) AS attempts,
            {TS} AS last_attempt,cast(NULL AS SMALLINT) AS last_status,cast(NULL AS VARCHAR) AS last_outcome,
            {TS} AS last_good_at,{TS} AS next_attempt_at,cast(NULL AS VARCHAR) AS capture_disposition,
            cast(NULL AS VARCHAR) AS capture_reason,cast(NULL AS VARCHAR) AS capture_decision_id WHERE false""",
            ['requested_url'], ['last_outcome'])]


def prepare_fixture_release(fixture, *, output, scratch, adapter, workspace, operation,
                            metadata_queries=(), entity_files=None):
    """Prepare the authored reader fixture through the current DDK definitions."""
    from ddk.catalog import assemble_catalog
    from viewer_publication.archive_catalog import capture_definitions, captured_catalog_options
    from viewer_publication.archive_format import native_release_job, prepare_native_release

    fixture, output, scratch = Path(fixture), Path(output), Path(scratch)
    scratch.mkdir(parents=True, exist_ok=False)
    project = capture_definitions(scratch/'definitions')
    catalog = assemble_catalog(project, **captured_catalog_options(project))
    source_bytes = fixture.read_bytes()
    data = json.loads(source_bytes)
    # These are authored input records, not a migration of retained source data.
    # The only added value is the application's stable endpoint ID formula.
    documents = [dict(row, version_key=sha256(json.dumps([row['source_url'].removeprefix('https://'), None],
        ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:16]) for row in data['documents']]
    inputs = [_json_input(scratch, 'hand', documents, name='Utf8', filename='Utf8', title='Utf8', body_byte='Int64',
        format='Utf8', document_date='Utf8', document_date_source='Utf8', congress='Int64', first_captured='Utf8', hidden='Boolean', review_note='Utf8',
        review_decided_at='Utf8', source_url='Utf8', meeting_keys=_list('Utf8'), version_names=_list('Utf8'),
        version_key='Utf8', extra_link_body_bytes=_list('Int64'),
        committee_keys=_list('Utf8'), chambers=_list('Utf8'), measure_keys=_list('Utf8'),
        bioguide_ids=_list('Utf8'), witness_keys=_list('Utf8'),
        alternates=_list(_struct(format='Utf8', body_byte='Int64', suffix='Utf8', size='Int64')),
        recovery=_struct(kind='Utf8', recovered_url='Utf8', identity_note='Utf8', imported_at='Utf8')),
        _json_input(scratch, 'hand_meetings', data['meetings'], event_id='Int64', chamber='Utf8', title='Utf8', meeting_date='Utf8'),
        _json_input(scratch, 'hand_witnesses', data['witnesses'], witness_key='Utf8', occasion='Utf8', source='Utf8',
            record_sha='Utf8', source_locator='Utf8', context_key='Utf8', event_id='Int64', package_id='Utf8',
            page_url='Utf8', name='Utf8', position='Utf8', organization='Utf8', on_behalf_of='Utf8', location='Utf8',
            panel='Utf8', panel_order='Int16', display_order='Int16', witness_type='Utf8', testified='Boolean',
            bioguide_id='Utf8', superseded_by='Utf8'),
        _json_input(scratch, 'hand_witness_key_map', data['witness_key_map'], old_key='Utf8', witness_key='Utf8',
            status='Utf8', basis='Utf8', candidate_keys=_list('Utf8'), occasion='Utf8', source='Utf8')]
    steps = [_step('hand_bodies', f"SELECT *,{_body('body_byte')} AS body_hex FROM hand"),
        _step('hand_alternates', 'SELECT name,unnest(alternates) AS alt FROM hand'),
        _step('alternate_groups', f"""SELECT name,array_agg(named_struct('format',alt['format'],
            'body',{_binary(_body("alt['body_byte']"), 32)},'suffix',alt['suffix'],'size',alt['size']) ORDER BY alt['format']) AS alternatives,
            array_agg({_body("alt['body_byte']")} ORDER BY alt['format']) AS bodies FROM hand_alternates GROUP BY name"""),
        _step('hand_extra_bodies', 'SELECT name,unnest(extra_link_body_bytes) AS extra FROM hand'),
        _step('extra_groups', f'SELECT name,array_agg({_body("extra")} ORDER BY extra) AS bodies FROM hand_extra_bodies GROUP BY name'),
        _step('normalized', _normal('hand_bodies h LEFT JOIN alternate_groups a ON h.name=a.name LEFT JOIN extra_groups e ON h.name=e.name',
            doc_key='h.name', filename='h.filename', title='h.title', format='h.format', body_hex='h.body_hex', source_url='h.source_url',
            congress='cast(h.congress AS SMALLINT)', committee_keys='h.committee_keys', chambers='h.chambers',
            measure_keys='h.measure_keys', bioguide_ids='h.bioguide_ids', witness_keys='h.witness_keys',
            document_date='try_cast(h.document_date AS DATE)', first_captured='try_cast(h.first_captured AS DATE)',
            date_kind="CASE WHEN h.first_captured IS NOT NULL THEN 'captured' WHEN h.recovery IS NOT NULL THEN 'import_day' ELSE 'unknown' END",
            saved_kind="CASE WHEN h.recovery IS NOT NULL THEN 'recovery' ELSE 'original' END", hidden='h.hidden',
            meeting_keys=f'coalesce(h.meeting_keys,{EMPTY_STRINGS})',
            version_keys=f"CASE WHEN cardinality(h.version_names)>0 THEN make_array(h.version_key) ELSE {EMPTY_STRINGS} END",
            bytes='cast(100 AS BIGINT)', media_type="'application/pdf'", document_date_source="CASE WHEN h.document_date IS NOT NULL THEN coalesce(h.document_date_source,'content') END",
            in_archive_since="try_cast(h.recovery['imported_at'] AS DATE)", review_note='h.review_note', review_decided_at='try_cast(h.review_decided_at AS DATE)',
            alternates=f'coalesce(a.alternatives,{EMPTY_ALTERNATES})',
            link_bodies=f"CASE WHEN h.recovery IS NOT NULL THEN {EMPTY_STRINGS} ELSE array_concat(make_array(h.body_hex),coalesce(a.bodies,{EMPTY_STRINGS}),coalesce(e.bodies,{EMPTY_STRINGS})) END"), materialize=True),
        _step('source_input', """SELECT name AS doc_key,name AS source_key,source_url AS url,cast(NULL AS VARCHAR) AS member_path,
            recovery IS NULL AS is_saved,try_cast(first_captured AS DATE) AS first_seen,cast(NULL AS VARCHAR) AS listed_on,
            title AS link_text,cast(NULL AS VARCHAR) AS doc_type,cast(NULL AS DATE) AS posted FROM hand"""),
        _step('recovery_input', f"""SELECT name AS doc_key,name AS recovery_key,source_url AS original_url,recovery['kind'] AS kind,
            {_binary(_body('body_byte'), 32)} AS body,'.gz' AS suffix,cast(100 AS BIGINT) AS bytes,
            try_cast(recovery['imported_at'] AS DATE) AS imported_at,recovery['recovered_url'] AS recovered_url,
            recovery['identity_note'] AS identity_note FROM hand WHERE recovery IS NOT NULL"""),
        _step('meeting_input', 'SELECT event_id,chamber,title,try_cast(meeting_date AS DATE) AS meeting_date FROM hand_meetings'),
        _step('committee_input', 'SELECT cast(NULL AS VARCHAR) AS system_code,cast(NULL AS VARCHAR) AS name,cast(NULL AS VARCHAR) AS chamber WHERE false'),
    ]
    origin = dict(kind='hand_fixture', source_sha256=sha256(source_bytes).hexdigest(),
                  gaps=['Synthetic reader fixture; capture scheduling is disabled'])
    auxiliary = fixture_auxiliary()
    entities = entity_files or {}
    if set(entities) - {'meetings', 'committees', 'witnesses', 'rosters', 'members',
                        'bills', 'nominations', 'recordings', 'videos'}:
        raise ValueError('Unknown authored reader fixture entity table')
    definitions = catalog.local_catalog['extensions']['urn:ddk:catalog:assembly']['datasetDefinitions']
    for name, path in entities.items():
        inputs.append(dict(name='fixture_'+name, kind='parquet', path=str(Path(path).resolve(strict=True))))
        alias, = [alias for alias, table in definitions.items() if table['name'] == name]
        identity, = [item for item in catalog.local_catalog['identities']
                     if item['dataset'] == alias and item['kind'] == 'key']
        keys = [field['path'][0]['field'] for field in identity['fields']]
        auxiliary = [item for item in auxiliary if item[0] != name]
        auxiliary.append((name, 'SELECT * FROM fixture_'+name, keys, []))
    job, diagnostics = native_release_job(inputs, steps, catalog_result=catalog,
        output=output, scratch=scratch, auxiliary=auxiliary, origin=origin,
        metadata_queries=metadata_queries)
    return prepare_native_release(job, diagnostics, adapter=adapter, project=project,
        catalog_result=catalog, request_dir=scratch, workspace=workspace, dataset='archive-fixture',
        operation=operation, policy_id='archive-required-v1', file_pins={}, producer_proof=None, producer_definition=None,
        expected_epoch=0, expected_selection=None, controls_dir=output, private_outputs=(), origin=origin,
        capture_scope=None, content_files={'witness_map_expected.json': data['expected']['witnesses']},
        entity_digests=None)


def build_fixture_release(fixture, *, output, scratch, adapter, workspace, operation,
                          metadata_queries=(), entity_files=None):
    from viewer_publication.archive_format import execute_native_release

    prepared = prepare_fixture_release(fixture, output=output, scratch=scratch, adapter=adapter,
        workspace=workspace, operation=operation, metadata_queries=metadata_queries, entity_files=entity_files)
    return execute_native_release(prepared, adapter=adapter)
