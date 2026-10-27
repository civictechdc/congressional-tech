"""Modern root receipt facts survive counters with older typed projections."""
from copy import deepcopy
import gzip
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets
from test_receipt_writer_contract import attempt,WRITER


def native():
    return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


def modern_receipts(tmp_path):
    from congress_api.models.raw_fetch import FetchResult
    from congress_api.retention.body_store import BodyStore,LocalAdapter
    from congress_api.retention.receipt_writer import ReceiptWriter
    root=tmp_path/'raw'
    writer=ReceiptWriter(BodyStore(LocalAdapter(root)),identity=WRITER,run_id='root-facts',
                         write_date='2026-10-27',archive_limits=None)
    prior=attempt(tmp_path,data=b'partial',status=206,complete=False,transport='prior')
    final=attempt(tmp_path,transport='final')
    fetch_key,fetch=writer.write(FetchResult(final,(prior,)),family='documents')
    evidence=dict(original_url='https://docs.house.gov/original.pdf',
        imported_at='2026-10-21T14:00:00Z',match_basis='reviewed-digest',
        acquisition=dict(prior_access_category='blocked',recovered_url='https://archive.org/recovered.pdf',
                         evidence_sha256='e'*64))
    imported=attempt(tmp_path,data=b'%PDF-1.7\nrecovered\n%%EOF',transport='recovery')
    recovery_key,recovery=writer.write(FetchResult(imported),family='documents',
        mode='retained_import',recovery_evidence=evidence)
    plain=deepcopy(fetch)
    plain.update(run_id='plain',prior_attempts=[],captures=[plain['captures'][0]])
    plain.pop('writer')
    plain_key='receipts/documents/2026-10-27/plain.jsonl.gz'
    (root/plain_key).write_bytes(gzip.compress((json.dumps(plain)+'\n').encode()))
    rows=[(fetch_key,fetch),(recovery_key,recovery),(plain_key,plain)]
    return [dict(key=key,path=str(root/key)) for key,_ in rows],rows


def minimal_counter(tmp_path,rows,field_paths):
    body=pa.list_(pa.struct([('sha256',pa.string())]))
    schema=pa.schema([('record',pa.struct([('url',pa.string())])),('captures',body),
        ('file_references',body),('__receipt_key',pa.string()),('__receipt_line',pa.int64()),
        ('__receipt_family',pa.string()),('__raw_line',pa.string()),('__type_conflicts',pa.list_(pa.string()))])
    if field_paths:
        schema=schema.append(pa.field('__field_paths',pa.list_(pa.string())))
    data=[]
    for key,raw in rows:
        row=dict(record=None,captures=raw['captures'],file_references=None,__receipt_key=key,
            __receipt_line=1,__receipt_family='documents',__raw_line=json.dumps(raw),__type_conflicts=[])
        if field_paths:
            # Root entries use C1's exact path#kind representation; descendants
            # are irrelevant to the three root-object presence decisions.
            row['__field_paths']=[json.dumps([name],separators=(',',':'))+'#'+kind
                for name,kind in [('prior_attempts','array'),('writer','object'),('recovery_evidence','object')]
                if name in raw]
        data.append(row)
    path=tmp_path/'counter.parquet'
    pq.write_table(pa.Table.from_pylist(data,schema=schema),path)
    return path


@pytest.mark.parametrize('field_paths',[False,True])
def test_actual_writer_root_facts_equal_direct_and_missing_typed_counter(tmp_path,field_paths):
    from congress_api.lake.captures import stage_captures
    files,rows=modern_receipts(tmp_path)
    counter=minimal_counter(tmp_path,rows,field_paths)
    expected=stage_captures(files,engine=native(),work=tmp_path/'direct')
    actual=stage_captures([dict(key=row['key']) for row in files],engine=native(),
        work=tmp_path/'counter-stage',validated_counter=counter)
    direct=pq.read_table(expected/'captures.parquet')
    captured=pq.read_table(actual/'captures.parquet')
    values=captured.to_pylist()
    fetched=[row for row in values if row['receipt_key']==files[0]['key']]
    assert [(row['attempt_status'],row['complete']) for row in fetched]==[(200,True),(206,False)]
    [recovery]=[row for row in values if row['receipt_key']==files[1]['key']]
    assert recovery['mode']=='retained_import' and recovery['original_url']=='https://docs.house.gov/original.pdf'
    assert recovery['recovered_url']=='https://archive.org/recovered.pdf'
    assert recovery['match_basis']=='reviewed-digest' and recovery['recovery_category']=='blocked'
    assert recovery['evidence_sha256']==bytes.fromhex('e'*64)
    assert recovery['imported_at'].isoformat()=='2026-10-21T14:00:00+00:00'
    assert all(row['writer_job']==WRITER['job'] and row['writer_commit']==WRITER['commit']
               for row in values if row['receipt_key']!=files[2]['key'])
    [plain]=[row for row in values if row['receipt_key']==files[2]['key']]
    assert plain['mode']=='fetch' and plain['original_url'] is None and plain['evidence_sha256'] is None
    assert plain['writer_job'] is None and plain['writer_commit'] is None
    assert captured.equals(direct)


def test_missing_typed_root_prior_is_narrowed_before_payload_fanout(tmp_path):
    from congress_api.lake.receipt_metadata import compact
    files,rows=modern_receipts(tmp_path)
    key,source=rows[0]
    raw=deepcopy(source)
    marker='root-prior-body-must-stay-raw-'
    raw['prior_attempts'][0]['content']={'body':marker*5000}
    counter=minimal_counter(tmp_path,[(key,raw)],True)
    output=compact(counter=counter,engine=native(),work=tmp_path/'metadata')
    [metadata]=pq.read_table(output).to_pylist()
    assert marker not in metadata['line'] and marker not in metadata['record_json']
    assert len(metadata['line'].encode())<32768
    line=json.loads(metadata['line'])
    prior=line.get('prior_attempts')
    if prior is None:
        prior=json.loads(line['_ingest_prior_attempts_json'])
    assert prior[0]['http_status']==206


@pytest.mark.parametrize('operation',['plan','pins','compact','batch','stage'])
def test_raw_counter_directories_refuse_before_registration(tmp_path,operation):
    from congress_api.lake import receipt_metadata
    from congress_api.lake.captures import stage_captures
    root=tmp_path/'counter-directory';root.mkdir()
    (root/'root.parquet').write_bytes(b'not-a-counter')
    partition=root/'part=1';partition.mkdir()
    (partition/'nested.parquet').write_bytes(b'unpinned')
    class UnopenedEngine:
        source_revision='fixture';binary_sha256='a'*64
        def run_job(self,path):
            raise AssertionError('Unsupported directory reached native registration')
    engine=UnopenedEngine()
    with pytest.raises(ValueError,match='single.*file'):
        if operation=='plan':
            receipt_metadata.metadata_plan(counter=root)
        elif operation=='pins':
            receipt_metadata.source_pins(counter=root)
        elif operation=='compact':
            receipt_metadata.compact(counter=root,engine=engine,work=tmp_path/'work')
        elif operation=='batch':
            receipt_metadata.compact_counter(root,engine=engine,work=tmp_path/'work')
        else:
            stage_captures([dict(key='receipts/f/2026-10-27/a.gz')],engine=engine,
                           work=tmp_path/'work',validated_counter=root)
    assert not list(tmp_path.rglob('job.json'))
