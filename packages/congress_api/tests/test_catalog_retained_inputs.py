"""Explicit adoption reuses exact retained inputs without a second download."""
import json
import shutil

import pyarrow.parquet as pq
import pytest

from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import MANIFEST_KEY, read_catalog
from test_catalog_adoption import existing
from testing_fakes import Native


def retained_pair(tmp_path):
    store = LocalStore(tmp_path / "store")
    existing(tmp_path, store)
    directory = tmp_path / "retained"
    directory.mkdir()
    selected = store.read(MANIFEST_KEY)
    (directory / "catalog-selector.json").write_bytes(selected)
    for name, item in json.loads(selected)["files"].items():
        shutil.copyfile(store.root / item["key"], directory / (name + ".parquet"))
    return store, directory


def test_retained_pair_avoids_download_and_survives_owned_snapshot_close(tmp_path, monkeypatch):
    store, directory = retained_pair(tmp_path)
    monkeypatch.setattr(store, "read_derived_file", lambda *a, **k: pytest.fail("Repeated download"))
    with read_catalog(store, retained_directory=directory) as snapshot:
        owned = snapshot.directory
        assert snapshot.identity["selector_sha256"]
        for name in ("filenames", "documents"):
            path = getattr(snapshot, name + "_path")
            assert pq.read_table(path).equals(pq.read_table(directory / (name + ".parquet")))
    assert not owned.exists()
    assert all((directory / name).is_file() for name in
               ("catalog-selector.json", "filenames.parquet", "documents.parquet"))


@pytest.mark.parametrize("damage", ["selector", "hash", "missing", "rows"])
def test_retained_pair_refuses_damage_without_remote_fallback(tmp_path, monkeypatch, damage):
    store, directory = retained_pair(tmp_path)
    monkeypatch.setattr(store, "read_derived_file", lambda *a, **k: pytest.fail("Remote fallback"))
    if damage == "selector":
        (directory / "catalog-selector.json").write_bytes(b"{}")
    elif damage == "hash":
        with (directory / "filenames.parquet").open("ab") as output:
            output.write(b"changed")
    elif damage == "missing":
        (directory / "documents.parquet").unlink()
    else:
        selected = json.loads(store.read(MANIFEST_KEY))
        selected["files"]["filenames"]["rows"] += 1
        data = json.dumps(selected).encode()
        store.put(MANIFEST_KEY, data)
        (directory / "catalog-selector.json").write_bytes(data)
    with pytest.raises((ValueError, FileNotFoundError)):
        read_catalog(store, retained_directory=directory)
    assert (directory / "filenames.parquet").exists()


def test_retained_catalog_option_requires_explicit_adoption(tmp_path, monkeypatch):
    from congress_api.cli import raw_sync
    from test_native_raw_cli import execute
    monkeypatch.setattr(raw_sync, "connect_storage", lambda *a: pytest.fail("Storage entered"))
    with pytest.raises(SystemExit, match="requires --adopt-catalog"):
        execute(tmp_path, "--update-only", "--retained-catalog", str(tmp_path))


def test_retained_cli_adoption_preserves_all_values_and_completed_retry(tmp_path, monkeypatch):
    import pyarrow as pa
    from test_native_raw_cli import execute, no_acquisition, owner_for

    store, directory = retained_pair(tmp_path)
    expected = {name: pq.read_table(directory / (name + ".parquet"))
                for name in ("filenames", "documents")}
    native = Native()
    owner = owner_for(store)
    owner.native = native
    no_acquisition(monkeypatch)
    monkeypatch.setattr(store, "read_derived_file", lambda *a, **k: pytest.fail("Repeated download"))
    flags = ("--adopt-catalog", "retained-pair", "--retained-catalog", str(directory))
    first = execute(tmp_path, *flags, store=store, raw_storage=owner)
    with read_catalog(store, native=native) as selected:
        assert first["catalog"]["selected_identity"] == selected.identity
        for name, original in expected.items():
            actual = pa.Table.from_batches(list(selected.table(
                name, max_ordered_bytes=16 << 20).iter_batches()))
            assert actual.equals(original, check_metadata=True)
    monkeypatch.setattr(store, "put", lambda *a, **k: pytest.fail("Completed retry wrote metadata"))
    monkeypatch.setattr(store, "put_index_selector", lambda *a, **k: pytest.fail("Completed retry selected"))
    monkeypatch.setattr(native, "run_table", lambda *a, **k: pytest.fail("Completed retry imported data"))
    second = execute(tmp_path, *flags, store=store, raw_storage=owner)
    assert second["catalog"]["unchanged"]
    assert second["catalog"]["selection"] == first["catalog"]["selection"]
    assert all(pq.read_table(directory / (name + ".parquet")).equals(table, check_metadata=True)
               for name, table in expected.items())
