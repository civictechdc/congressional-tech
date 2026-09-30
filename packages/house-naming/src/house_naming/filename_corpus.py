"""Build and audit a regex corpus from saved filenames, without fetching files.

Run: python -m house_naming.filename_corpus INPUT.parquet OUTPUT_DIRECTORY
Install house-naming-guide[corpus] for Parquet input and the typed result API.
build_corpus() accepts literal basenames and does not read Parquet itself.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Sequence
import gzip
import hashlib
import json
from pathlib import Path
import re

from .corpus import DESCRIPTIVE_FIELDS, residual_fields as _residual_fields

from .filenames import (
    EXTENSION, FilenameField, ParsedFilename, resolve_unmatched_filename, filename_tokens, parse_filename, registry,
    shared_token_pattern,
    member_title_pattern,
)

def _write_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def _gzip_text(path: Path):
    return gzip.open(path, 'wt', encoding='utf-8')


def _line(stream, value):
    stream.write(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')


OTHER_TEXT_FIELDS = DESCRIPTIVE_FIELDS - {'descriptor', 'suffix'} | {'amendment_token', 'document_number'}


def parser_source_paths() -> list[Path]:
    """Hash the installed naming package and its catalog, without application dependencies."""
    package = Path(__file__).parent
    return [*sorted(package.glob('*.py')), *sorted((package / 'data').glob('*.json'))]


def file_hashes(paths):
    return {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def uncertain_capture(field):
    return bool(field.candidates and field.code is None)


def residual_fields(parsed: ParsedFilename, *, field_names=frozenset({'descriptor', 'suffix'}),
                    include_unstructured=False) -> list[dict]:
    """Adapt typed results to the shared residual-text reader."""
    rows = _residual_fields({'input': parsed.filename, 'stem_end': parsed.stem_end,
                            'observations': [match.model_dump() for match in parsed.matches]},
                           field_names=field_names, include_unstructured=include_unstructured)
    for row in rows:
        # Synthetic unstructured stems use the same saved field shape as captures.
        row['field'] = FilenameField.model_validate(row['field']).model_dump()
    return rows


def build_corpus(filenames, output: Path, *, member_surnames: dict[str, Sequence[str]] | None = None) -> dict:
    """Validate all literal spellings; export shared rules and reviewable gaps.

    Recurrence means at least two distinct literal basenames. Matching source
    metadata, semantic document classification, and deduplicating documents are
    deliberately outside this measurement.
    """
    names = sorted(set(filenames))
    stats = {}
    rule_counts = Counter()
    examples = defaultdict(list)
    definitions = {r['id']: r for r in registry()}
    scopes = {r['id']: r['scope'] for r in definitions.values()}
    unmatched_rules = [r for r in definitions.values() if r['scope'] in {'unmatched-date', 'unmatched-stem'}]
    scopes['extension'] = 'extension'
    collisions = []
    counts = Counter()
    assumption_counts = Counter()
    date_resolution_counts = Counter()
    residual_counts = Counter(opaque_fields_audited=0, fields_with_residual_text=0,
                              filenames_with_opaque_fields=0, filenames_with_residual_text=0)
    residual_groups = defaultdict(Counter)
    residual_patterns = {}
    other_groups = defaultdict(Counter)
    other_patterns = {}
    capture_groups = {}
    input_digest = hashlib.sha256()
    for name in names:
        input_digest.update((json.dumps(name, ensure_ascii=False) + '\n').encode())
        parsed = parse_filename(name, member_surnames=member_surnames)
        assert ''.join(p.raw for p in parsed.pieces) == name
        end = 0
        for piece in parsed.pieces:
            assert piece.start == end
            end += len(piece.raw)
            assert piece.end == end
        counts['lossless_filenames_checked'] += 1
        per_scope = defaultdict(list)
        for match in parsed.matches:
            scopes[match.rule] = match.scope
            definitions.setdefault(match.rule, dict(id=match.rule, scope=match.scope,
                description=match.description, pattern=None, derived=True))
            rule_counts[match.rule] += 1
            per_scope[(match.scope, match.start, match.end)].append(match.rule)
            if len(examples[match.rule]) < 3:
                examples[match.rule].append({'filename': name, 'match': match.model_dump()})
            for field in match.fields:
                assert 0 <= match.start <= field.start <= field.end <= match.end <= len(name)
                assert name[field.start:field.end] == field.raw
                counts['field_spans_checked'] += 1
                if field.name not in DESCRIPTIVE_FIELDS:
                    status = ('uncertain' if uncertain_capture(field) else 'unresolved_date' if field.name == 'date_token'
                              else 'vocabulary_label' if field.label
                              else 'unlisted_code' if field.name in {'version_token', 'measure_token'} else 'literal_syntax')
                    value = field.raw.casefold() if field.name in {'version_token', 'measure_token', 'document_token'} else field.code
                    group = capture_groups.setdefault((match.rule, field.name, status, value), {'occurrences': 0, 'examples': []})
                    group['occurrences'] += 1
                    if len(group['examples']) < 3:
                        group['examples'].append({'filename': name, 'field': field.model_dump()})
                if field.name == 'member_surname_token':
                    counts['member_title_matches'] += 1
                if field.name == 'date_token':
                    counts['date_occurrences'] += 1
                    counts['date_occurrences_ambiguous' if len(field.candidates) > 1 else
                           'date_occurrences_one_reading' if field.candidates else
                           'date_occurrences_without_calendar_reading'] += 1
        for (scope, start, end), ids in per_scope.items():
            if scope in {'stem', 'committee-payload', 'legislative-payload', 'collection-prefix'} and len(ids) > 1:
                collisions.append({'filename': name, 'scope': scope, 'start': start, 'end': end, 'rules': ids})
        seen = set()
        for token in filename_tokens(parsed):
            key = (token.kind, token.raw.casefold())
            if key not in stats:
                stats[key] = {'filenames': 0, 'occurrences': 0, 'variants': set(), 'examples': []}
            row = stats[key]
            row['occurrences'] += 1
            row['variants'].add(token.raw)
            if key not in seen:
                row['filenames'] += 1
                if len(row['examples']) < 3:
                    row['examples'].append(name)
                seen.add(key)
    shared = {key: row for key, row in stats.items() if row['filenames'] >= 2}
    patterns = {key: re.compile(shared_token_pattern(tuple(row['variants']), key[0]))
                for key, row in shared.items()}
    for key, row in shared.items():
        regex = patterns[key]
        for variant in row['variants']:
            assert regex.fullmatch(variant)
            # Whole-token negatives: extensions or longer words/numbers cannot
            # create spurious recurrence. CamelCase boundaries have unit tests.
            if key[0] in {'word', 'number'}:
                adjacent = 'x' if key[0] == 'word' else '9'
                assert regex.search(adjacent + variant + adjacent) is None
            counts['token_variant_controls_checked'] += 1

    output.mkdir(parents=True, exist_ok=True)
    with (_gzip_text(output / 'review.jsonl.gz') as gaps,
          _gzip_text(output / 'residual-fields.jsonl.gz') as residuals,
          _gzip_text(output / 'other-text-fields.jsonl.gz') as other_text,
          (output / 'unmatched-resolutions.jsonl').open('w', encoding='utf-8') as resolutions,
          (output / 'unmatched-names.txt').open('w', encoding='utf-8') as unmatched):
        for name in names:
            parsed = parse_filename(name, member_surnames=member_surnames)
            other = residual_fields(parsed, field_names=OTHER_TEXT_FIELDS, include_unstructured=True)
            if other:
                _line(other_text, {'filename': name, 'fields': other})
            for row in other:
                key = (row['rule'], row['field']['name'])
                other_groups[key]['fields_audited'] += 1
                other_groups[key]['fields_with_residual_text'] += bool(row['residual_spans'])
                if row['residual_spans']:
                    shape = ' … '.join(re.sub(r'[0-9]+', '<number>', span['raw'].casefold()) for span in row['residual_spans'])
                    group = other_patterns.setdefault((*key, shape), {'filenames': 0, 'stems': set(), 'examples': []})
                    group['filenames'] += 1
                    group['stems'].add(name[:parsed.stem_end].casefold())
                    if len(group['examples']) < 3:
                        group['examples'].append({'filename': name, 'spans': row['residual_spans']})
            opaque = residual_fields(parsed)
            residual_counts['filenames_with_opaque_fields'] += bool(opaque)
            residual_counts['filenames_with_residual_text'] += any(row['residual_spans'] for row in opaque)
            if opaque:
                _line(residuals, {'filename': name, 'fields': opaque})
            for row in opaque:
                key = (row['rule'], row['field']['name'])
                group = residual_groups[key]
                group['fields_audited'] += 1
                residual_counts['opaque_fields_audited'] += 1
                has_residual = bool(row['residual_spans'])
                group['fields_with_residual_text'] += has_residual
                residual_counts['fields_with_residual_text'] += has_residual
                if has_residual:
                    # A review grouping, not an extraction rule or inferred type.
                    shape = ' … '.join(re.sub(r'[0-9]+', '<number>', span['raw'].casefold())
                                       for span in row['residual_spans'])
                    pattern = residual_patterns.setdefault((*key, shape), {'names': set(), 'stems': set(), 'examples': []})
                    pattern['names'].add(name)
                    pattern['stems'].add(name[:parsed.stem_end].casefold())
                    if len(pattern['examples']) < 3:
                        pattern['examples'].append({'filename': name, 'spans': row['residual_spans']})
            expected = defaultdict(list)
            for token in filename_tokens(parsed):
                key = (token.kind, token.raw.casefold())
                if key in shared:
                    expected[key].append((token.start, token.end, token.raw))
            for key, spans in expected.items():
                actual = [(m.start('token'), m.end('token'), m['token'])
                          for m in patterns[key].finditer(name[:parsed.stem_end])]
                assert actual == spans, (name, key, actual, spans)
                counts['shared_token_occurrences_checked'] += len(spans)
            counts['filenames_with_shared_token'] += bool(expected)
            counts['filenames_with_shared_word'] += any(k[0] in {'word', 'wordpart'} for k in expected)
            ids = {m.rule for m in parsed.matches}
            has_layout = any(scopes[m.rule] == 'stem' for m in parsed.matches)
            counts['filenames_with_layout'] += has_layout
            recurring_layout = any(scopes[m.rule] == 'stem' and rule_counts[m.rule] >= 2 for m in parsed.matches)
            counts['filenames_with_shared_token_or_recurring_layout'] += bool(expected) or recurring_layout
            interpretation = None
            if not expected and not recurring_layout:
                counts['filenames_unmatched_before_assumptions'] += 1
                interpretation = resolve_unmatched_filename(parsed)
                basis = 'date_pattern' if interpretation and interpretation.rule.startswith('unmatched-leading-') else 'user_assumption'
                if interpretation:
                    (date_resolution_counts if basis == 'date_pattern' else assumption_counts)[interpretation.rule] += 1
                    counts['filenames_resolved_by_date_pattern' if basis == 'date_pattern' else 'filenames_resolved_by_assumption'] += 1
                    for field in interpretation.fields:
                        assert name[field.start:field.end] == field.raw
                        counts['unmatched_resolution_field_spans_checked'] += 1
                else:
                    counts['filenames_unmatched_after_assumptions'] += 1
                    unmatched.write(name + '\n')
                _line(resolutions, {'filename': name,
                                   'basis': basis if interpretation else 'zip_excluded' if name.lower().endswith('.zip') else 'unresolved',
                                   'interpretation': interpretation.model_dump() if interpretation else None})
            counts['filenames_with_fields_beyond_extension'] += any(m.rule != 'extension' for m in parsed.matches)
            unparsed_payload = ('committee-file' in ids and not any(scopes[i] == 'committee-payload' for i in ids)
                                or 'legislative-file' in ids and not any(scopes[i] == 'legislative-payload' for i in ids))
            counts['filenames_with_unparsed_structured_payload'] += bool(unparsed_payload)
            if not has_layout or unparsed_payload or not expected:
                _line(gaps, {'filename': name, 'has_layout': has_layout,
                             'unparsed_structured_payload': bool(unparsed_payload),
                             'has_shared_token': bool(expected),
                             'unmatched_interpretation': interpretation.model_dump() if interpretation else None,
                             'matches': [m.model_dump() for m in parsed.matches if m.rule != 'extension'],
                             'suppressed': [m.model_dump() for m in parsed.suppressed],
                             'issues': list(parsed.issues),
                             'rejected_candidates': [r.model_dump() for r in parsed.rejected_candidates]})
                counts['review_rows'] += 1
    ranked_residuals = sorted([
        {'rule': rule, 'field': field, 'shape': shape, 'filenames': len(row['names']), 'distinct_stems': len(row['stems']), 'examples': row['examples']}
        for (rule, field, shape), row in residual_patterns.items()
    ], key=lambda row: (-row['filenames'], row['rule'], row['field'], row['shape']))
    with _gzip_text(output / 'residual-patterns.jsonl.gz') as stream:
        for row in ranked_residuals:
            _line(stream, row)
    with _gzip_text(output / 'other-text-patterns.jsonl.gz') as stream:
        for (rule, field, shape), row in sorted(other_patterns.items(), key=lambda item: (-item[1]['filenames'], item[0])):
            _line(stream, dict(rule=rule, field=field, shape=shape, filenames=row['filenames'], distinct_stems=len(row['stems']), examples=row['examples']))
    _write_json(output / 'other-text-summary.json', {
        'by_rule_and_field': [dict(rule=rule, field=field, **values) for (rule, field), values in sorted(other_groups.items())],
        'scope': 'Other opaque fields and stems without a full outer layout; structured enclosing payloads are skipped.',
        'limits': 'Residual text can be useful names, identifiers or prose. Plain numeric/letter-suffixed amendment and document IDs are already captured syntax and remain in capture-review rather than this text review. Distinct stems are not resolved document identities.',
    })
    _write_json(output / 'capture-review.json', [
        dict(rule=rule, field=field, status=status, value=value, **row)
        for (rule, field, status, value), row in sorted(capture_groups.items(), key=lambda item: str(item[0]))
    ])
    _write_json(output / 'residual-summary.json', {
        **dict(residual_counts),
        'by_rule_and_field': [dict(rule=rule, field=field, **values)
                              for (rule, field), values in sorted(residual_groups.items())],
        'distinct_residual_shapes': len(ranked_residuals),
        'recurring_residual_shapes': sum(row['filenames'] >= 2 for row in ranked_residuals),
        'top_recurring_shapes': [row for row in ranked_residuals if row['filenames'] >= 2][:50],
        'scope': 'Nonempty descriptor and suffix fields, after subtracting specific captures; delimiters alone are excluded.',
        'limits': [
            'Residual text can be an appropriate free-text title, not missing structured metadata.',
            'Extracted syntax includes uncertain dates and literal identifiers; it does not prove their meaning.',
            'Other opaque fields and unstructured stems are reported separately in other-text artifacts; inferred fields are sampled in capture-review.json.',
            'Shapes fold case and replace digit runs only to rank review work; they are not parser rules.',
            'Counts refer to literal filenames; PDF/XML spellings can refer to the same document.',
        ],
    })
    with _gzip_text(output / 'shared-tokens.jsonl.gz') as stream:
        for (kind, token), row in sorted(shared.items()):
            _line(stream, {'id': f'{kind}:{token}', 'kind': kind, 'token': token,
                           'pattern': patterns[(kind, token)].pattern, 'flags': [],
                           'variants': sorted(row['variants']), 'filenames': row['filenames'],
                           'occurrences': row['occurrences'], 'examples': row['examples']})
    definitions['extension'] = dict(id='extension', pattern=EXTENSION.pattern,
        scope='extension', flags=['IGNORECASE', 'ASCII'], description='Repeatedly strip a recognized trailing extension; retain every suffix.')
    _write_json(output / 'structural-rules.json', [dict(r, matches=rule_counts[r['id']], examples=examples[r['id']]) for r in definitions.values()])
    _write_json(output / 'collisions.json', collisions)
    _write_json(output / 'member-title-rules.json', [
        {'congress': congress, 'surname_count': len(surnames), 'pattern': member_title_pattern(tuple(surnames)),
         'scope': 'legislative descriptor', 'flags': ['IGNORECASE']}
        for congress, surnames in (member_surnames or {}).items()
    ])
    _write_json(output / 'unmatched-rules.json', [dict(r, matches=assumption_counts[r['id']] + date_resolution_counts[r['id']]) for r in unmatched_rules])
    summary = {
        'literal_filenames': len(names), 'sorted_literal_filenames_sha256': input_digest.hexdigest(),
        'structural_and_field_rules': len(definitions),
        'shared_token_rules': len(shared),
        'shared_token_rules_by_kind': dict(Counter(k[0] for k in shared)),
        'nonrecurring_tokens_by_kind': dict(Counter(k[0] for k in stats if k not in shared)),
        'structural_collisions': len(collisions),
        'unmatched_resolution_rules': len(unmatched_rules),
        'unmatched_assumption_rules': sum(r['scope'] == 'unmatched-stem' for r in unmatched_rules),
        'per_assumption_rule_matches': dict(assumption_counts),
        'per_unmatched_date_rule_matches': dict(date_resolution_counts),
        **dict(counts),
        'residual_text_audit': dict(residual_counts),
        'per_rule_matches': dict(rule_counts),
        'top_shared_words': [dict(kind=k[0], token=k[1], filenames=v['filenames'])
                             for k, v in sorted(shared.items(), key=lambda kv: (-kv[1]['filenames'], kv[0]))
                             if k[0] == 'word'][:60],
        'scope': 'Exact filename spelling and regex syntax only; no document-content accuracy claim.',
        'checks': [
            'Every original character reconstructs exactly from parser pieces.',
            'Every named field equals its original substring, including blank slots.',
            'Every recurring-token occurrence is recovered with exactly the same span by its rule.',
            'Applied token rules produce no extra occurrences in those filenames.',
            'All token variants and whole-word/number negative boundary controls pass.',
            'All overlapping full-layout/payload matches are listed; field-search overlap is intentional.',
            'User-assumed fields retain exact original spans and are reported separately from syntax matches.',
        ],
        'limits': [
            'Tokenization is explicit: Unicode letter runs, ASCII numbers, ASCII CamelCase parts; no synonym or substring guessing.',
            'Recurrence can be two spellings/formats of one document; filenames do not establish document identity.',
            'Token rules are case-sensitive to observed variants; structural rules ignore case and preserve original captures.',
            'Generic date/identifier shapes remain candidates; source metadata and file contents were not used as labels.',
            'Positive token/rule pairs were tested exhaustively; the absent-rule-by-filename cross product was not executed.',
            'Unmatched non-ZIP names retain recognizable leading dates/timestamps before using generic-identifier/name fallbacks; these are not source-verified identities.',
            'Unknown payloads and original spelling remain visible; future filenames require a fresh corpus audit.',
        ],
    }
    _write_json(output / 'coverage.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inventory', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--member-surnames', type=Path,
                        help='Optional Congress-keyed surname JSON, as accepted by house-naming extract.')
    args = parser.parse_args()
    source_paths = parser_source_paths()
    reference_paths = [args.member_surnames] if args.member_surnames else []
    paths = [*source_paths, args.inventory, *reference_paths]
    before = file_hashes(paths)
    import pyarrow.parquet as pq
    rows = pq.read_table(args.inventory, columns=['filename', 'variants']).to_pylist()
    filenames = {name for row in rows for name in [row['filename'], *(row['variants'] or [])]}
    reference = json.loads(args.member_surnames.read_text()) if args.member_surnames else {}
    if not isinstance(reference, dict) or any(not isinstance(names, list) or any(not isinstance(name, str) or not name.strip() for name in names) for names in reference.values()):
        parser.error('--member-surnames must contain an object mapping Congress numbers to lists of names')
    summary = build_corpus(filenames, args.output, member_surnames=reference)
    summary['member_reference_inputs'] = [{'path': str(path.resolve()), 'sha256': before[str(path.resolve())]}
                                         for path in reference_paths]
    summary['input'] = {'path': str(args.inventory.resolve()), 'rows': len(rows),
                        'sha256': before[str(args.inventory.resolve())]}
    summary['implementation_sha256'] = {
        str(path.resolve()): before[str(path.resolve())] for path in source_paths
    }
    after = file_hashes(paths)
    summary['changed_during_run'] = [name for name in before if before[name] != after[name]]
    summary['mechanical_gate'] = not summary['structural_collisions'] and not summary['changed_during_run']
    _write_json(args.output / 'coverage.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in {'per_rule_matches', 'top_shared_words', 'checks', 'limits'}}, indent=2))
    return 0 if summary['mechanical_gate'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
