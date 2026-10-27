"""Reusable native source/recovery facts from the retained legacy receipt stage."""
from pathlib import Path
import json
import pyarrow as pa
import pyarrow.parquet as pq
from congress_api.retention.provenance import json_input,parquet_output,run_job


def project_legacy(counter,*,output,engine,accepted=None):
    """Project only recovery/source facts from an existing native receipt stage.

    This is a transition input adapter for reconciliation, not a second lake
    ingest or receipt parser. The native counter retains the receipt positions.
    """
    counter,output=Path(counter),Path(output)
    schema=pq.read_schema(counter)
    if not {'__receipt_key','__receipt_line'}.issubset(schema.names):
        raise ValueError('Legacy projection requires the native receipt counter positions')
    def path_type(parts):
        node=schema
        for part in parts:
            try:node=node.field(part).type
            except (KeyError,AttributeError):return None
        return node
    def raw(*parts):
        return '.'.join('"'+p+'"' for p in parts) if path_type(parts) is not None else 'cast(NULL AS VARCHAR)'
    cap_types=[]
    for name in ('captures','file_references'):
        dtype=path_type((name,))
        if dtype is not None and pa.types.is_list(dtype) and pa.types.is_struct(dtype.value_type):
            cap_types.append(dtype.value_type)
    def cap(name):
        return 'cap."'+name+'"' if any(name in typ.names for typ in cap_types) else 'cast(NULL AS VARCHAR)'
    def assoc(name):
        dtype=path_type(('record','source_associations'))
        if dtype is not None and pa.types.is_list(dtype) and pa.types.is_struct(dtype.value_type) and name in dtype.value_type.names:
            return f"get_field(array_element({raw('record','source_associations')},1),'{name}')"
        return 'cast(NULL AS VARCHAR)'
    has_caps=path_type(('captures',)) is not None
    has_refs=path_type(('file_references',)) is not None
    if not has_caps and not has_refs:raise ValueError('Receipt counter has no capture lists')
    caps=('CASE WHEN coalesce(array_length(captures),0)>0 THEN captures ELSE file_references END'
          if has_caps and has_refs else 'captures' if has_caps else 'file_references')
    original=f"coalesce({raw('record','recovery_evidence','original_url')},{assoc('original_url')})"
    basis=f"coalesce({raw('record','recovery_evidence','match_basis')},{assoc('basis')})"
    mode=f"coalesce({raw('mode')},{raw('record','mode')})"
    # Select nested fields before UNNEST; no raw JSON strings or body values
    # enter this job, and an absent original timestamp stays null.
    steps=[dict(name='receipt_facts',sql=f'''SELECT __receipt_key,__receipt_line,{caps} AS caps,
        {original} AS original_url,{basis} AS match_basis,{mode} AS old_mode,
        {raw('record','recovery_evidence','acquisition','prior_access_category')} AS recovery_category,
        {raw('record','recovery_evidence','acquisition','body_path')} AS retained_filename,
        coalesce({raw('record','recovery_evidence','acquisition','recovered_url')},
                 {raw('record','url')},{raw('url')}) AS recovered_url,
        {raw('record','url')} AS record_url,{raw('url')} AS root_url,
        {raw('record','requested_url')} AS record_requested,{raw('requested_url')} AS root_requested,
        {raw('retrieved_at')} AS root_retrieved,{raw('record','retrieved_at')} AS record_retrieved,
        {raw('captured_at')} AS root_captured,{raw('record','captured_at')} AS record_captured,
        {raw('observed_at')} AS root_observed,{raw('record','observed_at')} AS record_observed FROM raw_counter'''),
        dict(name='expanded',sql='''SELECT *,unnest(caps) AS cap,
            unnest(range(0,cast(coalesce(array_length(caps),0) AS BIGINT))) AS capture_index FROM receipt_facts''')]
    retrieve_cols=[cap(name) for name in ('retrieved_at','captured_at','observed_at')]+[
        'root_retrieved','record_retrieved','root_captured','record_captured','root_observed','record_observed']
    jobs=output/'projection-job';jobs.mkdir(parents=True,exist_ok=False)
    inputs=[dict(name='raw_counter',kind='parquet',path=str(counter.resolve()))]
    sql=f'''SELECT {cap('sha256')} AS sha256,
        CASE WHEN old_mode='retained_import' OR original_url IS NOT NULL THEN 'retained_import' ELSE 'fetch' END AS mode,
        original_url,recovered_url,match_basis,recovery_category,
        coalesce({cap('context_url')},record_url,root_url,record_requested,root_requested) AS url,
        coalesce({','.join(retrieve_cols)}) AS retrieved_at,
        __receipt_key AS receipt_key,__receipt_line AS receipt_line,capture_index,
        cast({cap('bytes')} AS BIGINT) AS bytes,{cap('media_type')} AS media_type,
        CASE WHEN coalesce(length({cap('original_path')}),0)=0 THEN retained_filename ELSE cast(NULL AS VARCHAR) END AS recovered_filename,
        {cap('sniffed_format')} AS sniffed_format,{cap('sniff_version')} AS sniff_version,
        cast({cap('intact')} AS BOOLEAN) AS intact,coalesce({cap('stored_suffix')},'.gz') AS stored_suffix FROM expanded
        WHERE {cap('sha256')} IS NOT NULL'''
    if accepted is not None:
        mappings=json.loads(Path(accepted).read_text())
        if mappings.get('version')!=1:raise ValueError('Unsupported accepted recovery version')
        inputs.append(json_input(jobs,'accepted_bodies',mappings['recoveries'],body_key='Utf8'))
        # A named, materialized flat relation gives the native join one stable
        # schema rather than re-extracting nested UNNEST fields on both sides.
        steps.append(dict(name='body_facts',sql=sql,materialize=True))
        steps.append(dict(name='selected_bodies',sql="SELECT DISTINCT substr(body_key,18,64) AS selected_sha FROM accepted_bodies"))
        sql='''SELECT f.* FROM body_facts f LEFT JOIN selected_bodies s ON f.sha256=s.selected_sha
            WHERE f.mode='retained_import' OR s.selected_sha IS NOT NULL'''
    run_job(jobs,engine,inputs=inputs,
        steps=steps,outputs=[parquet_output(output,'capture-facts',sql,['receipt_key','receipt_line','capture_index'])])
    return output/'capture-facts.parquet'
