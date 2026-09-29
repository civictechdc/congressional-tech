"""Build and audit a regex corpus from saved filenames, without fetching files.

Run: python -m congress_api.filename_corpus INPUT.parquet OUTPUT_DIRECTORY
The Parquet reader needs pyarrow (already used by the explorer). The parser and
build_corpus() have no Parquet dependency; callers can supply literal basenames.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import gzip
import hashlib
import json
from pathlib import Path
import re

from congress_api.filenames import (
    EXTENSION, RULES, UNMATCHED_RULES, resolve_unmatched_filename, filename_tokens, parse_filename, registry,
    shared_token_pattern,
    member_title_pattern,
)
from congress_api.models.legislators import Legislator, parse_legislators


def member_surnames_by_congress(legislators: list[Legislator]) -> dict[str, tuple[str, ...]]:
    """Use retained service dates to select surname vocabulary for each Congress."""
    names = defaultdict(set)
    def start_of(congress):
        return date(1789 + 2 * (congress - 1), 1, 3) if congress >= 74 else date(1789 + 2 * (congress - 1), 3, 4)
    for member in legislators:
        for term in member.terms:
            start, end = date.fromisoformat(term.start), date.fromisoformat(term.end)
            first = max(1, (start.year - 1789) // 2)
            last = (end.year - 1789) // 2 + 1
            for congress in range(first, last + 1):
                if start < start_of(congress + 1) and end > start_of(congress):
                    names[str(congress)].add(member.name.last)
    return {congress: tuple(sorted(surnames)) for congress, surnames in sorted(names.items(), key=lambda row: int(row[0]))}


def _write_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def _gzip_text(path: Path):
    return gzip.open(path, 'wt', encoding='utf-8')


def _line(stream, value):
    stream.write(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')


def build_corpus(filenames, output: Path, *, member_surnames: dict[str, tuple[str, ...]] | None = None) -> dict:
    """Validate all literal spellings; export shared rules and reviewable gaps.

    Recurrence means at least two distinct literal basenames. Matching source
    metadata, semantic document classification, and deduplicating documents are
    deliberately outside this measurement.
    """
    names = sorted(set(filenames))
    stats = {}
    rule_counts = Counter()
    examples = defaultdict(list)
    scopes = {r.id: r.scope for r in RULES}
    scopes['extension'] = 'extension'
    collisions = []
    counts = Counter()
    assumption_counts = Counter()
    date_resolution_counts = Counter()
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
            rule_counts[match.rule] += 1
            per_scope[scopes[match.rule]].append(match.rule)
            if len(examples[match.rule]) < 3:
                examples[match.rule].append({'filename': name, 'match': match.model_dump()})
            for field in match.fields:
                assert 0 <= match.start <= field.start <= field.end <= match.end <= len(name)
                assert name[field.start:field.end] == field.raw
                counts['field_spans_checked'] += 1
                if field.name == 'member_surname_token':
                    counts['member_title_matches'] += 1
                if field.name == 'date_token':
                    counts['date_occurrences'] += 1
                    counts['date_occurrences_ambiguous' if len(field.candidates) > 1 else
                           'date_occurrences_one_reading' if field.candidates else
                           'date_occurrences_without_calendar_reading'] += 1
        for scope, ids in per_scope.items():
            if scope not in {'search', 'extension'} and len(ids) > 1:
                collisions.append({'filename': name, 'scope': scope, 'rules': ids})
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
          (output / 'unmatched-resolutions.jsonl').open('w', encoding='utf-8') as resolutions,
          (output / 'unmatched-names.txt').open('w', encoding='utf-8') as unmatched):
        for name in names:
            parsed = parse_filename(name, member_surnames=member_surnames)
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
                             'matches': [m.model_dump() for m in parsed.matches if m.rule != 'extension']})
                counts['review_rows'] += 1
    with _gzip_text(output / 'shared-tokens.jsonl.gz') as stream:
        for (kind, token), row in sorted(shared.items()):
            _line(stream, {'id': f'{kind}:{token}', 'kind': kind, 'token': token,
                           'pattern': patterns[(kind, token)].pattern, 'flags': [],
                           'variants': sorted(row['variants']), 'filenames': row['filenames'],
                           'occurrences': row['occurrences'], 'examples': row['examples']})
    definitions = registry() + [dict(id='extension', pattern=EXTENSION.pattern,
        scope='extension', flags=['IGNORECASE'], description='Repeatedly strip a recognized trailing extension; retain every suffix.')]
    _write_json(output / 'structural-rules.json', [dict(r, matches=rule_counts[r['id']], examples=examples[r['id']]) for r in definitions])
    _write_json(output / 'collisions.json', collisions)
    _write_json(output / 'member-title-rules.json', [
        {'congress': congress, 'surname_count': len(surnames), 'pattern': member_title_pattern(surnames),
         'scope': 'legislative descriptor', 'flags': ['IGNORECASE']}
        for congress, surnames in (member_surnames or {}).items()
    ])
    _write_json(output / 'unmatched-rules.json', [dict(r, matches=assumption_counts[r['id']] + date_resolution_counts[r['id']]) for r in registry(UNMATCHED_RULES)])
    summary = {
        'literal_filenames': len(names), 'sorted_literal_filenames_sha256': input_digest.hexdigest(),
        'structural_and_field_rules': len(RULES) + 1,
        'shared_token_rules': len(shared),
        'shared_token_rules_by_kind': dict(Counter(k[0] for k in shared)),
        'nonrecurring_tokens_by_kind': dict(Counter(k[0] for k in stats if k not in shared)),
        'structural_collisions': len(collisions),
        'unmatched_resolution_rules': len(UNMATCHED_RULES),
        'unmatched_assumption_rules': sum(r.scope == 'unmatched-stem' for r in UNMATCHED_RULES),
        'per_assumption_rule_matches': dict(assumption_counts),
        'per_unmatched_date_rule_matches': dict(date_resolution_counts),
        **dict(counts),
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
    parser.add_argument('--legislators', nargs='+', type=Path, default=[],
                        help='Optional retained current/historical legislator JSON; no names are fetched by this command.')
    args = parser.parse_args()
    import pyarrow.parquet as pq
    rows = pq.read_table(args.inventory, columns=['filename', 'variants']).to_pylist()
    filenames = {name for row in rows for name in [row['filename'], *(row['variants'] or [])]}
    legislators = [member for path in args.legislators for member in parse_legislators(path.read_bytes())]
    summary = build_corpus(filenames, args.output, member_surnames=member_surnames_by_congress(legislators))
    summary['member_reference_inputs'] = [{'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                                         for path in args.legislators]
    summary['input'] = {'path': str(args.inventory.resolve()), 'rows': len(rows),
                        'sha256': hashlib.sha256(args.inventory.read_bytes()).hexdigest()}
    summary['implementation_sha256'] = {
        name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
        for name in ('filenames.py', 'filename_corpus.py', 'bill_codes.py', 'models/legislators.py', 'models/base.py')
    }
    _write_json(args.output / 'coverage.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in {'per_rule_matches', 'top_shared_words', 'checks', 'limits'}}, indent=2))


if __name__ == '__main__':
    main()
