"""Row-driven D4 stages and the unselected-row differential for selective backfill.

D4 runs first from the base table's own selected keys (row-driven), then once through the
producers' own candidate SQL (completion), which adds candidates the base never had.
Completion refuses before any body read when a work item's body is not available.

Cost: the inline index reads each inline receipt once per run, O(L); the MODS sidecar is
read once. Each stage holds its rows in Python memory and re-reads inline receipts once
(unchanged in the hashed producer). The differential reduces risk and proves nothing
about rows outside its sample.
"""
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.lake import appearance_records,capture_staging,captures,committee_records,filenames,meeting_records,playlist_records,transcript_headings,tables,video_records
from congress_api.lake._record_producer import INLINE_CONGRESS_MEETINGS_SQL,_candidate_rel_paths,stage_record_table
from congress_api.lake.video_records import NO_INLINE_SQL
from congress_api.lake.readings import BackfillRequired
from congress_api.retention.provenance import parquet_output,run_job

RECORD_TABLES={'meeting_records':(meeting_records,meeting_records.build_meeting_record_row),
               'appearance_records':(appearance_records,appearance_records.build_appearance_record_row)}
# Explorer tables (ct-gi01) have no base: a run that names them builds them in full here,
# through the same completion pass, so they come from this run's captures.
EXPLORER_TABLES={'video_records':video_records,'committee_records':committee_records,'playlist_records':playlist_records,
                 'transcript_headings':transcript_headings}
SELECTION_SCHEMA=pa.schema([('record_sha',pa.string()),('source',pa.string()),('stored_suffix',pa.string()),
    ('receipt_key',pa.string()),('receipt_line',pa.int64()),('source_url',pa.string())])


class SelectiveStop(RuntimeError):
    """A named condition that needs a person; nothing downstream has run."""


class Bodies:
    """Find selected record bodies, reading each index once per invocation."""
    def __init__(self,run):
        self.run=run;self.mirror=Path(run.selective['raw_root']);self.root=run.attempt/'bodies';self._inline=None;self._packages=None

    def inline(self):
        """sha256 of an inline line to (receipt,line), so no wide query carries the lines."""
        if self._inline is None:
            from viewer_publication.archive_selective import _input
            rows=run_job(self.run.attempt/'inline-index',self.run.engine,inputs=[_input('captures',self.run.base['captures'])],steps=[],outputs=[],
                queries=[dict(name='receipts',sql=f'SELECT DISTINCT receipt_key FROM ({INLINE_CONGRESS_MEETINGS_SQL})')])['receipts']
            self._inline={}
            for row in rows:
                path=self.mirror/row['receipt_key']
                if not path.is_file():raise SelectiveStop('Inline receipt is not available: '+row['receipt_key'])
                with gzip.open(path,'rb') as stream:
                    for number,line in enumerate(stream,1):
                        self._inline.setdefault(sha256(line.rstrip(b'\n')).hexdigest(),(row['receipt_key'],number))
        return self._inline

    def _fallback(self,sha):
        """A sidecar MODS body, checked against its receipt digest before use."""
        fallback=self.run.selective.get('body_fallback',{}).get('gpo_mods')
        if fallback is None:return False
        if self._packages is None:
            self._packages={}
            with open(fallback['receipts']) as stream:
                for text in stream:
                    row=json.loads(text)
                    if row.get('sha256') and row.get('package_id'):self._packages[row['sha256']]=row['package_id']
        xml=Path(fallback['root'])/(self._packages.get(sha,'')+'.xml')
        if sha not in self._packages or not xml.is_file():return False
        data=xml.read_bytes()
        if sha256(data).hexdigest()!=sha:raise ValueError('GPO MODS sidecar digest mismatch: '+sha)
        target=self.root/_candidate_rel_paths(sha,'.gz')[0];target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(gzip.compress(data,mtime=0))
        return True

    def available(self,sha,source,suffix='.gz'):
        return any((self.mirror/rel).is_file() for rel in _candidate_rel_paths(sha,suffix)) or (source=='mods' and self._fallback(sha))

    def selection(self,name,keys):
        """Rows for the producer's captures seam, or a stop listing every missing body."""
        rows=[];gaps=[]
        index=self.inline() if any(key['source']=='congress_gov' for key in keys) else {}
        for key in keys:
            sha,source=key['record_sha'],key['source']
            if source=='congress_gov' and sha in index:
                rows.append(dict(record_sha=None,source=None,stored_suffix=None,receipt_key=index[sha][0],receipt_line=index[sha][1],source_url=''))
            elif self.available(sha,source):
                rows.append(dict(record_sha=sha,source=source,stored_suffix='.gz',receipt_key=None,receipt_line=None,source_url=None))
            else:gaps.append(dict(record_sha=sha,source=source))
        if gaps:raise BodiesUnavailable(f'{name}: selected bodies are not available: '+json.dumps(gaps))
        return rows


class BodiesUnavailable(SelectiveStop):
    pass


def _stage(run,bodies,name,keys,work,*,existing,raw_store,unreadable):
    """Stage exactly these rows through the one record producer.

    The selection file stands in for captures because that is the hashed producer's only seam.
    """
    rows=bodies.selection(name,keys);work.mkdir(parents=True)
    selection=work/'selection.parquet';pq.write_table(pa.Table.from_pylist(rows,schema=SELECTION_SCHEMA),selection)
    bodies.root.mkdir(parents=True,exist_ok=True)
    return stage_selected_records(name,selection,engine=run.engine,work=work/'stage',
        existing=existing,local_root=bodies.root,raw_store=raw_store,
        unreadable_files=unreadable,decided_at=run.decided_at)


def stage_selected_records(name,selection,*,engine,work,existing=None,local_root,raw_store,
                           unreadable_files=(),decided_at=None,max_work_items=None):
    """Replay exact captured body keys or inline receipt positions through the maintained producer."""
    if name == 'committee_records':
        module,build=committee_records,committee_records.build_row
        inline_sql=NO_INLINE_SQL
    else:
        module,build=RECORD_TABLES[name]
        inline_sql='SELECT receipt_key,receipt_line,source_url FROM captures WHERE receipt_key IS NOT NULL ORDER BY receipt_key,receipt_line'
    return stage_record_table(parser_name=name,out_filename=name+'.parquet',
        candidate_sql='SELECT record_sha,stored_suffix,source FROM captures WHERE record_sha IS NOT NULL',
        inline_sql=inline_sql,
        build_row_fn=build,table_fn=module.table,captures=selection,engine=engine,work=work,
        version=module.current_versions(),existing=existing,local_root=local_root,raw_store=raw_store,
        unreadable_files=unreadable_files,decided_at=decided_at,max_work_items=max_work_items,unreadable_store=None)


def stage_d4(run,bodies):
    """Step 7: row-driven stages, reconciled against the table afterward."""
    from viewer_publication.archive_selective import _versions,current_version_sql
    done=run.state.setdefault('d4',{});raw_store,_=run.raw_store()
    for name,(module,_build) in RECORD_TABLES.items():
        keys_path=run.state['selection'][name]['keys']
        if name in done or keys_path is None:continue
        directory=run.attempt/('d4-'+name);directory.mkdir();keys=pq.read_table(keys_path).to_pylist()
        head=run.head(name,'d4-'+name+'/head')
        staged=_stage(run,bodies,name,keys,directory/'work',existing=head,raw_store=raw_store,unreadable=run.state['daily']['unreadable'])
        if staged['unreadable_pending']:raise SelectiveStop(f'{name}: new unreadable decisions await the owner: '+str(staged['unreadable_path']))
        if pq.ParquetFile(staged['records']).metadata.num_rows:
            module.append(staged,engine=run.engine,work=directory/'append',catalog_root=run.catalog,table=run.spec['tables'][name])
        pin=run.head(name,'d4-'+name+'/final');_,version=current_version_sql(name,_versions(),'t')
        found=run_job(directory/'reconcile',run.engine,inputs=[tables.table_input('t',pin),dict(name='k',kind='parquet',path=keys_path)],steps=[],outputs=[],
            queries=[dict(name='n',sql=f"SELECT count(*) AS n FROM k JOIN t ON k.record_sha=encode(t.record_sha,'hex') AND k.source=t.source AND t.parser_version={version}")])['n'][0]['n']
        if found!=len(keys):raise SelectiveStop(f'{name}: {len(keys)} selected, {found} present; a row was lost')
        done[name]=dict(selected=len(keys),appended=staged['produced']);run.save()


def _explorer_counts(run,name,directory):
    """Recover counts from the final current-pin head, including after an append/save crash."""
    from viewer_publication.archive_selective import _versions,current_version_sql
    pin=run.head(name,directory/'resolve');_,version=current_version_sql(name,_versions({name}),'t')
    rows=run_job(directory/'counts',run.engine,inputs=[tables.table_input('t',pin)],steps=[],outputs=[],
        queries=[dict(name='sources',sql=f'SELECT source,count(*) AS n FROM t WHERE parser_version={version} GROUP BY source ORDER BY source')])['sources']
    sources={row['source']:row['n'] for row in rows}
    return dict(appended=sum(sources.values()),sources=sources)


def complete_d4(run,bodies):
    """Step 7b: the producers' own candidates over the new captures and readings heads.

    Row-driven D4 cannot add a candidate the base never had (ct-kn6d). Planning runs once
    with no budget so the work list exists before any body is opened; every unavailable
    body is listed at once. The second pass repeats the O(captures) planning, named.
    """
    from viewer_publication.archive_selective import _ensure_table
    done=run.state.setdefault('completion',{});raw_store,_=run.raw_store()
    limit=run.spec['batch_size']*run.spec['max_batches']
    producers=[(name,module,True) for name,(module,_build) in RECORD_TABLES.items()]
    producers+=[(name,module,False) for name,module in EXPLORER_TABLES.items() if name in run.spec['tables']]
    for name,module,routed in producers:
        if name in done:continue
        directory=run.attempt/('complete-'+name);directory.mkdir()
        if not routed:(directory/'ensure').mkdir();_ensure_table(run,name,directory/'ensure')
        common=dict(captures=run.head('captures','complete-'+name+'/captures'),
            existing=run.head(name,'complete-'+name+'/head'),engine=run.engine,local_root=bodies.root,raw_store=raw_store,
            unreadable_files=run.state['daily']['unreadable'],decided_at=run.decided_at,unreadable_store=None)
        # D4 tables route House XML by reading; the Explorer producers read no readings.
        if routed:common['readings']=run.head('readings','complete-'+name+'/readings')
        bodies.root.mkdir(parents=True,exist_ok=True)
        try:
            module.stage(work=directory/'plan',max_work_items=0,**common)
            done[name]=dict(appended=0,sources={}) if routed else _explorer_counts(run,name,directory/'final')
            run.save();continue
        except BackfillRequired as planned:
            items=pq.read_table(planned.report['work_list']).to_pylist()
        gaps=[dict(record_sha=i['record_sha'],source=i['source']) for i in items
              if i['record_sha'] and not bodies.available(i['record_sha'],i['source'],i['stored_suffix'] or '')]
        if gaps:raise BodiesUnavailable(f'{name}: completion bodies are not available: '+json.dumps(gaps))
        try:
            staged=module.stage(work=directory/'stage',max_work_items=limit,**common)
        except BackfillRequired as error:
            raise SelectiveStop(f'{name}: completion has {error.report["work_items"]} work items, over max_work_items {limit}') from error
        if staged['unreadable_pending']:raise SelectiveStop(f'{name}: new unreadable decisions await the owner: '+str(staged['unreadable_path']))
        sources={}
        if pq.ParquetFile(staged['records']).metadata.num_rows:
            for source in pq.read_table(staged['records'],columns=['source']).column('source').to_pylist():sources[source]=sources.get(source,0)+1
            module.append(staged,engine=run.engine,work=directory/'append',catalog_root=run.catalog,table=run.spec['tables'][name])
        done[name]=dict(appended=staged['produced'],sources=sources) if routed else _explorer_counts(run,name,directory/'final')
        run.save()


def _compare(name,keys,base,fresh,ignore=None):
    """Both ways, naming the first table, key and column that differs."""
    def index(rows):return {tuple(row[k] for k in keys):row for row in rows}
    old,new=index(base),index(fresh)
    for key in old.keys()-new.keys():raise SelectiveStop(f'Predicate too narrow: {name} {key!r} was not recomputed')
    for key in new.keys()-old.keys():raise SelectiveStop(f'Predicate too narrow: {name} {key!r} recomputed but not in base')
    for key,row in old.items():
        for column in row.keys()|new[key].keys():
            if column!=ignore and row.get(column)!=new[key].get(column):
                raise SelectiveStop(f'Predicate too narrow: {name} {key!r} differs in {column}')


def _sample(run,name,n):
    from viewer_publication.archive_selective import SEED_KEYS,_input,row_predicate
    directory=run.attempt/('differential-'+name);keys=SEED_KEYS[name];narrow=','.join(keys)
    hashed="filename,source_url" if name=='filename_readings' else "encode(record_sha,'hex'),source"
    partition='PARTITION BY source ' if name in RECORD_TABLES else ''
    same=' AND '.join(f'(b.{k} IS NOT DISTINCT FROM s.{k})' for k in keys)
    ranked=f"SELECT {narrow},row_number() OVER ({partition}ORDER BY encode(sha256(concat_ws('|',{hashed})),'hex')) AS rn FROM base WHERE NOT {row_predicate(name,run.selective['where'])}"
    run_job(directory,run.engine,inputs=[_input('base',run.base[name])],
        steps=[dict(name='sample',sql=f'SELECT {narrow} FROM ({ranked}) WHERE rn<={n}',materialize=True)],
        outputs=[parquet_output(directory,'rows',f'SELECT b.* FROM base b JOIN sample s ON {same}',keys)])
    return directory,pq.read_table(directory/'rows.parquet')


def _captures_differential(run,n):
    """Unselected receipts first by hashed key, whole receipts only, up to the row cap."""
    from viewer_publication.archive_selective import _input
    directory=run.attempt/'differential-captures';keys_path=run.state['selection']['captures']['keys']
    inputs=[_input('base',run.base['captures'])];join='';keep='true'
    if keys_path:
        inputs.append(dict(name='selected',kind='parquet',path=keys_path));join=' LEFT ANTI JOIN selected s ON base.receipt_key=s.receipt_key'
    counts=run_job(directory,run.engine,inputs=inputs,steps=[],outputs=[],
        queries=[dict(name='receipts',sql=f"SELECT receipt_key,count(*) AS n FROM base{join} GROUP BY receipt_key HAVING count(*)<={n} ORDER BY encode(sha256(receipt_key),'hex') LIMIT 1000")])['receipts']
    inventory={row['key']:row for row in run.inventory()};chosen=[];total=0
    for row in counts:
        if row['receipt_key'] in inventory and Path(inventory[row['receipt_key']]['path']).is_file() and total+row['n']<=n:
            chosen.append(inventory[row['receipt_key']]);total+=row['n']
    if not chosen:return 0
    stage=capture_staging.stage_captures(chosen,engine=run.engine,work=directory/'stage',source_qualifications=run.qualifications())
    listed=','.join("'"+row['key'].replace("'","''")+"'" for row in chosen);pk=list(captures.PK)
    run_job(directory/'base',run.engine,inputs=[_input('base',run.base['captures'])],steps=[],
        outputs=[parquet_output(directory/'base','rows',f'SELECT * FROM base WHERE receipt_key IN ({listed})',pk)])
    _compare('captures',pk,pq.read_table(directory/'base/rows.parquet').to_pylist(),pq.read_table(stage/'captures.parquet').to_pylist())
    return total


def _records_differential(run,bodies,name,n,raw_store):
    from viewer_publication.archive_selective import SEED_KEYS
    directory,table=_sample(run,name,n);rows=table.to_pylist();report={};version='parser_version'
    for source in sorted({row['source'] for row in rows}):
        group=[row for row in rows if row['source']==source]
        keys=[dict(record_sha=row['record_sha'].hex(),source=source) for row in group]
        try:
            staged=_stage(run,bodies,name,keys,directory/source,existing=None,raw_store=raw_store,unreadable=[])
        except BodiesUnavailable as stop:
            if run.state['selection'][name].get('restamped'):raise SelectiveStop(f'{name}/{source}: not_differentially_checked with re-stamped rows') from stop
            report[source]='not_differentially_checked';continue
        if staged['unreadable_pending']:raise SelectiveStop(f'{name}/{source}: a reused row no longer parses')
        _compare(name,SEED_KEYS[name],group,pq.read_table(staged['records']).to_pylist(),version)
        report[source]=len(group)
    return report


def differential(run,bodies):
    """Step 3: recompute a sample of UNSELECTED rows, before any table exists.

    A difference means the predicate is too narrow. A table with unselected rows and
    nothing checked also stops: an empty comparison looks exactly like a clean one.
    """
    if 'differential' in run.state:return
    n=run.selective['differential_rows']
    if not n:
        run.state['differential']=dict(skipped=True);run.save();return
    from viewer_publication.archive_selective import _versions
    selection=run.state['selection'];raw_store,_=run.raw_store();report={}
    def unselected(name):return selection[name]['base']-selection[name]['selected']
    report['captures']=_captures_differential(run,n)
    if unselected('captures') and not report['captures']:
        raise SelectiveStop(f'captures: no unselected receipt of at most {n} rows has an available source')
    directory,table=_sample(run,'filename_readings',n);rows=table.to_pylist()
    version=_versions()['filename_readings'];parser=filenames._parser()
    fresh=[filenames.read_filename(row['filename'],row['source_url'],catalog_version=version,parser=parser) for row in rows]
    _compare('filename_readings',['filename','source_url'],rows,pa.Table.from_pylist(fresh,schema=table.schema).to_pylist(),'catalog_version')
    report['filename_readings']=len(rows)
    for name in RECORD_TABLES:
        report[name]=_records_differential(run,bodies,name,n,raw_store)
        if unselected(name) and not any(type(v) is int for v in report[name].values()):
            raise SelectiveStop(f'{name}: nothing checked in the differential')
    if unselected('filename_readings') and not report['filename_readings']:
        raise SelectiveStop('filename_readings: nothing checked in the differential')
    run.state['differential']=report;run.save()
