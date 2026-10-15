"""Literal House XML codes and publisher labels, independent of output categories.

A meaning identifies the publisher's document type. Consumers map these meanings
into their own coarse meeting categories or detailed retained-file kinds.
"""

import re
from functools import lru_cache

DOCUMENT_TYPE_MEANINGS = {
    alias.casefold(): kind
    for kind, aliases in [
        ("witness-statement", ("Witness Statement", "WS")),
        ("testimony-disclosure", ("Witness Truth in Testimony", "truth in testimony", "WT")),
        ("witness-biography", ("Witness Biography", "WB")),
        ("witness-support", ("Witness Support Document", "WD")),
        ("member-statement", ("Member Statement", "Member Statements", "MS")),
        ("committee-amendment", ("Committee Amendment", "CA")),
        ("interchamber-amendment", ("House or Senate Amendment", "HA")),
        ("floor-amendment", ("Floor Amendment", "FA")),
        ("committee-vote", ("Committee Recorded Vote", "CV")),
        ("committee-report", ("Committee Report", "CR")),
        ("conference-report", ("Conference Report", "FR")),
        ("legislative-text", ("Bills and Resolutions", "BR", "legislative text")),
        ("summary", ("summary",)),
        ("support-document", ("Support Document", "SD")),
        ("transcript", ("Hearing: Transcript", "transcript", "HT")),
        ("witness-list", ("Hearing: Witness List", "witness list", "HW")),
        ("questions-for-record", ("Hearing: Questions for the Record", "questions for the record", "HQ")),
        ("member-roster", ("Hearing: Member Roster", "HM")),
        ("cover-page", ("Hearing: Cover Page", "HC")),
        ("table-of-contents", ("Hearing: Table of Contents", "TC")),
        ("questionnaire", ("questionnaire",)),
    ]
    for alias in aliases
}


def document_type(value: object) -> str | None:
    """Return a recognized literal meaning; titles and filenames are not evidence here."""
    if not isinstance(value, str):
        return None
    return DOCUMENT_TYPE_MEANINGS.get(' '.join(value.split()).casefold())


@lru_cache(maxsize=8192)
def document_label_kind(label: str) -> str | None:
    """Read an explicit document-link designation, not arbitrary topic wording.

    XML abbreviations are not free-text labels. Callers must establish that the
    label belongs to this document and keep conflicting occurrences separate.
    """
    value = ' '.join(label.replace('_', ' ').split()).casefold().strip(' :»')
    value = re.sub(r'\s*\[(?:pdf|docx?)\]$', '', value).strip()
    value = re.sub(r'^(?:download (?:the )?|click here for (?:the )?)', '', value)
    if len(value) > 2 and (kind := document_type(value)):
        return kind
    labels = {
        'testimony': 'testimony', 'written testimony': 'testimony',
        'witness testimony': 'witness-statement',
        'written statement': 'statement', 'prepared statement': 'statement',
        'statement': 'statement', 'written remarks': 'remarks',
        'opening statement': 'opening-statement', 'opening statements': 'opening-statement',
        'opening remarks': 'opening-remarks',
        'preliminary transcript': 'transcript', 'hearing transcript': 'transcript',
        'official transcript': 'transcript', 'printed hearing text': 'transcript',
        'a preliminary transcript of this hearing is now available.': 'transcript',
        'a transcript of this hearing is now available.': 'transcript',
        'hearing memo': 'committee-memorandum', 'official hearing memo': 'committee-memorandum',
        'hearing memorandum': 'committee-memorandum', 'markup memo': 'committee-memorandum',
        'markup memorandum': 'committee-memorandum', 'committee memo': 'committee-memorandum',
        'background memo': 'committee-memorandum', 'briefing memo': 'committee-memorandum',
        'summary of subject matter': 'committee-memorandum',
        'hearing charter': 'hearing-charter',
        'hearing notice': 'meeting-notice', 'meeting notice': 'meeting-notice',
        'hearing advisory': 'meeting-notice',
        'official hearing notice': 'meeting-notice',
        'updated: subcommittee hearing notice': 'meeting-notice',
        'full committee hearing notice': 'meeting-notice', 'subcommittee hearing notice': 'meeting-notice',
        'subcommittee hearing witness list': 'witness-list', 'full committee hearing witness list': 'witness-list',
        'truth in testimony form': 'testimony-disclosure', 'truth in testifying': 'testimony-disclosure',
        'witness disclosure': 'testimony-disclosure', 'witness disclosure form': 'testimony-disclosure',
        'amendment text': 'amendment', 'amendment': 'amendment',
        'roll call': 'committee-vote', 'roll call vote': 'committee-vote',
        'recorded vote': 'committee-vote', 'vote tally': 'committee-vote',
    }
    if value in labels:
        return labels[value]
    # Numbered amendment designations identify the document itself. Vote
    # outcomes, summaries and reports about amendments are different documents.
    if (not re.search(r'\b(?:vote|voting|tally|report|summary|description)\b', value)
            and re.fullmatch(
                r'amendment\s*#?\s*\d+[a-z]?(?:\s+to\s+(?:h\.?r\.?|s\.?)\s*\d+)?'
                r'\s+(?:offered\s+)?by\s+(?:mr\.?|ms\.?|mrs\.?|rep\.?)\s+[^.!?]+', value)):
        return 'amendment'
    # Speaker role is explicit in these labels; surnames alone supply no kind.
    if (re.fullmatch(r'(?:prepared )?(?:opening )?statement\s*-\s*ranking member .+', value)
            or re.fullmatch(r'(?:prepared )?opening statement (?:of|from) .+', value)
            or re.fullmatch(r'(?:full committee )?(?:ranking member|chairman|chairwoman) .+ opening statement', value)):
        return 'opening-statement' if 'opening' in value else 'member-statement'
    if re.fullmatch(r'memorandum from (?:ranking member|chairman|chairwoman) .+', value):
        return 'committee-memorandum'
    return None
