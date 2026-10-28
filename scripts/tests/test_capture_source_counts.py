"""Independent event-stream totals bind D1's reference-first, missing-item grain."""
import cProfile
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def counts():
    path=Path(__file__).resolve().parents[1]/'measure/cxb_capture_source_counts.py'
    spec=importlib.util.spec_from_file_location('capture_source_counts_under_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def authority(path,rows):
    qualification=path.with_suffix(path.suffix+'.qualification.json')
    qualification.write_text(json.dumps(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        size=path.stat().st_size,rows=rows,producer='fixture')))
    return qualification


def receipt(tmp_path,records,*,name='source'):
    path=tmp_path/(name+'.jsonl.gz')
    raw=[json.dumps(r,separators=(',',':'),ensure_ascii=False) for r in records]
    compressed=gzip.compress(('\n'.join(raw)+'\n').encode(),mtime=0);path.write_bytes(compressed)
    source=dict(key='receipts/fixture/'+name+'.jsonl.gz',path=str(path),size=len(compressed),
        etag='"'+hashlib.md5(compressed).hexdigest()+'"')
    return source,authority(path,len(raw)),raw


def run(counts,tmp_path,files,pins,*,work='work',keys=None):
    return counts.count_sources(files=files,receipt_keys=keys or [f['key'] for f in files],
        work=tmp_path/work,source_qualifications={f['path']:str(p) for f,p in zip(files,pins)})


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
    source,pin,raw=receipt(tmp_path,[record])
    result=run(counts,tmp_path,[source],[pin])
    assert result==[dict(key=source['key'],source_rows=1,uncompressed_bytes=len(raw[0].encode()),
        list_items=items,expected_captures=expected,max_line_bytes=len(raw[0].encode()),max_line_items=items)]
    assert json.loads((tmp_path/'work/counts.json').read_text())==result
    assert json.loads((tmp_path/'work/metrics.json').read_text())['parsed_lines']==1


def test_original_gzip_inputs_group_only_small_receipt_metrics(counts,tmp_path):
    first,pin,raw=receipt(tmp_path,[{},dict(record=[{},{}])])
    second,other,other_raw=receipt(tmp_path,[dict(record=[{},{},{}]),{}],name='new')
    result=run(counts,tmp_path,[first,second],[pin,other])
    assert [r['key'] for r in result]==sorted([first['key'],second['key']])
    assert [r['source_rows'] for r in result]==[2,2]
    assert sum(r['expected_captures'] for r in result)==7
    assert sum(r['list_items'] for r in result)==7
    assert sum(r['uncompressed_bytes'] for r in result)==sum(len(s.encode()) for s in raw+other_raw)
    assert not list((tmp_path/'work').glob('*.parquet'))


@pytest.mark.parametrize('record',[{'captures':{}},{'file_references':'lost-list'}])
def test_malformed_reference_lists_refuse_without_accepted_counts(counts,tmp_path,record):
    source,pin,_=receipt(tmp_path,[record])
    with pytest.raises(ValueError,match='[Mm]alformed|[Ii]nvalid'):run(counts,tmp_path,[source],[pin])
    assert not (tmp_path/'work/counts.json').exists()


def test_missing_selected_receipt_refuses_without_a_partial_success(counts,tmp_path):
    source,pin,_=receipt(tmp_path,[{}])
    with pytest.raises(ValueError,match='receipt|Receipt'):
        run(counts,tmp_path,[source],[pin],keys=[source['key'],'receipts/fixture/lost.jsonl.gz'])
    assert not (tmp_path/'work/counts.json').exists()


def test_malformed_original_json_line_refuses(counts,tmp_path):
    source,pin,_=receipt(tmp_path,[{}]);path=Path(source['path'])
    data=gzip.compress(b'{"missing":\n',mtime=0);path.write_bytes(data)
    source.update(size=len(data),etag=hashlib.md5(data).hexdigest());pin=authority(path,1)
    with pytest.raises(ValueError,match='[Mm]alformed|[Ii]nvalid'):run(counts,tmp_path,[source],[pin])
    assert not (tmp_path/'work/counts.json').exists()
    failure=json.loads((tmp_path/'work/error.json').read_text())
    assert failure['error_class'] and failure['kind']=='invalid_source' and failure['detail'] is None


def test_source_row_loss_against_qualified_creation_count_refuses(counts,tmp_path):
    source,pin,_=receipt(tmp_path,[{}]);facts=json.loads(pin.read_text());facts['rows']=2;pin.write_text(json.dumps(facts))
    with pytest.raises(ValueError,match='row|Row'):run(counts,tmp_path,[source],[pin])
    assert not (tmp_path/'work/counts.json').exists()


def test_new_qualified_gzip_source_establishes_its_own_count_without_a_prior_row_total(counts,tmp_path):
    source,pin,_=receipt(tmp_path,[{}]);facts=json.loads(pin.read_text());del facts['rows'];pin.write_text(json.dumps(facts))
    result=run(counts,tmp_path,[source],[pin])
    assert sum(r['source_rows'] for r in result)==sum(r['expected_captures'] for r in result)==1


@pytest.mark.parametrize('size',[9<<20,12<<20])
def test_whole_large_line_is_counted_without_an_artificial_sql_pool_or_line_limit(counts,tmp_path,size):
    source,pin,raw=receipt(tmp_path,[dict(record={'body':'x'*size})])
    [row]=run(counts,tmp_path,[source],[pin])
    assert row['source_rows']==row['expected_captures']==row['list_items']==1
    assert row['uncompressed_bytes']==len(raw[0].encode())


def test_many_lines_remain_one_complete_receipt_total(counts,tmp_path):
    source,pin,_=receipt(tmp_path,[dict(record=[{},{}]),{},dict(captures=[{},{}],record=[{},{}]),
        dict(file_references=[{}]),dict(record=[])])
    [row]=run(counts,tmp_path,[source],[pin])
    assert row['source_rows']==5 and row['expected_captures']==8 and row['list_items']==9


def test_receipt_totals_do_not_require_holding_every_source_line(counts,tmp_path):
    size=131072;source,pin,_=receipt(tmp_path,[{}]*size)
    [row]=run(counts,tmp_path,[source],[pin])
    assert row['source_rows']==row['expected_captures']==row['list_items']==size


def test_each_original_line_enters_the_stream_parser_exactly_once(counts,tmp_path):
    source,pin,_=receipt(tmp_path,[{},dict(record=[{},{}]),dict(captures=[{},{}])])
    profile=cProfile.Profile();result=profile.runcall(run,counts,tmp_path,[source],[pin])
    calls=sum(e.callcount for e in profile.getstats() if e.code is counts.ijson.basic_parse.__code__)
    assert calls==3 and result[0]['source_rows']==3 and result[0]['expected_captures']==5


def test_mutating_one_source_list_changes_the_independent_total(counts,tmp_path):
    source,pin,_=receipt(tmp_path,[dict(record=[{},{}])]);before=run(counts,tmp_path,[source],[pin],work='before')
    changed,changed_pin,_=receipt(tmp_path,[dict(record=[{},{},{}])])
    after=run(counts,tmp_path,[changed],[changed_pin],work='after')
    assert before[0]['source_rows']==after[0]['source_rows']==1
    assert (before[0]['expected_captures'],after[0]['expected_captures'])==(2,3)


def test_inventory_checksum_is_checked_during_the_same_compressed_read(counts,tmp_path):
    source,pin,_=receipt(tmp_path,[{}]);source['etag']='0'*32
    with pytest.raises(ValueError,match='checksum|MD5'):run(counts,tmp_path,[source],[pin])
    assert not (tmp_path/'work/counts.json').exists()


def test_opaque_multipart_inventory_etag_keeps_a_separate_verified_local_md5(counts,tmp_path):
    source,pin,_=receipt(tmp_path,[{}]);source['md5']=source['etag'].strip('"')
    source['etag']='"opaque-multipart-16"'
    [row]=run(counts,tmp_path,[source],[pin])
    assert row['expected_captures']==1
    [proof]=json.loads((tmp_path/'work/metrics.json').read_text())['sources']
    assert proof['etag']==source['etag'] and proof['md5']==source['md5']
