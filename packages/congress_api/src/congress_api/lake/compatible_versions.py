"""Which older readings versions still count, the one selection that honors them, and their proofs.

A version digest moves when any hashed byte moves, including a lock-file pin or a code path
another parser owns. An entry lets readings rows at `version` stand in for `current` instead
of re-stamping them. Only readings parsers qualify: the four leaf parsers, the derived
`html_metadata` parser (its own pass, outside the bundle) and the `readings` bundle
(unreadable-decision authority). Catalog and record tables (D3/D4) are recomputed.

Bases:
- lock_only: only lock pins moved; the old tree must recompute the old pin (attestation).
- whole: hashed code moved but this parser's output did not; a differential proves it.
- predicate: semantics changed for a key set. `recompute_sql` is the reader's own query over
  `{readings}` returning the body_sha that must be recomputed ('none' when the reader names
  none); every other old row stays. The engine evaluates it only as a set, so the selection
  anti-joins it. Every html/xml/json entry is a predicate entry: bodies above the current
  page-parse bound are also recomputed, by rule, and the proof is bound to that bound.
- bundle: the unreadable-decision authority, re-read in full. (A static bundle proof needed
  lock-only page leaves; page entries are predicate entries now, so it was removed.)

Every proof is bound to its entry: both pins, the recompute-set digest and the two inputs it
read. `selected_readings_steps` is the single selection every reader uses; `accepted_versions`
is for existence checks only, because selecting rows with it would admit old and new duplicates.

Proof tooling (prove_unchanged, the raw-key preflight) lives in compatible_proof, which no
pin hashes.
"""
import hashlib
import importlib
import json
from pathlib import Path

from congress_api.retention.provenance import json_input

ROOT = Path(__file__).resolve().parents[5]
REGISTRY = ROOT / 'model/registries/compatible-versions.json'
LEAF_PARSERS = ('sniff', 'html', 'xml', 'json')
# Page parsers parse the whole body, so their outcome depends on readings.PAGE_PARSE_MAX_BYTES
# (ct-61ys): a body above it is refused under the current rule. Every page entry therefore
# recomputes those bodies, by rule, sized from captures (`bytes` is the decoded size).
PAGE_PARSERS = ('html', 'xml', 'json')
DERIVED_PARSERS = ('html_metadata',)
PARSERS = (*LEAF_PARSERS, *DERIVED_PARSERS, 'readings')
ENTRY = {'parser', 'version', 'current', 'basis', 'recompute_sql', 'reason', 'proof'}
BINDING = {'scope', 'version', 'current', 'recompute_sha256', 'old_input_sha256', 'new_input_sha256'}
COUNTS = {'rows', 'columns', 'differences', 'only_old', 'only_new'}
WHOLE = 'none'
# A lock-only or whole proof may be a sample whose keys were fixed before recompute; a
# predicate entry changes semantics, so it compares every row it keeps.
SCOPES = {'lock_only': {'sample', 'full'}, 'whole': {'sample', 'full'}, 'predicate': {'full'},
          'bundle': {'full'}}
# A sample compares at least this many completed rows (or all local ones), and every local
# error/size_limit row: those exercise the paths a few successes do not.
MIN_SAMPLE_ROWS = 2000
ERROR_STRATA = ('error', 'size_limit')
# The one place each recompute set is defined: the reader that changed. An entry carries a
# digest-bound copy and must equal it; a reader that names none cannot have a predicate entry.
RECOMPUTE_SOURCES = {'html': ('congress_api.parsers.archive_readings', 'HTML_REREAD_SQL')}


def current_pins():
    """The four leaf pins, the derived pins beside them, and the bundle the leaves make."""
    from congress_api.lake import readings
    leaf = {p: readings.current_version(p) for p in LEAF_PARSERS}
    derived = {p: readings.current_version(p) for p in DERIVED_PARSERS}
    return {**leaf, **derived, 'readings': readings.bundle_version(leaf, policy=readings.worker_limits())}


def page_parse_max_bytes():
    from congress_api.lake.readings import PAGE_PARSE_MAX_BYTES
    return PAGE_PARSE_MAX_BYTES


def oversize_bodies_sql(captures='captures'):
    """Bodies the current page parser refuses by size: narrow, one filtered capture scan."""
    return f'SELECT DISTINCT sha256 AS body_sha FROM {captures} WHERE bytes > {page_parse_max_bytes()}'


def recompute_sha256(recompute_sql):
    return hashlib.sha256(recompute_sql.encode()).hexdigest()


def reader_recompute_sql(parser):
    """The changed reader's own recompute set, or None when it names none."""
    if parser not in RECOMPUTE_SOURCES:
        return None
    module, name = RECOMPUTE_SOURCES[parser]
    return vars(importlib.import_module(module)).get(name)


def _refuse(message, name):
    raise ValueError(f'{message}: {name}')


def _validate_proof(entry, name):
    proof = entry['proof']
    scope = proof.get('scope') if isinstance(proof, dict) else None
    if not isinstance(proof, dict) or not BINDING <= set(proof) or scope not in SCOPES[entry['basis']]:
        _refuse('Compatible version requires a differential proof of its basis scope', name)
    if proof['version'] != entry['version'] or proof['current'] != entry['current']:
        _refuse('Compatible version proof is bound to other pins', name)
    if proof['recompute_sha256'] != recompute_sha256(entry['recompute_sql']):
        _refuse('Compatible version recompute set changed after its proof', name)
    if any(not isinstance(proof[k], str) or len(proof[k]) != 64 for k in ('old_input_sha256', 'new_input_sha256')):
        _refuse('Compatible version proof must name both inputs it read', name)
    if entry['basis'] == 'lock_only':
        attestation = proof.get('lock_only')
        if not isinstance(attestation, dict) or attestation.get('recomputed') != entry['version']:
            _refuse('Lock-only proof requires the old tree to recompute the old version', name)
    if entry['parser'] in PAGE_PARSERS and proof.get('page_parse_max_bytes') != page_parse_max_bytes():
        _refuse('Page entry proof is bound to another page-parse bound', name)
    if not COUNTS <= set(proof) or any(type(proof[k]) is not int for k in COUNTS):
        _refuse('Compatible version requires a differential proof', name)
    if proof['rows'] <= 0 or proof['columns'] <= 0:
        _refuse('Compatible version proof compared nothing', name)
    _validate_coverage(proof, name)
    if proof['differences'] or proof['only_old'] or proof['only_new']:
        _refuse('Compatible version proof found differences', name)


def _validate_coverage(proof, name):
    """Bind how much was compared: all kept rows for `full`, a stratified minimum for `sample`.

    `strata` maps status to {population, local, sampled}: old rows the entry keeps, those with a
    local body, and those compared. The counts are the proof tool's; a forged count is not
    detected here, only an inconsistent or too-small one.
    """
    strata = proof.get('strata')
    fields = {'population', 'local', 'sampled'}
    if (not isinstance(strata, dict) or not strata or any(not isinstance(v, dict) or set(v) != fields
            or any(type(v[k]) is not int or v[k] < 0 for k in fields) or not v['sampled'] <= v['local'] <= v['population']
            for v in strata.values())):
        _refuse('Compatible version proof must state its strata', name)
    if sum(v['sampled'] for v in strata.values()) != proof['rows']:
        _refuse('Compatible version proof strata do not add up to its rows', name)
    if proof['scope'] == 'full':
        if any(v['sampled'] != v['population'] for v in strata.values()):
            _refuse('A full proof compares every row the entry keeps', name)
        return
    for status, v in strata.items():
        least = v['local'] if status in ERROR_STRATA else min(v['local'], MIN_SAMPLE_ROWS)
        if v['sampled'] < least:
            _refuse(f'Compatible version sample is too small in its {status} stratum', name)


def validate_entries(entries, *, current):
    """Refuse an unproved, stale or unbound entry. `current` maps parser to its live pin."""
    seen = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != ENTRY or any(not isinstance(entry[k], str) or not entry[k].strip() for k in ENTRY - {'proof'}):
            raise ValueError('A compatible version requires exactly its declared fields')
        name = entry['parser'], entry['version']
        if entry['parser'] not in PARSERS:
            _refuse('D3/D4 have no compatible versions; recompute', name)
        if entry['basis'] not in SCOPES:
            _refuse('Unknown compatible version basis', name)
        if (entry['basis'] == 'bundle') != (entry['parser'] == 'readings'):
            _refuse('The readings bundle, and only it, uses the bundle basis', name)
        if entry['basis'] != 'predicate' and entry['recompute_sql'] != WHOLE:
            _refuse('Only a predicate entry names a recompute set', name)
        if (entry['parser'] in PAGE_PARSERS) != (entry['basis'] == 'predicate'):
            _refuse('A page parser entry, and only one, is a predicate entry (the parse-size bound applies)', name)
        if entry['basis'] in ('lock_only', 'whole') and reader_recompute_sql(entry['parser']) is not None:
            _refuse('Its reader names a recompute set; a whole-version entry would keep rows it changes', name)
        if entry['basis'] == 'predicate' and entry['recompute_sql'] != (reader_recompute_sql(entry['parser']) or WHOLE):
            _refuse("A predicate entry's recompute set must equal its reader's", name)
        if name in seen:
            _refuse('Duplicate compatible version', name)
        seen[name] = entry
        if current.get(entry['parser']) != entry['current']:
            _refuse('Compatible version names a superseded pin', name)
        if entry['version'] == entry['current']:
            _refuse('A version cannot be compatible with itself', name)
    # Every current is the live pin and no version equals it, so entries cannot chain.
    for entry in entries:
        _validate_proof(entry, (entry["parser"], entry["version"]))
    return entries


def load_registry(*, current=None, path=None):
    value = json.loads(Path(path or REGISTRY).read_text())
    if not isinstance(value, dict) or set(value) != {'version', 'entries'} or value['version'] != 2 or not isinstance(value['entries'], list):
        raise ValueError('Invalid compatible version registry')
    return validate_entries(value['entries'], current=current_pins() if current is None else current)


def _quote(value):
    return "'" + value.replace("'", "''") + "'"


def recompute_set_sql(recompute_sql, relation):
    """The recompute key set over one relation; empty for a whole-version entry."""
    if recompute_sql == WHOLE:
        return f'SELECT body_sha FROM {relation} WHERE false'
    return recompute_sql.replace('{readings}', relation)


def selected_readings_steps(entries, *, parsers=LEAF_PARSERS):
    """The one readings selection: pinned rows, plus older rows an entry covers where no current row exists.

    The selection is never materialized: readers project what they need. Readings is
    partitioned by (parser, parser_version), so each branch prunes to one partition and the
    current-row anti-join builds on current rows only. A predicate entry adds one narrow,
    materialized body_sha set (its recompute set over the old partition), anti-joined here.
    With no entries it equals the plain pin join.
    """
    steps, sql = [], 'SELECT r.* FROM parser_versions v JOIN readings r ON r.parser=v.parser AND r.parser_version=v.version'
    earlier = {}
    for i, e in enumerate(sorted(entries, key=lambda e: (e['parser'], e['version']))):
        if e['parser'] not in parsers:
            continue
        p, old, new = map(_quote, (e['parser'], e['version'], e['current']))
        # One row per body: an earlier old version of this parser takes precedence, even where
        # its own recompute set leaves the body out (then the producer re-reads it).
        prior = ''.join(f' AND NOT EXISTS (SELECT 1 FROM readings o WHERE o.body_sha=r.body_sha AND o.parser={p} AND o.parser_version={v})'
                        for v in earlier.get(e['parser'], []))
        earlier.setdefault(e['parser'], []).append(old)
        sql += (f"\nUNION ALL\nSELECT r.* FROM readings r WHERE r.parser={p} AND r.parser_version={old} "
                f"AND NOT EXISTS (SELECT 1 FROM readings c WHERE c.body_sha=r.body_sha AND c.parser={p} AND c.parser_version={new})"
                + prior)
        if e['recompute_sql'] != WHOLE:
            name = f'recompute_{i}'
            steps.append(dict(name=name, materialize=True, sql=recompute_set_sql(
                e['recompute_sql'], f'(SELECT * FROM readings WHERE parser={p} AND parser_version={old})')))
            sql += f' AND NOT EXISTS (SELECT 1 FROM {name} x WHERE x.body_sha=r.body_sha)'
        if e['parser'] in PAGE_PARSERS:
            if not any(step['name'] == 'oversize_page_bodies' for step in steps):
                steps.append(dict(name='oversize_page_bodies', materialize=True, sql=oversize_bodies_sql()))
            sql += ' AND NOT EXISTS (SELECT 1 FROM oversize_page_bodies z WHERE z.body_sha=r.body_sha)'
    return [*steps, dict(name='selected_readings', sql=sql)]


def accepted_version_rows(entries, *, pins):
    """(parser, version) pairs an existence check may accept: the pins plus every non-predicate entry."""
    rows = {(p, v) for p, v in pins.items()}
    rows |= {(e['parser'], e['version']) for e in entries if e['basis'] != 'predicate'}
    return [dict(parser=p, version=v) for p, v in sorted(rows)]


def accepted_versions_input(work, entries, *, pins):
    return json_input(work, 'accepted_versions', accepted_version_rows(entries, pins=pins), parser='Utf8', version='Utf8')
