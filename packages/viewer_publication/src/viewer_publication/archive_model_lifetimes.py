"""Release native relations from the complete application job's SQL graph."""
import json

import duckdb


def _dependencies(parser, sql):
    # DuckDB's maintained parser accepts the model's expressions without binding
    # functions or opening tables. DataFusion spells anti joins LEFT/RIGHT ANTI;
    # remove only that lexer token in the parser copy, retaining both operands.
    tokens = duckdb.tokenize(sql)
    encoded = sql.encode('utf-8')  # The maintained lexer returns UTF-8 byte offsets.
    words = [encoded[start:tokens[i+1][0] if i+1 < len(tokens) else len(encoded)].decode('utf-8').strip().upper()
             for i, (start, _kind) in enumerate(tokens)]
    for index in range(len(tokens)-2, 0, -1):
        if (words[index] == 'ANTI' and words[index-1] in {'LEFT', 'RIGHT'}
                and words[index+1] == 'JOIN'
                and tokens[index][1] == duckdb.token_type.keyword):
            start, end = tokens[index][0], tokens[index+1][0]
            encoded = encoded[:start] + b' '*(end-start) + encoded[end:]
    parsed = json.loads(parser.execute('SELECT json_serialize_sql(?)', [encoded.decode('utf-8')]).fetchone()[0])
    if parsed['error']:
        raise ValueError('Cannot parse model SQL dependencies: ' + parsed['error_message'])

    def tables(node, scope=frozenset()):
        if isinstance(node, list):
            return set().union(*(tables(value, scope) for value in node))
        if not isinstance(node, dict):
            return set()
        found = set()
        if node.get('type') == 'BASE_TABLE':
            name = node['table_name'].casefold()
            if node.get('schema_name') or node.get('catalog_name'):
                raise ValueError('Model dependencies require unqualified named relations')
            return {name} - scope
        # A nonrecursive CTE can read a table with its own name; it enters scope
        # only after its definition. Nested WITH scopes never hide outer reads.
        for entry in node.get('cte_map', {}).get('map', []):
            found |= tables(entry['value'], scope)
            scope = scope | {entry['key'].casefold()}
        for key, value in node.items():
            if key != 'cte_map':
                found |= tables(value, scope)
        return found

    return tables(parsed)


def sql_dependencies(sql):
    """Return external relation names from the locked SQL parser's syntax tree."""
    with duckdb.connect(config={'enable_external_access': False, 'threads': 1}) as parser:
        return _dependencies(parser, sql)


def retire_relations(spec):
    """Replace manual releases with each named step's final native reader.

    Lazy views retain their providers until the view's final reader. Materialized
    results and connected components own independent batches, ending that chain.
    C7 runs exports and queries after all steps, with no releases between them;
    their providers therefore remain registered until native job teardown.
    """
    steps = spec['steps']
    available = {item['name'] for item in spec['inputs']}
    dependencies = {}
    final = set()
    with duckdb.connect(config={'enable_external_access': False, 'threads': 1}) as parser:
        for index, step in enumerate(steps):
            name = step['name']
            if name in available:
                raise ValueError('Duplicate model relation: ' + name)
            sql = step['components']['sql'] if 'components' in step else step['sql']
            readers = _dependencies(parser, sql)
            if readers - available:
                raise ValueError('Model reader has unavailable relations: ' + name + ': ' + ', '.join(sorted(readers-available)))
            dependencies[name] = readers
            available.add(name)
        for reader in [*spec['outputs'], *spec.get('queries', ())]:
            readers = _dependencies(parser, reader['sql'])
            if readers - available:
                raise ValueError('Final model reader has unavailable relations: ' + reader['name'])
            final |= readers
    # C7 cannot self-release. Omit relations with no path to an actual reader,
    # including unused views that would otherwise retain their input providers.
    live = set(final)
    for step in reversed(steps):
        if step['name'] in live:
            live |= dependencies[step['name']]
    steps = [step for step in steps if step['name'] in live]
    positions = {step['name']: index for index, step in enumerate(steps)}
    last = dict(positions)
    for index, step in enumerate(steps):
        for name in dependencies[step['name']] & positions.keys():
            last[name] = index
    for name in final & positions.keys():
        last[name] = len(steps)
    # Propagate ownership backwards only through lazy providers. This also
    # retires unused views at registration, avoiding hidden Arc-held batches.
    for step in reversed(steps):
        if 'components' not in step and not step.get('materialize'):
            for name in dependencies[step['name']] & positions.keys():
                last[name] = max(last[name], last[step['name']])
    releases = [[] for _step in steps]
    for step in reversed(steps):
        index = last[step['name']]
        if index < len(steps):
            releases[index].append(step['name'])
    # Drop dependent views before their providers when both die at one reader.
    planned = []
    lazy = {step['name'] for step in steps if 'components' not in step and not step.get('materialize')}
    for step, retired in zip(steps, releases):
        if not lazy.intersection(retired):
            previous = [name for name in dict.fromkeys(step.get('release_after', ())) if name in retired]
            retired = previous + [name for name in retired if name not in previous]
        step = {key: value for key, value in step.items() if key != 'release_after'}
        planned.append(dict(step, release_after=retired) if retired else step)
    return dict(spec, steps=planned)
