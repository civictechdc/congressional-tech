"""Hosted execution refuses missing/unqualified runtime without native/network calls."""
import importlib.util
import json
import subprocess
from pathlib import Path
from hashlib import sha256

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module():
    spec = importlib.util.spec_from_file_location('native_preflight', ROOT / '.github/scripts/check-native-runtime.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_runtime_preflight_pins_execution_files_without_creating_native_workspace(tmp_path, monkeypatch):
    value = module()
    binary = tmp_path / 'docspec'
    binary.write_bytes(b'fixture-qualified-binary')
    binary.chmod(0o700)
    config = tmp_path / 'runtime.json'
    config.write_text(json.dumps(dict(version=1, binary=str(binary), workspace=str(tmp_path / 'native'))))
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('Native process started'))
    expected = sha256(binary.read_bytes()).hexdigest()
    report = value.check(config, expected)
    assert report['verified'] and report['binary_sha256'] == expected
    assert report['execution_sha256'][str(config)] == sha256(config.read_bytes()).hexdigest()
    assert not (tmp_path / 'native').exists()
    with pytest.raises(ValueError, match='binary'):
        value.check(config, '0' * 64)
    binary.unlink()
    with pytest.raises(ValueError, match='binary'):
        value.check(config, expected)
