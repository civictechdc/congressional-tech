"""Read raw records for each open Explorer comparison finding, over the whole affected set.

    raw_findings_audit.py --mirror R2 --release V21 --tables TABLES --data DATA --inputs INPUTS --output OUT.json

Derived tables only name which raw records to read. Reports read/affected per finding and
lists anything it could not read, so nothing unreachable is inferred.
"""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
from hashlib import sha256
import html
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import duckdb

EVENT_ID = re.compile(r"(?:event\s*id|\bid)\s*[:=#]?\s*(1\d{5})(?!\d)|house-event/(1\d{5})(?!\d)", re.I)
ORIGIN = 'https://congressional-data.spicygov.ai/'
PURE = ('date in video', 'date window')


def rows(data, name):
    with (Path(data) / f'{name}.csv').open(newline='') as source:
        return list(csv.DictReader(source))


class Raw:
    def __init__(self, mirror):
        self.mirror, self.public, self.missing = Path(mirror), 0, set()

    def body(self, sha):
        if not sha:
            return None
        for suffix in ('.gz', '', '.pdf'):
            path = self.mirror / 'bodies/sha256' / sha[:2] / (sha + suffix)
            if path.is_file():
                data = path.read_bytes()
                return gzip.decompress(data) if suffix == '.gz' else data
        for suffix in ('.gz', ''):
            try:
                request = Request(f'{ORIGIN}bodies/sha256/{sha[:2]}/{sha}{suffix}', headers={'User-Agent': 'congressional-tech-measure/1'})
                with urlopen(request, timeout=60) as response:
                    data = response.read()
                self.public += 1
                return gzip.decompress(data) if suffix == '.gz' else data
            except (HTTPError, URLError, TimeoutError):
                continue
        self.missing.add(sha)
        return None


def norm(text):
    return re.sub(r'[^a-z0-9]+', ' ', html.unescape(text or '').lower()).strip()


def latest_caches(db, inputs):
    return db.execute(f"""SELECT regexp_extract(url,'youtube/youtube_[0-9]+',0) p,arg_max(hex(sha256),retrieved_at) s FROM read_parquet('{inputs}/captures.parquet')
        WHERE family='pipeline-data' AND regexp_matches(url,'/youtube/youtube_[0-9]+[.]json$') GROUP BY 1""").fetchall()


def raw_videos(raw, db, inputs):
    videos = {}
    caches = latest_caches(db, inputs)
    for _, sha in caches:
        data = raw.body(sha.lower())
        if data is None:
            continue
        for name, table in json.loads(data).items():
            if name.startswith('youtube_videos_'):
                for row in table.values():
                    row.pop('upstream', None)
                    videos.setdefault(row['videoId'], dict(row, handle=name[15:]))
    return videos, len(caches)


def raw_meetings(raw, db, inputs, events):
    """Every raw record naming a wanted event: Congress.gov JSON and House XML."""
    found = defaultdict(list)
    wanted = {str(e) for e in events}
    named = db.execute(f"""SELECT hex(record_sha),source,m.event_id FROM (SELECT record_sha,source,unnest(meetings) m FROM read_parquet('{inputs}/meeting_records.parquet'))""").fetchall()
    shas = defaultdict(set)
    for sha, source, event in named:
        if event in wanted:
            shas[sha.lower()].add((source, event))
    lines = {}
    for path in sorted((raw.mirror / 'receipts/congress/meetings').rglob('*')):
        if path.is_file():
            data = path.read_bytes()
            data = gzip.decompress(data) if path.suffix == '.gz' else data
            for line in data.split(b'\n'):
                digest = sha256(line).hexdigest()
                if digest in shas:
                    lines.setdefault(digest, line)
    unread = []
    for sha, owners in shas.items():
        data = lines.get(sha) or raw.body(sha)
        if data is None:
            unread.append(sha)
            continue
        text = data.decode('utf-8', 'replace')
        for source, event in owners:
            found[event].append((source, text))
    return found, len(shas), unread


def audit_absent(args, db, raw, videos):
    db.execute(f"""CREATE TEMP TABLE absent AS SELECT n.event_id FROM read_parquet('{args.tables}/meeting_coverage.parquet') n
        JOIN read_csv('{args.data}/meeting_completeness.csv',all_varchar=true,header=true) o ON o.event_id=cast(n.event_id AS VARCHAR)
        WHERE n.aspect='recording' AND n.state='confirmed_absent' AND o.recording='yes'""")
    events = [str(r[0]) for r in db.execute('SELECT event_id FROM absent').fetchall()]
    transcripts = defaultdict(list)
    for event, package in db.execute(f"SELECT cast(event_id AS VARCHAR),unnest(transcripts).package_id FROM read_parquet('{args.release}/meetings.parquet') WHERE event_id IN (SELECT event_id FROM absent)").fetchall():
        transcripts[event].append(package)
    verdict = {r['package_id']: r for r in rows(args.data, 'hearing_video_overrides')}
    matcher = {r['package_id']: r for r in rows(args.data, 'gpo_hearing_videos')}
    sources = {r['event_id']: r for r in rows(args.data, 'hearing_text_sources')}
    records, read, unread = raw_meetings(raw, db, args.inputs, events)
    result, classes = [], Counter()
    for event in events:
        packages = transcripts[event]
        contested = [p for p in packages if p in verdict and verdict[p]['verdict'] == 'no_video_found' and matcher.get(p, {}).get('status') == 'full_recording']
        ids = {v for p in packages for v in (matcher.get(p, {}).get('video_ids') or '').split()} | set((sources.get(event, {}).get('youtube_ids') or '').split())
        present = [v for v in ids if v in videos]
        raw_has_video = [v for v in ids if any(v in text for _, text in records.get(event, ()))]
        stated = [v for v in present if str(event) in {a or b for a, b in EVENT_ID.findall((videos[v].get('title') or '') + ' ' + (videos[v].get('description') or ''))}]
        kind = ('publisher_states_video' if raw_has_video else 'video_states_event' if stated else
            'matcher_overrode_research_verdict' if contested else 'other_package_or_source_says_yes')
        classes[kind] += 1
        result.append(dict(event_id=event, packages=packages, class_=kind, videos=sorted(ids), raw_cached=len(present),
            raw_records=len(records.get(event, ())), notes=[verdict[p]['note'][:160] for p in packages if p in verdict and verdict[p]['note']][:2],
            titles=[(videos[v].get('title') or '')[:100] for v in present][:2]))
    return dict(affected=len(events), raw_meeting_records_read=read, raw_meeting_records_unread=unread, events_with_a_raw_record=sum(1 for e in events if records.get(e)),
        videos_named=sum(len(r['videos']) for r in result), videos_read_in_raw_cache=sum(r['raw_cached'] for r in result), classes=classes, rows=result)


def audit_pairs(args, db, raw, videos):
    new = {(p, v) for p, v in db.execute(f"""SELECT package_id,video_key FROM read_parquet('{args.tables}/recording_matches.parquet') WHERE package_id IS NOT NULL AND video_key IS NOT NULL
        UNION SELECT t.package_id,m.video_key FROM read_parquet('{args.tables}/recording_matches.parquet') m JOIN (SELECT event_id,unnest(transcripts).package_id package_id FROM read_parquet('{args.release}/meetings.parquet')) t ON m.event_id=t.event_id WHERE m.video_key IS NOT NULL""").fetchall()}
    hearings = {r['package_id']: r for r in rows(args.data, 'gpo_hearings')}
    linked = {p for p, in db.execute(f"SELECT DISTINCT unnest(transcripts).package_id FROM read_parquet('{args.release}/meetings.parquet')").fetchall()}
    pairs = []
    for row in rows(args.data, 'gpo_hearing_videos'):
        for video in (row['video_ids'] or '').split():
            if re.fullmatch(r'[A-Za-z0-9_-]+', video) and (row['package_id'], 'youtube:' + video) not in new:
                pairs.append((row['package_id'], video, row['method'] or ''))
    pairs = list(dict.fromkeys(pairs))
    pure = [p for p in pairs if all(part.strip().startswith(PURE) for part in p[2].split(';')) and p[2]]
    extra = [p for p in pairs if p not in set(pure)]
    events = {hearings[p]['event_id'] for p, _, _ in extra if p in hearings and hearings[p].get('event_id')}
    records, read, unread = raw_meetings(raw, db, args.inputs, events)
    classes, examples = Counter(), defaultdict(list)
    cached = 0
    for package, video, method in extra:
        event = (hearings.get(package) or {}).get('event_id') or ''
        row = videos.get(video)
        cached += row is not None
        ids = {a or b for a, b in EVENT_ID.findall(((row or {}).get('title') or '') + ' ' + ((row or {}).get('description') or ''))}
        publisher = any(video in text for _, text in records.get(event, ()))
        if row is None:
            kind = 'video_not_in_raw_cache'
        elif not event:
            kind = 'no_gpo_event_id_so_stated_link_cannot_reach_package'
        elif package not in linked:
            kind = ('raw_evidence_for_event_but_package_not_linked_to_meeting' if publisher or event in ids else 'package_not_linked_and_raw_lacks_claim')
        elif publisher or event in ids:
            kind = 'raw_evidence_but_native_pair_missing'
        else:
            kind = 'method_named_link_but_event_differs_in_raw'
        classes[kind] += 1
        if len(examples[kind]) < 8:
            examples[kind].append([package, video, event, method])
    return dict(unmatched_pairs=len(pairs), date_title_only=len(pure), with_stronger_method=len(extra), videos_read_in_raw_cache=cached, raw_meeting_records_read=read,
        raw_meeting_records_unread=unread, events_named=len(events), classes=classes, examples=examples)


def audit_witnesses(args, db, raw):
    witness_events = {str(r[0]) for r in db.execute(f"SELECT DISTINCT event_id FROM read_parquet('{args.release}/witnesses.parquet') WHERE event_id IS NOT NULL").fetchall()}
    affected = [dict(row, file=name) for name in ('meeting_witnesses', 'house_witnesses_found') for row in rows(args.data, name) if row['event_id'] not in witness_events]
    url_body = dict(db.execute(f"""SELECT u,arg_max(s,t) FROM (SELECT coalesce(url,requested_url) u,lower(hex(sha256)) s,retrieved_at t FROM read_parquet('{args.inputs}/captures.parquet') WHERE sha256 IS NOT NULL AND mode='fetch') GROUP BY 1""").fetchall())
    meeting_pages = defaultdict(set)
    for row in rows(args.data, 'senate_hearing_pages_found'):
        meeting_pages[row['event_id']].add(row['page'])
    gpo_by_event = defaultdict(set)
    for row in rows(args.data, 'gpo_hearings'):
        if row.get('event_id'):
            gpo_by_event[row['event_id']].add(row['package_id'])
    cache, classes, examples, read, unreachable = {}, Counter(), defaultdict(list), 0, Counter()

    def text_of(url):
        sha = url_body.get(url) or url_body.get((url or '').replace('https://', 'http://')) or url_body.get((url or '').replace('http://', 'https://'))
        if sha is None:
            return None
        if sha not in cache:
            data = raw.body(sha)
            cache[sha] = norm(data.decode('utf-8', 'replace')) if data else None
        return cache[sha]

    for row in affected:
        source = row.get('source') or ('docs.house.gov' if row['file'] == 'house_witnesses_found' else '')
        name = norm(row['name'])
        family = name.split()[-1] if name else ''
        urls = [row['from']] if row.get('from') else []
        if not urls:
            urls = sorted(meeting_pages.get(row['event_id'], ())) or [f"https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID={row['event_id']}"]
        texts = [t for t in map(text_of, urls) if t is not None]
        if not texts:
            unreachable[source] += 1
            kind = 'raw_page_not_held'
        else:
            read += 1
            kind = 'name_in_raw_page' if any(family and family in text for text in texts) else 'name_not_in_raw_page'
        key = f'{source}: {kind}'
        classes[key] += 1
        if len(examples[key]) < 5:
            examples[key].append([row['event_id'], row['name'], urls[0][:120]])
    return dict(affected=len(affected), rows_with_raw_page_read=read, distinct_bodies_read=sum(1 for v in cache.values() if v is not None),
        unreachable_by_source=unreachable, classes=classes, examples=examples)


def audit_amendment(args, db, raw):
    event = '115405'
    shas = [r[0].lower() for r in db.execute(f"SELECT hex(record_sha) FROM read_parquet('{args.lake}/committee_records.parquet') WHERE event_id=?", [event]).fetchall()]
    result = []
    for sha in shas:
        data = raw.body(sha)
        if data is None:
            result.append(dict(sha=sha, read=False))
            continue
        result.append(dict(sha=sha, read=True, utf8_fernandez=b'Fern\xc3\xa1ndez' in data, double_encoded=b'Fern\xc3\x83\xc2\xa1ndez' in data))
    return dict(affected=1, records=result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('mirror', 'release', 'tables', 'data', 'inputs', 'lake', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    db = duckdb.connect(config=dict(memory_limit='2GB', threads=2))
    raw = Raw(args.mirror)
    videos, caches = raw_videos(raw, db, args.inputs)
    result = dict(raw_cache_files_read=caches, raw_videos=len(videos), amendment=audit_amendment(args, db, raw), confirmed_absent=audit_absent(args, db, raw, videos),
        recording_pairs=audit_pairs(args, db, raw, videos), witnesses=audit_witnesses(args, db, raw))
    result['bodies_from_public_origin'] = raw.public
    result['bodies_unreachable'] = sorted(raw.missing)
    Path(args.output).write_text(json.dumps(result, indent=1, default=str) + '\n')
    view = json.loads(json.dumps(result, default=str))
    view['confirmed_absent'].pop('rows')
    view['bodies_unreachable'] = len(view['bodies_unreachable'])
    print(json.dumps(view, indent=0)[:6000])


if __name__ == '__main__':
    main()
