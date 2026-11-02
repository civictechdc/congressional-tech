"""A raw check judges from raw bytes with its own reading, never through the rule it checks.

A check that shares the rule under test agrees with itself: impl-f's first meeting
raw check passed a wrong reschedule because it restated the rule (ct-asdg,
2026-11-02). This test sees only direct sharing: a raw check (scripts/measure/raw_*.py
or *_raw_check.py at any depth, and the sibling scripts it imports) may not import a producer,
parser or model package, nor read model SQL or a registry. It cannot see a rule
restated in the check's own words; AGENTS.md "Raw checks" asks for a planted wrong
value the check must flag, which a reviewer confirms.
"""
import ast
from pathlib import Path
import re

import pytest

MEASURE = Path(__file__).resolve().parents[1]
RULE_PACKAGES = {'congress_api', 'viewer_publication', 'congress_shared', 'house_naming', 'committee_meeting',
                 'news_lake', 'corpus_recovery', 'committee_explorer'}
RULE_FILES = re.compile(r'model/(sql|registries)/|\.sql\b')


def raw_checks(directory=MEASURE):
    return sorted(path for path in directory.rglob('*.py') if 'tests' not in path.relative_to(directory).parts
                  and (path.name.startswith('raw_') or path.stem.endswith('_raw_check')))


def shared_rules(path, seen=None):
    """Production rules `path` reaches by import or by reading their files, through sibling scripts."""
    seen = set() if seen is None else seen
    if path in seen:
        return []
    seen.add(path)
    found, text = [], path.read_text()
    for node in ast.walk(ast.parse(text)):
        names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                 else [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else [])
        for name in names:
            top = name.split('.')[0]
            if top in RULE_PACKAGES:
                found.append(f'{path.name} imports {name}')
            elif (sibling := path.parent / f'{top}.py').is_file():
                found += shared_rules(sibling, seen)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and RULE_FILES.search(node.value):
            found.append(f'{path.name} reads {node.value!r}')
    return found


@pytest.mark.parametrize('check', raw_checks(), ids=lambda path: path.name)
def test_raw_checks_do_not_share_the_rule_they_judge(check):
    assert shared_rules(check) == []


def test_sharing_through_an_import_a_sibling_or_a_registry_is_seen(tmp_path):
    (tmp_path / 'helpers.py').write_text('from congress_api.parsers.meeting_facts import rescheduled_to\n')
    (tmp_path / 'raw_through_sibling.py').write_text('from helpers import rescheduled_to\n')
    (tmp_path / 'titles_raw_check.py').write_text("WORDS = open('model/registries/page-signals.json').read()\n")
    (tmp_path / 'raw_independent.py').write_text('import json, gzip, re\nimport xml.etree.ElementTree as ET\n')
    (tmp_path / 'capture_causes').mkdir()  # Checks may live in a subdirectory (r1b-captures-causes).
    (tmp_path / 'capture_causes' / 'raw_judge.py').write_text('from congress_api.lake.captures import PK\n')
    found = {path.name: shared_rules(path) for path in raw_checks(tmp_path)}
    assert found == {'raw_independent.py': [], 'raw_judge.py': ['raw_judge.py imports congress_api.lake.captures'],
                     'raw_through_sibling.py': ['helpers.py imports congress_api.parsers.meeting_facts'],
                     'titles_raw_check.py': ["titles_raw_check.py reads 'model/registries/page-signals.json'"]}
