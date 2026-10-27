"""Native recovery reconciliation and thin imports through the common raw writer."""
from datetime import timezone
import gzip
from hashlib import file_digest
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.models.raw_fetch import BodyFile,FetchAttempt,FetchResult
from congress_api.retention.provenance import (
    file_pin,finish_stage,instant,json_input,parquet_output,parquet_records,run_job,stage_records,
)
from congress_api.retention.sniff import read_sniff_file
from congress_api.retention.receipt_privacy import basename
from congress_api.retention.body_store import validate_record
from congress_api.retention.recovery_facts import project_legacy


def import_retained(writer,source):
    """One retained file becomes one recovery receipt; no storage loop or index."""
    required=('original_url','recovered_url','body_sha256','retrieved_at',
              'category','match_basis','imported_at')
    if any(not isinstance(source.get(k),str) or not source[k] for k in required):
        raise ValueError('Recovery needs its original link, category, exact body and source time')
    instant(source['retrieved_at']);instant(source['imported_at'])
    for key in ('original_url','recovered_url'):
        parts=urlsplit(source[key])
        if parts.scheme not in {'http','https'} or not parts.hostname:
            raise ValueError('Recovery needs absolute public URLs')
    if source.get('retained_reference') is True:
        if (re.fullmatch('[0-9a-f]{64}',source['body_sha256']) is None
                or type(source.get('bytes')) is not int or source['bytes']<0
                or source.get('stored_suffix') not in {'','.gz'}):
            raise ValueError('Retained reference needs its exact digest, original size and stored suffix')
        body=BodyFile(None,source['body_sha256'],source['bytes'],source.get('media_type'),
            source.get('sniffed_format'),source.get('sniff_version'),source.get('intact'),
            stored_suffix=source['stored_suffix'])
        return _write_import(writer,source,body)
    if not isinstance(source.get('body_path'),str) or not source['body_path']:
        raise ValueError('New recovery needs a retained local file')
    with TemporaryDirectory(prefix='retained-import-') as temporary:
        path=Path(source['body_path'])
        if source.get('stored_gzip'):
            unpacked=Path(temporary)/'body'
            with gzip.open(path,'rb') as src,unpacked.open('xb') as dst:
                import shutil
                shutil.copyfileobj(src,dst,1024**2)
            path=unpacked
        with path.open('rb') as body:
            digest=file_digest(body,'sha256').hexdigest()
        if digest!=source['body_sha256']:raise ValueError('Recovery body changed')
        reading=read_sniff_file(path)
        body=BodyFile(path,digest,path.stat().st_size,source.get('media_type'),
            reading['format'],reading['parser_version'],reading['intact'],reading.get('error_type'))
        return _write_import(writer,source,body)


def _write_import(writer,source,body):
    attempt=FetchAttempt(source['recovered_url'],source['recovered_url'],source['retrieved_at'],
                         'retained-import',200,None,{},(),True,body)
    acquisition=dict(prior_access_category=source['category'],recovered_url=source['recovered_url'],
        evidence_sha256=source.get('evidence_sha256'),observed_capture_timestamp=source['retrieved_at'])
    if source.get('body_path'):acquisition['body_path']=basename(source['body_path'])
    elif source.get('recovered_filename'):acquisition['body_path']=source['recovered_filename']
    if source.get('source_receipt_key'):
        acquisition['source_receipt']=dict(key=source['source_receipt_key'],line=source['source_receipt_line'],
                                           capture_index=source['source_capture_index'])
    evidence=dict(original_url=source['original_url'],imported_at=source['imported_at'],
                  match_basis=source['match_basis'],acquisition=acquisition)
    return writer.write(FetchResult(attempt),family='documents',mode='retained_import',
                        recovery_evidence=evidence,fidelity=source.get('fidelity','retained-file'))


def capture_input(path):
    """Expose normalized capture facts, accepting the DM digest's binary form."""
    schema=pq.read_schema(path)
    required={'sha256','mode','original_url','recovered_url','match_basis','recovery_category',
              'url','retrieved_at','receipt_key','receipt_line','capture_index','bytes','media_type'}
    if not required.issubset(schema.names):raise ValueError('Reconciliation requires normalized capture facts')
    digest="encode(sha256,'hex')" if pa.types.is_binary(schema.field('sha256').type) or pa.types.is_fixed_size_binary(schema.field('sha256').type) else 'sha256'
    optional=','.join((name if name in schema.names else 'cast(NULL AS '+kind+') AS '+name)
        for name,kind in [('recovered_filename','VARCHAR'),('sniffed_format','VARCHAR'),
                          ('sniff_version','VARCHAR'),('intact','BOOLEAN')])
    suffix='stored_suffix' if 'stored_suffix' in schema.names else "'.gz' AS stored_suffix"
    return dict(name='capture_input',kind='parquet',path=str(Path(path).resolve())),f'''SELECT
        {digest} AS body_hex,mode,original_url,recovered_url,match_basis,recovery_category,
        url,cast(retrieved_at AS VARCHAR) AS retrieved_at,receipt_key,receipt_line,capture_index,bytes,media_type,{optional},{suffix}
        FROM capture_input'''


def reconcile(accepted,captures,registry,*,output,engine,decided_at,decided_by):
    instant(decided_at)
    if not isinstance(decided_by,str) or not decided_by:raise ValueError('Reconciliation needs its decision process')
    accepted,captures,registry=map(Path,(accepted,captures,registry))
    value=json.loads(accepted.read_text())
    if value.get('version')!=1:raise ValueError('Unsupported accepted recovery version')
    mappings=value['recoveries']
    if not isinstance(mappings,list) or not mappings:raise ValueError('Accepted recovery mappings are required')
    validate_record(mappings)
    for row in mappings:
        for name in ('original_url','recovered_url'):
            parts=urlsplit(row[name])
            if parts.scheme not in {'http','https'} or not parts.hostname:
                raise ValueError('Invalid accepted recovery URL')
    kinds=json.loads(registry.read_text())
    if not isinstance(kinds,list) or not kinds:raise ValueError('Recovery-kind registry is required')
    for row in kinds:
        if (not {'category','match_basis','kind'}.issubset(row)
                or set(row)-{'category','match_basis','kind','import_category'}
                or not row['kind'] or bool(row['category'])==bool(row['match_basis'])):
            raise ValueError('Registry rows map exactly one category or match basis to a display kind')
    capture,projection=capture_input(captures)
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    jobs=output/'jobs';jobs.mkdir()
    inputs=[json_input(jobs,'accepted_input',mappings,original_url='Utf8',recovered_url='Utf8',
        body_key='Utf8',kind='Utf8',recovery_basis='Utf8',recovery_status='Utf8'),capture,
        json_input(jobs,'kind_registry',kinds,category='Utf8',match_basis='Utf8',kind='Utf8',import_category='Utf8')]
    steps=[dict(name='captures',sql=projection),
        dict(name='accepted',sql='''SELECT *,substr(body_key,18,64) AS body_hex FROM accepted_input'''),
        dict(name='recovery_pairs',materialize=True,sql='''SELECT original_url,body_hex,count(*) AS receipt_rows,
            max(recovery_category) AS category,count(DISTINCT recovery_category) AS category_count,
            array_agg(DISTINCT match_basis) AS bases,array_agg(DISTINCT recovered_url) AS recovered_urls
            FROM captures WHERE mode='retained_import' GROUP BY original_url,body_hex'''),
        dict(name='name_candidates',sql='''SELECT a.original_url,a.body_hex,c.recovered_filename,
            row_number() OVER (PARTITION BY a.original_url,a.body_hex ORDER BY c.retrieved_at DESC,
                c.receipt_key,c.receipt_line,c.capture_index) AS ordinal FROM accepted a JOIN captures c
            ON a.body_hex=c.body_hex AND (a.original_url=c.original_url OR a.recovered_url=c.url)
            WHERE c.recovered_filename IS NOT NULL'''),
        dict(name='decisions',materialize=True,sql='''SELECT a.*,r.receipt_rows,r.category,r.category_count,r.bases,r.recovered_urls,
            CASE WHEN r.category IS NOT NULL THEN k.kind ELSE b.kind END AS display_kind,n.recovered_filename,
            b.import_category,
            (r.category IS NOT NULL AND k.kind IS NULL) AS unknown_category
            FROM accepted a LEFT JOIN recovery_pairs r ON a.original_url=r.original_url AND a.body_hex=r.body_hex
            LEFT JOIN kind_registry k ON r.category=k.category
            LEFT JOIN kind_registry b ON a.recovery_basis=b.match_basis
            LEFT JOIN name_candidates n ON a.original_url=n.original_url AND a.body_hex=n.body_hex AND n.ordinal=1'''),
        dict(name='source_candidates',sql='''SELECT a.original_url,a.body_hex,c.retrieved_at,c.bytes,c.media_type,
            c.receipt_key AS source_receipt_key,c.receipt_line AS source_receipt_line,c.capture_index AS source_capture_index,
            c.sniffed_format,c.sniff_version,c.intact,c.stored_suffix,c.recovery_category AS source_category,
            row_number() OVER (PARTITION BY a.original_url,a.body_hex ORDER BY c.retrieved_at DESC,
                c.receipt_key,c.receipt_line,c.capture_index) AS ordinal
            FROM decisions a JOIN captures c ON a.body_hex=c.body_hex AND a.recovered_url=c.url
            WHERE a.receipt_rows IS NULL AND try_cast(c.retrieved_at AS TIMESTAMP) IS NOT NULL
                AND regexp_like(c.retrieved_at,'[Tt ][0-9]{2}:[0-9]{2}')
                AND regexp_like(c.retrieved_at,'(Z|[+-][0-9]{2}:[0-9]{2})$')''')]
    q=lambda text:text.replace("'","''")
    pin=file_pin(accepted)['sha256']
    decision_sql=f'''SELECT encode(sha256('accepted:{pin}:' || original_url || ':' || body_hex),'hex') AS id,
        original_url,recovered_url,recovered_filename,body_hex AS body_sha256,
        display_kind AS kind,recovery_basis AS match_basis,'{pin}' AS evidence_sha256,
        'Reconciled from pinned accepted mappings {pin}; receipt categories preserved' AS identity_note,
        '{q(decided_by)}' AS decided_by,'{q(decided_at)}' AS decided_at,cast(NULL AS VARCHAR) AS supersedes
        FROM decisions'''
    missing_sql=f'''SELECT d.original_url,d.recovered_url,d.body_hex AS body_sha256,d.body_key,
        i.category,d.display_kind,d.recovery_basis AS match_basis,s.retrieved_at,s.bytes,s.media_type,
        s.source_receipt_key,s.source_receipt_line,s.source_capture_index,d.recovered_filename,
        s.sniffed_format,s.sniff_version,s.intact,s.stored_suffix,s.source_category,d.import_category AS planned_category,
        '{pin}' AS evidence_sha256,
        CASE WHEN s.retrieved_at IS NULL THEN 'source_timestamp_not_established'
             WHEN s.bytes IS NULL THEN 'source_size_not_established'
             WHEN s.stored_suffix IS NULL THEN 'stored_suffix_not_established'
             WHEN i.category IS NULL THEN 'recovery_category_not_established' ELSE 'ready_for_owner_import' END AS status
        FROM decisions d LEFT JOIN source_candidates s ON d.original_url=s.original_url AND d.body_hex=s.body_hex AND s.ordinal=1
        LEFT JOIN kind_registry i ON i.category=coalesce(s.source_category,d.category,d.import_category) AND i.kind=d.display_kind
        WHERE d.receipt_rows IS NULL'''
    receipt_only='''SELECT c.* FROM captures c LEFT JOIN accepted a ON c.original_url=a.original_url AND c.body_hex=a.body_hex
        WHERE c.mode='retained_import' AND a.original_url IS NULL'''
    queries=[dict(name='invariants',sql='''SELECT
        (SELECT count(*) FROM decisions WHERE display_kind IS NULL OR unknown_category OR category_count>1) AS invalid,
        (SELECT count(*) FROM decisions) AS decisions,
        (SELECT count(*) FROM accepted) AS accepted,
        (SELECT count(*) FROM (SELECT original_url FROM accepted GROUP BY original_url HAVING count(*)>1)) AS duplicate_accepted,
        (SELECT count(*) FROM accepted WHERE NOT coalesce(
            regexp_like(body_key,'^bodies/sha256/[a-f0-9]{2}/[a-f0-9]{64}[.]gz$') AND
            substr(body_key,15,2)=substr(body_hex,1,2) AND recovery_status='recovered' AND
            kind IN ('pdf','html','xml','doc','video') AND
            regexp_like(original_url,'^https?://[^/]+') AND regexp_like(recovered_url,'^https?://[^/]+'),false)) AS invalid_accepted,
        (SELECT count(*) FROM (SELECT category,match_basis FROM kind_registry GROUP BY category,match_basis HAVING count(*)>1)) AS duplicate_registry'''),
        dict(name='counts',sql=f'''SELECT (SELECT count(*) FROM accepted) AS accepted,
            count(*) FILTER(WHERE receipt_rows IS NOT NULL) AS matched,
            count(*) FILTER(WHERE receipt_rows IS NULL) AS accepted_only,
            (SELECT count(*) FROM ({receipt_only})) AS receipt_only,
            count(*) FILTER(WHERE receipt_rows IS NOT NULL AND
                (NOT coalesce(array_has(bases,recovery_basis),false) OR array_length(bases)>1)) AS basis_differences,
            count(*) FILTER(WHERE receipt_rows IS NOT NULL AND
                (NOT coalesce(array_has(recovered_urls,recovered_url),false) OR array_length(recovered_urls)>1)) AS url_differences
            FROM decisions'''),
        dict(name='import_counts',sql=f'''SELECT count(*) FILTER(WHERE status='ready_for_owner_import') AS ready,
            count(*) FILTER(WHERE status<>'ready_for_owner_import') AS unresolved FROM ({missing_sql})''')]
    outputs=[
        parquet_output(output,'recovery-decisions',decision_sql,['id']),
        parquet_output(output,'missing-imports',missing_sql,['original_url','body_sha256']),
        parquet_output(output,'ready-imports',f"SELECT * FROM ({missing_sql}) WHERE status='ready_for_owner_import'",['original_url','body_sha256']),
        parquet_output(output,'receipt-only',receipt_only,['receipt_key','receipt_line','capture_index']),
        parquet_output(output,'unresolved-kinds','''SELECT original_url,body_hex,category,category_count,
            recovery_basis,display_kind,unknown_category FROM decisions
            WHERE display_kind IS NULL OR unknown_category OR category_count>1''',['original_url','body_hex']),
        parquet_output(output,'disagreements','''SELECT original_url,body_hex,category,recovery_basis,bases,
            recovered_url,recovered_urls FROM decisions WHERE receipt_rows IS NOT NULL AND
            (NOT coalesce(array_has(bases,recovery_basis),false) OR array_length(bases)>1 OR
             NOT coalesce(array_has(recovered_urls,recovered_url),false) OR array_length(recovered_urls)>1)''',['original_url','body_hex'])]
    reports=run_job(jobs,engine,inputs=inputs,steps=steps,outputs=outputs,queries=queries)
    check=reports['invariants'][0]
    if check['invalid'] or check['duplicate_registry'] or check['duplicate_accepted'] or check['invalid_accepted'] or check['decisions']!=check['accepted']:
        raise ValueError('Recovery reconciliation has unknown or ambiguous kinds; native evidence retained')
    key,count=stage_records(output,'recoveries',parquet_records(output/'recovery-decisions.parquet'),decided_at=decided_at)
    return finish_stage(output,kind='recoveries',provenance=key,records=count,
        inputs=dict(accepted=file_pin(accepted),captures=file_pin(captures),registry=file_pin(registry)),
        extra=dict(counts=reports['counts'][0],import_counts=reports['import_counts'][0],
            missing_imports='missing-imports.parquet',ready_imports='ready-imports.parquet',receipt_only='receipt-only.parquet',
            artifacts=[dict(path=Path(item['path']).name,**file_pin(item['path'])) for item in outputs]))



def main(argv=None):
    import argparse
    from datetime import datetime
    from uuid import uuid4
    from docspec_client.client import NativeDatasets
    from congress_api.retention.provenance import load_stage
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    stage=commands.add_parser('stage',help='Stage local native reconciliation; no live storage')
    stage.add_argument('--accepted',type=Path,required=True)
    capture=stage.add_mutually_exclusive_group(required=True)
    capture.add_argument('--captures',type=Path,help='Normalized capture facts')
    capture.add_argument('--legacy-counter',type=Path,help='Already validated native receipt stage')
    stage.add_argument('--kind-registry',type=Path,required=True)
    stage.add_argument('--stage',type=Path,required=True)
    stage.add_argument('--native-config',type=Path,required=True)
    stage.add_argument('--decided-at',required=True)
    stage.add_argument('--decided-by',default='accepted-mapping-reconciliation')
    apply=commands.add_parser('import',help='Inspect proposed imports; --apply is owner-gated')
    apply.add_argument('--stage',type=Path,required=True)
    apply.add_argument('--ready-only',action='store_true',help='Explicitly import only rows with established source times')
    apply.add_argument('--bucket',default='congressional-tech-raw')
    apply.add_argument('--apply',action='store_true')
    args=parser.parse_args(argv)
    if args.command=='stage':
        engine=NativeDatasets.from_config(args.native_config)
        captures=args.captures
        if args.legacy_counter:
            inputs=args.stage.with_name(args.stage.name+'-source-facts')
            inputs.mkdir(parents=True,exist_ok=False)
            captures=project_legacy(args.legacy_counter,output=inputs,engine=engine,accepted=args.accepted)
        result=reconcile(args.accepted,captures,args.kind_registry,output=args.stage,engine=engine,
                         decided_at=args.decided_at,decided_by=args.decided_by)
        print(json.dumps(result,indent=2));return
    root,value=load_stage(args.stage)
    if value['kind']!='recoveries' or 'missing_imports' not in value or 'ready_imports' not in value:
        raise ValueError('Import needs a recovery reconciliation stage')
    if value['import_counts']['unresolved'] and not args.ready_only:
        raise ValueError('Unresolved source times remain; inspect the report or explicitly select --ready-only')
    selected=value['ready_imports'] if args.ready_only else value['missing_imports']
    if selected not in {item['path'] for item in value.get('artifacts',[])}:
        raise ValueError('Import request artifact is not pinned by the stage')
    def source_row(row,at):
        key=row['body_key']
        from congress_api.retention.body_keys import body_key_digest
        if body_key_digest(key)!=row['body_sha256']:
            raise ValueError('Import request has a mismatched physical body key')
        if row['status']!='ready_for_owner_import':raise ValueError('Import request lacks original source evidence')
        return dict(row,retained_reference=True,imported_at=at)

    # Validate every pinned import request before connection. Existing bodies
    # are referenced by exact physical keys; no PDF/body bytes are reread.
    now=datetime.now(timezone.utc).isoformat()
    count=0
    for row in parquet_records(root/selected):source_row(row,now);count+=1
    result=dict(records=count,unresolved=value['import_counts']['unresolved'],apply=False)
    if args.apply:
        from congress_api.retention.writer_identity import writer_identity
        from congress_api.retention.body_store import BodyStore,R2Adapter
        from congress_api.retention.receipt_writer import ReceiptWriter
        identity=writer_identity(Path(__file__).resolve().parents[4],'recovery-import')
        from congress_shared.storage import connect_r2
        client=connect_r2(bucket=args.bucket,retries={'mode':'standard','max_attempts':5})
        writer=ReceiptWriter(BodyStore(R2Adapter(client,args.bucket)),identity=identity,
            run_id='recovery-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:12],
            write_date=datetime.now(timezone.utc).date().isoformat(),archive_limits=None)
        for row in parquet_records(root/selected):import_retained(writer,source_row(row,now))
        result.update(apply=True,writer=identity,run_id=writer.run_id)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
