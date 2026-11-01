"""Replay the Senate event-row cohort through the listing parsers.

Usage: replay_listing.py listing-cohort.json BODIES_DIR  (bodies are <sha>.gz).
Rows are read here independently of the parsers (plain DOM), and cross-checked with
extruct's microformat reader, a different parser family. Expected counts are in the
cohort file; the program exits 1 when any differs.
"""
import gzip
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import extruct
from lxml import html as dom

from congress_api.parsers.senate import parse_listing_details, parse_listing_page
from congress_api.parsers.senate_page import DATE, written_day

EVENT = 'contains(concat(" ",normalize-space(@class)," ")," vevent ") or contains(concat(" ",normalize-space(@class)," ")," h-event ")'


def key(url):
    parts = urlsplit(url)
    return parts.netloc.removeprefix('www.'), parts.path, parts.query


def replay(cohort, bodies):
    counts = Counter()
    for entry in cohort['bodies']:
        raw = gzip.decompress((Path(bodies) / f"{entry['sha']}.gz").read_bytes())
        page = raw.decode('utf-8')
        site = urlsplit(entry['declared']).netloc.removeprefix('www.')
        listed = {}
        for day, url, _ in parse_listing_page(page, site):
            listed.setdefault(key(url), []).append(str(day))
        details = {key(url): value for url, value in parse_listing_details(page, site).items()}
        events = [event for event in extruct.extract(raw, base_url=None, syntaxes=['microformat'], errors='strict')['microformat']
                  if 'h-event' in event.get('type', [])]
        rows = dom.fromstring(raw).xpath(f'//*[{EVENT}]')
        counts['extruct_row_count_differs'] += len(events) != len(rows)
        for row in rows:
            counts['rows'] += 1
            href = row.xpath('.//a[@href]')[0].get('href')
            time = row.xpath('.//time')[0]
            day = next((str(written_day(m)) for m in DATE.finditer(time.text_content()) if written_day(m)), None)
            found = key(urljoin(entry['declared'], href))
            counts['rows_with_room_in_dom'] += bool(row.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," location ")]'))
            detail = details.get(found, {})
            if found not in listed:
                counts['listing_absent'] += 1
            else:
                counts['matched'] += 1
                counts['matched_wrong_day'] += listed[found][-1] != day
            if detail.get('time'):
                counts['details_rows_with_time'] += 1
            counts['evidence:' + str(detail.get('time_evidence'))] += 1
    return counts


cohort = json.loads(Path(sys.argv[1]).read_text())
actual = replay(cohort, sys.argv[2])
print(json.dumps(dict(sorted(actual.items())), indent=1))
wrong = {name: (value, actual[name]) for name, value in cohort['expected'].items() if actual[name] != value}
if wrong:
    print('DIFFERS from expected (expected, actual):', wrong)
    sys.exit(1)
