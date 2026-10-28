"""Display-only v5 seed: pinned local inputs, one native SQL conversion path."""
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from congress_api.retention.derived_files import file_identity,check_identity,retain_verified_file
from congress_api.retention.provenance import json_input,field,list_of,struct,parquet_output
from viewer_publication.archive_model_job import _local,_pin
from viewer_publication.archive_format import (ROOT,EMPTY_STRINGS,_step,_normal,_execute,legacy_meeting_keys)
from viewer_publication.archive_model import probe_selectors_query

INPUTS=('documents','filenames','captures','accepted')
ORIGIN=('kind','label','display_only','catalog_id','generation','input_files')
REQUIRED={'version','kind','display_only','catalog_id','generation','document_rows','engine_revision',
          'engine_config','output','scratch','input_files'}


def _definition_paths(job):
    paths=['model/jobs/seed-v5.json','model/registries/release-schema.json','model/registries/recovery-kinds.json',
        'model/registries/committee-codes.json','model/registries/reader-limits.json','model/fixtures/id-golden-vectors.json',
        'packages/viewer_publication/src/viewer_publication/archive_seed.py',
        'packages/viewer_publication/src/viewer_publication/archive_format.py',
        'packages/viewer_publication/src/viewer_publication/archive_model.py']
    return sorted(set(paths+[step['sql_file'] for step in job['steps']]))


def load_seed_spec(path):
    """Read the description/current definitions, never runtime or input payloads."""
    path=Path(path).resolve();value=json.loads(path.read_text())
    if not isinstance(value,dict) or set(value)!=REQUIRED:
        raise ValueError('Seed specification needs exactly its declared metadata fields')
    if type(value['version']) is not int or value['version']!=1 or value['kind']!='seed_v5' or value['display_only'] is not True:
        raise ValueError('Only a version 1 display-only v5 seed is supported')
    for name,size in [('catalog_id',32),('generation',32),('engine_revision',40)]:
        if not isinstance(value[name],str) or not re.fullmatch('[a-f0-9]{'+str(size)+'}',value[name]):
            raise ValueError('Seed '+name+' needs its exact hexadecimal identity')
    if type(value['document_rows']) is not int or value['document_rows']<=0:
        raise ValueError('Seed document_rows must be the positive pinned source count')
    if not isinstance(value['input_files'],dict) or set(value['input_files'])!=set(INPUTS):
        raise ValueError('Seed needs the four approved input files')
    result=dict(value,input_files={})
    for name in INPUTS:
        item=value['input_files'][name];_pin(item,{'path','sha256','size'})
        result['input_files'][name]=dict(item,path=_local(item['path'],path.parent))
    for name in ['engine_config','output','scratch']:result[name]=_local(value[name],path.parent)
    job_path=ROOT/'model/jobs/seed-v5.json';job_identity=file_identity(job_path)
    job=json.loads(job_path.read_text());job_identity.require(job_path)
    identities={name:(job_identity if name=='model/jobs/seed-v5.json' else file_identity(ROOT/name))
        for name in _definition_paths(job)}
    profile={name:value[name] for name in ['version','kind','display_only','catalog_id','generation','document_rows','engine_revision']}
    profile.update(label='seed: v5 catalog '+value['generation'][:8],
        input_files={name:{key:result['input_files'][name][key] for key in ['sha256','size']} for name in INPUTS},
        definition_hashes={name:identity['sha256'] for name,identity in identities.items()})
    result['profile']=profile
    result['_definition_identities']=identities
    return result


def _require_definitions(spec):
    identities=spec['_definition_identities']
    if spec['profile']['definition_hashes']!={name:identity['sha256'] for name,identity in identities.items()}:
        raise ValueError('Seed definition hashes differ from their verified custody')
    for name,identity in identities.items():identity.require(ROOT/name)


def _sql_steps():
    job=json.loads((ROOT/'model/jobs/seed-v5.json').read_text())
    return [_step(item['name'],(ROOT/item['sql_file']).read_text(),materialize=item['materialize'],
        release_after=item.get('release_after',())) for item in job['steps']]


def _seed_steps():
    return _sql_steps()+[
        _step('seed_old_meeting_values',"SELECT legacy_document_id,cast(try_cast(regexp_replace(unnest(source_meeting_id),'^(HHRG|HMKP|HMTG)-?','') AS BIGINT) AS VARCHAR) AS meeting_key FROM seed_docs"),
        _step('seed_old_meetings',"SELECT legacy_document_id,array_agg(DISTINCT meeting_key ORDER BY meeting_key) AS meeting_keys FROM seed_old_meeting_values WHERE meeting_key IS NOT NULL GROUP BY legacy_document_id",materialize=True,release_after=["seed_old_meeting_values"]),
        _step('seed_links',"""SELECT i.document_id,array_agg(DISTINCT m.body_hex ORDER BY m.body_hex) FILTER(WHERE m.body_hex IS NOT NULL) AS link_bodies
            FROM seed_identities i JOIN seed_members m USING(legacy_document_id) GROUP BY i.document_id""",materialize=True),
        _step('seed_meeting_values',f"""SELECT i.document_id,cast(try_cast(regexp_replace(unnest(d.source_meeting_id),'^(HHRG|HMKP|HMTG)-?','') AS BIGINT) AS VARCHAR) AS meeting_key
            FROM seed_identities i JOIN seed_docs d USING(legacy_document_id)
            UNION SELECT i.document_id,unnest({legacy_meeting_keys('m.source_url')}) FROM seed_identities i JOIN seed_members m USING(legacy_document_id)"""),
        _step('seed_meetings',"SELECT document_id,array_agg(DISTINCT meeting_key ORDER BY meeting_key) AS meeting_keys FROM seed_meeting_values WHERE meeting_key IS NOT NULL GROUP BY document_id",materialize=True,release_after=["seed_meeting_values"]),
        _step('seed_codes',"SELECT i.document_id,unnest(d.committee_code) AS code FROM seed_identities i JOIN seed_docs d USING(legacy_document_id)"),
        _step('seed_committees',"""SELECT d.document_id,array_agg(DISTINCT c.system_code ORDER BY c.system_code) AS committee_keys,
            array_agg(DISTINCT c.chamber ORDER BY c.chamber) AS chambers FROM committee_codes c JOIN seed_codes d ON upper(d.code)=upper(c.code) GROUP BY d.document_id""",materialize=True,release_after=["seed_codes"]),
        _step('recovery_input',"SELECT doc_key,recovery_key,original_url,kind,body,suffix,bytes,imported_at,recovered_url,identity_note FROM seed_recoveries"),
        _step('seed_recovery_choice',"SELECT *,row_number() OVER(PARTITION BY doc_key ORDER BY kind,recovered_url,body_hex,recovery_key) AS preference FROM seed_recoveries",materialize=True),
        _step('seed_presented',"""SELECT r.document_id,d.filename,d.title,d.source_url,d.body_key,d.media_type,
            d.document_kind,d.document_family,d.congress,d.document_date,
            d.measure_references,d.member_bioguide_id,d.hearing_package_id,
            coalesce(array_element(regexp_match(d.body_key,'([a-f0-9]{64})'),1),a.body_hex) AS saved_hex,
            CASE WHEN d.body_key IS NOT NULL THEN d.body_key ELSE a.body_key END AS saved_physical,
            coalesce(d.format,a.format) AS saved_format,
            CASE WHEN d.body_key IS NOT NULL THEN s.bytes ELSE a.bytes END AS saved_size,
            CASE WHEN d.body_key IS NULL AND a.body_hex IS NOT NULL THEN 'recovery' ELSE 'original' END AS saved_kind,
            CASE WHEN d.body_key IS NOT NULL THEN t.first_captured END AS first_captured,
            m.meeting_keys,c.committee_keys,c.chambers,l.link_bodies
            FROM seed_links l RIGHT JOIN (
             seed_committees c RIGHT JOIN (
              seed_meetings m RIGHT JOIN (
               seed_recovery_choice a RIGHT JOIN (
                seed_dates t RIGHT JOIN (
                 seed_sizes s RIGHT JOIN (
                  seed_representatives r JOIN seed_docs d USING(legacy_document_id)
                 ) ON d.body_key=s.body_key
                ) ON r.legacy_document_id=t.legacy_document_id
               ) ON r.document_id=a.doc_key AND a.preference=1
              ) ON r.document_id=m.document_id
             ) ON r.document_id=c.document_id
            ) ON r.document_id=l.document_id""",materialize=True,
            release_after=["seed_dates","seed_links","seed_meetings","seed_committees","seed_recovery_choice"]),
        _step('normalized',_normal('seed_presented p',doc_key='p.document_id',filename='p.filename',title='p.title',
            source_url='p.source_url',body_expected='p.body_key IS NOT NULL',body_hex='p.saved_hex',
            format='p.saved_format',document_kind='p.document_kind',document_family='p.document_family',
            committee_keys='p.committee_keys',chambers='p.chambers',congress='p.congress',document_date='p.document_date',
            first_captured='p.first_captured',date_kind="CASE WHEN p.first_captured IS NOT NULL THEN 'captured' ELSE 'unknown' END",
            saved_kind='p.saved_kind',meeting_keys='p.meeting_keys',measure_keys='p.measure_references',bioguide_ids='p.member_bioguide_id',
            suffix="CASE WHEN regexp_like(p.saved_physical,'[.]pdf$') THEN '.pdf' WHEN regexp_like(p.saved_physical,'[.]gz$') THEN '.gz' ELSE '' END",
            media_type="coalesce(p.media_type,CASE WHEN p.saved_format='pdf' THEN 'application/pdf' ELSE 'application/octet-stream' END)",
            bytes='p.saved_size',document_date_source="CASE WHEN p.document_date IS NOT NULL THEN 'filename' END",link_bodies='p.link_bodies',
            package_id='array_element(p.hearing_package_id,1)'),materialize=True,release_after=['seed_presented']),
        _step('meeting_input',"""WITH candidates AS (SELECT try_cast(regexp_replace(d.source_meeting_id[1],'^(HHRG|HMKP|HMTG)-?','') AS BIGINT) AS event_id,
            CASE WHEN cardinality(d.source_chamber)=1 THEN lower(d.source_chamber[1]) END AS chamber,
            CASE WHEN cardinality(d.source_meeting_title)=1 THEN d.source_meeting_title[1] END AS title,
            CASE WHEN cardinality(d.source_meeting_date)=1 THEN try_cast(d.source_meeting_date[1] AS DATE) END AS meeting_date
            FROM seed_docs d WHERE cardinality(d.source_meeting_id)=1)
            SELECT event_id,CASE WHEN count(DISTINCT chamber)=1 THEN min(chamber) END AS chamber,
            CASE WHEN count(DISTINCT title)=1 THEN min(title) END AS title,
            CASE WHEN count(DISTINCT meeting_date)=1 THEN min(meeting_date) END AS meeting_date
            FROM candidates WHERE event_id IS NOT NULL GROUP BY event_id""",materialize=True),
        _step('committee_input',"""SELECT c.system_code,min(d.source_committee_name[1]) AS name,min(c.chamber) AS chamber
            FROM committee_codes c JOIN seed_docs d ON upper(d.source_committee_code[1])=upper(c.code)
            WHERE cardinality(d.source_committee_code)=1 AND cardinality(d.source_committee_name)=1
            GROUP BY c.system_code HAVING count(DISTINCT d.source_committee_name[1])=1""",materialize=True),
        _step('seed_spot_sample',"SELECT *,cast(row_number() OVER(ORDER BY legacy_document_id)-1 AS BIGINT) AS source_row FROM (SELECT * FROM seed_representatives ORDER BY encode(sha256('v5-seed-spot:'||legacy_document_id),'hex') LIMIT 50)",materialize=True),
    ]


def _seed_queries(spec):
    checks=dict(
        source_count_mismatch=f"(SELECT cast(count(*)<>{spec['document_rows']} AS BIGINT) FROM seed_docs)",
        duplicate_legacy_documents="(SELECT count(*) FROM (SELECT legacy_document_id FROM seed_docs GROUP BY legacy_document_id HAVING count(*)<>1))",
        documents_without_sources="(SELECT count(*) FROM seed_document_admission d LEFT JOIN seed_identities i USING(legacy_document_id) WHERE d.exclusion_reason IS NULL AND i.document_id IS NULL)",
        unaccounted_source_rows="(SELECT abs((SELECT count(*) FROM seed_file_values)-(SELECT count(*) FROM seed_members)-(SELECT count(*) FROM seed_source_status WHERE exclusion_reason IS NOT NULL)))",
        conflicting_byte_formats="(SELECT count(*) FROM seed_docs WHERE byte_format_candidates>1)",
        missing_source_filenames="(SELECT count(*) FROM seed_members WHERE filename IS NULL OR trim(filename)='')",
        invalid_body_keys="(SELECT count(*) FROM seed_members WHERE body_key IS NOT NULL AND NOT regexp_like(body_key,'^bodies/sha256/[a-f0-9]{2}/[a-f0-9]{64}([.]gz|[.]pdf)?$'))",
        missing_member_sizes="(SELECT count(*) FROM seed_members m LEFT JOIN seed_sizes s USING(body_key) WHERE m.body_key IS NOT NULL AND s.bytes IS NULL)",
        conflicting_member_sizes="(SELECT count(*) FROM seed_members m JOIN seed_sizes s USING(body_key) WHERE s.bytes<>s.max_bytes OR s.null_bytes<>0 OR s.bytes<0)",
        unknown_recovery_kinds="(SELECT count(*) FROM seed_recovery_candidates WHERE kind IS NULL)",
        bad_recovery_records="(SELECT count(*) FROM seed_recovery_candidates WHERE body_hex IS NULL OR original_url IS NULL OR recovered_url IS NULL OR recovery_status IS DISTINCT FROM 'recovered')",
        missing_recovery_sizes="(SELECT count(*) FROM seed_recoveries WHERE bytes IS NULL OR bytes<0)",
        conflicting_recovery_sizes="(SELECT count(*) FROM seed_recoveries r JOIN seed_sizes s USING(body_key) WHERE s.bytes<>s.max_bytes OR s.null_bytes<>0)",
        required_document_values="(SELECT count(*) FROM ordered WHERE filename IS NULL OR trim(filename)='' OR format IS NULL OR trim(format)='')",
        invalid_source_ids="(SELECT count(*) FROM seed_members WHERE source_id<>encode(sha256(json_array(logical_body_key,filename,source_url)),'hex'))",
        invalid_document_ids="(SELECT count(*) FROM seed_identities WHERE document_id<>encode(sha256(CASE WHEN cardinality(body_keys)>0 THEN json_array('bodies',body_keys) ELSE json_array('sources',source_ids) END),'hex'))",
        bad_accepted_version="(SELECT count(*) FROM accepted_input WHERE version<>1 OR version IS NULL)",
        bad_accepted_container="(SELECT cast(count(*)<>1 AS BIGINT) FROM accepted_input)",
    )
    guard=dict(name='seed_invariants',sql='SELECT '+','.join(sql+' AS '+name for name,sql in checks.items()))
    duplicate_sql="SELECT i.document_id,i.legacy_document_id,r.legacy_document_id AS representative FROM seed_representatives r JOIN seed_identities i USING(document_id) WHERE i.legacy_document_id<>r.legacy_document_id"
    reconciliation=dict(name='seed_reconciliation',sql="""SELECT (SELECT count(*) FROM seed_docs) AS input_docs,
        (SELECT count(*) FROM ordered) AS listed,(SELECT count(*) FROM ("""+duplicate_sql+""")) AS merged_duplicates,
        (SELECT count(*) FROM seed_document_admission WHERE exclusion_reason IS NOT NULL) AS excluded""")
    exclusions=dict(name='seed_exclusions',sql="SELECT exclusion_reason AS reason,count(*) AS count FROM seed_document_admission WHERE exclusion_reason IS NOT NULL GROUP BY exclusion_reason")
    merged=dict(name='seed_merged_duplicates',sql='SELECT count(*) AS merged_duplicates FROM ('+duplicate_sql+')')
    merged_examples=dict(name='seed_merged_examples',sql=duplicate_sql+' ORDER BY legacy_document_id LIMIT 10')
    spot_sql="""SELECT s.source_row,d.legacy_document_id,s.document_id,o.list_row,
        d.filename AS old_filename,o.filename AS new_filename,d.format AS old_format,o.format AS new_format,
        d.source_page,d.source_meeting_id,o.meeting_keys,
        o.filename=d.filename AS filename_matches,o.format=d.format AS format_matches,
        (d.source_page IS NULL OR coalesce(array_has(a.pages,d.source_page),false)) AS source_page_matches,
        cardinality(array_except(coalesce(e.meeting_keys,"""+EMPTY_STRINGS+"""),o.meeting_keys))=0 AS meeting_matches
        FROM seed_spot_sample s JOIN seed_docs d USING(legacy_document_id) JOIN ordered o ON s.document_id=o.doc_key
        LEFT JOIN seed_old_meetings e ON d.legacy_document_id=e.legacy_document_id
        LEFT JOIN (SELECT s.document_id,array_agg(DISTINCT a.listed_on) AS pages FROM seed_spot_sample s
          JOIN ordered o ON s.document_id=o.doc_key JOIN source_rows a ON o.list_row=a.list_row
          GROUP BY s.document_id) a ON s.document_id=a.document_id"""
    examples=dict(name='seed_spot_examples',sql=spot_sql+' ORDER BY source_row')
    spots=dict(name='seed_spot_checks',sql='SELECT source_row,filename_matches,format_matches,source_page_matches,meeting_matches FROM ('+spot_sql+') ORDER BY source_row')
    guard['sql']+=',(SELECT count(*) FROM ('+spot_sql+') WHERE filename_matches IS DISTINCT FROM true OR format_matches IS DISTINCT FROM true OR source_page_matches IS DISTINCT FROM true OR meeting_matches IS DISTINCT FROM true) AS spot_mismatches'
    probe=probe_selectors_query()
    recovery_report=dict(name='seed_recovery_reconciliation',sql="""SELECT (SELECT count(*) FROM seed_recovery_candidates) AS accepted,
        (SELECT count(*) FROM seed_recoveries) AS attached,(SELECT count(*) FROM seed_recovery_candidates r LEFT JOIN seed_recovery_targets t USING(recovery_key)
        WHERE t.recovery_key IS NULL OR (t.targets<>1 AND t.original_targets<>1)) AS without_unique_v5_source""")
    source_exclusions=dict(name='seed_source_exclusions',sql="SELECT exclusion_reason AS reason,count(*) AS count FROM seed_source_status WHERE exclusion_reason IS NOT NULL GROUP BY exclusion_reason")
    source_reconciliation=dict(name='seed_source_reconciliation',sql="""SELECT (SELECT count(*) FROM seed_file_values) AS input_sources,
        (SELECT count(*) FROM seed_members) AS included,(SELECT count(*) FROM seed_source_status WHERE exclusion_reason IS NOT NULL) AS excluded""")
    source_examples=dict(name='seed_source_exclusion_examples',sql="SELECT * FROM seed_source_status WHERE exclusion_reason IS NOT NULL ORDER BY legacy_document_id,legacy_source_id LIMIT 10")
    mapping=dict(name='seed_mapping_choices',sql="""SELECT count(*) FILTER(WHERE filename_candidates>1) AS multiple_filename_candidates,
        (SELECT count(*) FROM seed_source_status WHERE seed_source_filename_from_document) AS seed_source_filename_from_document,
        count(*) FILTER(WHERE raw_filename IS NULL AND filename IS NOT NULL) AS repaired_filenames,
        count(*) FILTER(WHERE raw_format IS NULL AND format IS NOT NULL) AS repaired_formats,
        count(*) FILTER(WHERE filename IS NULL OR trim(filename)='') AS missing_filenames,
        count(*) FILTER(WHERE format IS NULL OR trim(format)='') AS missing_formats FROM seed_docs""")
    return guard,[reconciliation,exclusions,spots,examples,probe,recovery_report,source_exclusions,mapping,merged,merged_examples,source_reconciliation,source_examples]


def build_seed_release(spec,*,engine,output,scratch):
    """Bind approved files and shared writer; every join/group/export is native."""
    _require_definitions(spec)
    output,scratch=Path(output),Path(scratch)
    if output.exists() or scratch.exists() or output.is_symlink() or scratch.is_symlink():
        raise ValueError('Seed output and scratch must be fresh')
    if engine.source_revision!=spec['profile']['engine_revision']:
        raise ValueError('Seed engine revision differs from the declared profile')
    scratch.mkdir(parents=True)
    with TemporaryDirectory(prefix='seed-inputs-',dir=scratch) as directory:
        held={};paths={}
        for name in INPUTS:
            pin=spec['input_files'][name];path=Path(pin['path']);actual=file_identity(path)
            check_identity(actual,dict(sha256=pin['sha256'],bytes=pin['size']),'seed input '+name)
            owned=retain_verified_file(path,Path(directory)/(name+path.suffix),expected=actual,key='seed input '+name)
            held[name]=owned;paths[name]=str(owned.path)
        inputs=[dict(name=name,kind='parquet',path=paths[key]) for name,key in [('v5_documents','documents'),('v5_filenames','filenames'),('capture_index','captures')]]
        recovery_type=struct(**{name:'Utf8' for name in ['body_key','kind','original_url','recovered_url','recovery_basis','recovery_status']})
        inputs.append(dict(name='accepted_input',kind='json_lines',files=[dict(key='accepted',path=paths['accepted'])],
            schema=dict(fields=[field('version','Int64'),field('recoveries',list_of(recovery_type))],metadata={})))
        kinds=json.loads((ROOT/'model/registries/recovery-kinds.json').read_text())
        inputs.append(json_input(scratch,'recovery_kinds',kinds,category='Utf8',match_basis='Utf8',kind='Utf8'))
        codes=json.loads((ROOT/'model/registries/committee-codes.json').read_text())
        inputs.append(json_input(scratch,'committee_codes',codes,code='Utf8',system_code='Utf8',chamber='Utf8'))
        guard,queries=_seed_queries(spec)
        private=[parquet_output(scratch,'seed-members','SELECT DISTINCT legacy_document_id,source_id,logical_body_key,filename,source_url FROM seed_members',['legacy_document_id','source_id']),
            parquet_output(scratch,'seed-identities','SELECT * FROM seed_identities',['legacy_document_id'])]
        origin={name:spec['profile'][name] for name in ORIGIN}
        origin['gaps']=['Display-only v5 seed; capture remains on the old jobs until the raw rebuild',
            'Import dates absent from the seed have no date label; raw rebuild restores recorded dates']
        # The variants file is public; only the two proof tables are private.
        from viewer_publication.archive_format import _auxiliary
        auxiliaries=_auxiliary()+[('url_variants',"SELECT cast(NULL AS VARCHAR) AS canonical_url,cast(NULL AS VARCHAR) AS variant_url WHERE false",['variant_url','canonical_url'],[])]
        manifest=_execute(inputs,_seed_steps(),output=output,scratch=scratch,engine=engine,origin=origin,
            auxiliary=auxiliaries,extra_outputs=private,diagnostics=[guard],metadata_queries=queries)
        for owned in held.values():owned.require(owned.path)
        _require_definitions(spec)
        return manifest
