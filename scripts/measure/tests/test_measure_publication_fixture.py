"""A pinned checkout owns its fixture, including before the test relocation."""
import hashlib
from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts/measure'))
import measure_publication_control as measurement


@pytest.mark.parametrize('relative', [
    'packages/viewer_publication/tests/test_viewer_publication_attempt.py',
    'tests/test_viewer_publication_attempt.py',
])
def test_measurement_executes_the_selected_checkouts_fixture(tmp_path, monkeypatch, relative):
    checkout = tmp_path / 'selected'
    fixture = checkout / relative
    fixture.parent.mkdir(parents=True)
    # Stop at actual fixture execution, before any publication or timed work.
    fixture.write_text('raise RuntimeError(__file__)\n')
    ambient = tmp_path / 'ambient'
    ambient_fixture = ambient / 'packages/viewer_publication/tests/test_viewer_publication_attempt.py'
    ambient_fixture.parent.mkdir(parents=True)
    ambient_fixture.write_text('raise AssertionError("ambient fixture selected")\n')
    monkeypatch.chdir(ambient)
    monkeypatch.setattr(sys, 'path', sys.path.copy())
    source = tmp_path / 'source'
    manifest = source / 'indexes/catalog.json'
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(b'{}')
    pin = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with pytest.raises(RuntimeError, match=re.escape(str(fixture))):
        measurement.run(checkout, source, tmp_path / 'evidence', pin)


def test_relocated_fixture_takes_precedence_when_both_layouts_exist(tmp_path):
    current = tmp_path / 'packages/viewer_publication/tests/test_viewer_publication_attempt.py'
    prior = tmp_path / 'tests/test_viewer_publication_attempt.py'
    for path in (current, prior):
        path.parent.mkdir(parents=True)
        path.touch()
    assert measurement.publication_fixture(tmp_path) == current


def test_missing_selected_fixture_cannot_fall_back_to_ambient_checkout(tmp_path, monkeypatch):
    ambient = tmp_path / 'ambient'
    ambient_fixture = ambient / 'tests/test_viewer_publication_attempt.py'
    ambient_fixture.parent.mkdir(parents=True)
    ambient_fixture.touch()
    selected = tmp_path / 'selected'
    selected.mkdir()
    monkeypatch.chdir(ambient)
    with pytest.raises(FileNotFoundError, match='selected checkout'):
        measurement.publication_fixture(selected)


def test_fixture_symlink_cannot_select_another_checkouts_source(tmp_path):
    selected = tmp_path / 'selected'
    link = selected / 'packages/viewer_publication/tests/test_viewer_publication_attempt.py'
    link.parent.mkdir(parents=True)
    outside = tmp_path / 'ambient.py'
    outside.touch()
    link.symlink_to(outside)
    with pytest.raises(ValueError, match='escapes the selected checkout'):
        measurement.publication_fixture(selected)
