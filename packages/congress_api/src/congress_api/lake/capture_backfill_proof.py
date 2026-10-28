"""One measured original-source sample proves one-shot/batched capture equivalence.

Sample selection is O(R log R), keeps the three independent cost extremes and
fills from cheap receipts. DocSpec owns public-row comparison and table work.
"""
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from congress_api.lake.captures import COLUMNS,current_version
from congress_api.lake.receipt_metadata import source_pins,recheck_source_pins
from congress_api.lake.tables import table_input
from congress_api.retention.provenance import file_pin,run_job


class EquivalenceMismatch(ValueError):
    def __init__(self,report):
        self.report=report
        super().__init__('One-shot and batched captures differ; see '+report['report_path'])


def select_sample(files,counts,*,byte_target,item_target,sample_size=200):
    """Include each extreme, then cheap original counter receipts deterministically."""
    from congress_api.lake.capture_backfill import make_plan
    if type(sample_size) is not int or sample_size<=0:
        raise ValueError('sample_size must be a positive integer')
    normalized=make_plan(files,counts,byte_target=byte_target,item_target=item_target)
    inventory={row['key']:dict(row) for row in files}
    metrics={row['key']:row for row in normalized['source_counts']}
    eligible=sorted(key for key,row in inventory.items()
                    if row.get('path') is None and row.get('prepared_stage') is None)
    if not eligible:raise ValueError('Equivalence needs original counter receipt sources')
    def weight(key):
        row=metrics[key]
        return max(row['uncompressed_bytes']*item_target,row['list_items']*byte_target)
    choices={name:max(eligible,key=lambda key:metrics[key][name])
             for name in ('max_line_bytes','max_line_items')}
    choices['weight']=max(eligible,key=weight)
    mandatory=set(choices.values())
    if sample_size<len(mandatory):
        raise ValueError('sample_size cannot omit a required source-cost extreme')
    order=sorted((key for key in eligible if key not in mandatory),
                 key=lambda key:(weight(key),metrics[key]['uncompressed_bytes'],metrics[key]['list_items'],key))
    selected=sorted(mandatory|set(order[:max(0,min(sample_size,len(eligible))-len(mandatory))]))
    return dict(files=[inventory[key] for key in selected],counts=[metrics[key] for key in selected],
        mandatory_keys=sorted(mandatory),extremes={name:dict(metrics[key],weight=weight(key))
            for name,key in choices.items()},
        excluded_non_counter_keys=sorted(set(inventory)-set(eligible)))


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


def proof_identity(*,engine,engine_config,validated_counter,source_qualifications):
    """Bind a proof to mapping/runtime and unchanged original counter authority."""
    if engine.remote is not None:
        raise ValueError('Rebuild equivalence qualification requires a local catalog runtime')
    if validated_counter is None:
        raise ValueError('Rebuild equivalence needs an original validated counter')
    from congress_api.lake.capture_backfill import runtime_identity
    config=Path(engine_config).resolve()
    runtime=runtime_identity(engine,engine_config)
    identity=dict(mapping_digest=current_version(),
        proof_definition=sha256(Path(__file__).read_bytes()).hexdigest(),
        engine=runtime,
        engine_config=dict(path=str(config),**file_pin(config)),
        sources=source_pins(counter=validated_counter,qualifications=source_qualifications))
    return json.loads(json.dumps(identity))


def prove_equivalence(files,counts,*,engine,engine_config,work,table,catalog_root,location,
                      byte_target,item_target,validated_counter,source_qualifications,
                      sample_size=200,scratch_root=None):
    """Build fresh local generations, compare them and retain only a truthful proof.

    Logical one-shot packing targets do not alter the runtime's physical limits.
    The whole-corpus receipt set is deliberately outside this once-per-original-
    counter proof: later separately qualified receipts do not invalidate it.
    """
    from congress_api.lake.capture_backfill import execute_batches
    if catalog_root is None:raise ValueError('Rebuild equivalence requires an explicit local catalog')
    identity=proof_identity(engine=engine,engine_config=engine_config,
        validated_counter=validated_counter,source_qualifications=source_qualifications)
    selected=select_sample(files,counts,byte_target=byte_target,item_target=item_target,sample_size=sample_size)
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
                validated_counter=validated_counter,source_qualifications=source_qualifications,
                scratch_root=scratch_root or work)
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
                validated_counter=validated_counter,source_qualifications=source_qualifications):
            raise ValueError('Rebuild equivalence source, mapping or runtime changed during qualification')
        report['status']='equivalent'
    except Exception as error:
        report.update(status='rejected',failure=dict(type=type(error).__name__,message=str(error)))
        (work/'proof.json').write_text(json.dumps(report,indent=2)+'\n')
        raise
    (work/'proof.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
