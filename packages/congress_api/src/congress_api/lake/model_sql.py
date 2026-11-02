"""The model relations each ``model/sql`` file reads, derived from the file itself.

A model SQL file is shared by callers that assemble their own jobs. When one
starts reading another model relation (good-fetches.sql gained
``good_archive_containers`` in 9e2bb6d3), every hand-built caller must add it.
The dependency is read from the SQL, so it cannot drift from it: ``model_steps``
adds a named file's missing model inputs first, and ``check_relations`` refuses
a job, before the engine runs any step, when a step or query reads a model
relation that no earlier input or step defines.

Only names of model SQL files count as references. FROM/JOIN after a comment or
string literal is ignored, and a CTE shadows a model name inside its statement.
"""
from functools import cache
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[5]

_COMMENT = re.compile(r'--[^\n]*')
_LITERAL = re.compile(r"'(?:[^']|'')*'")
_CTE = re.compile(r'(?i)(?:\bWITH\s+(?:RECURSIVE\s+)?|,\s*)([a-z_][a-z0-9_]*)\s+AS\s*\(')
_SOURCE = re.compile(r'(?i)\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)\b')


def relation(name):
    """The relation name a model SQL file defines: its stem with '-' as '_'."""
    return name.replace('-', '_')


@cache
def _model_files(root):
    return {relation(path.stem): path for path in (Path(root) / 'model/sql').glob('*.sql')}


def references(sql, *, root=ROOT):
    """Model relations a SQL text reads, excluding its own CTE names."""
    text = _LITERAL.sub("''", _COMMENT.sub('', sql))
    return (set(_SOURCE.findall(text)) - set(_CTE.findall(text))) & _model_files(str(root)).keys()


def model_steps(names, *, provided=(), root=ROOT, materialize=False):
    """Steps for the named model SQL files, preceded by the model inputs they read.

    ``provided`` names relations the caller defines itself (inputs or its own
    steps); those are not loaded from model SQL.
    """
    files = _model_files(str(root))
    ordered, seen = [], set(provided)

    def visit(name, path):
        if name in seen:
            return
        if name in path:
            raise ValueError(f'Model SQL dependency cycle: {" -> ".join((*path, name))}')
        if name not in files:
            raise ValueError(f'No model SQL file defines {name}')
        for dependency in sorted(references(files[name].read_text(), root=root) - {name}):
            visit(dependency, (*path, name))
        seen.add(name)
        ordered.append(name)

    for name in names:
        visit(relation(name), ())
    return [dict(name=name, sql=files[name].read_text(), materialize=materialize) for name in ordered]


def check_relations(inputs, steps, queries=(), outputs=(), *, root=ROOT):
    """Refuse a job whose steps read a model relation not yet defined."""
    defined = {item['name'] for item in inputs}
    missing = []
    for step in steps:
        absent = references(step.get('sql', ''), root=root) - defined - {step['name']}
        missing.extend(f'{step["name"]} reads {name}' for name in sorted(absent))
        defined.add(step['name'])
    for item in [*queries, *outputs]:
        if 'sql' in item:
            missing.extend(f'{item["name"]} reads {name}'
                           for name in sorted(references(item['sql'], root=root) - defined))
    if missing:
        raise ValueError('Job reads model relations no earlier input or step defines: ' + '; '.join(missing)
                         + '. model_sql.model_steps adds a model file\'s inputs.')
