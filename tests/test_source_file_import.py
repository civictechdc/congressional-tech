"""Migration checks for independent cache copies and conflicts."""
import gzip
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def importer():
    pytest.importorskip('pyarrow')
    path = Path(__file__).resolve().parents[1] / 'docs/youtube-coverage/research/scripts/import_source_files.py'
    spec = importlib.util.spec_from_file_location('import_source_files', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('data', [b'', b'\xff\x00\r\n', gzip.compress(b'<xml>\r\n</xml>', mtime=123)])
def test_import_preserves_bytes_and_is_independent(tmp_path, importer, data):
    source, destination = tmp_path / 'original', tmp_path / 'cache/imported'
    source.write_bytes(data)
    result = importer.copy_verified(source, destination, min_free_bytes=0)
    assert result['status'] == 'copied'
    assert source.read_bytes() == destination.read_bytes() == data
    assert importer.copy_verified(source, destination, min_free_bytes=0)['status'] == 'already_present'
    source.write_bytes(b'changed later')
    assert destination.read_bytes() == data


def test_conflict_preserves_existing_file(tmp_path, importer):
    source, destination = tmp_path / 'original', tmp_path / 'imported'
    source.write_bytes(b'new')
    destination.write_bytes(b'existing')
    with pytest.raises(ValueError, match='different contents'):
        importer.copy_verified(source, destination, min_free_bytes=0)
    assert source.read_bytes() == b'new' and destination.read_bytes() == b'existing'
    assert not list(tmp_path.glob('.import-*'))


def test_space_floor_leaves_no_partial_copy(tmp_path, importer):
    source, destination = tmp_path / 'original', tmp_path / 'imported'
    source.write_bytes(b'body')
    with pytest.raises(OSError, match='free-space'):
        importer.copy_verified(source, destination, min_free_bytes=2**80)
    assert not destination.exists()


def test_manifest_accepts_relative_destination_and_publishes_portable_path(tmp_path, importer, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path('original.xml').write_bytes(b'<meeting/>')
    Path('.cache').mkdir()
    manifest = Path('inputs.jsonl')
    manifest.write_text(json.dumps({'source': 'original.xml', 'destination': '.cache/imported/meeting.xml'}) + '\n')
    assert importer.run(manifest, Path('.cache'), Path('.cache/index'), workers=1, min_free_gib=0) == 0
    row = importer.pq.read_table('.cache/index/files.parquet').to_pylist()[0]
    assert row['cache_relative_path'] == 'imported/meeting.xml'
    assert (Path('.cache') / row['cache_relative_path']).read_bytes() == b'<meeting/>'
