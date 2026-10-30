"""B11: production raw components use their injected inputs in every environment."""
import ast
from pathlib import Path, PurePosixPath
import re

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'packages/congress_api/src/congress_api'
SURVIVING = (
    'retention/body_store.py', 'retention/receipt_privacy.py', 'retention/writer_identity.py',
    'retention/pipeline_raw.py', 'retention/archive_members.py', 'retention/sniff.py',
    'models/raw_fetch.py', 'acquisition/fetcher.py', 'transport/raw_adapters.py',
    'retention/receipt_writer.py', 'retention/archive_expander.py',
    'retention/provenance.py', 'retention/recovery_facts.py',
    'retention/raw_verifier.py', 'retention/raw_repair.py', 'retention/pdf_backfill.py',
    'cli/provenance.py', 'cli/raw_verify.py', 'cli/raw_repair.py',
)
OTHER_SURVIVING = (
    ROOT / 'packages/corpus_recovery/src/corpus_recovery/reconcile.py',
    ROOT / 'packages/viewer_publication/src/viewer_publication/review_provenance.py',
    ROOT / 'packages/viewer_publication/src/viewer_publication/backfill_uncompressed_pdfs.py',
)
TEST_SWITCH = re.compile(r'^(?:PYTEST(?:_.*)?|UNITTEST(?:_.*)?|TEST_MODE|TESTING)$', re.I)


def violations(source):
    result = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or '']
            if any(module.split('.')[0] in {'pytest', 'unittest', 'testing_fakes'} for module in modules):
                result.append((node.lineno, 'test framework import'))
        if isinstance(node, (ast.Name, ast.Attribute, ast.arg)):
            name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else node.arg
            if TEST_SWITCH.fullmatch(name):
                result.append((node.lineno, 'test switch'))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if TEST_SWITCH.fullmatch(node.value):
                result.append((node.lineno, 'test environment switch'))
            # Concrete input paths may not select a test fixture or a dated development output.
            parts = PurePosixPath(node.value).parts
            if len(parts) > 1 and (any(part in {'tests', 'fixtures', 'testing_fakes'} for part in parts)
                                  or parts[:1] == ('output',)):
                result.append((node.lineno, 'fixture or development input path'))
    return result


def test_surviving_raw_components_have_no_test_selected_inputs():
    found = {name: violations((SOURCE / name).read_text()) for name in SURVIVING}
    found.update({str(path.relative_to(ROOT)): violations(path.read_text()) for path in OTHER_SURVIVING})
    assert {name: errors for name, errors in found.items() if errors} == {}


def test_ratchet_detects_environment_and_fixture_substitutions():
    assert violations("if 'PYTEST_CURRENT_TEST' in os.environ: pass")
    assert violations("Path('output/daily-sample/input.parquet')")
    assert violations("open('tests/fixtures/sample.json')")
    assert violations('import pytest')
    assert violations('def capture(test_mode=False): pass')
    assert violations("# pytest is discussed in comments\nsource = adapter.read(key)") == []
