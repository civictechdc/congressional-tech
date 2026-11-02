"""The relations each SQL step reads, from the locked DuckDB parser's syntax tree.

A model SQL file is shared by callers that assemble their own jobs. When one
starts reading another model relation (good-fetches.sql gained
``good_archive_containers`` in 9e2bb6d3), every hand-built caller must add it.
The dependency is read from the SQL, so it cannot drift from it: ``model_steps``
adds a named file's missing model inputs first, in dependency order, and
``check_relations`` refuses a job, before the engine runs any step, when a model
file's step reads a model relation that no earlier input or step defines.

Files with ``{{...}}`` placeholders are rendered by their own callers; they are
not parsed here and ``model_steps`` refuses to load one.
"""
from functools import cache
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[5]


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


def _parser():
    return duckdb.connect(config={'enable_external_access': False, 'threads': 1})


def sql_dependencies(sql):
    """Return external relation names from the locked SQL parser's syntax tree."""
    with _parser() as parser:
        return _dependencies(parser, sql)


def relation(name):
    """The relation name a model SQL file defines: its stem with '-' as '_'."""
    return name.replace('-', '_')


@cache
def _model_files(root):
    return {relation(path.stem): path for path in (Path(root) / 'model/sql').glob('*.sql')}


@cache
def _file_references(root, name):
    sql = _model_files(root)[name].read_text()
    if '{{' in sql:
        raise ValueError(f'{name} has placeholders; its caller renders and supplies it')
    return frozenset(sql_dependencies(sql) & _model_files(root).keys()), sql


def model_steps(names, *, provided=(), root=ROOT, materialize=False):
    """Steps for the named model SQL files, preceded by the model inputs they read.

    ``provided`` names relations the caller defines itself (inputs or its own
    steps); those are not loaded from model SQL. Each step follows every model
    relation it reads.
    """
    root = str(root)
    files = _model_files(root)
    ordered, seen = [], set(provided)

    def visit(name, path):
        if name in seen:
            return
        if name in path:
            raise ValueError(f'Model SQL dependency cycle: {" -> ".join((*path, name))}')
        if name not in files:
            raise ValueError(f'No model SQL file defines {name}')
        reads, sql = _file_references(root, name)
        for dependency in sorted(reads - {name}):
            visit(dependency, (*path, name))
        seen.add(name)
        ordered.append(dict(name=name, sql=sql, materialize=materialize))

    for name in names:
        visit(relation(name), ())
    return ordered


@cache
def _files_by_text(root):
    texts = {}
    for name, path in _model_files(root).items():
        sql = path.read_text()
        if '{{' not in sql:
            texts[sql] = name
    return texts


def check_relations(inputs, steps, *, root=ROOT):
    """Refuse a job in which a model SQL file runs before a model relation it reads.

    Only steps whose SQL is a model file's text are checked; a job's own inline
    SQL may use DataFusion syntax the parser does not read, and the engine still
    plans it.
    """
    root = str(root)
    files = _files_by_text(root)
    defined = {item['name'] for item in inputs}
    missing = []
    for step in steps:
        name = files.get(step.get('sql'))
        if name is not None:
            reads, _ = _file_references(root, name)
            missing.extend(f'{step["name"]} ({_model_files(root)[name].name}) reads {read}' for read in sorted(reads - defined))
        defined.add(step['name'])
    if missing:
        raise ValueError('Job reads model relations no earlier input or step defines: ' + '; '.join(missing)
                         + ". model_sql.model_steps adds a model file's inputs.")
