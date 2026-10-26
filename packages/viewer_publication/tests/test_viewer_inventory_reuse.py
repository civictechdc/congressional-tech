"""Inventory context handoffs reuse facts while fresh use checks retain custody."""
from copy import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from congress_api.retention.derived_files import VerifiedFile, file_identity
from congress_api.retention.viewer_inventory import issue_inventory, verify_inventory
from viewer_publication.plan import accept_viewer_plan


def fixture_inventory(root):
    root.mkdir(exist_ok=True)
    manifest = {"source_manifest": {"catalog_id": "fixture"}}
    (root / "manifest.json").write_text(json.dumps(manifest))
    for number in range(12):
        (root / f"part-{number}.bin").write_bytes(bytes([number]) * 8)
    identities = {path.name: file_identity(path) for path in root.iterdir()}
    return manifest, identities


def accept(root, manifest, validation):
    publisher = SimpleNamespace(
        prepared_files=lambda root, manifest, validation: {
            name: root / name for name in validation.files if name != "manifest.json"},
        load_prepared_recovery=lambda *args, **kwargs: {})
    return accept_viewer_plan(publisher, root, manifest,
        validation=validation, context={"prepared": True},
        protected={"source": (manifest["source_manifest"], "selected"),
                   "viewer": (None, None), "accepted": None},
        source_pins={}, release_plan={},
        conditions={"selected_etag": "selected", "previous_etag": None})


def test_inventory_and_plan_handoff_each_check_files_once(tmp_path, monkeypatch):
    manifest, identities = fixture_inventory(tmp_path)
    calls = []
    original = VerifiedFile.require
    def counted(self, path):
        calls.append(Path(path))
        return original(self, path)
    monkeypatch.setattr(VerifiedFile, "require", counted)
    validation = issue_inventory(tmp_path, identities, context={"prepared": True})
    assert len(calls) == len(identities)
    calls.clear()
    plan = accept(tmp_path, manifest, validation)
    # A complete boundary check plus the manifest read, without reissuance.
    assert len(calls) == len(identities) + 1
    assert plan.validation.identities is validation.identities
    calls.clear()
    plan.require(tmp_path, manifest)
    assert len(calls) == len(identities)


def test_context_binding_does_not_hash_or_scan_files(tmp_path, monkeypatch):
    _, identities = fixture_inventory(tmp_path)
    validation = issue_inventory(tmp_path, identities, context={"prepared": True})
    monkeypatch.setattr(VerifiedFile, "require", lambda *args: pytest.fail("Repeated file scan"))
    bound = validation.bind_context({"accepted": True})
    assert bound.files is validation.files
    assert bound.identities is validation.identities
    with pytest.raises(ValueError, match="proof no longer applies"):
        copy(validation).bind_context({"accepted": True})


@pytest.mark.parametrize("change", ["changed", "missing", "facts", "binding"])
def test_plan_rechecks_changed_files_facts_and_context(tmp_path, change):
    manifest, identities = fixture_inventory(tmp_path)
    validation = issue_inventory(tmp_path, identities, context={"prepared": True})
    plan = accept(tmp_path, manifest, validation)
    if change == "changed":
        (tmp_path / "part-0.bin").write_bytes(b"different")
    elif change == "missing":
        (tmp_path / "part-0.bin").unlink()
    elif change == "facts":
        plan.validation.files["part-0.bin"]["sha256"] = "0" * 64
    else:
        plan.source_pins["changed"] = True
    with pytest.raises((ValueError, FileNotFoundError)):
        plan.require(tmp_path, manifest)


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
