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
from congress_api.parsers.main_content import _is_cms_chrome
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


def _calendar_event(tree, url, calendar):
    if not calendar:
        return set()
    from viewer_publication.corpus_quality.provenance_validator import CONGRESSIONAL_HOST_TO_SYSTEM_CODE
    code = CONGRESSIONAL_HOST_TO_SYSTEM_CODE.get((urlsplit(url).hostname or '').removeprefix('www.'))
    if not code:
        return set()
    identity = event_identity(html.tostring(tree), url)
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


def video_keys(targets):
    return {key.replace('$1', match[1]) for target in targets for pattern, key in _video_rules()
            if (match := pattern.search(target))}


def publisher_video_keys(body, event):
    """Read only the video URLs listed on the publisher record for this event."""
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return set()
    meeting = payload.get('committeeMeeting') if isinstance(payload, dict) else None
    if not isinstance(meeting, dict) or str(meeting.get('eventId')) != str(event):
        return set()
    videos = meeting.get('videos')
    if not isinstance(videos, list):
        return set()
    return video_keys(v['url'] for v in videos if isinstance(v, dict) and isinstance(v.get('url'), str))


def _document(body):
    return html.document_fromstring(body, parser=html.HTMLParser(no_network=True), ensure_head_body=True)


_URL_ATTRIBUTES = './/@href | .//@src | .//object/@data'
_CHROME_ROLES = {'navigation', 'complementary', 'banner', 'contentinfo', 'menu', 'menubar', 'menuitem',
                 'toolbar', 'tablist', 'dialog', 'alertdialog', 'search', 'status'}
_CHROME_TOKEN = re.compile(r'(?:^|[\s_-])(?:sidebar|nav|related|recent|more-hearings|menu|breadcrumb|pager|pagination)(?:$|[\s_-])', re.I)
_ITEM_TOKEN = re.compile(r'(?:^|[\s_-])(?:card|item)(?:$|\s)|(?:^|\s)(?:hearing|event|meeting)(?:$|\s)', re.I)


def _targets(node, url):
    return {urljoin(url, ref) for ref in node.xpath(_URL_ATTRIBUTES)}


def _event_ids(targets):
    events = set()
    for target in targets:
        address = urlsplit(target)
        if address.hostname == 'docs.house.gov':
            match = re.search(r'/meetings/[^/]+/[^/]+/\d{8}/(\d+)(?:/|$)', address.path, re.I)
            if match:
                events.add(int(match[1]))
            elif address.path.lower() == '/committee/calendar/byevent.aspx':
                events.update(int(v) for k, values in parse_qs(address.query).items() if k.lower() == 'eventid'
                              for v in values if re.fullmatch(r'[0-9]{1,10}', v))
        elif address.hostname in ('congress.gov', 'www.congress.gov'):
            match = re.fullmatch(r'/event/[0-9]+(?:st|nd|rd|th)?(?:-congress)?/(?:house|senate)-event/([0-9]{1,10})/?',
                                 address.path, re.I)
            if match:
                events.add(int(match[1]))
    return events


def _item_scopes(root, url):
    """Articles own their links. Repeated list items and cards can also hold separate proceedings."""
    scopes = set(root.xpath('.//article | .//*[@role="article"]'))
    siblings = defaultdict(list)
    for node in root.xpath('.//li | .//*[@role="listitem"] | .//div[@class] | .//section[@class]'):
        if node.tag == 'li' or node.get('role') == 'listitem' or _ITEM_TOKEN.search(node.get('class', '')):
            siblings[node.getparent()].append(node)
    for items in siblings.values():
        if len(items) > 1 and any(video_keys(_targets(item, url)) for item in items):
            scopes.update(items)
    return scopes


def _proceeding_body(tree):
    body = tree.body
    for node in body.xpath('.//aside | .//nav | .//footer | .//header | .//template | .//menu | .//dialog | .//*[@role or @class or @id]'):
        if (_is_cms_chrome(node) or node.tag in ('aside', 'footer', 'template', 'menu', 'dialog')
                or (node.tag == 'header' and not node.xpath('ancestor::article'))
                or _CHROME_ROLES.intersection(node.get('role', '').lower().split())
                or _CHROME_TOKEN.search(f"{node.get('class', '')} {node.get('id', '')}")):
            node.drop_tree()
    # Keep head metadata for the committee calendar. Some legacy templates mark only the article.
    mains = body.xpath('.//main | .//*[@role="main"]')
    outer = [node for node in mains if not any(parent in mains for parent in node.iterancestors())]
    if len(outer) > 1:
        return None
    if not outer:
        outer = body.xpath('.//article | .//*[@role="article"]')
    if len(outer) == 1:
        # A legacy article can have an explicit event link in a sibling section.
        roots = outer if mains else outer[0].xpath('. | ../section')
        body.clear()
        body.extend(roots)
    return body


def _proceeding_links(tree, url, calendar):
    body = _proceeding_body(tree)
    if body is None:
        return {}
    items = _item_scopes(body, url)
    targets = {scope: set() for scope in (body, *items)}
    for ref in body.xpath(_URL_ATTRIBUTES):
        owner = ref.getparent()
        while owner not in targets:
            owner = owner.getparent()
        targets[owner].add(urljoin(url, ref))

    videos = {scope: keys for scope, refs in targets.items() if (keys := video_keys(refs))}
    # Head metadata and a single hearing on the calendar describe a detail page. A listing
    # needs an explicit event link in the same item as the recording, even for its first item.
    host = (urlsplit(url).hostname or '').removeprefix('www.')
    official = host in ('csce.gov', 'house.gov', 'senate.gov') or host.endswith(('.house.gov', '.senate.gov'))
    detail = len(videos) == 1 and (not items or (len(items) == 1 and body not in videos))
    detail_events = set()
    if official and detail:
        detail_events = _calendar_event(tree, url, calendar) | _event_ids(set().union(*targets.values()))
    found = defaultdict(set)
    for scope, keys in videos.items():
        if scope is body and items:
            continue  # Links between items do not belong to any proceeding.
        events = detail_events if detail else (_event_ids(targets[scope]) if official else set())
        for key in keys:
            found[key].update(events if len(events) == 1 else ())
    return found


def page_links(body, url, calendar):
    """Return the videos and only the events corroborated for every one of them."""
    found = _proceeding_links(_document(body), url, calendar)
    return set(found), sorted(set.intersection(*found.values())) if found else []


def recording_page_events(body, url, calendar, linked, unlinked):
    tree = _document(body)
    # An unlinked addition claims only that a new page contains its URL.
    found = {video: [] for video in unlinked & video_keys(_targets(tree, url))} if unlinked else {}
    if linked:
        by_video = _proceeding_links(tree, url, calendar)
        found.update((video, sorted(by_video[video])) for video in linked & by_video.keys())
    return found
