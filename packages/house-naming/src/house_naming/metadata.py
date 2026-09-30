"""Derive metadata only inside known filename fields, retaining their raw text."""
from __future__ import annotations

import re
from functools import lru_cache
from .errors import NamingError

NUMBER_BOUNDARY_NOTE = (
    'Digits adjoin ordinal wording; their division into a measure number and '
    'a title or reference number is not established.'
)


def starts_with_ordinal_suffix(description: str) -> bool:
    """Recognize an ordinal tail without confusing the, Stephen or Third."""
    return bool(re.match(
        r'(?:st|nd|rd|th)(?=[A-Z]|[ _-]|$)'
        r'|(?i:st|nd|rd|th)(?=(?i:Congress|Century))', description, re.ASCII))


@lru_cache(maxsize=1)
def _reference_patterns(measures: tuple[str, ...]) -> tuple[re.Pattern, ...]:
    codes = '|'.join(map(re.escape, measures))
    # A following ordinal is especially dangerous: HR575921stCentAct does
    # not establish HR 575921. Only documented boundaries/suffix shapes qualify.
    measure = re.compile(
        r'(?<![A-Za-z0-9])(?P<code>(?i:' + codes + r'))[-_]?(?P<number>[0-9]{1,10})'
        r'(?!(?i:st|nd|rd|th)(?:[A-Za-z]|$))'
        r'(?=$|[-_]|[A-Z]|(?i:asamended|amendment|rev[0-9])|(?i:a|b|q|r|sa)(?:$|[-_]))', re.ASCII)
    print_ref = re.compile(r'(?<![A-Za-z0-9])RCP(?P<congress>[1-9][0-9]{2})-'
                           r'(?P<number>[0-9]{1,10})(?=$|[-_])', re.I | re.ASCII)
    year = re.compile(r'(?<![A-Za-z0-9])FY(?P<year>[0-9]{4}|[0-9]{2})(?![0-9])', re.I | re.ASCII)
    return measure, print_ref, year


def _references(record: dict, measures: tuple[str, ...]) -> list[dict]:
    """Extract literal references only inside eligible, already assigned slots."""
    measure, print_ref, year = _reference_patterns(measures)
    result = []
    # The entire slot is schema-checked as adjacent measure tokens. Ordinary
    # prose still requires word boundaries; HR1HR2 is allowed only in this slot.
    for hit in re.finditer('(' + '|'.join(map(re.escape, measures)) + r')([0-9]+)',
                           record.get('measureList', ''), re.I | re.ASCII):
        number = int(hit[2])
        if not 0 < number <= 2147483647:
            raise NamingError('invalid-measure-reference', 'A measure in the reference list is outside the supported numeric bounds')
        result.append({'type': 'measure', 'measureType': hit[1].lower(), 'measureNumber': number,
                       'raw': hit[0], 'sourceField': 'measureList', 'start': hit.start(), 'end': hit.end()})
    for field in ('subject', 'descriptionRemainder', 'description', 'versionSuffix', 'voteId', 'amendmentId'):
        value = record.get(field)
        if not value:
            continue
        if field == 'description' and record['kind'] in {'appropriation-described', 'appropriation-routed'}:
            # The AP/FY routing year already has a role. Descriptive references
            # are found in subject/remainder, never used to backfill that slot.
            continue
        hits = []
        for hit in measure.finditer(value):
            number = int(hit['number'])
            if not 0 < number <= 2147483647 or re.fullmatch(r'[A-Z][0-9]{6}', hit[0], re.I | re.ASCII):
                continue
            if field == 'subject' and hit[0] == value and record.get('measureType', '').lower() == hit['code'].lower() and record.get('measureNumber') == number:
                continue  # Already the complete, explicitly assigned primary measure.
            hits.append((hit, {'type': 'measure', 'measureType': hit['code'].lower(), 'measureNumber': number}))
        for hit in print_ref.finditer(value):
            hits.append((hit, {'type': 'rules-committee-print', 'congress': int(hit['congress']), 'number': hit['number']}))
        for hit in year.finditer(value):
            hits.append((hit, {'type': 'fiscal-year', 'year': hit['year']}))
        for hit, reference in sorted(hits, key=lambda item: item[0].start()):
            result.append({**reference, 'raw': hit[0], 'sourceField': field, 'start': hit.start(), 'end': hit.end()})
    return result


def derived_values(record: dict, subjects: tuple[str, ...], measures: tuple[str, ...]) -> dict:
    """Return supported metadata; never search across filename slots."""
    out = {}
    kind = record['kind']
    if kind == 'bill-unnumbered':
        text = record['measureToken'] + record['numberPlaceholder'] + record['stage'] + record['versionSuffix']
        longest = next((code for code in measures if text.lower().startswith(code)), '')
        if longest != record['measureToken']:
            raise NamingError('ambiguous-measure-boundary', 'A measure type cannot be shortened by splitting off a version code')
        if record['numberPlaceholder'].startswith('-') and not record['measureToken']:
            raise NamingError('ambiguous-placeholder-boundary', 'A bare hyphen cannot establish an untyped number placeholder')
        if record['measureToken']:
            out['measureType'] = record['measureToken']
    if kind == 'interchamber-amendment':
        out['amendmentDegree'] = int(record['amendmentType'][-1]) if record['amendmentType'][-1] in '23' else 1
    if kind == 'bill-house-amendment' and record['amendmentSuffix'] in {'', '2', '3'}:
        out['amendmentType'] = 'HAmdt' + record['amendmentSuffix']
        out['amendmentDegree'] = int(record['amendmentSuffix'] or '1')
    if kind in {'bill-numbered-described', 'bill-house-amendment'}:
        if kind == 'bill-numbered-described' and starts_with_ordinal_suffix(record['description']):
            raise NamingError('ambiguous-number-boundary', NUMBER_BOUNDARY_NOTE)
        text = record['numberedSubject'] if kind == 'bill-numbered-described' else record['subject']
        hit = re.fullmatch('(' + '|'.join(map(re.escape, measures)) + r')([0-9]+)', text, re.I | re.ASCII)
        if hit and 0 < int(hit[2]) <= 2147483647:
            out.update(measureType=hit[1].lower(), measureNumber=int(hit[2]))
    if 'witnessId' in record and re.fullmatch(r'[A-Z][0-9]{6}', record['witnessId'], re.ASCII):
        out['witnessIdType'] = 'bioguide'
    if kind == 'published-report':
        out['documentType'] = 'report'
    if kind in {'published-hearing', 'published-report', 'published-print'}:
        # Unknown and repeated components remain available in publicationSuffix.
        components = {}
        for hit in re.finditer(r'(?:^|-)(part|pt|p|volume|vol|v|addendum|add|errata|err)([0-9]+|[IVXLCDM]+|[A-Z])?(?=-|$)',
                               record.get('publicationSuffix', ''), re.I | re.ASCII):
            marker = hit[1].lower()
            field = ('part' if marker in {'part', 'pt', 'p'} else
                     'volume' if marker in {'volume', 'vol', 'v'} else
                     'addendum' if marker in {'addendum', 'add'} else 'errata')
            components.setdefault(field, []).append(hit[2] or '')
        out.update({key: values[0] for key, values in components.items() if len(values) == 1})
    if kind in {'bill-numbered', 'bill-untyped-numbered'}:
        hit = re.match(r'(?P<occurrence>[0-9]*)(?:\((?P<annotation>[^()]+)\))?', record.get('versionSuffix', ''))
        if hit['occurrence']:
            out['stageOccurrence'] = hit['occurrence']
        if hit['annotation'] is not None:
            out['annotation'] = hit['annotation']
    if kind == 'appropriation-routed':
        prefix, _ = re.split('-AP-', record['routing'], maxsplit=1, flags=re.I)
        tokens = prefix.split('-')
        if tokens[-1].upper() in {'FC', 'SC', 'ORH'}:
            out['stage'] = tokens.pop().upper()
        elif tokens[-1] == '':
            tokens.pop()
        if len(tokens) == 1 and tokens[0].lower() in measures:
            out['measureType'] = tokens[0].lower()
        elif len(tokens) == 1:
            hit = re.fullmatch('(' + '|'.join(map(re.escape, measures)) + r')([0-9]+)', tokens[0], re.I | re.ASCII)
            if hit and 0 < int(hit[2]) <= 2147483647:
                out.update(measureType=hit[1].lower(), measureNumber=int(hit[2]))
        # Preserve AP spelling; derived references point into the retained text.
        out['description'] = record['routing'][len(prefix) + 1:]
    if kind in {'appropriation-described', 'appropriation-routed'}:
        # The fiscal year must occupy the AP-FY slot, not occur later in prose.
        hit = re.fullmatch(r'AP-(?:FY(?P<year>[0-9]{4}|[0-9]{2}))?-(?:(?P<committee>AP[0-9]{2})-)?(?P<body>.+)',
                           out.get('description', record.get('description', '')), re.I | re.ASCII)
        if hit:
            if hit['year']:
                out['fiscalYear'] = hit['year']
            if hit['committee']:
                out['committeeCode'] = hit['committee'].upper()
            body = hit['body']
            numbered = re.fullmatch(r'(suppl|CR)-([0-9]+)', body, re.I | re.ASCII)
            if numbered:
                out['appropriationType'] = 'supplemental' if numbered[1].lower() == 'suppl' else 'continuing-resolution'
                out['sequence'] = numbered[2]
            else:
                out['subject'] = body
                for subject in subjects:
                    if body.casefold().startswith(subject.casefold() + '-'):
                        out['subject'] = body[:len(subject)]
                        out['descriptionRemainder'] = body[len(subject) + 1:]
                        break
    if kind == 'committee-print':
        hit = re.fullmatch('(' + '|'.join(map(re.escape, measures)) + r')([1-9][0-9]{0,9})', record['subject'], re.I | re.ASCII)
        if hit and int(hit[2]) <= 2147483647:
            out.update(measureType=hit[1].lower(), measureNumber=int(hit[2]))
    references = _references({**record, **out}, measures)
    if references:
        out['references'] = references
    return out
