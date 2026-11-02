"""Check meeting_coverage per class against raw records and old inputs, not against its own rule; read
the imported ZIP set and the old witness rows with no native home.

    explorer_class_validation.py --tables DIR --release V21 --records PARQUET --appearances PARQUET --captures PARQUET --data DATA --mirror R2 --mods DIR --output OUT.json

A cross-tab shows where each state and independent evidence disagree; each disagreement cell keeps samples.
"""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

import duckdb
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).parent))
from explorer_full_compare import body, find_event  # noqa: E402


def norm(text):
    return re.sub(r'[^a-z0-9]+', ' ', (text or '').lower()).strip()


def rows(data, name):
    with (Path(data) / f'{name}.csv').open(newline='') as source:
        return list(csv.DictReader(source))


def raw_meetings(args):
    records = pq.read_table(args.records, columns=['record_sha', 'source', 'meetings']).to_pylist()
    wanted = {r['record_sha'].hex() for r in records}
    lines = {}
    for path in sorted((Path(args.mirror) / 'receipts/congress/meetings').rglob('*')):
        if path.is_file():
            data = path.read_bytes()
            for line in (gzip.decompress(data) if path.suffix == '.gz' else data).split(b'\n'):
                digest = sha256(line).hexdigest()
                if digest in wanted:
                    lines.setdefault(digest, line)
    congress, house, unread = {}, defaultdict(list), 0
    for record in records:
        sha = record['record_sha'].hex()
        data = lines.get(sha) or body(args.mirror, sha)
        if data is None:
            unread += 1
            continue
        for meeting in record['meetings']:
            event = meeting['event_id']
            if record['source'] == 'congress_gov':
                raw = find_event(json.loads(data), event)
                if raw and str(raw.get('updateDate') or '') >= str(congress.get(event, {}).get('updateDate') or ''):
                    congress[event] = raw
            else:
                house[event].append(data.decode('utf-8', 'replace'))
    return congress, house, len(records) - unread, unread


def cross(result, name, pairs):
    table, samples = Counter(), defaultdict(list)
    for event, state, evidence in pairs:
        cell = f'{state} | {evidence}'
        table[cell] += 1
        if len(samples[cell]) < 5:
            samples[cell].append(event)
    result[name] = dict(records=sum(table.values()), table=dict(table.most_common()), samples=dict(samples))


def validate_coverage(args, result):
    congress, house, read, unread = raw_meetings(args)
    result['raw_meeting_records'] = dict(read=read, unread=unread)
    state = defaultdict(dict)
    for row in pq.read_table(Path(args.tables) / 'meeting_coverage.parquet').to_pylist():
        state[row['aspect']][str(row['event_id'])] = row['state']
    sources = {r['event_id']: r for r in rows(args.data, 'hearing_text_sources')}
    complete = {r['event_id']: r for r in rows(args.data, 'meeting_completeness')}
    # Transcript: the publisher's jackets, and old GPO package ownership.
    cross(result, 'transcript', [(e, s, f"raw_jackets={'yes' if (congress.get(e) or {}).get('hearingTranscript') else 'no'},old_gpo={'none' if e not in sources else 'yes' if sources[e]['gpo_packages'] else 'no'}") for e, s in state['transcript'].items()])
    # Documents: what raw records state, and old document files.
    old_documents = Counter(r['event_id'] for name in ('house_documents_found', 'senate_documents_found') for r in rows(args.data, name))
    def stated(e):
        raw = congress.get(e) or {}
        return bool(raw.get('meetingDocuments') or raw.get('witnessDocuments')) or any('<meeting-document' in t for t in house.get(e, ()))
    cross(result, 'documents', [(e, s, f"raw={'yes' if stated(e) else 'no'},old_found={'yes' if old_documents[e] else 'no'}") for e, s in state['documents'].items()])
    # Witnesses: raw lists, and old rows.
    old_witnesses = Counter(r['event_id'] for name in ('meeting_witnesses', 'house_witnesses_found', 'senate_witnesses_found') for r in rows(args.data, name))
    cross(result, 'witnesses', [(e, s, f"raw_congress={'yes' if (congress.get(e) or {}).get('witnesses') else 'no'},old={'yes' if old_witnesses[e] else 'no'}") for e, s in state['witnesses'].items()])
    # Captions: bodies of retained tracks, the raw flag, and old text source.
    tracks = {r['video_key']: r['tracks'] or [] for r in pq.read_table(Path(args.release) / 'recordings.parquet', columns=['video_key', 'tracks']).to_pylist()}
    links = defaultdict(set)
    for row in pq.read_table(Path(args.tables) / 'recording_matches.parquet', columns=['event_id', 'package_id', 'video_key']).to_pylist():
        if row['event_id'] is not None and row['video_key']:
            links[str(row['event_id'])].add(row['video_key'])
    read_tracks, bad_tracks, seen = 0, [], set()
    has_track = defaultdict(bool)
    for event, keys in links.items():
        for key in keys:
            for track in tracks.get(key, ()):
                sha = track['body'].hex()
                if sha not in seen:
                    seen.add(sha)
                    data = body(args.mirror, sha)
                    if data is None:
                        bad_tracks.append(sha)
                    else:
                        read_tracks += 1
                        if not data[:200].lstrip(b'\xef\xbb\xbf').startswith((b'WEBVTT', b'#EXTM3U')) and b'<tt' not in data[:400]:
                            bad_tracks.append(sha)
                has_track[event] = True
    result['caption_tracks'] = dict(bodies_read=read_tracks, not_read_or_not_captions=len(bad_tracks), examples=bad_tracks[:5])
    cross(result, 'captions', [(e, s, f"track={'yes' if has_track[e] else 'no'},old={(complete.get(e) or {}).get('text_source', 'none')}") for e, s in state['captions'].items()])
    cross(result, 'recording', [(e, s, f"raw_videos={'yes' if (congress.get(e) or {}).get('videos') else 'no'},old={(complete.get(e) or {}).get('recording') or 'none'}") for e, s in state['recording'].items()])
    return congress, house


def validate_imports(args, result):
    db = duckdb.connect(config=dict(memory_limit='3GB', threads=4))
    source = f"read_parquet('{args.captures}')"
    lines = db.execute(f"""SELECT DISTINCT c.receipt_key,c.receipt_line,lower(hex(c.sha256)) FROM {source} c JOIN {source} m ON c.receipt_key=m.receipt_key AND c.receipt_line=m.receipt_line
        WHERE m.member_path IS NOT NULL AND m.mode='retained_import' AND c.member_path IS NULL""").fetchall()
    good = {r[0] for r in db.execute(f"""SELECT lower(hex(sha256)) FROM {source} WHERE member_path IS NULL AND sha256 IS NOT NULL AND mode='fetch' AND complete AND outcome IN ('stored','unchanged') AND http_status BETWEEN 200 AND 299""").fetchall()}
    tally = Counter()
    by_key = defaultdict(dict)
    for key, line, sha in lines:
        by_key[key][line] = sha
    for key, wanted in by_key.items():
        with gzip.open(Path(args.mirror) / key, 'rt') as handle:
            for number, text in enumerate(handle, 1):
                if number not in wanted:
                    continue
                record = json.loads(text)['record']
                tally['zip_lines_read'] += 1
                zipped = wanted[number]
                data = body(args.mirror, zipped)
                tally['zip_bytes_rehashed_equal'] += bool(data) and sha256(data).hexdigest() == zipped
                tally['zip_has_good_download_by_digest'] += zipped in good
                tally['line_states_200_complete'] += record.get('http_status') == 200 and record.get('complete') is True
                tally['line_processing_completed'] += (record.get('archive_processing') or {}).get('status') == 'completed'
                for member in record.get('archive_members') or []:
                    tally['members_read'] += 1
                    tally['member_status_completed'] += member.get('status') == 'completed'
                    member_data = body(args.mirror, (member.get('content') or {}).get('sha256') or '')
                    tally['member_bytes_rehashed_equal'] += bool(member_data) and sha256(member_data).hexdigest() == member['content']['sha256']
    result['imported_zips'] = dict(tally)


def validate_null_complete(args, result):
    db = duckdb.connect(config=dict(memory_limit='3GB', threads=4))
    source = f"read_parquet('{args.captures}')"
    db.execute(f"""CREATE TEMP TABLE nc AS SELECT family,url,requested_url,context_url,original_url,recovered_url,http_status,fetch_http_status,receipt_key,receipt_line,lower(hex(sha256)) AS sha,
        EXISTS (SELECT 1 FROM {source} g WHERE g.sha256=c.sha256 AND g.complete AND g.mode='fetch' AND g.outcome IN ('stored','unchanged') AND g.http_status BETWEEN 200 AND 299) AS good_elsewhere
        FROM {source} c WHERE member_path IS NULL AND complete IS NULL AND mode='fetch' AND outcome IN ('stored','unchanged') AND sha256 IS NOT NULL""")
    keys = ['rows', 'any_url_field', 'url', 'requested_url', 'context_url', 'original_url', 'recovered_url', 'http_status', 'http_2xx', 'fetch_http_status']
    query = "count(*),count(coalesce(url,requested_url,context_url,original_url,recovered_url)),count(url),count(requested_url),count(context_url),count(original_url),count(recovered_url),count(http_status),sum((http_status BETWEEN 200 AND 299)::INT),count(fetch_http_status)"
    result['null_complete'] = dict(all=dict(zip(keys, db.execute(f'SELECT {query} FROM nc').fetchone())),
        no_good_row=dict(zip(keys, db.execute(f'SELECT {query} FROM nc WHERE NOT good_elsewhere').fetchone())),
        no_good_row_with_address=db.execute('SELECT family,url,requested_url,context_url,http_status,receipt_key,receipt_line,sha FROM nc WHERE NOT good_elsewhere AND coalesce(url,requested_url,context_url,original_url,recovered_url) IS NOT NULL').fetchall())


def validate_witnesses(args, result, congress, house):
    native = pq.read_table(Path(args.release) / 'witnesses.parquet', columns=['event_id', 'package_id', 'page_url', 'name']).to_pylist()
    by_event, by_origin, events = set(), set(), set()
    for row in native:
        name = norm(row['name'])
        if row['event_id'] is not None:
            by_event.add((str(row['event_id']), name)); events.add(str(row['event_id']))
        for origin in (row['package_id'], row['page_url']):
            if origin:
                by_origin.add((origin, name))
    old = {}
    for file, source_of, origin_of in (('meeting_witnesses', lambda r: r['source'], lambda r: r['from']), ('house_witnesses_found', lambda r: 'docs.house.gov', lambda r: None), ('senate_witnesses_found', lambda r: 'senate committee page', lambda r: r['page'])):
        for row in rows(args.data, file):
            old.setdefault((row['event_id'], norm(row['name'])), dict(row, source=source_of(row), origins=set()))['origins'].add(origin_of(row))
    table, samples = Counter(), defaultdict(list)
    appearances = pq.read_table(args.appearances, columns=['event_id', 'source', 'collection_state']).to_pylist()
    house_state = {str(r['event_id']): r['collection_state'] for r in appearances if r['source'] == 'house_xml' and r['event_id'] is not None}
    for (event, name), row in old.items():
        if (event, name) in by_event or any((o, name) in by_origin for o in row['origins'] if o):
            continue
        family = name.split()[-1] if name else ''
        raw = congress.get(event) or {}
        stated_congress = family and family in norm(json.dumps(raw.get('witnesses') or []))
        stated_house = family and any(family in norm(text) for text in house.get(event, ()))
        title = family and family in norm(raw.get('title'))
        kind = ('name_in_raw_congress_witnesses' if stated_congress else 'name_in_raw_house_record' if stated_house else 'name_in_raw_meeting_title' if title else 'not_in_held_meeting_records')
        cell = f"{'event_has_other_witnesses' if event in events else 'no_native_witness_on_event'} | {row['source']} | {kind}"
        table[cell] += 1
        if len(samples[cell]) < 3:
            samples[cell].append([event, row['name'], sorted(str(o) for o in row['origins'])[:1], house_state.get(event)])
    result['old_witness_rows_without_home'] = dict(rows=sum(table.values()), table=dict(table.most_common()), samples=dict(samples))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('tables', 'release', 'records', 'appearances', 'captures', 'data', 'mirror', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    result = {}
    validate_null_complete(args, result)
    validate_imports(args, result)
    congress, house = validate_coverage(args, result)
    validate_witnesses(args, result, congress, house)
    Path(args.output).write_text(json.dumps(result, indent=1, default=str) + '\n')
    for name, value in result.items():
        print(name, json.dumps({k: v for k, v in value.items() if k != 'samples'}, default=str)[:1500] if isinstance(value, dict) else value)


if __name__ == '__main__':
    main()
