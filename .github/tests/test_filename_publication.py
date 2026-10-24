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
SCRIPT = ROOT / 'scripts/publication/publish-filename-viewer.py'
spec = importlib.util.spec_from_file_location('historical_filename_publication', ROOT / 'packages/congress_api/tests/historical_viewer_publication.py')
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
    tree = ast.parse((ROOT / 'packages/viewer_publication/src/viewer_publication/publish_filename_viewer.py').read_text())
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
    with pytest.raises(ValueError, match='Invalid catalog generation path'):
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


@pytest.mark.parametrize('level', [19, 9, 3])
def test_compression_policy_preserves_all_values_across_row_groups(tmp_path, level):
    import pyarrow as pa
    import pyarrow.parquet as pq
    schema = pa.schema([('id', pa.string()), ('values', pa.list_(pa.struct([('value', pa.string())])))],
                       metadata={b'catalog_id': b'exact', b'custom': b'preserve'})
    rows = [{'id': str(i), 'values': None if i % 3 == 0 else ([] if i % 3 == 1 else
             [{'value': None}, {'value': 'duplicate'}, {'value': 'duplicate'}])} for i in range(19)]
    source, destination = tmp_path / 'source.parquet', tmp_path / 'output.parquet'
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), source)
    policy = publication.DEFAULT_COMPRESSION_POLICY._replace(level=level, batch_size=8, row_group_size=4)
    result = publication.repack_and_verify(source, destination, policy)
    assert result['exact_equal'] and result['rows'] == 19 and result['row_groups'] == 5
    assert pq.read_table(destination).to_pylist() == rows
    assert pq.read_schema(destination).equals(pq.read_schema(source), check_metadata=True)


def test_default_compression_uses_approved_level_3(catalog, tmp_path):
    timing = {}
    events = []
    result = publication.publish(catalog, tmp_path / 'public', stage_timings=timing, stage_event=events.append)
    assert result['compression_policy'] == {'codec': 'zstd', 'level': 3, 'batch_size': 16384, 'row_group_size': 16384,
                                            'applies_to': ['filenames']}
    assert timing['documents_copy']['verification_method'] == 'complete_sha256_bytes'
    assert 'documents_repack' not in timing and timing['filenames_repack']['exact_equal']
    assert timing['total_seconds'] > timing['documents_preparation']
    assert events[0] == {'event': 'stage_started', 'stage': 'input_verification'}
    assert events[-1]['event'] == 'stage_completed' and events[-1]['stage'] == 'manifest'


def test_document_archive_copies_exact_source_bytes_without_repack_or_rehash(catalog, tmp_path, monkeypatch):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from congress_api.retention.viewer_inventory import issue_inventory, verify_inventory
    root, target = tmp_path / 'input', tmp_path / 'publication'
    shutil.copytree(catalog, root)
    raw = json.loads((root / 'indexes/catalog.json').read_text())
    source = root / raw['files']['documents']['key']
    table = pq.read_table(source)
    # Archive-only nested data includes a row above the unchanged Arrow limit.
    # The browsing columns still fit their ordinary reader path.
    table = table.append_column('archive_only', pa.array(
        [[None, '', 'é', 'é', 'x' * publication.DEFAULT_DECODED_POLICY.row_arrow_bytes]] +
        [None] * (len(table) - 1), type=pa.list_(pa.string())))
    pq.write_table(table, source, compression='gzip', row_group_size=2)
    raw['files']['documents'].update(bytes=source.stat().st_size, sha256=publication.digest(source))
    (root / 'indexes/catalog.json').write_text(json.dumps(raw))
    original_catalog, original_identity, original_repack = publication.viewer.Catalog, publication.file_identity, publication.repack_and_verify
    readers, repacks = [], []
    def load(*args, **kwargs):
        value = original_catalog(*args, **kwargs)
        def forbidden(*args, **kwargs): raise AssertionError('document archive decoded for repack')
        value.document_file.iter_batches = forbidden
        readers.append(value); return value
    def identify(path):
        assert path.name != 'documents.parquet', 'copied destination unnecessarily rehashed'
        return original_identity(path)
    def repack(reader, destination, *args, **kwargs):
        assert reader is readers[0].file and destination.name == 'filenames.parquet'
        repacks.append(destination.name)
        return original_repack(reader, destination, *args, **kwargs)
    monkeypatch.setattr(publication.viewer, 'Catalog', load)
    monkeypatch.setattr(publication, 'file_identity', identify)
    monkeypatch.setattr(publication, 'repack_and_verify', repack)
    timings = {}
    manifest = publication.publish(root, target, review_identities=None, stage_timings=timings)
    descriptor = manifest['files']['documents']; output = target / descriptor['path']
    assert output.read_bytes() == source.read_bytes()
    assert pq.read_schema(output).equals(pq.read_schema(source), check_metadata=True)
    assert descriptor['encoding'] == {'mode': 'source_passthrough', 'source_sha256': raw['files']['documents']['sha256']}
    assert timings['documents_copy']['verification_method'] == 'complete_sha256_bytes'
    assert timings['documents_copy']['sha256'] == descriptor['sha256'] == raw['files']['documents']['sha256']
    assert repacks == ['filenames.parquet'] and timings['filenames_repack']['exact_equal']
    proof = manifest.identities[descriptor['path']]
    assert proof.require(output)['sha256'] == descriptor['sha256']
    inventory = issue_inventory(target, manifest.identities, context={'source': raw})
    restored = json.loads(json.dumps(inventory.files))
    verify_inventory(target, restored, context={'source': raw})
    with output.open('ab') as stream: stream.write(b'altered')
    with pytest.raises(ValueError, match='custody'): proof.require(output)
    with pytest.raises(ValueError, match='changed'): verify_inventory(target, restored, context={'source': raw})


@pytest.mark.parametrize('when', ['before_copy', 'during_copy'])
def test_document_archive_copy_refuses_changed_source_custody(catalog, tmp_path, monkeypatch, when):
    root, target = tmp_path / 'input', tmp_path / 'publication'
    shutil.copytree(catalog, root)
    raw = json.loads((root / 'indexes/catalog.json').read_text())
    source = root / raw['files']['documents']['key']
    expected = source.read_bytes()
    def replace_source():
        replacement = source.with_suffix('.replacement')
        replacement.write_bytes(expected); replacement.replace(source)
    if when == 'before_copy':
        original = publication.viewer.Catalog
        def load(*args, **kwargs):
            value = original(*args, **kwargs); replace_source(); return value
        monkeypatch.setattr(publication.viewer, 'Catalog', load)
    else:
        original = publication.copy_checked
        def copy(*args, **kwargs):
            result = original(*args, **kwargs); replace_source(); return result
        monkeypatch.setattr(publication, 'copy_checked', copy)
    with pytest.raises(ValueError, match='source custody'):
        publication.publish(root, target, review_identities=None)
    assert source.read_bytes() == expected and not (target / 'manifest.json').exists()


def test_failed_preparation_upload_keeps_memory_receipts_without_partial_payloads(tmp_path):
    import yaml
    workflow = yaml.safe_load((ROOT / '.github/workflows/publish-filename-viewer.yml').read_text())
    uploads = [step for job in workflow['jobs'].values() for step in job['steps']
               if step.get('uses') == 'actions/upload-artifact@v4' and step.get('if') == 'always()']
    assert len(uploads) == 1
    patterns = uploads[0]['with']['path'].splitlines()
    root = 'viewer-preparation/publication/'
    assert root + 'preparation-memory-failure.json' in patterns
    assert root + '**/preparation-memory-failure.json' in patterns
    # Exercise root and nested receipts against the entire diagnostic path list.
    receipts = {root + 'preparation-memory-failure.json',
                root + 'catalog/viewer-v2/preparation-memory-failure.json'}
    partials = {root + 'catalog/viewer-v2/documents.parquet',
                root + 'catalog/viewer-v2/observation-rows.bin',
                root + 'catalog/viewer-v2/manifest.json', root + 'other.json'}
    for name in receipts | partials:
        path = tmp_path / name; path.parent.mkdir(parents=True, exist_ok=True); path.touch()
    matched = {str(path.relative_to(tmp_path)) for pattern in patterns for path in tmp_path.glob(pattern)}
    assert matched == receipts
    assert uploads[0]['with']['if-no-files-found'] == 'ignore'
