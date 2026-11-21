"""Build the Explorer tables and meetings resolution alone, without rebuilding documents.

    explorer_tables_frozen.py --spec model.json --release V21_RELEASE --lake DIR --decisions FILE --output DIR --runtime RUNTIME

Runs the maintained SQL over a finished release plus frozen lake inputs, so a comparison
needs no full model run. It does not prove byte identity of other files, or the full job's
memory: only a full run can. `ordered` and the jacket transcript links come from that release;
MODS links, package choice and witnesses are rebuilt from the lake and the pinned MODS readings.
Document links need `ordered` rebuilt, so only a full run measures them.
"""
import argparse
import json
from pathlib import Path

import duckdb
from congress_api.lake import compatible_versions
from docspec_client.client import NativeDatasets
from viewer_publication.archive_format import MEETING_DICTIONARY, _settings
from viewer_publication.archive_model_lifetimes import retire_relations
from viewer_publication.archive_model_profile import expand_parser_version_rows, readings_bundle_version
from viewer_publication.archive_model import (EMPTY_RECORDING_PAGE_VIDEO_EVENTS_SQL, EXPLORER_TABLES, RECORDING_DECISION_FIELDS, ROOT, SPICY_SCHEMAS, TRANSCRIPT_HEADINGS_UNAVAILABLE, VIDEO_KEY_ALIASES_SQL, WITNESSES_SQL, appearance_steps, channel_directory_rows, known_meetings_sql, meeting_records_have_document_references,
    meeting_steps, recording_match_prep_steps, registry_inputs, selected_record_step, senate_page_prelim_links_sql)
from viewer_publication.meeting_detail_observations import EMPTY_OBSERVATIONS
from viewer_publication.release_gate import (BASE_PERSON_ALIASES, BASE_WITNESS_KEY_MAP, PRIOR_PEOPLE, PRIOR_WITNESSES,
    _write_prior_table)
from congress_api.retention.provenance import field, json_input, run_job


def sql(name):
    return (ROOT / 'model/sql' / (name + '.sql')).read_text()


def scoped_captures(spec, work):
    """Both captures readers want only these rows. Scoping in DuckDB first keeps this job's
    pool on the tables it measures, not on the document model's join over all captures."""
    work.mkdir(parents=True, exist_ok=True)
    path = work / 'captures.parquet'
    with duckdb.connect(config=dict(memory_limit='800MB', threads=2, temp_directory=str(work / 'duckdb'))) as db:
        db.execute(f"""COPY (SELECT * FROM read_parquet('{spec['captures']['path']}') c
            WHERE sha256 IS NOT NULL AND (family='pipeline-data' OR sha256 IN
             (SELECT record_sha FROM read_parquet('{spec['meeting_records']['path']}') UNION
              SELECT record_sha FROM read_parquet('{spec['appearance_records']['path']}')))) TO '{path}' (FORMAT PARQUET)""")
    return path


def mods_page_facts(spec, work):
    """Keep detected page readings for MODS and Senate appearances."""
    path = work / 'page-facts.parquet'
    versions = spec['parser_versions']
    entries = compatible_versions.load_registry(current={**versions, 'readings': readings_bundle_version(versions)})
    with duckdb.connect(config=dict(memory_limit='800MB', threads=2, temp_directory=str(work / 'duckdb'))) as db:
        db.read_parquet(spec['readings']['path']).create_view('readings')
        db.read_parquet(spec['captures']['path']).create_view('captures')
        db.read_parquet(spec['appearance_records']['path']).create_view('appearances')
        db.execute('CREATE TEMP TABLE parser_versions(parser VARCHAR, version VARCHAR)')
        pins = {p: versions[p] for p in compatible_versions.LEAF_PARSERS}
        db.executemany('INSERT INTO parser_versions VALUES (?, ?)', list(pins.items()))
        db.execute('CREATE TEMP TABLE accepted_versions(parser VARCHAR, version VARCHAR)')
        accepted = compatible_versions.accepted_version_rows(entries, pins=pins)
        db.executemany('INSERT INTO accepted_versions VALUES (?, ?)', [(r['parser'], r['version']) for r in accepted])
        for step in compatible_versions.selected_readings_steps(entries):
            kind = 'TABLE' if step.get('materialize') else 'VIEW'
            db.execute(f"CREATE TEMP {kind} {step['name']} AS {step['sql']}")
        db.execute('CREATE TEMP VIEW pinned_readings AS ' + sql('pinned-readings'))
        # Bound the format conflict check to bodies the frozen tables could use.
        db.execute("""CREATE TEMP TABLE page_bodies AS
            SELECT record_sha AS body_sha FROM appearances WHERE source='senate_page'
            UNION SELECT body_sha FROM pinned_readings WHERE parser='xml' AND xml_root='mods'""")
        db.execute(f'''CREATE TEMP TABLE sniff_observations AS
            SELECT o.* FROM ({sql('sniff-observations')}) o SEMI JOIN page_bodies USING (body_sha)''')
        db.execute('CREATE TEMP VIEW sniff_conflicts AS ' + sql('sniff-conflicts'))
        # DuckDB spells the production RIGHT ANTI JOIN with the observations first.
        db.execute('''CREATE TEMP VIEW sniff_facts AS SELECT body_sha,max(format) AS format
            FROM sniff_observations ANTI JOIN sniff_conflicts USING (body_sha) GROUP BY body_sha''')
        db.execute(f"""COPY (SELECT body_sha,status,title,heading,text_head,content_date,named_meetings
            FROM ({sql('page-facts')})
            WHERE (parser='xml' AND xml_root='mods')
               OR body_sha IN (SELECT record_sha FROM appearances WHERE source='senate_page'))
            TO ? (FORMAT PARQUET)""", [str(path)])
    return path


DEFAULT_SPICY_REGS_DIR = Path('/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/r1b/inputs/spicy_regs')


def positioned_list(release, work):
    """The list file with its physical row number, which committee transcripts cite as list_row."""
    work.mkdir(parents=True, exist_ok=True)
    path = work / 'list-positions.parquet'
    with duckdb.connect() as db:
        db.execute(f"""COPY (SELECT l.meeting_keys,l.measure_keys,l.filename,l.format,
            l.chambers,l.committee_keys,l.congress,l.document_date,d.document_date_status,l.hidden,
            l.file_row_number AS list_row
            FROM read_parquet('{release / 'list.parquet'}',file_row_number=true) l
            JOIN read_parquet('{release / 'detail.parquet'}',file_row_number=true) d USING (file_row_number)) TO '{path}' (FORMAT PARQUET)""")
    return path


def spicy_inputs(work, spicy_regs_dir):
    # Members and their terms decide which witness rows are Member appearances (ct-kw85).
    names = ('spicy_committees', 'spicy_bill_committee_activities', 'spicy_congress_bills', 'spicy_nominations',
             'spicy_members', 'spicy_member_terms')
    if spicy_regs_dir is not None and (spicy_regs_dir / 'spicy-regs.json').is_file():
        tables = json.loads((spicy_regs_dir / 'spicy-regs.json').read_text())['tables']
        return [dict(name=name, kind='parquet', path=str(spicy_regs_dir / tables[name]['path'])) for name in names]
    return [
        json_input(work, 'spicy_committees', [], system_code='Utf8', parent_system_code='Utf8', website_url='Utf8'),
        json_input(work, 'spicy_bill_committee_activities', [], **SPICY_SCHEMAS['spicy_bill_committee_activities']),
        json_input(work, 'spicy_congress_bills', [], **SPICY_SCHEMAS['spicy_congress_bills']),
        json_input(work, 'spicy_nominations', [], **SPICY_SCHEMAS['spicy_nominations']),
        json_input(work, 'spicy_members', [], **SPICY_SCHEMAS['spicy_members']),
        json_input(work, 'spicy_member_terms', [], **SPICY_SCHEMAS['spicy_member_terms']),
    ]


def positioned_detail(release, work):
    """list_row is a physical position, which an engine window over a scan does not preserve."""
    work.mkdir(parents=True, exist_ok=True)
    path = work / 'detail-positions.parquet'
    with duckdb.connect() as db:
        # detail and list share row positions; transcripts read the saved format and alternates (g).
        db.execute(f"""COPY (SELECT d.package_id,d.file_row_number AS list_row,l.format,d.alternates,d.link_key
            FROM read_parquet('{release / 'detail.parquet'}',file_row_number=true) d
            JOIN read_parquet('{release / 'list.parquet'}',file_row_number=true) l USING (file_row_number)) TO '{path}' (FORMAT PARQUET)""")
    return path


def frozen_ledger_inputs(release, work):
    """Carry prior witness/person identity ledgers from the frozen release when present, else empty typed tables."""
    release = Path(release)
    out = Path(work) / 'ledgers'
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = release / 'manifest.json'
    base_release_id = json.loads(manifest_path.read_text()).get('release_id', '') if manifest_path.is_file() else ''
    _write_prior_table(release / 'witnesses.parquet', out / 'prior_witnesses.parquet',
                       PRIOR_WITNESSES, defaults={'listing_status': 'listed'})
    _write_prior_table(release / 'witness_key_map.parquet', out / 'base_witness_key_map.parquet', BASE_WITNESS_KEY_MAP)
    _write_prior_table(release / 'people.parquet', out / 'prior_people.parquet',
                       PRIOR_PEOPLE, defaults={'release_id': base_release_id, 'ranks': []})
    _write_prior_table(release / 'person_aliases.parquet', out / 'base_person_aliases.parquet', BASE_PERSON_ALIASES)
    return [
        dict(name=name, kind='parquet', path=str(out / f'{name}.parquet'))
        for name in ('prior_witnesses', 'base_witness_key_map', 'prior_people', 'base_person_aliases')
    ]


def build_steps_and_outputs(*, output, has_document_references, has_caption_resources):
    """Build the ordered frozen Explorer steps and outputs."""
    output = Path(output)
    steps = [
        dict(name='meeting_records_input', sql="SELECT lower(encode(record_sha,'hex')) AS record_sha_hex,parser_version,status,error_type,source,meetings FROM meeting_records", materialize=True),
        selected_record_step('meeting_records', 'meeting_records_input'),
        # The lake table as the model's prepared appearance input (archive_model._normalize_appearance_rows).
        dict(name='appearance_records_input', sql="SELECT lower(encode(record_sha,'hex')) AS record_sha_hex,* EXCLUDE(record_sha),cast(NULL AS VARCHAR) AS context_url FROM appearance_records_lake", materialize=True),
        selected_record_step('appearance_records', 'appearance_records_input'),
        *meeting_steps(has_document_references=has_document_references),
        dict(name='person_nicknames', sql=sql('person-nicknames'), materialize=True),
        dict(name='appearance_people', sql=sql('appearance-people'), materialize=True),
        dict(name='person_same_family', sql=sql('person-same-family'), materialize=True),
        dict(name='person_given_matches', sql=sql('person-given-matches'), materialize=True),
        dict(name='package_mods_facts', sql=sql('package-mods-facts'), materialize=True),
        dict(name='senate_page_records', sql=sql('senate-page-records'), materialize=True),
        dict(name='senate_page_candidates', sql=sql('senate-page-candidates'), materialize=True),
        dict(name='senate_page_prelim_links', sql=senate_page_prelim_links_sql(), materialize=True),
        dict(name='print_meeting_agreement', sql=sql('print-meeting-agreement'), materialize=True),
        dict(name='meeting_mods_links', sql=sql('meeting-mods-links'), materialize=True),
        dict(name='meeting_transcript_links', sql="""SELECT event_id,t['package_id'] AS package_id FROM (SELECT event_id,unnest(transcripts) AS t FROM released_meetings)
            UNION SELECT event_id,package_id FROM meeting_mods_links""", materialize=True),
        dict(name='package_meeting_links', sql=sql('package-meeting-links'), materialize=True),
        # Curated URL variants live outside the frozen inputs; with none, Senate page keys may differ
        # from the release, equally on both sides of a before/after comparison.
        dict(name='url_variants', sql='SELECT cast(NULL AS VARCHAR) AS canonical_url,cast(NULL AS VARCHAR) AS variant_url WHERE false', materialize=True),
        # No transcript_headings input: the transcript decides nothing here (ct-sfra).
        dict(name='transcript_headings', sql=TRANSCRIPT_HEADINGS_UNAVAILABLE, materialize=True),
        selected_record_step('transcript_headings', 'transcript_headings'),
        dict(name='document_packages', sql='SELECT package_id,cast(list_row AS BIGINT) AS component FROM released_detail WHERE package_id IS NOT NULL', materialize=True),
        dict(name='document_metadata', sql='SELECT cast(list_row AS BIGINT) AS component,committee_keys,meeting_keys FROM released_list', materialize=True),
        *appearance_steps(),
        dict(name='witnesses_export', sql=WITNESSES_SQL, materialize=True),
        selected_record_step('video_records', 'video_records'),
        selected_record_step('committee_records', 'committee_records'),
        dict(name='active_recording_decisions', sql='SELECT r.* FROM recording_decision_records r WHERE NOT EXISTS(SELECT 1 FROM recording_decision_records s WHERE s.supersedes=r.id)', materialize=True),
        dict(name='youtube_cache_bodies', sql=sql('youtube-cache-bodies'), materialize=True),
        dict(name='youtube_api_bodies', sql=sql('youtube-api-bodies'), materialize=True),
        dict(name='ordered', sql='SELECT meeting_keys,measure_keys,filename,format,chambers,committee_keys,congress,document_date,document_date_status,hidden,cast(list_row AS INT) AS list_row FROM released_list WHERE coalesce(array_length(meeting_keys),0)>0', materialize=True),
        dict(name='known_meetings', sql=known_meetings_sql('ordered'), materialize=True),
        dict(name='recording_url_sources', sql="SELECT id,pattern,key_template,format,default_language,default_production FROM recording_sources WHERE kind='video_url'", materialize=True),
        dict(name='video_key_aliases', sql=VIDEO_KEY_ALIASES_SQL, materialize=True),
        dict(name='recordings_export', sql='SELECT * FROM recordings_entity', materialize=True),
        dict(name='retained_caption_tracks', sql=(
            "SELECT DISTINCT video_key,track_body FROM released_caption_resources WHERE status='retained' AND ordinal>0 AND format IN ('vtt','srt','ttml')"
            if has_caption_resources
            else "SELECT cast(NULL AS VARCHAR) AS video_key,arrow_cast(NULL,'FixedSizeBinary(32)') AS track_body WHERE false"
        ), materialize=True),
        dict(name='meeting_document_urls', sql=sql('meeting-document-urls'), materialize=True),
        dict(name='details', sql='SELECT package_id,cast(list_row AS INT) AS list_row,format,alternates,link_key FROM released_detail', materialize=True),
        dict(name='meeting_detail_observations', sql=EMPTY_OBSERVATIONS, materialize=True),
        dict(name='meetings_export', sql=sql('entity-meetings'), materialize=True),
    ]
    outputs = [dict(name='resolved_meetings.parquet', path=str(output / 'resolved_meetings.parquet'),
        sql="SELECT event_id,chamber,title,meeting_date,session,status,committees,subject_keys,videos,congress,congress_gov_updated,house_xml_updated,congress_gov_meeting_type,meeting_type,sittings,access,access_basis,not_held,title_key,reschedule_candidate,committee_key,transcript_jackets FROM meetings_resolved",
        settings=_settings('whole', ['event_id']))]
    outputs.append(dict(name='meetings.parquet', path=str(output / 'meetings.parquet'), sql='SELECT * FROM meetings_export', settings=_settings('whole', ['event_id'], dictionary=MEETING_DICTIONARY)))
    outputs.append(dict(name='meeting_transcript_links.parquet', path=str(output / 'meeting_transcript_links.parquet'),
        sql='SELECT DISTINCT package_id,event_id FROM meeting_transcript_links', settings=_settings('whole', ['package_id', 'event_id'])))
    outputs.append(dict(name='witnesses.parquet', path=str(output / 'witnesses.parquet'), sql='SELECT * FROM witnesses_export',
        settings=_settings('whole', ['occasion', 'panel_order', 'display_order', 'witness_key'])))
    for name, file, keys, dictionary in EXPLORER_TABLES:
        if name == 'recording_matches':
            steps.append(dict(name='recording_page_video_events', sql=EMPTY_RECORDING_PAGE_VIDEO_EVENTS_SQL, materialize=True))
            steps.extend(recording_match_prep_steps(videos_relation='videos_export', include_stopwords=True))
        steps.append(dict(name=name + '_export', sql=sql(file), materialize=True))
        outputs.append(dict(name=name + '.parquet', path=str(output / (name + '.parquet')), sql=f'SELECT * FROM {name}_export',
            settings=_settings('whole', keys, dictionary=dictionary)))
    return steps, outputs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('spec', 'release', 'lake', 'decisions', 'output', 'runtime'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--spicy-regs-dir', type=Path, default=DEFAULT_SPICY_REGS_DIR if DEFAULT_SPICY_REGS_DIR.is_dir() else None)
    args = parser.parse_args(argv)
    spec = json.loads(args.spec.read_text())
    args.output.mkdir(parents=True)
    work = args.output / '.work'
    parquet = lambda name, path: dict(name=name, kind='parquet', path=str(path))
    has_caption_resources = (args.release / 'caption_resources.parquet').is_file()
    inputs = registry_inputs(work / 'registries') + [
        parquet('captures', scoped_captures(spec, work)),
        parquet('meeting_records', spec['meeting_records']['path']),
        parquet('appearance_records_lake', spec['appearance_records']['path']),
        parquet('video_records', args.lake / 'video_records.parquet'),
        parquet('committee_records', args.lake / 'committee_records.parquet'),
        parquet('released_list', positioned_list(args.release, work)),
        parquet('released_meetings', args.release / 'meetings.parquet'),
        parquet('released_detail', positioned_detail(args.release, work)),
        parquet('page_facts', mods_page_facts(spec, work)),
        parquet('recordings_entity', args.release / 'recordings.parquet'),
        *([parquet('released_caption_resources', args.release / 'caption_resources.parquet')] if has_caption_resources else []),
        dict(name='recording_decision_records', kind='json_lines', files=[dict(key='decisions', path=str(args.decisions))],
             schema=dict(fields=[field(k, v) for k, v in RECORDING_DECISION_FIELDS.items()], metadata={})),
        json_input(work, 'channel_directory', channel_directory_rows(), handle='Utf8', channel_id='Utf8', system_code='Utf8', committee_label='Utf8', role='Utf8'),
        *spicy_inputs(work, args.spicy_regs_dir),
        *frozen_ledger_inputs(args.release, work),
        json_input(work, 'parser_versions', expand_parser_version_rows(spec['parser_versions']), parser='Utf8', version='Utf8'),
    ]
    steps, outputs = build_steps_and_outputs(
        output=args.output,
        has_document_references=meeting_records_have_document_references(spec['meeting_records']['path']),
        has_caption_resources=has_caption_resources,
    )
    # The maintained lifetime plan releases each relation at its last reader.
    job = retire_relations(dict(scratch=str(work / 'native'), inputs=inputs, steps=steps, outputs=outputs, queries=[]))
    path = work / 'job.json'
    path.write_text(json.dumps(job))
    with NativeDatasets.from_config(args.runtime) as engine:
        result = engine.run_job(path)
    print(json.dumps({item['name']: dict(rows=item['rows'], size=item['size']) for item in result['outputs']}))


if __name__ == '__main__':
    main()
