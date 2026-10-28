"""Independent source totals bind D1's reference-first, missing-item grain."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


@pytest.fixture
def counts():
    path=Path(__file__).resolve().parents[1]/'measure/cxb_capture_source_counts.py'
    spec=importlib.util.spec_from_file_location('capture_source_counts_under_test',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def authority(path,rows):
    qualification=path.with_suffix(path.suffix+'.qualification.json')
    qualification.write_text(json.dumps(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        size=path.stat().st_size,rows=rows,producer='fixture')))
    return qualification


def counter(tmp_path,records):
    path=tmp_path/'original-counter.parquet'
    raw=[json.dumps(r,separators=(',',':'),ensure_ascii=False) for r in records]
    pq.write_table(pa.table({'__receipt_key':['receipts/fixture/source.jsonl.gz']*len(raw),
        '__receipt_line':pa.array(range(1,len(raw)+1),type=pa.int64()),'__raw_line':raw}),path)
    return path,authority(path,len(raw)),raw


@pytest.mark.parametrize('record,expected,items',[
    ({},1,1),
    ({'record':[{}, {}, {}]},3,3),
    ({'record':[{}, {}],'captures':[{'pointer':[0,'a']},{'pointer':[0,'b']}]},3,4),
    ({'record':[{}, {}],'captures':[{'pointer':[0]}],'file_references':[{'pointer':[1]},{'pointer':[0]}]},2,5),
    ({'record':[{}, {}],'file_references':[{'pointer':[0]}]},2,3),
    ({'record':[{}, {}],'captures':[{'pointer':[0]},{'pointer':[1]}]},2,4),
    ({'record':[{}, {}],'captures':[{'pointer':['0']},{'pointer':['record','1']}]},2,4),
    ({'record':[{}, {}],'captures':[{'pointer':[0]},{'pointer':['0']}]},3,4),
    ({'record':[{}, {}],'captures':[{},{}]},3,4),
    ({'record':[{}, {}],'captures':[{'pointer':[-1]},{'pointer':[3]}]},4,4),
    ({'record':[]},1,1),
    ({'record':[],'captures':[{'pointer':[0]}]},1,1),
    ({'captures':[],'file_references':[{},{}]},2,2),
    ({'captures':[{},{}],'file_references':[{}, {}, {}]},2,5),
    ({'record':{'text':'Montréal'}},1,1),
])
def test_each_source_shape_has_an_independent_expected_grain(counts,tmp_path,record,expected,items):
    path,pin,raw=counter(tmp_path,[record]);key='receipts/fixture/source.jsonl.gz'
    result=counts.count_sources(counter=path,files=[],receipt_keys=[key],work=tmp_path/'work',
        source_qualifications={str(path):str(pin)})
    assert result==[dict(key=key,source_rows=1,uncompressed_bytes=len(raw[0].encode()),
        list_items=items,expected_captures=expected,max_line_bytes=len(raw[0].encode()),max_line_items=items)]
    assert json.loads((tmp_path/'work/counts.json').read_text())==result
    assert (tmp_path/'work/counts.sql').is_file()


def test_counter_and_original_gzip_inputs_group_only_small_receipt_metrics(counts,tmp_path):
    path,pin,raw=counter(tmp_path,[{},dict(record=[{},{}])]);key='receipts/fixture/source.jsonl.gz'
    direct=tmp_path/'new.jsonl.gz';payload=b'{"record":[{},{},{}]}\n{}\n'
    direct.write_bytes(gzip.compress(payload,mtime=0));direct_pin=authority(direct,2)
    extra='receipts/fixture/new.jsonl.gz'
    result=counts.count_sources(counter=path,files=[dict(key=extra,path=str(direct))],
        receipt_keys=[key,extra],work=tmp_path/'work',
        source_qualifications={str(path):str(pin),str(direct):str(direct_pin)})
    assert [r['key'] for r in result]==sorted([key,extra])
    assert [r['source_rows'] for r in result]==[2,2]
    assert sum(r['expected_captures'] for r in result)==7
    assert sum(r['list_items'] for r in result)==7
    assert sum(r['uncompressed_bytes'] for r in result)==sum(len(s.encode()) for s in raw)+len(payload)-2
    assert not list((tmp_path/'work').glob('*.parquet'))


@pytest.mark.parametrize('record',[
    {'captures':{}},{'file_references':'lost-list'},
])
def test_malformed_reference_lists_refuse_without_accepted_counts(counts,tmp_path,record):
    path,pin,_=counter(tmp_path,[record])
    with pytest.raises((ValueError,RuntimeError),match='[Mm]alformed|[Ii]nvalid'):
        counts.count_sources(counter=path,files=[],receipt_keys=['receipts/fixture/source.jsonl.gz'],
            work=tmp_path/'work',source_qualifications={str(path):str(pin)})
    assert not (tmp_path/'work/counts.json').exists()


def test_missing_selected_receipt_refuses_without_a_partial_success(counts,tmp_path):
    path,pin,_=counter(tmp_path,[{}])
    with pytest.raises(ValueError,match='receipt|Receipt'):
        counts.count_sources(counter=path,files=[],receipt_keys=['receipts/fixture/source.jsonl.gz',
            'receipts/fixture/lost.jsonl.gz'],work=tmp_path/'work',source_qualifications={str(path):str(pin)})
    assert not (tmp_path/'work/counts.json').exists()


def test_malformed_original_json_line_refuses(counts,tmp_path):
    path,pin,_=counter(tmp_path,[{}]);direct=tmp_path/'broken.jsonl.gz'
    direct.write_bytes(gzip.compress(b'{"missing":\n',mtime=0));direct_pin=authority(direct,1)
    with pytest.raises((ValueError,RuntimeError),match='[Mm]alformed|[Ii]nvalid'):
        counts.count_sources(counter=path,files=[dict(key='receipts/fixture/broken.jsonl.gz',path=str(direct))],
            receipt_keys=['receipts/fixture/source.jsonl.gz','receipts/fixture/broken.jsonl.gz'],work=tmp_path/'work',
            source_qualifications={str(path):str(pin),str(direct):str(direct_pin)})
    assert not (tmp_path/'work/counts.json').exists()
    failure=json.loads((tmp_path/'work/error.json').read_text())
    assert failure['error_class'] and failure['kind']=='invalid_source' and failure['detail'] is None


def test_source_row_loss_against_qualified_creation_count_refuses(counts,tmp_path):
    path,pin,_=counter(tmp_path,[{}]);facts=json.loads(pin.read_text());facts['rows']=2;pin.write_text(json.dumps(facts))
    with pytest.raises(ValueError,match='row|Row'):
        counts.count_sources(counter=path,files=[],receipt_keys=['receipts/fixture/source.jsonl.gz'],
            work=tmp_path/'work',source_qualifications={str(path):str(pin)})
    assert not (tmp_path/'work/counts.json').exists()


def test_new_qualified_gzip_source_establishes_its_own_count_without_a_prior_row_total(counts,tmp_path):
    path,pin,_=counter(tmp_path,[{}]);direct=tmp_path/'new.jsonl.gz'
    direct.write_bytes(gzip.compress(b'{}\n',mtime=0));direct_pin=authority(direct,1)
    facts=json.loads(direct_pin.read_text());del facts['rows'];direct_pin.write_text(json.dumps(facts))
    result=counts.count_sources(counter=path,files=[dict(key='receipts/fixture/new.jsonl.gz',path=str(direct))],
        receipt_keys=['receipts/fixture/source.jsonl.gz','receipts/fixture/new.jsonl.gz'],work=tmp_path/'work',
        source_qualifications={str(path):str(pin),str(direct):str(direct_pin)})
    assert sum(r['source_rows'] for r in result)==2 and sum(r['expected_captures'] for r in result)==2


def test_direct_receipt_line_capacity_refuses_an_oversized_line_explicitly(counts,tmp_path):
    path,pin,_=counter(tmp_path,[{}]);direct=tmp_path/'large-line.jsonl.gz'
    direct.write_bytes(gzip.compress(b'{"large":"'+b'x'*(9<<20)+b'"}\n',mtime=0))
    direct_pin=authority(direct,1)
    with pytest.raises(ValueError,match='invalid|resource'):
        counts.count_sources(counter=path,files=[dict(key='receipts/fixture/new.jsonl.gz',path=str(direct))],
            receipt_keys=['receipts/fixture/source.jsonl.gz','receipts/fixture/new.jsonl.gz'],work=tmp_path/'work',
            source_qualifications={str(path):str(pin),str(direct):str(direct_pin)})
    assert not (tmp_path/'work/counts.json').exists()


def test_projected_arrow_batches_preserve_complete_receipt_aggregation(counts,tmp_path):
    records=[dict(record=[{},{}]),{},dict(captures=[{},{}],record=[{},{}]),
        dict(file_references=[{}]),dict(record=[])]
    path,pin,_=counter(tmp_path,records)
    [row]=counts.count_sources(counter=path,files=[],receipt_keys=['receipts/fixture/source.jsonl.gz'],
        work=tmp_path/'work',source_qualifications={str(path):str(pin)},batch_rows=1)
    assert row['source_rows']==5 and row['expected_captures']==8 and row['list_items']==9
