"""Build release discovery metadata from the producer's existing schema registry.

Only small JSON definitions are read here. Native key checks join the existing
publication job; no Parquet rows or bodies are reread to produce documentation.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path

ROOT = Path(__file__).parents[4]
REGISTRY = ROOT / 'model/registries/release-schema.json'
REFERENCE = ROOT / 'docs/release-relationships.md'


def _parts(text):
    """Split the registry's existing nested type notation at top-level commas."""
    depth, start = 0, 0
    for index, character in enumerate(text):
        if character == '<':
            depth += 1
        elif character == '>':
            depth -= 1
        elif character == ',' and depth == 0:
            yield text[start:index]
            start = index + 1
    yield text[start:]


def field_types(table):
    """Expand declared field paths; [] explicitly denotes an element of a list."""
    paths = {}

    def visit(path, kind):
        paths[path] = kind
        if kind.startswith('list<'):
            visit(path + '[]', kind[5:-1])
        elif kind.startswith('struct<'):
            for field in _parts(kind[7:-1]):
                name, child = field.strip().split(' ', 1)
                visit(path + '.' + name, child)

    for column in table['columns'] + table.get('virtual_columns', []):
        visit(column['name'], column['type'])
    return paths


def _kind(kind):
    if kind in ('dict', 'string'):
        return 'string'
    if kind.startswith('int'):
        return 'integer'
    return kind


def validate_schema(schema):
    """Validate authored paths, identities and relationship compatibility."""
    if schema['relationships_version'] != 1:
        raise ValueError('Unsupported relationships_version')
    tables = {f['name'].removesuffix('.parquet'): f for f in schema['files']}
    if len(tables) != len(schema['files']):
        raise ValueError('Duplicate table definition')
    paths = {name: field_types(table) for name, table in tables.items()}

    def endpoint(value):
        name = value['table']
        if name not in tables:
            raise ValueError(f'Unknown relationship table: {name}')
        if not value['fields']:
            raise ValueError(f'No fields: {name}')
        for field in value['fields']:
            if field not in paths[name]:
                raise ValueError(f'Unknown field path: {name}.{field}')
        return [paths[name][field] for field in value['fields']]

    for name, table in tables.items():
        if not table.get('purpose') or not table.get('row_meaning'):
            raise ValueError(f'Missing table meaning: {name}')
        identity = table['identity']
        kinds = endpoint(dict(table=name, fields=identity['fields']))
        if len(set(identity['fields'])) != len(identity['fields']):
            raise ValueError(f'Duplicate identity field: {name}')
        if any('[]' in field or '.' in field for field in identity['fields']):
            raise ValueError(f'Identity must use scalar row fields: {name}')
        if any(kind.startswith(('list<', 'struct<')) for kind in kinds):
            raise ValueError(f'Identity must use scalar row fields: {name}')
        if identity['kind'] not in ('row_position', 'primary_key'):
            raise ValueError(f'Unknown identity kind: {name}')
        if identity['kind'] == 'primary_key' and any(
            column.get('nullable') for column in table['columns'] if column['name'] in identity['fields']
        ):
            raise ValueError(f'Nullable primary key: {name}')
        for path in table.get('notes', {}):
            if path not in paths[name]:
                raise ValueError(f'Unknown note field: {name}.{path}')
    ids = set()
    for relationship in schema['relationships']:
        rid = relationship['id']
        if rid in ids:
            raise ValueError(f'Duplicate relationship: {rid}')
        ids.add(rid)
        source = endpoint(relationship['source'])
        if relationship['cardinality'] not in ('one-to-one', 'many-to-one', 'many-to-many'):
            raise ValueError(f'Invalid cardinality: {rid}')
        if not isinstance(relationship['nullable'], bool):
            raise ValueError(f'Invalid nullable: {rid}')
        if relationship['resolution'] not in ('required', 'unresolved_allowed', 'external'):
            raise ValueError(f'Invalid resolution: {rid}')
        target = relationship['target']
        if 'external' in target:
            if relationship['resolution'] != 'external' or not target['external']:
                raise ValueError(f'Invalid external reference: {rid}')
            continue
        destination = endpoint(target)
        if relationship['cardinality'] in ('one-to-one', 'many-to-one') and target['fields'] != tables[target['table']]['identity']['fields']:
            raise ValueError(f'Target is not a declared unique key: {rid}')
        if len(source) != len(destination):
            raise ValueError(f'Unequal join key lengths: {rid}')
        match = relationship['match']
        if match == 'decimal_string_to_integer':
            compatible = list(map(_kind, source)) == ['string'] and list(map(_kind, destination)) == ['integer']
        elif match in ('equal', 'shared_list_value'):
            compatible = list(map(_kind, source)) == list(map(_kind, destination))
        else:
            raise ValueError(f'Unknown match: {rid}')
        if not compatible:
            raise ValueError(f'Incompatible join types: {rid}')
    recipe_ids = set()
    for recipe in schema['recipes']:
        if recipe['id'] in recipe_ids:
            raise ValueError(f'Duplicate recipe: {recipe["id"]}')
        recipe_ids.add(recipe['id'])
        if set(recipe['requires']) - tables.keys() or set(recipe['relationships']) - ids:
            raise ValueError(f'Unknown recipe dependency: {recipe["id"]}')
        if recipe['dialect'] != 'duckdb' or not recipe['result_row']:
            raise ValueError(f'Invalid recipe description: {recipe["id"]}')
        if recipe['sql'].count('?') != len(recipe['parameters']):
            raise ValueError(f'Recipe parameter count: {recipe["id"]}')
    return schema


def build_schema(available=None, *, registry=None):
    """Add release-specific availability without inventing absent table contents."""
    schema = validate_schema(deepcopy(registry) if registry is not None else json.loads(REGISTRY.read_text()))
    if available is None:
        return schema
    available = {name.removesuffix('.parquet') for name in available}
    for table in schema['files']:
        table['available'] = table['name'].removesuffix('.parquet') in available
    for relationship in schema['relationships']:
        required = {relationship['source']['table']}
        if 'table' in relationship['target']:
            required.add(relationship['target']['table'])
        relationship['missing_tables'] = sorted(required - available)
        relationship['available'] = not relationship['missing_tables']
    for recipe in schema['recipes']:
        recipe['missing_tables'] = sorted(set(recipe['requires']) - available)
        recipe['available'] = not recipe['missing_tables']
    return schema


def validate_parquet_fields(schema, paths):
    """Check published key/reference paths against output footers, never rows."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    declarations = {f['name'].removesuffix('.parquet'): f for f in schema['files']}
    for path in paths:
        name = path.stem
        table = declarations[name]
        expected = field_types(table)
        required = set(table['identity']['fields'])
        required.update(field for r in schema['relationships'] for endpoint in (r['source'], r['target'])
                        if endpoint.get('table') == name for field in endpoint['fields'])
        actual = {}

        def visit(field, kind):
            if pa.types.is_dictionary(kind):
                kind = kind.value_type
            if pa.types.is_string(kind) or pa.types.is_large_string(kind):
                actual[field] = 'string'
            elif pa.types.is_integer(kind):
                actual[field] = 'integer'
            elif pa.types.is_fixed_size_binary(kind):
                actual[field] = f'fixed[{kind.byte_width}]'
            if pa.types.is_list(kind) or pa.types.is_large_list(kind):
                visit(field + '[]', kind.value_type)
            elif pa.types.is_struct(kind):
                for child in kind:
                    visit(field + '.' + child.name, child.type)

        for field in pq.read_schema(path):
            visit(field.name, field.type)
        for column in table.get('virtual_columns', []):
            actual[column['name']] = _kind(column['type'])
        for field in sorted(required):
            if actual.get(field) != _kind(expected[field]):
                raise ValueError(f'Published key/reference type differs: {name}.{field}: {actual.get(field)} != {expected[field]}')


def publication_checks(schema, auxiliary):
    """Check new entity keys and required nested references in the native job.

    Core row positions, source/recovery ordinals, distinct lookup pairs and link
    keys already have one construction/validation owner in archive_format._core.
    Existing materialized export relations are reused, not exported files.
    """
    checks = ['''(SELECT count(*) FROM details d WHERE d.link_key IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM links l WHERE l.link_key=d.link_key)) AS missing_primary_link''']
    for table in schema['files']:
        name = table['name'].removesuffix('.parquet')
        if name not in auxiliary or name == 'url_state':
            continue  # url_state already has its own native uniqueness diagnostic.
        fields = ','.join('"' + field + '"' for field in table['identity']['fields'])
        nulls = ' OR '.join('"' + field + '" IS NULL' for field in table['identity']['fields'])
        checks.append(f'(SELECT count(*) FROM (SELECT {fields} FROM {name}_export GROUP BY {fields} HAVING count(*)>1 OR {nulls})) AS invalid_{name}_key')
    if 'meetings' in auxiliary:
        checks.append('''(SELECT count(*) FROM (SELECT unnest(meeting_keys) AS key FROM ordered) refs
            WHERE key IS NOT NULL AND NOT EXISTS (SELECT 1 FROM meetings_export m WHERE m.event_id=try_cast(refs.key AS BIGINT))) AS missing_document_meeting''')
        checks.append('''(SELECT count(*) FROM (SELECT unnest(transcripts) AS item FROM meetings_export) refs
            WHERE item['list_row'] IS NOT NULL AND NOT EXISTS (SELECT 1 FROM ordered o WHERE o.list_row=refs.item['list_row'])) AS missing_transcript_document''')
    if 'witnesses' in auxiliary:
        checks.append('''(SELECT count(*) FROM (SELECT unnest(witness_keys) AS key FROM ordered) refs
            WHERE key IS NOT NULL AND NOT EXISTS (SELECT 1 FROM witnesses_export w WHERE w.witness_key=refs.key)) AS missing_document_witness''')
    return [dict(name='relationship_invariants', sql='SELECT ' + ',\n'.join(checks))] if checks else []


def render_reference(schema):
    lines = ['# Published Congress data: keys and relationships', '',
        '<!-- Generated from model/registries/release-schema.json; do not edit. -->', '',
        'Regenerate with `.venv/bin/python -m viewer_publication.archive_schema`; use `--check` to detect drift.', '',
        'The producer publishes this metadata in each immutable release’s `schema.json`. The core archive schema remains version 1; relationship metadata has its own version 1. Older releases can lack this metadata. Availability describes tables actually published, not whether a reference resolves or whether external files can be fetched.', '',
        'Paths use `[]` for list elements. Cardinality describes the relationship across source and target rows, including all list elements. Nullable references can be absent. `unresolved_allowed` means that bounded or incomplete source coverage can leave an identifier without a local row. A null is unknown; an absent table is unavailable; a published empty table has zero rows.', '',
        'SQL examples use DuckDB and positional `?` parameters. They are guidance, never executed during discovery. Add `list_row` from zero-based physical position to list/detail, including shard offsets. Predicates such as `list_contains` preserve document grain; unnest only needed lists, and deduplicate before counting across multiple relationships.', '']
    for table in schema['files']:
        name = table['name'].removesuffix('.parquet')
        identity = table['identity']
        lines += [f'## `{name}` — {table["purpose"]}', '', table['row_meaning'] + '.', '',
            f'Identity: `{", ".join(identity["fields"])}` ({identity["kind"]}; {identity["scope"]}).', '']
        if identity.get('note'):
            lines += [identity['note'], '']
        for gap in table['gaps']:
            lines += ['Coverage: ' + gap + '.', '']
        lines += ['| Field | Published type | Meaning |', '| --- | --- | --- |']
        for col in table['columns']:
            lines.append(f'| `{col["name"]}` | `{col["type"]}` | {col["meaning"]} |')
        lines.append('')
        for path, note in table.get('notes', {}).items():
            lines += [f'- `{path}`: {note}']
        lines.append('')
        for direction in ('source', 'target'):
            selected = [r['id'] for r in schema['relationships'] if r[direction].get('table') == name]
            lines += [('Outgoing' if direction == 'source' else 'Incoming') + ': ' + (', '.join(f'`{x}`' for x in selected) or 'none') + '.', '']
    lines += ['## Relationships', '']
    for r in schema['relationships']:
        source, target = r['source'], r['target']
        dest = f'`{target["table"]}.{", ".join(target["fields"])}`' if 'table' in target else target['external']
        lines += [f'### `{r["id"]}`', '', f'`{source["table"]}.{", ".join(source["fields"])}` → {dest}. {r["meaning"]}', '',
            f'{r["cardinality"]}; match: `{r["match"]}`; nullable: {str(r["nullable"]).lower()}; resolution: `{r["resolution"]}`. Scope: {r["scope"]}.', '']
    lines += ['## Query recipes (DuckDB)', '']
    for recipe in schema['recipes']:
        lines += [f'### `{recipe["id"]}` — {recipe["title"]}', '',
            'Requires: ' + ', '.join(f'`{t}`' for t in recipe['requires']) + '.', '',
            'Result: ' + recipe['result_row'] + '.', '',
            'Parameters, in order: ' + ', '.join(f'`{p["name"]}` (example `{p["example"]}`)' for p in recipe['parameters']) + '.', '',
            '```sql', recipe['sql'], '```', '']
        lines += [note + '\n' for note in recipe['notes']]
    return '\n'.join(lines).rstrip() + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    generated = render_reference(build_schema())
    if args.check:
        if not REFERENCE.exists() or REFERENCE.read_text() != generated:
            parser.exit(1, f'{REFERENCE} differs; regenerate with python -m viewer_publication.archive_schema\n')
    else:
        REFERENCE.write_text(generated)


if __name__ == '__main__':
    main()
