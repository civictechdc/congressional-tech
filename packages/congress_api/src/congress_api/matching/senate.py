"""Exact source identifiers connect abbreviated or split official agendas."""

import re
from collections import defaultdict

from congress_api.matching.committees import codes_of
from congress_api.matching.recordings import bills
from congress_api.matching.senate_corrections import selected_date
from congress_api.parsers.senate_page import SITE

PACKAGE = re.compile(r'\bCHRG-(\d+)shrg(\d+)\b', re.I)

EXACT_METHOD = 'senate.records.match_identifiers'
FUZZY_METHOD = 'senate.records.match_pages'


def _event_method(page, event_id):
    return ((page.get('match_details') or {}).get(str(event_id)) or {}).get('method')


def _only_fuzzy_events(page):
    """True when every listed association is a fuzzy page match (safe to replace with exact)."""
    events = [str(event) for event in page.get('events') or []]
    return bool(events) and all(_event_method(page, event) == FUZZY_METHOD for event in events)


def match_identifiers(meetings, state):
    """Add only unique same-day, same-committee associations, retaining the proof.

    A native record can combine business and a hearing while the committee has
    separate pages for each. Exact transcript packages or a complete nonempty
    page bill list establish those component associations without fuzzy titles.
    Exact proof replaces a fuzzy-only ``events`` list; established exact (or
    unlabeled) associations stay put. Ties stay unresolved.
    """
    native = defaultdict(list)
    for meeting in meetings:
        if meeting.get('chamber') == 'House' or not meeting.get('date'):
            continue
        for code in codes_of(meeting):
            if host := SITE.get(code):
                native[host, meeting['date'][:10]].append(meeting)
    added = []
    for host, site in state.items():
        for url, page in site.get('pages', {}).items():
            event = page.get('event')
            if not event or page.get('absent') or page.get('status') == 'error':
                continue
            existing = [str(item) for item in page.get('events') or []]
            # Empty: add. Fuzzy-only: replace. Exact/unknown: leave alone (preserve-existing).
            if existing and not _only_fuzzy_events(page):
                continue
            page_bills = bills(event.get('title', ''))
            page_packages = {(int(match[0]), int(match[1])) for document in page.get('documents', []) for match in PACKAGE.findall(document[2])}
            matches = []
            for meeting in native[host, selected_date(url, event)]:
                native_bills = bills(meeting.get('title', ''))
                native_bills.update((str(bill['type']).upper(), str(bill['number'])) for bill in ((meeting.get('relatedItems') or {}).get('bills') or [])
                                    if bill.get('type') and bill.get('number') and int(bill.get('congress', meeting['congress'])) == int(meeting['congress']))
                native_packages = {(int(meeting['congress']), int(transcript['jacketNumber'])) for transcript in (meeting.get('hearingTranscript') or [])
                                   if str(transcript.get('jacketNumber', '')).isdigit()}
                shared_packages = page_packages & native_packages
                if shared_packages or (page_bills and page_bills <= native_bills):
                    matches.append((meeting, shared_packages, native_bills))
            if len(matches) != 1:
                continue
            meeting, packages, native_bills = matches[0]
            identifier = str(meeting['eventId'])
            reason = 'An exact Congress-specific transcript package appears in both sources.' if packages else 'Every bill identifier in the official page title appears in the native meeting agenda.'
            details = page.setdefault('match_details', {})
            for prior in existing:
                details.pop(prior, None)
            page['events'] = [identifier]
            details[identifier] = {
                'method': EXACT_METHOD, 'version': '1',
                'reason': reason, 'event_date': selected_date(url, event),
                'committee_codes': codes_of(meeting), 'native_event_id': identifier,
                'native_api_url': meeting.get('_url'), 'native_title': meeting.get('title'),
                'page_bill_ids': [list(bill) for bill in sorted(page_bills)], 'native_bill_ids': [list(bill) for bill in sorted(native_bills)],
                'shared_transcript_packages': [f'CHRG-{congress}shrg{jacket}' for congress, jacket in sorted(packages)],
            }
            added.append((url, identifier))
    return added
