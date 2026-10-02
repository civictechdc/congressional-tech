"""Select primary document wording without discarding literal labels.

The catalog owns spelling-to-category mappings. This module owns the distinction
between a document's genre, a topic it discusses and a more specific phrase.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from .metadata import target_subject_spans

EVENT_KINDS = frozenset({'business-meeting', 'nomination', 'field-hearing', 'panel-discussion'})
LEGISLATIVE_KINDS = frozenset({'amendment', 'committee-print', 'legislative-text', 'oversight-plan'})
TOPIC_KINDS = frozenset({'report', 'summary', 'response', 'rules-memorandum', 'chair-mark',
                         'mark-modification', 'business-meeting', 'nomination',
                         'tally-sheet', 'letter', 'exhibit', 'appendix', 'attachment',
                         'panelist-list', 'participant-list'}) | EVENT_KINDS

# Broad navigation groups, not new readings of a filename or its contents.
# Spell out membership: e.g. bill-comparison is not legislative text, and a
# conference-legislation-part is not a conference report. Unlisted kinds keep
# their own name until there is a deliberate reason to group them.
_FAMILY_MEMBERS = {
    'letter': ('letter-of-support',),
    'statement': ('opening-statement', 'member-statement', 'witness-statement', 'testimony',
                  'explanatory-statement'),
    'remarks': ('opening-remarks',),
    'transcript': ('committee-transcript',),
    'report': ('committee-report', 'committee-report-part', 'committee-report-unnumbered',
               'conference-report', 'conference-unnumbered', 'published-report'),
    'legislation': ('legislative-text', 'bill-named-draft', 'bill-numbered', 'bill-numbered-described',
                    'bill-preintroduced', 'bill-suspension-numbered', 'bill-titled-draft',
                    'bill-unnumbered', 'bill-untyped-draft', 'bill-untyped-numbered',
                    'appropriation-described', 'appropriation-routed', 'conference-legislation-part'),
    'amendment': ('amendment-collection', 'bill-house-amendment', 'committee-amendment',
                  'committee-amendment-described', 'committee-enbloc-described', 'committee-enbloc-numbered',
                  'floor-amendment', 'interchamber-amendment', 'managers-package', 'mark-modification'),
    'print': ('committee-print', 'published-print'),
    'list': ('amendment-list', 'exhibit-list', 'bill-measure-list', 'member-roster',
             'witness-list', 'panelist-list', 'participant-list'),
    'biography': ('witness-biography',),
    'memorandum': ('committee-memorandum', 'rules-memorandum'),
    'notice': ('meeting-notice',),
    'vote-record': ('committee-vote', 'tally-sheet'),
    'exhibit': ('exhibit-collection',),
    'supporting-material': ('support-document', 'meeting-support', 'witness-support'),
    'questions-and-answers': ('questionnaire', 'questions-for-record', 'questions-for-record-response'),
    'disclosure': ('testimony-disclosure',),
}
_KIND_FAMILIES = {kind: family for family, kinds in _FAMILY_MEMBERS.items() for kind in kinds}


def document_families(kinds: Iterable[str] | None) -> list[str]:
    """Group selected kinds; never infer a genre from a topic or relationship.

    Unknown kinds remain their own families. Missing kinds have no family.
    Multiple kinds may supply multiple families, with duplicates removed.
    """
    return sorted({_KIND_FAMILIES.get(kind, kind) for kind in kinds or ()})


def document_category_fields(filename: str | None, observations: list[dict]) -> list[dict]:
    """Return category-bearing fields that describe this document itself.

    Original observations are never changed. The same selection drives public
    kinds and subject trimming so a contextual label stays in the subject.
    """
    fields = [f for m in observations for f in m['fields'] if f.get('category')]
    targets = target_subject_spans(observations)
    titles = [(f['start'], f['end']) for m in observations for f in m['fields']
              if (m.get('scope') == 'legislative-payload' and f['name'] in {'descriptor', 'suffix'})
              or (m.get('scope') == 'legislative-text-search' and f['name'] == 'description')]
    # A publisher-qualified transcript prefix describes the document. Its
    # trailing title can discuss amendments, nominations or other documents
    # without making the transcript one of those things. Keep their literal
    # fields; exclude only their document-kind claims.
    transcript_subjects = [(f['start'], f['end']) for m in observations
                           if m.get('scope') == 'source-stem'
                           and any(part.get('category') == 'transcript' for part in m['fields'])
                           for f in m['fields'] if f['name'] in {'suffix', 'subject_token'}]
    candidates = []
    for field in sorted(fields, key=lambda f: (f['start'], -f['end'])):
        a, b, kind = field['start'], field['end'], field['category']
        if any(x <= a < b <= y for x, y in transcript_subjects):
            continue
        if field['name'] != 'amendment_marker' and any(x <= a < b <= y for x, y in targets):
            continue
        if (field['name'] in {'label', 'exhibit_marker', 'document_token', 'meeting_wording'} and kind not in LEGISLATIVE_KINDS
                and any(x <= a < b < y for x, y in titles)):
            continue
        # Long phrases own their nested generic wording, including QFR responses,
        # mark descriptions, opening statements and amendment/exhibit lists.
        if any(f['start'] <= a and b <= f['end'] and (a, b) != (f['start'], f['end'])
               and f['category'] != kind for f in fields):
            continue
        if any(f['category'].endswith('-' + kind) for f in fields):
            continue
        if filename is None:
            candidates.append(field)
            continue  # A supplied observation can be flattened without its source text.
        before, after = filename[:a], filename[b:]
        if kind == 'summary' and re.match(r'[ _-]+Judgments?(?![A-Za-z])', after, re.I):
            continue
        if kind == 'report' and re.match(r'(?:(?i:[ _-]+Cards?(?![A-Za-z]))|Cards?(?=[A-Z]|\b))', after):
            continue
        if kind == 'response' and re.search(
                r'(?:\b|_)(?:(?:Policy|US|U\.S\.|National|International|Emergency|Federal)[ _-]+'
                r'|(?:Preparedness|Prevention)[ ,_-]+(?:and[ _-]+)?)$', before, re.I):
            continue
        if kind == 'report' and re.search(r'(?:\b|_)(?:Hearing[ _-]+|Findings[ _-]+(?:in|from)[ _-]+)', before, re.I):
            continue
        if kind in TOPIC_KINDS and re.search(r'(?:\b|_)Hearing[ _-]+(?:on|about|concerning|examining)[ _-]+', before, re.I):
            continue
        if kind in TOPIC_KINDS and re.search(r'(?:\b|_)(?:Results?|Score)[ _-]+of[ _-]+', before, re.I):
            continue
        if kind == 'report' and any(
                f['category'] in {'transcript', 'testimony', 'statement', 'witness-statement', 'summary'}
                and not re.fullmatch(r'[ ,_-]*(?:and|&)[ ,_-]*',
                                     filename[min(b, f['end']):max(a, f['start'])], re.I)
                for f in fields):
            continue
        # A preceding genre followed by a topic/target connector governs this
        # wording. Adjacent genres and comma/and lists remain independent.
        if kind in TOPIC_KINDS and any(f['end'] <= a and re.match(r'[ _-]+(?:on|about|concerning|regarding|to|of)[ _-]+',
                                         filename[f['end']:a], re.I)
               for f in candidates if f['category'] not in EVENT_KINDS):
            continue
        candidates.append(field)

    # These adjacent phrases express "a summary of the package" and "a slide
    # containing a summary", not two independent document genres.
    refined = []
    for f in candidates:
        # A tally sheet records the vote on the preceding amendment or print.
        # Keep those literal fields, but do not call the tally sheet its target.
        if filename is not None and f['category'] in {'amendment', 'committee-print'} and any(
                other['category'] == 'tally-sheet' and f['end'] <= other['start']
                and not re.search(r'(?:^|[ _-])(?:and|&)(?:$|[ _-])',
                                  filename[f['end']:other['start']], re.I)
                for other in candidates):
            continue
        if filename is not None and any(f['end'] <= other['start'] and re.fullmatch(r'[ _-]+', filename[f['end']:other['start']])
               and (f['category'], other['category']) in {('managers-package', 'summary'), ('summary', 'slides')}
               for other in candidates):
            continue
        refined.append(f)
    return refined
