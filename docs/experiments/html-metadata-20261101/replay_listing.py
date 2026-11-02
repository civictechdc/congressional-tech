"""Replay Senate event-row listings against two independent readings of the same bytes.

Usage: replay_listing.py listing-cohort.json [OUT.json]  (bodies by digest via raw_bodies).
mf2py is a different parser family; a row with no encoded start is counted, not compared.
The raw reading is a plain regex over the row's bytes and shares nothing with the
parser's DATE, written_day or DOM. Exits 1 on any expected count that differs.
"""
from html import unescape
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import mf2py

from congress_api.parsers.senate import parse_listing_details, parse_listing_page
from congress_api.parsers.senate_page import HEARING_LINK
from raw_bodies import read_body

RAW_ROW = re.compile(r'<tr\b[^>]*class="[^"]*\bvevent\b[^"]*"[^>]*>(.*?)</tr>', re.S)
RAW_HREF = re.compile(r'<a\b[^>]*href="([^"]+)"')
RAW_TIME = re.compile(r'<time\b[^>]*>\s*(\d\d)[/.](\d\d)[/.](\d\d)\b')


def key(url):
    parts = urlsplit(url)
    return parts.netloc.removeprefix('www.'), parts.path, parts.query


def replay(cohort):
    counts, fallback = Counter(), []
    for entry in cohort['bodies']:
        raw, source = read_body(entry['sha'])
        counts['raw_bodies_read:' + source] += 1
        page = raw.decode('utf-8')
        site = urlsplit(entry['declared']).netloc.removeprefix('www.')
        listed = {}
        rows = parse_listing_page(page, site)
        for day, url, _ in rows:
            listed.setdefault(key(url), []).append(str(day))
        details = {key(url): value for url, value in parse_listing_details(page, site).items()}
        for event in mf2py.parse(doc=page, url=entry['declared'])['items']:
            if 'h-event' not in event['type']:
                continue
            counts['rows'] += 1
            found = key(event['properties']['url'][0])
            start = (event['properties'].get('start') or [''])[0]
            counts['evidence:' + str(details.get(found, {}).get('time_evidence'))] += 1
            counts['details_rows_with_time'] += bool(details.get(found, {}).get('time'))
            if found not in listed:
                counts['listing_absent'] += 1
            elif not re.match(r'\d{4}-\d{2}-\d{2}', start):
                counts['matched_no_encoded_day'] += 1
            else:
                counts['matched'] += 1
                counts['matched_wrong_day'] += listed[found][-1] != start[:10]
        written = {}
        for row in RAW_ROW.findall(page):
            href, time = RAW_HREF.search(row), RAW_TIME.search(row)
            counts['raw_rows'] += 1
            if not href or not time:
                counts['raw_rows_unread'] += 1
                continue
            written[key(urljoin(entry['declared'], unescape(href[1])))] = f'20{time[3]}-{time[1]}-{time[2]}'
        counts['raw_wrong_day'] += sum(found in written and listed[found][-1] != written[found] for found in listed)
        for day, url, title in rows:
            if HEARING_LINK.search(f'<a href="{url.split(site, 1)[-1]}">x</a>') is None:
                counts['fallback_rows'] += 1
                row_day = written.get(key(url))
                counts['fallback_wrong_day'] += row_day != str(day)
                fallback.append(dict(listing=entry['sha'], url=url, parser_day=str(day), raw_row_day=row_day))
    return counts, fallback


cohort = json.loads(Path(sys.argv[1]).read_text())
actual, fallback = replay(cohort)
print(json.dumps(dict(sorted(actual.items())), indent=1))
if len(sys.argv) > 2:
    Path(sys.argv[2]).write_text(json.dumps(dict(counts=dict(sorted(actual.items())), fallback_rows=fallback), indent=1) + '\n')
wrong = {name: (value, actual[name]) for name, value in cohort.get('expected', {}).items() if actual[name] != value}
if wrong:
    print('DIFFERS from expected (expected, actual):', wrong)
    sys.exit(1)
