"""Native CI fixtures request finite budgets without changing caller assertions."""
import json
import os
from pathlib import Path

import pytest

import native_test_helpers as helpers
from docspec_client import NativeDatasets
from news_lake.storage.docspec import DocSpecClient

PROFILE = dict(compute_threads=2, memory_bytes=2 << 30, scratch_bytes=2 << 30,
               batch_rows=8192, max_batch_bytes=8 << 20, max_metadata_bytes=32 << 20)


@pytest.fixture
def binary(tmp_path):
    path=tmp_path/'docspec';path.write_text('#!/bin/sh\nexit 1\n');path.chmod(0o755)
    return path


def test_shared_profile_is_finite_and_same_workspace_reuse_preserves_it(tmp_path):
    workspace=tmp_path/'workspace'
    path=helpers.native_ci_limits(workspace)
    assert json.loads(path.read_text()) == PROFILE
    os.utime(path,ns=(1_000_000_000,1_000_000_000))
    assert helpers.native_ci_limits(workspace) == path
    assert path.stat().st_mtime_ns == 1_000_000_000


def test_shared_profile_refuses_a_changed_existing_file(tmp_path):
    path=helpers.native_ci_limits(tmp_path/'workspace')
    path.write_text(json.dumps(dict(PROFILE,scratch_bytes=32 << 30)))
    with pytest.raises(ValueError,match='limits|profile'):
        helpers.native_ci_limits(tmp_path/'workspace')
    assert json.loads(path.read_text())['scratch_bytes'] == 32 << 30


@pytest.mark.parametrize('kind',['native','news'])
def test_ci_clients_reuse_profile_and_preserve_base_client_type(tmp_path,binary,kind,monkeypatch):
    workspace=tmp_path/'workspace'
    monkeypatch.setenv('DOCSPEC_BINARY',str(binary))
    if kind=='native':
        client=helpers.NativeCITestClient(binary,workspace,timeout=7)
        assert isinstance(client,NativeDatasets)
    else:
        client=helpers.NewsCITestClient(workspace,binary=str(binary),timeout=7)
        assert isinstance(client,DocSpecClient)
        assert helpers.NewsCITestClient.default_binary_path() == str(binary)
    try:
        assert client.limits == helpers.native_ci_limits(workspace)
        assert json.loads(client.limits.read_text()) == PROFILE
        assert client.timeout == 7
    finally:client.close()


@pytest.mark.parametrize('kind',['native','news'])
def test_ci_clients_preserve_explicit_tight_limits(tmp_path,binary,kind):
    tight=tmp_path/'tight.json'
    tight.write_text(json.dumps(dict(PROFILE,memory_bytes=128 << 20,scratch_bytes=4 << 20)))
    before=tight.read_bytes();workspace=tmp_path/'workspace'
    if kind=='native':client=helpers.NativeCITestClient(binary,workspace,limits=tight)
    else:client=helpers.NewsCITestClient(workspace,binary=str(binary),limits=tight)
    try:
        assert client.limits == tight
        assert tight.read_bytes() == before
        assert not (workspace/'ci-test-limits.json').exists()
    finally:client.close()


def test_existing_tiny_native_fixture_stays_tiny(tmp_path,binary):
    with helpers.native_test_client(binary,tmp_path/'tiny') as client:
        assert json.loads(client.limits.read_text()) == dict(compute_threads=2,memory_bytes=512 << 20,
            scratch_bytes=256 << 20,batch_rows=2,max_batch_bytes=4 << 20,max_metadata_bytes=8 << 20)
