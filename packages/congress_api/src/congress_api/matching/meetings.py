"""Shared interpretation of meeting facts, independent of storage and adapters.

Type and access return the source field used so callers can retain evidence.
Matching thresholds and recording-title hints stay with their own matchers;
they do not establish what kind of proceeding occurred or who could attend.
"""

import re

HEARING_TYPES = frozenset({"hearing", "field_hearing"})


def meeting_type(row):
    """Return (normalized type, source field); explicit publisher types win."""
    text = ' '.join(str(row.get('type') or '').lower().split())
    for label, kind in (('field hearing', 'field_hearing'), ('business meeting', 'business'),
                        ('hearing', 'hearing'), ('markup', 'markup'), ('briefing', 'briefing'),
                        ('roundtable', 'roundtable')):
        if label in text: return kind, '/type'
    if text in ('', 'meeting'):
        title = ' '.join(str(row.get('title') or '').lower().split())
        # Classify the proceeding named at the beginning, not a later agenda
        # item or a second event following a semicolon.
        prefix = (r'^\W*(?:(?:rescheduled|postponed|cancell?ed)\s*:\s*)?'
                  r'(?:(?:to\s+)?(?:receive|received|hold)\s+)?(?:(?:an?|the)\s+)?'
                  r'(?:(?:open|closed|joint|oversight|legislative|public|full|committee|subcommittee|members?|and)\s+)*')
        hearing = r'hearings?(?=\s*(?:$|[:“"\']|\b(?:on|to|with|of|entitled|titled)\b))'
        for pattern, kind in ((r'field\s+' + hearing, 'field_hearing'),
                              (r'business\s+meeting\b', 'business'), (r'briefings?\b', 'briefing'),
                              (r'mark[\s-]?up\b', 'markup'), (hearing, 'hearing')):
            if re.search(prefix + pattern, title): return kind, '/title'
        # Committee names sometimes precede the business-meeting label.
        # A resolution merely authorizing a later event is not that event.
        if not re.match(r'^(?:to\s+)?(?:consider|resolution)\b', title) and re.search(r'\bbusiness meeting\b', title.split(';', 1)[0]):
            return 'business', '/title'
    if text == 'meeting':
        return 'meeting', '/type'
    return 'unknown', '/type'


def meeting_access(row):
    """Keep explicit native access, otherwise use explicit title phrases only."""
    native = str(row.get('type') or '').lower()
    reported = {value for value in ('open', 'closed') if re.search(r'\b' + value + r'\b', native)}
    if reported:
        return ('partly_closed' if len(reported) == 2 else reported.pop()), '/type'
    title = ' '.join(str(row.get('title') or '').lower().split())
    # Possibility is not a declaration that a closed portion will occur.
    title = re.sub(r'\b(?:possibility of|possibly|may (?:be|go into|hold))\s+(?:an?\s+)?(?:closed|open)\s+(?:session|hearing|meeting)\b', '', title)
    event = r'(?:hearings?|briefings?|(?:business\s+)?meetings?|mark[ -]?up(?:\s+sessions?)?|sessions?|panels?|roundtables?)'
    if re.search(r'\b(?:open\s*(?:and|&|/)\s*closed|closed\s*(?:and|&|/)\s*open)(?=\s*(?:[\])]|' + event + r'\b))', title):
        return 'partly_closed', '/title'
    found, primary = set(), set()
    subsequent = re.search(r'\b(?:followed|preceded)\s+by\b', title)
    for access in ('open', 'closed'):
        marker = r'[\[(]\s*' + access + r'\s*(?:[\])]|(?:session|hearing|briefing)\b|in a closed space\b|-\s*possibility of closing\b)'
        phrase = r'\b' + access + r'\s+(?:joint\s+)?' + event + r'\b'
        declaration = r'\b' + event + r'\s+(?:is\s+|will be\s+)?' + access + r'\b|^\W*' + access + r'\s+to (?:the )?public\b'
        matches = [match for pattern in (marker, phrase, declaration) for match in re.finditer(pattern, title)]
        if matches:
            found.add(access)
            if subsequent is None or any(match.start() < subsequent.start() for match in matches):
                primary.add(access)
    if len(found) == 2:
        return 'partly_closed', '/title'
    # A later closed session alone does not establish access to the main event.
    if primary:
        return primary.pop(), '/title'
    return 'unknown', None


def is_hearing(row):
    """Both ordinary and field hearings can have witness lists."""
    return meeting_type(row)[0] in HEARING_TYPES


NOT_HELD = re.compile(r"^\s*(postponed|cancel+ed|rescheduled|test)\b", re.I)


TRANSCRIPT = re.compile(r"transcript", re.I)


def scheduled_or_rescheduled(row):
    """Scheduled and rescheduled meetings, with no congress floor."""
    return row.get("meetingStatus") in ("Scheduled", "Rescheduled")


def in_inventory_scope(row):
    """The retained inventory and print matcher share this collection scope."""
    return scheduled_or_rescheduled(row) and int(row.get("congress", 0)) >= 113
