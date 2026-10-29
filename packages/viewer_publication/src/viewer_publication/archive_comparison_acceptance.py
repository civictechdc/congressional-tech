"""Accept exact owner-disposed comparison groups without changing diagnostics.

The caller supplies the owner record's trusted byte pin. This module validates
coverage and custody; it does not determine who is authorized to decide.
"""
import copy
import json
from pathlib import Path
import re

from congress_api.retention.provenance import file_pin,json_input,run_job
from congress_api.retention.derived_files import copy_checked
from congress_shared.custody import verify_local_file,write_atomic_json
from viewer_publication.archive_model_job import _pin,_selector

FIELDS=('context_url','bytes','stored_bytes','media_type','fidelity','http_status','family','run_id','member_path','body_key','retrieved_at')
LABELS=('changed_fields','old_family','new_family','old_fidelity','new_fidelity','old_reference_kind','new_reference_kind','retrieved_at_reason','http_change_kind')
DECISIONS={'accept_new','blocked'}
KNOWN_HTTP_DEFECT='known_defect_mapping_52120d49_http_alias'
KNOWN_INLINE_DEFECT='known_defect_mapping_52120d49_inline_payload_outcome'
MAPPING_52120D49='52120d49aa771c10105d87af6440b3d2a0b0c297aca08a0dac1c654205464d4b'
HTTP_CHANGE_KINDS={'unchanged','null_to_value','value_to_null','value_changed'}
CLASSIFICATIONS={'old_pipeline_error','rule_change','accepted_derived_fact_loss',KNOWN_HTTP_DEFECT,KNOWN_INLINE_DEFECT}
OWNER_FIELDS={'version','mapping_digest','capture_pin','comparison_report','comparison_terminal','changed_fields','groups'}
GROUP_FIELDS={'id',*LABELS,'count','decision','classification','reason','evidence'}


def _require(value,message):
    if not value:raise ValueError(message)


def _verified(pin):
    _pin(pin,{'path','sha256','size'})
    path=Path(pin['path'])
    _require(path.is_absolute() and str(path.resolve())==pin['path'],'Pin needs an absolute canonical local path')
    return verify_local_file(path,expected_sha256=pin['sha256'],expected_size=pin['size'])


def _pinned(path):
    path=Path(path).resolve()
    verified=verify_local_file(path)
    return dict(path=str(path),sha256=verified.sha256,size=verified.size_bytes),verified


def _json(pin,held):
    _require(pin['size']<=8<<20,'Comparison policy JSON exceeds 8 MiB')
    verified=_verified(pin);held.append(verified)
    value=json.loads(Path(pin['path']).read_text())
    verified.require(pin['path'])
    return value


def _signature(value):
    parts=(value.split(',') if value else []) if isinstance(value,str) else value
    _require(isinstance(parts,list) and all(isinstance(x,str) and x in FIELDS for x in parts),'Invalid changed_fields signature')
    _require(parts==[x for x in FIELDS if x in parts],'changed_fields must follow the fixed field order exactly once')
    return ','.join(parts)


def validate_owner_record(value,*,mapping_digest,capture_pin,comparison_report,comparison_terminal,changed_fields,unexplained):
    """Validate explicit policy records and pins; never match capture data in Python."""
    _require(isinstance(value,dict) and set(value)==OWNER_FIELDS,'Incomplete owner record')
    _require(type(value['version']) is int and value['version']==1,'Owner record requires version 1')
    expected=dict(mapping_digest=mapping_digest,capture_pin=capture_pin,comparison_report=comparison_report,
        comparison_terminal=comparison_terminal,changed_fields=changed_fields)
    _require(all(value[k]==v for k,v in expected.items()),'Owner record comparison binding differs')
    result=copy.deepcopy(value);groups=result['groups']
    _require(isinstance(groups,list) and bool(groups),'Owner record needs explicit groups')
    ids=set();keys=set();total=0;evidence_pins={}
    for group in groups:
        _require(isinstance(group,dict) and set(group)==GROUP_FIELDS,'Each owner group needs every explicit match field')
        for name in ('id','reason'):
            _require(isinstance(group[name],str) and bool(group[name].strip()),'Owner group needs '+name)
        _require(group['id'] not in ids,'Duplicate owner group id');ids.add(group['id'])
        group['changed_fields']=_signature(group['changed_fields'])
        for name in LABELS[1:]:
            _require(group[name] is None or isinstance(group[name],str),'Owner match fields must be text or explicit null')
        _require(group['http_change_kind'] in HTTP_CHANGE_KINDS,'Invalid HTTP change kind')
        key=tuple(group[name] for name in LABELS)
        _require(key not in keys,'Overlapping owner group predicates');keys.add(key)
        _require(type(group['count']) is int and group['count']>0,'Owner group count must be a positive integer')
        total+=group['count']
        _require(isinstance(group['decision'],str) and group['decision'] in DECISIONS,'Invalid owner decision')
        _require(group['decision']=='accept_new','Owner group remains blocked')
        _require(isinstance(group['classification'],str) and group['classification'] in CLASSIFICATIONS,'Invalid owner classification')
        if group['classification'] in (KNOWN_HTTP_DEFECT,KNOWN_INLINE_DEFECT):
            _require(mapping_digest==MAPPING_52120D49,'Known defect tag requires mapping 52120d49')
        if group['classification']==KNOWN_HTTP_DEFECT:
            _require(group['http_change_kind']=='value_to_null','HTTP alias defect tag requires value_to_null')
        _require(isinstance(group['evidence'],list) and bool(group['evidence']),'Owner group needs pinned evidence')
        for pin in group['evidence']:
            _pin(pin,{'path','sha256','size'})
            key=(pin['path'],pin['sha256'],pin['size']);evidence_pins[key]=pin
    _require(total==unexplained,'Owner counts do not reconcile with unexplained total')
    for pin in evidence_pins.values():_verified(pin)
    return result


def coverage_steps():
    """One native aggregate, then exact null-safe matching against owner groups."""
    signature="concat_ws(',',"+','.join("CASE WHEN old_"+n+" IS DISTINCT FROM new_"+n+" THEN '"+n+"' END" for n in FIELDS)+')'
    labels=','.join(LABELS)
    return [dict(name='diagnostics',sql='SELECT '+','.join(LABELS[1:-1])+','+signature+" AS changed_fields, CASE WHEN old_http_status IS NOT DISTINCT FROM new_http_status THEN 'unchanged' WHEN old_http_status IS NULL THEN 'null_to_value' WHEN new_http_status IS NULL THEN 'value_to_null' ELSE 'value_changed' END AS http_change_kind FROM changes WHERE unexplained IS TRUE"),
        dict(name='actual_groups',sql='SELECT '+labels+',count(*) AS n FROM diagnostics GROUP BY '+labels,materialize=True),
        dict(name='coverage',sql='SELECT a.n,o.expected_count,o.id FROM actual_groups a FULL OUTER JOIN owner_groups o ON '+
            ' AND '.join('(a.'+name+' IS NOT DISTINCT FROM o.'+name+')' for name in LABELS),materialize=True)]


COVERAGE_SQL="""SELECT
    (SELECT count(*) FROM actual_groups) AS actual_groups,
    (SELECT count(*) FROM owner_groups) AS owner_groups,
    (SELECT coalesce(sum(n),0) FROM actual_groups) AS unexplained,
    (SELECT count(*) FROM coverage WHERE n IS NULL OR id IS NULL OR n<>expected_count) AS mismatches"""


def validate_coverage(counts,*,unexplained,owner_groups=None):
    fields={'actual_groups','owner_groups','unexplained','mismatches'}
    _require(isinstance(counts,dict) and set(counts)==fields and all(type(v) is int and v>=0 for v in counts.values()),'Malformed native coverage counts')
    _require(counts['mismatches']==0 and counts['actual_groups']==counts['owner_groups'] and counts['unexplained']==unexplained,
        'Native owner group coverage differs')
    if owner_groups is not None:_require(counts['owner_groups']==owner_groups,'Native owner group population differs')
    return counts


def _inputs(report_path,expected_mapping_digest,capture_pin,owner_record):
    _require(isinstance(expected_mapping_digest,str) and re.fullmatch('[a-f0-9]{64}',expected_mapping_digest),'Invalid expected mapping digest')
    _selector(dict(kind='native_table',**capture_pin),base=Path.cwd())
    held=[];report_pin,verified=_pinned(report_path);held.append(verified)
    report=_json(report_pin,held)
    _require(report.get('mapping_digest')==expected_mapping_digest and report.get('capture_pin')==capture_pin,'Comparison mapping or capture pin differs')
    counts=report.get('counts',{})
    for name in ('old_only','unexplained_new_only','unexplained'):
        _require(type(counts.get(name)) is int and counts[name]>=0,'Comparison needs explicit nonnegative counts')
    _require(type(counts.get('owner_gate')) is bool,'Comparison needs an explicit owner gate')
    _require(counts['owner_gate']==bool(counts['old_only'] or counts['unexplained_new_only'] or counts['unexplained']),'Comparison owner gate contradicts counts')
    _require(counts['old_only']==0 and counts['unexplained_new_only']==0,'Old-only or unexplained new-only cannot be disposed by this API')
    status='compared_owner_gate' if counts['owner_gate'] else 'compared'
    _require(report.get('status')==status,'Comparison is not completed')
    terminal_pin,verified=_pinned(Path(report_pin['path']).parent/'comparison-status.json');held.append(verified)
    terminal=_json(terminal_pin,held)
    _require(terminal.get('status')==status and terminal.get('report')==report_pin['path'] and
        terminal.get('measurement',{}).get('returncode')==0 and terminal['measurement'].get('failure') is None,'Comparison terminal receipt differs or failed')
    outputs=[v for v in report.get('outputs',[]) if v.get('name')=='changed-fields']
    _require(len(outputs)==1,'Comparison needs one changed-fields output pin')
    changed=dict(path=report.get('changed_fields'),**{k:outputs[0][k] for k in ('sha256','size')})
    held.append(_verified(changed))
    selected=dict(comparison_report=report_pin,comparison_terminal=terminal_pin,changed_fields=changed,owner_record=owner_record)
    owner=None
    if counts['owner_gate']:
        _require(owner_record is not None,'Owner-disposed comparison requires a pinned owner record')
        value=_json(owner_record,held)
        owner=validate_owner_record(value,mapping_digest=expected_mapping_digest,capture_pin=capture_pin,
            comparison_report=report_pin,comparison_terminal=terminal_pin,changed_fields=changed,unexplained=counts['unexplained'])
        evidence={tuple(pin[k] for k in ('path','sha256','size')):pin for group in owner['groups'] for pin in group['evidence']}
        for pin in evidence.values():held.append(_verified(pin))
    else:_require(owner_record is None,'A comparison without owner gate takes no owner override')
    for verified in held:verified.require(verified.path)
    return report,selected,owner,held


def accept_comparison(report_path,*,expected_mapping_digest,capture_pin,work,engine,owner_record=None):
    """Write a separate receipt after complete native coverage and input checks."""
    report,selected,owner,held=_inputs(report_path,expected_mapping_digest,capture_pin,owner_record)
    work=Path(work).resolve()
    _require(not work.exists(),'Comparison acceptance work must be fresh')
    if owner is not None:_require(engine is not None,'Owner coverage requires a native engine')
    for verified in held:verified.require(verified.path)
    work.mkdir(parents=True)
    native_job=native_result=owner_groups_input=retained_changes=None
    if owner is not None:
        changed=selected['changed_fields'];source=next(v for v in held if str(v.path)==changed['path'])
        # A retained hard link changes another reader's source ctime/link count.
        # The maintained checked-copy helper keeps shared comparison data read-only.
        with Path(changed['path']).open('rb') as stream:
            retained=copy_checked(stream,work/'changed-fields.parquet',size=changed['size'],expected=source,key='comparison changed-fields')
        retained_changes=dict(changed,path=str(retained.path))
        owner_input=json_input(work,'owner_groups',({**{k:g[k] for k in LABELS},'id':g['id'],'expected_count':g['count']} for g in owner['groups']),
            **{k:'Utf8' for k in (*LABELS,'id')},expected_count='Int64')
        owner_groups_input,verified=_pinned(owner_input['files'][0]['path']);held.append(verified)
        for verified in held:verified.require(verified.path)
        result=run_job(work/'native',engine,inputs=[dict(name='changes',kind='parquet',path=str(retained.path)),owner_input],
            steps=coverage_steps(),outputs=[],queries=[dict(name='coverage_counts',sql=COVERAGE_SQL)])
        retained.require(retained.path)
        rows=result.get('coverage_counts');_require(isinstance(rows,list) and len(rows)==1,'Native coverage query result is absent')
        counts=validate_coverage(rows[0],unexplained=report['counts']['unexplained'],owner_groups=len(owner['groups']))
        native_job,_=_pinned(work/'native/job.json');native_result,_=_pinned(work/'native/result.json')
    else:counts=dict(actual_groups=0,owner_groups=0,unexplained=0,mismatches=0)
    for verified in held:verified.require(verified.path)
    receipt=dict(version=1,status='accepted_with_owner_dispositions' if owner else 'accepted_without_owner_dispositions',
        mapping_digest=expected_mapping_digest,capture_pin=capture_pin,**selected,counts=counts,native_job=native_job,native_result=native_result,owner_groups_input=owner_groups_input,retained_changes=retained_changes)
    write_atomic_json(work/'acceptance.json',receipt,fsync=True,fsync_dir=True)
    return receipt


def validate_receipt(receipt_pin,*,expected_mapping_digest,capture_pin):
    """Recheck a caller-pinned acceptance receipt and every original evidence pin."""
    held=[];receipt=_json(receipt_pin,held)
    fields={'version','status','mapping_digest','capture_pin','comparison_report','comparison_terminal','changed_fields','owner_record','counts','native_job','native_result','owner_groups_input','retained_changes'}
    _require(isinstance(receipt,dict) and set(receipt)==fields and type(receipt['version']) is int and receipt['version']==1,'Malformed comparison acceptance receipt')
    _require(receipt['mapping_digest']==expected_mapping_digest and receipt['capture_pin']==capture_pin,'Acceptance receipt mapping or capture differs')
    report,selected,owner,inputs=_inputs(receipt['comparison_report']['path'],expected_mapping_digest,capture_pin,receipt['owner_record']);held+=inputs
    _require(all(receipt[k]==v for k,v in selected.items()),'Acceptance receipt input pins differ')
    expected_status='accepted_with_owner_dispositions' if owner else 'accepted_without_owner_dispositions'
    _require(receipt['status']==expected_status,'Acceptance receipt status differs')
    validate_coverage(receipt['counts'],unexplained=report['counts']['unexplained'],owner_groups=len(owner['groups']) if owner else 0)
    if owner:
        held.append(_verified(receipt['native_job']))
        held.append(_verified(receipt['owner_groups_input']))
        held.append(_verified(receipt['retained_changes']))
        _require(all(receipt['retained_changes'][k]==selected['changed_fields'][k] for k in ('sha256','size')),'Retained native comparison input differs')
        native=_json(receipt['native_result'],held)
        queries=[q for q in native.get('queries',[]) if q.get('name')=='coverage_counts']
        _require(len(queries)==1 and queries[0].get('data')==[receipt['counts']],'Acceptance native result differs')
    else:_require(all(receipt[k] is None for k in ('native_job','native_result','owner_groups_input','retained_changes')),'Unexpected native receipt for ungated comparison')
    for verified in held:verified.require(verified.path)
    return receipt
