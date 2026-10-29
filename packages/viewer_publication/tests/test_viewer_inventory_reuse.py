"""Inventory context handoffs reuse facts while fresh use checks retain custody."""
from copy import copy
import json
from pathlib import Path

import pytest

from congress_api.retention.derived_files import VerifiedFile, file_identity
from congress_api.retention.viewer_inventory import issue_inventory, verify_inventory


def fixture_inventory(root):
    root.mkdir(exist_ok=True)
    manifest = {"source_manifest": {"catalog_id": "fixture"}}
    (root / "manifest.json").write_text(json.dumps(manifest))
    for number in range(12):
        (root / f"part-{number}.bin").write_bytes(bytes([number]) * 8)
    identities = {path.name: file_identity(path) for path in root.iterdir()}
    return manifest, identities


def test_context_binding_does_not_hash_or_scan_files(tmp_path, monkeypatch):
    _, identities = fixture_inventory(tmp_path)
    validation = issue_inventory(tmp_path, identities, context={"prepared": True})
    monkeypatch.setattr(VerifiedFile, "require", lambda *args: pytest.fail("Repeated file scan"))
    bound = validation.bind_context({"accepted": True})
    assert bound.files is validation.files
    assert bound.identities is validation.identities
    with pytest.raises(ValueError, match="proof no longer applies"):
        copy(validation).bind_context({"accepted": True})


def test_plain_digest_dictionaries_still_cannot_issue_inventory(tmp_path):
    _, identities = fixture_inventory(tmp_path)
    with pytest.raises(ValueError, match="Issued file proof"):
        issue_inventory(tmp_path, {name: dict(proof) for name, proof in identities.items()}, context={})


def test_verification_still_rejects_same_size_content_change(tmp_path):
    _, identities = fixture_inventory(tmp_path)
    facts = {name: dict(proof) for name, proof in identities.items()}
    (tmp_path / "part-0.bin").write_bytes(b"replaced")
    with pytest.raises(ValueError, match="file changed"):
        verify_inventory(tmp_path, facts, context={})
