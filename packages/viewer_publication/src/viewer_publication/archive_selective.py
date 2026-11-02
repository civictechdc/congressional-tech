"""Rebuild a local archive generation, recomputing only rows a predicate selects.

Everything else is copied forward verbatim by a native append: no row is re-stamped.
Unselected D3/D4 rows must already carry the current version (D3/D4 have no compatible
versions; select them to recompute), and unselected readings must sit at a current pin or
a compatible-versions registry version. Seeded tables make the producers' own anti-joins
select the work, so there is no second selection logic.
Refuses a non-local catalog or a runtime naming a remote, so this job has no path to
Basin. It builds and writes candidate specs; publishing stays with archive_publish_job.

Cost: selection and seed are O(N) per table per run; D1 is O(bytes of selected
receipts), whole receipts being the unit; D3 and D4 are O(K) serial, all in Python
memory for D4. Selection sorts K narrow keys; the differential ranks N narrow keys per
sampled table, O(N log N). Repeated on purpose: filename-only runs guard once here, and
the model runs again at publish, because the controller trusts only its own checkpoint.
"""
from datetime import datetime,timezone
from hashlib import md5,sha256
import json
from pathlib import Path
import time
from urllib.parse import urlsplit
from uuid import uuid4

import pyarrow.parquet as pq

import shutil

from congress_api.lake import capture_backfill,captures,compatible_proof,compatible_versions,filenames,readings,tables
from congress_api.lake.capture_backfill_guard import validate_generation
from congress_api.lake.daily import ALL_TABLE_NAMES,PROVENANCE_KINDS,produce_daily
from congress_api.retention.body_store import BodyStore,LocalAdapter
from congress_api.retention.provenance import file_pin,parquet_output,run_job
from docspec_client.models import DocSpecFailure
from viewer_publication.archive_backfill_job import write_empty_body_inventory
from viewer_publication.archive_controller import _save_continuation
from viewer_publication.archive_model_job import PROVENANCE,_local,_pin,_selector,execute as execute_model,validate_spec as validate_model
from viewer_publication.archive_selective_records import RECORD_TABLES,SelectiveStop,Bodies,complete_d4,differential,stage_d4

PREDICATE_TABLES=('captures','filename_readings','meeting_records','appearance_records')
SUITES=('invariants','model_invariants','url_state_invariants','profile_completeness',
        'entity_profile_completeness','relationship_invariants')
PIN={'path','sha256','size'}
SCRATCH_BYTES=64<<30  # v21's model scratch; the job owns the seed, stages and model.
THROUGH=('tables','model')
# Identifies a seeded row, so a re-run cannot duplicate it.
SEED_KEYS={'captures':['receipt_key'],'readings':['body_sha','parser','parser_version'],
           'filename_readings':['filename','source_url'],'meeting_records':['record_sha','source'],
           'appearance_records':['record_sha','source']}
_RECORD_KEY=[("encode(record_sha,'hex')",'record_sha'),('source','source')]
SELECTION_KEYS={'filename_readings':[('filename','filename'),('source_url','source_url')],
                'meeting_records':_RECORD_KEY,'appearance_records':_RECORD_KEY}


def validate_selective(value,*,base,catalog_root,tables):
    """Refuse before any effect, without opening a runtime."""
    if catalog_root is None or urlsplit(str(catalog_root)).scheme:
        raise ValueError('Selective backfill requires a local catalog_root')
    if any(ref['namespace']==['archive'] for ref in tables.values()):
        raise ValueError('Selective backfill refuses the archive namespace')
    required={'base','raw_root','receipt_inventory','source_counts','provenance','where','differential_rows','model','publish_template'}
    if not isinstance(value,dict) or not required<=value.keys() or value.keys()-required-{'body_fallback','source_qualifications','input_manifest'}:
        raise ValueError('Selective backfill requires exactly its declared fields')
    if not isinstance(value['base'],dict) or set(value['base'])!=set(ALL_TABLE_NAMES):
        raise ValueError('Selective backfill requires a pin for all five base tables')
    result=dict(value,base={name:_selector(pin,base) for name,pin in value['base'].items()})
    result['raw_root']=_local(value['raw_root'],base)
    if not Path(result['raw_root']).is_dir():raise ValueError('Selective raw_root is absent')
    where=value['where']
    if not isinstance(where,dict) or 'readings' in where:
        raise ValueError('Selective backfill cannot select readings; metadata replay is ct-pocg')
    if not where or set(where)-set(PREDICATE_TABLES) or any(not isinstance(sql,str) or not sql.strip() for sql in where.values()):
        raise ValueError('Selective backfill requires at least one predicate')
    if any(';' in sql for sql in where.values()):raise ValueError('A selective predicate cannot contain a semicolon')
    if type(value['differential_rows']) is not int or value['differential_rows']<0:
        raise ValueError('Selective differential_rows must be a nonnegative integer')
    def pinned(item):
        _pin(item,PIN);return dict(item,path=_local(item['path'],base))
    for name in ('receipt_inventory','source_counts'):result[name]=pinned(value[name])
    for name in ('source_qualifications','input_manifest'):
        # input_manifest ties the run to how its regenerated inputs were made (release_input_custody).
        if value.get(name) is not None:result[name]=pinned(value[name])
    provenance=value['provenance']
    if not isinstance(provenance,dict) or set(provenance)!=set(PROVENANCE_KINDS):
        raise ValueError('Selective provenance must name recoveries, reviews and unreadable')
    result['provenance']={}
    for kind,rows in provenance.items():
        for row in rows:_pin(row,{'key','path','sha256','size'})
        result['provenance'][kind]=[dict(row,path=_local(row['path'],base)) for row in rows]
    fallback=value.get('body_fallback') or {}
    if set(fallback)-{'gpo_mods'}:raise ValueError('Unknown selective body fallback')
    if 'gpo_mods' in fallback:
        result['body_fallback']=dict(gpo_mods={name:_local(fallback['gpo_mods'][name],base) for name in ('receipts','root')})
    model=value['model']
    if not isinstance(model,dict) or {'template','engine_config'}-model.keys() or model.keys()-{'template','engine_config','spicy_regs'}:
        raise ValueError('Selective model requires its template and runtime; the job owns work/model-{output,scratch}')
    result['model']=dict(model,**{name:_local(model[name],base) for name in ('template','engine_config')})
    if model.get('spicy_regs') is not None:result['model']['spicy_regs']=pinned(model['spicy_regs'])
    result['publish_template']=_local(value['publish_template'],base)
    return result


def _verify_pins(selective):
    """A digest mismatch or a remote model runtime stops the run before the first effect."""
    selectors=[pin for pin in selective['base'].values() if pin['kind']=='parquet']
    selectors+=[selective[name] for name in ('receipt_inventory','source_counts','source_qualifications','input_manifest') if name in selective]
    selectors+=[row for rows in selective['provenance'].values() for row in rows]
    for item in selectors:
        if not Path(item['path']).is_file() or file_pin(item['path'])!={k:item[k] for k in ('sha256','size')}:
            raise ValueError('Selective input does not match its pin: '+item['path'])
    if json.loads(Path(selective['model']['engine_config']).read_text()).get('remote'):
        raise ValueError('Selective backfill is local-only; the model runtime names a remote')


def _versions():
    from viewer_publication.archive_model_profile import current_parser_versions
    pins=current_parser_versions(RECORD_TABLES)
    return dict(filename_readings=filenames.current_version(),**{name:pins[name] for name in RECORD_TABLES})


def _source(pin):
    return pin['path'] if pin['kind']=='parquet' else {k:pin[k] for k in ('metadata_location','table_uuid','snapshot','schema_id')}


NULL_TYPES={'string':'VARCHAR','int':'INT','long':'BIGINT','boolean':'BOOLEAN'}


def _base_columns(pin):
    """Column names a parquet base actually has; None for a native table (it carries the lake schema)."""
    return set(pq.read_schema(pin['path']).names) if pin['kind']=='parquet' else None


def _seed_columns(name,pin):
    """The lake schema's columns from the base, verbatim; a nullable column the base predates is NULL.

    A base written before a schema gained a column (v21 captures before mapping_version and
    original_path) is still copied verbatim: the absent value is unknown, and NULL says so.
    """
    have=_base_columns(pin);columns=[];added=[]
    for field in tables.load_schema(name)['fields']:
        if have is None or field['name'] in have:columns.append(f'i."{field["name"]}"');continue
        if field.get('required') or field['type'] not in NULL_TYPES:
            raise SelectiveStop(f'{name}: the base lacks required or untyped column {field["name"]}')
        columns.append(f'cast(NULL AS {NULL_TYPES[field["type"]]}) AS "{field["name"]}"');added.append(field['name'])
    return ','.join(columns),added


def _input(name,pin):
    return tables.table_input(name,_source(pin))


def current_version_sql(name,versions,alias=None):
    """(column, expression) naming the one current version a D3/D4 row may carry; None otherwise."""
    source=(alias+'.' if alias else '')+'source'
    if name=='filename_readings':return 'catalog_version',"'"+versions[name]+"'"
    if name in RECORD_TABLES:
        cases=' '.join(f"WHEN '{key}' THEN '{version}'" for key,version in sorted(versions[name].items()))
        return 'parser_version',f'CASE {source} {cases} END'
    return None,None


def row_predicate(name,where):
    return f'coalesce(({where[name]}),false)' if name in where and name!='readings' else 'false'


class Run:
    """One invocation: its pinned spec, runtime, attempt directory and durable state."""
    def __init__(self,spec,engine,state,attempt):
        self.spec=spec;self.selective=spec['selective'];self.engine=engine;self.state=state;self.attempt=attempt
        self.work=Path(spec['work']);self.catalog=spec['catalog_root'];self.base=self.selective['base']
        self.decided_at=state['decided_at']
    def save(self):
        _save_continuation(self.work/'state.json',self.state)
    def counts(self):
        return json.loads(Path(self.selective['source_counts']['path']).read_text())
    def inventory(self):
        return json.loads(Path(self.selective['receipt_inventory']['path']).read_text())
    def qualifications(self):
        return json.loads(Path(self.selective['source_qualifications']['path']).read_text()) if 'source_qualifications' in self.selective else None
    def head(self,name,work):
        return tables.resolve_tables(engine=self.engine,work=self.attempt/work,catalog_root=self.catalog,tables={name:self.spec['tables'][name]})[name]
    def raw_store(self):
        """Private store: receipts and bodies link to the mirror, provenance is copied.

        The inventory lists this store, and a new unreadable decision is written to it.
        It must never be the shared mirror.
        """
        raw=self.work/'raw';(raw/'provenance').mkdir(parents=True,exist_ok=True)
        for name in ('receipts','bodies'):
            link=raw/name
            if not link.exists():link.symlink_to(Path(self.selective['raw_root'])/name,target_is_directory=True)
        rows={}
        for kind,items in self.selective['provenance'].items():
            rows[kind]=[]
            for item in items:
                target=raw/item['key'];target.parent.mkdir(parents=True,exist_ok=True)
                if not target.exists():target.write_bytes(Path(item['path']).read_bytes())
                rows[kind].append(dict(key=item['key'],etag=None,path=str(target),sha256=item['sha256'],size=item['size']))
        return BodyStore(LocalAdapter(raw)),rows
    def check_scratch(self):
        capture_backfill.check_scratch(self.work,self.work,max_owned_scratch_bytes=SCRATCH_BYTES)


def _open_state(spec,engine):
    """Step 1: refuse changed inputs on resume. decided_at is fixed by the first run."""
    work=Path(spec['work'])
    # A model retry with another runtime keeps D1-D4; only the tables' definition is identity.
    definition={k:v for k,v in spec.items() if k not in ('work','resume','decided_at','through')}
    definition['selective']=dict(definition['selective'],model={k:v for k,v in spec['selective']['model'].items() if k!='engine_config'})
    identity=sha256(json.dumps(dict(definition=definition,captures=captures.current_version(),
        versions=_versions(),parsers={p:readings.current_version(p) for p in ('sniff','html','xml','json')},
        engine=[engine.source_revision,engine.binary_sha256]),sort_keys=True,default=str).encode()).hexdigest()
    path=work/'state.json'
    if path.exists():
        if not spec.get('resume'):raise ValueError('Selective work already exists; set resume to continue it')
        state=json.loads(path.read_text())
        if state['identity']!=identity:raise ValueError('Selective identity changed; refuse to resume')
        return state
    if work.exists():raise ValueError('Selective work must be fresh')
    if spec.get('resume'):raise ValueError('Selective resume found no state')
    (work/'attempts').mkdir(parents=True)
    state=dict(identity=identity,decided_at=spec.get('decided_at') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
    _save_continuation(path,state)
    return state


def _select(run):
    """Step 2: preflight raw keys, refuse uncovered versions, freeze narrow keys and the counts.

    A captures hit selects its whole receipt, because D1 skips committed receipt keys and
    a row-level seed would lose the rest. `hits` and `selected` report that expansion.
    Version checks group by version columns only (a handful of groups per table).
    """
    if 'selection' in run.state:return
    compatible_proof.preflight(engine=run.engine,work=run.attempt/'preflight',
        inputs={name:_source(pin) for name,pin in run.base.items()})
    where=run.selective['where'];versions=_versions();selection={}
    registry=compatible_versions.load_registry();pins=compatible_versions.current_pins()
    covered={(p,v) for p,v in pins.items()}|{(e['parser'],e['version']) for e in registry}
    for name in ALL_TABLE_NAMES:
        directory=run.attempt/('select-'+name);column,value=current_version_sql(name,versions);hit=row_predicate(name,where)
        steps=[];source='base';selected=hit;outputs=[]
        if name=='captures' and name in where:
            steps=[dict(name='selected_receipts',sql=f'SELECT DISTINCT receipt_key AS selected_key FROM base WHERE {hit}',materialize=True)]
            source='base LEFT JOIN selected_receipts ON receipt_key=selected_key';selected='selected_key IS NOT NULL'
            outputs=[parquet_output(directory,'keys','SELECT selected_key AS receipt_key FROM selected_receipts',['receipt_key'])]
        elif name in where:
            keys=SELECTION_KEYS[name]
            outputs=[parquet_output(directory,'keys','SELECT DISTINCT '+','.join(f'{e} AS {a}' for e,a in keys)+f' FROM base WHERE {hit}',[a for _,a in keys])]
        queries=[dict(name='counts',sql=f'SELECT count(*) FILTER (WHERE {hit}) AS hits,count(*) FILTER (WHERE {selected}) AS selected,count(*) AS base FROM {source}')]
        if column:
            group='source' if name in RECORD_TABLES else "cast(NULL AS VARCHAR)"
            queries.append(dict(name='stale',sql=f'SELECT {group} AS source,{column} AS version,count(*) AS n FROM base '
                f'WHERE NOT {selected} AND {column} IS DISTINCT FROM {value} GROUP BY 1,2'))
        if name=='readings':
            queries.append(dict(name='versions',sql='SELECT parser,parser_version,count(*) AS n FROM base GROUP BY parser,parser_version'))
        result=run_job(directory,run.engine,inputs=[_input('base',run.base[name])],steps=steps,outputs=outputs,queries=queries)
        [count]=result['counts']
        if name in where and not count['hits']:raise SelectiveStop(f'{name}: the predicate selects no rows')
        if result.get('stale'):
            raise SelectiveStop(f'{name}: unselected rows are not at the current version {json.dumps(result["stale"])}; '
                'select them: D3/D4 have no compatible versions')
        uncovered=[row for row in result.get('versions',[]) if (row['parser'],row['parser_version']) not in covered]
        if uncovered:
            raise SelectiveStop(f'readings: rows at versions neither current nor in the compatible-versions registry {json.dumps(uncovered)}')
        selection[name]=dict(count,keys=str(directory/'keys.parquet') if name in where else None)
    if selection['captures']['keys']:
        inventory={row['key']:row for row in run.inventory()}
        keys=pq.read_table(selection['captures']['keys']).column('receipt_key').to_pylist()
        gaps=[key for key in keys if key not in inventory or not Path(inventory[key]['path']).is_file()]
        if gaps:raise SelectiveStop('Selected receipts are absent from the inventory or disk: '+json.dumps(gaps))
    run.state['selection']=selection;run.save()


def _ensure_table(run,name,directory):
    ref=run.spec['tables'][name];missing_namespace=False
    try:
        tables.resolve_tables(engine=run.engine,work=directory/'head',catalog_root=run.catalog,tables={name:ref})
        return
    except ValueError as error:
        # The one absence resolve_tables reports: a crash can land either side of creation.
        if str(error)!=name+' table does not exist':raise
    except DocSpecFailure as error:
        # Resolution opens the catalog read-only, so a fresh one fails outright rather than
        # reporting absence. Creation makes the database; a later table's namespace exists.
        if not any(sign in str(error).lower() for sign in ('unable to open database','namespace')):raise
        missing_namespace=True
    tables.create_table(engine=run.engine,work=directory/'create',catalog_root=run.catalog,table=ref,schema=tables.load_schema(name),
        location=Path(run.catalog).parent/'lake'/name,create_namespace=missing_namespace)


def _seed(run):
    """Step 4: create the tables, then append base minus selected inside the engine, verbatim.

    No intermediate reused file: parquet_output always sorts and 4.1M wide rows do not
    fit. The anti-join makes a re-run a no-op. The spec identity already pins this work's
    inputs and predicate, so the append identity needs no sort over N keys.
    """
    seeded=run.state.setdefault('seeded',{});where=run.selective['where']
    for name in ALL_TABLE_NAMES:
        if name in seeded:continue
        directory=run.attempt/('seed-'+name);directory.mkdir();_ensure_table(run,name,directory)
        expected=run.state['selection'][name]['base']-run.state['selection'][name]['selected']
        if not expected:
            # Everything is selected: nothing to copy, and no reason to read the base's shape.
            seeded[name]=0;run.save();continue
        columns,_=_seed_columns(name,run.base[name])
        same=' AND '.join(f'(i.{k} IS NOT DISTINCT FROM e.{k})' for k in SEED_KEYS[name])
        inputs=[_input('incoming',run.base[name])];joins=f'LEFT ANTI JOIN existing e ON {same}';keep=f'NOT {row_predicate(name,where)}'
        if name=='captures' and name in where:
            inputs.append(dict(name='selected_receipts',kind='parquet',path=run.state['selection'][name]['keys']))
            joins+=' LEFT ANTI JOIN selected_receipts s ON i.receipt_key=s.receipt_key';keep='true'
        prefix=sha256((run.state['identity']+name).encode()).hexdigest()
        operation=dict(kind='append',name='append',table=run.spec['tables'][name],current_table='existing',work_table='pending',
            sql=f'SELECT {columns} FROM incoming i {joins} WHERE {keep}',identity_sql=f"SELECT '{prefix}' AS identity",
            layout=dict(file_bytes=128<<20,row_group_rows=8192,row_group_bytes=32<<20))
        tables._job(run.engine,directory/'append',catalog_root=run.catalog,inputs=inputs,operations=[operation])
        pin=tables.resolve_tables(engine=run.engine,work=directory/'seeded',catalog_root=run.catalog,tables={name:run.spec['tables'][name]})[name]
        actual=run_job(directory/'count',run.engine,inputs=[tables.table_input('t',pin)],steps=[],outputs=[],
            queries=[dict(name='n',sql='SELECT count(*) AS n FROM t')])['n'][0]['n']
        if actual!=expected:raise SelectiveStop(f'{name}: seeded {actual} rows, expected {expected}')
        seeded[name]=actual;run.save()


def _d1(run):
    """Step 5: rebuild selected whole receipts through the guarded batch driver."""
    keys=run.state['selection']['captures']['keys']
    if 'd1' in run.state or not keys:return
    selected=set(pq.read_table(keys).column('receipt_key').to_pylist());counts=run.counts()
    result=capture_backfill.execute_batches([r for r in run.inventory() if r['key'] in selected],[r for r in counts if r['key'] in selected],
        engine=run.engine,engine_config=run.spec['engine_config'],work=run.attempt/'d1',table=run.spec['tables']['captures'],catalog_root=run.catalog,
        reused_counts=[r for r in counts if r['key'] not in selected],scratch_root=run.attempt,source_qualifications=run.qualifications())
    if result['status']!='public_guard_passed':raise SelectiveStop('D1 did not pass its guard: '+result['status'])
    run.state['d1']=result['pin'];run.state['rebuilt_diff']=_rebuilt_diff(run,keys,result['pin']);run.save()


def _rebuilt_diff(run,keys,pin):
    """Per column base versus rebuilt, both ways by primary key: the guard cannot see wrong in-domain values."""
    pk=list(captures.PK);have=_base_columns(run.base['captures'])
    schema=[f['name'] for f in tables.load_schema('captures')['fields'] if f['name'] not in pk]
    fields=[c for c in schema if have is None or c in have];added=[c for c in schema if c not in fields]
    same=' AND '.join(f'b.{k}=h.{k}' for k in pk)
    columns=[f"count(*) FILTER (WHERE h.{pk[0]} IS NULL) AS only_base",f"count(*) FILTER (WHERE b.{pk[0]} IS NULL) AS only_rebuilt"]
    columns+=[f'count(*) FILTER (WHERE b.{pk[0]} IS NOT NULL AND h.{pk[0]} IS NOT NULL AND b."{c}" IS DISTINCT FROM h."{c}") AS "{c}"' for c in fields]
    rows=run_job(run.attempt/'rebuilt-diff',run.engine,inputs=[_input('base',run.base['captures']),tables.table_input('head',pin),
        dict(name='selected',kind='parquet',path=keys)],steps=[
            dict(name='old',sql='SELECT base.* FROM base JOIN selected s ON base.receipt_key=s.receipt_key'),
            dict(name='new',sql='SELECT head.* FROM head JOIN selected s ON head.receipt_key=s.receipt_key')],outputs=[],
        queries=[dict(name='diff',sql='SELECT '+','.join(columns)+f' FROM old b FULL JOIN new h ON {same}')])['diff'][0]
    # Columns the base predates are added values, not differences.
    return {**{k:v for k,v in rows.items() if v},**({'added_columns':added} if added else {})}


def _daily(run):
    """Step 6: the three-table producer form, which leaves D4 to the records module."""
    if 'daily' in run.state:return
    raw_store,provenance=run.raw_store();inventory=run.attempt/'body-inventory.parquet';write_empty_body_inventory(inventory)
    production=produce_daily(dict(work=str(run.attempt/'daily'),decided_at=run.decided_at,catalog_root=run.catalog,
        tables={name:run.spec['tables'][name] for name in ('captures','readings','filename_readings')},receipt_inventory=[],
        body_inventory=str(inventory),local_root=str(run.attempt/'bodies'),max_work_items=run.spec['batch_size']*run.spec['max_batches'],
        provenance=provenance),engine=run.engine,raw_store=raw_store)
    if production['status']!='completed':raise SelectiveStop('Daily producers stopped at '+production['status'])
    run.state['daily']=dict(captures=production['pins']['captures'],unreadable=[dict(key=r['key'],path=r['path']) for r in production['provenance']['unreadable']],
        filenames_recomputed=production['producerreports']['filename_readings'].get('produced'))
    run.save()


def _guard(run):
    """Step 8: D1 already guarded this exact head when it ran; filename-only runs have no D1."""
    if 'pins' in run.state:return
    pins=tables.resolve_tables(engine=run.engine,work=run.attempt/'heads',catalog_root=run.catalog,tables=run.spec['tables'])
    if pins['captures']!=run.state['daily']['captures']:raise SelectiveStop('Captures head changed after daily production')
    if pins['captures']!=run.state.get('d1'):
        validate_generation(engine=run.engine,work=run.attempt/'guard',pin=pins['captures'],counts=run.counts())
    run.state['pins']=pins;run.save()


def _model_value(run):
    from viewer_publication.archive_model_profile import current_parser_versions
    model=run.selective['model'];value=json.loads(Path(model['template']).read_text())
    value.update(engine_config=model['engine_config'],catalog_version=_versions()['filename_readings'],
        output=str(run.work/'model-output'),scratch=str(run.work/'model-scratch'),
        parser_versions=current_parser_versions(set(value.get('parser_versions',{}))|set(RECORD_TABLES)))
    for name,pin in run.state['pins'].items():value[name]=dict(kind='native_table',**pin)
    if 'spicy_regs' in model:value['spicy_regs']=model['spicy_regs']
    for field,kind in PROVENANCE.items():
        if kind in run.selective['provenance']:value[field]=[{k:row[k] for k in ('key','path','sha256','size')} for row in run.selective['provenance'][kind]]
    return value


def _clear_unaccepted_model(run):
    """Delete an unaccepted model attempt's output and scratch, before any scratch check.

    The runtime is not identity, so a retry with a larger pool resumes after D4. Each failed
    attempt leaves up to SCRATCH_BYTES; the invocation's first check would refuse on it.
    """
    if 'model' in run.state:return
    for name in ('model-output','model-scratch'):
        if (run.work/name).exists():shutil.rmtree(run.work/name)


def _model(run):
    """Step 9: one owned output and scratch, checked again after the tables grew the work."""
    if 'model' in run.state:return
    value=_model_value(run)
    run.check_scratch()
    built=execute_model(validate_model(value,base=run.work))
    result=json.loads((Path(value['scratch'])/'result.json').read_text())
    observed={query['name']:query['data'] for query in result.get('queries',[])}
    for name in SUITES:
        rows=observed.get(name)
        if not rows or any(type(v) is int and v for row in rows for v in row.values()):
            raise SelectiveStop('Model suite absent or positive: '+name)
    run.state['model']=dict(release_id=built['release_id'],output=built['output'],rows=built['rows'],
        runtime=dict(path=run.selective['model']['engine_config'],**file_pin(run.selective['model']['engine_config'])));run.save()


def _tables_report(run,started):
    """The `through: tables` stop: every table built and guarded, no model run."""
    state=run.state
    report=dict(status='tables_built',executed=True,work=str(run.work),seconds=round(time.monotonic()-started,1),pins=state['pins'],
        differential=state['differential'],rebuilt_diff=state.get('rebuilt_diff'),completion=state.get('completion'),
        tables={name:dict(base=state['selection'][name]['base'],hits=state['selection'][name]['hits'],selected=state['selection'][name]['selected'],
            reused=state['seeded'][name],appended=state.get('d4',{}).get(name,{}).get('appended')) for name in ALL_TABLE_NAMES})
    (run.work/'tables-report.json').write_text(json.dumps(report,indent=1,sort_keys=True))
    return report


def _outputs(run,started):
    """Step 10: only a run reaching this step writes candidates."""
    state=run.state;work=run.work
    # The publish controller runs the model again into its own fresh directories.
    candidate=dict(_model_value(run),output=str(work/'candidate-output'),scratch=str(work/'candidate-scratch'))
    model_path=work/'candidate-model.json';model_path.write_text(json.dumps(candidate,indent=1,sort_keys=True))
    template=Path(run.selective['publish_template']);publish=json.loads(template.read_text());publish.pop('daily',None)
    rows=[row for items in run.selective['provenance'].values() for row in items]
    publish.update(model_spec=dict(path=str(model_path),**file_pin(model_path)),receipt_keys=sorted(row['key'] for row in run.counts()),work=str(work/'publish'),
        provenance=[dict(key=row['key'],etag='"'+md5(Path(row['path']).read_bytes()).hexdigest()+'"') for row in rows])
    publish['contract_next_release']=str((template.parent/publish['contract_next_release']).resolve())
    publish['targets']=dict(publish['targets'],path=str((template.parent/publish['targets']['path']).resolve()))
    (work/'candidate-publish.json').write_text(json.dumps(publish,indent=1,sort_keys=True))
    report=dict(status='built',executed=True,work=str(work),release_id=state['model']['release_id'],release=state['model']['output'],seconds=round(time.monotonic()-started,1),
        differential=state['differential'],rebuilt_diff=state.get('rebuilt_diff'),filenames_recomputed=state['daily']['filenames_recomputed'],
        tables={name:dict(base=state['selection'][name]['base'],hits=state['selection'][name]['hits'],selected=state['selection'][name]['selected'],
            reused=state['seeded'][name],appended=state.get('d4',{}).get(name,{}).get('appended')) for name in ALL_TABLE_NAMES},
        completion=state.get('completion'))
    (work/'selective-report.json').write_text(json.dumps(report,indent=1,sort_keys=True))
    return report


def execute_selective(spec,*,runtime_factory=None):
    from docspec_client.client import NativeDatasets
    runtime_factory=runtime_factory or NativeDatasets.from_config
    if not spec.get('engine_config'):raise ValueError('Selective backfill requires an explicit batch engine_config')
    _verify_pins(spec['selective']);started=time.monotonic()
    with runtime_factory(spec['engine_config']) as engine:
        if engine.remote is not None:raise ValueError('Selective backfill is local-only; the runtime names a remote')
        engine.verify_runtime()
        state=_open_state(spec,engine)
        attempt=Path(spec['work'])/'attempts'/('attempt-'+uuid4().hex);attempt.mkdir(parents=True)
        run=Run(spec,engine,state,attempt);_clear_unaccepted_model(run);run.check_scratch();bodies=Bodies(run)
        _select(run)
        differential(run,bodies)
        run.check_scratch()
        _seed(run)
        _d1(run)
        _daily(run)
        stage_d4(run,bodies)
        complete_d4(run,bodies)
        _guard(run)
    if spec.get('through')=='tables':return _tables_report(run,started)
    _model(run)
    return _outputs(run,started)
