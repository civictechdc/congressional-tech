"""Unit tests for congress_shared.custody and congress_shared.storage."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import pytest

from congress_shared.custody import (
    VerifiedFile,
    canonical_json_bytes,
    copy_checked,
    custody_identity,
    file_identity,
    issue_verified_file,
    iter_canonical_digest,
    read_bound_receipt,
    verify_local_file,
    write_atomic_bytes,
    write_atomic_json,
    write_bound_receipt,
)
from congress_shared.storage import R2Config, connect_r2


def test_verified_file_attributes_and_mapping_compatibility(tmp_path: Path) -> None:
    target = tmp_path / "sample.bin"
    payload = b"congress-shared-custody-payload"
    target.write_bytes(payload)
    digest = sha256(payload).hexdigest()

    verified = verify_local_file(target)
    assert isinstance(verified, VerifiedFile)
    assert isinstance(verified, dict)
    assert verified.path == target
    assert verified.sha256 == digest
    assert verified.size_bytes == len(payload)
    assert verified["sha256"] == digest
    assert verified["bytes"] == len(payload)
    assert dict(verified) == {"sha256": digest, "bytes": len(payload)}
    assert verified.require(target) is verified

    with pytest.raises(AttributeError):
        verified.sha256 = "0" * 64  # type: ignore[misc]
    with pytest.raises(AttributeError):
        verified.size_bytes = 0  # type: ignore[misc]


def test_verify_local_file_enforces_expectations_and_custody(tmp_path: Path) -> None:
    target = tmp_path / "checked.txt"
    payload = b"verified content"
    target.write_bytes(payload)
    digest = sha256(payload).hexdigest()

    assert verify_local_file(target, expected_sha256=digest, expected_size=len(payload)).sha256 == digest
    assert file_identity(target) == {"sha256": digest, "bytes": len(payload)}

    with pytest.raises(ValueError, match="size mismatch"):
        verify_local_file(target, expected_size=len(payload) + 1)

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        verify_local_file(target, expected_sha256="0" * 64)

    symlink = tmp_path / "link.txt"
    symlink.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        custody_identity(symlink)


def test_write_atomic_bytes_unique_and_fixed_modes_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unique_target = tmp_path / "nested" / "unique.bin"
    vf_unique = write_atomic_bytes(unique_target, b"alpha", temp_mode="unique")
    assert unique_target.read_bytes() == b"alpha"
    assert vf_unique.path == unique_target
    assert vf_unique.size_bytes == 5
    assert vf_unique.sha256 == sha256(b"alpha").hexdigest()
    assert vf_unique.require(unique_target) is vf_unique

    fixed_target = tmp_path / "nested" / "fixed.json"
    vf_fixed = write_atomic_bytes(fixed_target, b"beta", temp_mode="fixed")
    assert fixed_target.read_bytes() == b"beta"
    assert not fixed_target.with_suffix(".json.tmp").exists()
    assert vf_fixed.size_bytes == 4

    def fail_replace(self: Path, target: Path) -> Path:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        write_atomic_bytes(fixed_target, b"gamma", temp_mode="fixed")
    assert fixed_target.read_bytes() == b"beta"
    assert not fixed_target.with_suffix(".json.tmp").exists()

    with pytest.raises(OSError, match="simulated replace failure"):
        write_atomic_bytes(unique_target, b"delta", temp_mode="unique")
    assert unique_target.read_bytes() == b"alpha"
    assert list(unique_target.parent.glob("*.tmp")) == []


def test_canonical_json_bytes_and_write_bound_receipt(tmp_path: Path) -> None:
    payload = {"b": [1, 2], "a": "José 雪"}
    encoded = canonical_json_bytes(payload)
    assert encoded == '{"a":"José 雪","b":[1,2]}'.encode("utf-8")

    receipt_path = tmp_path / "receipts" / "bound.json"
    verified = write_bound_receipt(receipt_path, payload, temp_mode="fixed")
    expected_bytes = '{"a":"José 雪","b":[1,2]}\n'.encode("utf-8")
    assert receipt_path.read_bytes() == expected_bytes
    assert verified.sha256 == sha256(expected_bytes).hexdigest()
    assert verified.size_bytes == len(expected_bytes)
    assert verified.require(receipt_path) is verified


def test_relative_paths_canonicalize_to_absolute_paths_and_extended_custody_helpers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    rel = Path("subdir/relative.json")

    vf_written = write_atomic_bytes(rel, b"hello", temp_mode="unique")
    assert vf_written.path.is_absolute()
    assert vf_written.path == vf_written.target == (tmp_path / rel).resolve()
    assert vf_written["path"] == vf_written.path

    vf_verified = verify_local_file(rel)
    assert vf_verified.path.is_absolute()
    assert vf_verified.path == vf_verified.target == (tmp_path / rel).resolve()
    assert vf_verified["path"] == vf_verified.path

    vf_issued = issue_verified_file(rel, {"sha256": vf_verified.sha256, "bytes": vf_verified.size_bytes})
    assert vf_issued.path.is_absolute()
    assert vf_issued.path == vf_issued.target == (tmp_path / rel).resolve()
    assert vf_issued["path"] == vf_issued.path

    json_rel = Path("subdir/atomic.json")
    vf_json = write_atomic_json(json_rel, {"status": "ok", "count": 3})
    assert vf_json.path.is_absolute()
    parsed = read_bound_receipt(
        json_rel,
        expected_fields={"status": "ok", "count": 3},
        expected_sha256=vf_json.sha256,
        expected_size=vf_json.size_bytes,
    )
    assert parsed == {"status": "ok", "count": 3}
    with pytest.raises(ValueError, match="field mismatch"):
        read_bound_receipt(json_rel, expected_fields={"status": "mismatch"})

    copied_rel = Path("subdir/copied.json")
    vf_copied = copy_checked(
        json_rel,
        copied_rel,
        expected_sha256=vf_json.sha256,
        expected_bytes=vf_json.size_bytes,
    )
    assert vf_copied.path.is_absolute()
    assert vf_copied.sha256 == vf_json.sha256
    assert vf_copied.size_bytes == vf_json.size_bytes

    items = [{"k": 1, "b": "x"}, {"a": True, "k": 2}]
    expected_stream = canonical_json_bytes(items[0], trailing_newline=True) + canonical_json_bytes(
        items[1], trailing_newline=True
    )
    assert iter_canonical_digest(items) == sha256(expected_stream).hexdigest()


def test_r2_config_and_connect_r2() -> None:
    env = {
        "CLOUDFLARE_ACCOUNT_ID": "acct-123",
        "R2_ACCESS_KEY_ID": "key-id",
        "R2_SECRET_ACCESS_KEY": "secret-key",
    }
    cfg = R2Config.from_env(env=env, max_pool_connections=12)
    assert cfg.endpoint_url == "https://acct-123.r2.cloudflarestorage.com"
    assert cfg.access_key_id == "key-id"
    assert cfg.secret_access_key == "secret-key"
    assert cfg.max_pool_connections == 12

    with pytest.raises(ValueError, match="CLOUDFLARE_ACCOUNT_ID"):
        R2Config.from_env(env={})

    captured: dict[str, object] = {}

    def fake_client(service: str, **kwargs: object) -> object:
        captured["service"] = service
        captured.update(kwargs)
        return object()

    with patch("boto3.client", side_effect=fake_client):
        client = connect_r2(env=env, max_pool_connections=12)
    assert client is not None
    assert captured["service"] == "s3"
    assert captured["endpoint_url"] == "https://acct-123.r2.cloudflarestorage.com"
    assert captured["aws_access_key_id"] == "key-id"
    assert captured["aws_secret_access_key"] == "secret-key"
    assert captured["region_name"] == "auto"
    assert "config" in captured


@pytest.mark.parametrize("change", ["add", "remove"])
def test_verified_file_rejects_link_changes_with_unchanged_timestamps(tmp_path, monkeypatch, change):
    import os
    import congress_shared.custody as custody

    target = tmp_path / "verified"
    target.write_bytes(b"unchanged payload")
    alias = tmp_path / "alias"
    if change == "remove":
        os.link(target, alias)
    original_identity = custody.custody_identity
    def unchanged_timestamps(path):
        identity = list(original_identity(path))
        identity[3:5] = [1, 1]
        return tuple(identity)
    monkeypatch.setattr(custody, "custody_identity", unchanged_timestamps)
    verified = custody.issue_verified_file(target, {"bytes": target.stat().st_size,
        "sha256": sha256(target.read_bytes()).hexdigest()})
    verified.require(target)
    if change == "remove":
        alias.unlink()
    else:
        os.link(target, alias)
    assert target.read_bytes() == b"unchanged payload"
    with pytest.raises(ValueError, match="custody"):
        verified.require(target)


def test_require_rejects_same_size_rewrite_when_timestamps_do_not_change(tmp_path, monkeypatch):
    import congress_shared.custody as custody
    target = tmp_path / "verified"
    target.write_bytes(b"original")
    original_identity = custody.custody_identity
    def unchanged_timestamps(path):
        identity = list(original_identity(path))
        identity[3:5] = [1, 1]
        return tuple(identity)
    monkeypatch.setattr(custody, "custody_identity", unchanged_timestamps)
    verified = custody.issue_verified_file(target, {"bytes": 8,
        "sha256": sha256(b"original").hexdigest()})
    verified.require(target)
    target.write_bytes(b"replaced")
    assert custody.custody_identity(target) == verified.custody
    with pytest.raises(ValueError, match="custody"):
        verified.require(target)


def test_require_does_not_turn_an_unchecked_digest_into_byte_authority(tmp_path):
    target = tmp_path / "verified"
    target.write_bytes(b"payload")
    verified = VerifiedFile(target, "0" * 64, 7)
    with pytest.raises(ValueError, match="custody"):
        verified.require(target)
