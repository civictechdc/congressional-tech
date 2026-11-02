"""Read every affected record on both sides and compare values column by column.

    explorer_full_compare.py --tables DIR --release V21 --records meeting_records.parquet --lake DIR --data DATA --mirror R2 --output OUT.json

Raw bodies and receipt lines are walked here, without the repository's parsers, so a parser
bug cannot agree with itself. Reports records and columns read, differing values, and anything
not read. Where this script restates a rule, such as the merge order, it encodes the intended
rule: a shared misunderstanding of that rule would not show here.
"""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

EASTERN = ZoneInfo('America/New_York')
PLACEHOLDER = re.compile(r'^(?:-+|select one)$', re.I)
BUILDINGS = {'CAPITOL': 'Capitol', 'CHOB': 'Cannon House Office Building', 'DSOB': 'Dirksen Senate Office Building',
             'HSOB': 'Hart Senate Office Building', 'LHOB': 'Longworth House Office Building', 'RHOB': 'Rayburn House Office Building'}
PUBLIC = 'https://congressional-data.spicygov.ai/'
EVENT_TEXT = re.compile(r'(?:event\s*id|\bid)\s*[:=#]?\s*(1\d{5})(?!\d)|house-event/(1\d{5})(?!\d)', re.I)
SAMPLES = 15


class Check:
    """Tallies one family: every value read, every value that differs."""
    def __init__(self, name):
        self.name, self.records, self.values, self.differ, self.samples = name, 0, Counter(), Counter(), defaultdict(list)
        self.unread = []

    def compare(self, key, column, actual, expected):
        self.values[column] += 1
        if norm(actual) != norm(expected):
            self.differ[column] += 1
            if len(self.samples[column]) < SAMPLES:
                self.samples[column].append([str(key), repr(actual)[:160], repr(expected)[:160]])

    def report(self):
        return dict(records=self.records, columns_read=sorted(self.values), values_read=sum(self.values.values()),
            values_differing=dict(self.differ), samples=dict(self.samples), not_read=len(self.unread), not_read_examples=self.unread[:SAMPLES])


def norm(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, str):
        # Runs of XML whitespace and empty list separators state nothing.
        return re.sub(r'(?:,\s*)+$', '', ' '.join(value.split())) or None
    if isinstance(value, (list, tuple)):
        return [norm(item) for item in value]
    return value


def body(mirror, sha):
    for suffix in ('.gz', ''):
        path = Path(mirror) / 'bodies/sha256' / sha[:2] / (sha + suffix)
        if path.is_file():
            data = path.read_bytes()
            return gzip.decompress(data) if suffix else data
    for suffix in ('.gz', ''):
        try:
            request = Request(f'{PUBLIC}bodies/sha256/{sha[:2]}/{sha}{suffix}', headers={'User-Agent': 'congressional-tech-measure/1'})
            with urlopen(request, timeout=120) as response:
                data = response.read()
            return gzip.decompress(data) if suffix else data
        except (HTTPError, URLError, TimeoutError):
            continue
    return None


def active(element):
    # House XML marks a withdrawn element with a remove-date attribute.
    return not (element.get('remove-date') or '').strip()


def place(value):
    text = str(value).strip() if value else ''
    return None if not text or PLACEHOLDER.match(text) else text


def instant(text, *, eastern=False):
    if not text:
        return None
    value = datetime.fromisoformat(text.replace('Z', '+00:00'))
    if value.tzinfo is None:
        value = value.replace(tzinfo=EASTERN if eastern else timezone.utc)
    return value.astimezone(timezone.utc)


def find_event(value, event):
    if isinstance(value, dict):
        if str(value.get('eventId') or '') == event:
            return value
        value = list(value.values())
    if isinstance(value, list):
        for child in value:
            hit = find_event(child, event)
            if hit is not None:
                return hit
    return None


def congress_facts(meeting):
    location = meeting.get('location') if isinstance(meeting.get('location'), dict) else {}
    address = location.get('address') if isinstance(location.get('address'), dict) else {}
    parts = [str(address[k]).strip() for k in ('buildingName', 'streetAddress', 'city', 'state', 'zipCode') if address.get(k) and str(address[k]).strip()]
    first = dict(start=meeting.get('date'), end=None, room=place(location.get('room')), building=place(location.get('building')), address=', '.join(parts) or None)
    rest = [dict(first, start=str(c.get('continuationDate')).strip()) for c in meeting.get('continuations') or [] if isinstance(c, dict) and c.get('continuationDate')]
    return [first, *rest]


def house_facts(data):
    root = ET.fromstring(data)
    details = root.find('meeting-details')
    if details is None:
        return None
    text = lambda parent, name: ((parent.find(name).text or '').strip() if parent is not None and parent.find(name) is not None else '')
    date = details.find('meeting-date')
    day = text(date, 'calendar-date')
    clock = lambda name: f'{day}T{text(date, name)}' if day and text(date, name) else None
    capitol, field = details.find('meeting-location/capitol-complex'), details.find('meeting-location/field')
    building = place(text(capitol, 'building'))
    state = field.find('state') if field is not None else None
    parts = [text(field, 'street-address'), text(field, 'city'), (state.get('postal-code') or '') if state is not None else '', text(field, 'zip')]
    return dict(update=(root.get('update-date') or '').strip(), start=clock('start-time'), end=clock('end-time'), day=day, room=place(text(capitol, 'room')),
        building=BUILDINGS.get(building, building) or place(text(field, 'building-name')), address=', '.join(p for p in parts if p) or None)


def read_records(args):
    """Every pinned raw record once, by the hash it is named by."""
    rows = pq.read_table(args.records, columns=['record_sha', 'source', 'meetings']).to_pylist()
    wanted = {r['record_sha'].hex() for r in rows}
    lines = {}
    for path in sorted((Path(args.mirror) / 'receipts/congress/meetings').rglob('*')):
        if path.is_file():
            data = path.read_bytes()
            for line in (gzip.decompress(data) if path.suffix == '.gz' else data).split(b'\n'):
                digest = sha256(line).hexdigest()
                if digest in wanted:
                    lines.setdefault(digest, line)
    congress, house, unread = defaultdict(list), defaultdict(list), []
    for row in rows:
        sha = row['record_sha'].hex()
        data = lines.get(sha) or body(args.mirror, sha)
        if data is None:
            unread.append(sha)
            continue
        for meeting in row['meetings']:
            event = meeting['event_id']
            if row['source'] == 'house_xml':
                facts = house_facts(data)
                if facts:
                    house[event].append(facts)
            else:
                raw = find_event(json.loads(data), event)
                if raw:
                    congress[event].append(raw)
    return congress, house, unread, len(rows)


def check_meetings(args):
    check = Check('meetings_sittings_vs_raw')
    congress, house, unread, read = read_records(args)
    check.unread = unread
    table = pq.read_table(Path(args.tables) / 'resolved_meetings.parquet').to_pylist()
    for row in table:
        event = str(row['event_id'])
        check.records += 1
        c_list, h_list = congress.get(event, []), house.get(event, [])
        c = max(c_list, key=lambda m: str(m.get('updateDate') or '')) if c_list else None
        h = max(h_list, key=lambda f: f['update']) if h_list else None
        stated = congress_facts(c) if c else []
        expected = stated or ([dict(start=h['start'] or h['day'], end=h['end'], room=h['room'], building=h['building'], address=h['address'])] if h else [])
        actual = row['sittings'] or []
        check.compare(event, 'sitting_count', len(actual), len(expected))
        for index, (a, e) in enumerate(zip(actual, expected)):
            fill = h if index == 0 and h else {}
            check.compare(event, 'start', a['start'], instant(e['start']) if c else instant(e['start'], eastern=True))
            check.compare(event, 'end', a['end'], instant(e['end'] or fill.get('end'), eastern=True))
            for name in ('room', 'building', 'address'):
                check.compare(event, name, a[name], e[name] or fill.get(name))
            check.compare(event, 'place', a['place'], ', '.join(v for v in (a['room'], a['building'], a['address']) if v) or None)
        check.compare(event, 'congress_gov_updated', row['congress_gov_updated'], instant(c.get('updateDate')) if c else None)
        check.compare(event, 'house_xml_updated', row['house_xml_updated'], h['update'] if h else None)
        check.compare(event, 'congress_gov_meeting_type', row['congress_gov_meeting_type'], c.get('type') if c else None)
        check.compare(event, 'congress', row['congress'], int(c['congress']) if c and c.get('congress') else row['congress'] if h else None)
        check.compare(event, 'meeting_date', str(row['meeting_date']) if row['meeting_date'] else None, (h['day'] if h and h['day'] else (str(c.get('date') or '')[:10] if c else None)))
    report = check.report()
    report['raw_records_read'] = read - len(unread)
    return report


def check_released_columns(args):
    """Columns the old SQL also wrote, against v21, on every event: identity of the rewrite."""
    check = Check('meetings_vs_v21')
    old = {r['event_id']: r for r in pq.read_table(Path(args.release) / 'meetings.parquet').to_pylist()}
    for row in pq.read_table(Path(args.tables) / 'meetings.parquet').to_pylist():
        before = old.get(row['event_id'])
        if before is None:
            check.unread.append(row['event_id'])
            continue
        check.records += 1
        for column in ('chamber', 'title', 'meeting_date', 'meeting_type', 'session', 'status', 'committees', 'subject_keys', 'transcripts', 'videos'):
            check.compare(row['event_id'], column, json.dumps(row[column], default=str, sort_keys=True), json.dumps(before[column], default=str, sort_keys=True))
    return check.report()


def check_videos(args):
    videos, channels = Check('videos_vs_raw_cache'), Check('channels_vs_raw_and_csv')
    raw_videos, raw_channels = {}, {}
    for sha in sorted({r['record_sha'].hex() for r in pq.read_table(Path(args.tables) / 'videos.parquet', columns=['record_sha']).to_pylist()}):
        data = body(args.mirror, sha)
        if data is None:
            videos.unread.append(sha)
            continue
        for name, table in json.loads(data).items():
            for row in table.values():
                row.pop('upstream', None)
                if name.startswith('youtube_videos_'):
                    raw_videos.setdefault(row['videoId'], []).append(dict(row, handle=name[15:]))
                elif name == 'youtube_channels':
                    raw_channels[row['handle']] = row
    for row in pq.read_table(Path(args.tables) / 'videos.parquet').to_pylist():
        key = row['video_key']
        copies = raw_videos.get(key.removeprefix('youtube:'))
        if not copies:
            videos.unread.append(key)
            continue
        videos.records += 1
        raw = next((c for c in copies if c['handle'] == row['handle']), copies[0])
        videos.compare(key, 'handle', row['handle'], sorted(c['handle'] for c in copies)[0])
        for column, source in (('title', 'title'), ('source_description', 'description'), ('channel_id', 'channelId')):
            videos.compare(key, column, row[column], raw.get(source) or None)
        for column, source in (('published_at', 'publishedAt'), ('video_published_at', 'videoPublishedAt'), ('details_checked_at', 'details_checked_at')):
            videos.compare(key, column, row[column], instant(raw.get(source)))
        videos.compare(key, 'duration_seconds', row['duration_seconds'], int(raw['duration']) if str(raw.get('duration')).isdigit() else None)
        videos.compare(key, 'available', row['available'], raw.get('available'))
        videos.compare(key, 'has_caption', row['has_caption'], raw.get('caption') if isinstance(raw.get('caption'), bool) else {'true': True, 'false': False}.get(str(raw.get('caption')).lower()))
        videos.compare(key, 'stated_event_ids', row['stated_event_ids'], sorted({int(a or b) for a, b in EVENT_TEXT.findall(f"{raw.get('title') or ''}\n{raw.get('description') or ''}")}))
    directory = {}
    with (Path(args.repo) / 'packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv').open(newline='') as source:
        for row in csv.DictReader(source):
            ids = json.loads(row['channel_ids'] or '{}')
            for role, handles in (('primary', [row['handle']]), ('secondary', row['secondary'].split(';')), ('member', row['member_channels'].split(';'))):
                for handle in filter(None, map(str.strip, handles)):
                    directory[handle] = dict(system_code=row['systemCode'], committee_label=row['committee'], role=role, channel_id=ids.get(handle))
    for row in pq.read_table(Path(args.tables) / 'channels.parquet').to_pylist():
        expected, raw = directory.get(row['handle']), raw_channels.get(row['handle'], {})
        if expected is None:
            channels.unread.append(row['handle'])
            continue
        channels.records += 1
        for column in ('system_code', 'committee_label', 'role', 'channel_id'):
            channels.compare(row['handle'], column, row[column], expected[column])
        channels.compare(row['handle'], 'title', row['title'], raw.get('title'))
        channels.compare(row['handle'], 'custom_url', row['custom_url'], raw.get('customUrl'))
        channels.compare(row['handle'], 'uploads_scan_complete', row['uploads_scan_complete'], raw.get('uploads_scan_complete'))
        channels.compare(row['handle'], 'raw_channel_id', row['channel_id'], raw.get('channelId') or row['channel_id'])
    return videos.report(), channels.report()


def check_committee_records(args):
    """Every published row against its raw XML, then every old CSV row by its full values."""
    check = Check('committee_records_vs_raw_xml')
    rows = pq.read_table(Path(args.tables) / 'committee_records.parquet').to_pylist()
    by_sha = defaultdict(list)
    for row in rows:
        by_sha[row['record_sha'].hex()].append(row)
    for sha, published in by_sha.items():
        data = body(args.mirror, sha)
        if data is None:
            check.unread.append(sha)
            continue
        root = ET.fromstring(data)
        groups = {document: [group] for group in root.iter('meeting-document-group') for document in group.iter('meeting-document')}
        expected = []
        for document in root.iter('meeting-document'):
            code = document.get('type') or (document.findtext('type') or '').strip()
            if code not in ('CA', 'HA', 'FA', 'CV') or not active(document) or any(not active(g) for g in groups.get(document, ())):
                continue
            field = lambda name: (document.findtext('filename-metadata/' + name) or '').strip() or None
            files = [f.get('doc-url', '').replace('http://', 'https://') for f in document.findall('files/file') if f.get('doc-url') and active(f)]
            for url in files or [None]:
                expected.append(('vote' if code == 'CV' else 'amendment', (document.findtext('legis-num') or '').strip() or field('legis-num'),
                    field('vote-num' if code == 'CV' else 'amdt-num'), field('bioguideID'), field('amdt-type'), field('enbloc-num'),
                    (document.findtext('description') or '').strip() or field('description'), url))
        columns = ('kind', 'bill', 'number', 'sponsor_bioguide', 'amendment_type', 'enbloc', 'source_description', 'url')
        actual = Counter(tuple(norm(row[c]) for c in columns) for row in published)
        wanted = Counter(tuple(norm(v) for v in item) for item in expected)
        check.records += len(published)
        check.values['all_eight_columns'] += len(published)
        for key, count in (actual - wanted).items():
            check.differ['published_row_values_not_in_raw'] += count
            if len(check.samples['published_row_values_not_in_raw']) < SAMPLES:
                check.samples['published_row_values_not_in_raw'].append([sha, *map(str, key)])
        for key, count in (wanted - actual).items():
            check.differ['raw_row_values_not_published'] += count
            if len(check.samples['raw_row_values_not_published']) < SAMPLES:
                check.samples['raw_row_values_not_published'].append([sha, *map(str, key)])
    old = Check('committee_records_vs_old_csv')
    with (Path(args.data) / 'house_amendments_found.csv').open(newline='') as source:
        expected = Counter((r['event_id'], r['kind'], r['url'] or None, r['number'] or None, r['bill'] or None, r['sponsor_bioguide'] or None, r['amendment_type'] or None, r['enbloc'] or None, r['description'] or None) for r in csv.DictReader(source))
    actual = Counter((str(r['event_id']), r['kind'], r['url'], r['number'], r['bill'], r['sponsor_bioguide'], r['amendment_type'], r['enbloc'], r['source_description']) for r in rows)
    old.records = sum(expected.values())
    old.values['all_nine_columns'] = old.records
    for key, count in (expected - actual).items():
        old.differ['old_row_values_absent_natively'] += count
        old.samples['old_row_values_absent_natively'].append(list(map(str, key)))
    for key, count in (actual - expected).items():
        old.differ['native_row_values_absent_from_old'] += count
        old.samples['native_row_values_absent_from_old'].append(list(map(str, key)))
    return check.report(), old.report()


def check_decisions(args):
    """Each curated row by its full values, directly from the CSVs."""
    check = Check('recording_matches_curated_vs_csv')
    published = defaultdict(list)
    for row in pq.read_table(Path(args.tables) / 'recording_matches.parquet').to_pylist():
        if row['basis'] == 'curated':
            published[(row['subject_kind'], str(row['package_id'] or row['event_id']))].append(row)
    subjects = defaultdict(lambda: dict(verdicts=set(), refs=set(), notes=[]))
    with (Path(args.data) / 'hearing_video_overrides.csv').open(newline='') as source:
        for row in csv.DictReader(source):
            item = subjects['package', row['package_id']]
            item['verdicts'].add(row['verdict']); item['refs'].update(row['video_ids'].split()); item['notes'].append(row['note'])
            check.records += 1
    with (Path(args.data) / 'meeting_recordings_found.csv').open(newline='') as source:
        for row in csv.DictReader(source):
            item = subjects['event', row['event_id']]
            item['verdicts'].add('found'); item['refs'].add(row['recording']); item['notes'].append(row['note'])
            check.records += 1
    for (kind, subject), item in subjects.items():
        rows = published.get((kind, subject), [])
        check.compare(subject, 'row_count', len(rows), max(len(item['refs']), 1))
        check.compare(subject, 'decision', sorted({r['decision'] for r in rows}), sorted(item['verdicts']))
        check.compare(subject, 'refs', sorted(r['url'] or (r['video_key'] or '').removeprefix('youtube:') for r in rows if r['url'] or r['video_key']), sorted(item['refs']))
        check.compare(subject, 'notes_kept', all(any((r['note'] or '').startswith(n) for n in item['notes'] if n) or not any(item['notes']) for r in rows), True)
    return check.report()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('tables', 'release', 'records', 'data', 'mirror', 'repo', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    result = dict(meetings_sittings_vs_raw=check_meetings(args), meetings_vs_v21=check_released_columns(args))
    result['videos_vs_raw_cache'], result['channels_vs_raw_and_csv'] = check_videos(args)
    result['committee_records_vs_raw_xml'], result['committee_records_vs_old_csv'] = check_committee_records(args)
    result['recording_matches_curated_vs_csv'] = check_decisions(args)
    Path(args.output).write_text(json.dumps(result, indent=1, default=str) + '\n')
    for name, value in result.items():
        print(name, 'records', value['records'], 'values', value['values_read'], 'differ', value['values_differing'], 'not_read', value['not_read'])


if __name__ == '__main__':
    main()
