"""D3: one typed reading per distinct filename/URL/version, through native work lists."""
import gzip
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets
from house_naming.errors import NamingError


def reader():
    from congress_api.lake import filenames
    return filenames


def engine():
    return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


def test_typed_bill_keys_use_known_congress_and_preserve_literals():
    row = reader().read_filename('BILLS-119hr6028ih.pdf', '', catalog_version='v')
    assert row['status'] == 'completed' and row['valid']
    assert row['congress'] == 119 and row['measure_type'] == 'hr'
    assert row['measure_keys'] == ['119-hr-6028']
    assert row['package_id'] == 'BILLS-119hr6028ih'
    unknown = reader().read_filename('H.R.1.S.2.pdf', '', catalog_version='v')
    assert unknown['measure_keys'] == [] and unknown['measure_number'] is None
    assert [v['value'] for v in unknown['fields'] if v['field'] == 'measure_references'] == ['hr1', 's2']


def test_dates_bioguide_and_all_facets_keep_ambiguity():
    row = reader().read_filename('HHRG-119-IF00-Wstate-X000001-20260203.pdf', '', catalog_version='v')
    assert row['filename_date'].isoformat() == '2026-02-03'
    assert row['bioguide_ids'] == ['X000001'] and row['committee_code'] == ['IF00']
    assert row['package_id'] is None
    ambiguous = reader().read_filename('01-02-2003.pdf', '', catalog_version='v')
    assert ambiguous['filename_date'] is None
    empty = reader().read_filename('', '', catalog_version='v')
    assert empty['status'] == 'completed' and not empty['valid']


class Parser:
    def __init__(self, error): self.calls = []; self.error = error
    def extract(self, filename, *, source_url=None, **kwargs):
        self.calls.append(source_url)
        if source_url is not None: raise NamingError(self.error, 'stable code, private detail')
        return {'valid': False, 'matches': [], 'metadata': {'document_kind': ['a', 'b'],
                'congress': ['118', '119'], 'measure_references': ['hr7']}}


def test_only_invalid_source_url_retries_without_changing_identity():
    parser = Parser('invalid-source-url')
    row = reader().read_filename('a.pdf', 'bad URL', catalog_version='v', parser=parser)
    assert parser.calls == ['bad URL', None] and row['source_url'] == 'bad URL'
    assert row['status'] == 'completed' and row['error_type'] is None
    assert row['document_kind'] == ['a', 'b'] and row['congress'] is None
    parser = Parser('invalid-filename')
    row = reader().read_filename('a.pdf', 'https://a.test/a', catalog_version='v', parser=parser)
    assert parser.calls == ['https://a.test/a']
    assert row['status'] == 'error' and row['error_type'] == 'invalid-filename'
    assert 'private detail' not in str(row)
    with pytest.raises(RuntimeError, match='input unavailable'):
        reader().read_filename('a.pdf', '', catalog_version='v', parser=Unavailable())


class Unavailable:
    def extract(self, *args, **kwargs): raise RuntimeError('input unavailable')


def test_large_input_is_settled_without_entering_the_parser():
    row = reader().read_filename('x' * 16385, '', catalog_version='v', parser=Unavailable())
    assert row['status'] == 'size_limit' and not row['valid']


def test_version_digest_covers_package_nested_vocabularies_and_lock(tmp_path):
    from congress_api.lake.versions import version_digest
    package = tmp_path / 'package'; package.mkdir()
    (package/'one.py').write_text('a')
    nested = package/'data'; nested.mkdir(); vocabulary = nested/'codes.json'; vocabulary.write_text('{}')
    lock = tmp_path/'uv.lock'; lock.write_text('locked')
    def version(): return version_digest(packages={'parser': package}, files={'lock': lock}, values={'vocab': {'x': ['a']}})
    first = version(); assert first == version()
    vocabulary.write_text('{"a":1}'); second = version(); assert second != first
    lock.write_text('changed'); assert version() != second
    before_cache = version()
    cache = package/'__pycache__'; cache.mkdir(); (cache/'x.pyc').write_bytes(b'ignored')
    assert version() == before_cache
    assert version_digest(packages={'parser': package}, files={'lock': lock}, values={'vocab': {'x': ['b']}}) != before_cache


def input_tables(tmp_path, rows):
    schema = pa.schema([('receipt_key',pa.string()),('receipt_line',pa.int64()),('capture_index',pa.int32()),
        ('mode',pa.string()),('url',pa.string()),('requested_url',pa.string()),('member_path',pa.string()),
        ('h_content_disposition',pa.string()),('sha256',pa.binary(32))])
    path=tmp_path/'captures.parquet'; pq.write_table(pa.Table.from_pylist(rows,schema=schema),path)
    return path


def test_native_effective_names_and_work_anti_join(tmp_path):
    cases = [
        dict(url='https://a.test/path.pdf', h_content_disposition="attachment; filename=old.pdf; filename*=UTF-8''caf%C3%A9.pdf"),
        dict(url='https://a.test/path.pdf?name=b.pdf&file=a%2520%2Bb.pdf&file=later.pdf'),
        dict(url='https://a.test/path.pdf?file=%FF.pdf'),
        dict(url='https://a.test/path.pdf', member_path='folder/Member%20.pdf'),
        dict(url=None, requested_url='https://a.test/Requested%20Name.pdf'),
        dict(url='https://a.test/path.pdf?name=source.pdf',requested_url='https://a.test/path?file=requested.pdf'),
        dict(url='https://a.test/path.pdf?file&name=ignored.pdf'),
        dict(url='https://a.test/path.pdf#fragment?file=ignored.pdf'),
        dict(url='https://a.test/path.pdf?file=question?mark.pdf'),
    ]
    captures=input_tables(tmp_path,[dict(receipt_key='r',receipt_line=i,capture_index=0,mode='fetch',**row)
        for i,row in enumerate(cases,1)])
    version = reader().current_version()
    result=reader().stage(captures=captures, recovery_files=[], engine=engine(), work=tmp_path/'job', catalog_version=version)
    rows=pq.read_table(result['readings']).to_pylist()
    assert len(rows) == 9  # Same path name at different exact URLs remains separate work.
    names={r['filename'] for r in rows}
    assert names == {'café.pdf','a%20+b.pdf','%FF.pdf','Member%20.pdf','Requested Name.pdf','source.pdf','path.pdf','question?mark.pdf'}
    member=next(r for r in rows if r['filename']=='Member%20.pdf'); assert member['source_url']==''
    second=reader().stage(captures=captures,recovery_files=[],existing=result['readings'],engine=engine(),work=tmp_path/'again',catalog_version=version)
    assert pq.read_metadata(second['readings']).num_rows == 0
    newer=reader().stage(captures=captures,recovery_files=[],existing=result['readings'],engine=engine(),work=tmp_path/'new',vocabularies={'member_surnames': {'119': ['New']}})
    assert pq.read_metadata(newer['readings']).num_rows == 9


def test_recovery_original_work_deduplicates_and_rejection_removes_name_override(tmp_path):
    captures=input_tables(tmp_path,[dict(receipt_key='r',receipt_line=1,capture_index=0,mode='retained_import',
        url='https://archive.test/recovered.pdf')])
    path=tmp_path/'recoveries.jsonl.gz'
    decisions=[dict(body_sha256='a'*64,id='a',original_url='https://a.test/Original.pdf',recovered_filename='Old.pdf',kind='recovered_document',decided_at='2026-10-01T00:00:00Z'),
               dict(body_sha256='a'*64,id='b',original_url='https://a.test/Original.pdf',recovered_filename='Rejected.pdf',kind='rejected',decided_at='2026-10-02T00:00:00Z'),
               dict(body_sha256='c'*64,id='c',original_url='https://a.test/Another.pdf',recovered_filename='Named.pdf',kind='recovered_document',decided_at='2026-10-02T00:00:00Z'),
               dict(body_sha256='d'*64,id='d',original_url='https://a.test/Another.pdf',recovered_filename='Other Body.pdf',kind='recovered_document',decided_at='2026-10-03T00:00:00Z')]
    with gzip.open(path,'wt') as out:
        for row in decisions: out.write(json.dumps(row)+'\n')
    result=reader().stage(captures=captures,recovery_files=[dict(key='provenance/recoveries/source.jsonl',path=str(path))],engine=engine(),work=tmp_path/'job')
    rows=pq.read_table(result['readings']).to_pylist()
    assert {(r['filename'],r['source_url']) for r in rows} == {('Original.pdf','https://a.test/Original.pdf'),('Named.pdf','https://a.test/Another.pdf'),('Other Body.pdf','https://a.test/Another.pdf')}


def test_stage_refuses_a_version_that_does_not_name_its_code_and_inputs(tmp_path):
    captures=input_tables(tmp_path, [])
    with pytest.raises(ValueError, match='version'):
        reader().stage(captures=captures,recovery_files=[],engine=engine(),work=tmp_path/'job',catalog_version='wrong')
