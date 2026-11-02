"""Build the Explorer tables and meetings resolution alone, without rebuilding documents.

    explorer_tables_frozen.py --spec model.json --release V21_RELEASE --lake DIR --decisions FILE --output DIR --runtime RUNTIME

Runs the maintained SQL over a finished release plus frozen lake inputs, so a comparison
needs no full model run. It does not prove byte identity of other files, or the full job's
memory: only a full run can. `ordered` and the meeting transcripts come from that release.
"""
import argparse
import json
from pathlib import Path

import duckdb
from docspec_client.client import NativeDatasets
from viewer_publication.archive_format import MEETING_DICTIONARY, _settings
from viewer_publication.archive_model_lifetimes import retire_relations
from viewer_publication.archive_model_profile import expand_parser_version_rows
from viewer_publication.archive_model import (EXPLORER_TABLES, RECORDING_DECISION_FIELDS, ROOT, channel_directory_rows, meeting_steps, selected_record_step,
    registry_inputs)
from congress_api.retention.provenance import field, json_input, run_job


def sql(name):
    return (ROOT / 'model/sql' / (name + '.sql')).read_text()


def scoped_captures(spec, work):
    """Both captures readers want only these rows. Scoping in DuckDB first keeps this job's
    pool on the tables it measures, not on the document model's join over all captures."""
    work.mkdir(parents=True, exist_ok=True)
    path = work / 'captures.parquet'
    with duckdb.connect(config=dict(memory_limit='800MB', threads=2, temp_directory=str(work / 'duckdb'))) as db:
        db.execute(f"""COPY (SELECT sha256,retrieved_at,mode,complete,outcome,http_status,family,url,requested_url,stored_suffix
            FROM read_parquet('{spec['captures']['path']}') c
            WHERE mode='fetch' AND sha256 IS NOT NULL AND (family='pipeline-data' OR sha256 IN
             (SELECT record_sha FROM read_parquet('{spec['meeting_records']['path']}')))) TO '{path}' (FORMAT PARQUET)""")
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
        parquet('appearance_records_input', spec['appearance_records']['path']),
        parquet('video_records', args.lake / 'video_records.parquet'),
        parquet('committee_records', args.lake / 'committee_records.parquet'),
        parquet('list', args.release / 'list.parquet'),
        parquet('released_meetings', args.release / 'meetings.parquet'),
        parquet('released_detail', args.release / 'detail.parquet'),
        parquet('witnesses_export', args.release / 'witnesses.parquet'),
        parquet('recordings_export', args.release / 'recordings.parquet'),
        dict(name='recording_decision_records', kind='json_lines', files=[dict(key='decisions', path=str(args.decisions))],
             schema=dict(fields=[field(k, v) for k, v in RECORDING_DECISION_FIELDS.items()], metadata={})),
        json_input(work, 'channel_directory', channel_directory_rows(), handle='Utf8', channel_id='Utf8', system_code='Utf8', committee_label='Utf8', role='Utf8'),
        json_input(work, 'parser_versions', expand_parser_version_rows(spec['parser_versions']), parser='Utf8', version='Utf8'),
    ]
    steps = [
        dict(name='meeting_records_input', sql="SELECT lower(encode(record_sha,'hex')) AS record_sha_hex,parser_version,status,error_type,source,meetings FROM meeting_records", materialize=True),
        selected_record_step('meeting_records', 'meeting_records_input'),
        selected_record_step('appearance_records', 'appearance_records_input'),
        selected_record_step('video_records', 'video_records'),
        selected_record_step('committee_records', 'committee_records'),
        dict(name='active_recording_decisions', sql='SELECT r.* FROM recording_decision_records r WHERE NOT EXISTS(SELECT 1 FROM recording_decision_records s WHERE s.supersedes=r.id)', materialize=True),
        dict(name='youtube_cache_bodies', sql=sql('youtube-cache-bodies'), materialize=True),
        *meeting_steps(),
        dict(name='ordered', sql='SELECT meeting_keys FROM "list"', materialize=True),
        dict(name='meeting_transcript_links', sql="SELECT event_id,t['package_id'] AS package_id FROM (SELECT event_id,unnest(transcripts) AS t FROM released_meetings)", materialize=True),
        dict(name='details', sql='SELECT package_id,cast(row_number() OVER()-1 AS INT) AS list_row FROM released_detail', materialize=True),
        dict(name='meetings_export', sql=sql('entity-meetings'), materialize=True),
    ]
    outputs = [dict(name='resolved_meetings.parquet', path=str(args.output / 'resolved_meetings.parquet'),
        sql="SELECT event_id,chamber,title,meeting_date,session,status,committees,subject_keys,videos,congress,congress_gov_updated,house_xml_updated,congress_gov_meeting_type,meeting_type,sittings,access,access_basis,not_held,title_key,reschedule_candidate,committee_key,transcript_jackets FROM meetings_resolved",
        settings=_settings('whole', ['event_id']))]
    outputs.append(dict(name='meetings.parquet', path=str(args.output / 'meetings.parquet'), sql='SELECT * FROM meetings_export', settings=_settings('whole', ['event_id'], dictionary=MEETING_DICTIONARY)))
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
