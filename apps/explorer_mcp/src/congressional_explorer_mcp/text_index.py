"""Release-bound full-text search over compressed verified pages and caption cues."""
import base64
from contextlib import closing
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import zlib

from .citations import text_citation
from .models import ExplorerError, MAX_BYTES
from .release import encoded

INDEX_VERSION = 1
MAX_PASSAGE_CHARS = 65536
MAX_PASSAGE_BYTES = 4 * MAX_PASSAGE_CHARS
MAX_TEXT_CHARS = 64 << 20
INDEX_NAME = 'search_index.sqlite'


def source_data_id(manifest):
    """Bind every original file, schema, coverage and source meaning, without a self-reference."""
    value = {key: value for key, value in manifest.items() if key not in ('release_id', 'text_index', 'published_at')}
    value['files'] = [item for item in manifest['files'] if item['name'] != INDEX_NAME]
    return sha256(encoded(value)).hexdigest()


def extraction_definition():
    from . import body_reader, caption_reader, citations, index_storage, index_builder
    from .large_body_reader import large_pdf_definition
    import inspect
    def hashes(module,names):
        return {name:sha256(inspect.getsource(getattr(module,name)).encode()).hexdigest() for name in names}
    transport=hashes(body_reader,('_normalize_format','_validate_archive_url','_NoRedirectHandler','_check_deadline',
        '_fetch_raw_bytes','_decompress_bounded','verify_and_decode_body','extract_pages','_load_or_extract_pages'))
    markup=hashes(body_reader,('_MarkupTextExtractor','_extract_xml_text'))
    markup.update(block_tags=sorted(body_reader._BLOCK_TAGS),skip_tags=sorted(body_reader._SKIP_TAGS))
    # Dispatch and cache code do not define unrelated format readings. Relevant
    # parsers and transport guards are pinned separately to preserve selective reuse.
    common=dict(version=INDEX_VERSION,python=sys.version.split()[0],transport=transport,
        units=hashes(index_builder,('_document_units',)),max_text_chars=MAX_TEXT_CHARS,max_passage_chars=MAX_PASSAGE_CHARS)
    plain=dict(common,text_policy='utf-8-sig then latin-1; strip; reject binary NUL')
    html=dict(common,markup=markup)
    pdf_reader=large_pdf_definition()
    pdf=dict(version=INDEX_VERSION,units=common['units'],max_text_chars=MAX_TEXT_CHARS,
             max_passage_chars=MAX_PASSAGE_CHARS,reader=pdf_reader['sha256'])
    caption=dict(plain,units=hashes(index_builder,('_caption_units',)),caption_reader=sha256(Path(caption_reader.__file__).read_bytes()).hexdigest())
    definitions={key:sha256(encoded(value)).hexdigest() for key,value in
                 dict(document=plain,text=plain,html=html,xml=html,pdf=pdf,caption=caption,playlist=caption).items()}
    association=hashes(index_builder,('seed','_seed_captions','_source','_key','qualify_caption_sources','coverage','_prune_retired_text','_restore_historical','build','source_data_id'))
    layout={name:sha256(inspect.getsource(value).encode()).hexdigest() for name,value in
            [('initialize',initialize),('inflate',inflate),('consume',index_builder._consume)]}
    consumer={name:sha256(inspect.getsource(value).encode()).hexdigest() for name,value in
              [('query_verifier',QueryVerifier),('search',TextIndex.search),('resolve',TextIndex.resolve),('read_document',TextIndex.read_document),('read_caption',TextIndex.read_caption),('indexed_pages',IndexedPages)]}
    facts=dict(version=INDEX_VERSION,python=sys.version.split()[0],sqlite=sqlite3.sqlite_version,
        pypdf=version('pypdf'),fonttools=version('fonttools'),pdf_reader=pdf_reader,
        storage_definition=sha256(Path(index_storage.__file__).read_bytes()).hexdigest(),
        definition_algorithm=sha256(inspect.getsource(extraction_definition).encode()).hexdigest(),
        extraction_code=hashes(index_builder,('extract_one','_document_units','_caption_units','_run_child')),
        body_definitions=definitions,association=association,index_layout=layout,consumer=consumer)
    # Publication intent is portable across qualified preparation hosts. Actual
    # platform SQLite and executable paths/hashes remain in retained reading facts.
    portable=dict(facts)
    portable.pop('sqlite')
    portable['body_definitions']={key:value for key,value in definitions.items() if key!='pdf'}
    portable_pdf=dict(pdf_reader['facts'])
    portable_pdf['tools']={name:{key:value for key,value in tool.items() if key not in ('executable','sha256')}
                           for name,tool in portable_pdf['tools'].items()}
    portable['pdf_reader']=portable_pdf
    return dict(sha256=sha256(encoded(facts)).hexdigest(),policy_sha256=sha256(encoded(portable)).hexdigest(),
        body_definitions=definitions,facts=facts,association_definition=sha256(encoded(association)).hexdigest(),
        layout_definition=sha256(encoded(layout)).hexdigest())


def inflate(value):
    decompressor = zlib.decompressobj()
    raw = decompressor.decompress(value, MAX_PASSAGE_BYTES + 1)
    if len(raw) > MAX_PASSAGE_BYTES or decompressor.unconsumed_tail or not decompressor.eof or decompressor.unused_data:
        raise ExplorerError('Search passage exceeds its decoded limit or is corrupt')
    return raw.decode('utf-8')


def connect(path, *, readonly=False, timeout=10):
    db = sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro&immutable=1' if readonly else str(path), uri=readonly)
    db.row_factory = sqlite3.Row
    db.create_function('inflate', 1, inflate, deterministic=True)
    db.execute('PRAGMA cache_size=-32768')
    db.execute('PRAGMA temp_store=FILE')
    db.execute('PRAGMA trusted_schema=ON')  # The shipped external-content view calls bounded inflate().
    if readonly:
        db.execute('PRAGMA query_only=ON')
    deadline = time.monotonic() + timeout
    db.set_progress_handler(lambda: time.monotonic() > deadline, 10000)
    return db


def initialize(db, layout_definition=None):
    db.execute('PRAGMA auto_vacuum=INCREMENTAL')
    db.executescript('''
      CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS bodies(body_key TEXT PRIMARY KEY,target TEXT NOT NULL,state TEXT NOT NULL,
        reason TEXT,chars INTEGER DEFAULT 0,units INTEGER DEFAULT 0,extra TEXT);
      CREATE TABLE IF NOT EXISTS passages(id INTEGER PRIMARY KEY,body_key TEXT NOT NULL,ordinal INTEGER NOT NULL,
        location TEXT NOT NULL,text_z BLOB NOT NULL,speakers TEXT NOT NULL,UNIQUE(body_key,ordinal));
      CREATE VIEW IF NOT EXISTS text_content AS SELECT id,inflate(text_z) AS text FROM passages;
      CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(text,content='text_content',content_rowid='id',detail=none,tokenize='unicode61');
      CREATE TABLE IF NOT EXISTS page_spans(body_key TEXT,page INTEGER,chars INTEGER,PRIMARY KEY(body_key,page));
      CREATE TABLE IF NOT EXISTS sources(source_key TEXT PRIMARY KEY,body_key TEXT,kind TEXT NOT NULL,
        context TEXT NOT NULL,seen TEXT NOT NULL,reason TEXT);
      CREATE INDEX IF NOT EXISTS source_bodies ON sources(body_key);
      CREATE INDEX IF NOT EXISTS source_generation ON sources(seen);
      CREATE INDEX IF NOT EXISTS source_caption_identity ON sources(json_extract(context,'$.reference.source_id'));
      CREATE INDEX IF NOT EXISTS passage_bodies ON passages(body_key);
      CREATE TABLE IF NOT EXISTS changes(source_data_id TEXT,source_key TEXT,disposition TEXT,prior_body_key TEXT,body_key TEXT,
        PRIMARY KEY(source_data_id,source_key));
      CREATE TABLE IF NOT EXISTS body_metrics(body_key TEXT PRIMARY KEY,elapsed_seconds REAL,declared_bytes INTEGER,
        completion_bytes INTEGER,index_growth_bytes INTEGER);
      CREATE TABLE IF NOT EXISTS root_coverage(source_id TEXT PRIMARY KEY,source_data_id TEXT NOT NULL,value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS body_failures(id INTEGER PRIMARY KEY,body_key TEXT NOT NULL,definition TEXT NOT NULL,
        category TEXT NOT NULL,reason TEXT NOT NULL);
    ''')
    if layout_definition is not None and metadata(db,'layout_definition') != layout_definition:
        # Schema/query fixes rebuild cheap postings from retained verified text;
        # they never invalidate the expensive body extraction completion.
        db.execute('DROP TABLE search')
        db.execute("CREATE VIRTUAL TABLE search USING fts5(text,content='text_content',content_rowid='id',detail=none,tokenize='unicode61')")
        cursor=db.execute('SELECT id,text_z FROM passages ORDER BY id')
        while rows:=cursor.fetchmany(128):
            for row in rows:
                db.execute('INSERT INTO search(rowid,text) VALUES(?,?)',[row['id'],inflate(row['text_z'])])
        metadata(db,'layout_definition',layout_definition)
    if not db.execute('SELECT 1 FROM page_spans LIMIT 1').fetchone():
        for row in db.execute("SELECT body_key,json_extract(location,'$.page') AS page,max(json_extract(location,'$.offset')+length(inflate(text_z))) AS chars FROM passages WHERE json_extract(location,'$.kind')='body_text' GROUP BY body_key,json_extract(location,'$.page')"):
            db.execute('INSERT INTO page_spans VALUES(?,?,?)',list(row))
    db.commit()


def metadata(db, key, value=None):
    if value is None:
        row = db.execute('SELECT value FROM meta WHERE key=?', [key]).fetchone()
        return json.loads(row[0]) if row else None
    db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', [key, encoded(value).decode()])


class QueryVerifier:
    """Use SQLite's own tokenizer and positional phrase check on one candidate at a time."""
    def __init__(self, query):
        self.db=sqlite3.connect(':memory:')
        self.db.execute('PRAGMA cache_size=-2048')
        self.db.execute('PRAGMA max_page_count=4096')
        self.db.execute("CREATE VIRTUAL TABLE passage USING fts5(text,tokenize='unicode61')")
        self.db.execute("CREATE VIRTUAL TABLE tokens USING fts5vocab(passage,'instance')")
        self.db.execute('INSERT INTO passage(rowid,text) VALUES(1,?)',[query.text])
        terms=[row[0] for row in self.db.execute('SELECT term FROM tokens ORDER BY offset')]
        self.db.execute('DELETE FROM passage')
        if not terms:
            self.close()
            raise ExplorerError('Search text must contain an indexed word')
        quoted=['"'+term.replace('"','""')+'"' for term in dict.fromkeys(terms)]
        self.candidate_expression=(' OR ' if query.match=='any' else ' AND ').join(quoted)
        self.exact_expression=('"'+query.text.replace('"','""')+'"') if query.match=='phrase' else self.candidate_expression

    def snippet(self,text,minimum_match_end=0):
        self.db.execute('DELETE FROM passage')
        self.db.execute('INSERT INTO passage(rowid,text) VALUES(1,?)',[text])
        self.db.commit()
        marker='\ufff0search-match\ufff1'
        while marker in text:
            marker+='\ufff1'
        end_marker=marker+'end'
        row=self.db.execute('SELECT highlight(passage,0,?,?) FROM passage WHERE passage MATCH ?',
            [marker,end_marker,self.exact_expression]).fetchone()
        if row is None:
            return None
        highlighted=row[0]
        plain_position=0
        while marker in highlighted:
            before,highlighted=highlighted.split(marker,1)
            match,highlighted=highlighted.split(end_marker,1)
            plain_position+=len(before)
            if plain_position+len(match)>minimum_match_end:
                offset=max(0,plain_position-120)
                return offset,text[offset:offset+600]
            plain_position+=len(match)
        return None

    def close(self):
        self.db.close()


class IndexedPages:
    """Decode one physical page at a time; metadata skips untouched pages."""
    def __init__(self,db,body_key,extra):
        self.db,self.body_key=db,body_key
        lengths={row['page']:row['chars'] for row in db.execute('SELECT page,chars FROM page_spans WHERE body_key=?',[body_key])}
        count=extra.get('page_count',max(lengths,default=0))
        self.lengths=[lengths.get(page,0) for page in range(1,count+1)]
    def __len__(self):return len(self.lengths)
    def __getitem__(self,index):
        if not 0<=index<len(self):raise IndexError(index)
        return self.window(index,0,self.lengths[index])
    def window(self,index,start,length):
        if not 0<=index<len(self):raise IndexError(index)
        stop=min(start+length,self.lengths[index])
        if start>=stop:return ''
        fragments=[];position=start
        rows=self.db.execute("""SELECT location,text_z FROM passages WHERE body_key=? AND json_extract(location,'$.page')=?
            AND json_extract(location,'$.offset')<? AND json_extract(location,'$.offset')+?>? ORDER BY ordinal""",
            [self.body_key,index+1,stop,MAX_PASSAGE_CHARS,start])
        for row in rows:
            offset=json.loads(row['location']).get('offset',0)
            text=inflate(row['text_z'])
            if offset>position:raise ExplorerError('Retained page has an unexplained text gap')
            end=min(offset+len(text),stop)
            if end>position:
                fragments.append(text[position-offset:end-offset]);position=end
            if position==stop:break
        if position!=stop:raise ExplorerError('Retained page differs from its accepted character count')
        return ''.join(fragments)


class TextIndex:
    def __init__(self, selection):
        manifest = selection['manifest']
        info = manifest.get('text_index')
        if not info:
            raise ExplorerError('Corpus text index is unavailable in this release; metadata search and get_document remain available')
        if info.get('source_data_id') != source_data_id(manifest):
            raise ExplorerError('Published text index identifies different source data')
        entry = next((item for item in manifest['files'] if item['name'] == INDEX_NAME), None)
        if entry is None or entry['sha256'] not in selection['files']:
            raise ExplorerError('Published text index asset is unavailable')
        self.path = selection['files'][entry['sha256']]['path']
        self.selection, self.info = selection, info

    def _validate_artifact(self,db):
        artifact=metadata(db,'artifact') or {}
        if artifact.get('state')!='complete' or artifact.get('source_data_id')!=self.info['source_data_id'] or artifact.get('definition',{}).get('sha256')!=self.info['definition']:
            raise ExplorerError('Text index completion evidence differs from the selected release')

    def read_document(self,target,query):
        from .body_reader import read_document_pages
        with closing(connect(self.path,readonly=True)) as db:
            self._validate_artifact(db)
            row=db.execute("""SELECT s.context,s.body_key,b.extra FROM sources s JOIN bodies b USING(body_key)
              WHERE s.seen=? AND s.reason IS NULL AND json_extract(s.context,'$.reference.link_key')=?
              AND b.state IN ('indexed','empty')""",[self.info['source_data_id'],target['reference']['link_key']]).fetchone()
            if row is None:return None
            context=json.loads(row['context'])
            if context['saved_body']!=target['saved_body']:
                raise ExplorerError('Retained document reading identifies another archived body')
            extra=json.loads(row['extra'] or '{}')
            target=dict(target,reader_version=context['reader_version'],witness_keys=context.get('witness_keys',[]))
            result=read_document_pages(target,query,IndexedPages(db,row['body_key'],extra))
            evidence=dict(extraction_definition=self.info['definition'],reading_definition=extra.get('reading_definition'),backend=extra.get('backend'))
            result.update(evidence,reading_origin='accepted immutable corpus text index',raw_bytes_fetched=0)
            for item in result.get('rows',[]):
                if item.get('citation'):item['citation'].update(evidence)
            if result.get('citation'):result['citation'].update(evidence)
            return result

    def read_caption(self,target,query):
        from .caption_reader import _position,caption_cursor,CAPTION_READER_VERSION,MAX_SEGMENTS_PER_CALL
        segment,cue_offset,position,skip=_position(query,target)
        reference=target['reference']
        conditions=["s.seen=?","json_extract(s.context,'$.reference.source_id')=?","json_extract(s.context,'$.reference.video_key')=?"]
        args=[self.info['source_data_id'],reference['source_id'],reference.get('video_key') or target.get('video_key')]
        if reference.get('event_id') is not None:
            conditions.append("json_extract(s.context,'$.reference.event_id')=?");args.append(reference['event_id'])
        else:
            conditions.append("json_extract(s.context,'$.reference.event_id') IS NULL")
        with closing(connect(self.path,readonly=True)) as db:
            self._validate_artifact(db)
            root=db.execute('SELECT s.context FROM sources s WHERE '+' AND '.join(conditions)+" AND json_extract(s.context,'$.resource_ordinal')=0",args).fetchone()
            if root is None and target.get('association_scope')=='package_context' and (target.get('provenance') or {}).get('scope')=='package_context':
                # The server obtained this private target from published metadata.
                # Reuse the root reading without inventing an event-specific search association.
                conditions=conditions[:3];args=args[:3]
                root=db.execute('SELECT s.context FROM sources s WHERE '+' AND '.join(conditions)+" AND json_extract(s.context,'$.resource_ordinal')=0 ORDER BY s.source_key LIMIT 1",args).fetchone()
                if root is not None:
                    selected_reference=json.loads(root['context'])['reference']
                    if selected_reference.get('event_id') is None:conditions.append("json_extract(s.context,'$.reference.event_id') IS NULL")
                    else:
                        conditions.append("json_extract(s.context,'$.reference.event_id')=?");args.append(selected_reference['event_id'])
            if root is None:return None
            context=json.loads(root['context'])
            if context['saved_body']!=target['saved_body'] or context['reader_version']!=CAPTION_READER_VERSION:
                raise ExplorerError('Retained captions identify another archived root or reader')
            coverage_row=db.execute('SELECT value FROM root_coverage WHERE source_id=? AND source_data_id=?',[reference['source_id'],self.info['source_data_id']]).fetchone()
            coverage=json.loads(coverage_row[0]) if coverage_row else dict(archive_state='unknown')
            if coverage['archive_state'] in ('unavailable','pending','unknown'):return None
            complete=coverage['archive_state'] in ('complete_retained_track','complete_retained_resources')
            result=dict(release_id=target['release_id'],event_id=reference.get('event_id'),source=target,rows=[],offset=query.offset,
                has_more=False,missing_resources=[],state='available' if complete else 'partial',reader_version=CAPTION_READER_VERSION,
                coverage=('complete_snapshot' if coverage.get('publisher_snapshot')!='live_or_open' else 'partial_live_snapshot') if complete else 'partial',
                caption_resource_coverage=coverage,reading_origin='accepted immutable corpus text index',raw_bytes_fetched=0)
            resources=db.execute('SELECT s.context,s.reason,s.body_key,b.state,b.extra FROM sources s LEFT JOIN bodies b USING(body_key) WHERE '+
                ' AND '.join(conditions)+" AND json_extract(s.context,'$.resource_ordinal')>=? ORDER BY json_extract(s.context,'$.resource_ordinal') LIMIT ?",
                [*args,segment,MAX_SEGMENTS_PER_CALL+1]).fetchall()
            done=True;next_position=None
            for resource_number,resource in enumerate(resources):
                context=json.loads(resource['context']);ordinal=context['resource_ordinal']
                if resource_number>=MAX_SEGMENTS_PER_CALL:
                    done=False;next_position=(ordinal,0);break
                if resource['reason'] or resource['state'] not in ('indexed','empty'):
                    result['missing_resources'].append(dict(ordinal=ordinal,reason=resource['reason'] or resource['state']))
                    continue
                extra=json.loads(resource['extra'] or '{}')
                rows=db.execute("SELECT location,text_z FROM passages WHERE body_key=? AND json_extract(location,'$.cue_index')>=? ORDER BY ordinal",
                    [resource['body_key'],cue_offset if ordinal==segment else 0])
                for stored in rows:
                    location=json.loads(stored['location']);index=location['cue_index']
                    if skip:skip-=1;position+=1;continue
                    text=inflate(stored['text_z'])
                    cue=dict(location.get('cue') or {},start=location['start'],end=location['end'],text=text,
                        resource_ordinal=ordinal,cue_index=index,segment_body=context['segment_body'])
                    cue['citation']=text_citation(dict(target,reader_version=CAPTION_READER_VERSION),
                        dict(kind='caption_cue',resource_ordinal=ordinal,cue_index=index,segment_body=context['segment_body'],start=cue['start'],end=cue['end']),text)
                    cue['citation'].update(extraction_definition=self.info['definition'],reading_definition=extra.get('reading_definition'),backend=extra.get('backend'))
                    if len(result['rows'])>=query.limit or len(encoded(result))+len(encoded(cue))>MAX_BYTES-4096:
                        if not result['rows']:raise ExplorerError('Caption cue exceeds response budget; open the retained source file')
                        done=False;next_position=(ordinal,index);break
                    result['rows'].append(cue);position+=1
                if not done:break
            result.update(has_more=not done,next_offset=position if not done else None,
                verification='Exact release, root, declared resource occurrence, retained reading and cue location verified in the immutable index')
            if not done:result['next_cursor']=caption_cursor(reference,*next_position,position)
            if not result['rows'] and done and not position:
                result.update(state='unavailable',reason='Retained source contains no readable caption cues')
            return result

    def resolve(self, value):
        citation=value.get('citation',value)
        source=citation.get('source') or {}
        if source.get('release_id')!=self.selection['release_id']:
            raise ExplorerError('Citation belongs to another release')
        location=citation.get('location') or {}
        offset,length=location.get('offset',0),location.get('length')
        if type(offset) is not int or offset<0 or (length is not None and (type(length) is not int or not 0<=length<=MAX_PASSAGE_CHARS)):
            raise ExplorerError('Citation offset and length exceed the retained passage limits')
        conditions,args=['seen=?','reason IS NULL'],[self.info['source_data_id']]
        if 'link_key' in source:
            conditions.append("json_extract(context,'$.reference.link_key')=?");args.append(source['link_key'])
        elif source.get('kind')=='captions':
            for key in ('source_id','video_key'):
                if key=='video_key' and source.get(key) is None:continue
                conditions.append(f"json_extract(context,'$.reference.{key}')=?");args.append(source.get(key))
            approved=value.get('source') or {}
            package_context=(approved.get('association_scope')=='package_context' and (approved.get('provenance') or {}).get('scope')=='package_context'
                and approved.get('reference')==source and approved.get('saved_body')==citation.get('saved_body'))
            if source.get('event_id') is not None and not package_context:
                conditions.append("json_extract(context,'$.reference.event_id')=?");args.append(source['event_id'])
            conditions.append("json_extract(context,'$.resource_ordinal')=?");args.append(location.get('resource_ordinal'))
        else:
            return dict(state='not_indexed',reason='This source kind has no retained full-text passage')
        with closing(connect(self.path,readonly=True)) as db:
            self._validate_artifact(db)
            for selected in db.execute('SELECT body_key,context FROM sources WHERE '+' AND '.join(conditions),args):
                context=json.loads(selected['context'])
                if context['saved_body']!=citation.get('saved_body') or context.get('reader_version')!=citation.get('reader_version'):
                    return dict(state='different_source',reason='Citation body or reader differs from this retained reading')
                if citation.get('witness_key') is not None and citation['witness_key'] not in context.get('witness_keys',[]):
                    raise ExplorerError('Citation witness occurrence is not associated with this source')
                if citation.get('extraction_definition') not in (None,self.info['definition']):
                    return dict(state='different_source',reason='Citation extraction definition differs from the retained reading')
                if location.get('kind')=='caption_cue':
                    if location.get('segment_body')!=context.get('segment_body'):
                        return dict(state='different_source',reason='Citation caption resource differs from this source occurrence')
                    sql="SELECT p.*,b.extra FROM passages p JOIN bodies b USING(body_key) WHERE p.body_key=? AND json_extract(p.location,'$.cue_index')=?"
                    params=[selected['body_key'],location.get('cue_index')]
                elif location.get('kind')=='body_text':
                    from .models import DocumentQuery
                    from .body_reader import read_document_pages
                    body=db.execute('SELECT extra FROM bodies WHERE body_key=?',[selected['body_key']]).fetchone()
                    evidence=json.loads(body['extra'] or '{}')
                    pages=IndexedPages(db,selected['body_key'],evidence)
                    if location.get('page') is None:
                        query=DocumentQuery(release_id=self.selection['release_id'],link_key=source['link_key'],section='text',offset=offset,max_chars=length or 32768)
                        target=dict(context,release_id=self.selection['release_id'],reference=source,saved_url=None)
                        text=read_document_pages(target,query,pages)['text']
                    else:
                        page=location['page']
                        if type(page) is not int or not 1<=page<=len(pages):
                            return dict(state='not_indexed',reason='Citation physical page is outside the retained reading')
                        text=pages.window(page-1,offset,length if length is not None else MAX_PASSAGE_CHARS)
                        if length is not None and len(text)!=length:
                            return dict(state='different_source',reason='Citation window exceeds the retained physical page')
                    if citation.get('reading_definition') not in (None,evidence.get('reading_definition')) or citation.get('backend') not in (None,evidence.get('backend')) or sha256(text.encode()).hexdigest()!=citation.get('text_sha256'):
                        return dict(state='different_source',reason='Citation differs from this retained exact window')
                    return dict(state='resolved',release_id=self.selection['release_id'],text=text,citation=citation,source=source,saved_body=context['saved_body'],
                        extraction_definition=self.info['definition'],reading_definition=evidence.get('reading_definition'),backend=evidence.get('backend'))
                else:
                    return dict(state='not_indexed',reason='This citation location uses another maintained reading')
                for row in db.execute(sql,params):
                    stored_location=json.loads(row['location'])
                    if location['kind']=='caption_cue' and any(location.get(key)!=stored_location.get(key) for key in ('start','end')):
                        return dict(state='different_source',reason='Citation cue timing differs from the retained cue')
                    text=inflate(row['text_z'])
                    start=offset-(stored_location.get('offset',0) if location['kind']=='body_text' else 0)
                    stop=start+length if length is not None else len(text)
                    if not 0<=start<=stop<=len(text):
                        continue
                    text=text[start:stop]
                    evidence=json.loads(row['extra'] or '{}')
                    if citation.get('reading_definition') not in (None,evidence.get('reading_definition')) or citation.get('backend') not in (None,evidence.get('backend')):
                        return dict(state='different_source',reason='Citation reading definition or backend differs')
                    if sha256(text.encode()).hexdigest()!=citation.get('text_sha256'):
                        return dict(state='different_source',reason='Citation passage digest differs from the retained exact text')
                    return dict(state='resolved',release_id=self.selection['release_id'],text=text,citation=citation,
                        source=source,saved_body=context['saved_body'],extraction_definition=self.info['definition'],
                        reading_definition=evidence.get('reading_definition'),backend=evidence.get('backend'),
                        verification='Exact release, body, reading, source association, location and passage digest verified against the immutable text index')
        return dict(state='not_indexed',reason='No matching retained passage; use the maintained source reader')

    def search(self, query):
        binding = sha256(encoded([self.selection['release_id'], query.model_dump(exclude={'cursor'})])).hexdigest()
        position, source_position = 0, ''
        if query.cursor:
            try:
                cursor = json.loads(base64.urlsafe_b64decode(query.cursor))
                if cursor['binding'] != binding or type(cursor['position']) is not int or cursor['position'] < 0 or not isinstance(cursor.get('source'),str):
                    raise ValueError()
                position, source_position = cursor['position'], cursor['source']
            except (ValueError, KeyError, TypeError):
                raise ExplorerError('Text cursor belongs to another release or query') from None
        conditions, args = ['s.seen=?', 's.reason IS NULL', "coalesce(json_extract(s.context,'$.hidden'),0)=0"], [self.info['source_data_id']]
        for field, value in [('committee_keys', query.committee_key), ('document_types', query.document_type), ('witness_keys', query.witness_key)]:
            if value is not None:
                conditions.append(f"EXISTS(SELECT 1 FROM json_each(s.context,'$.{field}') WHERE value=?)")
                args.append(value)
        if query.source_kind is not None:
            conditions.append('s.kind=?'); args.append(query.source_kind)
        if not query.include_suspect:
            conditions.append("coalesce(json_extract(s.context,'$.date_status'),'undated')<>'suspect'")
        for field, comparison in [('date_from', '>='), ('date_to', '<=')]:
            if (value := getattr(query, field)) is not None:
                conditions.append(f"json_extract(s.context,'$.date'){comparison}?"); args.append(value)
        result = dict(release_id=self.selection['release_id'], source_data_id=self.info['source_data_id'],
            coverage=self.info['coverage'], rows=[], has_more=False, order='release passage and source identity',
            notes=['Document witness keys describe source association, not inferred speakers.',
                   'Speaker filtering uses literal caption voice labels only; no person identity is inferred.'])
        last_position,last_source=position,source_position
        deadline=time.monotonic()+10
        with closing(connect(self.path, readonly=True)) as db, closing(QueryVerifier(query)) as verifier:
            self._validate_artifact(db)
            stored = metadata(db, 'artifact')
            if not stored or stored['source_data_id'] != self.info['source_data_id'] or stored.get('state') != 'complete':
                raise ExplorerError('Text index completion or source identity differs from its manifest')
            try:
                pages=db.execute('''SELECT p.*,b.extra FROM search JOIN passages p ON p.id=search.rowid
                    JOIN bodies b ON b.body_key=p.body_key WHERE search MATCH ? AND search.rowid>=? ORDER BY search.rowid''',
                    [verifier.candidate_expression,position])
                for page in pages:
                    if time.monotonic()>deadline:
                        raise ExplorerError('Text search exceeded its deadline; narrow the phrase or filters')
                    speakers=json.loads(page['speakers'])
                    if query.speaker is not None and query.speaker.lower() not in [name.lower() for name in speakers]:
                        continue
                    sources=db.execute('SELECT s.context,s.kind,s.source_key FROM sources s WHERE s.body_key=? AND '+
                        ' AND '.join(conditions)+' AND s.source_key>? ORDER BY s.source_key LIMIT ?',
                        [page['body_key'],*args,source_position if page['id']==position else '',query.limit+1]).fetchall()
                    if not sources:
                        continue
                    matched=verifier.snippet(inflate(page['text_z']),2048 if json.loads(page['location']).get('offset',0) else 0)
                    if matched is None:
                        continue
                    offset,snippet=matched
                    for row in sources:
                        if len(result['rows'])==query.limit:
                            result['has_more']=True;break
                        location=json.loads(page['location'])
                        location.update(offset=location.get('offset',0)+offset,length=len(snippet))
                        target=json.loads(row['context'])
                        if location['kind']=='caption_cue':
                            location.update(resource_ordinal=target['resource_ordinal'],segment_body=target['segment_body'])
                        target['release_id']=self.selection['release_id']
                        reference=dict(target['reference'],release_id=self.selection['release_id']);target['reference']=reference
                        evidence=json.loads(page['extra'] or '{}')
                        citation=text_citation(target,location,snippet)
                        citation.update(extraction_definition=self.info['definition'],reading_definition=evidence.get('reading_definition'),backend=evidence.get('backend'))
                        item=dict(source_key=row['source_key'],source_kind=row['kind'],reference=reference,
                            title=target.get('title'),filename=target.get('filename'),document_types=target.get('document_types',[]),
                            date=target.get('date'),date_status=target.get('date_status'),date_basis=target.get('date_basis'),
                            saved_body=target['saved_body'],text=snippet,location=location,speaker_labels=speakers,
                            witness_keys=target.get('witness_keys',[]),citation=citation)
                        if row['kind']=='caption':
                            root=db.execute('SELECT value FROM root_coverage WHERE source_id=? AND source_data_id=?',
                                [target['reference']['source_id'],self.info['source_data_id']]).fetchone()
                            item['caption_resource_coverage']=json.loads(root[0]) if root else dict(archive_state='unknown')
                            item['caption_coverage']=item['caption_resource_coverage']['archive_state']
                            item['language'],item['production']=target.get('language'),target.get('production')
                        result['rows'].append(item)
                        if len(encoded(result))>MAX_BYTES-4096:
                            result['rows'].pop()
                            if not result['rows']:
                                raise ExplorerError('Search source metadata exceeds the response budget')
                            result['has_more']=True;break
                        last_position,last_source=page['id'],row['source_key']
                    if result['has_more']:
                        break
            except sqlite3.OperationalError as error:
                raise ExplorerError('Text search exceeded its deadline or could not parse the search terms; narrow the query') from error
        if result['has_more']:
            result['next_cursor'] = base64.urlsafe_b64encode(encoded(dict(binding=binding,position=last_position,source=last_source))).decode()
        return result
