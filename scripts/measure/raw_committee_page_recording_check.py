"""Independent raw check of published committee_page recording matches (ct-414r).

    raw_committee_page_recording_check.py --release DIR [--mirror R2_IMMUTABLE] --output OUT.json [--require-provenance]

Judges published committee_page recording matches directly from raw fetched bytes (re-hashed
against the SHA-256 cited in source_ref) and independent signals that do not mirror any
production threshold:
  1. Direction A (published -> raw):
     - Raw byte SHA-256 verification and presence of the claimed YouTube ID.
     - DOM-aware HTML structure separating editorial content from site navigation, footer,
       sidebar, and lightbox-carousel chrome (detecting chrome-only footer/sidebar embeds
       and nav-bar-only false topic overlap).
     - Congress.gov API JSON support when the cited raw body is a JSON meeting payload.
     - Explicit House EventID links in raw HTML hrefs (docs.house.gov EventID and ordinal or
       numeric congress.gov/event/.../house-event/ URLs, including zero-padded IDs).
     - Independent bill-number comparison across video title, raw editorial page, and meeting.
     - Independent calendar-date comparison (video title dates and upload timestamps vs
       meeting dates) and Jaccard title-similarity check for conflicting stated EventIDs.
     - Explicit four-way verdict: raw_supports (only with affirmative raw corroboration),
       raw_inconclusive (read without contradiction or affirmative corroboration),
       raw_contradicts, and unread_body_no_metadata_contradiction.
  2. Direction B (raw -> published):
     - For every readable raw body (from --raw-pages or cited mirror bodies) that explicitly
       links one known House meeting and embeds a YouTube video in editorial content, verify
       that (event_id, video_key) is published specifically under basis='committee_page'.

Every cited body not present in the mirror is named in unread_pages rather than assumed valid.
"""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
import gzip
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re

import pyarrow.parquet as pq

YOUTUBE_URL_RE = re.compile(
    r'(?:youtube(?:-nocookie)?\.com/(?:watch\?(?:[^"\'\s<>]*&)?v=|embed/|live/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})',
    re.I,
)
HOUSE_EVENT_URL_RE = re.compile(
    r'(?:docs\.house\.gov/[^"\'\s<>]*?[?&]EventID=|congress\.gov/event/\d+(?:st|nd|rd|th)?(?:-congress)?/house-event/)0*(1\d{5})\b',
    re.I,
)
EXPLICIT_EVENT_ID_RE = re.compile(r'(?:\bevent\s*id|\bid)\s*[=:#]\s*0*(1\d{5})\b', re.I)
ROUNDTABLE_RE = re.compile(r'\bround[- ]?tables?\b', re.I)
HEARING_OR_MARKUP_RE = re.compile(r'\b(?:hearing|hearings|markup|mark-?up)\b', re.I)
SHA64_RE = re.compile(r'^[0-9a-f]{64}$')
VIA_SHA_RE = re.compile(r'\[via committee_page:([0-9a-f]{64})\]')
BILL_RE = re.compile(
    r'\b(h\.?\s*r\.?|s\.?|h\.?\s*j\.?\s*res\.?|s\.?\s*j\.?\s*res\.?|h\.?\s*con\.?\s*res\.?|s\.?\s*con\.?\s*res\.?|h\.?\s*res\.?|s\.?\s*res\.?)\s*(\d{1,5})\b',
    re.I,
)
SUBJECT_BILL_RE = re.compile(r'^\d+-(hr|s|hjres|sjres|hconres|sconres|hres|sres)-(\d+)$', re.I)
CHROME_ATTR_RE = re.compile(
    r'\b(?:nav|navbar|navigation|menu|submenu|dropdown|site-header|main-header|top-header|footer|intfooter|sidebar|side-bar|breadcrumb|breadcrumbs|social|share|related|popup-holder|video-list|carousel|footer-links)\b',
    re.I,
)
EDITORIAL_ATTR_RE = re.compile(
    r'\b(?:bodycopy|newsbody|main-newscopy|user-content|evo-press-release|entry-content|post-content|page-content)\b',
    re.I,
)
CMTE_SUFFIX_RE = re.compile(r'(?:\||[-–—])\s*([^|–—-]*\bcommittee\b.*)$', re.I)
CMTE_PHRASE_RE = re.compile(
    r'\bcommittee\s+on\s+[a-z\s,&-]+?(?=[.,;:]|\s+(?:democrats|republicans|gave|held|today|will|has|on|for|to|at|in)\b)',
    re.I,
)

MONTHS = {
    'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
    'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6, 'jul': 7, 'july': 7,
    'aug': 8, 'august': 8, 'sep': 9, 'sept': 9, 'september': 9,
    'oct': 10, 'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12,
}

# Lightweight independent English function-word list for topical comparison.
BASIC_STOP = {
    'the', 'and', 'for', 'with', 'from', 'that', 'this', 'into', 'over', 'under', 'about',
    'their', 'there', 'these', 'those', 'have', 'been', 'will', 'would', 'could', 'should',
    'hearing', 'hearings', 'subcommittee', 'committee', 'house', 'senate', 'united', 'states', 'congress',
    'washington', 'full', 'open', 'closed', 'public', 'session', 'meeting', 'markup', 'markups',
    'business', 'legislative', 'oversight', 'review', 'examining', 'examine', 'part', 'titled',
    'entitled', 'act', 'bill', 'bills', 'law', 'laws', 'democrats', 'republicans', 'democratic',
    'republican', 'member', 'members', 'ranking', 'chairman', 'chair', 'chairwoman', 'congresswoman',
    'congressman', 'representative', 'today', 'statement', 'opening', 'remarks', 'press', 'release',
    'releases', 'committee', 'federal', 'national', 'american', 'americans', 'various', 'measures',
    'pending', 'legislation', 'fiscal', 'year',
}


def normalize_bill_type(raw_type):
    return re.sub(r'[\s.]+', '', (raw_type or '').lower())


def extract_bills(text, subject_keys=()):
    bills = set()
    if text:
        for btype, num in BILL_RE.findall(text):
            bt = normalize_bill_type(btype)
            if bt == 's' and len(num) == 4 and num.startswith(('19', '20')):
                continue
            bills.add((bt, int(num)))
    for key in subject_keys or ():
        m = SUBJECT_BILL_RE.match(str(key).strip())
        if m:
            bills.add((m.group(1).lower(), int(m.group(2))))
    return bills


def distinctive_tokens(text, *, exclude=frozenset()):
    raw = text or ''
    toks = {
        t for t in re.findall(r'[a-z]{4,}|\d{3,}', raw.lower())
        if t not in BASIC_STOP and t not in exclude and not (len(t) == 4 and t.startswith(('19', '20')))
    }
    # Preserve 3-letter uppercase agency/topic acronyms (e.g., SEC, CBO, EPA, FDA, DHS, GAO).
    for acro in re.findall(r'\b([A-Z]{3})\b', raw):
        low = acro.lower()
        if low not in BASIC_STOP and low not in exclude:
            toks.add(low)
    return toks


def jaccard_similarity(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class _RawHtmlDomReader(HTMLParser):
    """DOM-aware stdlib HTML reader separating editorial content from site chrome/nav/footer/sidebar."""

    VOID_TAGS = frozenset({'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._stack = []
        self._skip_depth = 0
        self._chrome_depth = 0
        self._editorial_depth = 0
        self._in_title = False
        self._in_heading = False
        self._title_parts = []
        self._cur_heading = []
        self.headings = []
        self._editorial_parts = []
        self._non_chrome_parts = []
        self.hrefs = []
        self.editorial_video_ids = set()
        self.chrome_video_ids = set()

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr_map = dict(attrs)
        cls_id = (attr_map.get('class') or '') + ' ' + (attr_map.get('id') or '')

        is_skip = tag in {'script', 'style', 'noscript', 'svg'}
        is_editorial = tag in {'main', 'article'} or bool(EDITORIAL_ATTR_RE.search(cls_id))
        # A <header> inside <article>/<main> holds the article headline; a top-level <header> is site chrome.
        # Do not treat <form> as chrome: ASP.NET House committee sites wrap the entire page body in <form id="aspnetForm">.
        is_chrome = (
            tag in {'nav', 'footer', 'aside'}
            or (tag == 'header' and self._editorial_depth == 0)
            or bool(CHROME_ATTR_RE.search(cls_id))
        )

        next_chrome = self._chrome_depth + (1 if is_chrome else 0)
        for key in ('href', 'src', 'data-src', 'content'):
            val = attr_map.get(key)
            if not val:
                continue
            self.hrefs.append(val)
            for vid in YOUTUBE_URL_RE.findall(val):
                if next_chrome > 0:
                    self.chrome_video_ids.add(vid)
                else:
                    self.editorial_video_ids.add(vid)

        if tag in self.VOID_TAGS:
            return

        self._stack.append((tag, is_skip, is_chrome, is_editorial))
        if is_skip:
            self._skip_depth += 1
        if is_chrome:
            self._chrome_depth += 1
        if is_editorial:
            self._editorial_depth += 1
        if tag == 'title' and not self._title_parts:
            self._in_title = True
        elif tag == 'h1' and self._skip_depth == 0 and not any(t in {'nav', 'footer', 'aside'} for t, _, _, _ in self._stack[:-1]):
            self._in_heading = True
            self._cur_heading = []
        elif tag == 'h2' and self._chrome_depth == 0 and self._skip_depth == 0:
            self._in_heading = True
            self._cur_heading = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.VOID_TAGS:
            return
        if tag == 'title':
            self._in_title = False
        elif tag in {'h1', 'h2'} and self._in_heading:
            text = re.sub(r'\s+', ' ', ''.join(self._cur_heading)).strip()
            if text:
                self.headings.append(text)
            self._in_heading = False
            self._cur_heading = []

        # Unwind stack to matching open tag when present.
        for idx in range(len(self._stack) - 1, -1, -1):
            if self._stack[idx][0] == tag:
                while len(self._stack) > idx:
                    _, was_skip, was_chrome, was_ed = self._stack.pop()
                    if was_skip and self._skip_depth > 0:
                        self._skip_depth -= 1
                    if was_chrome and self._chrome_depth > 0:
                        self._chrome_depth -= 1
                    if was_ed and self._editorial_depth > 0:
                        self._editorial_depth -= 1
                break

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title_parts.append(data)
            return
        if self._in_heading:
            self._cur_heading.append(data)
        if self._chrome_depth == 0:
            self._non_chrome_parts.append(data)
            if self._editorial_depth > 0:
                self._editorial_parts.append(data)

    @property
    def title(self):
        return re.sub(r'\s+', ' ', ''.join(self._title_parts)).strip()

    @property
    def editorial_body(self):
        src = self._editorial_parts if self._editorial_parts else self._non_chrome_parts
        return re.sub(r'\s+', ' ', ' '.join(src)).strip()


def parse_raw_body(raw_bytes):
    text = raw_bytes.decode('utf-8', 'replace')
    stripped = text.lstrip()
    if stripped.startswith('{'):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get('committeeMeeting'), dict):
            cm = payload['committeeMeeting']
            ev = cm.get('eventId')
            linked = [int(ev)] if ev is not None and str(ev).strip().isdigit() else []
            vids = sorted(set(YOUTUBE_URL_RE.findall(text)))
            title = str(cm.get('title') or '')
            ed_text = title
            return dict(
                body_kind='congress_gov_json',
                title=title,
                clean_title=title,
                headings=[],
                committee_tokens=set(),
                editorial_text=ed_text,
                editorial_bills=extract_bills(ed_text),
                editorial_video_ids=vids,
                chrome_only_video_ids=[],
                all_video_ids=vids,
                linked_event_ids=linked,
                title_event_ids=[],
            )

    reader = _RawHtmlDomReader()
    reader.feed(text)
    reader.close()

    raw_title = reader.title
    m_suf = CMTE_SUFFIX_RE.search(raw_title)
    committee_tokens = distinctive_tokens(m_suf.group(1)) if m_suf else set()
    clean_title = CMTE_SUFFIX_RE.sub('', raw_title).strip()

    all_vids = set(reader.editorial_video_ids) | set(reader.chrome_video_ids) | set(YOUTUBE_URL_RE.findall(text))
    chrome_only = reader.chrome_video_ids - reader.editorial_video_ids
    editorial_vids = all_vids - chrome_only

    linked_events = set()
    for href in reader.hrefs:
        for m in HOUSE_EVENT_URL_RE.findall(href):
            linked_events.add(int(m))
    for m in HOUSE_EVENT_URL_RE.findall(text):
        linked_events.add(int(m))

    heading_text = ' '.join(reader.headings[:4])
    title_events = {int(m) for m in EXPLICIT_EVENT_ID_RE.findall(raw_title + ' ' + heading_text)}
    ed_text = CMTE_PHRASE_RE.sub(' ', f'{clean_title} {heading_text} {reader.editorial_body}')
    return dict(
        body_kind='html',
        title=raw_title,
        clean_title=clean_title,
        headings=reader.headings[:4],
        committee_tokens=committee_tokens,
        editorial_text=ed_text,
        editorial_bills=extract_bills(ed_text),
        editorial_video_ids=sorted(editorial_vids),
        chrome_only_video_ids=sorted(chrome_only),
        all_video_ids=sorted(all_vids),
        linked_event_ids=sorted(linked_events),
        title_event_ids=sorted(title_events),
    )


def parse_raw_html(raw_bytes):
    """Compatibility alias for callers parsing raw HTML bytes."""
    return parse_raw_body(raw_bytes)


def read_mirror_body(mirror, sha):
    """Read raw bytes for a 64-hex SHA-256 from mirror and verify the digest."""
    if not mirror or not sha or not SHA64_RE.match(sha):
        return None, None
    base = Path(mirror) / 'bodies' / 'sha256' / sha[:2]
    for suffix in ('.gz', '', '.html', '.json'):
        path = base / (sha + suffix)
        if path.is_file():
            raw = path.read_bytes()
            body = gzip.decompress(raw) if suffix == '.gz' else raw
            actual = sha256(body).hexdigest()
            return body, (actual == sha)
    return None, None


def parse_iso_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if len(s) >= 10:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    return None


def extract_explicit_date(text):
    """Extract an explicit calendar date printed in a video title (independent of page dates)."""
    if not text:
        return None
    m = re.search(r'\b(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\b', text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = re.search(r'\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b', text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    m = re.match(r'\s*(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(1[3-9]|2[0-9])\b', text)
    if m:
        try:
            return date(2000 + int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    m = re.search(r'\b(\d{1,2})[./-](\d{1,2})[./-](1[3-9]|2[0-9])\b', text)
    if m:
        try:
            return date(2000 + int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    m = re.search(
        r'\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(20\d{2})\b',
        text,
        re.I,
    )
    if m:
        try:
            return date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
        except ValueError:
            pass
    return None


def _load_table(path, columns=None):
    path = Path(path)
    if path.suffix == '.json':
        return json.loads(path.read_text())
    schema = set(pq.read_schema(path).names)
    cols = [c for c in columns if c in schema] if columns else None
    return pq.read_table(path, columns=cols).to_pylist()


def evaluate_release(
    *,
    matches_rows,
    meetings_rows,
    videos_rows,
    mirror=None,
    raw_pages_dir=None,
    require_provenance=False,
    max_examples=50,
):
    """Run independent two-directional raw checks over committee_page recording matches."""
    meetings = {}
    for row in meetings_rows:
        eid = row.get('event_id')
        if eid is not None:
            title = row.get('title') or ''
            subj = list(row.get('subject_keys') or [])
            meetings[int(eid)] = dict(
                event_id=int(eid),
                chamber=row.get('chamber'),
                meeting_date=parse_iso_date(row.get('meeting_date')),
                meeting_type=row.get('meeting_type'),
                title=title,
                subject_keys=subj,
                bills=extract_bills(title, subj),
            )

    videos = {}
    for row in videos_rows:
        vk = row.get('video_key')
        if vk:
            vtitle = row.get('title') or ''
            videos[vk] = dict(
                video_key=vk,
                title=vtitle,
                source_description=row.get('source_description') or '',
                stated_event_ids=[int(x) for x in (row.get('stated_event_ids') or []) if x is not None],
                video_date=parse_iso_date(row.get('video_published_at') or row.get('published_at')),
                bills=extract_bills(vtitle),
            )

    # Direction B must compare strictly against published basis='committee_page' pairs so another
    # basis (e.g. video_states_event_id or publisher_link) can never mask a missing committee_page row.
    published_cp_pairs = set()
    cp_rows = []
    for row in matches_rows:
        if row.get('basis') != 'committee_page':
            continue
        cp_rows.append(row)
        eid = row.get('event_id')
        vk = row.get('video_key')
        if eid is not None and vk and row.get('status') in ('asserted', 'claimed', 'decided'):
            published_cp_pairs.add((int(eid), vk))

    body_cache = {}
    unread_pages = set()
    read_pages = set()

    def get_page(sha):
        if sha in body_cache:
            return body_cache[sha]
        body, digest_ok = read_mirror_body(mirror, sha)
        if body is None:
            unread_pages.add(sha)
            body_cache[sha] = None
            return None
        read_pages.add(sha)
        parsed = parse_raw_body(body)
        parsed['digest_ok'] = digest_ok
        body_cache[sha] = parsed
        return parsed

    contradictions = Counter()
    examples = defaultdict(list)
    verdicts = Counter()
    row_verdicts = {}

    def flag(kind, row, detail):
        contradictions[kind] += 1
        if len(examples[kind]) < max_examples:
            examples[kind].append(dict(
                match_id=row.get('match_id'),
                event_id=row.get('event_id'),
                video_key=row.get('video_key'),
                source_ref=row.get('source_ref'),
                note=row.get('note'),
                detail=detail,
            ))

    for row in cp_rows:
        eid = row.get('event_id')
        vk = row.get('video_key')
        sref = row.get('source_ref') or ''
        note = row.get('note')
        row_flags = []

        if not sref.startswith('committee_page:') or not SHA64_RE.match(sref.split(':', 1)[1]):
            row_flags.append('invalid_source_ref')
            flag('invalid_source_ref', row, {'source_ref': sref})
            sha = None
        else:
            sha = sref.split(':', 1)[1]

        via_match = VIA_SHA_RE.search(str(note or ''))
        win_sha = via_match.group(1) if via_match else None

        if require_provenance and not (note and str(note).strip()):
            row_flags.append('missing_provenance_note')
            flag('missing_provenance_note', row, {'note': note})

        cited_page = get_page(sha) if sha else None
        win_page = get_page(win_sha) if (win_sha and win_sha != sha) else None
        # Evaluate the winning supporting body when distinct and available, while still validating source_ref bytes.
        page = win_page if win_page is not None else cited_page

        if cited_page is not None and not cited_page['digest_ok']:
            row_flags.append('raw_html_digest_mismatch')
            flag('raw_html_digest_mismatch', row, {'sha': sha})
        if win_page is not None and not win_page['digest_ok']:
            row_flags.append('raw_html_digest_mismatch')
            flag('raw_html_digest_mismatch', row, {'sha': win_sha})

        meeting = meetings.get(int(eid)) if eid is not None else None
        video = videos.get(vk) if vk else None
        yt_id = vk.split(':', 1)[1] if (vk and vk.startswith('youtube:')) else None
        v_title = (video or {}).get('title') or ''
        v_toks = distinctive_tokens(v_title)
        v_bills = (video or {}).get('bills') or set()

        corroborated = False
        if page is not None:
            if yt_id is not None and yt_id not in page['all_video_ids']:
                row_flags.append('video_not_in_raw_body')
                flag('video_not_in_raw_body', row, {'expected_youtube_id': yt_id, 'found_ids': page['all_video_ids'][:10]})
            page_explicit_events = sorted(set(page['linked_event_ids']) | set(page['title_event_ids']))
            if eid is not None and page_explicit_events and int(eid) not in page_explicit_events:
                row_flags.append('raw_body_event_link_conflict')
                flag('raw_body_event_link_conflict', row, {'explicit_event_ids': page_explicit_events})

            m_toks = distinctive_tokens(meeting['title'], exclude=page['committee_tokens']) if meeting else set()
            m_bills = meeting['bills'] if meeting else set()
            video_meeting_overlap = len(v_toks & m_toks)
            video_meeting_bills = v_bills & m_bills

            if yt_id is not None and yt_id in page['chrome_only_video_ids'] and video_meeting_overlap == 0 and not video_meeting_bills:
                row_flags.append('chrome_only_video_embed')
                flag('chrome_only_video_embed', row, {
                    'youtube_id': yt_id,
                    'video_title': v_title,
                    'page_title': page['title'],
                })

            ed_toks = distinctive_tokens(page['editorial_text'], exclude=page['committee_tokens'])
            ed_overlap = ed_toks & m_toks
            ed_bill_overlap = page['editorial_bills'] & m_bills
            header_toks = distinctive_tokens(page['clean_title'] + ' ' + ' '.join(page['headings']), exclude=page['committee_tokens'])

            if (
                meeting is not None
                and meeting.get('chamber') == 'house'
                and page['body_kind'] == 'html'
                and int(eid) not in page_explicit_events
                and len(m_toks) >= 2
                and len(header_toks) >= 3
                and len(ed_overlap) == 0
                and not ed_bill_overlap
            ):
                row_flags.append('editorial_body_topic_contradiction')
                flag('editorial_body_topic_contradiction', row, {
                    'meeting_title': meeting['title'],
                    'page_title': page['title'],
                    'video_title': v_title,
                })

            # Affirmative corroboration from raw bytes (never default uncorroborated reads to raw_supports).
            in_editorial = yt_id is None or yt_id in page['editorial_video_ids']
            if in_editorial:
                if page['body_kind'] == 'congress_gov_json' and eid is not None and int(eid) in page['linked_event_ids']:
                    corroborated = True
                elif eid is not None and int(eid) in page_explicit_events:
                    corroborated = True
                elif meeting is not None and (
                    len(ed_overlap) >= 2
                    or bool(ed_bill_overlap)
                    or (len(m_toks) == 1 and len(ed_overlap) == 1)
                ):
                    corroborated = True

        if meeting is not None:
            m_title = meeting['title']
            m_bills = meeting['bills']
            m_toks_all = distinctive_tokens(m_title)
            m_rt = bool(ROUNDTABLE_RE.search(m_title))
            p_title = ((page or {}).get('clean_title') or '') + ' ' + ' '.join((page or {}).get('headings') or [])
            p_rt = bool(ROUNDTABLE_RE.search(p_title))
            v_rt = bool(ROUNDTABLE_RE.search(v_title))
            v_hm = bool(HEARING_OR_MARKUP_RE.search(v_title))

            if (p_rt or v_rt) and not m_rt:
                row_flags.append('proceeding_genre_conflict')
                flag('proceeding_genre_conflict', row, {'meeting_title': m_title, 'video_title': v_title, 'page_title': p_title.strip()})
            elif m_rt and v_hm and not v_rt:
                row_flags.append('proceeding_genre_conflict')
                flag('proceeding_genre_conflict', row, {'meeting_title': m_title, 'video_title': v_title})

            if video is not None:
                cand_overlap = len(v_toks & m_toks_all)
                cand_bill_overlap = v_bills & m_bills

                # Independent bill-number contradiction: video names specific bill(s) absent from both meeting and editorial page.
                if (
                    v_bills
                    and int(eid) not in video['stated_event_ids']
                    and (m_bills or len(m_toks_all) >= 2)
                    and not cand_bill_overlap
                    and cand_overlap == 0
                ):
                    page_has_vbill = bool(page and (v_bills & page['editorial_bills']))
                    if not page_has_vbill:
                        row_flags.append('video_bill_contradiction')
                        flag('video_bill_contradiction', row, {
                            'video_bills': sorted(f'{bt}-{num}' for bt, num in v_bills),
                            'meeting_title': m_title,
                            'video_title': v_title,
                        })

                # Independent calendar date contradiction: explicit date in video title disagrees sharply with meeting_date.
                title_date = extract_explicit_date(v_title)
                if meeting['meeting_date'] is not None and title_date is not None:
                    if abs((title_date - meeting['meeting_date']).days) > 7 and cand_overlap == 0 and not cand_bill_overlap:
                        row_flags.append('video_date_contradiction')
                        flag('video_date_contradiction', row, {
                            'meeting_date': str(meeting['meeting_date']),
                            'video_title_date': str(title_date),
                            'video_title': v_title,
                            'meeting_title': m_title,
                        })

                # Independent stated-event check using calendar dates, bill numbers, and Jaccard title similarity.
                stated = [se for se in video['stated_event_ids'] if se != int(eid)]
                if stated and int(eid) not in video['stated_event_ids'] and not cand_bill_overlap:
                    vid_ref_date = title_date or video['video_date']
                    cand_jacc = jaccard_similarity(v_toks, m_toks_all)
                    best_conflict = None
                    for se in stated:
                        sm = meetings.get(se)
                        if sm is None:
                            continue
                        sm_toks = distinctive_tokens(sm['title'])
                        sm_bills = sm['bills']
                        date_proves_other = (
                            vid_ref_date is not None
                            and sm['meeting_date'] is not None
                            and meeting['meeting_date'] is not None
                            and abs((vid_ref_date - sm['meeting_date']).days) <= 3
                            and abs((vid_ref_date - meeting['meeting_date']).days) > 10
                        )
                        date_proves_cand = (
                            vid_ref_date is not None
                            and sm['meeting_date'] is not None
                            and meeting['meeting_date'] is not None
                            and abs((vid_ref_date - meeting['meeting_date']).days) <= 2
                            and abs((vid_ref_date - sm['meeting_date']).days) > 14
                        )
                        bill_proves_other = bool(v_bills & sm_bills)
                        sm_jacc = jaccard_similarity(v_toks, sm_toks)
                        jacc_proves_other = (cand_jacc == 0.0 and sm_jacc >= 0.25 and not date_proves_cand)
                        if date_proves_other or bill_proves_other or jacc_proves_other:
                            reasons = []
                            if date_proves_other:
                                reasons.append('calendar_date')
                            if bill_proves_other:
                                reasons.append('bill_number')
                            if jacc_proves_other:
                                reasons.append('title_jaccard')
                            best_conflict = dict(
                                stated_event_id=se,
                                stated_meeting_title=sm['title'],
                                stated_meeting_date=str(sm['meeting_date']) if sm['meeting_date'] else None,
                                candidate_meeting_date=str(meeting['meeting_date']) if meeting['meeting_date'] else None,
                                video_date=str(vid_ref_date) if vid_ref_date else None,
                                cand_jaccard=round(cand_jacc, 3),
                                stated_jaccard=round(sm_jacc, 3),
                                reasons=reasons,
                            )
                            break
                    if best_conflict is not None:
                        row_flags.append('conflicting_video_stated_event_id')
                        flag('conflicting_video_stated_event_id', row, best_conflict)

        if row_flags:
            verdict = 'raw_contradicts'
        elif page is None:
            verdict = 'unread_body_no_metadata_contradiction'
        elif corroborated:
            verdict = 'raw_supports'
        else:
            verdict = 'raw_inconclusive'
        verdicts[verdict] += 1
        if eid is not None and vk:
            row_verdicts[f'{eid}/{vk}'] = dict(verdict=verdict, flags=row_flags)

    # Direction B (raw -> published committee_page): verify explicit raw bodies appear under basis='committee_page'.
    dir_b_checked = 0
    dir_b_missing = []
    scan_pages = []
    if raw_pages_dir is not None:
        for path in sorted(Path(raw_pages_dir).rglob('*')):
            if path.is_file():
                raw = path.read_bytes()
                body = gzip.decompress(raw) if path.suffix == '.gz' else raw
                scan_pages.append((path.name, parse_raw_body(body)))
    else:
        for sha in sorted(read_pages):
            parsed = body_cache.get(sha)
            if parsed is not None and parsed.get('digest_ok', True):
                scan_pages.append((sha, parsed))

    for page_id, parsed in scan_pages:
        linked_known = [eid for eid in parsed['linked_event_ids'] if eid in meetings]
        if len(linked_known) != 1 or not parsed['editorial_video_ids']:
            continue
        eid = linked_known[0]
        m_title = meetings[eid]['title']
        m_rt = bool(ROUNDTABLE_RE.search(m_title))
        p_rt = bool(ROUNDTABLE_RE.search(parsed['clean_title'] + ' ' + ' '.join(parsed['headings'])))
        if p_rt != m_rt:
            continue
        for yt_id in parsed['editorial_video_ids']:
            vk = f'youtube:{yt_id}'
            dir_b_checked += 1
            if (eid, vk) not in published_cp_pairs:
                dir_b_missing.append(dict(page_id=page_id, event_id=eid, video_key=vk, page_title=parsed['title']))

    return dict(
        committee_page_rows=len(cp_rows),
        raw_pages_read=len(read_pages),
        raw_pages_unread=len(unread_pages),
        unread_pages=sorted(unread_pages),
        verdicts=dict(sorted(verdicts.items())),
        contradiction_counts=dict(sorted(contradictions.items())),
        contradiction_examples={k: v for k, v in sorted(examples.items())},
        direction_b=dict(
            basis_checked='committee_page',
            explicit_raw_pairs_checked=dir_b_checked,
            missing_from_published_count=len(dir_b_missing),
            missing_from_published=dir_b_missing[:max_examples],
        ),
        _row_verdicts=row_verdicts,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--release', required=True, help='Release directory containing recording_matches, meetings, and videos tables')
    parser.add_argument('--meetings', help='Optional override path to meetings table (parquet or json)')
    parser.add_argument('--mirror', help='Optional r2-immutable mirror directory holding bodies/sha256/<ab>/<sha>.gz')
    parser.add_argument('--raw-pages', help='Optional directory of raw HTML/JSON pages to check in Direction B (raw -> published)')
    parser.add_argument('--require-provenance', action='store_true', help='Flag committee_page rows missing a non-empty provenance note')
    parser.add_argument('--output', required=True, help='Output JSON report path')
    args = parser.parse_args(argv)

    rel = Path(args.release)
    matches_path = rel / ('recording_matches.parquet' if (rel / 'recording_matches.parquet').exists() else 'recording_matches.json')
    meetings_path = Path(args.meetings) if args.meetings else (rel / ('meetings.parquet' if (rel / 'meetings.parquet').exists() else 'meetings.json'))
    videos_path = rel / ('videos.parquet' if (rel / 'videos.parquet').exists() else 'videos.json')

    report = evaluate_release(
        matches_rows=_load_table(matches_path, ['match_id', 'event_id', 'video_key', 'basis', 'status', 'note', 'source_ref']),
        meetings_rows=_load_table(meetings_path, ['event_id', 'chamber', 'meeting_date', 'meeting_type', 'title', 'subject_keys']),
        videos_rows=_load_table(videos_path, ['video_key', 'title', 'source_description', 'stated_event_ids', 'published_at', 'video_published_at']),
        mirror=args.mirror,
        raw_pages_dir=args.raw_pages,
        require_provenance=args.require_provenance,
    )
    output_report = {k: v for k, v in report.items() if k != '_row_verdicts'}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output_report, indent=2, default=str))
    summary = {k: v for k, v in output_report.items() if k not in ('unread_pages', 'contradiction_examples')}
    print(json.dumps(summary, indent=2, default=str))
    return report


if __name__ == '__main__':
    main()
