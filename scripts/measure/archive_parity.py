"""Read-only E4 comparison. Policy witnesses explain individual differences.

The catalog pair is the oracle. Candidate fields come from the release; source
membership and ID inputs come from pinned, nonpublished model relations.
"""
import argparse
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import re
import sys

from congress_api.retention.provenance import parquet_output, run_job
from docspec_client.client import NativeDatasets

ROOT = Path(__file__).parents[2]
ORACLE_CATALOG = '469ef1ebf6864739a2c8a4c096defcc0'
ORACLE_GENERATION = '596f08fa2dbf4875bb8da7dc94e33847'
MEMBER_COLUMNS = {'document_id','list_row','source_id','body_key','effective_filename','source_url','member_path'}


def pinned_file(base, pin):
    if not isinstance(pin,dict) or not isinstance(pin.get('path'),str):
        raise ValueError('Missing file pin')
    path=(base/pin['path']).resolve()
    if not path.is_file():
        raise ValueError('Missing pinned file: '+str(path))
    if not isinstance(pin.get('sha256'),str) or not re.fullmatch('[a-f0-9]{64}',pin['sha256']):
        raise ValueError('Missing SHA-256 file pin: '+str(path))
    if path.stat().st_size!=pin.get('size'):
        raise ValueError('Pinned file size differs: '+str(path))
    with path.open('rb') as stream:
        if file_digest(stream,'sha256').hexdigest()!=pin['sha256']:
            raise ValueError('Pinned file digest differs: '+str(path))
    return path


def load_descriptor(path):
    """Verify selectors and bytes before registering any native relation."""
    import pyarrow.parquet as pq
    path=Path(path).resolve()
    value=json.loads(path.read_text())
    if value.get('version')!=1:
        raise ValueError('Missing version-1 parity descriptor')
    base=path.parent
    oracle=value.get('oracle',{})
    selector_path=pinned_file(base,oracle.get('selector'))
    selector=json.loads(selector_path.read_text())
    if selector.get('catalog_id')!=ORACLE_CATALOG or selector.get('generation')!=ORACLE_GENERATION:
        raise ValueError('The oracle must be the agreed pinned catalog pair, never F0')
    paths={}
    for name in ['documents','filenames']:
        source=pinned_file(base,oracle.get(name))
        expected=selector['files'][name]
        if oracle[name]['sha256']!=expected['sha256'] or oracle[name]['size']!=expected['bytes']:
            raise ValueError('Oracle pair differs from its selector: '+name)
        if pq.ParquetFile(source).metadata.num_rows!=expected['rows']:
            raise ValueError('Oracle rows differ: '+name)
        paths['oracle_'+name]=str(source)
        receipt_path=pinned_file(base,oracle.get(name+'_receipt'))
        receipt=json.loads(receipt_path.read_text())
        if receipt.get('key')!=expected['key'] or receipt.get('identity',{}).get('sha256')!=expected['sha256']:
            raise ValueError('Oracle receipt differs: '+name)
    candidate=value.get('candidate',{})
    if candidate.get('kind') not in {'model','f0'} or not isinstance(candidate.get('release'),str):
        raise ValueError('Missing candidate kind or immutable release location')
    release=(base/candidate['release']).resolve()
    manifest_path=release/'manifest.json'
    if not manifest_path.is_file():
        raise ValueError('Missing candidate manifest')
    if sha256(manifest_path.read_bytes()).hexdigest()!=candidate.get('manifest_sha256'):
        raise ValueError('Candidate manifest digest differs')
    manifest=json.loads(manifest_path.read_text())
    if candidate['kind']=='f0' and (manifest.get('origin',{}).get('kind')!='converted_catalog'
            or manifest['origin'].get('catalog_id')!=ORACLE_GENERATION):
        raise ValueError('F0 candidate lacks the pinned converter origin')
    if candidate['kind']=='model' and manifest.get('origin',{}).get('kind')=='converted_catalog':
        raise ValueError('F0 cannot claim model qualification')
    names=set()
    for item in manifest['files']:
        name=item['name']
        if Path(name).name!=name or name in names:
            raise ValueError('Invalid or duplicate release filename')
        names.add(name)
        source=pinned_file(release,dict(path=name,sha256=item['sha256'],size=item['size']))
        if name.endswith('.parquet') and pq.ParquetFile(source).metadata.num_rows!=item['rows']:
            raise ValueError('Candidate file rows differ: '+name)
        if name.endswith('.parquet'):
            paths['release_'+name.removesuffix('.parquet')]=str(source)
    required={'list.parquet','detail.parquet','links.parquet','urls.parquet','sources.parquet','recoveries.parquet'}
    if not required<=names:
        raise ValueError('Missing required public candidate files')
    identity=[manifest['schema_version'],[[f['name'],f['sha256'],f['size'],f['rows']] for f in manifest['files']]]
    if sha256(json.dumps(identity,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()!=manifest['release_id']:
        raise ValueError('Candidate release identity differs')
    members=pinned_file(base,candidate.get('source_members'))
    if set(pq.read_schema(members).names)!=MEMBER_COLUMNS:
        raise ValueError('Source-member sidecar must have the agreed seven columns')
    paths['source_members']=str(members)
    for name,pin in value.get('cause_relations',{}).items():
        source=pinned_file(base,pin)
        if not set(pin.get('required_columns',[]))<=set(pq.read_schema(source).names):
            raise ValueError('Cause relation lacks its declared columns: '+name)
        if not re.fullmatch('[a-z_]+',name):
            raise ValueError('Invalid canonical relation name')
        paths[name]=str(source)
    provenance=value.get('provenance',{})
    paths['owner_decisions']=str(pinned_file(base,provenance.get('owner_decisions')))
    b7=pinned_file(base,provenance.get('b7_manifest'))
    b7_manifest=json.loads(b7.read_text())
    for pin in b7_manifest['provenance']:
        pinned_file(b7.parent,pin)
    for pin in b7_manifest['artifacts']:
        if pin['path'] in {'owner-records.parquet','ready-imports.parquet','source-time-minima.parquet','recovery-decisions.parquet'}:
            source=pinned_file(b7.parent,pin)
            paths['b7_'+Path(pin['path']).stem.replace('-','_')]=str(source)
    return dict(descriptor=value,paths=paths,manifest=manifest,selector=selector,
        descriptor_sha256=sha256(path.read_bytes()).hexdigest())


def _text(key):
    return "json_get_str(fact,'" + key + "')"


def _bool(key):
    return "json_get_bool(fact,'" + key + "')"


def _int(key):
    return "json_get_int(fact,'" + key + "')"


# These are explanations of observed changes, not admission/grouping rules.
# Every branch has an explicit field scope and direction. A receipt/reading or
# canonical model witness is required; a changed document alone proves nothing.
CAUSES = {
    'non_document_roles': (['document','body_keys','files'], 'removed',
        f"{_text('record_role')} IN ('caption','source_record','playlist','api','envelope')"),
    'listing_pages': (['document','body_keys','files'], 'removed', f"{_text('record_role')}='listing'"),
    'soft_error_wrapper_senate': (['body_keys','files'], 'removed',
        f"{_text('record_role')} IN ('error_response','wrapper') AND {_text('format')}='html'"),
    'real_web_untyped': (['body_keys','files'], 'added',
        f"{_text('record_role')}='document' AND {_bool('is_real_file')} AND ({_text('format')}='html' OR {_text('format')} IS NULL)"),
    'incomplete_damaged_failed_feed': (['body_keys','files'], 'removed',
        f"({_bool('complete')}=false OR {_text('record_role')}='damaged' OR {_text('reading_status')} IN ('failed','missing') OR {_text('xml_kind')}='feed')"),
    'recovery_independent_fetch': (['body_keys','files'], 'added',
        f"{_text('mode')}='fetch' AND {_bool('complete')} AND {_int('http_status')} BETWEEN 200 AND 299 AND {_text('outcome')} IN ('stored','unchanged') AND {_text('recovery_original_url')} IS NOT NULL"),
    'direct_provider_same_text': (['body_keys','files'], 'added',
        f"{_text('fingerprint')} IS NOT NULL AND {_text('fingerprint')}={_text('other_fingerprint')} AND {_text('receipt_key')}={_text('other_receipt_key')} AND {_int('receipt_line')}={_int('other_receipt_line')} AND {_int('attempt')}<>{_int('other_attempt')}"),
    'eot_webharvest_attachment': (['recoveries'], 'added',
        f"regexp_like({_text('original_url')},'^https?://([^/]+[.])?veterans[.]house[.]gov/') AND regexp_like({_text('recovered_url')},'^https?://([^/]+[.])?webharvest[.]gov/')"),
    'publisher_link_kind': (['document_kind'], 'added',
        f"{_int('filename_kind_count')}=0 AND {_text('publisher_kind')}=value AND {_text('link_basis')}='saved_page'"),
    'capture_header_names': (['filename','files'], 'added',
        f"{_text('name_basis')}='content_disposition' AND {_text('header_filename')}=value"),
    'saved_text_exact_twins': (['body_keys','files','saved_body'], 'removed',
        f"{_text('fingerprint')} IS NOT NULL AND {_text('fingerprint')}={_text('other_fingerprint')} AND {_text('source_url')}={_text('other_source_url')} AND {_text('fidelity')}='saved_text' AND {_text('other_fidelity')}='exact'"),
    'govinfo_same_stem_groups': (['body_keys','files'], 'added',
        f"{_text('group_id')} IS NOT NULL AND ({_text('group_kind')}='same_stem' OR ({_text('group_kind')}='publisher' AND regexp_like({_text('source_url')},'^https?://([^/]+[.])?govinfo[.]gov/')))"),
    'old_placeholder_xml': (['body_keys','files'], 'removed',
        f"{_text('record_role')}='error_response' AND {_text('format')}='html' AND {_int('distinct_contexts')}>100 AND regexp_like({_text('source_url')},'^https?://docs[.]house[.]gov/.*[.]xml([?#]|$)')"),
    'link_label_provenance': (['title','source.link_text','source.listed_on'], 'added',
        f"{_text('label_basis')}='saved_page' AND {_text('link_text')}=value"),
    'capture_dates': (['first_captured','in_archive_since','date_kind'], 'removed',
        f"{_text('retrieved_at')} IS NULL AND {_bool('is_import_run')} AND {_text('old_time_basis')}='import_run'"),
    'govinfo123_fetch': (['first_captured','body_keys','files'], 'added',
        f"{_text('match_basis')}='direct_official_package' AND {_text('mode')}='fetch' AND {_text('requested_url')}={_text('url')} AND {_text('url')}={_text('original_url')} AND regexp_like({_text('url')},'^https?://([^/]+[.])?govinfo[.]gov/') AND {_bool('publisher_requested')} AND {_int('http_status')}=200 AND {_bool('complete')} AND {_text('outcome')}='stored' AND {_text('retrieved_at')} IS NOT NULL"),
    'b7_owner_recoveries': (['recoveries','recovery.kind','recovery.imported_at'], 'added',
        f"{_text('stage')}='raw-recoveries-owner-32c13ffa' AND {_text('decision_id')} IS NOT NULL AND {_text('kind')}='requested_content_in_official_hearing' AND {_text('source_time_basis')}='earliest_matching_fetch'"),
}


def cause_steps():
    branches = []
    for cause, (fields, direction, predicate) in CAUSES.items():
        scope = ','.join("'" + name + "'" for name in fields)
        branches.append(f"""SELECT DISTINCT difference_id,'{cause}' AS cause,evidence_ref
            FROM observed_differences WHERE field IN ({scope}) AND direction='{direction}'
            AND evidence_ref IS NOT NULL AND length(evidence_ref)>0 AND ({predicate})""")
    return [dict(name='known_causes',sql=' UNION ALL '.join(branches),materialize=True)]


def alignment_steps():
    # Exact evidence sets avoid expanding unchanged editions sharing an address.
    # Remaining edges are many-to-many; worst-case output is O(old × new) per
    # anchor. Report its fanout rather than hide rows or choose an arbitrary mate.
    return [
        dict(name='old_signatures',sql="SELECT doc,json_array(array_sort(array_agg(DISTINCT identity_anchor))) AS signature FROM old_anchors GROUP BY doc",materialize=True),
        dict(name='new_signatures',sql="SELECT doc,json_array(array_sort(array_agg(DISTINCT identity_anchor))) AS signature FROM new_anchors GROUP BY doc",materialize=True),
        dict(name='exact_pairs',sql='SELECT o.doc AS old_doc,n.doc AS new_doc FROM old_signatures o JOIN new_signatures n ON o.signature=n.signature',materialize=True),
        dict(name='aligned_pairs',sql='''SELECT old_doc,new_doc FROM exact_pairs UNION
            SELECT o.doc,n.doc FROM old_anchors o JOIN new_anchors n ON o.anchor=n.anchor
            WHERE NOT EXISTS(SELECT 1 FROM exact_pairs p WHERE p.old_doc=o.doc)
               OR NOT EXISTS(SELECT 1 FROM exact_pairs p WHERE p.new_doc=n.doc)''',materialize=True),
    ]


def decision_ready(*, unclassified, derived_only, invalid_ids, missing_evidence, invalid_records=0):
    return not any((unclassified, derived_only, invalid_ids, missing_evidence, invalid_records))


def comparison_steps():
    steps = alignment_steps()
    steps += [
        dict(name='old_values',sql='SELECT DISTINCT p.old_doc,p.new_doc,f.field,f.subject,f.value FROM aligned_pairs p JOIN old_fields f ON p.old_doc=f.doc',materialize=True),
        dict(name='new_values',sql='SELECT DISTINCT p.old_doc,p.new_doc,f.field,f.subject,f.value FROM aligned_pairs p JOIN new_fields f ON p.new_doc=f.doc',materialize=True),
        dict(name='delta_values',sql='''SELECT o.old_doc,o.new_doc,o.field,o.subject,o.value,'removed' AS direction
            FROM old_values o LEFT ANTI JOIN new_values n ON o.old_doc=n.old_doc AND o.new_doc=n.new_doc
                AND o.field=n.field AND o.subject=n.subject AND o.value=n.value
            UNION ALL SELECT n.old_doc,n.new_doc,n.field,n.subject,n.value,'added' FROM new_values n
            LEFT ANTI JOIN old_values o ON o.old_doc=n.old_doc AND o.new_doc=n.new_doc
                AND o.field=n.field AND o.subject=n.subject AND o.value=n.value
            UNION ALL SELECT d.doc AS old_doc,cast(NULL AS VARCHAR) AS new_doc,'document' AS field,'' AS subject,d.doc AS value,'removed' AS direction FROM old_documents d
                WHERE NOT EXISTS(SELECT 1 FROM aligned_pairs p WHERE p.old_doc=d.doc)
            UNION ALL SELECT cast(NULL AS VARCHAR) AS old_doc,d.doc AS new_doc,'document' AS field,'' AS subject,d.doc AS value,'added' AS direction FROM new_documents d
                WHERE NOT EXISTS(SELECT 1 FROM aligned_pairs p WHERE p.new_doc=d.doc)''',materialize=True),
        dict(name='differences',sql="SELECT DISTINCT encode(sha256(json_array(old_doc,new_doc,field,subject,value,direction)),'hex') AS difference_id,* FROM delta_values",materialize=True),
        dict(name='observed_differences',sql='''SELECT d.*,w.fact,w.evidence_ref FROM differences d LEFT JOIN witnesses w
            ON (w.old_doc IS NULL OR w.old_doc=d.old_doc) AND (w.new_doc IS NULL OR w.new_doc=d.new_doc)
            AND w.subject=d.subject AND (w.old_doc IS NOT NULL OR w.new_doc IS NOT NULL)''',materialize=True),
    ]
    steps += cause_steps()
    steps += [
        dict(name='unexplained',sql='SELECT d.* FROM differences d LEFT ANTI JOIN known_causes c ON d.difference_id=c.difference_id',materialize=True),
        dict(name='classified',sql='''SELECT u.*,r.classification,r.rule_ref,r.note,r.raw_signal FROM unexplained u
            LEFT JOIN difference_records r ON u.difference_id=r.difference_id''',materialize=True),
        dict(name='source_identity_errors',sql="""SELECT side,doc,'source_id' AS identity,source_id AS declared,
            encode(sha256(json_array(body_key,filename,source_url)),'hex') AS computed
            FROM identity_sources WHERE source_id IS DISTINCT FROM encode(sha256(json_array(body_key,filename,source_url)),'hex')""",materialize=True),
        dict(name='document_identity_errors',sql="""SELECT side,doc,'document_id' AS identity,document_id AS declared,
            encode(sha256(CASE WHEN array_length(body_keys)>0 THEN json_array('bodies',array_sort(array_distinct(body_keys)))
            ELSE json_array('sources',array_sort(array_distinct(source_ids))) END),'hex') AS computed FROM identity_documents
            WHERE document_id IS DISTINCT FROM encode(sha256(CASE WHEN array_length(body_keys)>0 THEN json_array('bodies',array_sort(array_distinct(body_keys)))
            ELSE json_array('sources',array_sort(array_distinct(source_ids))) END),'hex')""",materialize=True),
    ]
    return steps


def compare_relations(inputs, *, engine, work, missing_evidence=0):
    work = Path(work).resolve()
    work.mkdir(parents=True,exist_ok=False)
    outputs = [parquet_output(work,name,sql,order) for name,sql,order in [
        ('differences','SELECT * FROM differences',['difference_id']),
        ('explained','SELECT * FROM known_causes',['difference_id','cause','evidence_ref']),
        ('unexplained','SELECT * FROM classified',['difference_id']),
        ('alignment','SELECT * FROM aligned_pairs',['old_doc','new_doc']),
        ('identity-errors','SELECT * FROM source_identity_errors UNION ALL SELECT * FROM document_identity_errors',['side','doc','identity']),
    ]]
    queries = [dict(name='counts',sql='''SELECT (SELECT count(*) FROM differences) AS differences,
        (SELECT count(*) FROM unexplained) AS unexplained,
        (SELECT count(*) FROM classified WHERE classification IS NULL) AS unclassified,
        (SELECT count(*) FROM classified WHERE classification='derived_only_fact') AS derived_only,
        (SELECT count(*) FROM difference_records r WHERE classification IS NULL
            OR classification NOT IN ('rule_change','old_pipeline_error','derived_only_fact')
            OR note IS NULL OR length(trim(note))=0
            OR (classification='rule_change' AND (rule_ref IS NULL OR length(trim(rule_ref))=0))
            OR NOT EXISTS(SELECT 1 FROM unexplained u WHERE u.difference_id=r.difference_id))
            +(SELECT count(*) FROM (SELECT difference_id FROM difference_records GROUP BY difference_id HAVING count(*)>1)) AS invalid_records,
        (SELECT count(*) FROM source_identity_errors)+(SELECT count(*) FROM document_identity_errors) AS invalid_ids,
        (SELECT count(*) FROM aligned_pairs) AS aligned_pairs'''),
        dict(name='causes',sql='SELECT cause,count(DISTINCT difference_id) AS differences FROM known_causes GROUP BY cause ORDER BY cause'),
        dict(name='examples',sql='''SELECT * FROM (SELECT c.cause,d.*,c.evidence_ref,
            row_number() OVER(PARTITION BY cause ORDER BY d.difference_id,c.evidence_ref) AS example
            FROM known_causes c JOIN differences d ON c.difference_id=d.difference_id) WHERE example<=3 ORDER BY cause,example'''),
        dict(name='clusters',sql='''SELECT field,direction,classification,count(*) AS differences,
            count(*) FILTER(WHERE raw_signal IS NOT NULL AND length(raw_signal)>0) AS with_raw_signal
            FROM classified GROUP BY field,direction,classification ORDER BY differences DESC,field,direction''')]
    reports = run_job(work,engine,inputs=inputs,steps=comparison_steps(),outputs=outputs,queries=queries)
    counts=reports['counts'][0]
    ready=decision_ready(**{key:counts[key] for key in ['unclassified','derived_only','invalid_ids','invalid_records']},missing_evidence=missing_evidence)
    result=dict(version=1,status='complete' if ready else 'incomplete',decision_ready=ready,
        counts=dict(counts,missing_evidence=missing_evidence),causes=reports['causes'],examples=reports['examples'],clusters=reports['clusters'])
    (work/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
