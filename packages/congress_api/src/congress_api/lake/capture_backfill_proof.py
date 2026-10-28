"""One measured original-source sample proves one-shot/batched capture equivalence.

Sample selection is O(R log R), keeps each family's largest line and
fills from cheap receipts. DocSpec owns public-row comparison and table work.
"""
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from congress_api.lake.captures import COLUMNS,current_version
from congress_api.lake.receipt_metadata import source_pins,recheck_source_pins,qualification_path
from congress_api.lake.tables import table_input
from congress_api.retention.provenance import file_pin,run_job


class EquivalenceMismatch(ValueError):
    def __init__(self,report):
        self.report=report
        super().__init__('One-shot and batched captures differ; see '+report['report_path'])


def select_sample(files,counts,*,byte_target,item_target,sample_size=200,
                  proof_bytes=2<<30,required_keys=()):
    """Keep family-largest lines and named shape cases, then cheap whole sources.

    The logical byte cap bounds the one-shot comparison's input, independently
    of runtime physical limits. A required receipt is never split or omitted.
    """
    from congress_api.lake.capture_backfill import make_plan
    for name,value in (('sample_size',sample_size),('proof_bytes',proof_bytes)):
        if type(value) is not int or value<=0:
            raise ValueError(name+' must be a positive integer')
    normalized=make_plan(files,counts,byte_target=byte_target,item_target=item_target)
    inventory={row['key']:dict(row) for row in files}
    if any(not row.get('path') or row.get('prepared_stage')
           or not row.get('qualification') for row in files):
        raise ValueError('Equivalence needs qualified original receipt file sources')
    metrics={row['key']:row for row in normalized['source_counts']}
    if (not isinstance(required_keys,(list,tuple))
            or any(not isinstance(key,str) for key in required_keys)
            or len(set(required_keys))!=len(required_keys) or set(required_keys)-set(inventory)):
        raise ValueError('Required proof keys must uniquely name inventory receipts')
    def weight(key):
        row=metrics[key]
        return max(row['uncompressed_bytes']*item_target,row['list_items']*byte_target)
    choices={}
    for family in ('house','senate','youtube'):
        candidates=[key for key in inventory if key.startswith('receipts/'+family+'/')]
        if candidates:
            choices[family]=min(candidates,key=lambda key:(-metrics[key]['max_line_bytes'],key))
    mandatory=set(choices.values())|set(required_keys)
    if sample_size<len(mandatory):
        raise ValueError('sample_size cannot omit required proof sources')
    total=sum(metrics[key]['uncompressed_bytes'] for key in mandatory)
    if total>proof_bytes:raise ValueError('Required proof receipts exceed the logical byte cap')
    selected=set(mandatory)
    order=sorted(set(inventory)-mandatory,key=lambda key:(weight(key),
        metrics[key]['uncompressed_bytes'],metrics[key]['list_items'],key))
    for key in order:
        if len(selected)>=sample_size:break
        cost=metrics[key]['uncompressed_bytes']
        if total+cost<=proof_bytes:selected.add(key);total+=cost
    selected=sorted(selected)
    return dict(files=[inventory[key] for key in selected],counts=[metrics[key] for key in selected],
        mandatory_keys=sorted(mandatory),required_keys=sorted(required_keys),
        family_largest_lines={name:dict(metrics[key]) for name,key in choices.items()},
        logical_bytes=total,proof_bytes=proof_bytes,sample_size=sample_size)


def _selected_qualifications(files,qualifications):
    bindings={str(Path(row['path']).resolve()):row['qualification'] for row in files
              if row.get('qualification')}
    paths={str(Path(row['path']).resolve()) for row in files}
    external={}
    for path,authority in (qualifications or {}).items():
        canonical=str(qualification_path(path).resolve())
        if canonical in external:raise ValueError("Duplicate source qualification binding")
        external[canonical]=authority
    bindings.update({path:authority for path,authority in external.items() if path in paths})
    return bindings


def _count(result,name):
    rows=result.get(name)
    if (not isinstance(rows,list) or len(rows)!=1 or set(rows[0])!={'n'}
            or type(rows[0]['n']) is not int or rows[0]['n']<0):
        raise ValueError('Malformed native equivalence count '+name)
    return rows[0]['n']


def compare_tables(left,right,*,engine,work):
    """Compare exact public values and counts, using immutable native table pins."""
    inputs=[table_input('one_shot',left),table_input('batched',right)]
    work=Path(work).resolve();work.mkdir(parents=True,exist_ok=False)
    columns=','.join('"'+name+'"' for name in COLUMNS)
    queries=[dict(name='left_rows',sql='SELECT count(*) AS n FROM one_shot'),
             dict(name='right_rows',sql='SELECT count(*) AS n FROM batched')]
    for name,a,b in [('left_only','one_shot','batched'),('right_only','batched','one_shot')]:
        queries.append(dict(name=name,sql=f'SELECT count(*) AS n FROM (SELECT {columns} FROM {a} EXCEPT SELECT {columns} FROM {b})'))
    result=run_job(work,engine,inputs=inputs,steps=[],outputs=[],queries=queries)
    report=dict(status='rejected',columns=list(COLUMNS),report_path=str(work/'comparison.json'),
                **{query['name']:_count(result,query['name']) for query in queries},
                job=file_pin(work/'job.json'),result=file_pin(work/'result.json'))
    if (report['left_rows']==report['right_rows'] and report['left_only']==report['right_only']==0):
        report['status']='equivalent'
    (work/'comparison.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['status']!='equivalent':raise EquivalenceMismatch(report)
    return report


def proof_identity(*,engine,engine_config,files,source_qualifications=None):
    """Bind selected receipt keys and original source authorities to the runtime."""
    if engine.remote is not None:
        raise ValueError('Rebuild equivalence qualification requires a local catalog runtime')
    from congress_api.lake.capture_backfill import runtime_identity
    config=Path(engine_config).resolve()
    runtime=runtime_identity(engine,engine_config)
    identity=dict(mapping_digest=current_version(),
        proof_definition=sha256(Path(__file__).read_bytes()).hexdigest(),
        engine=runtime,
        engine_config=dict(path=str(config),**file_pin(config)),
        receipt_sources=sorted([dict(key=row['key'],path=str(Path(row['path']).resolve())) for row in files],key=lambda row:row['key']),
        sources=source_pins(files=files,qualifications=_selected_qualifications(files,source_qualifications)))
    return json.loads(json.dumps(identity))


def prove_equivalence(files,counts,*,engine,engine_config,work,table,catalog_root,location,
                      byte_target,item_target,source_qualifications=None,
                      sample_size=200,proof_bytes=2<<30,required_keys=(),scratch_root=None,progress_log=None):
    """Build fresh local generations, compare them and retain only a truthful proof.

    Logical one-shot packing targets do not alter the runtime's physical limits.
    Only selected original receipts enter either generation; the whole-corpus
    final guard and receipt counts remain separate acceptance requirements.
    """
    from congress_api.lake.capture_backfill import execute_batches
    if catalog_root is None:raise ValueError('Rebuild equivalence requires an explicit local catalog')
    selected=select_sample(files,counts,byte_target=byte_target,item_target=item_target,
        sample_size=sample_size,proof_bytes=proof_bytes,required_keys=required_keys)
    qualifications=_selected_qualifications(selected['files'],source_qualifications)
    identity=proof_identity(engine=engine,engine_config=engine_config,
        files=selected['files'],source_qualifications=qualifications)
    work=Path(work).resolve();work.mkdir(parents=True,exist_ok=False)
    generation='eq_'+uuid4().hex[:12]
    report=dict(status='running_unaccepted',identity=identity,sample=selected,
        byte_target=byte_target,item_target=item_target,generation=generation,
        qualified_for_downstream=False,report_path=str(work/'proof.json'))
    (work/'sample.json').write_text(json.dumps(selected,indent=2)+'\n')
    try:
        results={}
        for index,(name,byte_cost,item_cost) in enumerate([
                ('one_shot',sum(r['uncompressed_bytes'] for r in selected['counts'])+1,
                 sum(r['list_items'] for r in selected['counts'])+1),
                ('batched',byte_target,item_target)]):
            namespace=list(table['namespace'])
            namespace[-1]+='_proof_'+generation
            target=dict(namespace=namespace,name=table['name']+'_'+generation+'_'+name)
            target_location=Path(location).resolve().with_name(Path(location).name+'_'+generation+'_'+name)
            value=execute_batches(selected['files'],selected['counts'],engine=engine,engine_config=engine_config,
                work=work/name,table=target,catalog_root=catalog_root,location=target_location,
                create_table=True,create_namespace=index==0,byte_target=byte_cost,item_target=item_cost,
                source_qualifications=qualifications,
                scratch_root=scratch_root or work.parent,progress_log=progress_log,
                progress_step='equivalence_'+name)
            if value.get('status')!='public_guard_passed' or value.get('mapping_digest')!=identity['mapping_digest'] or value.get('engine')!=identity['engine']:
                raise ValueError('Equivalence producer did not return guarded rows from the pinned definition/runtime')
            if name=='one_shot' and len(value['batches'])!=1:
                raise ValueError('Original-source one-shot proof unexpectedly split receipts')
            results[name]=value
        report['generations']=results
        report['comparison']=compare_tables(results['one_shot']['pin'],results['batched']['pin'],
            engine=engine,work=work/'comparison')
        recheck_source_pins(identity['sources'])
        if identity!=proof_identity(engine=engine,engine_config=engine_config,
                files=selected['files'],source_qualifications=qualifications):
            raise ValueError('Rebuild equivalence source, mapping or runtime changed during qualification')
        report['status']='equivalent'
    except Exception as error:
        report.update(status='rejected',failure=dict(type=type(error).__name__,message=str(error)))
        (work/'proof.json').write_text(json.dumps(report,indent=2)+'\n')
        raise
    (work/'proof.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
