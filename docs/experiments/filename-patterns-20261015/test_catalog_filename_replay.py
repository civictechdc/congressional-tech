"""Full pair replay retains body/source evidence and exposes every kind change."""
import csv
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import catalog_filename_replay as replay
from congress_api.retention import document_index as index
from congress_api.retention.catalog_publication import local_catalog_paths


def baseline(tmp_path):
    root = tmp_path / 'input'
    (root / 'indexes').mkdir(parents=True)
    law = 'PLAW-118publ5.pdf'
    body = 'bodies/sha256/' + 'a' * 64 + '.gz'
    rows = [dict(body_key=body, filename=law, source_url='https://www.govinfo.gov/content/pkg/PLAW-118publ5/pdf/' + law),
            dict(body_key=body, filename='alias.pdf', source_url='https://example.gov/alias.pdf'),
            dict(body_key='bodies/sha256/' + 'b' * 64 + '.gz', filename='opaque.pdf', source_url='https://example.gov/opaque.pdf',
                 content_document_kind=['report'], content_title=['Retained report title']),
            dict(body_key='bodies/sha256/' + 'c' * 64 + '.gz', filename=None, source_url=None),
            dict(body_key=None, filename='unavailable.pdf', source_url='https://example.gov/unavailable.pdf',
                 source_document_type=['Witness Statement']),
            dict(body_key=None, filename='listing.xml', source_url='https://example.gov/listing.xml',
                 source_record_type=['committee-meeting'], record_role=['source-record'])]
    for row in rows:
        row.update(media_type=['application/pdf'], http_status=['200'], filename_origins=['url_path'],
                   source_paths=['retained/source.json'], extension=['pdf'])
        if row['body_key']:
            row['body_format'] = ['pdf']
    fields = set().union(*(row.keys() for row in rows)) - set(index.SOURCE_SCHEMA.names)
    schema = pa.schema([*index.SOURCE_SCHEMA, *[(name, index.metadata_type(name)) for name in sorted(fields)]],
                       metadata={'house_naming_version': '3.1.0', 'body_evidence_fingerprint': 'old-body-reader', 'capture_digest': 'retained-captures'})
    # Known 3.1 fixture state: public-law filename has not yet supplied a kind.
    index.write_document_indexes(root / 'indexes/document-filenames.parquet', rows, schema)
    return root


def changed_table(path, destination, change):
    table = pq.read_table(path)
    rows = table.to_pylist()
    change(rows)
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), destination)


def test_complete_pair_replay_preserves_aliases_body_readings_roles_and_unnamed(tmp_path, monkeypatch):
    root = baseline(tmp_path)
    before = local_catalog_paths(root)
    hashes = [replay.file_digest(path) for path in before]
    monkeypatch.setattr(index, 'read_retained_body', lambda *a: pytest.fail('Body opened during filename-only replay'))
    output = tmp_path / 'result'
    result = replay.run(root, output, rehearsal=True, workers=1)
    assert result['completed'] and result['invariants_preserved']
    assert result['changed_prior_kinds_need_review'] == 0
    assert result['release_qualified'] is False
    assert result['publication_performed'] is False and result['body_reinspection'] is False
    assert [replay.file_digest(path) for path in before] == hashes
    assert not (root / 'indexes/catalog.json').exists()
    assert not (output / 'catalog/indexes/catalog.json').exists()
    files, documents = local_catalog_paths(output / 'catalog')
    rows = pq.read_table(documents).to_pylist()
    assert len(rows) == 5 and any(row['filename'] is None for row in rows)
    assert next(row for row in rows if row['filename'] == 'opaque.pdf')['content_document_kind'] == ['report']
    law = next(row for row in rows if 'PLAW-118publ5.pdf' in (row['filenames'] or []))
    assert law['document_kind'] == ['public-law'] and len(law['filenames']) == 2
    for path in [files, documents]:
        meta = pq.read_schema(path).metadata
        assert meta[b'body_evidence_fingerprint'] == b'old-body-reader'
        assert meta[b'house_naming_version'] == b'3.2.0'
        assert meta[b'capture_digest'] == b'retained-captures'
    assert result['comparisons']['documents']['changes']['new_assignment'] == 1


@pytest.mark.parametrize('name', ['BILLS-117HR3684RH-RCP117-9.xml', 'CPRT-119HPRT59719.xml'])
def test_replay_retains_cached_xml_when_filename_has_kind(tmp_path, monkeypatch, name):
    root = tmp_path / 'input'
    (root / 'indexes').mkdir(parents=True)
    url = 'https://www.govinfo.gov/content/pkg/example/xml/' + name
    fields = dict(body_format=['xml'], content_document_kind=['amendment'],
                  content_xml_root=['amendment-doc'], content_amendment_type=['house-amendment'],
                  content_amendment_stage=['proposed'], content_amendment_degree=['first'],
                  content_legis_num=['Rules Committee Print 117–9'])
    row = dict(body_key='bodies/sha256/' + 'd' * 64 + '.gz', filename=name, source_url=url,
               media_type=['application/xml'], http_status=['200'], **index.extract((name, url)), **fields)
    assert row['document_kind'], 'Fixture must exercise an already typed filename'
    names = set(row) - set(index.SOURCE_SCHEMA.names)
    schema = pa.schema([*index.SOURCE_SCHEMA, *[(k, index.metadata_type(k)) for k in sorted(names)]],
                       metadata={'house_naming_version': '3.1.0', 'body_evidence_fingerprint': 'retained-xml-reader'})
    index.write_document_indexes(root / 'indexes/document-filenames.parquet', [row], schema)
    monkeypatch.setattr(index, 'read_retained_body', lambda *a: pytest.fail('Cached XML must not be reread'))
    output = tmp_path / 'result'
    result = replay.run(root, output, rehearsal=True, workers=1)
    assert result['invariants_preserved']
    assert result['changed_prior_kinds_need_review'] == 0
    for path in local_catalog_paths(output / 'catalog'):
        table = pq.read_table(path)
        actual, = table.to_pylist()
        assert {key: actual.get(key) for key in fields} == fields
        assert table.schema.metadata[b'body_evidence_fingerprint'] == b'retained-xml-reader'


@pytest.mark.parametrize('change', ['role', 'evidence', 'kind', 'missing', 'duplicate', 'document_id'])
def test_comparison_exposes_changes_or_rejects_invalid_ids(tmp_path, change):
    root = baseline(tmp_path)
    source, _ = local_catalog_paths(root)
    after = tmp_path / 'after.parquet'
    def mutate(rows):
        if change == 'role': rows[0]['record_role'] = ['error-response']
        elif change == 'evidence': rows[0]['source_paths'] = ['replaced']
        elif change == 'kind':
            row = next(r for r in rows if r.get('document_kind'))
            row['document_kind'] = ['unexpected-kind']
        elif change == 'missing': rows.pop()
        elif change == 'duplicate': rows.append(rows[0])
        else: rows[0]['document_id'] = 'different'
    changed_table(source, after, mutate)
    output = tmp_path / 'changes.csv'
    if change == 'duplicate':
        with pytest.raises(ValueError, match='Duplicate comparison identity'):
            replay.compare_table(source, after, output)
    else:
        result = replay.compare_table(source, after, output)
        assert not result['identities_roles_evidence_preserved'] if change != 'kind' else result['prior_kind_changes'] == 1
        changes = list(csv.DictReader(output.open()))
        assert len(changes) == 1
        if change == 'missing': assert changes[0]['change'] == 'missing_id'


def test_unverified_pair_refuses_without_rehearsal(tmp_path, monkeypatch):
    root = baseline(tmp_path)
    monkeypatch.setattr(index, 'write_filename_metadata', lambda *a, **kw: pytest.fail('Writer ran without publication gate'))
    with pytest.raises(ValueError, match='Verified 3.1.0'):
        replay.run(root, tmp_path / 'result', workers=1)
    assert not (tmp_path / 'result').exists()


def test_refresh_inputs_excludes_old_filename_meanings_but_preserves_source_context(tmp_path):
    source, _ = local_catalog_paths(baseline(tmp_path))
    rows, metadata = index.filename_refresh_inputs(pq.ParquetFile(source))
    rows = list(rows)
    assert len(rows) == 6
    assert all('document_kind' not in row and 'document_id' not in row and 'extension' not in row for row in rows)
    assert any(row.get('source_document_type') == ['Witness Statement'] for row in rows)
    assert metadata == {'capture_digest': 'retained-captures'}


def test_low_disk_space_refuses_before_any_write(tmp_path, monkeypatch):
    from collections import namedtuple
    usage = namedtuple('usage', 'total used free')
    root = baseline(tmp_path)
    monkeypatch.setattr(replay.shutil, 'disk_usage', lambda path: usage(100, 99, 1))
    with pytest.raises(ValueError, match='Insufficient free disk'):
        replay.run(root, tmp_path / 'result', rehearsal=True)
    assert not (tmp_path / 'result').exists()


def test_moving_input_cannot_produce_a_completed_summary(tmp_path, monkeypatch):
    root = baseline(tmp_path)
    source, _ = local_catalog_paths(root)
    original = index.write_filename_metadata
    def write_then_change(*args, **kwargs):
        result = original(*args, **kwargs)
        replacement = tmp_path / 'replacement.parquet'
        changed_table(source, replacement, lambda rows: rows[0].update(source_paths=['concurrent-change']))
        replacement.replace(source)
        return result
    monkeypatch.setattr(index, 'write_filename_metadata', write_then_change)
    with pytest.raises(ValueError, match='Input catalog changed'):
        replay.run(root, tmp_path / 'result', rehearsal=True, workers=1)
    assert (tmp_path / 'result/manifest.json').exists()
    assert not (tmp_path / 'result/summary.json').exists()
