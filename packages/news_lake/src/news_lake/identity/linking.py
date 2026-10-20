"""Link entity mentions into versions (C6): surfaces, code-point spans.

link_mentions(versions, entities, decision_result, run) produces mention
records for one linking run. Surfaces come from entity names and aliases
(exact match, casefolded for comparison). Spans are zero-based Unicode
code-point offsets with an exclusive end into the exact version title/text —
Python str slicing is code-point based, which is exactly the contract.

Resolution follows the decision result: candidates are deduplicated by their
resolved root, so a merged same-name pair resolves while two genuinely
distinct people (different_from, or unrelated) stay ambiguous. Aboutness
defaults to unknown: it is method-specific and never presumed calibrated.
Confidence scores are deliberately omitted for the same reason.

The run must be a successful run whose inputs cover every version passed;
C7's output-input coverage enforces this at corpus time. Recomputing per
version means a stale surface (no longer present in a changed version)
simply produces no spans — never out-of-bounds offsets.
"""
from news_lake.context import adapter_namespace, named_id
from news_lake.contract.records import validate_shape

NAMESPACE = adapter_namespace('identity:linking')
ABOUTNESS_DEFAULT = 'unknown'


def _is_word_character(character):
    """Word characters for boundary checks: Unicode alphanumerics and '_'."""
    return character.isalnum() or character == '_'


def _candidate_surfaces(entities):
    """original surface -> entity ids claiming it."""
    pool = {}
    for entity in entities:
        surfaces = [entity['name']] + [alias['value'] for alias in entity.get('aliases', [])]
        for surface in surfaces:
            pool.setdefault(surface, set()).add(entity['id'])
    return pool


def _find_occurrences(haystack, surface):
    """All (start, end) code-point spans where the surface matches, casefolded.

    Casefolding can change a string's length ('ß' -> 'ss'), so the match is
    verified on each candidate slice of the *original* haystack. Scanning ends
    up to the folded length (plus a small allowance) finds the true code-point
    span; the returned indexes therefore always slice the original string.

    A surface that begins or ends with a word character only matches at a
    corresponding word boundary, so 'Robin Roe' cannot match inside
    'Robin Roebuck' and 'A. Doe' cannot match inside 'M.A. Doering'.
    """
    folded = surface.casefold()
    if not folded:
        return []
    first_folded = folded[0]
    max_length = max(len(surface), len(folded)) + 2
    first_is_word = _is_word_character(surface[0])
    last_is_word = _is_word_character(surface[-1])
    haystack_length = len(haystack)
    spans = []
    for start in range(haystack_length):
        if first_is_word and start > 0 and _is_word_character(haystack[start - 1]):
            continue
        first_chunk = haystack[start].casefold()
        if not first_chunk or first_chunk[0] != first_folded or not folded.startswith(first_chunk):
            continue
        limit = min(haystack_length, start + max_length)
        for end in range(start + 1, limit + 1):
            if haystack[start:end].casefold() != folded:
                continue
            if last_is_word and end < haystack_length and _is_word_character(haystack[end]):
                continue
            spans.append((start, end))
            break
    return spans


def resolution_for(candidates, roots):
    """resolved (single root) / ambiguous (several) / unresolved (none)."""
    distinct_roots = {roots.get(entity_id, entity_id) for entity_id in candidates}
    if not distinct_roots:
        return 'unresolved', None
    if len(distinct_roots) == 1:
        return 'resolved', next(iter(distinct_roots))
    return 'ambiguous', None


def link_mentions(versions, entities, decision_result, run):
    """Mention records for the given versions under one linking run."""
    roots = decision_result['roots'] if decision_result else {}
    pool = _candidate_surfaces(entities)
    mentions = []
    for version in sorted(versions, key=lambda v: v['id']):
        found = {}  # exact matched surface string -> {'spans': set, 'candidates': set}
        for candidate in sorted(pool):
            for field in ('title', 'text'):
                haystack = version.get(field)
                if not haystack:
                    continue
                # Any candidate spelling or casing matching the folded surface works.
                for start, end in _find_occurrences(haystack, candidate):
                    actual = haystack[start:end]
                    entry = found.setdefault(actual, {'spans': set(), 'candidates': set()})
                    entry['spans'].add((field, start, end))
                    entry['candidates'].update(pool[candidate])
        for surface in sorted(found):
            entry = found[surface]
            resolution, entity_id = resolution_for(entry['candidates'], roots)
            mention = {
                'kind': 'mention',
                'id': named_id(NAMESPACE, f'mention:{run["id"]}:{version["id"]}:{surface}'),
                'recorded_at': run['recorded_at'],
                'version_id': version['id'],
                'run_id': run['id'],
                'surface': surface,
                'resolution': resolution,
                'aboutness': ABOUTNESS_DEFAULT,
                'occurrences': [
                    {'field': field, 'start': start, 'end': end}
                    for field, start, end in sorted(entry['spans'])
                ],
            }
            if resolution == 'resolved':
                mention['entity_id'] = entity_id
            mentions.append(validate_shape(mention))
    return mentions
