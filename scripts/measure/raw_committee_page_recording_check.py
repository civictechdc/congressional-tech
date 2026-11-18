"""Independent raw check of published committee_page recording matches (ct-414r).

    raw_committee_page_recording_check.py --release DIR [--mirror R2_IMMUTABLE] --output OUT.json [--require-provenance]

Judges committee_page matches using raw HTML bytes (re-hashed against the SHA-256 in source_ref)
and independent signals the page-date linker does not inspect:
  1. Direction A (published -> raw):
     - Raw HTML byte integrity and presence of the claimed video ID in the raw HTML.
     - Independent proceeding-kind check (roundtable vs hearing/markup) across raw HTML
       title/heading, video title, and meeting title.
     - Explicit House EventID references (in raw HTML links and video metadata) compared against
       both the linked meeting and the referenced meeting.
     - Independent calendar-date check comparing video title dates and upload timestamps against
       meeting_date.
     - Provenance note presence and source_ref format on committee_page rows.
  2. Direction B (raw -> published):
     - For every readable raw HTML body on disk (or in --raw-pages) that explicitly links to a
       known House meeting via docs.house.gov or congress.gov and embeds a YouTube video ID,
       verify that (event_id, video_key) is published in recording_matches.

Every cited page body that cannot be read from the mirror is named in unread_pages rather than
assumed valid.
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
    r'(?:docs\.house\.gov/[^"\'\s<>]*?[?&]EventID=|congress\.gov/event/\d+/house-event/)(\d{5,7})\b',
    re.I,
)
EXPLICIT_EVENT_ID_RE = re.compile(r'(?:\bevent\s*id|\bid)\s*[=:#]\s*(1\d{5})\b', re.I)
ROUNDTABLE_RE = re.compile(r'\broundtable\b', re.I)
HEARING_OR_MARKUP_RE = re.compile(r'\b(?:hearing|markup)\b', re.I)
SHA64_RE = re.compile(r'^[0-9a-f]{64}$')

MONTHS = {
    'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
    'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6, 'jul': 7, 'july': 7,
    'aug': 8, 'august': 8, 'sep': 9, 'sept': 9, 'september': 9,
    'oct': 10, 'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12,
}

# Lightweight independent English function-word list (not copied from any model file).
BASIC_STOP = {
    'the', 'and', 'for', 'with', 'from', 'that', 'this', 'into', 'over', 'under', 'about',
    'hearing', 'hearings', 'subcommittee', 'committee', 'house', 'united', 'states', 'congress',
    'full', 'open', 'closed', 'public', 'session', 'meeting', 'markup', 'business', 'legislative',
    'oversight', 'review', 'examining', 'examine', 'part', 'titled', 'entitled', 'act', 'bill', 'bills',
}


class _RawHtmlReader(HTMLParser):
    """Minimal stdlib HTML extractor for title, first heading, links, embeds, and visible text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._stack = []
        self._skip_depth = 0
        self._title_parts = []
        self._h1_parts = []
        self._in_title = False
        self._in_h1 = False
        self._got_h1 = False
        self.hrefs = []
        self.video_ids = set()

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr_map = dict(attrs)
        if tag in {'script', 'style', 'noscript', 'svg'}:
            self._skip_depth += 1
        elif tag == 'title' and not self._title_parts:
            self._in_title = True
        elif tag in {'h1', 'h2'} and not self._got_h1 and not self._h1_parts:
            self._in_h1 = True
        for key in ('href', 'src', 'data-src', 'content'):
            val = attr_map.get(key)
            if not val:
                continue
            self.hrefs.append(val)
            for vid in YOUTUBE_URL_RE.findall(val):
                self.video_ids.add(vid)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {'script', 'style', 'noscript', 'svg'} and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == 'title':
            self._in_title = False
        elif tag in {'h1', 'h2'} and self._in_h1:
            self._in_h1 = False
            self._got_h1 = True

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title_parts.append(data)
        if self._in_h1:
            self._h1_parts.append(data)

    @property
    def title(self):
        return re.sub(r'\s+', ' ', ''.join(self._title_parts)).strip()

    @property
    def heading(self):
        return re.sub(r'\s+', ' ', ''.join(self._h1_parts)).strip()


def parse_raw_html(raw_bytes):
    text = raw_bytes.decode('utf-8', 'replace')
    reader = _RawHtmlReader()
    reader.feed(text)
    reader.close()
    video_ids = set(reader.video_ids)
    video_ids.update(YOUTUBE_URL_RE.findall(text))
    linked_events = {int(m) for m in HOUSE_EVENT_URL_RE.findall(text)}
    text_events = {int(m) for m in EXPLICIT_EVENT_ID_RE.findall(reader.title + ' ' + reader.heading)}
    return dict(
        title=reader.title,
        heading=reader.heading,
        video_ids=sorted(video_ids),
        linked_event_ids=sorted(linked_events),
        title_event_ids=sorted(text_events),
    )


def read_mirror_body(mirror, sha):
    """Read raw bytes for a 64-hex SHA-256 from mirror and verify the digest."""
    if not mirror or not sha or not SHA64_RE.match(sha):
        return None, None
    base = Path(mirror) / 'bodies' / 'sha256' / sha[:2]
    for suffix in ('.gz', '', '.html'):
        path = base / (sha + suffix)
        if path.is_file():
            raw = path.read_bytes()
            body = gzip.decompress(raw) if suffix == '.gz' else raw
            actual = sha256(body).hexdigest()
            return body, (actual == sha)
    return None, None


def content_tokens(text):
    return {t for t in re.findall(r'[a-z0-9]{3,}', (text or '').lower()) if t not in BASIC_STOP}


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
            meetings[int(eid)] = dict(
                event_id=int(eid),
                chamber=row.get('chamber'),
                meeting_date=parse_iso_date(row.get('meeting_date')),
                meeting_type=row.get('meeting_type'),
                title=row.get('title') or '',
                subject_keys=list(row.get('subject_keys') or []),
            )

    videos = {}
    for row in videos_rows:
        vk = row.get('video_key')
        if vk:
            videos[vk] = dict(
                video_key=vk,
                title=row.get('title') or '',
                source_description=row.get('source_description') or '',
                stated_event_ids=[int(x) for x in (row.get('stated_event_ids') or []) if x is not None],
                video_date=parse_iso_date(row.get('video_published_at') or row.get('published_at')),
            )

    published_pairs = set()
    cp_rows = []
    for row in matches_rows:
        eid = row.get('event_id')
        vk = row.get('video_key')
        if eid is not None and vk and row.get('status') in ('asserted', 'claimed', 'decided'):
            published_pairs.add((int(eid), vk))
        if row.get('basis') == 'committee_page':
            cp_rows.append(row)

    # Cache parsed raw HTML bodies so each SHA is decompressed and parsed at most once.
    html_cache = {}
    unread_pages = set()
    read_pages = set()

    def get_page(sha):
        if sha in html_cache:
            return html_cache[sha]
        body, digest_ok = read_mirror_body(mirror, sha)
        if body is None:
            unread_pages.add(sha)
            html_cache[sha] = None
            return None
        read_pages.add(sha)
        parsed = parse_raw_html(body)
        parsed['digest_ok'] = digest_ok
        html_cache[sha] = parsed
        return parsed

    contradictions = Counter()
    examples = defaultdict(list)
    verdicts = Counter()

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

        if require_provenance and not (note and str(note).strip()):
            row_flags.append('missing_provenance_note')
            flag('missing_provenance_note', row, {'note': note})

        page = get_page(sha) if sha else None
        if page is not None:
            if not page['digest_ok']:
                row_flags.append('raw_html_digest_mismatch')
                flag('raw_html_digest_mismatch', row, {'sha': sha})
            if vk and vk.startswith('youtube:'):
                yt_id = vk.split(':', 1)[1]
                if yt_id not in page['video_ids']:
                    row_flags.append('video_not_in_raw_html')
                    flag('video_not_in_raw_html', row, {'expected_youtube_id': yt_id, 'found_ids': page['video_ids'][:10]})
            page_explicit_events = sorted(set(page['linked_event_ids']) | set(page['title_event_ids']))
            if eid is not None and page_explicit_events and int(eid) not in page_explicit_events:
                row_flags.append('raw_html_event_link_conflict')
                flag('raw_html_event_link_conflict', row, {'explicit_event_ids': page_explicit_events})

        meeting = meetings.get(int(eid)) if eid is not None else None
        video = videos.get(vk) if vk else None

        if meeting is not None:
            m_title = meeting['title']
            m_rt = bool(ROUNDTABLE_RE.search(m_title))
            m_toks = content_tokens(m_title + ' ' + ' '.join(meeting['subject_keys']))
            p_title = ((page or {}).get('title') or '') + ' ' + ((page or {}).get('heading') or '')
            p_rt = bool(ROUNDTABLE_RE.search(p_title))
            v_title = (video or {}).get('title') or ''
            v_rt = bool(ROUNDTABLE_RE.search(v_title))
            v_hm = bool(HEARING_OR_MARKUP_RE.search(v_title))

            if (p_rt or v_rt) and not m_rt:
                row_flags.append('roundtable_kind_conflict')
                flag('roundtable_kind_conflict', row, {'meeting_title': m_title, 'video_title': v_title, 'page_title': p_title.strip()})
            elif m_rt and v_hm and not v_rt:
                row_flags.append('roundtable_kind_conflict')
                flag('roundtable_kind_conflict', row, {'meeting_title': m_title, 'video_title': v_title})

            if video is not None:
                v_toks = content_tokens(v_title)
                cand_overlap = len(v_toks & m_toks)
                # Independent stated event ID contradiction: video states a different event whose title strongly matches the video.
                stated = [se for se in video['stated_event_ids'] if se != int(eid)]
                if stated and int(eid) not in video['stated_event_ids']:
                    best_other = None
                    for se in stated:
                        sm = meetings.get(se)
                        if sm is None:
                            continue
                        s_toks = content_tokens(sm['title'] + ' ' + ' '.join(sm['subject_keys']))
                        ov = len(v_toks & s_toks)
                        if best_other is None or ov > best_other[1]:
                            best_other = (se, ov, sm['title'])
                    if best_other is not None and ((cand_overlap == 0 and best_other[1] >= 2) or (cand_overlap <= 1 and best_other[1] >= 4)):
                        other_m = meetings.get(best_other[0])
                        # Calendar-date cross-check: if the video's upload date matches this meeting within 2 days
                        # while the stated meeting is >14 days away and the video title is just a subcommittee label
                        # ("Oversight Hearing | ... Subcommittee"), treat the stated EventID as a stale description copy.
                        stale_subcmte = (
                            '|' in v_title
                            and 'subcommittee' in v_title.lower()
                            and video['video_date'] is not None
                            and meeting['meeting_date'] is not None
                            and other_m is not None
                            and other_m['meeting_date'] is not None
                            and abs((video['video_date'] - meeting['meeting_date']).days) <= 2
                            and abs((video['video_date'] - other_m['meeting_date']).days) > 14
                        )
                        if not stale_subcmte:
                            row_flags.append('conflicting_stated_event_id')
                            flag('conflicting_stated_event_id', row, {
                                'video_title': v_title,
                                'meeting_title': m_title,
                                'stated_event_id': best_other[0],
                                'stated_meeting_title': best_other[2],
                                'cand_overlap': cand_overlap,
                                'stated_overlap': best_other[1],
                            })

                # Independent calendar date contradiction: explicit date in video title disagrees sharply with meeting_date.
                if meeting['meeting_date'] is not None:
                    title_date = extract_explicit_date(v_title)
                    if title_date is not None and abs((title_date - meeting['meeting_date']).days) > 7 and cand_overlap == 0:
                        row_flags.append('video_date_contradiction')
                        flag('video_date_contradiction', row, {
                            'meeting_date': str(meeting['meeting_date']),
                            'video_title_date': str(title_date),
                            'video_title': v_title,
                            'meeting_title': m_title,
                        })

        if row_flags:
            verdicts['raw_contradicts'] += 1
        elif page is None:
            verdicts['unread_body_no_metadata_contradiction'] += 1
        else:
            verdicts['raw_supports'] += 1

    # Direction B (raw -> published): check explicit raw HTML pages that link both a known House meeting and a YouTube video.
    dir_b_checked = 0
    dir_b_missing = []
    scan_pages = []
    if raw_pages_dir is not None:
        for path in sorted(Path(raw_pages_dir).rglob('*')):
            if path.is_file():
                raw = path.read_bytes()
                body = gzip.decompress(raw) if path.suffix == '.gz' else raw
                scan_pages.append((path.name, parse_raw_html(body)))
    else:
        for sha in sorted(read_pages):
            parsed = html_cache.get(sha)
            if parsed is not None and parsed.get('digest_ok', True):
                scan_pages.append((sha, parsed))

    for page_id, parsed in scan_pages:
        linked_known = [eid for eid in parsed['linked_event_ids'] if eid in meetings]
        if len(linked_known) != 1 or not parsed['video_ids']:
            continue
        eid = linked_known[0]
        m_title = meetings[eid]['title']
        m_rt = bool(ROUNDTABLE_RE.search(m_title))
        p_rt = bool(ROUNDTABLE_RE.search(parsed['title'] + ' ' + parsed['heading']))
        if p_rt != m_rt:
            continue
        for yt_id in parsed['video_ids']:
            vk = f'youtube:{yt_id}'
            dir_b_checked += 1
            if (eid, vk) not in published_pairs:
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
            explicit_raw_pairs_checked=dir_b_checked,
            missing_from_published_count=len(dir_b_missing),
            missing_from_published=dir_b_missing[:max_examples],
        ),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--release', required=True, help='Release directory containing recording_matches, meetings, and videos tables')
    parser.add_argument('--meetings', help='Optional override path to meetings table (parquet or json)')
    parser.add_argument('--mirror', help='Optional r2-immutable mirror directory holding bodies/sha256/<ab>/<sha>.gz')
    parser.add_argument('--raw-pages', help='Optional directory of raw HTML pages to check in Direction B (raw -> published)')
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
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))
    summary = {k: v for k, v in report.items() if k not in ('unread_pages', 'contradiction_examples')}
    print(json.dumps(summary, indent=2, default=str))
    return report


if __name__ == '__main__':
    main()
