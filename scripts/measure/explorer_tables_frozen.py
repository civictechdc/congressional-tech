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
from docspec_client.client import NativeDatasets
from viewer_publication.archive_format import MEETING_DICTIONARY, _settings
from viewer_publication.archive_model_lifetimes import retire_relations
from viewer_publication.archive_model_profile import expand_parser_version_rows
from viewer_publication.archive_model import (EXPLORER_TABLES, RECORDING_DECISION_FIELDS, ROOT, WITNESSES_SQL, appearance_steps, channel_directory_rows,
    meeting_steps, registry_inputs, selected_record_step)
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
    """Only MODS readings feed package_mods_facts; scoping them first keeps 370 MB of readings out of the job."""
    path = work / 'page-facts.parquet'
    with duckdb.connect(config=dict(memory_limit='800MB', threads=2, temp_directory=str(work / 'duckdb'))) as db:
        db.execute(f"""COPY (SELECT body_sha,status,named_meetings FROM read_parquet('{spec['readings']['path']}')
            WHERE parser='xml' AND xml_root='mods') TO '{path}' (FORMAT PARQUET)""")
    return path


def positioned_detail(release, work):
    """list_row is a physical position, which an engine window over a scan does not preserve."""
    work.mkdir(parents=True, exist_ok=True)
    path = work / 'detail-positions.parquet'
    with duckdb.connect() as db:
        db.execute(f"""COPY (SELECT package_id,file_row_number AS list_row FROM read_parquet('{release / 'detail.parquet'}',file_row_number=true)) TO '{path}' (FORMAT PARQUET)""")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('spec', 'release', 'lake', 'decisions', 'output', 'runtime'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    spec = json.loads(args.spec.read_text())
    args.output.mkdir(parents=True)
    work = args.output / '.work'
    parquet = lambda name, path: dict(name=name, kind='parquet', path=str(path))
    inputs = registry_inputs(work / 'registries') + [
        parquet('captures', scoped_captures(spec, work)),
        parquet('meeting_records', spec['meeting_records']['path']),
        parquet('appearance_records_lake', spec['appearance_records']['path']),
        parquet('video_records', args.lake / 'video_records.parquet'),
        parquet('committee_records', args.lake / 'committee_records.parquet'),
        parquet('list', args.release / 'list.parquet'),
        parquet('released_meetings', args.release / 'meetings.parquet'),
        parquet('released_detail', positioned_detail(args.release, work)),
        parquet('page_facts', mods_page_facts(spec, work)),
        parquet('recordings_export', args.release / 'recordings.parquet'),
        dict(name='recording_decision_records', kind='json_lines', files=[dict(key='decisions', path=str(args.decisions))],
             schema=dict(fields=[field(k, v) for k, v in RECORDING_DECISION_FIELDS.items()], metadata={})),
        json_input(work, 'channel_directory', channel_directory_rows(), handle='Utf8', channel_id='Utf8', system_code='Utf8', committee_label='Utf8', role='Utf8'),
        json_input(work, 'parser_versions', expand_parser_version_rows(spec['parser_versions']), parser='Utf8', version='Utf8'),
    ]
    steps = [
        dict(name='meeting_records_input', sql="SELECT lower(encode(record_sha,'hex')) AS record_sha_hex,parser_version,status,error_type,source,meetings FROM meeting_records", materialize=True),
        selected_record_step('meeting_records', 'meeting_records_input'),
        # The lake table as the model's prepared appearance input (archive_model._normalize_appearance_rows).
        dict(name='appearance_records_input', sql="SELECT lower(encode(record_sha,'hex')) AS record_sha_hex,* EXCLUDE(record_sha),cast(NULL AS VARCHAR) AS context_url FROM appearance_records_lake", materialize=True),
        selected_record_step('appearance_records', 'appearance_records_input'),
        selected_record_step('video_records', 'video_records'),
        selected_record_step('committee_records', 'committee_records'),
        dict(name='active_recording_decisions', sql='SELECT r.* FROM recording_decision_records r WHERE NOT EXISTS(SELECT 1 FROM recording_decision_records s WHERE s.supersedes=r.id)', materialize=True),
        dict(name='youtube_cache_bodies', sql=sql('youtube-cache-bodies'), materialize=True),
        dict(name='youtube_api_bodies', sql=sql('youtube-api-bodies'), materialize=True),
        *meeting_steps(),
        dict(name='ordered', sql='SELECT meeting_keys FROM "list"', materialize=True),
        dict(name='appearance_people', sql=sql('appearance-people'), materialize=True),
        dict(name='package_mods_facts', sql=sql('package-mods-facts'), materialize=True),
        dict(name='print_meeting_agreement', sql=sql('print-meeting-agreement'), materialize=True),
        dict(name='meeting_mods_links', sql=sql('meeting-mods-links'), materialize=True),
        dict(name='meeting_transcript_links', sql="""SELECT event_id,t['package_id'] AS package_id FROM (SELECT event_id,unnest(transcripts) AS t FROM released_meetings)
            UNION SELECT event_id,package_id FROM meeting_mods_links""", materialize=True),
        dict(name='package_meeting_links', sql=sql('package-meeting-links'), materialize=True),
        # Curated URL variants live outside the frozen inputs; with none, Senate page keys may differ
        # from the release, equally on both sides of a before/after comparison.
        dict(name='url_variants', sql='SELECT cast(NULL AS VARCHAR) AS canonical_url,cast(NULL AS VARCHAR) AS variant_url WHERE false', materialize=True),
        *appearance_steps(),
        dict(name='witnesses_export', sql=WITNESSES_SQL, materialize=True),
        dict(name='meeting_document_urls', sql=sql('meeting-document-urls'), materialize=True),
        dict(name='details', sql='SELECT package_id,cast(list_row AS INT) AS list_row FROM released_detail', materialize=True),
        dict(name='meetings_export', sql=sql('entity-meetings'), materialize=True),
    ]
    outputs = [dict(name='resolved_meetings.parquet', path=str(args.output / 'resolved_meetings.parquet'),
        sql="SELECT event_id,chamber,title,meeting_date,session,status,committees,subject_keys,videos,congress,congress_gov_updated,house_xml_updated,congress_gov_meeting_type,meeting_type,sittings,access,access_basis,not_held,title_key,reschedule_candidate,committee_key,transcript_jackets FROM meetings_resolved",
        settings=_settings('whole', ['event_id']))]
    outputs.append(dict(name='meetings.parquet', path=str(args.output / 'meetings.parquet'), sql='SELECT * FROM meetings_export', settings=_settings('whole', ['event_id'], dictionary=MEETING_DICTIONARY)))
    outputs.append(dict(name='meeting_transcript_links.parquet', path=str(args.output / 'meeting_transcript_links.parquet'),
        sql='SELECT DISTINCT package_id,event_id FROM meeting_transcript_links', settings=_settings('whole', ['package_id', 'event_id'])))
    outputs.append(dict(name='witnesses.parquet', path=str(args.output / 'witnesses.parquet'), sql='SELECT * FROM witnesses_export',
        settings=_settings('whole', ['occasion', 'panel_order', 'display_order', 'witness_key'])))
    for name, file, keys, dictionary in EXPLORER_TABLES:
        steps.append(dict(name=name + '_export', sql=sql(file), materialize=True))
        outputs.append(dict(name=name + '.parquet', path=str(args.output / (name + '.parquet')), sql=f'SELECT * FROM {name}_export',
            settings=_settings('whole', keys, dictionary=dictionary)))
    # The maintained lifetime plan releases each relation at its last reader.
    job = retire_relations(dict(scratch=str(work / 'native'), inputs=inputs, steps=steps, outputs=outputs, queries=[]))
    path = work / 'job.json'
    path.write_text(json.dumps(job))
    with NativeDatasets.from_config(args.runtime) as engine:
        result = engine.run_job(path)
    print(json.dumps({item['name']: dict(rows=item['rows'], size=item['size']) for item in result['outputs']}))


if __name__ == '__main__':
    main()
