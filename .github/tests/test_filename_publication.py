"""Pages reads immutable catalog files; it never joins the R2 writer pipeline."""
import ast
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'apps/site/scripts/publish-filename-viewer.py'
spec = importlib.util.spec_from_file_location('filename_publication', SCRIPT)
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


@pytest.fixture(scope='module')
def catalog(tmp_path_factory):
    root = tmp_path_factory.mktemp('filename-publication')
    subprocess.run([sys.executable, str(SCRIPT.with_name('filename-test-fixture.py')), str(root)], check=True, capture_output=True)
    return root


def test_r2_fetch_reads_only_the_manifest_and_its_immutable_pair(catalog, tmp_path, monkeypatch):
    calls = []
    class ReadOnlyClient:
        def get_object(self, *, Bucket, Key):
            calls.append(('get', Bucket, Key))
            return {'Body': (catalog / Key).open('rb'), 'LastModified': datetime(2026, 10, 13, tzinfo=timezone.utc)}
        def download_file(self, bucket, key, destination):
            calls.append(('download', bucket, key))
            shutil.copyfile(catalog / key, destination)
    monkeypatch.setitem(sys.modules, 'boto3', SimpleNamespace(client=lambda *args, **kwargs: ReadOnlyClient()))
    for name in ('CLOUDFLARE_ACCOUNT_ID','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY'):
        monkeypatch.setenv(name, 'test')
    assert publication.fetch(tmp_path) == '2026-10-13T00:00:00+00:00'
    manifest = json.loads((tmp_path / 'indexes/catalog.json').read_text())
    publication.verify(tmp_path, manifest)
    assert calls == [('get','congressional-tech-raw','indexes/catalog.json')] + [
        ('download','congressional-tech-raw',item['key']) for item in manifest['files'].values()]
    tree = ast.parse(SCRIPT.read_text())
    assert {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == 'client'} == {'get_object','download_file'}


def test_corrupted_input_is_rejected_before_publication(catalog, tmp_path):
    manifest = json.loads((catalog / 'indexes/catalog.json').read_text())
    manifest['files']['filenames']['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='differs from the R2 manifest'):
        publication.verify(catalog, manifest)


def test_generation_cannot_escape_the_selected_snapshot(catalog):
    manifest = json.loads((catalog / 'indexes/catalog.json').read_text())
    manifest['files']['filenames']['key'] = 'catalog-generations/' + manifest['generation'] + '/../other.parquet'
    with pytest.raises(ValueError, match='Invalid immutable catalog location'):
        publication.verify(catalog, manifest)
