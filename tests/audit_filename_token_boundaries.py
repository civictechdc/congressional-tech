"""Check every possible literal match of every saved shared-token regex."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from time import perf_counter

from compare_filename_families import load_baseline
from house_naming.corpus import shared_token_pattern

# These expressions consume no characters. Any other serialized shape must be
# reviewed before literal-occurrence pruning can establish exhaustive coverage.
_CAMEL = r'(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])'
_WRAPPERS = {
    'word': (r'(?<![^\W\d_])', r'(?![^\W\d_])'),
    'number': (r'(?<![0-9])', r'(?![0-9])'),
    'wordpart': (rf'(?:(?<![^\W\d_])|{_CAMEL})', rf'(?:(?![^\W\d_])|{_CAMEL})'),
}


def word_character(char):
    return char.isalnum() and not char.isdecimal()


def independent_tokens(stem):
    """Character scanner independent of the production regex lexer/splitter."""
    i = 0
    while i < len(stem):
        start = i
        if '0' <= stem[i] <= '9':
            while i < len(stem) and '0' <= stem[i] <= '9': i += 1
            yield 'number', start, i, stem[start:i]
        elif word_character(stem[i]):
            while i < len(stem) and word_character(stem[i]): i += 1
            yield 'word', start, i, stem[start:i]
            part = start
            for j in range(start + 1, i):
                lower_upper = 'a' <= stem[j-1] <= 'z' and 'A' <= stem[j] <= 'Z'
                acronym_title = ('A' <= stem[j-1] <= 'Z' and 'A' <= stem[j] <= 'Z'
                                 and j + 1 < i and 'a' <= stem[j+1] <= 'z')
                if lower_upper or acronym_title:
                    yield 'wordpart', part, j, stem[part:j]
                    part = j
            yield 'wordpart', part, i, stem[part:i]
        else:
            i += 1


class TokenIndex:
    def __init__(self, rows):
        self.rules = {}
        self.patterns = {}
        self.tree = {}
        self.nodes = 1
        for row in rows:
            key = row['id']
            assert key == row['kind'] + ':' + row['token'] and key not in self.rules
            variants = set(row['variants'])
            assert variants and all(isinstance(v, str) and v and v.casefold() == row['token'] for v in variants)
            assert row['flags'] == []
            prefix, suffix = _WRAPPERS[row['kind']]
            body = '|'.join(re.escape(v) for v in sorted(variants, key=lambda s: (-len(s), s)))
            assert row['pattern'] == prefix + '(?P<token>' + body + ')' + suffix, key
            self.rules[key] = dict(row, variants=variants)
            self.patterns[key] = re.compile(row['pattern'])
            for variant in variants:
                node = self.tree
                for char in variant:
                    if char not in node:
                        node[char] = {}
                        self.nodes += 1
                    node = node[char]
                node.setdefault(None, []).append(key)

    def expected(self, stem):
        found = set()
        for kind, start, end, raw in independent_tokens(stem):
            key = kind + ':' + raw.casefold()
            if key in self.rules and raw in self.rules[key]['variants']:
                found.add((key, start, end, raw))
        return found

    def indexed(self, stem):
        found = set(); checked = set(); literals = 0
        for start in range(len(stem)):
            node = self.tree; end = start
            while end < len(stem) and stem[end] in node:
                node = node[stem[end]]; end += 1
                for key in node.get(None, ()):
                    literals += 1
                    if (key, start) in checked: continue
                    checked.add((key, start))
                    hit = self.patterns[key].match(stem, start)
                    if hit:
                        assert hit.start() == hit.start('token') == start
                        assert hit.end() == hit.end('token')
                        found.add((key, start, hit.end('token'), hit['token']))
        return found, len(checked), literals

    def direct(self, stem):
        return {(key, hit.start('token'), hit.end('token'), hit['token'])
                for key, pattern in self.patterns.items() for hit in pattern.finditer(stem)}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('extraction', type=Path)
    ap.add_argument('corpus', type=Path)
    ap.add_argument('baseline', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('--limit', type=int)
    ap.add_argument('--direct-cases', type=int, default=12)
    args = ap.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    inputs = [args.extraction/'extractions.jsonl.gz', args.corpus/'shared-tokens.jsonl.gz',
              Path(__file__), Path('packages/house-naming/src/house_naming/corpus.py'),
              Path('tests/compare_filename_families.py'),
              Path('tests/test_filename_token_boundaries.py'),
              Path('tests/house-naming-token-boundaries.md'), args.baseline/'summary.json']
    hashes = {str(p.resolve()): digest(p) for p in inputs}
    for source in inputs[2:-1]:
        shutil.copy2(source, args.output/source.name)
    summary = json.loads((args.baseline/'summary.json').read_text())
    for path, expected in summary['hashes'].items():
        if '/packages/congress_api/' in path:
            frozen = args.baseline/'source'/Path(path).relative_to(Path.cwd())
            assert digest(frozen) == expected
    native = load_baseline(args.baseline)
    with gzip.open(inputs[1], 'rt') as f:
        rows = [json.loads(line) for line in f]
    for row in rows:
        variants = tuple(row['variants'])
        assert row['pattern'] == shared_token_pattern(variants, row['kind'])
        assert row['pattern'] == native.shared_token_pattern(variants, row['kind'])
    index = TokenIndex(rows)
    word = re.compile(r'[^\W\d_]')
    assert all(word_character(chr(i)) == bool(word.fullmatch(chr(i))) for i in range(sys.maxunicode + 1))
    counts = Counter(); matches_by_rule = Counter(); mismatches = []; direct_checked = 0
    with gzip.open(inputs[0], 'rt') as f:
        for number, line in enumerate(f):
            if args.limit is not None and number >= args.limit: break
            row = json.loads(line); name = row['filename']; stem = name[:row['result']['stem_end']]
            expected = index.expected(stem)
            actual, candidates, literals = index.indexed(stem)
            counts['filenames'] += 1; counts['stem_characters'] += len(stem)
            counts['candidate_rule_starts'] += candidates; counts['literal_occurrences'] += literals
            counts['expected_matches'] += len(expected); counts['actual_matches'] += len(actual)
            matches_by_rule.update(hit[0] for hit in actual)
            counts['rejected_literal_candidates'] += candidates - len(actual)
            if direct_checked < args.direct_cases:
                assert actual == index.direct(stem), ('Indexed/direct mismatch', name)
                direct_checked += 1
            if actual != expected:
                mismatches.append({'filename': name, 'missing': sorted(expected-actual), 'extra': sorted(actual-expected)})
            if (number + 1) % 25000 == 0:
                print(json.dumps({'processed': number+1, 'seconds': round(perf_counter()-started, 1)}), flush=True)
            if perf_counter()-started > 1800:
                raise TimeoutError('Thirty-minute execution bound reached; partial log retained')
    occurrence_mismatches = ([] if args.limit is not None else [
        {'id': row['id'], 'saved': row['occurrences'], 'actual': matches_by_rule[row['id']]}
        for row in rows if matches_by_rule[row['id']] != row['occurrences']])
    accepted = not mismatches and not occurrence_mismatches
    if args.limit is None:
        accepted = accepted and counts['filenames'] == 333368
    report = {'counts': dict(counts), 'rules': len(rows), 'native_patterns_identical': len(rows),
              'trie_nodes': index.nodes, 'direct_cases': direct_checked,
              'unicode_characters_checked': sys.maxunicode+1, 'mismatches': mismatches,
              'occurrence_mismatches': occurrence_mismatches, 'accepted': accepted,
              'full_corpus': args.limit is None, 'seconds': perf_counter()-started,
              'equivalent_rule_filename_pairs': len(rows)*counts['filenames'],
              'hashes': hashes, 'python': sys.version,
              'limits': ['Matches are checked within the existing extracted stem boundary.',
                         'Literal recurrence does not verify document categories or semantic interpretations.']}
    assert all(digest(p)==v for p,v in hashes.items())
    (args.output/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in {'hashes','mismatches','occurrence_mismatches'}}, indent=2))
    assert not mismatches, f'{len(mismatches)} filenames have missing or extra regex matches'
    assert not occurrence_mismatches, f'{len(occurrence_mismatches)} rules disagree with saved occurrence counts'
    if args.limit is None:
        assert counts['filenames'] == 333368
        assert counts['actual_matches'] == sum(row['occurrences'] for row in rows)


if __name__ == '__main__': main()
