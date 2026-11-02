"""Fetch the listing rows HEARING_LINK used to miss and read each through event_details.

Usage: root_slug_pages.py PRIOR_REPLAY.json OUT.json  (public publisher pages, one at a time).
PRIOR_REPLAY.json holds those rows with the day written on each. The written-date check is
a plain regex on the page, separate from DATE and written_day.
"""
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

from congress_api.parsers.senate_page import event_details

WRITTEN = re.compile(r'<b>Date:\s*</b>\s*\w+, (\w+ \d{1,2}, \d{4})')
rows = json.loads(Path(sys.argv[1]).read_text())['listing_absent_rows']
results = []
for row in rows:
    url = row['url'].replace('https://', 'https://www.', 1)
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status, page = response.status, response.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as error:
        status, page = error.code, ''
    event = event_details(page, url) if page else None
    written = WRITTEN.search(page)
    raw_day = datetime.strptime(written[1], '%B %d, %Y').date().isoformat() if written else None
    results.append(dict(url=url, status=status, listing_row_day=row['raw_row_day'], raw_page_day=raw_day, event_day=event and event['date'],
                        event_title=event and event['title'], reason=None if event else 'not_found' if status == 404 else f'http_{status}'))
    print(status, row['raw_row_day'], raw_day, event and event['date'], url[-48:])
    time.sleep(1)
Path(sys.argv[2]).write_text(json.dumps(results, indent=1) + '\n')
