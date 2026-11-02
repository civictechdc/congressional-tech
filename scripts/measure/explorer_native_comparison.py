"""Account for every old Explorer row against the native release, in both directions.

    explorer_native_comparison.py --old OLD_RELEASE --release NEW_RELEASE [--overlay DIR]
        --data apps/committee_youtube/data --lake DIR --decisions FILE --output RESULT.json

DuckDB over written Parquet, a different tool family from the engine that wrote it. It
raises unless each side's rows equal matched plus its reasons. An identity proves the
ledger is complete, not that a reason is right; samples per reason are for the reviewer.
Natural keys can hide a wrong value, so a fixed-hash value check re-derives 200 rows per
family where a source value exists. Name normalization can merge two different people.
"""
import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys

import duckdb

SAMPLES = 20
REASONS = {
    'pending_r2_matcher': 'Scored date and title matches arrive with the native decide() producer.',
    'pending_r2_senate_page_link': 'Senate page-to-event links are held only in derived data until the derived-link layer.',
    'pending_r2_print_link': 'Print-to-meeting links are derived; they arrive with native hearing records.',
    'pending_r2_access_state': 'Access, closed, not-held and rescheduled facts arrive with native hearing records.',
    'old_state_only': 'Rows the old exporter built from state files with no native source yet; kept by old-release reference.',
    'new_snapshot_only': 'The frozen captures end at the 2026-10-28 snapshot, after the retained old inputs.',
    'native_found_more': 'The native record states rows the old derived file lacks.',
    'no_public_url': 'The source states no URL, so a URL key cannot match.',
    'witness_name_normalization': 'The event matches but the name spelling differs; not proof of a different person.',
    'old_uuid_diagnostic': 'A diagnostic about an old UUID row; the fact it concerns is carried natively, or by old-release reference.',
    'not_a_row_fact': 'A condition, not a stored fact: it is derived by query from native tables.',
    'member_ineligible_split_see_ct-qg8e': 'Archive-member eligibility split, awaiting the ct-qg8e owner decision.',
    'release_delta_unexplained_see_ct-qg8e': 'Release delta on row counts owned by the ct-qg8e accounting.',
    'superseded_by_newer_record': 'The key is in an older retained record of this event; the current record replaced it.',
    'other_source_meeting': 'An old meeting from a Senate page or House XML with no Congress.gov event ID.',
    'old_text_mojibake': 'The old CSV stored this text double-encoded; once repaired it equals the native value, which is the correct one.',
    'pending_r2_package_event_link': 'Raw MODS states the name, and native witnesses hold it on a package occasion with no event; the package-to-event link arrives with native hearing records.',
    'house_xml_witness_not_parsed': 'The event has House XML but native witnesses have no row for it; a family name in the raw XML is a lead, so this needs a parser check.',
    'derived_from_title_or_document': 'The old row came from a meeting title or a witness list PDF, which no native parser reads.',
    'unexplained': 'No reason established. Reported, not hidden.',
}
# A title's first matching pattern gives its disposition; section 6 of the cluster plan.
ISSUE_DISPOSITIONS = [
    ('original video publication time', 'old_uuid_diagnostic'), ('no verified meeting association', 'not_a_row_fact'),
    ('retained decision aggregates', 'pending_r2_matcher'), ('Package-level recordings', 'pending_r2_matcher'),
    ('clips_only verdict', 'pending_r2_matcher'), ('committee/day probe', 'not_a_row_fact'),
    ('no supported meeting association', 'not_a_row_fact'), ('Witness rows have no meeting ownership', 'not_a_row_fact'),
    ('Sources disagree about', 'old_uuid_diagnostic'), ('caption observation', 'old_uuid_diagnostic'),
    ('live check date', 'old_uuid_diagnostic'), ('live retrieval', 'old_uuid_diagnostic'),
    ('Legacy House state', 'old_state_only'), ('identity review', 'old_uuid_diagnostic'), ('correspondence review', 'old_uuid_diagnostic'),
    ('held date differs', 'old_uuid_diagnostic'), ('repeats the same convening', 'old_uuid_diagnostic'),
    ('House source file URL is malformed', 'old_uuid_diagnostic'), ('binary document data', 'old_uuid_diagnostic'),
]


def normal_url(column):
    return f"regexp_replace({column},'^http://','https://')"


def normal_name(column):
    return f"regexp_replace(lower(trim({column})),'[^a-z0-9]+',' ','g')"


def issue_disposition(title):
    return next((reason for pattern, reason in ISSUE_DISPOSITIONS if pattern in title), 'unexplained')


def account(db, family, old_sql, new_sql, *, old_reason="'unexplained'", new_reason="'unexplained'", multiset=False):
    """Compare (key, context) rows. Multiset pairs repeated keys; otherwise any presence matches.

    Reason expressions read the unmatched row's `key` and `context`.
    """
    db.execute(f'CREATE OR REPLACE TEMP TABLE o AS SELECT key,context,row_number() OVER(PARTITION BY key) AS n FROM ({old_sql})')
    db.execute(f'CREATE OR REPLACE TEMP TABLE w AS SELECT key,context,row_number() OVER(PARTITION BY key) AS n FROM ({new_sql})')
    pairing = 'x.key=y.key AND x.n=y.n' if multiset else 'x.key=y.key'

    def side(left, right, reason):
        db.execute(f"""CREATE OR REPLACE TEMP TABLE unmatched AS SELECT x.key,x.context,{reason} AS reason FROM {left} x
            WHERE x.key IS NULL OR NOT EXISTS (SELECT 1 FROM {right} y WHERE {pairing})""")
        total = db.execute(f'SELECT count(*) FROM {left}').fetchone()[0]
        unmatched = dict(db.execute('SELECT reason,count(*) FROM unmatched GROUP BY reason').fetchall())
        unknown = set(unmatched) - REASONS.keys()
        if unknown:
            raise ValueError(f'{family}: undeclared reasons {sorted(unknown)}')
        matched = total - sum(unmatched.values())
        samples = {reason: [list(map(str, row)) for row in db.execute(
            f"SELECT key,context FROM unmatched WHERE reason=? ORDER BY sha256(coalesce(key,'')||coalesce(context,'')) LIMIT {SAMPLES}", [reason]).fetchall()]
            for reason in unmatched}
        return total, matched, unmatched, samples

    old_rows, matched_old, old_only, old_samples = side('o', 'w', old_reason)
    new_rows, matched_new, new_only, new_samples = side('w', 'o', new_reason)
    if old_rows != matched_old + sum(old_only.values()) or new_rows != matched_new + sum(new_only.values()):
        raise ValueError(f'{family}: ledger does not balance')
    return dict(old_rows=old_rows, new_rows=new_rows, matched=matched_old, matched_new=matched_new,
        old_only_by_reason=old_only, new_only_by_reason=new_only,
        samples=dict(old_only=old_samples, new_only=new_samples))


def csv_view(data, name):
    return f"read_csv('{Path(data) / (name + '.csv')}',all_varchar=true,header=true,quote='\"',escape='\"',strict_mode=false)"


def compare(db, *, old, table, data, lake, decisions):
    """Every family of the annex inventory; `table` resolves a new release file."""
    o = lambda name: f"read_parquet('{Path(old) / (name + '.parquet')}')"
    c = lambda name: csv_view(data, name)
    out = {}
    db.execute(f"""CREATE TEMP TABLE old_meeting_event AS
        WITH m AS (SELECT id,unnest(source_ids) AS sid FROM {o('meetings')})
        SELECT m.id,max(try_cast(split_part(s.identifier_value,'|',4) AS BIGINT)) AS event_id
        FROM m JOIN {o('sources')} s ON m.sid=s.id WHERE s.identifier_scheme='congress.gov:record' GROUP BY m.id""")
    out['meetings'] = account(db, 'meetings',
        f"SELECT cast(e.event_id AS VARCHAR) AS key,m.id AS context FROM {o('meetings')} m LEFT JOIN old_meeting_event e ON m.id=e.id",
        f"SELECT cast(event_id AS VARCHAR) AS key,title AS context FROM {table('meetings')}",
        old_reason="CASE WHEN x.key IS NULL THEN 'other_source_meeting' ELSE 'unexplained' END", new_reason="'new_snapshot_only'")
    new_urls = f"SELECT DISTINCT {normal_url('url')} AS key,cast(NULL AS VARCHAR) AS context FROM {table('sources')} WHERE url IS NOT NULL"
    out['document_files'] = account(db, 'document_files',
        f"""SELECT {normal_url("f['url']")} AS key,id AS context FROM (SELECT id,unnest(files) AS f FROM {o('materials')} WHERE type='document')""",
        new_urls, old_reason="CASE WHEN x.key IS NULL THEN 'no_public_url' ELSE 'pending_r2_print_link' END", new_reason="'native_found_more'")
    for name, reason in (('house_documents_found', 'old_state_only'), ('senate_documents_found', 'pending_r2_senate_page_link')):
        out[name] = account(db, name, f"SELECT {normal_url('url')} AS key,event_id AS context FROM {c(name)}", new_urls,
            old_reason=f"CASE WHEN x.key IS NULL THEN 'no_public_url' ELSE '{reason}' END", new_reason="'native_found_more'")
    new_witness = f"""SELECT cast(event_id AS VARCHAR)||'|'||{normal_name('name')} AS key,witness_key AS context FROM {table('witnesses')}
        WHERE event_id IS NOT NULL AND name IS NOT NULL"""
    db.execute(f"CREATE TEMP TABLE witness_events AS SELECT DISTINCT cast(event_id AS VARCHAR) AS event_id FROM {table('witnesses')} WHERE event_id IS NOT NULL")
    absent = """CASE split_part(x.context,'|',2) WHEN 'senate committee page' THEN 'pending_r2_senate_page_link' WHEN 'gpo' THEN 'pending_r2_package_event_link'
        WHEN 'docs.house.gov' THEN 'house_xml_witness_not_parsed' ELSE 'derived_from_title_or_document' END"""
    for name, source in (('meeting_witnesses', 'source'), ('house_witnesses_found', "'docs.house.gov'"), ('senate_witnesses_found', "'senate committee page'")):
        out[name] = account(db, name, f"SELECT event_id||'|'||{normal_name('name')} AS key,event_id||'|'||{source} AS context FROM {c(name)}", new_witness,
            old_reason=f"CASE WHEN EXISTS (SELECT 1 FROM witness_events e WHERE e.event_id=split_part(x.context,'|',1)) THEN 'witness_name_normalization' ELSE {absent} END",
            new_reason="'native_found_more'")
    amendment_key = lambda event, description: f"""concat_ws('|',{event},kind,coalesce(url,''),coalesce("number",''),coalesce(bill,''),coalesce({description},''))"""
    new_amendments = table('committee_records')
    db.execute(f"""CREATE TEMP TABLE lake_amendments AS SELECT DISTINCT concat_ws('|',event_id,r.kind,coalesce(r.url,''),coalesce(r."number",''),coalesce(r.bill,''),coalesce(r.description,'')) AS key
        FROM (SELECT event_id,unnest(records) AS r FROM read_parquet('{Path(lake) / 'committee_records.parquet'}') WHERE event_id IS NOT NULL)""")
    out['amendments'] = account(db, 'amendments',
        f"SELECT {amendment_key('event_id', 'description')} AS key,event_id AS context FROM {c('house_amendments_found')}",
        f"SELECT {amendment_key('cast(event_id AS VARCHAR)', 'source_description')} AS key,record_key AS context FROM {new_amendments}",
        old_reason="""CASE WHEN x.key IN (SELECT key FROM lake_amendments) THEN 'superseded_by_newer_record'
            WHEN replace(x.key,'\u00c3\u00a1','\u00e1') IN (SELECT key FROM lake_amendments) THEN 'old_text_mojibake' ELSE 'unexplained' END""",
        new_reason="""CASE WHEN regexp_matches(x.key,'[^\\x00-\\x7f]') AND x.context IS NOT NULL
            AND x.key IN (SELECT replace(y.key,'\u00c3\u00a1','\u00e1') FROM o y) THEN 'old_text_mojibake' ELSE 'native_found_more' END""", multiset=True)
    # Pairs: curated rows directly, publisher links and claims through a meeting's transcripts.
    db.execute(f"""CREATE TEMP TABLE new_pairs AS
        SELECT package_id,video_key FROM {table('recording_matches')} WHERE package_id IS NOT NULL AND video_key IS NOT NULL
        UNION SELECT t.package_id,m.video_key FROM {table('recording_matches')} m
            JOIN (SELECT event_id,unnest(transcripts)['package_id'] AS package_id FROM {table('meetings')}) t ON m.event_id=t.event_id
            WHERE m.video_key IS NOT NULL""")
    out['recording_pairs'] = account(db, 'recording_pairs',
        f"""SELECT DISTINCT package_id||'|youtube:'||vid AS key,method AS context
            FROM (SELECT package_id,method,unnest(string_split(video_ids,' ')) AS vid FROM {c('gpo_hearing_videos')} WHERE coalesce(video_ids,'')<>'') WHERE regexp_matches(vid,'^[A-Za-z0-9_-]+$')""",
        "SELECT package_id||'|'||video_key AS key,cast(NULL AS VARCHAR) AS context FROM new_pairs",
        old_reason="'pending_r2_matcher'", new_reason="'native_found_more'")
    out['curated_decisions'] = account(db, 'curated_decisions',
        f"SELECT json_extract_string(json,'$.id') AS key,json_extract_string(json,'$.subject_id') AS context FROM read_ndjson_objects('{decisions}')",
        f"SELECT regexp_extract(source_ref,'recording_decisions:(.*)$',1) AS key,cast(NULL AS VARCHAR) AS context FROM {table('recording_matches')} WHERE basis='curated'")
    out['completeness'] = account(db, 'completeness',
        f"SELECT event_id AS key,recording AS context FROM {c('meeting_completeness')}",
        f"SELECT DISTINCT cast(event_id AS VARCHAR) AS key,cast(NULL AS VARCHAR) AS context FROM {table('meeting_coverage')}", new_reason="'new_snapshot_only'")
    out['completeness']['column_agreement'] = {
        name: dict(db.execute(f"""SELECT coalesce(old.{source},'')||' -> '||n.state AS pair,count(*) FROM {c('meeting_completeness')} old
            JOIN {table('meeting_coverage')} n ON cast(n.event_id AS VARCHAR)=old.event_id AND n.aspect='{aspect}' GROUP BY pair ORDER BY pair""").fetchall())
        for name, source, aspect in (('recording', 'recording', 'recording'), ('text_source', 'text_source', 'transcript'))}
    video_of = "regexp_extract(url,'[?&]v=([^&]+)',1)"
    out['videos'] = account(db, 'videos',
        f"SELECT 'youtube:'||{video_of} AS key,id AS context FROM {o('sources')} WHERE identifier_scheme='youtube:record'",
        f"SELECT video_key AS key,title AS context FROM {table('videos')}",
        old_reason="'old_state_only'", new_reason="'new_snapshot_only'")
    # The old committee rows are per Congress; a code present natively carries them.
    out['committees'] = account(db, 'committees', f"SELECT committee_code AS key,id AS context FROM {o('committees')}",
        f"SELECT system_code AS key,name AS context FROM {table('committees')}", old_reason="'old_state_only'", new_reason="'native_found_more'")
    out['witnesses'] = account(db, 'witnesses',
        f"""SELECT cast(e.event_id AS VARCHAR)||'|'||{normal_name('w.title')} AS key,w.id AS context FROM {o('witnesses')} w LEFT JOIN old_meeting_event e ON w.meeting_id=e.id""",
        new_witness, old_reason="CASE WHEN x.key IS NULL THEN 'pending_r2_senate_page_link' ELSE 'witness_name_normalization' END", new_reason="'native_found_more'")
    db.execute(f"""CREATE TEMP TABLE material_refs AS SELECT id,type,{normal_url('recording_url')} AS url FROM {o('materials')} WHERE type='recording'
        UNION ALL SELECT id,type,{normal_url("f['url']")} FROM (SELECT id,type,unnest(files) AS f FROM {o('materials')} WHERE type='document')""")
    db.execute(f"""CREATE TEMP TABLE new_refs AS {new_urls.replace(' AS key,cast(NULL AS VARCHAR) AS context','')}
        UNION SELECT 'https://www.youtube.com/watch?v='||substr(video_key,9) FROM {table('videos')}""")
    out['materials'] = account(db, 'materials',
        f"""SELECT id AS key,type AS context FROM {o('materials')} WHERE id IN (SELECT id FROM material_refs WHERE url IN (SELECT * FROM new_refs))
            UNION ALL SELECT id,type FROM {o('materials')} WHERE id NOT IN (SELECT id FROM material_refs WHERE url IN (SELECT * FROM new_refs))""",
        f"SELECT DISTINCT id AS key,cast(NULL AS VARCHAR) AS context FROM material_refs WHERE url IN (SELECT * FROM new_refs)",
        old_reason="CASE WHEN x.context='recording' THEN 'not_a_row_fact' ELSE 'pending_r2_print_link' END")
    scheme = dict(db.execute(f'SELECT identifier_scheme,count(*) FROM {o("sources")} GROUP BY 1').fetchall())
    out['old_sources'] = dict(old_rows=sum(scheme.values()), by_scheme=scheme,
        note='Source rows are evidence for the families above and stay by old-release reference; each scheme is compared through its family, not row by row.')
    return out


def issue_classes(db, old):
    rows = db.execute(f"SELECT title,status,count(*) FROM read_parquet('{Path(old) / 'issues.parquet'}') GROUP BY 1,2 ORDER BY 3 DESC").fetchall()
    classes = [dict(title=title, status=status, rows=count, disposition=issue_disposition(title)) for title, status, count in rows]
    return dict(old_rows=sum(c['rows'] for c in classes), classes=classes,
        unexplained=sum(c['rows'] for c in classes if c['disposition'] == 'unexplained'))


def value_checks(db, *, old, table, data, decisions, channels):
    """200 rows per family by fixed hash, source value against published value."""
    def sample(name, sql):
        rows = db.execute(f"""SELECT * FROM ({sql}) ORDER BY sha256(cast(key AS VARCHAR)) LIMIT 200""").fetchall()
        bad = [list(map(str, r)) for r in rows if r[1] != r[2]]
        return {name: dict(checked=len(rows), mismatched=len(bad), samples=bad[:SAMPLES])}
    o = lambda name: f"read_parquet('{Path(old) / (name + '.parquet')}')"
    out = {}
    out |= sample('curated_verdict', f"""SELECT json_extract_string(d.json,'$.id') AS key,json_extract_string(d.json,'$.verdict') AS expected,m.decision AS actual
        FROM read_ndjson_objects('{decisions}') d JOIN {table('recording_matches')} m
        ON m.source_ref='recording_decisions:'||json_extract_string(d.json,'$.id')""")
    out |= sample('meeting_date', f"""SELECT e.event_id AS key,cast(m.date AS VARCHAR) AS expected,cast(n.meeting_date AS VARCHAR) AS actual
        FROM {o('meetings')} m JOIN old_meeting_event e ON m.id=e.id JOIN {table('meetings')} n ON n.event_id=e.event_id""")
    out |= sample('video_title', f"""SELECT 'youtube:'||regexp_extract(s.url,'[?&]v=([^&]+)',1) AS key,s.title AS expected,v.title AS actual FROM {o('sources')} s
        JOIN {table('videos')} v ON v.video_key='youtube:'||regexp_extract(s.url,'[?&]v=([^&]+)',1) WHERE s.identifier_scheme='youtube:record'""")
    db.execute('CREATE TEMP TABLE directory(handle VARCHAR,channel_id VARCHAR)')
    db.executemany('INSERT INTO directory VALUES (?,?)', [(r['handle'], r['channel_id']) for r in channels])
    out |= sample('channel_id', f"SELECT d.handle AS key,d.channel_id AS expected,c.channel_id AS actual FROM directory d JOIN {table('channels')} c ON c.handle=d.handle")
    out['amendments'] = dict(checked=0, mismatched=0, note='The amendment key is every value, so its multiset comparison is the value check.')
    return out


def file_sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def run(args):
    from viewer_publication.archive_model import channel_directory_rows
    db = duckdb.connect(config=dict(memory_limit='1800MB', threads=2))
    search = [Path(p) for p in ([args.overlay] if args.overlay else [])] + [Path(args.release)]

    def table(name):
        path = next((d / (name + '.parquet') for d in search if (d / (name + '.parquet')).is_file()), None)
        if path is None:
            raise FileNotFoundError(name)
        return f"read_parquet('{path}')"

    families = compare(db, old=args.old, table=table, data=args.data, lake=args.lake, decisions=args.decisions)
    channels = channel_directory_rows()
    directory = {r['handle'] for r in channels}
    new_handles = {row[0] for row in db.execute(f"SELECT handle FROM {table('channels')}").fetchall()}
    families['channels'] = dict(old_rows=len(directory), new_rows=len(new_handles), matched=len(directory & new_handles), matched_new=len(directory & new_handles),
        old_only_by_reason={'unexplained': len(directory - new_handles)} if directory - new_handles else {},
        new_only_by_reason={'unexplained': len(new_handles - directory)} if new_handles - directory else {}, samples={})
    meetings_map = db.execute("SELECT id,event_id FROM old_meeting_event ORDER BY id").fetchall()
    if args.uuid_map:
        with Path(args.uuid_map).open('w', newline='') as out:
            csv.writer(out).writerows([('old_meeting_id', 'event_id'), *meetings_map])
    inputs = sorted(str(p) for p in [*Path(args.data).glob('*.csv'), *Path(args.lake).glob('*.parquet'), Path(args.decisions)])
    result = dict(old_release=Path(args.old).name, new_release=args.release_id, commit=args.commit,
        release_files={p.name: file_sha(p) for d in search for p in sorted(d.glob('*.parquet'))},
        input_sha256={Path(p).name: file_sha(p) for p in inputs}, reasons=REASONS, families=families,
        old_issues=issue_classes(db, args.old), value_checks=value_checks(db, old=args.old, table=table, data=args.data, decisions=args.decisions, channels=channels),
        old_meeting_uuid_to_event=dict(rows=len(meetings_map), sha256=sha256(json.dumps(meetings_map).encode()).hexdigest(), file=args.uuid_map and Path(args.uuid_map).name))
    Path(args.output).write_text(json.dumps(result, indent=1, sort_keys=True, default=str) + '\n')
    for family in ('curated_decisions', 'amendments'):
        if families[family]['old_only_by_reason'].get('unexplained'):
            raise ValueError(f'{family} has unexplained rows: stop condition; ledger written to {args.output}')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('old', 'release', 'data', 'lake', 'decisions', 'output', 'release-id', 'commit'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--overlay')
    parser.add_argument('--uuid-map')
    result = run(parser.parse_args(argv))
    for name, family in result['families'].items():
        print(name, family.get('old_rows'), family.get('new_rows'), family.get('matched'), family.get('old_only_by_reason'), family.get('new_only_by_reason'))


if __name__ == '__main__':
    sys.exit(main())
