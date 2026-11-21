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

from congress_api.parsers.committee_pages import event_identity, event_title, listing_url
from congress_api.parsers.main_content import _is_cms_chrome
from congress_api.parsers.senate_page import DATE, written_day
from congress_api.parsers.text import words as substantive_words
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
    req = {'event_id', 'committees', 'meeting_date', 'title', 'sittings'}
    if path and path.is_file():
        names = set(pq.read_schema(path).names)
        if req <= names:
            cols = sorted(req | (names & {'meeting_type'}))
            for row in pq.read_table(path, columns=cols).to_pylist():
                if row['meeting_date'] is None:
                    continue
                for committee in row['committees'] or ():
                    by_day[committee['system_code'][:4], str(row['meeting_date'])][row['event_id']] = row
    return by_day


_MARKUP_DATE = '//span[@class="date" and starts-with(normalize-space(.),"Markup Date:")]'
_TEMPLATE_DATES = '//main//span[@class="date-bar"] | //article//span[@class="date-bar"] | ' + _MARKUP_DATE
_DATE_TERM = re.compile(r'(?:(?:hearing|meeting|event|markup) date|date|when)\s*:?', re.I)
_DATE_IN_TEXT = re.compile(
    r'(?:(?:\b(?:hearing|meeting|event|markup)\s+date|^(?:date|when))\s*:\s*|'
    r'\b(?:hearing|meeting|event|markup)\s+(?:(?:is|was|has|been|will|be|now)\s+)*'
    r'(?:rescheduled|postponed|moved|scheduled|held|take place|convene)\s+(?:to|for|on)\s+)'
    r'(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s+)?', re.I | re.M)


def _text(node):
    return ' '.join(' '.join(node.itertext()).split())


def _displayed_dates(body):
    """Read every visible date source before deciding whether the proceeding has one day."""
    fields = set(body.xpath('.//time[not(ancestor::p)] | .//h1 | .//h2 | .//h3 | .//h4 | .//h5 | .//h6 | '
                            './/*[@itemprop="startDate" or contains(concat(" ",normalize-space(@class)," ")," date ") or '
                            'contains(concat(" ",normalize-space(@class)," ")," date-bar ") or contains(@class,"hearing__date") or '
                            'contains(@class,"field-evo-meeting-date") or contains(@class,"event-item__date") or '
                            'contains(@class,"event-item__meta") or contains(@id,"_EventDate")]'))
    for definition in body.iter('dd'):
        term = next(definition.itersiblings('dt', preceding=True), None)
        if term is not None and _DATE_TERM.fullmatch(_text(term)):
            fields.add(definition)
    matches = [match for node in fields for match in DATE.finditer(_text(node))]
    # Labels may span inline elements or sit directly in an otherwise unmarked container.
    lines = '\n'.join(' '.join(part.split()) for part in body.itertext() if part.strip())
    text = lines.replace('\n', ' ')
    matches.extend(match for label in _DATE_IN_TEXT.finditer(lines) if (match := DATE.match(text, label.end())))
    # An unlabelled paragraph can be the date field itself. A date mentioned
    # in filing instructions or other prose does not date the proceeding.
    for paragraph in body.iter('p'):
        if match := DATE.fullmatch(_text(paragraph)):
            matches.append(match)
    return {day.isoformat() for match in matches if (day := written_day(match))}


_ROUNDTABLE_KIND = re.compile(r'\bround[- ]?tables?\b', re.I)
_MARKUP_KIND = re.compile(r'\b(?:markup|business\s+meeting)\b', re.I)
_HEARING_KIND = re.compile(r'\bhearings?\b', re.I)
_JOINT_SUFFIX = re.compile(r'\s*\([^()]*\bjoint\b[^()]*\)\s*$', re.I)


def _proceeding_kind(title, meeting_type=None, *, markup_date=False):
    text = title or ''
    mtype = (meeting_type or '').strip()
    if _ROUNDTABLE_KIND.search(text) or 'roundtable' in mtype.lower():
        return 'roundtable'
    if markup_date or mtype.upper() == 'HMKP' or 'markup' in mtype.lower() or _MARKUP_KIND.search(text):
        return 'markup'
    if mtype.upper() == 'HHRG' or 'hearing' in mtype.lower() or _HEARING_KIND.search(text):
        return 'hearing'
    return None


def _calendar_event(tree, body, url, calendar, displayed_date):
    from viewer_publication.corpus_quality.provenance_validator import CONGRESSIONAL_HOST_TO_SYSTEM_CODE
    code = CONGRESSIONAL_HOST_TO_SYSTEM_CODE.get((urlsplit(url).hostname or '').removeprefix('www.'))
    if not code:
        return set()
    identity = event_identity(html.tostring(tree), url)
    require_title = False
    has_markup_date = bool(tree.xpath(_MARKUP_DATE))
    if not identity:
        # Legacy detail templates also use four-digit post IDs on apparent archive routes.
        if not displayed_date or (listing_url(url) and not tree.xpath(_TEMPLATE_DATES)):
            return set()
        require_title = not has_markup_date
        identity = dict(title=event_title(tree) or tree.xpath('string(//title)'), date=displayed_date)
    if displayed_date and identity['date'] != displayed_date:
        return set()
    events = calendar.get((code[:4], identity['date']), {})
    if not events:
        return set()
    page_kind = _proceeding_kind(identity['title'], markup_date=has_markup_date)
    if page_kind is not None:
        same_kind = {ev: row for ev, row in events.items()
                     if _proceeding_kind(row.get('title'), row.get('meeting_type')) == page_kind}
        other_kind = {ev for ev, row in events.items()
                      if (ek := _proceeding_kind(row.get('title'), row.get('meeting_type'))) is not None and ek != page_kind}
        if same_kind and len(same_kind) + len(other_kind) == len(events):
            events = same_kind
    if len(events) == 1 and not require_title:
        return set(events)

    def words(value):
        return ' '.join(re.findall(r'\w+', (value or '').casefold()))

    heading = words(identity['title'])
    def title_matches(title):
        subject = words((title or '').split(':', 1)[0])
        if not subject:
            return False
        base = words(_JOINT_SUFFIX.sub('', title or ''))
        return (words(title) in heading
                or (len(heading.split()) >= 3 and bool(base) and base == heading)
                or (len(subject.split()) >= 3 and heading.startswith(subject + ' ')))
    titled = {ev for ev, row in events.items() if title_matches(row.get('title'))}
    # Page and calendar can show different scheduled start times. A single exact title
    # identifies the proceeding on that committee's day even after a time change.
    if len(titled) == 1:
        return titled

    body_words = substantive_words(_text(body)) - _RECORDING_STOPWORDS
    strong = {}
    for ev, row in events.items():
        ek = _proceeding_kind(row.get('title'), row.get('meeting_type'))
        if page_kind is not None and ek is not None and (page_kind == 'roundtable') != (ek == 'roundtable'):
            continue
        m_words = substantive_words(row.get('title')) - _RECORDING_STOPWORDS
        shared = len(body_words & m_words)
        if m_words and shared >= 3 and (shared >= 4 or shared * 2 >= len(m_words)):
            strong[ev] = shared
    if strong:
        best = max(strong.values())
        winners = {ev for ev, score in strong.items() if score == best}
        if len(winners) == 1:
            return winners
    if require_title:
        return set()
    fields = tree.xpath('//*[contains(@class,"hearing__time") or starts-with(@class,"time ")] | ' + _MARKUP_DATE)
    times = {datetime.strptime(t, '%I:%M %p').time() for node in fields
             for t in re.findall(r'\b(?:0?[1-9]|1[0-2]):[0-5]\d [AP]M\b', node.text_content().upper())}
    timed = {ev for ev, row in events.items() if any(s['start'] and
             s['start'].astimezone(ZoneInfo('America/New_York')).time() in times for s in row.get('sittings') or ())}
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
    tree = html.document_fromstring(body, parser=html.HTMLParser(no_network=True), ensure_head_body=True)
    # Both linked and unlinked evidence must come from visible elements.
    for node in tree.xpath('//style | //noscript | //*[@hidden or @aria-hidden or @style]'):
        if (node.tag in ('style', 'noscript') or 'hidden' in node.attrib or node.get('aria-hidden', '').strip().lower() == 'true'
                or _HIDDEN_STYLE.search(node.get('style', ''))):
            if node is tree or node.tag in ('head', 'body'):
                node.clear()
            else:
                node.drop_tree()
    return tree


_URL_ATTRIBUTES = './/@href | .//@src | .//object/@data'
_DOCUMENT_ROLES = {'main', 'article', 'region', 'document', 'presentation', 'none'}
_HIDDEN_STYLE = re.compile(r'(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\b', re.I)
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


def _is_landmark(node, *names):
    return node.tag in names or any(role in names for role in node.get('role', '').lower().split())


def _landmarks(root, name):
    return [node for node in root.xpath(f'.//{name} | .//*[@role]') if _is_landmark(node, name)]


def _item_scopes(root, url):
    """Articles own their links. Repeated list items and cards can also hold separate proceedings."""
    scopes = set(_landmarks(root, 'article'))
    siblings = defaultdict(list)
    for node in root.xpath('.//li | .//div[@class] | .//section[@class]'):
        if node.tag == 'li' or _ITEM_TOKEN.search(node.get('class', '')):
            siblings[node.getparent()].append(node)
    for items in siblings.values():
        if len(items) > 1 and any(video_keys(_targets(item, url)) for item in items):
            scopes.update(items)
    return scopes


def _proceeding_body(tree):
    for node in tree.xpath('//aside | //nav | //footer | //header | //template | //menu | //dialog | //*[@role or @class or @id]'):
        if (_is_cms_chrome(node) or node.tag in ('aside', 'footer', 'template', 'menu', 'dialog')
                or (node.tag == 'header' and not any(_is_landmark(p, 'article', 'main') for p in node.iterancestors()))
                or not _DOCUMENT_ROLES.issuperset(node.get('role', '').lower().split())
                or _CHROME_TOKEN.search(f"{node.get('class', '')} {node.get('id', '')}")):
            if node is tree or node.tag == 'body':
                return None
            if node.tag == 'head':
                node.clear()
            else:
                node.drop_tree()
    # Preserve structured event metadata for event_identity, outside visible headings and dates.
    for script in tree.xpath('//body//script'):
        script.drop_tree()
        if script.get('type') == 'application/ld+json' or script.get('id') == '__NEXT_DATA__':
            script.tail = None
            tree.head.append(script)
    return tree.body


def _recording_scope(body):
    mains = _landmarks(body, 'main')
    outer = [node for node in mains if not any(parent in mains for parent in node.iterancestors())]
    if len(outer) > 1:
        return None
    if outer:
        return outer[0]
    articles = _landmarks(body, 'article')
    return articles[0] if len(articles) == 1 else body


# The recording matcher also excludes these generic words from the parser's title tokens.
_RECORDING_STOPWORDS = set('united states congress washington open closed public session http https www gov html htm '
                           'aspx events event calendar eventsingle eventid democrats republicans markups business '
                           'entitled legislative office'.split())
_COMMITTEE_SUFFIX = re.compile(r'\s*\|\s*[^|]*\bcommittee\b[^|]*$|'
                               r'\s*[-–—]\s*(?:(?:hearings?|markups?|events?|press releases?)\s*[-–—]\s*)?'
                               r'(?:u\.?s\.?\s+)?(?:the\s+)?(?:house\s+)?committee\b.*$', re.I)

_COMMITTEE_NAME = re.compile(r'^(?:the\s+)?(?:(?:u\.?s\.?|united states)\s+)?'
                             r'(?:(?:house|senate)\s+)?(?:sub)?committee\s+on\b', re.I)
_PROCEEDING_KIND = re.compile(r'\b(?:hearing|meeting|markup|roundtable|session)\b', re.I)
_STATED_EVENT = re.compile(r'(?:\bevent\s*id\s*[=:#]\s*|\bdocs\.house\.gov/[^\s"\'<>]*[?&]eventid=|'
                           r'\bcongress\.gov/event/[0-9]+(?:st|nd|rd|th)?(?:-congress)?/house-event/)'
                           r'0*(1[0-9]{5})\b', re.I)


def _subject_words(tree):
    titles = (_COMMITTEE_SUFFIX.sub('', value or '').strip()
              for value in (event_title(tree), tree.xpath('string(/html/head/title)')))
    # A site-wide committee name supplies no subject. A named proceeding such as
    # "Subcommittee on Economic Opportunity Legislative Hearing" supplies one.
    subjects = [t for t in titles if not _COMMITTEE_NAME.match(t) or _PROCEEDING_KIND.search(t)]
    return substantive_words(' '.join(subjects)) - _RECORDING_STOPWORDS


def _detail_events(tree, body, url, calendar):
    from viewer_publication.corpus_quality.provenance_validator import CONGRESSIONAL_HOST_TO_SYSTEM_CODE
    all_explicit = _event_ids(_targets(body, url))
    if not calendar:
        return all_explicit
    dates = _displayed_dates(body)
    if len(dates) > 1:
        return set()
    day = next(iter(dates), None)
    proceeding = _calendar_event(tree, body, url, calendar, day)
    events = proceeding | all_explicit
    if not day or all_explicit <= proceeding:
        return events

    code = CONGRESSIONAL_HOST_TO_SYSTEM_CODE.get((urlsplit(url).hostname or '').removeprefix('www.'))
    on_day = {}
    other_titles = defaultdict(set)
    other_committees = defaultdict(set)
    for (cal_code, calendar_day), rows in calendar.items():
        if calendar_day == day:
            on_day.update((ev, rows[ev].get('title')) for ev in events.intersection(rows))
        else:
            for ev in all_explicit.intersection(rows):
                other_titles[ev].add(rows[ev].get('title'))
                other_committees[ev].add(cal_code)
    stale = other_titles.keys() - on_day.keys()
    if not stale:
        return events
    title_words = _subject_words(tree)
    if not proceeding and not on_day and len(all_explicit) == 1 and code:
        explicit_ev, = all_explicit
        if code[:4] in other_committees.get(explicit_ev, ()):
            day_rows = calendar.get((code[:4], day), {})
            day_max = max((len(title_words & (substantive_words(r.get('title')) - _RECORDING_STOPWORDS))
                           for r in day_rows.values()), default=0)
            exp_titles = other_titles.get(explicit_ev, ())
            if exp_titles and all(
                title and (ov := len(title_words & (substantive_words(title) - _RECORDING_STOPWORDS))) >= 2 and ov > day_max
                for title in exp_titles
            ):
                return set(all_explicit)
    if len(proceeding) != 1:
        return set()
    candidate, = proceeding
    overlap = len(title_words & substantive_words(on_day.get(candidate)))
    if not overlap or any(not title or overlap <= len(title_words & substantive_words(title))
                          for ev in stale for title in other_titles[ev]):
        return events  # The candidate and the explicit evidence still conflict.
    return events - stale


def _proceeding_links(tree, url, calendar):
    from viewer_publication.corpus_quality.provenance_validator import CONGRESSIONAL_HOST_TO_SYSTEM_CODE
    body = _proceeding_body(tree)
    if body is None:
        return {}
    root = _recording_scope(body)
    if root is None:
        return {}
    items = _item_scopes(root, url)
    targets = {scope: set() for scope in (root, *items)}
    for ref in root.xpath(_URL_ATTRIBUTES):
        owner = ref.getparent()
        while owner not in targets:
            owner = owner.getparent()
        targets[owner].add(urljoin(url, ref))

    videos = {scope: keys for scope, refs in targets.items() if (keys := video_keys(refs))}
    # Head metadata and a single hearing on the calendar describe a detail page. A listing
    # needs an explicit event link in the same item as the recording, even for its first item.
    host = (urlsplit(url).hostname or '').removeprefix('www.')
    official = host in ('csce.gov', 'house.gov', 'senate.gov') or host.endswith(('.house.gov', '.senate.gov'))
    detail = len(videos) == 1 and (not items or (len(items) == 1 and root not in videos))
    detail_events = _detail_events(tree, body, url, calendar) if official and detail else set()
    code = CONGRESSIONAL_HOST_TO_SYSTEM_CODE.get(host)
    dates = _displayed_dates(body) if detail and len(detail_events) > 1 else set()
    day = next(iter(dates), None) if len(dates) == 1 else None
    found = defaultdict(set)
    for scope, keys in videos.items():
        if scope is root and items:
            continue  # Links between items do not belong to any proceeding.
        events = set(detail_events) if detail else (_event_ids(targets[scope]) if official else set())
        if len(events) > 1:
            day_rows = calendar.get((code[:4], day), {}) if (detail and code and day) else {}
            scope_explicit = _event_ids(targets[scope])
            scope_words = substantive_words(_text(scope)) - _RECORDING_STOPWORDS
            if not (detail and day_rows and events == scope_explicit and events <= day_rows.keys()
                    and all(len(scope_words & (substantive_words(day_rows[ev].get('title')) - _RECORDING_STOPWORDS)) >= 2
                            for ev in events)):
                events = set()
        if events:
            # A printed citation identifies the proceeding directly. Only an outbound
            # template link can be set aside on the strength of calendar and title.
            title = tree.xpath('string(/html/head/title)') if detail else ''
            text = f'{title} {_text(body if detail else scope)}'
            stated = {int(value) for value in _STATED_EVENT.findall(text)}
            if detail:
                stated.update(_event_ids((url,)))
            if stated - events:
                events = set()
        for key in keys:
            found[key].update(events)
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
