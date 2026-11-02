"""Which older readings versions still count, the one selection that honors them, and their proofs.

A version digest moves when any hashed byte moves, including a lock-file pin or a code path
another parser owns. An entry lets readings rows at `version` stand in for `current` instead
of re-stamping them. Only readings parsers qualify: the four leaf parsers and the `readings`
bundle (unreadable-decision authority). Catalog and record tables (D3/D4) are recomputed.

Bases:
- lock_only: only lock pins moved; the old tree must recompute the old pin (attestation).
- whole: hashed code moved but this parser's output did not; a differential proves it.
- predicate: semantics changed for a key set the reader names. `recompute_sql` is that
  reader's own query over `{readings}` returning the body_sha that must be recomputed; every
  other old row stays. The engine evaluates it only as a set, so the selection anti-joins it.
- bundle: the unreadable-decision authority, re-read in full or, when every leaf entry is
  lock_only or whole under the same worker policy, attested statically.

Every proof is bound to its entry: both pins, the recompute-set digest and the two inputs it
read. `selected_readings_steps` is the single selection every reader uses; `accepted_versions`
is for existence checks only, because selecting rows with it would admit old and new duplicates.

The preflight runs on raw primary keys before any selection: selecting first would hide a
duplicate, not detect it. It groups narrow keys only, O(N) expected per table.
"""
import hashlib
import importlib
import json
from pathlib import Path

from congress_api.lake import tables
from congress_api.lake.tables import TABLE_SPECS, table_input
from congress_api.retention.provenance import json_input, run_job

ROOT = Path(__file__).resolve().parents[5]
REGISTRY = ROOT / 'model/registries/compatible-versions.json'
LEAF_PARSERS = ('sniff', 'html', 'xml', 'json')
PARSERS = (*LEAF_PARSERS, 'readings')
ENTRY = {'parser', 'version', 'current', 'basis', 'recompute_sql', 'reason', 'proof'}
BINDING = {'scope', 'version', 'current', 'recompute_sha256', 'old_input_sha256', 'new_input_sha256'}
COUNTS = {'rows', 'columns', 'differences', 'only_old', 'only_new'}
WHOLE = 'none'
# Most bodies are not local, so a leaf proof may be a sample whose keys were fixed before recompute.
SCOPES = {'lock_only': {'sample', 'full'}, 'whole': {'sample', 'full'}, 'predicate': {'sample', 'full'},
          'bundle': {'full', 'static'}}
# The one place each recompute set is defined: the reader that changed. An entry carries a
# digest-bound copy and must equal it; a reader that names none cannot have a predicate entry.
RECOMPUTE_SOURCES = {'html': ('congress_api.parsers.archive_readings', 'HTML_REREAD_SQL')}


def current_pins():
    """The four leaf pins plus the bundle they make under the current worker policy."""
    from congress_api.lake import readings
    leaf = {p: readings.current_version(p) for p in LEAF_PARSERS}
    return {**leaf, 'readings': readings.bundle_version(leaf, policy=readings.worker_limits())}


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


def _validate_proof(entry, name, by_version):
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
    if entry['basis'] == 'lock_only' or scope == 'static':
        attestation = proof.get('lock_only')
        if not isinstance(attestation, dict) or attestation.get('recomputed') != entry['version']:
            _refuse('Lock-only proof requires the old tree to recompute the old version', name)
    if scope == 'static':
        from congress_api.lake.readings import worker_limits
        leaves = proof.get('leaf_versions')
        if not isinstance(leaves, dict) or set(leaves) != set(LEAF_PARSERS):
            _refuse('Static bundle proof must name the old leaf pins', name)
        if any(by_version.get((p, v), {}).get('basis') not in {'lock_only', 'whole'} for p, v in leaves.items()):
            _refuse('Static bundle proof needs a lock-only or whole entry for every old leaf pin', name)
        if proof.get('policy') != worker_limits():
            _refuse('Static bundle proof names another worker policy', name)
        return
    if not COUNTS <= set(proof) or any(type(proof[k]) is not int for k in COUNTS):
        _refuse('Compatible version requires a differential proof', name)
    if proof['rows'] <= 0 or proof['columns'] <= 0:
        _refuse('Compatible version proof compared nothing', name)
    if proof['differences'] or proof['only_old'] or proof['only_new']:
        _refuse('Compatible version proof found differences', name)


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
        if entry['basis'] == 'predicate':
            source = reader_recompute_sql(entry['parser'])
            if source is None:
                _refuse('The reader names no recompute set for a predicate entry', name)
            if entry['recompute_sql'] != source:
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
        _validate_proof(entry, (entry['parser'], entry['version']), seen)
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
    for i, e in enumerate(entries):
        if e['parser'] not in parsers:
            continue
        p, old, new = map(_quote, (e['parser'], e['version'], e['current']))
        sql += (f"\nUNION ALL\nSELECT r.* FROM readings r WHERE r.parser={p} AND r.parser_version={old} "
                f"AND NOT EXISTS (SELECT 1 FROM readings c WHERE c.body_sha=r.body_sha AND c.parser={p} AND c.parser_version={new})")
        if e['recompute_sql'] != WHOLE:
            name = f'recompute_{i}'
            steps.append(dict(name=name, materialize=True, sql=recompute_set_sql(
                e['recompute_sql'], f'(SELECT * FROM readings WHERE parser={p} AND parser_version={old})')))
            sql += f' AND NOT EXISTS (SELECT 1 FROM {name} x WHERE x.body_sha=r.body_sha)'
    return [*steps, dict(name='selected_readings', sql=sql)]


def accepted_version_rows(entries, *, pins):
    """(parser, version) pairs an existence check may accept: the pins plus every whole-version entry."""
    rows = {(p, v) for p, v in pins.items()}
    rows |= {(e['parser'], e['version']) for e in entries if e['recompute_sql'] == WHOLE}
    return [dict(parser=p, version=v) for p, v in sorted(rows)]


def accepted_versions_input(work, entries, *, pins):
    return json_input(work, 'accepted_versions', accepted_version_rows(entries, pins=pins), parser='Utf8', version='Utf8')


def duplicate_keys_sql(name, input_name='t'):
    keys = ','.join(TABLE_SPECS[name]['primary_key'])
    return f'SELECT count(*) AS duplicate_keys FROM (SELECT {keys} FROM {input_name} GROUP BY {keys} HAVING count(*)>1)'


def preflight(*, engine, work, inputs):
    """Reject raw duplicate primary keys before selection. `inputs` maps table name to its source."""
    work = Path(work)
    found = {}
    for name, source in inputs.items():
        rows = run_job(work / name, engine, inputs=[table_input('t', source)], steps=[], outputs=[],
            queries=[dict(name='keys', sql=duplicate_keys_sql(name))])['keys']
        found[name] = rows[0]['duplicate_keys']
    bad = {name: count for name, count in found.items() if count}
    if bad:
        raise ValueError(f'Raw primary keys are duplicated before selection: {bad}')
    return found


def prove_unchanged(*, engine, work, old, new, parser, version, current, recompute_sql=WHOLE, sample_keys=None):
    """Read old rows at `version` against recomputed rows at `current`, column by column, both ways.

    The compared domain K is every key outside the recompute set on the old side or on the
    new side, so a row that left or joined the recompute set is counted, not hidden. With
    `sample_keys` (a parquet of body_sha chosen before the recompute) K is limited to those.
    Rows outside K on either side are not read as differences. Queries only: no sorted export.
    """
    name = 'readings'
    schema = [f['name'] for f in tables.load_schema(name)['fields']]
    keys = [k for k in TABLE_SPECS[name]['primary_key'] if k != 'parser_version']
    compared = [c for c in schema if c not in keys and c != 'parser_version']
    on = lambda a, b: ' AND '.join(f'{a}.{k}={b}.{k}' for k in keys)
    p, old_v, new_v = map(_quote, (parser, version, current))
    inputs = [table_input('old_input', old), table_input('new_input', new)]
    steps = [dict(name='old_rows', sql=f'SELECT * FROM old_input r WHERE r.parser={p} AND r.parser_version={old_v}'),
             dict(name='new_rows', sql=f'SELECT * FROM new_input r WHERE r.parser={p} AND r.parser_version={new_v}'),
             dict(name='old_recompute', sql=recompute_set_sql(recompute_sql, 'old_rows'), materialize=True),
             dict(name='new_recompute', sql=recompute_set_sql(recompute_sql, 'new_rows'), materialize=True)]
    cols = ','.join(keys)
    held = (f'SELECT {cols} FROM old_rows r WHERE NOT EXISTS (SELECT 1 FROM old_recompute x WHERE x.body_sha=r.body_sha) '
            f'UNION SELECT {cols} FROM new_rows r WHERE NOT EXISTS (SELECT 1 FROM new_recompute x WHERE x.body_sha=r.body_sha)')
    if sample_keys is not None:
        inputs.append(table_input('sample_keys', sample_keys))
        held = f'SELECT h.* FROM ({held}) h WHERE h.body_sha IN (SELECT body_sha FROM sample_keys)'
    steps += [dict(name='k', sql=held, materialize=True),
              dict(name='o', sql=f'SELECT r.* FROM old_rows r WHERE EXISTS (SELECT 1 FROM k WHERE {on("k", "r")})'),
              dict(name='n', sql=f'SELECT r.* FROM new_rows r WHERE EXISTS (SELECT 1 FROM k WHERE {on("k", "r")})')]
    present = f'o.{keys[0]} IS NOT NULL AND n.{keys[0]} IS NOT NULL'
    columns = ['count(*) AS total', f'count(*) FILTER (WHERE n.{keys[0]} IS NULL) AS only_old', f'count(*) FILTER (WHERE o.{keys[0]} IS NULL) AS only_new']
    columns += [f'count(*) FILTER (WHERE {present} AND o."{c}" IS DISTINCT FROM n."{c}") AS "{c}"' for c in compared]
    row = run_job(work, engine, inputs=inputs, steps=steps, outputs=[],
        queries=[dict(name='proof', sql='SELECT ' + ','.join(columns) + f' FROM o FULL JOIN n ON {on("o", "n")}')])['proof'][0]
    differing = {c: row[c] for c in compared if row[c]}
    return dict(rows=row['total'], columns=len(compared), differences=sum(differing.values()), only_old=row['only_old'], only_new=row['only_new']), differing
