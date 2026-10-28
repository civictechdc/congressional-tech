"""Real alternate-runtime imports must never reuse ambient project modules."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
DRIVER = ROOT / 'scripts/corpus_recovery/dispatch_corpus_recovery_publication.py'
spec = importlib.util.spec_from_file_location('runtime_probe', ROOT / 'docs/experiments/efficiency-debt/runtime-ownership-probe.py')
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
spec = importlib.util.spec_from_file_location('runtime_dispatch', DRIVER)
dispatch = importlib.util.module_from_spec(spec); spec.loader.exec_module(dispatch)


@pytest.fixture(scope='module')
def alternate(tmp_path_factory):
    root = tmp_path_factory.mktemp('selected-runtime')
    metadata = probe.fixture(ROOT, root)
    assert 0 < metadata['source_bytes'] < 16 * 1024**2
    return root


def test_clean_alternate_runtime_loads_real_builder_and_transitive_owners(alternate):
    result = probe.probe(DRIVER, ROOT, alternate)
    assert result['error']['type'] == 'ClientBoundary', result
    assert result['calls'] == {'client': 1, 'ownership_check': 3, 'direct_load': 2}
    assert result['warm_boundary']['checks'] == 25
    assert result['warm_boundary']['path_resolves'] == 0
    assert result['remote_operations_possible'] is False
    assert result['admission_calls'] == 1
    selected = alternate / 'selected'
    assert len(result['owners']) > 40  # Catalog, controls, and actual builder helper imports.
    assert set(result['direct_owners']) == {'recovery_viewer_builder', 'recovery_viewer_publisher',
        'filename_viewer', 'filename_observations', 'filename_details', 'filename_navigation', 'filename_review_binding'}
    assert all(Path(path).is_relative_to(selected) for path in [*result['owners'].values(), *result['direct_owners'].values()])
    pins = json.loads((alternate / 'attempt/pins.json').read_text())
    for relative in ('packages/corpus_recovery/src/corpus_recovery/admission.py',
                     'packages/viewer_publication/src/viewer_publication/continuation.py',
                     'packages/viewer_publication/src/viewer_publication/filename_details.py',
                     'packages/congress_shared/src/congress_shared/__init__.py',
                     'scripts/publication/publish-filename-viewer.py',
                     'scripts/publication/publish-viewer-r2.py',
                     'scripts/viewer_release_identity.py'):
        assert str(selected / relative) in pins
    for excluded in ('scripts/publication/README.md',
                     'scripts/publication/pipeline_status.py',
                     'scripts/publication/prepare_workflow_resume.py',
                     'scripts/publication/filename-test-fixture.py'):
        assert str(selected / excluded) not in pins
    assert str(DRIVER) in pins


@pytest.mark.parametrize('conflict', ['congress_api', 'filename_resources', 'corpus_recovery',
                                     'viewer_publication', 'unknown', 'extended_path'])
def test_foreign_prebound_modules_refused_before_client_or_destination(alternate, conflict):
    attempt = 'refused-' + conflict
    result = probe.probe(DRIVER, ROOT, alternate, conflict, attempt)
    assert result['calls'] == {'client': 0, 'ownership_check': 1, 'direct_load': 0}
    assert result['error']['type'] == 'ValueError'
    assert 'cannot reuse loaded module' in result['error']['message']
    assert 'Start a fresh process with --runtime' in result['error']['message']
    assert not (alternate / attempt).exists()
    assert result['admission_calls'] == 0


@pytest.mark.parametrize('damage', ['missing_corpus', 'symlink_corpus'])
def test_required_selected_source_cannot_fall_back_to_ambient_admission(alternate, damage):
    result = probe.probe(DRIVER, ROOT, alternate, damage, damage + '-attempt')
    assert result['error']['type'] == 'ValueError'
    assert 'missing or escaping required source owner corpus_recovery' in result['error']['message']
    assert result['admission_calls'] == 0
    assert result['calls'] == {'client': 0, 'ownership_check': 0, 'direct_load': 0}
    assert not (alternate / (damage + '-attempt')).exists()


def test_explicit_file_builder_children_are_checked_without_sys_modules(tmp_path, monkeypatch):
    selected = object.__new__(dispatch.SelectedRuntime); selected.root = tmp_path; selected._checked = {}
    child = ModuleType('filename_details'); child.__file__ = str(ROOT / 'packages/viewer_publication/src/viewer_publication/filename_details.py')
    builder = ModuleType('recovery_viewer_builder')
    builder.__file__ = str(tmp_path / 'scripts/publication/publish-filename-viewer.py')
    builder.details = child
    # Restrict the cache to this direct-file scenario; the child is intentionally
    # absent from sys.modules, like the maintained builder's module objects.
    monkeypatch.setattr(dispatch.sys, 'modules', {})
    with pytest.raises(ValueError, match='loaded module filename_details'):
        selected.check(builder)


def test_changed_module_origin_and_package_path_invalidate_cached_ownership(tmp_path, monkeypatch):
    selected = object.__new__(dispatch.SelectedRuntime); selected.root = tmp_path; selected._checked = {}
    package = ModuleType('congress_api')
    owner = tmp_path / 'packages/congress_api/src/congress_api'
    package.__file__ = str(owner / '__init__.py'); package.__path__ = [str(owner)]
    monkeypatch.setattr(dispatch.sys, 'modules', {'congress_api': package})
    selected.check(); selected.check()
    package.__path__.append(str(ROOT / 'packages/congress_api/src/congress_api'))
    with pytest.raises(ValueError, match='loaded module congress_api'):
        selected.check()
    package.__path__.pop()
    package.__file__ = str(ROOT / 'packages/congress_api/src/congress_api/__init__.py')
    with pytest.raises(ValueError, match='loaded module congress_api'):
        selected.check()


def test_eager_import_failure_does_not_hold_shared_lock(tmp_path, monkeypatch):
    import fcntl
    from types import SimpleNamespace
    (tmp_path / '.cache').mkdir()
    retained = []
    monkeypatch.setattr(dispatch, 'verify_import', lambda *a, **kw: {})
    monkeypatch.setattr(dispatch, 'cloud_clear', lambda: None)
    def failed_import(*args): raise ImportError('selected builder unsupported')
    monkeypatch.setattr(dispatch, 'load', failed_import)
    # The retained traceback deliberately keeps run() locals alive.
    try:
        dispatch.run(SimpleNamespace(batch=tmp_path, imported=tmp_path, runtime=ROOT,
            execute=True, control_root=tmp_path))
    except ImportError as error:
        retained.append(error)
    assert str(retained[0]) == 'selected builder unsupported'
    with (tmp_path / '.cache/local-recovery.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_selected_helper_change_keeps_explicit_resume_pin_refusal(tmp_path):
    from viewer_publication.continuation import Continuation
    helper = tmp_path / 'scripts/viewer_release_identity.py'
    helper.parent.mkdir(); helper.write_text('version = 1\n')
    selected = object.__new__(dispatch.SelectedRuntime)
    selected.root = tmp_path; selected.sources = [tmp_path / 'scripts']
    def binding(): return {'pins': {str(path): dispatch.digest(path) for path in selected.files()}}
    original = binding()
    Continuation(tmp_path / 'attempt', original)
    assert Continuation(tmp_path / 'attempt', original, resume=True)
    helper.write_text('version = 2\n')
    with pytest.raises(ValueError, match='continuation inputs changed'):
        Continuation(tmp_path / 'attempt', binding(), resume=True)


@pytest.mark.parametrize('order', [
    ('publication_cli', 'viewer_publication.publication_cli'),
    ('viewer_publication.publication_cli', 'publication_cli'),
])
@pytest.mark.parametrize('foreign', [False, True])
def test_publication_cli_import_orders_preserve_runtime_ownership(alternate, order, foreign):
    selected = alternate / 'selected' if foreign else ROOT
    command = r"""
import importlib, importlib.util, sys
from pathlib import Path
root, selected, *order = sys.argv[1:]
root = Path(root)
spec = importlib.util.spec_from_file_location(
    'runtime_dispatch', root / 'scripts/corpus_recovery/dispatch_corpus_recovery_publication.py')
dispatch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dispatch)
sys.path[:0] = [str(root / folder) for folder in dispatch.SelectedRuntime.PACKAGES.values()]
sys.path[:0] = [str(root / 'scripts/publication'), str(root / 'scripts')]
for name in order:
    importlib.import_module(name)
assert sys.modules['publication_cli'] is sys.modules['viewer_publication.publication_cli']
try:
    runtime = dispatch.SelectedRuntime(Path(selected))
except ValueError as error:
    assert Path(selected) != root, str(error)
    assert 'cannot reuse loaded module' in str(error)
    assert str(root) in str(error)
    assert 'Start a fresh process with --runtime' in str(error)
else:
    assert Path(selected) == root, 'Foreign publication CLI was admitted'
    runtime.check()
"""
    result = subprocess.run([sys.executable, '-I', '-B', '-c', command,
                             str(ROOT), str(selected), *order],
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
