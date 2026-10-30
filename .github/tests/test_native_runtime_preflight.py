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


def test_runtime_preflight_reads_committed_pin_file_and_binary_forbids_path_fallback(tmp_path, monkeypatch):
    from docspec_client import QUALIFIED_DOCSPEC_RUNTIME, RUNTIME_PIN_FILE, load_runtime_pin, resolve_docspec_binary
    pin = load_runtime_pin(RUNTIME_PIN_FILE)
    assert pin['source_revision'] == QUALIFIED_DOCSPEC_RUNTIME['source_revision']
    assert set(pin['platforms']) == {'darwin-arm64', 'linux-amd64'}
    assert pin['platforms']['darwin-arm64']['sha256'] == QUALIFIED_DOCSPEC_RUNTIME['darwin_arm64_binary_sha256']
    assert pin['platforms']['linux-amd64']['sha256'] == QUALIFIED_DOCSPEC_RUNTIME['linux_amd64_binary_sha256']

    value = module()
    binary = tmp_path / 'docspec'
    binary.write_bytes(b'\x7fELFfixture-pinned-binary')
    binary.chmod(0o700)
    digest = sha256(binary.read_bytes()).hexdigest()
    custom_pin = tmp_path / 'pin.json'
    custom_pin.write_text(json.dumps({
        'version': 1,
        'source_revision': pin['source_revision'],
        'build_features': ['remote'],
        'required_capabilities': ['request-deadline', 'owned-stdin-eof'],
        'platforms': {'linux-amd64': {'sha256': digest}},
    }))
    config = tmp_path / 'runtime.json'
    config.write_text(json.dumps({
        'version': 1,
        'binary': str(binary),
        'workspace': str(tmp_path / 'native'),
        'platform': 'linux-amd64',
        'source_revision': pin['source_revision'],
        'build_features': ['remote'],
        'binary_sha256': digest,
    }))
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('Native process started'))
    report = value.check(config, pin_file=custom_pin)
    assert report['verified'] and report['binary_sha256'] == digest

    fake_bin_dir = tmp_path / 'path-bin'
    fake_bin_dir.mkdir()
    fake_docspec = fake_bin_dir / 'docspec'
    fake_docspec.write_bytes(b'#!/bin/sh\nexit 0\n')
    fake_docspec.chmod(0o755)
    monkeypatch.setenv('PATH', str(fake_bin_dir))
    monkeypatch.delenv('DOCSPEC_BINARY', raising=False)
    monkeypatch.delenv('DOCSPEC_BIN', raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError, match='Unable to locate native docspec binary'):
        resolve_docspec_binary()
