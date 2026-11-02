"""Which older parser versions still count, and the raw checks that make that safe.

A version digest moves when any hashed byte moves, including a lock-file pin with no
semantic change. An entry here lets rows at `version` stand in for `current` where its
predicate holds, in place of re-stamping them. It needs a differential proof, read in full.
A predicate of "true" covers a move with no semantic change at all.

The selection SQL prefers a current row through an anti-join, so a key never appears twice.
The preflight runs on raw primary keys before any selection: selecting first would hide a
duplicate, not detect it. It groups narrow keys only, O(N) expected per table.
"""
import json
from pathlib import Path

from congress_api.lake import tables
from congress_api.lake.tables import TABLE_SPECS, table_input
from congress_api.retention.provenance import run_job

ROOT = Path(__file__).resolve().parents[4]
REGISTRY = ROOT / 'model/registries/compatible-versions.json'
ENTRY = {'parser', 'version', 'current', 'predicate_sql', 'reason', 'proof'}
PROOF = {'rows', 'columns', 'differences', 'only_old', 'only_new'}
# The join key differs by input, so each selection names its own.
SELECTION_KEYS = {'readings': ['body_sha'], 'meeting_records_input': ['record_sha_hex'], 'appearance_records_input': ['record_sha_hex'],
                  'video_records': ['record_sha'], 'committee_records': ['record_sha']}


def validate_entries(entries, *, current):
    """Refuse an unproved, stale or looping entry. `current` maps flattened parser to its pin."""
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != ENTRY or any(not isinstance(entry[k], str) or not entry[k].strip() for k in ENTRY - {'proof'}):
            raise ValueError('A compatible version requires exactly its declared fields')
        if ';' in entry['predicate_sql']:
            raise ValueError('A compatible predicate cannot contain a semicolon')
        name = entry['parser'], entry['version']
        if name in seen:
            raise ValueError(f'Duplicate compatible version: {name}')
        seen.add(name)
        if current.get(entry['parser']) != entry['current']:
            raise ValueError(f'Compatible version names a superseded pin: {name}')
        if entry['version'] == entry['current']:
            raise ValueError(f'A version cannot be compatible with itself: {name}')
        proof = entry['proof']
        if (not isinstance(proof, dict) or set(proof) != PROOF or any(type(proof[k]) is not int for k in PROOF)):
            raise ValueError(f'Compatible version requires a differential proof: {name}')
        if proof['rows'] <= 0 or proof['columns'] <= 0:
            raise ValueError(f'Compatible version proof compared nothing: {name}')
        if proof['differences'] or proof['only_old'] or proof['only_new']:
            raise ValueError(f'Compatible version proof found differences: {name}')
    return entries


def load_registry(*, current, path=REGISTRY):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict) or set(value) != {'version', 'entries'} or value['version'] != 1 or not isinstance(value['entries'], list):
        raise ValueError('Invalid compatible version registry')
    return validate_entries(value['entries'], current=current)


def render_compatible(entries, *, parser, input_name):
    """UNION ALL rows for one parser's older versions; nothing when none applies.

    Rendering nothing leaves a registry-free job's SQL, and so its hashes, unchanged.
    """
    keys = SELECTION_KEYS[input_name]
    same = ' AND '.join(f'c.{k}=r.{k}' for k in keys)
    return ''.join(
        f"\nUNION ALL\nSELECT r.* FROM {input_name} r WHERE r.parser_version='{e['version']}' AND ({e['predicate_sql']}) "
        f"AND NOT EXISTS (SELECT 1 FROM {input_name} c WHERE {same} AND c.parser_version='{e['current']}')"
        for e in entries if e['parser'] == parser)


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


def prove_unchanged(*, engine, work, name, old, new, version_column, predicate_sql='true'):
    """Read every old row in the predicate against its recomputed row, column by column, both ways."""
    schema = [f['name'] for f in tables.load_schema(name)['fields']]
    keys = [k for k in TABLE_SPECS[name]['primary_key'] if k != version_column]
    compared = [c for c in schema if c not in keys and c != version_column]
    # The one FULL JOIN differential; new rows are not filtered by the old-side predicate.
    result = tables.column_differential(engine, work, old, new, keys=keys, compared=compared,
                                        predicate_sql=predicate_sql, new_predicate_sql='true')
    differing = {c: n for c, n in result['changes'].items() if n}
    return dict(rows=result['rows'], columns=len(compared), differences=sum(differing.values()),
                only_old=result['only_old'], only_new=result['only_new']), differing
