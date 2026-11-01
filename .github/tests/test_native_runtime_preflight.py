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
    with pytest.raises(ValueError, match='committed runtime pin file'):
        value.check(config, expected)
    report = value.check(config, expected, pin_file=None)
    assert report['verified'] and report['binary_sha256'] == expected
    assert report['execution_sha256'][str(config)] == sha256(config.read_bytes()).hexdigest()
    assert not (tmp_path / 'native').exists()
    with pytest.raises(ValueError, match='binary'):
        value.check(config, '0' * 64, pin_file=None)
    binary.unlink()
    with pytest.raises(ValueError, match='binary'):
        value.check(config, expected, pin_file=None)


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
    with pytest.raises(ValueError, match='committed runtime pin file'):
        value.check(config, 'f' * 64, pin_file=custom_pin)
    with pytest.raises(ValueError, match='source_revision'):
        value.check(config, digest, expected_source_revision='0' * 40, pin_file=custom_pin)

    unpinned_binary = tmp_path / 'unpinned-docspec'
    unpinned_binary.write_bytes(b'\x7fELFfixture-unpinned-binary')
    unpinned_binary.chmod(0o700)
    unpinned_digest = sha256(unpinned_binary.read_bytes()).hexdigest()
    config_no_platform = tmp_path / 'runtime-no-platform.json'
    config_no_platform.write_text(json.dumps({
        'version': 1,
        'binary': str(unpinned_binary),
        'workspace': str(tmp_path / 'native'),
        'source_revision': pin['source_revision'],
        'build_features': ['remote'],
    }))
    with pytest.raises(ValueError, match='committed runtime pin file'):
        value.check(config_no_platform, unpinned_digest, pin_file=custom_pin)
    config_no_platform.write_text(json.dumps({
        'version': 1,
        'binary': str(binary),
        'workspace': str(tmp_path / 'native'),
        'source_revision': pin['source_revision'],
        'build_features': ['remote'],
    }))
    resolved_report = value.check(config_no_platform, digest, pin_file=custom_pin)
    assert resolved_report['verified'] and resolved_report['platform'] == 'linux-amd64'

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
