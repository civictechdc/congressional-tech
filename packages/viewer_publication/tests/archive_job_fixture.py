"""Real local raw-to-lake inputs shared by model and publisher integration tests."""
import hashlib
import json
import os


#: Fixture generations, stated explicitly: the producer never derives one.
SPICY_GENERATIONS={'amendments':'6'*64,'bill-family':'3'*64,'committee-rosters':'1'*64,
                   'members':'2'*64,'nominations':'4'*64,'roll-call-votes':'5'*64}


def spicy_input(generations=None,**tables):
    """In-memory spicy-regs input: every table stated, absent ones as explicitly empty rows."""
    from viewer_publication.archive_model import SPICY_SCHEMAS
    if set(tables)-set(SPICY_SCHEMAS):raise ValueError('Unknown spicy fixture table')
    return dict(generations=dict(SPICY_GENERATIONS if generations is None else generations),
                tables={name:tables.get(name,[]) for name in SPICY_SCHEMAS})


def spicy_file(directory,**tables):
    """The production spicy-regs input shape: Parquet tables under their stated generation's prefix."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    from congress_api.retention.provenance import file_pin
    from viewer_publication.archive_model import SPICY_SCHEMAS
    def arrow(kind):
        if isinstance(kind,str):return dict(Utf8=pa.string(),Int32=pa.int32(),Int64=pa.int64(),Boolean=pa.bool_())[kind]
        if 'List' in kind:return pa.list_(arrow(kind['List']['data_type']))
        return pa.struct([(item['name'],arrow(item['data_type'])) for item in kind['Struct']])
    stated=spicy_input(**tables);pinned={}
    for name,rows in stated['tables'].items():
        family='committee-rosters';key=name.removeprefix('spicy_')+'.parquet'
        path='generations/'+family+'/'+stated['generations'][family]+'/'+key
        (directory/path).parent.mkdir(parents=True,exist_ok=True)
        schema=pa.schema([(k,arrow(v)) for k,v in SPICY_SCHEMAS[name].items()])
        pq.write_table(pa.Table.from_pylist(rows,schema=schema),directory/path)
        pinned[name]=dict(family=family,key=key,path=path,rows=len(rows),**file_pin(directory/path))
    return dict(version=1,source='fixture',generations=stated['generations'],tables=pinned)


def spicy_pin(directory,**tables):
    """Write the spicy-regs input file under `directory` and return its model-spec pin."""
    from congress_api.retention.provenance import file_pin
    path=directory/'spicy-regs.json';path.write_text(json.dumps(spicy_file(directory,**tables)))
    return dict(path=str(path),**file_pin(path))


def versions():
    from congress_api.lake import readings,filenames
    return {p:readings.current_version(p) for p in ['sniff','html','xml','json']},filenames.current_version()


def model_spec(tmp_path):
    parsers,catalog=versions()
    return dict(version=1,engine_config=str(tmp_path/'unopened-runtime.json'),
        **{name:dict(kind='parquet',path=str(tmp_path/(name+'.parquet')),sha256='a'*64,size=17)
           for name in ['captures','readings','filename_readings']},
        parser_versions=parsers,catalog_version=catalog,output=str(tmp_path/'release'),scratch=str(tmp_path/'model'))


def real_model_spec(tmp_path,*,entities=False):
    import gzip
    from congress_api.lake import readings
    from congress_api.retention.provenance import file_pin
    raw=tmp_path/'raw';raw.mkdir()
    html=b'<html><head><title>Retained CLI report</title></head><body><p>'+b'Substantive retained report evidence. '*100+b'</p></body></html>'
    digest=hashlib.sha256(html).hexdigest();key='bodies/sha256/'+digest[:2]+'/'+digest+'.gz'
    stored=gzip.compress(html,mtime=0);body=raw/key;body.parent.mkdir(parents=True);body.write_bytes(stored)
    url='https://fixture.test/report.html'
    row=dict(writer=dict(job='fixture',commit='a'*40),run_id='fixture',mode='fetch',family='documents',outcome='stored',
        requested_url=url,url=url,http_status=200,complete=True,retrieved_at='2026-10-27T12:00:00Z',
        captures=[dict(sha256=digest,bytes=len(html),media_type='text/html',fidelity='exact-bytes',
            sniffed_format='html',sniff_version=readings.current_version('sniff'),stored_suffix='.gz',
            stored_bytes=len(stored),stored_md5=hashlib.md5(stored).hexdigest())])
    receipt=raw/'receipts/documents/2026-10-27/slice.jsonl.gz';receipt.parent.mkdir(parents=True)
    receipt.write_bytes(gzip.compress((json.dumps(row)+'\n').encode(),mtime=0))
    qualification=tmp_path/'receipt-pin.json';qualification.write_text(json.dumps(dict(path=str(receipt),**file_pin(receipt),producer='fixture creation')))
    return rebuild_model_spec(tmp_path,raw=raw,qualification=qualification,entities=entities),digest,html


def rebuild_model_spec(tmp_path,*,raw,qualification=None,receipts=None,entities=False):
    """Run the same producers from retained raw, with no earlier derived inputs.

    `receipts` lists (raw-relative key, qualification path); the default is the one
    real_model_spec slice with `qualification`.
    """
    from pathlib import Path
    from congress_api.lake.capture_staging import stage_captures
    from docspec_client.client import NativeDatasets
    raw=Path(raw)
    if receipts is None:receipts=[('receipts/documents/2026-10-27/slice.jsonl.gz',qualification)]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        captures=stage_captures([dict(key=key,path=str(raw/key),qualification=str(pin)) for key,pin in receipts],engine=engine,work=tmp_path/'capture-stage')/'captures.parquet'
    return derive_model_spec(tmp_path,raw=raw,captures=captures,entities=entities)


def derive_model_spec(tmp_path,*,raw,captures,entities=False):
    """Readings and filename readings from one captures file, as the producers stage them;
    with `entities`, meeting and appearance records too."""
    from congress_api.lake import readings,filenames
    from congress_api.retention.provenance import file_pin,parquet_output,run_job
    from docspec_client.client import NativeDatasets
    runtime=os.environ['DOCSPEC_JOB_CONFIG']
    with NativeDatasets.from_config(runtime) as engine:
        inventory=tmp_path/'inventory';inventory.mkdir()
        run_job(inventory,engine,inputs=[dict(name='captures',kind='parquet',path=str(captures))],steps=[],outputs=[
            parquet_output(inventory,'bodies',"""SELECT DISTINCT sha256 AS body_sha,
            'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS physical_key,
            'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS relative_path,
            stored_bytes FROM captures WHERE sha256 IS NOT NULL""",['body_sha'])])
        pages=readings.stage_once(captures=captures,body_inventory=inventory/'bodies.parquet',local_root=raw,
            engine=engine,work=tmp_path/'reading-stage',decided_at='2026-10-27T12:00:00Z')
        names=filenames.stage(captures=captures,recovery_files=(),engine=engine,work=tmp_path/'filename-stage',decided_at='2026-10-27T12:00:00Z')
        value=model_spec(tmp_path);value['engine_config']=runtime
        staged=[('captures',captures),('readings',pages['readings']),('filename_readings',names['readings'])]
        if entities:
            from congress_api.lake import appearance_records,meeting_records
            common=dict(captures=captures,engine=engine,local_root=raw,decided_at='2026-10-27T12:00:00Z',readings=pages['readings'])
            staged+=[('meeting_records',meeting_records.stage(work=tmp_path/'meeting-stage',**common)['records']),
                     ('appearance_records',appearance_records.stage(work=tmp_path/'appearance-stage',**common)['records'])]
            value['parser_versions']=dict(value['parser_versions'],meeting_records=meeting_records.current_versions(),
                                          appearance_records=appearance_records.current_versions())
        for name,path in staged:
            value[name]=dict(kind='parquet',path=str(path),**file_pin(path))
    return value


def native_daily_spec(tmp_path,model,engine):
    """Seed real local tables from the independently rebuilt raw fixture."""
    from pathlib import Path
    from congress_api.lake import captures,readings,filenames,tables
    catalog=str(tmp_path/'catalog')
    refs={name:dict(namespace=['archive'],name=name) for name in ['captures','readings','filename_readings']}
    schema=json.loads((Path(__file__).resolve().parents[3]/'model/lake/captures.schema.json').read_text())
    tables.create_table(engine=engine,work=tmp_path/'create-captures',catalog_root=catalog,
        table=refs['captures'],schema=schema,location=tmp_path/'lake-captures',create_namespace=True)
    for name,module in [('readings',readings),('filename_readings',filenames)]:
        module.create_table(engine=engine,work=tmp_path/('create-'+name),catalog_root=catalog,
            table=refs[name],location=tmp_path/('lake-'+name))
    for name,keys,definition in [('captures',['receipt_key'],captures.current_version()),
            ('readings',readings.PK,'fixture-current-readings'),
            ('filename_readings',filenames.PK,'fixture-current-filenames')]:
        tables.append_rows(model[name]['path'],engine=engine,work=tmp_path/('seed-'+name),
            catalog_root=catalog,table=refs[name],keys=keys,definition=definition)
    return dict(work=str(tmp_path/'daily'),decided_at='2026-10-28T12:00:00Z',catalog_root=catalog,
        tables=refs,receipt_inventory=[],body_inventory=str(tmp_path/'inventory/bodies.parquet'),
        local_root=str(tmp_path/'raw'),max_work_items=10,
        provenance={kind:[] for kind in ['recoveries','reviews','unreadable']})


SELECTIVE_STAMP='2026-10-28T12:00:00Z'
_MEETING_XML=b"""<?xml version="1.0" encoding="UTF-8"?>
<committee-meeting congress-num="118" session-num="1" meeting-id="HHRG118888" meeting-type="HHRG">
  <meeting-details>
    <meeting-title>Selective Hearing</meeting-title>
    <meeting-date><calendar-date>2023-06-01</calendar-date></meeting-date>
    <committees><committee-name id="AG00">Committee on Agriculture</committee-name></committees>
  </meeting-details>
</committee-meeting>"""
_WITNESS_XML=b"""<?xml version="1.0" encoding="UTF-8"?>
<witness-list meeting-id="HHRG118888">
  <panel sort-order="1">
    <witness display-order="1">
      <witness-name><firstname>Selective</firstname><lastname>Witness</lastname></witness-name>
    </witness>
  </panel>
</witness-list>"""


def selective_base(root):
    """Raw mirror plus all five base tables, staged by the real producers."""
    import gzip
    from pathlib import Path
    from congress_api.lake import appearance_records,filenames,meeting_records,readings
    from congress_api.lake.capture_staging import stage_captures
    from congress_api.retention.provenance import file_pin,parquet_output,run_job
    from docspec_client.client import NativeDatasets
    root=Path(root);raw=root/'raw';raw.mkdir(parents=True)
    def fetched(url,data,family='documents',fmt='html',media='text/html'):
        stored=gzip.compress(data,mtime=0);digest=hashlib.sha256(data).hexdigest()
        body=raw/('bodies/sha256/'+digest[:2]+'/'+digest+'.gz');body.parent.mkdir(parents=True,exist_ok=True);body.write_bytes(stored)
        return dict(writer=dict(job='fixture',commit='a'*40),run_id='fixture',mode='fetch',family=family,outcome='stored',
            requested_url=url,url=url,http_status=200,complete=True,retrieved_at=SELECTIVE_STAMP,captures=[dict(sha256=digest,bytes=len(data),media_type=media,
            fidelity='exact-bytes',sniffed_format=fmt,sniff_version=readings.current_version('sniff'),stored_suffix='.gz',stored_bytes=len(stored),stored_md5=hashlib.md5(stored).hexdigest())])
    def page(name):
        return fetched(f'https://fixture.test/{name}.html',b'<html><head><title>'+name.encode()+b'</title></head><body><p>'+(b'Substantive evidence '+name.encode()+b'. ')*80+b'</p></body></html>')
    inline=dict(writer=dict(job='fixture',commit='a'*40),run_id='inline',family='congress/meetings',
        requested_url='https://api.congress.gov/v3/committee-meeting/118/house/115599?format=json',
        url='https://api.congress.gov/v3/committee-meeting/118/house/115599?format=json',retrieved_at=SELECTIVE_STAMP,
        record=dict(committeeMeeting=dict(eventId='115599',congress=118,chamber='House',title='Inline Meeting',date='2024-08-01T14:00:00Z',
            committees=[dict(systemCode='hsag00',name='Agriculture',chamber='House')],witnesses=[dict(name='Dr. Inline',organization='Lab')])))
    receipts={'receipts/documents/2026-10-27/a.jsonl.gz':[page('a-one'),page('a-two'),page('a-three')],
        'receipts/documents/2026-10-27/c.jsonl.gz':[page('c-one')],
        'receipts/documents/2026-10-27/b.jsonl.gz':[page('b-one'),page('b-two')],
        'receipts/documents/2026-10-27/b2.jsonl.gz':[page('b2-one')],
        'receipts/house/meetings/2026-10-27/m.jsonl.gz':[
            fetched('https://docs.house.gov/meetings/AG/AG00/20230601/118888/HHRG-118-AG00-20230601.xml',_MEETING_XML,'house/meeting-xml','xml','text/xml'),
            fetched('https://docs.house.gov/meetings/AG/AG00/20230601/118888/HHRG-118-AG00-WList-20230601.xml',_WITNESS_XML,'house/witness-xml','xml','text/xml')],
        'receipts/congress/meetings/2026-10-28/assemble-inline.jsonl.gz':[inline]}
    inventory=[];counts=[]
    for key,rows in receipts.items():
        path=raw/key;path.parent.mkdir(parents=True,exist_ok=True)
        text=''.join(json.dumps(row)+'\n' for row in rows).encode();path.write_bytes(gzip.compress(text,mtime=0))
        qualification=root/('pin-'+hashlib.md5(key.encode()).hexdigest()+'.json')
        qualification.write_text(json.dumps(dict(path=str(path),**file_pin(path),producer='fixture creation')))
        inventory.append(dict(key=key,path=str(path),qualification=str(qualification)))
        counts.append(dict(key=key,source_rows=len(rows),expected_captures=len(rows),uncompressed_bytes=len(text),list_items=len(rows),
            max_line_bytes=max(len(json.dumps(row)) for row in rows)+1,max_line_items=1))
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        captures=stage_captures(inventory,engine=engine,work=root/'capture-stage')/'captures.parquet'
        bodies=root/'inventory';bodies.mkdir()
        run_job(bodies,engine,inputs=[dict(name='captures',kind='parquet',path=str(captures))],steps=[],outputs=[
            parquet_output(bodies,'bodies',"""SELECT DISTINCT sha256 AS body_sha,
            'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS physical_key,
            'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS relative_path,
            stored_bytes FROM captures WHERE sha256 IS NOT NULL""",['body_sha'])])
        pages=readings.stage_once(captures=captures,body_inventory=bodies/'bodies.parquet',local_root=raw,engine=engine,work=root/'reading-stage',decided_at=SELECTIVE_STAMP)
        names=filenames.stage(captures=captures,recovery_files=(),engine=engine,work=root/'filename-stage',decided_at=SELECTIVE_STAMP)
        common=dict(captures=captures,engine=engine,local_root=raw,decided_at=SELECTIVE_STAMP,readings=pages['readings'])
        meetings=meeting_records.stage(work=root/'meeting-stage',**common)
        appearances=appearance_records.stage(work=root/'appearance-stage',**common)
    base=dict(captures=captures,readings=pages['readings'],filename_readings=names['readings'],meeting_records=meetings['records'],appearance_records=appearances['records'])
    return dict(raw=raw,base={name:str(path) for name,path in base.items()},inventory=inventory,counts=counts,root=root)


def selective_spec(tmp_path,fixture,where,*,base=None,differential_rows=50,counts=None,**more):
    """Write and load a selective job spec over one fixture, with `base` overriding tables."""
    from pathlib import Path
    from congress_api.retention.provenance import file_pin
    from viewer_publication.archive_backfill_job import load_spec
    tmp_path=Path(tmp_path);tmp_path.mkdir(parents=True,exist_ok=True);parsers,catalog=versions()
    def written(name,value):
        path=tmp_path/name;path.write_text(json.dumps(value));return dict(path=str(path),**file_pin(path))
    (tmp_path/'contract').mkdir(exist_ok=True);(tmp_path/'targets.json').write_text('{}')
    unused=dict(kind='parquet',path='unused',sha256='a'*64,size=1)
    model=written('model-template.json',dict(version=1,engine_config='unused',parser_versions=parsers,catalog_version=catalog,output='unused',scratch='unused',
        captures=unused,readings=unused,filename_readings=unused))
    publish=written('publish-template.json',dict(version=1,model_spec=dict(path='x',sha256='a'*64,size=1),daily=dict(path='x',sha256='a'*64,size=1),bucket='derived-fixture',work='x',
        public_origin='https://archive.fixture.test',receipt_keys=[],provenance=[],run=dict(id='selective'),contract_next_release='contract',targets=dict(path='targets.json',**file_pin(tmp_path/'targets.json'))))
    spicy=spicy_pin(tmp_path,spicy_committees=[dict(system_code='HSAG00',name='Committee on Agriculture',
        chamber='House',committee_type='Standing',parent_system_code=None,website_url='https://agriculture.house.gov/',is_current=True,history=[])])
    pins={name:dict(kind='parquet',path=str(path),**file_pin(path)) for name,path in {**fixture['base'],**(base or {})}.items()}
    value=dict(version=1,bucket='derived-fixture',catalog_root=str(tmp_path/'catalog'),work=str(tmp_path/'work'),batch_size=100,max_batches=2,
        decided_at=SELECTIVE_STAMP,engine_config=os.environ['DOCSPEC_JOB_CONFIG'],
        tables={name:dict(namespace=['selective'],name=name) for name in pins},
        selective=dict(base=pins,raw_root=str(fixture['raw']),receipt_inventory=written('inventory.json',fixture['inventory']),
            source_counts=written('counts.json',fixture['counts'] if counts is None else counts),provenance=dict(recoveries=[],reviews=[],unreadable=[]),
            where=where,differential_rows=differential_rows,publish_template=publish['path'],
            model=dict(template=model['path'],engine_config=os.environ['DOCSPEC_JOB_CONFIG'],spicy_regs=spicy)))
    value.update(more)
    path=tmp_path/'spec.json';path.write_text(json.dumps(value))
    return load_spec(path)
