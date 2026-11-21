"""Recording evidence from the native export, raw HTML, and the publisher's meeting calendar."""
from collections import defaultdict
from datetime import datetime
from functools import cache
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from lxml import html
import pyarrow.parquet as pq

from congress_api.parsers.committee_pages import event_identity, event_title
from congress_api.retention.body_keys import physical_body_object_key
from congress_shared.custody import verify_local_file

EXPORT = 'recording_video_links.parquet'
REGISTRY = Path(__file__).resolve().parents[4] / 'model/registries/recording-sources.json'


def verified_export(result, scratch):
    """Bind the fixed evidence path to exactly one native output, including on resume."""
    pins = [p for p in result['outputs'] if p['name'] == EXPORT]
    if len(pins) != 1:
        raise ValueError(f'Expected one native export of {EXPORT}')
    pin = pins[0]
    if not isinstance(pin.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', pin['sha256']) or type(pin.get('size')) != int:
        raise ValueError(f'Invalid native export pin for {EXPORT}')
    return verify_local_file(Path(scratch) / 'evidence' / EXPORT, pin['sha256'], pin['size'])


@cache
def _video_rules():
    return [(re.compile(r['pattern']), r['key_template']) for r in json.loads(REGISTRY.read_bytes()) if r['kind'] == 'video_url']


def captured_body(capture, read_object):
    digest = capture['sha256']
    raw = read_object(physical_body_object_key(digest, stored_suffix=capture.get('stored_suffix', '.gz')))
    body = gzip.decompress(raw) if raw.startswith(b'\x1f\x8b') else raw
    if sha256(body).hexdigest() != digest:
        raise ValueError(f'Captured bytes differ from receipt digest {digest}')
    return body


def meeting_calendar(path):
    """Index all meetings, so an ambiguous committee/date cannot prove either event."""
    by_day = defaultdict(dict)
    cols = ['event_id', 'committees', 'meeting_date', 'title', 'sittings']
    if path and path.is_file() and set(cols) <= set(pq.read_schema(path).names):
        for row in pq.read_table(path, columns=cols).to_pylist():
            for committee in row['committees'] or ():
                by_day[committee['system_code'][:4], str(row['meeting_date'])][row['event_id']] = row
    return by_day


def _calendar_event(tree, body, url, calendar):
    if not calendar:
        return set()
    from viewer_publication.corpus_quality.provenance_validator import CONGRESSIONAL_HOST_TO_SYSTEM_CODE
    code = CONGRESSIONAL_HOST_TO_SYSTEM_CODE.get((urlsplit(url).hostname or '').removeprefix('www.'))
    if not code:
        return set()
    identity = event_identity(body, url)
    require_title = False
    if not identity:
        # Some committee templates label the markup date or place it in the event's date bar.
        dates = tree.xpath('//main//span[@class="date-bar"] | //article//span[@class="date-bar"] | '
                           '//span[@class="date" and starts-with(normalize-space(.),"Markup Date:")]')
        if len(dates) != 1:
            return set()
        match = re.search(r'\b[A-Za-z]+ \d{1,2}, \d{4}\b', dates[0].text_content())
        if not match:
            return set()
        try:
            day = datetime.strptime(match[0], '%B %d, %Y').date()
        except ValueError:
            return set()
        require_title = dates[0].get('class') == 'date-bar'
        identity = dict(title=event_title(tree) or tree.xpath('string(//title)'), date=str(day))
    events = calendar.get((code[:4], identity['date']), {})
    if len(events) == 1 and not require_title:
        return set(events)

    def words(value):
        return ' '.join(re.findall(r'\w+', (value or '').casefold()))

    heading = words(identity['title'])
    def title_matches(title):
        subject = words((title or '').split(':', 1)[0])
        return bool(subject and (words(title) in heading or
                                 (len(subject.split()) >= 3 and heading.startswith(subject + ' '))))
    titled = {ev for ev, row in events.items() if title_matches(row['title'])}
    # Page and calendar can show different scheduled start times. A single exact title
    # identifies the proceeding on that committee's day even after a time change.
    if len(titled) == 1 or require_title:
        return titled if len(titled) == 1 else set()
    fields = tree.xpath('//*[contains(@class,"hearing__time") or starts-with(@class,"time ")] | '
                        '//span[@class="date" and starts-with(normalize-space(.),"Markup Date:")]')
    times = {datetime.strptime(t, '%I:%M %p').time() for node in fields
             for t in re.findall(r'\b(?:0?[1-9]|1[0-2]):[0-5]\d [AP]M\b', node.text_content().upper())}
    timed = {ev for ev, row in events.items() if any(s['start'] and
             s['start'].astimezone(ZoneInfo('America/New_York')).time() in times for s in row['sittings'] or ())}
    return timed if len(timed) == 1 else set()


def page_links(body, url, calendar):
    tree = html.fromstring(body, parser=html.HTMLParser(no_network=True))
    targets = {urljoin(url, ref) for ref in tree.xpath('//@href | //@src | //object/@data')}
    videos = {key.replace('$1', match[1]) for target in targets for pattern, key in _video_rules()
              if (match := pattern.search(target))}
    # A third-party page can link the video and House calendar without speaking for the committee.
    host = (urlsplit(url).hostname or '').removeprefix('www.')
    if host not in ('csce.gov', 'house.gov', 'senate.gov') and not host.endswith(('.house.gov', '.senate.gov')):
        return videos, []
    events = set()
    for target in targets:
        address = urlsplit(target)
        if address.hostname == 'docs.house.gov':
            match = re.search(r'/meetings/[^/]+/[^/]+/\d{8}/(\d+)(?:/|$)', address.path, re.I)
            if match:
                events.add(int(match[1]))
            elif address.path.lower() == '/committee/calendar/byevent.aspx':
                events.update(int(v) for v in parse_qs(address.query).get('EventID', []) if re.fullmatch(r'[0-9]{1,10}', v))
    # The displayed proceeding can link background documents from other meetings.
    # Its committee calendar identifies the proceeding independently of those links.
    proceeding = _calendar_event(tree, body, url, calendar)
    return videos, sorted(proceeding or (events if len(events) == 1 else set()))
