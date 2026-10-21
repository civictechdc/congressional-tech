"""Unit tests for congress_shared.custody and congress_shared.storage."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import pytest

from congress_shared.custody import (
    VerifiedFile,
    canonical_json_bytes,
    custody_identity,
    file_identity,
    verify_local_file,
    write_atomic_bytes,
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
