"""Admission accounts for application preparation and the native owner's scratch."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from congress_api.retention import native_capacity as capacity


def client(tmp_path, scratch=100):
    limits = tmp_path / "limits.json"
    limits.write_text(json.dumps({"scratch_bytes": scratch}))
    return SimpleNamespace(workspace=tmp_path / "native", limits=limits)


def filesystem(monkeypatch, free=1000, devices=None):
    monkeypatch.setattr(capacity, "_filesystem", lambda path: (
        (devices or {}).get(Path(path).name, 1), str(path), free))


def test_same_filesystem_adds_native_and_preparation_once(tmp_path, monkeypatch):
    filesystem(monkeypatch)
    receipt = capacity.require_adoption_capacity(client(tmp_path), tmp_path / "stage",
                                                 200, headroom_bytes=50)
    assert receipt["filesystems"][0]["required_free_bytes"] == 350
    assert receipt["native_scratch_bytes"] == 100
    assert not (tmp_path / "stage").exists()
    assert not (tmp_path / "native").exists()


def test_retained_stage_is_not_charged_twice_or_modified(tmp_path, monkeypatch):
    filesystem(monkeypatch, free=260)
    stage = tmp_path / "stage"
    stage.mkdir()
    retained = stage / "retained.parquet"
    retained.write_bytes(b"x" * 100)
    receipt = capacity.require_adoption_capacity(client(tmp_path), stage, 200,
                                                 headroom_bytes=50)
    assert receipt["staging_retained_bytes"] == 100
    assert receipt["filesystems"][0]["required_free_bytes"] == 250
    assert retained.read_bytes() == b"x" * 100


def test_separate_filesystems_keep_independent_requirements(tmp_path, monkeypatch):
    filesystem(monkeypatch, free=260, devices={"stage": 1, "native": 2})
    receipt = capacity.require_adoption_capacity(client(tmp_path), tmp_path / "stage",
                                                 200, headroom_bytes=50)
    assert sorted(row["required_free_bytes"] for row in receipt["filesystems"]) == [150, 250]


def test_insufficient_space_refuses_without_creating_stage(tmp_path, monkeypatch):
    filesystem(monkeypatch, free=349)
    with pytest.raises(capacity.AdoptionCapacityError) as caught:
        capacity.require_adoption_capacity(client(tmp_path), tmp_path / "stage",
                                            200, headroom_bytes=50)
    assert caught.value.receipt["filesystems"][0]["required_free_bytes"] == 350
    assert "1 additional bytes" in str(caught.value)
    assert not (tmp_path / "stage").exists()


@pytest.mark.parametrize("invalid", [True, 0, -1, 1.5, "100"])
def test_invalid_native_limits_refuse(tmp_path, monkeypatch, invalid):
    filesystem(monkeypatch)
    with pytest.raises(ValueError, match="scratch_bytes"):
        capacity.require_adoption_capacity(client(tmp_path, invalid), tmp_path / "stage",
                                            200, headroom_bytes=50)


def test_missing_override_uses_qualified_native_default(tmp_path, monkeypatch):
    filesystem(monkeypatch, free=100 << 30)
    native = SimpleNamespace(workspace=tmp_path / "native", limits=None)
    receipt = capacity.require_adoption_capacity(native, tmp_path / "stage", 200)
    assert receipt["native_scratch_bytes"] == 32 << 30
    assert receipt["headroom_bytes"] == 8 << 30


def test_stage_symlinks_are_not_counted_as_owned_preparation(tmp_path, monkeypatch):
    filesystem(monkeypatch)
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "external").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="symlink"):
        capacity.require_adoption_capacity(client(tmp_path), stage, 200,
                                            headroom_bytes=50)


def test_preparation_estimate_uses_uncompressed_metadata_not_payload(monkeypatch):
    metadata = SimpleNamespace(num_rows=3, num_row_groups=2,
        row_group=lambda i: SimpleNamespace(total_byte_size=[100, 200][i]))
    assert capacity.preparation_budget(metadata) == 2 * 300 + 4096 * 3 + (1 << 20)
