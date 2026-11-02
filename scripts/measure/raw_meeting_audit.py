"""Read the raw publisher record behind every changed sitting and report what it states.

    raw_meeting_audit.py --mirror R2_IMMUTABLE --records meeting_records.parquet --resolved resolved_meetings.parquet --pins PINS.json --output OUT.json

Raw means the stored body or the receipt line, re-hashed against record_sha; the lake row is
only the index that names them. A record that cannot be read is listed, never inferred.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

EASTERN = ZoneInfo('America/New_York')
PLACEHOLDER = re.compile(r'^(?:-+|select one)$', re.I)


def body(mirror, sha):
    for suffix in ('.gz', '', '.pdf'):
        path = Path(mirror) / 'bodies/sha256' / sha[:2] / (sha + suffix)
        if path.is_file():
            data = path.read_bytes()
            return gzip.decompress(data) if suffix == '.gz' else data
    return None


def inline_lines(mirror, wanted):
    """Receipt lines by the hash the producer gave them, reading each meeting receipt once."""
    found = {}
    for path in sorted((Path(mirror) / 'receipts/congress/meetings').rglob('*')):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if path.suffix == '.gz':
            data = gzip.decompress(data)
        for line in data.split(b'\n'):
            digest = sha256(line).hexdigest()
            if digest in wanted:
                found.setdefault(digest, line)
    return found


def unwrap(value, event):
    """The one meeting in a record, whichever envelope the publisher or receipt used."""
    if isinstance(value, dict):
        if str(value.get('eventId') or '') == event:
            return value
        for child in value.values():
            hit = unwrap(child, event)
            if hit is not None:
                return hit
    elif isinstance(value, list):
        for child in value:
            hit = unwrap(child, event)
            if hit is not None:
                return hit
    return None


def instant(text):
    if not text:
        return None
    return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(timezone.utc)


def house_facts(data):
    root = ET.fromstring(data)
    details = root.find('meeting-details')
    date = details.find('meeting-date') if details is not None else None
    text = lambda parent, name: ((parent.find(name).text or '').strip() if parent is not None and parent.find(name) is not None else '')
    day, start = text(date, 'calendar-date'), text(date, 'start-time')
    place = details.find('meeting-location/capitol-complex') if details is not None else None
    field = details.find('meeting-location/field') if details is not None else None
    return dict(day=day, start=start, end=text(date, 'end-time'), update=(root.get('update-date') or '').strip(), room=text(place, 'room'), building=text(place, 'building'),
        field_building=text(field, 'building-name'), field_street=text(field, 'street-address'), field_city=text(field, 'city'),
        has_old_location_tag=details is not None and details.find('capitol-complex-location') is not None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('mirror', 'records', 'resolved', 'pins', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    pins = json.loads(Path(args.pins).read_text())
    by_event = defaultdict(lambda: defaultdict(list))
    for row in pq.read_table(args.records, columns=['record_sha', 'source', 'parser_version', 'meetings']).to_pylist():
        if row['parser_version'] != pins.get(row['source']):
            continue
        for meeting in row['meetings']:
            by_event[meeting['event_id']][row['source']].append((row['record_sha'].hex(), meeting))
    published = {str(r['event_id']): r for r in pq.read_table(args.resolved, columns=['event_id', 'sittings', 'house_xml_updated']).to_pylist()}
    affected = sorted(e for e, sources in by_event.items() if 'house_xml' in sources)
    if not affected:
        raise SystemExit('No records at these pins: an empty audit proves nothing')
    congress_shas = {sha for e in affected for sha, _ in by_event[e].get('congress_gov', ())}
    lines = inline_lines(args.mirror, congress_shas)
    tally = defaultdict(int)
    unread = dict(congress=[], house=[])
    offsets = defaultdict(int)
    examples = defaultdict(list)

    def note(kind, event, detail=None):
        tally[kind] += 1
        if len(examples[kind]) < 10:
            examples[kind].append([event, detail])

    for event in affected:
        row = published.get(event)
        if row is None:
            note('event_not_published', event)
            continue
        sitting = (row['sittings'] or [None])[0]
        # The current record by the rule, from what each raw record itself states.
        candidates = []
        for sha, _ in by_event[event].get('congress_gov', ()):
            data = lines.get(sha) or body(args.mirror, sha)
            if data is None:
                unread['congress'].append(sha)
                continue
            tally['congress_raw_records_read'] += 1
            meeting = unwrap(json.loads(data), event)
            if meeting is None:
                note('congress_record_lacks_event', event, sha)
                continue
            candidates.append((str(meeting.get('updateDate') or ''), meeting))
        house = []
        for sha, _ in by_event[event]['house_xml']:
            data = body(args.mirror, sha)
            if data is None:
                unread['house'].append(sha)
                continue
            tally['house_raw_records_read'] += 1
            house.append(house_facts(data))
        if not candidates:
            note('event_without_readable_congress_record', event)
            continue
        tally['events_with_raw_congress'] += 1
        current = max(candidates, key=lambda item: item[0])[1]
        stated = instant(current.get('date'))
        if sitting is None or sitting['start'] is None:
            note('published_no_sitting', event, current.get('date'))
        elif stated != sitting['start'].astimezone(timezone.utc):
            # An older copy can state the published value when two copies tie on update date.
            if any(instant(m.get('date')) == sitting['start'].astimezone(timezone.utc) for _, m in candidates):
                note('start_matches_an_older_copy', event, [current.get('date'), str(sitting['start'])])
            else:
                note('start_differs_from_every_raw_record', event, [current.get('date'), str(sitting['start'])])
        else:
            tally['start_equals_raw_congress'] += 1
        location = current.get('location') if isinstance(current.get('location'), dict) else {}
        latest = max(house, key=lambda facts: facts['update']) if house else {}
        for name, stated_by_house in (('room', latest.get('room')), ('building', latest.get('building') or latest.get('field_building'))):
            published_value = (sitting or {}).get(name)
            congress_value = PLACEHOLDER.sub('', str(location.get(name) or '').strip()) or None
            house_value = PLACEHOLDER.sub('', stated_by_house or '') or None
            if congress_value is not None:
                tally[f'{name}_equals_raw_congress' if published_value == congress_value else f'{name}_differs_from_raw_congress'] += 1
            elif house_value is not None:
                tally[f'{name}_filled_from_raw_house' if published_value else f'{name}_lost_though_raw_house_states_it'] += 1
                if not published_value:
                    note(f'{name}_lost', event, house_value)
            else:
                tally[f'{name}_stated_by_neither' if not published_value else f'{name}_published_without_raw_source'] += 1
        if latest.get('end'):
            expected = datetime.fromisoformat(f"{latest['day']}T{latest['end']}").replace(tzinfo=EASTERN).astimezone(timezone.utc)
            if sitting and sitting['end'] and sitting['end'].astimezone(timezone.utc) == expected:
                tally['end_equals_raw_house'] += 1
            else:
                note('end_lost_or_differs', event, [latest['end'], str((sitting or {}).get('end'))])
        if latest.get('field_street') or latest.get('field_city'):
            address = (sitting or {}).get('address') or ''
            if all(part in address for part in (latest.get('field_street'), latest.get('field_city')) if part):
                tally['field_address_in_published_place'] += 1
            else:
                note('field_address_lost', event, [latest.get('field_street'), latest.get('field_city'), address])
        for facts in house:
            if facts['has_old_location_tag']:
                tally['house_has_capitol_complex_location_tag'] += 1
            if facts['room'] or facts['building']:
                tally['house_states_meeting_location_capitol_complex'] += 1
            if facts['day'] and facts['start'] and stated is not None:
                local = datetime.fromisoformat(f"{facts['day']}T{facts['start']}")
                if local.tzinfo is None:
                    tally['house_literal_unzoned'] += 1
                    if local.replace(tzinfo=EASTERN).astimezone(timezone.utc) == stated:
                        tally['house_eastern_equals_congress'] += 1
                    else:
                        note('house_eastern_differs_from_congress', event, [f"{facts['day']}T{facts['start']}", current.get('date')])
                    offsets[round((stated - local.replace(tzinfo=timezone.utc)).total_seconds() / 3600, 2)] += 1
                else:
                    tally['house_literal_zoned'] += 1
        if not house:
            continue
        if row['house_xml_updated'] not in {facts['update'] for facts in house}:
            note('house_update_not_in_raw', event, row['house_xml_updated'])
    result = dict(affected_events=len(affected), congress_records_named=len(congress_shas), inline_lines_found=len(lines), tally=dict(sorted(tally.items())),
        examples=examples, house_minus_congress_hours={str(k): v for k, v in sorted(offsets.items())}, unreadable={k: sorted(set(v)) for k, v in unread.items()})
    Path(args.output).write_text(json.dumps(result, indent=1, default=str) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('examples', 'unreadable')}, indent=0, default=str))
    print('unreadable', {k: len(set(v)) for k, v in unread.items()})


if __name__ == '__main__':
    main()
