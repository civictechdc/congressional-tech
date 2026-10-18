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


def test_publication_includes_bounded_provenance_lookup(catalog):
    manifest = json.loads((catalog / 'public/manifest.json').read_text())
    assert manifest['version'] == 5
    for name in ('observations', 'observation_rows', 'observation_index'):
        item = manifest['files'][name]
        assert (catalog / 'public' / item['path']).stat().st_size == item['bytes']
    index = json.loads((catalog / 'public' / manifest['files']['observation_index']['path']).read_text())
    assert index['references']['rows'] == manifest['info']['rows']
    assert index['max_part_bytes'] <= 1024 * 1024


def test_generation_cannot_escape_the_selected_snapshot(catalog):
    manifest = json.loads((catalog / 'indexes/catalog.json').read_text())
    manifest['files']['filenames']['key'] = 'catalog-generations/' + manifest['generation'] + '/../other.parquet'
    with pytest.raises(ValueError, match='Invalid immutable catalog location'):
        publication.verify(catalog, manifest)


def test_every_publication_binds_each_review_or_records_why_not(catalog, tmp_path):
    published = publication.publish(catalog, tmp_path / 'public')
    identities = json.loads((ROOT / 'apps/site/document-review-identities.json').read_text())
    placed = json.loads((tmp_path / 'public' / published['files']['review_binding']['path']).read_text())
    assert placed['review_sha256'] == identities['review_sha256']
    assert placed['catalog_id'] == published['info']['catalog_id']
    assert sorted(row['index'] for row in placed['rows'] + placed['withdrawn']) == list(range(len(identities['rows'])))
    # The fixture catalog contains none of the reviewed documents.
    assert {row['reason'] for row in placed['withdrawn']} == {'document_missing'}
    # Publications that supply their own review data publish no binding.
    assert 'review_binding' not in json.loads((catalog / 'public/manifest.json').read_text())['files']


def test_compact_serving_tables_replace_redundant_summary_and_mapping(catalog):
    import pyarrow as pa
    import pyarrow.parquet as pq
    manifest = json.loads((catalog / 'public/manifest.json').read_text())
    assert 'document_summaries' not in manifest['files']
    assert 'document_rows' not in manifest['files']
    browse = pq.ParquetFile(catalog / 'public' / manifest['files']['browse']['path'])
    assert 'document_kind_source' in browse.schema_arrow.names
    assert not {'extension', 'recovered_filename', 'response_result'} & set(browse.schema_arrow.names)
    detail = pq.ParquetFile(catalog / 'public' / manifest['files']['details']['path'])
    assert detail.schema_arrow.field('http_status').type == pa.uint16()
    assert detail.schema_arrow.field('response_usable').type == pa.bool_()
    assert detail.schema_arrow.field('state_checked_at').type == pa.timestamp('ms', tz='UTC')
    assert 'source_occurrences' not in detail.schema_arrow.names
    assert 'document_id' not in detail.schema_arrow.names
    assert detail.metadata.num_rows == manifest['info']['rows']


def test_detail_navigation_preserves_members_and_preferred_sources(catalog):
    from array import array
    import struct
    manifest = json.loads((catalog / 'public/manifest.json').read_text())
    def integers(name):
        values = array('I')
        values.frombytes((catalog / 'public' / manifest['files'][name]['path']).read_bytes())
        if sys.byteorder != 'little':
            values.byteswap()
        return values
    groups, preferred = integers('groups'), integers('preferred')
    members = integers('detail_members')
    packed = (catalog / 'public' / manifest['files']['detail_navigation']['path']).read_bytes()
    assert len(packed) == len(groups) * 16
    assert len(members) == len(groups)
    for row, expected_group in enumerate(groups):
        group, selected, offset, count = struct.unpack_from('<IIII', packed, row * 16)
        assert group == expected_group
        assert selected == preferred[group]
        assert list(members[offset:offset + count]) == [i for i, value in enumerate(groups) if value == group]


@pytest.mark.parametrize('groups,preferred', [([1], [0]), ([0], [1]), ([0, 1], [1, 0]), ([0], [0, 0])])
def test_detail_navigation_rejects_invalid_group_and_preferred_links(tmp_path, groups, preferred):
    with pytest.raises(ValueError):
        publication.navigation.publish_navigation(groups, preferred, tmp_path)
