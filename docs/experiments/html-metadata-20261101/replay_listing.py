"""Replay Senate event-row listings and compare the parser's days with mf2py's.

Usage: replay_listing.py listing-cohort.json BODIES_DIR  (bodies are <sha>.gz).
Rows and dates come from mf2py, a different parser family, not from the parser's own
DATE, written_day or <time> reading: an encoded start gives the day, and a row with
none is counted rather than compared. Exits 1 on any expected count that differs.
"""
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import mf2py

from congress_api.parsers.senate import parse_listing_details, parse_listing_page


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
    return counts


cohort = json.loads(Path(sys.argv[1]).read_text())
actual = replay(cohort, sys.argv[2])
print(json.dumps(dict(sorted(actual.items())), indent=1))
wrong = {name: (value, actual[name]) for name, value in cohort.get('expected', {}).items() if actual[name] != value}
if wrong:
    print('DIFFERS from expected (expected, actual):', wrong)
    sys.exit(1)
