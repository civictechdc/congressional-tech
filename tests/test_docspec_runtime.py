"""Explicit runtime settings isolate credentials from the parent process."""
import json
import os
from pathlib import Path
import subprocess

import pytest
import httpx

from congress_api.retention.docspec import NativeDatasets


def settings(tmp_path, *, remote=True):
    value = dict(version=1, binary="bin/docspec", workspace="workspace",
                 limits="limits.json", timeout_seconds=120)
    (tmp_path / "limits.json").write_text("{}")
    if remote:
        value.update(remote="remote.json", credentials="credentials.json")
        (tmp_path / "remote.json").write_text(json.dumps(dict(
            owned_prefix="s3://fixture/explicit-prefix",
            properties={"uri": "https://catalog.example.test"},
            secret_env={"token": "DOCSPEC_CATALOG_TOKEN"})))
        credential = tmp_path / "credentials.json"
        credential.write_text(json.dumps({"DOCSPEC_CATALOG_TOKEN": "fixture-private-value"}))
        credential.chmod(0o600)
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(value))
    return path


def test_configuration_is_side_effect_free_and_scopes_credentials_to_child(tmp_path, monkeypatch):
    path = settings(tmp_path)
    monkeypatch.setenv("DOCSPEC_CATALOG_TOKEN", "different-ambient-value")
    original = dict(os.environ)
    native = NativeDatasets.from_config(path)
    assert not native.workspace.exists()
    assert native.binary == str(tmp_path / "bin/docspec")
    assert native.remote == tmp_path / "remote.json"
    assert native.limits == tmp_path / "limits.json"
    calls = []

    class Process:
        returncode = None
        pid = 123456789
        def poll(self):
            return self.returncode
        def send_signal(self, signal):
            self.returncode = 0
        def wait(self, **kwargs):
            return self.returncode

    def start(command, **kwargs):
        calls.append((command, kwargs))
        ready = Path(command[command.index('--ready-file') + 1])
        ready.write_text(json.dumps(dict(protocol='docspec-loopback', version=1,
            capabilities=['request-deadline'], pid=Process.pid, address='127.0.0.1:7391')))
        ready.chmod(0o600)
        return Process()

    client_class = httpx.Client
    def client(**kwargs):
        return client_class(**kwargs, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={'configured': True})))

    monkeypatch.setattr(subprocess, 'Popen', start)
    monkeypatch.setattr('congress_api.retention.docspec_host.httpx.Client', client)
    assert native.latest("fixture") == {"configured": True}
    command, kwargs = calls[0]
    assert "fixture-private-value" not in repr(command)
    assert kwargs["env"]["DOCSPEC_CATALOG_TOKEN"] == "fixture-private-value"
    assert kwargs["env"]["PATH"] == original["PATH"]
    assert dict(os.environ) == original
    assert not native.workspace.exists()
    native.close()


def test_local_hash_does_not_receive_remote_credentials(tmp_path, monkeypatch):
    native = NativeDatasets.from_config(settings(tmp_path))
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout='{"digest":"fixture"}', stderr="")
    monkeypatch.setattr(subprocess, "run", run)
    native.hash_input(tmp_path / "input.parquet")
    assert "--remote" not in calls[0][0]
    assert calls[0][1].get("env") is None


def test_local_configuration_needs_no_remote_or_credentials(tmp_path):
    native = NativeDatasets.from_config(settings(tmp_path, remote=False))
    assert native.remote is None
    assert native.workspace == tmp_path / "workspace"
    assert not native.workspace.exists()


@pytest.mark.parametrize("change", [
    {"version": 2}, {"workspace": ""}, {"timeout_seconds": 0},
    {"timeout_seconds": float("inf")}, {"timeout_seconds": True},
    {"unknown": "typo"}, {"credentials": None},
])
def test_invalid_runtime_configuration_refuses_before_process_or_writes(tmp_path, monkeypatch, change):
    path = settings(tmp_path)
    value = json.loads(path.read_text())
    value.update(change)
    path.write_text(json.dumps(value))
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("must not execute"))
    with pytest.raises(ValueError):
        NativeDatasets.from_config(path)
    assert not (tmp_path / "workspace").exists()


@pytest.mark.parametrize("credential", [{}, {"DOCSPEC_CATALOG_TOKEN": ""},
    {"DOCSPEC_CATALOG_TOKEN": 10}, {"DOCSPEC_CATALOG_TOKEN": "value", "PATH": "override"}])
def test_credentials_must_match_declared_native_secret_references(tmp_path, credential):
    path = settings(tmp_path)
    (tmp_path / "credentials.json").write_text(json.dumps(credential))
    with pytest.raises(ValueError, match="credentials"):
        NativeDatasets.from_config(path)


def test_shared_readable_credentials_refuse(tmp_path):
    path = settings(tmp_path)
    (tmp_path / "credentials.json").chmod(0o644)
    with pytest.raises(ValueError, match="permissions"):
        NativeDatasets.from_config(path)


def test_non_docspec_environment_override_refuses(tmp_path):
    path = settings(tmp_path)
    remote = json.loads((tmp_path / "remote.json").read_text())
    remote["secret_env"] = {"token": "PATH"}
    (tmp_path / "remote.json").write_text(json.dumps(remote))
    with pytest.raises(ValueError, match="DOCSPEC_"):
        NativeDatasets.from_config(path)


def test_execution_files_name_only_frozen_inputs_and_exclude_workspace_and_secrets(tmp_path):
    path = settings(tmp_path)
    native = NativeDatasets.from_config(path)
    assert native.execution_files() == (path, tmp_path / 'bin/docspec', tmp_path / 'remote.json', tmp_path / 'limits.json')
    assert not native.workspace.exists()
    direct = NativeDatasets(tmp_path / 'direct', tmp_path / 'scratch')
    assert direct.execution_files() == (tmp_path / 'direct',)
    assert 'fixture-private-value' not in repr(native.execution_files())
