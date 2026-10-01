"""Validated filename rendering and ambiguity-preserving recognition."""
from __future__ import annotations
from copy import deepcopy
from collections.abc import Mapping, Sequence
from datetime import date
import math
import re
from typing import Any
from urllib.parse import urlsplit
from jsonschema import Draft202012Validator
from .catalog import load_guide
from .compiler import record_schema, stem_pattern
from .errors import NamingError
from .metadata import derived_values

MAX_FILENAME_BYTES = 255
UNSAFE = re.compile(r'[\s/\\<>:"|?*\x00-\x1f\x7f\u0085\uFEFF]')
REVISION = re.compile(r'-U([0-9]+)$', re.IGNORECASE | re.ASCII)


class Engine:
    """Render, validate and parse the bundled conventions, entirely offline.

    The bundled catalog is trusted application configuration. The Engine copies it and returns copies from accessors. It never
    changes input records, writes documents, fetches URLs, or repairs filenames.
    """
    def __init__(self):
        self._guide = load_guide()
        self._kinds = tuple(self._guide['patterns'])
        self._validators = {k: Draft202012Validator(record_schema(self._guide, k)) for k in self._kinds}
        self._derived_validators = {
            k: {f: Draft202012Validator(self._guide['field_types'][r['fields'][f]])
                for f in r.get('derived_fields', [])}
            for k, r in self._guide['patterns'].items()}
        self._matchers = {
            k: [re.compile(stem_pattern(self._guide, k, capture=True, accept_case=True, template=t))
                for t in [r['stem_template'], *r.get('parse_templates', [])]]
            for k, r in sorted(self._guide['patterns'].items(), key=lambda item: item[1].get('parse_priority', 0))
            if r['action'] == 'filename'}
        self._defaults = {k: {field: self._guide['field_types'][typ]['default']
                             for field, typ in r['fields'].items()
                             if 'default' in self._guide['field_types'][typ]}
                          for k, r in self._guide['patterns'].items()}
        self._extensions = {e for r in self._guide['patterns'].values() if r['action'] == 'filename'
                            for e in self._guide['field_types'][r['fields']['extension']]['enum']}
        self._subjects = tuple(sorted({re.sub(r'^fy[0-9]{2,4}-', '', token)
                                       for token in self._guide['codes']['appropriation-subject']}, key=len, reverse=True))
        self._measures = tuple(sorted(self._guide['codes']['measure'], key=len, reverse=True))

    @property
    def guide(self) -> dict[str, Any]:
        return deepcopy(self._guide)

    def extraction_rules(self) -> list[dict[str, Any]]:
        """Return copies of the catalog's literal extraction rules."""
        return deepcopy(self._guide['extraction_rules'])

    def kinds(self) -> list[str]:
        return list(self._kinds)

    def extract(self, filename: str, *, member_surnames: Mapping[str, Sequence[str]] | None = None,
                source_url: str | None = None) -> dict[str, Any]:
        """Read literal source fields, including non-renderable and partial names.

        `valid` and `matches` retain parse()'s convention-validation meaning.
        `observations` retain source spans, candidates and fallback assumptions;
        they do not certify a document's contents or a person's identity.
        `metadata` collects useful values and literal roles without requiring
        a valid naming convention. Values are lists of source strings.
        `source_url` optionally qualifies local publisher conventions. It is
        caller-supplied provenance, never fetched or used as document identity.
        """
        from .extraction import Extractor
        from .values import filename_metadata
        if not hasattr(self, '_extractor'):
            self._extractor = Extractor(self._guide)
        extracted = self._extractor.extract(filename, member_surnames=member_surnames, source_url=source_url)
        result = {**self.parse(filename), **extracted}
        result['metadata'] = filename_metadata(result)
        return result

    def lookup(self, context: str, token: str) -> dict[str, Any] | None:
        if not isinstance(context, str) or not isinstance(token, str):
            raise NamingError('invalid-lookup', 'Context and token must be strings')
        if context not in self._guide['codes']:
            raise NamingError('unknown-context', f'Unknown code context: {context}')
        return deepcopy(self._guide['codes'][context].get(token.casefold()))

    def contexts(self, token: str) -> list[str]:
        if not isinstance(token, str):
            raise NamingError('invalid-lookup', 'Token must be a string')
        return list(self._guide['code_index'].get(token.casefold(), []))

    def committee(self, folder_code: str) -> dict[str, Any] | None:
        """Exact folder-code lookup. 'AG' is not rewritten to 'AG00'."""
        if not isinstance(folder_code, str):
            raise NamingError('invalid-lookup', 'Folder code must be a string')
        return deepcopy(self._guide['committees'].get(folder_code))

    def source(self, source_id: str) -> dict[str, Any] | None:
        if not isinstance(source_id, str):
            raise NamingError('invalid-lookup', 'Source ID must be a string')
        return deepcopy(self._guide['source_nodes'].get(source_id))

    def examples(self, value: str) -> list[dict[str, Any]]:
        if not isinstance(value, str):
            raise NamingError('invalid-lookup', 'Example value must be a string')
        ids = self._guide['example_index'].get(value, [])
        return [{'id': eid, **deepcopy(self._guide['examples'][eid])} for eid in ids]

    def _render(self, record: dict[str, Any]) -> str:
        rule = self._guide['patterns'][record['kind']]
        if rule['action'] == 'reference':
            return record['url']
        values = {**self._defaults[record['kind']], **record}
        values['meetingSuffix'] = '-' + str(record['meetingOccurrence']) if 'meetingOccurrence' in record else ''
        stem = rule['stem_template'].format_map(values)
        revision = '-U' + str(record['revision']) if 'revision' in record else ''
        return stem + revision + '.' + record['extension']

    def validate(self, record: Any) -> dict[str, Any]:
        """Validate, fill declared defaults, and return a fresh canonical record."""
        if not isinstance(record, dict):
            raise NamingError('invalid-record', 'A naming record must be a JSON object')
        if len(record) > 32:
            raise NamingError('invalid-record', 'A record may contain at most 32 fields')
        values = list(record.items())
        references = record.get('references')
        if references is not None:
            if not isinstance(references, list) or len(references) > 64:
                raise NamingError('invalid-record', 'references must be an array of at most 64 objects')
            for reference in references:
                if not isinstance(reference, dict) or len(reference) > 12:
                    raise NamingError('invalid-record', 'Each reference must be a small JSON object')
            values = [(k, v) for k, v in record.items() if k != 'references'] + [
                (k, v) for reference in references for k, v in reference.items()]
        for key, value in values:
            if not isinstance(key, str) or not isinstance(value, (str, int, float, bool, type(None))):
                raise NamingError('invalid-record', 'Record keys must be strings and field values must be JSON scalars')
            if isinstance(value, str) and len(value) > 2048:
                raise NamingError('input-too-large', 'A record string exceeds 2048 characters')
            if type(value) is int and abs(value) > 2147483647:
                raise NamingError('invalid-record', 'A numeric field exceeds the supported 32-bit bound')
        kind = record.get('kind')
        if not isinstance(kind, str) or kind not in self._guide['patterns']:
            raise NamingError('unknown-kind', 'Record kind must name a catalog pattern')
        if any(isinstance(v, float) and not math.isfinite(v) for _, v in values):
            raise NamingError('non-finite-number', 'Numeric fields must be finite')
        errors = list(self._validators[kind].iter_errors(record))
        if errors:
            details = [{'path': '/' + '/'.join(str(x) for x in e.absolute_path),
                        'keyword': str(e.validator), 'message': e.message[:500]} for e in errors[:16]]
            raise NamingError('invalid-record', 'Record does not satisfy its naming schema', details)
        normalized = {**self._defaults[kind],
                      **{k: int(v) if type(v) is float and v.is_integer() else v for k, v in record.items()}}
        calculated = derived_values(normalized, self._subjects, self._measures)
        for field in self._guide['patterns'][kind].get('derived_fields', []):
            if field in record and (field not in calculated or record[field] != calculated[field]):
                raise NamingError('conflicting-derived-field', f'{field} disagrees with the retained filename field')
            if field in calculated:
                if not self._derived_validators[kind][field].is_valid(calculated[field]):
                    raise NamingError('invalid-derived-field', f'{field} violates its field schema')
                normalized[field] = calculated[field]
        for field in ('meetingDate', 'voteDate', 'weekOf'):
            if field in normalized:
                text = normalized[field]
                try:
                    day = date(int(text[:4]), int(text[4:6]), int(text[6:8]))
                except ValueError as exc:
                    raise NamingError('invalid-calendar-date', f'{field} is not a real YYYYMMDD calendar date') from exc
                if field == 'weekOf' and day.weekday() != 0:
                    raise NamingError('not-monday', 'weekOf must be a Monday, including holiday weeks')
        if self._guide['patterns'][kind]['action'] == 'reference':
            try:
                raw_url = normalized['url']
                # Deterministic structural HTTP(S) checks. Optional jsonschema
                # format plugins must not change this package's acceptance.
                if re.fullmatch(r"[A-Za-z0-9:/?#\[\]@!$&'()*+,;=._~%+-]+", raw_url) is None:
                    raise ValueError('URL must use ASCII URI spelling')
                if re.search(r'%(?![0-9A-Fa-f]{2})', raw_url):
                    raise ValueError('Invalid percent escape')
                url = urlsplit(raw_url)
                if url.scheme not in ('http', 'https') or not url.hostname or url.username is not None or url.password is not None:
                    raise ValueError('Expected absolute HTTP(S) URL without credentials')
                _ = url.port
                if re.search(r'[\s\\\x00-\x1f\x7f\u0085\uFEFF]', normalized['url']):
                    raise ValueError('Whitespace or controls in URL')
            except ValueError as exc:
                raise NamingError('invalid-url', 'Expected a syntactically valid absolute HTTP(S) URL without credentials') from exc
        else:
            name = self._render(normalized)
            try:
                size = len(name.encode('utf-8'))
            except UnicodeError as exc:
                raise NamingError('invalid-unicode', 'Filename is not encodable as UTF-8') from exc
            if size > MAX_FILENAME_BYTES:
                raise NamingError('filename-too-long', 'Rendered filename exceeds 255 UTF-8 bytes')
            if UNSAFE.search(name):
                raise NamingError('unsafe-filename', 'Filename contains forbidden characters')
        return normalized

    def render(self, record: Any) -> str:
        """Return a validated filename, or the supplied URL for link-only kinds."""
        return self._render(self.validate(record))

    def parse(self, filename: str) -> dict[str, Any]:
        """Return every matching convention, separately from exact source hits.

        Fixed tokens and code fields accept ASCII case variants. Free text and
        original input retain their spelling. Only catalogued layouts match;
        separators and missing metadata are not guessed. Every candidate
        validates and includes its canonical rendered filename. Generic patterns
        at later parse priorities run only if earlier priorities have no valid
        candidates. No winner is selected among candidates at the same priority.
        """
        if not isinstance(filename, str):
            raise NamingError('invalid-filename', 'Filename must be a string basename')
        ids = list(self._guide['example_index'].get(filename, []))
        result: dict[str, Any] = {'input': filename,
            'found_in_source': bool(ids), 'source_example_ids': ids,
            'source_issues': [{'example_id': eid, 'issues': list(self._guide['examples'][eid]['issues'])}
                              for eid in ids if self._guide['examples'][eid]['issues']],
            'valid': False, 'ambiguous': False,
            'matches': [], 'issues': [], 'rejected_candidates': []}
        try:
            if len(filename.encode('utf-8')) > MAX_FILENAME_BYTES:
                result['issues'].append('filename-too-long')
                return result
        except UnicodeError:
            result['issues'].append('invalid-unicode')
            return result
        if not filename or UNSAFE.search(filename):
            result['issues'].append('unsafe-or-empty-filename')
            return result
        stem, dot, extension = filename.rpartition('.')
        extension = extension.lower()
        if not dot or extension not in self._extensions:
            result['issues'].append('missing-or-unsupported-extension')
            return result
        revision = None
        hit = REVISION.search(stem)
        if hit:
            digits = hit.group(1)
            if len(digits) > 10 or digits.startswith('0') or int(digits) > 2147483647:
                result['issues'].append('invalid-revision-suffix')
                return result
            revision = int(digits)
            stem = stem[:hit.start()]
        matched_priority = None
        for kind, matchers in self._matchers.items():
            rule = self._guide['patterns'][kind]
            priority = rule.get('parse_priority', 0)
            if matched_priority is not None and priority > matched_priority:
                break
            for matcher in matchers:
                hit = matcher.fullmatch(stem)
                if hit is None:
                    continue
                try:
                    record = self._record_from_match(kind, hit, extension, revision)
                    parsed_kind = rule.get('parse_as', kind)
                    if parsed_kind != kind:
                        target = next((target for m in self._matchers[parsed_kind]
                                       if (target := m.fullmatch(stem)) is not None), None)
                        if target is None:
                            raise NamingError('unmatched-parse-target', 'Source convention does not match its shared record pattern')
                        record = self._record_from_match(parsed_kind, target, extension, revision)
                except NamingError as exc:
                    rejection = {'kind': kind, 'priority': priority, **exc.as_dict()}
                    if rejection not in result['rejected_candidates']:
                        result['rejected_candidates'].append(rejection)
                    if exc.code not in result['issues']:
                        result['issues'].append(exc.code)
                    continue
                matched_priority = priority
                previous = next((m for m in result['matches'] if m['record'] == record), None)
                if previous is not None:
                    if kind not in previous['matched_conventions']:
                        previous['matched_conventions'].append(kind)
                    previous['requires_interpretation'] |= rule['requires_interpretation']
                    previous['decisions'] = list(dict.fromkeys([*previous['decisions'], *rule['decisions']]))
                    continue
                result['matches'].append({'kind': parsed_kind, 'record': record,
                    'matched_conventions': [kind],
                    'canonical_filename': self._render(record),
                    'requires_interpretation': rule['requires_interpretation'],
                    'decisions': list(rule['decisions'])})
        result['valid'] = bool(result['matches'])
        result['ambiguous'] = len(result['matches']) > 1
        if not result['matches']:
            result['issues'].append('no-matching-convention')
        if result['ambiguous']:
            result['issues'].append('multiple-patterns-match')
        return result

    def _record_from_match(self, kind: str, hit: re.Match, extension: str, revision: int | None) -> dict:
        if kind in {'bill-titled-draft', 'bill-numbered-described'}:
            stage, description = hit['stage'], hit['description']
            if description and description[-1].isalpha() and not (stage.islower() or stage.isupper()):
                # OAWPih does not establish whether P belongs to the acronym
                # or PIH. Keep the input; do not promote a regex split to fact.
                raise NamingError('ambiguous-stage-boundary', 'Joined mixed-case stage has no established word boundary')
        record: dict[str, Any] = {'kind': kind, 'extension': extension}
        rule = self._guide['patterns'][kind]
        for field, text in hit.groupdict().items():
            if text is None:
                continue
            typ = self._guide['field_types'][rule['fields'][field]]
            value: Any = int(text) if typ['type'] == 'integer' else text
            if 'enum' in typ and isinstance(value, str):
                value = next(v for v in typ['enum'] if str(v).casefold() == value.casefold())
            elif '[A-Z]' in typ.get('pattern', ''):
                value = value.upper()
            record[field] = value
        if revision is not None:
            record['revision'] = revision
        return self.validate(record)
