"""Enforce the responsibility folders declared in congress-api's pyproject.toml."""
import ast
from importlib.util import resolve_name
from pathlib import Path
import tomllib

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / 'packages/congress_api'
SOURCE = PACKAGE / 'src/congress_api'
FENCES = tomllib.loads((PACKAGE / 'pyproject.toml').read_text())['tool']['congress-api']['import-fences']


def violations(code, relative_path):
    """Resolve normal Python import syntax, including nested and relative imports."""
    parts = Path(relative_path).parts
    family = parts[0] if len(parts) > 1 else ''
    package = '.'.join(('congress_api', *parts[:-1]))
    allowed = {family, *FENCES.get(family, [])}
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.ImportFrom):
            module = resolve_name('.' * node.level + (node.module or ''), package) if node.level else node.module or ''
            modules = [module]
            if module == 'congress_api':
                modules += [module + '.' + alias.name for alias in node.names]
        elif isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        else:
            continue
        for module in modules:
            if module.startswith('congress_api.'):
                target = module.split('.')[1]
                if target not in allowed:
                    yield f'{relative_path}:{node.lineno}: {family or "package root"} cannot import {module}; allowed: {sorted(allowed)}'
            if module.split('.')[0] in {'committee_explorer', 'youtube_api'}:
                yield f'{relative_path}:{node.lineno}: source package cannot depend on application {module}'
            if module == 'committee_meeting' or module.startswith('committee_meeting.'):
                if family != 'adapters':
                    yield f'{relative_path}:{node.lineno}: only adapters may import normalized meeting models'


def test_responsibility_import_fences():
    folders = {p.name for p in SOURCE.iterdir() if p.is_dir() and p.name != '__pycache__'}
    assert folders == set(FENCES), 'Every new responsibility folder needs an explicit import policy.'
    assert all(set(allowed) <= folders for allowed in FENCES.values()), 'An allowed folder does not exist.'
    failures = [failure for path in sorted(SOURCE.rglob('*.py'))
                for failure in violations(path.read_text(), path.relative_to(SOURCE))]
    assert not failures, '\n' + '\n'.join(failures)


@pytest.mark.parametrize(('path', 'code'), [
    ('models/example.py', 'import congress_api.transport.http'),
    ('models/example.py', 'from congress_api import transport'),
    ('models/example.py', 'from ..transport import http'),
    ('models/example.py', 'from .. import transport as network'),
    ('parsers/example.py', 'def parse():\n    from ..retention import tables'),
    ('matching/example.py', 'from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from ..acquisition import gaps'),
    ('retention/example.py', 'from ..cli import inventory'),
    ('transport/example.py', 'from ..acquisition import meetings'),
    ('adapters/example.py', 'from ..retention import tables'),
    ('acquisition/example.py', 'from ..adapters import meetings'),
    ('replay/example.py', 'from ..transport import http'),
    ('transcripts/example.py', 'from committee_meeting import Meeting'),
    ('acquisition/example.py', 'from committee_explorer import export'),
    ('parsers/example.py', 'from ..new_folder import helper'),
    ('__init__.py', 'from .acquisition import meetings'),
])
def test_fences_reject_forbidden_imports(path, code):
    assert list(violations(code, path))


@pytest.mark.parametrize(('path', 'code'), [
    ('models/example.py', 'from .base import SourceModel'),
    ('parsers/example.py', 'from ..models import congress'),
    ('matching/example.py', 'from congress_api.parsers import gpo'),
    ('acquisition/example.py', 'from ..transport import http'),
    ('adapters/example.py', 'from committee_meeting import Meeting'),
    ('cli/example.py', 'from ..acquisition import meetings'),
])
def test_fences_allow_intended_dependencies(path, code):
    assert not list(violations(code, path))
