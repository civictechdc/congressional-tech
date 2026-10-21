"""Explicit runtime settings isolate credentials from the parent process."""
from hashlib import sha256
import json
import io
import os
from pathlib import Path
import subprocess

import pytest
import httpx

from congress_api.retention.docspec import (
    QUALIFIED_DOCSPEC_RUNTIME,
    REQUIRED_LOOPBACK_CAPABILITIES,
    NativeDatasets,
)


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
        stdin = io.BytesIO()
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
            capabilities=['request-deadline', 'owned-stdin-eof'], pid=Process.pid, address='127.0.0.1:7391')))
        ready.chmod(0o600)
        return Process()

    client_class = httpx.Client
    def client(**kwargs):
        return client_class(**kwargs, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={'configured': True})))

    monkeypatch.setattr(subprocess, 'Popen', start)
    monkeypatch.setattr('docspec_client.docspec_host.httpx.Client', client)
    assert native.latest("fixture") == {"configured": True}
    command, kwargs = calls[0]
    assert "fixture-private-value" not in repr(command)
    assert kwargs["env"]["DOCSPEC_CATALOG_TOKEN"] == "fixture-private-value"
    assert kwargs["env"]["PATH"] == original["PATH"]
    assert kwargs['stdin'] == subprocess.PIPE
    assert '--shutdown-on-stdin-eof' in command
    assert dict(os.environ) == original
    assert not native.workspace.exists()
    native.close()
    assert Process.stdin.closed


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


def _write_qualified_binary(path, *, header=b'\xcf\xfa\xed\xfe', executable=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = header + b'-qualified-docspec-runtime-binary'
    path.write_bytes(raw)
    path.chmod(0o700 if executable else 0o600)
    return sha256(raw).hexdigest()


def test_qualified_runtime_descriptor_binds_commit_platform_features_digest_and_capabilities(tmp_path):
    path = settings(tmp_path)
    digest = _write_qualified_binary(tmp_path / 'bin/docspec', header=b'\xcf\xfa\xed\xfe')
    config = json.loads(path.read_text())
    config.update(
        source_revision=QUALIFIED_DOCSPEC_RUNTIME['source_revision'],
        platform='darwin-arm64',
        build_features=['remote'],
        binary_sha256=digest,
        required_capabilities=list(REQUIRED_LOOPBACK_CAPABILITIES),
    )
    path.write_text(json.dumps(config))
    native = NativeDatasets.from_config(path)
    report = native.verify_runtime(
        expected_sha256=digest,
        expected_platform='darwin-arm64',
        expected_source_revision=QUALIFIED_DOCSPEC_RUNTIME['source_revision'],
        required_features=('remote',),
        required_capabilities=REQUIRED_LOOPBACK_CAPABILITIES,
    )
    assert report == dict(
        verified=True,
        binary_sha256=digest,
        platform='darwin-arm64',
        source_revision=QUALIFIED_DOCSPEC_RUNTIME['source_revision'],
        build_features=('remote',),
        required_capabilities=REQUIRED_LOOPBACK_CAPABILITIES,
    )
    assert not native.workspace.exists()


@pytest.mark.parametrize(
    'scenario, expected_match',
    [
        ('missing_binary', 'missing or not executable'),
        ('non_executable', 'missing or not executable'),
        ('wrong_sha256', 'approved SHA-256'),
        ('wrong_platform_header', 'platform does not match'),
        ('wrong_expected_platform', 'platform differs'),
        ('missing_remote_feature', 'remote build feature'),
        ('missing_requested_feature', 'missing required build features'),
        ('missing_capability', 'request-deadline and owned-stdin-eof'),
    ],
)
def test_runtime_preflight_fails_fast_before_source_or_catalog_access(tmp_path, monkeypatch, scenario, expected_match):
    path = settings(tmp_path)
    binary_path = tmp_path / 'bin/docspec'
    header = b'\x7fELF' if scenario == 'wrong_platform_header' else b'\xcf\xfa\xed\xfe'
    digest = _write_qualified_binary(
        binary_path,
        header=header,
        executable=(scenario != 'non_executable'),
    )
    if scenario == 'missing_binary':
        binary_path.unlink()
    config = json.loads(path.read_text())
    config.update(
        source_revision=QUALIFIED_DOCSPEC_RUNTIME['source_revision'],
        platform='darwin-arm64',
        build_features=['local-only'] if scenario == 'missing_remote_feature' else ['remote'],
        binary_sha256='0' * 64 if scenario == 'wrong_sha256' else digest,
        required_capabilities=['request-deadline'] if scenario == 'missing_capability' else list(REQUIRED_LOOPBACK_CAPABILITIES),
    )
    path.write_text(json.dumps(config))
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('Native process must not start'))
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('Native process must not start'))

    with pytest.raises(ValueError, match=expected_match) as exc_info:
        native = NativeDatasets.from_config(path)
        if scenario == 'wrong_expected_platform':
            native.verify_runtime(expected_platform='linux-amd64')
        elif scenario == 'missing_requested_feature':
            native.verify_runtime(required_features=('remote', 'nonexistent-feature'))
        else:
            native.latest('fixture')
    assert 'fixture-private-value' not in str(exc_info.value)
    assert not (tmp_path / 'workspace').exists()


def test_host_refuses_readiness_missing_required_loopback_capability(tmp_path, monkeypatch):
    path = settings(tmp_path)
    digest = _write_qualified_binary(tmp_path / 'bin/docspec', header=b'\xcf\xfa\xed\xfe')
    config = json.loads(path.read_text())
    config.update(
        source_revision=QUALIFIED_DOCSPEC_RUNTIME['source_revision'],
        platform='darwin-arm64',
        build_features=['remote'],
        binary_sha256=digest,
        required_capabilities=list(REQUIRED_LOOPBACK_CAPABILITIES),
    )
    path.write_text(json.dumps(config))
    native = NativeDatasets.from_config(path)

    class Process:
        returncode = None
        pid = 987654
        stdin = io.BytesIO()
        def poll(self):
            return self.returncode
        def send_signal(self, signal):
            self.returncode = 0
        def wait(self, **kwargs):
            return self.returncode

    def start(command, **kwargs):
        ready = Path(command[command.index('--ready-file') + 1])
        ready.write_text(json.dumps(dict(
            protocol='docspec-loopback',
            version=1,
            capabilities=['request-deadline'],
            pid=Process.pid,
            address='127.0.0.1:7391',
        )))
        ready.chmod(0o600)
        return Process()

    monkeypatch.setattr(subprocess, 'Popen', start)
    with pytest.raises(ValueError, match='owned-stdin-eof') as exc_info:
        native.latest('fixture')
    assert 'fixture-private-value' not in str(exc_info.value)


def test_live_unified_docspec_binary_matches_qualified_contract(tmp_path):
    binary_env = os.environ.get('DOCSPEC_BINARY')
    candidate = Path(binary_env) if binary_env else Path('/Users/mikewolfd/Work/spicy-stack/docspec-rs/target/debug/docspec')
    if not candidate.is_file():
        pytest.skip('Local unified docspec binary not present')
    with candidate.open('rb') as source:
        actual_sha = sha256(source.read()).hexdigest()
    native = NativeDatasets(
        candidate,
        tmp_path / 'workspace',
        source_revision=QUALIFIED_DOCSPEC_RUNTIME['source_revision'],
        platform='darwin-arm64',
        build_features=list(QUALIFIED_DOCSPEC_RUNTIME['build_features']),
        binary_sha256=actual_sha,
        required_capabilities=list(QUALIFIED_DOCSPEC_RUNTIME['required_capabilities']),
    )
    report = native.verify_runtime(
        expected_sha256=QUALIFIED_DOCSPEC_RUNTIME['darwin_arm64_binary_sha256'],
        expected_platform='darwin-arm64',
        expected_source_revision=QUALIFIED_DOCSPEC_RUNTIME['source_revision'],
        required_features=('remote',),
    )
    assert report['verified'] is True
    assert report['binary_sha256'] == QUALIFIED_DOCSPEC_RUNTIME['darwin_arm64_binary_sha256']
    sample = tmp_path / 'sample.bin'
    sample.write_bytes(b'docspec-qualified-hash-probe')
    hashed = native.hash_input(sample)
    assert isinstance(hashed.get('digest'), str) and len(hashed['digest']) == 64


def test_update_table_retains_replacements_and_deletions_after_indeterminate_outcome(
        tmp_path):
    from congress_api.retention.docspec_host import DocSpecFailure

    client = NativeDatasets(tmp_path / "docspec", tmp_path / "workspace")
    replacements = tmp_path / "replacements.parquet"
    replacements.write_bytes(b"replacements")
    deletions = tmp_path / "deletions.parquet"
    deletions.write_bytes(b"deletions")

    def fail(*args, dispatch=None):
        if dispatch is not None:
            dispatch["submitted"] = True
        raise DocSpecFailure(
            [], subprocess.CompletedProcess(
                [], 500, stderr='{"code":"worker","message":"indeterminate"}'))

    client._request = fail
    with pytest.raises(DocSpecFailure):
        client.update_table(
            dataset="news_captures",
            operation="update-1",
            definition="news-v1",
            base="admit-1",
            keys=["id"],
            replacements={"path": str(replacements), "digest": "0" * 64},
            deletions={"path": str(deletions), "digest": "0" * 64},
        )

    retained = client.retained_producer_inputs()
    assert len(retained) == 1
    entry = retained[0]
    assert entry["bytes"] == len(b"replacements") + len(b"deletions")
    assert {item["path"] for item in entry["files"]} == {
        str(replacements), str(deletions)}
    assert Path(entry["request"]).is_file()


def test_update_table_cleans_up_after_deterministic_refusal(tmp_path):
    from congress_api.retention.docspec_host import DocSpecFailure

    client = NativeDatasets(tmp_path / "docspec", tmp_path / "workspace")
    replacements = tmp_path / "replacements.parquet"
    replacements.write_bytes(b"replacements")

    def refuse(*args, dispatch=None):
        if dispatch is not None:
            dispatch["submitted"] = True
        error = DocSpecFailure(
            [], subprocess.CompletedProcess(
                [], 422, stderr='{"code":"invalid_update","message":"refused"}'))
        error.status_code = 422
        raise error

    client._request = refuse
    with pytest.raises(DocSpecFailure):
        client.update_table(
            dataset="news_captures",
            operation="update-1",
            definition="news-v1",
            base="admit-1",
            keys=["id"],
            replacements={"path": str(replacements), "digest": "0" * 64},
        )
    assert client.retained_producer_inputs() == []


def test_compact_lifecycle_delegates_to_dataset_lifecycle_route(tmp_path):
    client = NativeDatasets(tmp_path / "docspec", tmp_path / "workspace")
    observed = []

    def fake_host_request(method, path, **kwargs):
        observed.append((method, path))
        return {"revisions_before": 12, "revisions_after": 1, "current_revision": 13}

    client._host_request = fake_host_request
    result = client.compact_lifecycle("news_captures")
    assert observed == [("POST", "/datasets/news_captures/lifecycle/compact")]
    assert result["revisions_after"] == 1


def test_compact_table_delegates_to_compactions_run_route(tmp_path):
    client = NativeDatasets(tmp_path / "docspec", tmp_path / "workspace")
    observed = []

    def fake_request(path, request, **kwargs):
        observed.append((path, dict(request)))
        return {"verified": True, "input_files": request["files"], "output_files": ["out.parquet"]}

    client._request = fake_request
    pin = {"dataset": {"dataset": "news_captures", "version": "append-capture-1"}}
    result = client.compact_table(
        "news_captures",
        operation="compact-1",
        version=pin,
        files=["a.parquet", "b.parquet"],
        target_file_bytes=32 * 1024 * 1024,
    )
    assert result["verified"] is True
    assert observed == [
        (
            "/compactions/run",
            {
                "dataset": "news_captures",
                "operation": "compact-1",
                "version": "append-capture-1",
                "group": "source",
                "files": ["a.parquet", "b.parquet"],
                "target_file_bytes": 32 * 1024 * 1024,
            },
        )
    ]


def test_producer_parquet_writes_bound_row_group_size_for_batch_budget(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from docspec_client.docspec import PRODUCER_PARQUET_ROW_GROUP_SIZE

    client = NativeDatasets(tmp_path / "docspec", tmp_path / "workspace")
    client.hash_input = lambda path: {"digest": "0" * 64}
    observed_row_groups = []

    def inspect_request(path, request, *, dispatch=None):
        for field in ("input", "replacements", "deletions"):
            value = request.get(field)
            file_path = value["path"] if isinstance(value, dict) else value
            if isinstance(file_path, str):
                pf = pq.ParquetFile(file_path)
                observed_row_groups.append(
                    (
                        path,
                        field,
                        pf.metadata.num_rows,
                        pf.metadata.num_row_groups,
                        [pf.metadata.row_group(i).num_rows for i in range(pf.metadata.num_row_groups)],
                    )
                )
        return {"id": "admit-1"}

    client._request = inspect_request
    rows = PRODUCER_PARQUET_ROW_GROUP_SIZE * 2 + 123
    table = pa.table({"id": [f"{i:064x}" for i in range(rows)], "body": ["x" * 64] * rows})
    deletions = pa.table({"id": [f"{i:064x}" for i in range(PRODUCER_PARQUET_ROW_GROUP_SIZE + 5)]})

    client.run_table(table, dataset="captures", operation="run-1", definition="v1")
    client.update_table(
        table,
        dataset="captures",
        operation="upd-1",
        definition="v1",
        base="admit-1",
        keys=["id"],
        deletions=deletions,
    )
    client.update_evidence_table(
        table,
        dataset="captures",
        operation="ev-1",
        definition="v1",
        base="admit-1",
        deletions=deletions,
    )

    assert len(observed_row_groups) == 5
    for route, field, total_rows, num_rgs, rg_counts in observed_row_groups:
        assert max(rg_counts) <= PRODUCER_PARQUET_ROW_GROUP_SIZE, (route, field, rg_counts)
        if total_rows == rows:
            assert num_rgs == 3
            assert rg_counts == [
                PRODUCER_PARQUET_ROW_GROUP_SIZE,
                PRODUCER_PARQUET_ROW_GROUP_SIZE,
                123,
            ]
        else:
            assert num_rgs == 2
            assert rg_counts == [PRODUCER_PARQUET_ROW_GROUP_SIZE, 5]
