"""Tests for scripts/publication/publish-docspec-runtime.py (ct-0odd)."""
from __future__ import annotations

from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path

import pytest
from docspec_client.docspec import QUALIFIED_DOCSPEC_RUNTIME, REQUIRED_LOOPBACK_CAPABILITIES

ROOT = Path(__file__).resolve().parents[3]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


from viewer_publication import publish_docspec_runtime as publish_runtime

setup_runtime = _load_module(
    "setup_native_runtime",
    ROOT / ".github" / "scripts" / "setup-native-runtime.py",
)


class _MockR2Client:
    def __init__(self, *, corrupt_readback: bool = False):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.puts: list[dict] = []
        self.corrupt_readback = corrupt_readback

    def put_object(self, **kwargs):
        bucket = kwargs["Bucket"]
        key = kwargs["Key"]
        body = kwargs["Body"]
        raw = body.read() if hasattr(body, "read") else bytes(body)
        assert kwargs["ContentLength"] == len(raw)
        self.objects[(bucket, key)] = raw
        self.puts.append({**kwargs, "Body": raw})
        return {"ETag": '"mock-etag"'}

    def get_object(self, *, Bucket: str, Key: str):
        raw = self.objects[(Bucket, Key)]
        if self.corrupt_readback:
            raw = raw[:-1] + bytes([raw[-1] ^ 0xFF])
        return {
            "ContentLength": len(raw),
            "Body": io.BytesIO(raw),
            "ETag": '"mock-etag"',
        }


def test_generated_descriptor_passes_setup_native_runtime_validation(tmp_path: Path):
    binary = tmp_path / "docspec"
    payload = b"\x7fELF-mock-docspec-4b29482-linux-amd64-binary"
    binary.write_bytes(payload)
    expected_sha = sha256(payload).hexdigest()

    output_file = tmp_path / "descriptor.json"
    rc = publish_runtime.main(
        [
            "--binary",
            str(binary),
            "--bucket",
            "congressional-tech-runtime",
            "--output",
            str(output_file),
        ]
    )
    assert rc == 0
    raw_json = output_file.read_text(encoding="utf-8")
    validated = setup_runtime.artifact_descriptor(raw_json)

    assert validated["version"] == 1
    assert validated["platform"] == "linux-amd64"
    assert validated["source_revision"] == QUALIFIED_DOCSPEC_RUNTIME["source_revision"]
    assert validated["bucket"] == "congressional-tech-runtime"
    assert validated["bytes"] == len(payload)
    assert validated["sha256"] == expected_sha
    assert validated["key"] == (
        f"runtime/docspec/{QUALIFIED_DOCSPEC_RUNTIME['source_revision']}/"
        f"linux-amd64/{expected_sha}/docspec"
    )
    assert validated["build_features"] == ["remote"]
    assert set(REQUIRED_LOOPBACK_CAPABILITIES).issubset(validated["required_capabilities"])


def test_upload_verifies_exact_byte_length_and_sha256(tmp_path: Path):
    binary = tmp_path / "docspec"
    payload = b"\x7fELF-upload-verified-binary" * 128
    binary.write_bytes(payload)
    expected_sha = sha256(payload).hexdigest()

    client = _MockR2Client()
    output_file = tmp_path / "uploaded-descriptor.json"
    rc = publish_runtime.main(
        [
            "--binary",
            str(binary),
            "--bucket",
            "congressional-tech-runtime",
            "--upload",
            "--output",
            str(output_file),
        ],
        client=client,
    )
    assert rc == 0
    descriptor = json.loads(output_file.read_text(encoding="utf-8"))
    assert len(client.puts) == 1
    put_call = client.puts[0]
    assert put_call["Bucket"] == "congressional-tech-runtime"
    assert put_call["Key"] == descriptor["key"]
    assert put_call["ContentLength"] == len(payload)
    assert put_call["IfNoneMatch"] == "*"
    assert sha256(put_call["Body"]).hexdigest() == expected_sha
    assert setup_runtime.artifact_descriptor(json.dumps(descriptor))["sha256"] == expected_sha


def test_upload_rejects_corrupted_readback(tmp_path: Path):
    binary = tmp_path / "docspec"
    binary.write_bytes(b"\x7fELF-corrupt-readback-test")
    corrupt_client = _MockR2Client(corrupt_readback=True)

    with pytest.raises(ValueError, match="SHA-256"):
        publish_runtime.main(
            [
                "--binary",
                str(binary),
                "--bucket",
                "congressional-tech-runtime",
                "--upload",
            ],
            client=corrupt_client,
        )


@pytest.mark.parametrize("upload", [False, True], ids=["descriptor", "upload"])
def test_cli_requires_bucket_before_reading_binary_or_connecting(tmp_path, monkeypatch, upload):
    monkeypatch.setattr(publish_runtime, "build_runtime_descriptor",
        lambda *args, **kwargs: pytest.fail("Missing bucket reached binary descriptor construction"))
    monkeypatch.setattr(publish_runtime, "make_client",
        lambda **kwargs: pytest.fail("Missing bucket reached storage"))
    output = tmp_path / "descriptor.json"
    args = ["--binary", str(tmp_path / "missing-binary"), "--output", str(output)]
    if upload:
        args.append("--upload")
    with pytest.raises(SystemExit) as refused:
        publish_runtime.main(args)
    assert refused.value.code == 2
    assert not output.exists()


def test_descriptor_builder_requires_explicit_bucket_before_hashing(tmp_path, monkeypatch):
    monkeypatch.setattr(publish_runtime, "compute_binary_identity",
        lambda *args: pytest.fail("Missing bucket reached binary hashing"))
    with pytest.raises(TypeError, match="bucket"):
        publish_runtime.build_runtime_descriptor(tmp_path / "missing-binary")


def test_storage_factory_requires_explicit_bucket_before_connecting(monkeypatch):
    monkeypatch.setattr(publish_runtime, "connect_r2",
        lambda **kwargs: pytest.fail("Missing bucket reached storage connection"))
    with pytest.raises(TypeError, match="bucket"):
        publish_runtime.make_client()
