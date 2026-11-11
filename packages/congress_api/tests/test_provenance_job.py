"""A native job can own a fresh nested work directory, and keeps what the engine said beside its spec."""
from hashlib import sha256
import json
import os
import re

import pytest

from congress_api.retention.provenance import field, run_job


def test_native_job_creates_a_fresh_work_root_before_writing_its_spec(tmp_path):
    root=tmp_path/'fresh'/'nested'
    class Engine:
        def run_job(self,path,**options):  # a wrapper that does not name `log` is still asked to keep it
            assert path==root/'job.json' and path.is_file() and options==dict(log=root/'engine.log')
            spec=json.loads(path.read_text())
            assert spec['scratch']==str(root/'native')
            assert spec['queries']==[dict(name='one',sql='SELECT 1 AS n')]
            return dict(queries=[dict(name='one',data=[dict(n=1)])])
    result=run_job(root,Engine(),inputs=[],steps=[],outputs=[],queries=[dict(name='one',sql='SELECT 1 AS n')])
    assert result==dict(one=[dict(n=1)])
    assert json.loads((root/'result.json').read_text())['queries'][0]['data']==[dict(n=1)]


STEPS=[dict(name='one',sql='SELECT 1 AS x')]
# An engine failure's first line is its code, then (on an engine that names it, the one line's X2) the failing
# statement, then the cause.
STATEMENT=r'(?:(?:query|step|output) \d+ "[^"]+": )?'


def native():
    from docspec_client.client import NativeDatasets
    return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


def test_a_passing_job_leaves_its_step_events_beside_its_spec(tmp_path):
    from docspec_client.models import metric_events
    assert run_job(tmp_path/'job',native(),inputs=[],steps=STEPS,outputs=[],queries=[dict(name='q',sql='SELECT x FROM one')])==dict(q=[dict(x=1)])
    events=list(metric_events(tmp_path/'job/engine.log'))
    assert [(e['event'],e.get('name')) for e in events if e['event']=='step']==[('step','one'),('step','query:q')]
    assert sorted(p.name for p in (tmp_path/'job').iterdir() if p.is_file())==['engine.log','job.json','result.json']


def test_a_job_through_the_publication_runtime_keeps_its_log(tmp_path):
    """The publish job hands its engine on inside this wrapper, which forwards run_job by attribute lookup."""
    from viewer_publication.archive_publish_job import PublicationRuntime
    engine=native()
    assert run_job(tmp_path/'job',PublicationRuntime(engine,engine),inputs=[],steps=STEPS,outputs=[],
        queries=[dict(name='q',sql='SELECT x FROM one')])==dict(q=[dict(x=1)])
    assert (tmp_path/'job/engine.log').read_text().startswith('[docspec-metric] ')


def test_a_failing_job_says_what_failed_first_and_keeps_the_whole_stream(tmp_path):
    """The failed nightly 20261110T111252Z in small: a JSON-lines source that cannot be opened, after work that logged metrics."""
    from docspec_client.models import DocSpecFailure
    absent=dict(name='absent',kind='json_lines',files=[dict(key='absent',path=str(tmp_path/'absent.jsonl.gz'))],
        schema=dict(fields=[field('x','Int64')],metadata={}))
    with pytest.raises(DocSpecFailure,match='source open failed') as raised:
        run_job(tmp_path/'job',native(),inputs=[absent],steps=STEPS,outputs=[],
            queries=[dict(name='before',sql='SELECT x FROM one'),dict(name='q',sql='SELECT count(*) AS n FROM absent')])
    error=raised.value
    # The failing query by name where the engine gives it; the one line also adds the path and the OS error.
    assert re.fullmatch(r'query: (?:query \d+ "q": )?Execution error: absent line 1: source open failed'
                        r'(?:: .+/absent\.jsonl\.gz: No such file or directory.*)?',str(error).splitlines()[0]),str(error)
    assert '[docspec-metric]' not in str(error) and 'Caused by:' in str(error)
    assert error.stderr.startswith('[docspec-metric] ') and error.stderr==(tmp_path/'job/engine.log').read_text()
    assert error.code is None and error.completed['queries'][0]['name']=='before'


# query() and explain(): one read-only statement over named tables, with no job file to write (cause F).
A,B,C=(sha256(value).digest() for value in (b'a',b'b',b'c'))


def capture_files(tmp_path,rows=3):
    import pyarrow as pa
    import pyarrow.parquet as pq
    captures=pa.table({'receipt_key':pa.array(['r1','r2','r3'][:rows],pa.string()),
        'sha256':pa.array([A,A,B][:rows],pa.binary()),'family':['video','video','html'][:rows]},
        schema=pa.schema([pa.field('receipt_key',pa.string(),nullable=False),pa.field('sha256',pa.binary()),
                          pa.field('family',pa.string())]))
    pq.write_table(captures,tmp_path/'captures.parquet')
    pq.write_table(pa.table({'sha':[A.hex(),C.hex()]}),tmp_path/'cited.parquet')
    return dict(captures=tmp_path/'captures.parquet',cited=tmp_path/'cited.parquet')


JOINED="SELECT k.sha,c.receipt_key FROM cited k JOIN captures c ON lower(encode(c.sha256,'hex'))=k.sha ORDER BY 2"


def test_one_call_returns_the_rows_of_a_statement_over_named_parquet_files(tmp_path,monkeypatch):
    import tempfile
    from congress_api.retention.provenance import query
    monkeypatch.setattr(tempfile,'tempdir',str(tmp_path/'tmp'));(tmp_path/'tmp').mkdir()
    tables=capture_files(tmp_path)
    rows=query(native(),JOINED,tables)
    assert rows==[dict(sha=A.hex(),receipt_key='r1'),dict(sha=A.hex(),receipt_key='r2')]
    assert list(rows[0])==['sha','receipt_key']  # the statement's order; the engine's JSON sorts names
    # The engine's JSON: binary as lowercase hex, SQL NULL as None.
    assert query(native(),"SELECT sha256,NULL AS nothing FROM captures WHERE receipt_key='r3'",tables)==[
        dict(sha256=B.hex(),nothing=None)]
    assert list((tmp_path/'tmp').iterdir())==[]  # the throwaway job leaves nothing behind


def test_a_kept_query_is_a_job_with_no_steps_or_outputs_under_small_memory_and_scratch(tmp_path):
    from congress_api.retention.provenance import QUERY_MEMORY_BYTES,QUERY_SCRATCH_BYTES,query
    engine=native();sql='SELECT count(*) AS n FROM captures'
    assert query(engine,sql,capture_files(tmp_path),work=tmp_path/'kept')==[dict(n=3)]
    spec=json.loads((tmp_path/'kept/job.json').read_text())
    assert spec['steps']==spec['outputs']==[] and [i['name'] for i in spec['inputs']]==['captures','cited']
    assert spec['queries']==[dict(name='columns',sql='EXPLAIN FORMAT pgjson '+sql),dict(name='query',sql=sql)]
    runtime=json.loads(engine.limits.read_text())
    # The local runtime allows more of both; a query gets less, so a stopped query leaves at most this much spill.
    assert runtime['memory_bytes']>QUERY_MEMORY_BYTES and runtime['scratch_bytes']>QUERY_SCRATCH_BYTES
    assert json.loads((tmp_path/'kept/limits.json').read_text())=={
        **runtime,'memory_bytes':QUERY_MEMORY_BYTES,'scratch_bytes':QUERY_SCRATCH_BYTES}
    assert (tmp_path/'kept/engine.log').read_text().startswith('[docspec-metric] ')


def test_a_kept_query_refuses_a_folder_that_already_holds_files(tmp_path):
    """A rerun into the same folder would leave the last run's result.json or limits.json beside the new job."""
    from congress_api.retention.provenance import query
    kept=tmp_path/'kept';kept.mkdir();(kept/'result.json').write_text('{}')
    with pytest.raises(ValueError,match='not empty'):
        query(native(),'SELECT 1 AS n',{},work=kept)
    assert [path.name for path in kept.iterdir()]==['result.json']
    (tmp_path/'empty').mkdir()
    assert query(native(),'SELECT 1 AS n',{},work=tmp_path/'empty')==[dict(n=1)]


@pytest.mark.parametrize('sql',['SELECT k.sha,c.sha FROM cited k LEFT JOIN cited c ON c.sha=k.sha',
                                'SELECT * FROM cited k LEFT JOIN cited c ON c.sha=k.sha'])
def test_a_statement_returning_two_columns_of_one_name_is_refused(tmp_path,sql):
    """The engine returns each row as a map, so one `sha` would silently replace the other: in a LEFT JOIN the right
    side's NULL replaced the left key (engine src/job/query_result.rs:58-76 at the pin). The plan names them first."""
    from congress_api.retention.provenance import query
    with pytest.raises(ValueError,match="2 columns named 'sha'"):
        query(native(),sql,capture_files(tmp_path))


def test_the_memory_limit_reaches_the_engine(tmp_path):
    """A sort that fits the default limit is refused for memory by the engine at 1 MiB (plant: the limit is not
    passed on). Where it refuses depends on the engine. The pin's view copy of the scanned batch reserves first and
    is refused by the engine's budget (code capacity, src/storage/batch/views.rs:148 at b0342a7). The one line skips
    a copy that frees under 1 MiB (MIN_FREED), so DataFusion's own pool refuses the TopK (code query, "Resources
    exhausted"); both engines give a DataFusion refusal the code query (src/error.rs)."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    from docspec_client.models import DocSpecFailure
    from congress_api.retention.provenance import query
    pq.write_table(pa.table({'k':[f'key-{i:06d}-'+'x'*40 for i in range(20000)]}),tmp_path/'big.parquet')
    sql='SELECT count(*) AS n FROM (SELECT k FROM big ORDER BY k DESC LIMIT 5000)'
    assert query(native(),sql,dict(big=tmp_path/'big.parquet'))==[dict(n=5000)]
    with pytest.raises(DocSpecFailure) as raised:
        query(native(),sql,dict(big=tmp_path/'big.parquet'),memory_bytes=1<<20)
    assert re.match(r'(?:capacity|query): '+STATEMENT+
                    r'(?:External error: capacity: shared memory budget exhausted|Resources exhausted): ',
                    str(raised.value)),str(raised.value)


def test_explain_returns_the_logical_and_physical_plans_without_running_the_statement(tmp_path):
    from docspec_client.models import DocSpecFailure
    from congress_api.retention.provenance import explain,query
    tables=capture_files(tmp_path)
    plans=explain(native(),JOINED,tables)
    assert set(plans)=={'logical_plan','physical_plan'}
    assert 'Inner Join' in plans['logical_plan'] and 'TableScan: captures' in plans['logical_plan']
    assert 'HashJoinExec' in plans['physical_plan']
    failing='SELECT CAST(receipt_key AS INT) AS n FROM captures'  # fails only when it runs
    assert 'CAST' in explain(native(),failing,tables)['logical_plan'].upper()
    with pytest.raises(DocSpecFailure):
        query(native(),failing,tables)
    measured=explain(native(),JOINED,tables,analyze=True)  # this one runs, and says what each operator did
    assert 'HashJoinExec' in measured['Plan with Metrics'] and 'output_rows=2' in measured['Plan with Metrics']
    with pytest.raises(DocSpecFailure,match='Nested EXPLAINs'):  # plans come from explain(), not query()
        query(native(),'EXPLAIN '+JOINED,tables)


def test_a_failing_statement_raises_the_engines_own_error_first(tmp_path):
    from docspec_client.models import DocSpecFailure
    from congress_api.retention.provenance import query
    with pytest.raises(DocSpecFailure) as raised:
        query(native(),'SELECT nope FROM cited',capture_files(tmp_path))
    assert re.fullmatch('query: '+STATEMENT+r'Schema error: No field named nope\. Valid fields are cited\.sha\.',
                        str(raised.value).splitlines()[0]),str(raised.value)
    assert '[docspec-metric]' not in str(raised.value)


@pytest.mark.parametrize('statement,refusal',[
    ("COPY (SELECT sha FROM cited) TO '{target}'",'DML not supported: COPY'),
    ("CREATE EXTERNAL TABLE copied STORED AS PARQUET LOCATION '{target}'",'DDL not supported'),
    ("INSERT INTO cited VALUES ('d')",'DML not supported: Insert Into')])
def test_a_statement_that_writes_is_refused_and_writes_nothing(tmp_path,statement,refusal):
    """Read-only by construction: the engine plans no DDL or DML in a job query, and query() adds no outputs."""
    from docspec_client.models import DocSpecFailure
    from congress_api.retention.provenance import query
    tables=capture_files(tmp_path);target=tmp_path/'written.parquet'
    before={path:path.read_bytes() for path in tables.values()}
    with pytest.raises(DocSpecFailure,match=refusal):
        query(native(),statement.format(target=target),tables)
    assert not target.exists() and {path:path.read_bytes() for path in tables.values()}==before


def test_a_local_lake_pin_is_bound_read_only_like_a_parquet_file(tmp_path):
    """The pinned lake tables bind through tables.table_input, as every job binds them; here a local catalog."""
    from congress_api.lake import tables
    from congress_api.retention.provenance import query
    engine=native();catalog=tmp_path/'catalog';ref=dict(namespace=['fixture'],name='captures')
    schema={'type':'struct','schema-id':0,'identifier-field-ids':[1],'fields':[
        dict(id=1,name='receipt_key',required=True,type='string'),dict(id=2,name='sha256',required=False,type='binary'),
        dict(id=3,name='family',required=False,type='string')]}
    tables.create_table(engine=engine,work=tmp_path/'create',catalog_root=catalog,table=ref,schema=schema,
                        location=tmp_path/'lake',create_namespace=True)
    appended=tables.append_rows(capture_files(tmp_path)['captures'],engine=engine,work=tmp_path/'append',
        catalog_root=catalog,table=ref,keys=['receipt_key'],definition='query fixture')
    pin={key:appended[key] for key in ('metadata_location','table_uuid','snapshot','schema_id')}
    lake=sorted(path.relative_to(tmp_path) for path in (tmp_path/'lake').rglob('*'))
    assert query(engine,JOINED,dict(captures=pin,cited=tmp_path/'cited.parquet'),work=tmp_path/'q')==[
        dict(sha=A.hex(),receipt_key='r1'),dict(sha=A.hex(),receipt_key='r2')]
    assert json.loads((tmp_path/'q/job.json').read_text())['inputs'][0]==dict(name='captures',kind='native_table',**pin)
    assert sorted(path.relative_to(tmp_path) for path in (tmp_path/'lake').rglob('*'))==lake
