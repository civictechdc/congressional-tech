"""Durable incremental preparation; verified payloads live only in one extraction child."""
from contextlib import closing
import fcntl
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import signal
import tempfile
import subprocess
import sys
import time
import zlib

from .models import ExplorerError
from .release import atomic_json, encoded
from .text_index import (INDEX_VERSION, MAX_PASSAGE_CHARS, MAX_PASSAGE_BYTES, MAX_TEXT_CHARS,
                         connect, initialize, metadata, extraction_definition, source_data_id)


class RetryableBodyRead(ExplorerError):
    pass


class IndexJobRefusal(ExplorerError):
    pass


def _key(target, definition, kind):
    from .body_reader import _normalize_format
    try:fmt=_normalize_format(target.get('format'),target.get('saved_media_type'),target.get('filename'))
    except ExplorerError:fmt=target.get('format')
    if isinstance(definition,dict):
        definition=definition[fmt if kind=='document' and fmt in ('pdf','html','xml','text') else kind]
    return sha256(encoded([definition,target['saved_body'],target.get('saved_suffix'),fmt,kind])).hexdigest()


def _source(db, identity, target, context, definition, source_key, kind, reason=None):
    body_key = _key(target, definition, target.get('unit_kind', kind)) if target.get('saved_body') and reason is None else None
    if body_key:
        # Eligibility belongs to the source occurrence. A shared body's extraction
        # cannot inherit the first playlist's validity or relationship decisions.
        raw_target = {key: value for key, value in target.items() if key not in ('root_key', 'resource_ordinal', 'declared_uri')}
        db.execute('INSERT OR IGNORE INTO bodies(body_key,target,state) VALUES(?,?,?)', [body_key, encoded(raw_target).decode(), 'pending'])
    previous = db.execute('SELECT body_key FROM sources WHERE source_key=?', [source_key]).fetchone()
    disposition = 'new' if previous is None else ('unchanged' if previous[0] == body_key else 'changed')
    db.execute('INSERT OR REPLACE INTO changes VALUES(?,?,?,?,?)', [identity, source_key, disposition, previous[0] if previous else None, body_key])
    db.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?,?)', [source_key, body_key, kind, encoded(context).decode(), identity, reason])


def seed(db, selection, definition, association_definition=None):
    identity = source_data_id(selection['manifest'])
    if metadata(db, 'seed') == identity and metadata(db, 'definition') == definition and metadata(db,'association_definition')==association_definition:
        return identity
    from .body_reader import TEXT_FORMATS
    from .citations import TEXT_READER_VERSION
    from .reader import Reader
    with closing(Reader(selection)) as reader, db:
        status = 'document_date_status' if 'document_date_status' in reader.schemas['documents'] else "CASE WHEN document_date IS NOT NULL THEN 'unavailable' END"
        sql = f'''SELECT lower(hex(link_key)),filename,title,format,hidden,committee_keys,witness_keys,document_kind,
                  cast(document_date AS VARCHAR),{status},lower(hex(saved_body)),saved_suffix,saved_bytes,saved_kind,saved_media_type
                  FROM documents ORDER BY list_row'''
        cursor = reader.db.execute(sql)
        while rows := cursor.fetchmany(128):
            for link, filename, title, fmt, hidden, committees, witnesses, types, date, date_status, body, suffix, size, saved_kind, media in rows:
                target = dict(saved_body=body or None, saved_suffix=suffix, saved_bytes=size, format=fmt,
                    saved_url=reader.file_url(body, suffix), archive_origin=selection.get('archive_origin'), filename=filename,
                    saved_kind=saved_kind, saved_media_type=media, unit_kind='document')
                context = dict(reference=dict(link_key=link), saved_body=body or None, filename=filename, title=title,
                    format=fmt,
                    committee_keys=committees or [], witness_keys=witnesses or [], document_types=types or [], hidden=hidden,
                    date=date, date_status=date_status, date_basis='published document_date', reader_version=TEXT_READER_VERSION)
                reason = 'unavailable: no archived body' if not body else (f'excluded: unsupported format {fmt}' if fmt not in TEXT_FORMATS else None)
                _source(db, identity, target, context, definition, 'document:' + link, 'document', reason)
        _seed_captions(db, reader, identity, definition)
        # A complete seed, not a partial extraction, establishes the reference set.
        # Old references remain recorded as retired and never appear in the new search.
        for row in db.execute('SELECT source_key,body_key FROM sources WHERE seen<>?', [identity]).fetchall():
            db.execute('INSERT OR REPLACE INTO changes VALUES(?,?,?,?,NULL)', [identity, row['source_key'], 'retired', row['body_key']])
        metadata(db, 'seed', identity)
        metadata(db, 'definition', definition)
        metadata(db, 'association_definition', association_definition)
        metadata(db, 'artifact', dict(state='partial', source_data_id=identity, version=INDEX_VERSION))
    return identity


def _seed_captions(db, reader, identity, definition):
    if 'recordings' not in reader.schemas:
        return
    from .caption_reader import CAPTION_READER_VERSION
    from .citations import caption_source_id
    db.execute('CREATE TEMP TABLE IF NOT EXISTS meeting_context(event_id INTEGER PRIMARY KEY,date TEXT,committees TEXT)')
    db.execute('DELETE FROM meeting_context')
    if 'meetings' in reader.schemas:
        cursor = reader.db.execute('SELECT event_id,cast(meeting_date AS VARCHAR),committees FROM meetings')
        while rows := cursor.fetchmany(128):
            for event, date, committees in rows:
                db.execute('INSERT INTO meeting_context VALUES(?,?,?)', [event, date, encoded([value['system_code'] for value in committees or [] if value.get('system_code')]).decode()])
    # An independent cursor keeps resource point lookups from replacing this scan.
    cursor = reader.db.cursor().execute('SELECT video_key,event_ids,tracks FROM recordings')
    while rows := cursor.fetchmany(128):
      for video, events, tracks in rows:
        for track in tracks or []:
            body = track['body'].hex().lower() if track.get('body') else None
            if not body:
                continue
            source_id = caption_source_id(video, body, track.get('language'), track.get('production'))
            root = dict(saved_body=body, saved_suffix=track.get('suffix'), saved_bytes=None, format=track['format'],
                saved_url=reader.file_url(body, track.get('suffix')), archive_origin=reader.selection.get('archive_origin'),
                unit_kind='playlist' if track['format'] == 'm3u8' else 'caption')
            resources = []
            if track['format'] == 'm3u8' and 'caption_resources' in reader.schemas:
                resources = reader.db.execute('''SELECT ordinal,declared_uri,lower(hex(body)),suffix,format,status
                    FROM caption_resources WHERE video_key=? AND track_body=unhex(?) ORDER BY ordinal''', [video, body]).fetchall()
            if track['format'] != 'm3u8':
                resources = [(0, None, body, track.get('suffix'), track['format'], 'retained')]
            elif not resources:
                resources = [(0, None, body, track.get('suffix'), 'm3u8', 'missing_map')]
            root_key = _key(root, definition, root['unit_kind'])
            db.execute('INSERT OR IGNORE INTO bodies(body_key,target,state) VALUES(?,?,?)', [root_key, encoded(root).decode(), 'pending'])
            for ordinal, uri, resource_body, suffix, fmt, state in resources:
                target = dict(root, saved_body=resource_body or None, saved_suffix=suffix, format=fmt,
                    saved_url=reader.file_url(resource_body, suffix) if resource_body else None,
                    unit_kind='playlist' if ordinal == 0 and fmt == 'm3u8' else 'caption',
                    root_key=root_key if ordinal else None, resource_ordinal=ordinal, declared_uri=uri)
                for event in events or [None]:
                    meeting = db.execute('SELECT date,committees FROM meeting_context WHERE event_id=?', [event]).fetchone()
                    date, committees = (meeting['date'], json.loads(meeting['committees'])) if meeting else (None, [])
                    reference = dict(kind='captions', source_id=source_id, video_key=video)
                    if event is not None:
                        reference['event_id'] = event
                    context = dict(reference=reference, saved_body=body, video_key=video, title=video,
                        committee_keys=committees, witness_keys=[], document_types=['captions'], hidden=False,
                        date=date, date_status='accepted' if date else None, date_basis='associated meeting date' if date else None,
                        reader_version=CAPTION_READER_VERSION, language=track.get('language'), production=track.get('production'),
                        resource_ordinal=ordinal, segment_body=resource_body, root_key=root_key,
                        playlist=track['format']=='m3u8', declared_uri=uri)
                    reason = None if state == 'retained' else ('unavailable: retained playlist resource map missing' if state == 'missing_map' else 'unavailable: caption resource not retained')
                    _source(db, identity, target, context, definition, f'caption:{source_id}:{ordinal}:{event}', 'caption', reason)


def _document_units(page,text):
    # The overlap preserves every public literal phrase across passage boundaries.
    for offset in range(0,len(text),MAX_PASSAGE_CHARS-2048):
        yield dict(location=dict(kind='body_text',page=page,offset=offset),
                   text=text[offset:offset+MAX_PASSAGE_CHARS],speakers=[])


def _caption_units(text,fmt):
    from .caption_reader import cue_rows
    for index,cue in enumerate(cue_rows(text,fmt)):
        content=cue['text']
        yield dict(location=dict(kind='caption_cue',cue_index=index,start=cue['start'],end=cue['end'],
                   cue={key:value for key,value in cue.items() if key!='text'}),text=content,
                   speakers=list(dict.fromkeys(re.findall(r'<v(?:\.[^\s>]*)?\s+([^>]+)>',content))))


def extract_one(target_path, output, *, timeout, memory_mb):
    """One isolated child owns one bounded raw spool and its complete reading."""
    if sys.platform.startswith('linux'):
        import resource
        resource.setrlimit(resource.RLIMIT_AS,(memory_mb<<20,memory_mb<<20))
    from .body_reader import _load_or_extract_pages, MAX_BODY_BYTES
    from .caption_reader import cue_rows, _playlist
    target=json.loads(Path(target_path).read_bytes())
    definition=extraction_definition()
    if target.get('extraction_definition')!=definition['sha256']:
        raise IndexJobRefusal('Extraction child definition changed before opening a body')
    deadline=time.monotonic()+timeout
    kind=target['unit_kind']
    from .body_reader import _normalize_format
    fmt=_normalize_format(target.get('format'),target.get('saved_media_type'),target.get('filename'))
    reading=definition['body_definitions'][fmt if kind=='document' and fmt in ('pdf','html','xml','text') else kind]
    scratch=Path(output).parent/'active-pdf'
    pages_stream=None
    try:
        if kind=='document' and fmt=='pdf':
            from .large_body_reader import read_pdf_pages_verified
            result=read_pdf_pages_verified(target,work_dir=scratch,timeout=timeout,
                max_source_bytes=2<<30,max_decoded_bytes=2<<30,max_output_bytes=256<<20,
                min_free_bytes=target.get('min_free_bytes',15<<30))
            extra={key:result[key] for key in ('backend','source','attempts','physical_page_count','textless_pages','textless_page_ranges')}
            extra.update(reading_definition=reading,page_count=result['page_count'],pdf_extraction_definition=result['extraction_definition'])
            pages_stream=gzip.open(result['pages_path'],'rt',encoding='utf-8')
            pages=((value['page'],value['text']) for value in (json.loads(line) for line in pages_stream))
        else:
            backend={}
            texts,_,_,_=_load_or_extract_pages(target,data_dir=None,timeout=timeout,max_bytes=MAX_BODY_BYTES,deadline=deadline,backend_info=backend)
            extra=dict(backend=backend,reading_definition=reading,page_count=len(texts),textless_pages=sum(not text for text in texts))
            if kind=='playlist':
                uris,final=_playlist('\n\n'.join(texts))
                extra.update(uris=uris,publisher_snapshot='closed' if final else 'live_or_open',endlist=final)
            pages=enumerate(texts,1)
        with Path(output).open('wb') as raw,gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as stream:
            stream.write(encoded(dict(extra=extra,unit_kind=kind))+b'\n')
            chars=0
            if kind=='playlist':
                return
            for page,text in pages:
                if time.monotonic()>deadline:
                    raise IndexJobRefusal('Text extraction exceeded its deadline')
                chars+=len(text)
                if chars>MAX_TEXT_CHARS:
                    raise IndexJobRefusal('Complete extracted text exceeds the configured character limit; no partial text was indexed')
                units=_caption_units(text,fmt) if kind=='caption' else _document_units(page,text)
                for unit in units:
                    if len(unit['text'])>MAX_PASSAGE_CHARS:
                        raise IndexJobRefusal('Complete caption cue exceeds the configured passage limit')
                    stream.write(encoded(unit)+b'\n')
            stream.write(encoded(dict(total_chars=chars))+b'\n')
    finally:
        if pages_stream is not None:
            pages_stream.close()
        shutil.rmtree(scratch,ignore_errors=True)


def _run_child(command, *, timeout, memory_mb):
    """Enforce a process-family RSS and deadline boundary on macOS and Linux."""
    deadline=time.monotonic()+timeout
    peak=0
    with tempfile.TemporaryFile() as diagnostics:
        process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=diagnostics,start_new_session=True)
        try:
            while process.poll() is None:
                if time.monotonic()>deadline:
                    raise IndexJobRefusal('Extraction process family exceeded its deadline')
                try:
                    observation=subprocess.run(['ps','-axo','pid=,pgid=,rss='],capture_output=True,text=True,timeout=3,check=True)
                except (OSError,subprocess.SubprocessError) as error:
                    raise IndexJobRefusal('Could not enforce extraction process-family memory boundary') from error
                rss=sum(int(parts[2])*1024 for line in observation.stdout.splitlines()
                        if len(parts:=line.split())==3 and int(parts[1])==process.pid)
                peak=max(peak,rss)
                if rss>memory_mb<<20:
                    raise IndexJobRefusal(f'Extraction process family exceeded {memory_mb} MiB RSS')
                time.sleep(.1)
            diagnostics.seek(0)
            detail=diagnostics.read(8193)
            if len(detail)>8192:
                raise IndexJobRefusal('Extraction diagnostics exceeded their bounded response; preserve the body as pending')
            return subprocess.CompletedProcess(command,process.returncode,'',detail.decode(errors='replace')),peak
        finally:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait()


def _consume(db, body_key, path):
    with gzip.open(path, 'rb') as stream, db:
        header = json.loads(stream.readline((64 << 20) + 1))
        chars = count = 0
        page_lengths={}
        while line := stream.readline(MAX_PASSAGE_BYTES * 6 + 8193):
            if len(line) > MAX_PASSAGE_BYTES * 6 + 8192:
                raise ExplorerError('Extraction passage is corrupt or exceeds its limit')
            unit = json.loads(line)
            if 'total_chars' in unit:
                chars = unit['total_chars']
                continue
            text = unit['text']
            if len(text) > MAX_PASSAGE_CHARS or len(text.encode()) > MAX_PASSAGE_BYTES:
                raise ExplorerError('Extraction passage exceeds its decoded limit')
            cursor = db.execute('INSERT INTO passages(body_key,ordinal,location,text_z,speakers) VALUES(?,?,?,?,?)',
                [body_key, count, encoded(unit['location']).decode(), zlib.compress(text.encode()), encoded(unit['speakers']).decode()])
            db.execute('INSERT INTO search(rowid,text) VALUES(?,?)', [cursor.lastrowid, text])
            location=unit['location']
            if location['kind']=='body_text':
                page_lengths[location['page']]=max(page_lengths.get(location['page'],0),location.get('offset',0)+len(text))
            count += 1; chars += len(text)
        for page in range(1,header['extra'].get('page_count',0)+1):
            db.execute('INSERT OR REPLACE INTO page_spans VALUES(?,?,?)',[body_key,page,page_lengths.get(page,0)])
        state = 'indexed' if count else ('manifest' if header.get('unit_kind') == 'playlist' else 'empty')
        db.execute('UPDATE bodies SET state=?,reason=NULL,chars=?,units=?,extra=? WHERE body_key=?',
                   [state, chars, count, encoded(header['extra']).decode(), body_key])


def coverage(db, identity):
    groups = db.execute('''WITH dispositions AS (
      SELECT s.kind,coalesce(s.reason,b.state,'unavailable') AS disposition FROM sources s LEFT JOIN bodies b USING(body_key) WHERE s.seen=?)
      SELECT kind,disposition AS state,count(*) AS count FROM dispositions GROUP BY kind,disposition ORDER BY kind,disposition''', [identity]).fetchall()
    counts = [dict(row) for row in groups]
    totals = db.execute('''SELECT count(*) AS bodies,coalesce(sum(chars),0) AS chars,coalesce(sum(units),0) AS passages
      FROM bodies WHERE body_key IN (SELECT body_key FROM sources WHERE seen=?)''', [identity]).fetchone()
    material = [dict(row) for row in db.execute('''WITH dispositions AS (SELECT coalesce(t.value,'unspecified') AS document_type,
      coalesce(s.reason,b.state,'unavailable') AS disposition FROM sources s
      LEFT JOIN bodies b USING(body_key) LEFT JOIN json_each(s.context,'$.document_types') t
      WHERE seen=?) SELECT document_type,disposition AS state,count(*) AS count FROM dispositions
      GROUP BY document_type,disposition ORDER BY document_type,disposition''', [identity])]
    roots = [dict(row) for row in db.execute('''SELECT json_extract(value,'$.archive_state') AS archive_state,
      json_extract(value,'$.publisher_snapshot') AS publisher_snapshot,count(*) AS tracks,
      sum(json_extract(value,'$.missing_resources')) AS missing_resources,
      sum(json_extract(value,'$.unreadable_resources')) AS unreadable_resources,
      sum(json_extract(value,'$.declaration_mismatches')) AS declaration_mismatches
      FROM root_coverage WHERE source_data_id=? GROUP BY 1,2''', [identity])]
    return dict(by_source_kind=counts, by_document_type=material, caption_tracks=roots, **dict(totals),
        caption_completeness='Per-root complete, partial/live and missing-resource facts are retained; a saved track does not prove a complete hearing.',
        speaker_attribution='Literal caption voice labels only; document witness links describe source association.')


def _next_body_query(identity,only_sources=None):
    """Use ordered eligible work, or source-PK lookups for a bounded pilot set."""
    order="json_extract(b.target,'$.unit_kind')='playlist' DESC,b.body_key"
    if only_sources:
        # CROSS JOIN fixes the small source-key set as the driving input. A shared
        # body may occur more than once; LIMIT 1 still selects the same body key.
        values=','.join('(?)' for _ in only_sources)
        sql=f"""WITH selected_keys(source_key) AS (VALUES {values})
          SELECT b.* FROM selected_keys k CROSS JOIN sources s CROSS JOIN bodies b
          WHERE s.source_key=k.source_key AND s.seen=? AND s.reason IS NULL
            AND b.body_key=s.body_key AND b.state='pending' ORDER BY {order} LIMIT 1"""
        return sql,[*only_sources,identity]
    return f"""SELECT b.* FROM bodies b WHERE b.state='pending' AND EXISTS
      (SELECT 1 FROM sources s WHERE s.body_key=b.body_key AND s.seen=? AND s.reason IS NULL)
      ORDER BY {order} LIMIT 1""",[identity]


def _exclude_ineligible_pending(db,identity):
    # Membership is reversible. Root qualification reenrolls newly eligible child
    # keys; source pending/unavailable reasons continue to govern completion.
    with db:
        db.execute("""UPDATE bodies SET state='excluded: no eligible source'
          WHERE state='pending' AND NOT EXISTS (SELECT 1 FROM sources s
          WHERE s.body_key=bodies.body_key AND s.seen=? AND s.reason IS NULL)""",[identity])


def qualify_caption_sources(db, identity, root_key=None):
    """Judge each declared relationship separately from reusable body extraction."""
    conditions="kind='caption' AND seen=? AND json_extract(context,'$.resource_ordinal')=0"
    arguments=[identity]
    if root_key is not None:
        conditions+=" AND json_extract(context,'$.root_key')=?";arguments.append(root_key)
    roots=db.execute('SELECT source_key,context,reason,body_key FROM sources WHERE '+conditions,arguments).fetchall()
    done=set();affected_bodies=set()
    waiting_states={'pending','retryable','refused','excluded: no eligible source'}
    with db:
      for source in roots:
        context = json.loads(source['context']); source_id = context['reference']['source_id']
        if source_id in done:
            continue
        done.add(source_id)
        root = db.execute('SELECT state,reason,extra,units FROM bodies WHERE body_key=?', [context['root_key']]).fetchone()
        extra = json.loads(root['extra'] or '{}') if root else {}
        result = dict(archive_state='unavailable', publisher_snapshot=extra.get('publisher_snapshot', 'unknown'),
            declared_resources=0, retained_resources=0, missing_resources=0, unreadable_resources=0,
            pending_resources=0, declaration_mismatches=0, indexed_cues=0, endlist=extra.get('endlist'),
            root_state=root['state'] if root else 'unavailable')
        if not context.get('playlist'):
            result['declared_resources'] = 1
            state = root['state'] if root else 'unavailable'
            result['retained_resources'] = int(state in ('indexed', 'empty'))
            result['indexed_cues'] = root['units'] if root else 0
            result['archive_state'] = 'complete_retained_track' if state in ('indexed','empty') else ('pending' if state in waiting_states else 'unavailable')
            result['unreadable_resources'] = int(state == 'unreadable')
            result['pending_resources'] = int(state in waiting_states)
        else:
            uris = extra.get('uris', [])
            result['declared_resources'] = len(uris)
            rows = db.execute('''SELECT s.source_key,s.context,s.reason,s.body_key,b.state,b.units FROM sources s LEFT JOIN bodies b USING(body_key)
              WHERE s.seen=? AND json_extract(s.context,'$.reference.source_id')=? AND json_extract(s.context,'$.resource_ordinal')>0''', [identity, source_id]).fetchall()
            ordinals = {json.loads(row['context'])['resource_ordinal'] for row in rows}
            valid_map = bool(root and root['state']=='manifest' and ordinals==set(range(1,len(uris)+1)))
            seen_ordinals = set()
            for row in rows:
                child = json.loads(row['context']); ordinal = child['resource_ordinal']
                if row['body_key'] is not None:affected_bodies.add(row['body_key'])
                original_missing = row['reason'] == 'unavailable: caption resource not retained'
                reason = row['reason'] if original_missing else None
                if not original_missing:
                    if root is None or root['state'] in waiting_states:
                        reason = 'pending: playlist root verification'
                    elif root['state'] != 'manifest':
                        reason = 'unavailable: verified playlist root is unsupported or unreadable'
                    elif not valid_map or not 1<=ordinal<=len(uris) or uris[ordinal-1]!=child.get('declared_uri'):
                        reason = 'unavailable: verified playlist declaration mismatch'
                db.execute('UPDATE sources SET reason=? WHERE source_key=? AND reason IS NOT ?', [reason,row['source_key'],reason])
                if ordinal in seen_ordinals:
                    continue
                seen_ordinals.add(ordinal)
                result['missing_resources'] += int(original_missing)
                result['declaration_mismatches'] += int(reason is not None and 'mismatch' in reason)
                result['pending_resources'] += int((reason or '').startswith('pending:') or (reason is None and row['state'] in waiting_states))
                result['unreadable_resources'] += int(row['state']=='unreadable')
                result['retained_resources'] += int(reason is None and row['state'] in ('indexed','empty'))
                if reason is None and row['state']=='indexed':
                    result['indexed_cues'] += row['units']
            if root and root['state']=='manifest' and valid_map:
                if result['missing_resources'] or result['unreadable_resources'] or result['declaration_mismatches']:
                    result['archive_state']='partial'
                elif result['pending_resources']:
                    result['archive_state']='pending'
                else:
                    result['archive_state']='complete_retained_resources'
            elif root and root['state'] in waiting_states and not source['reason']:
                result['archive_state']='pending'
            db.execute('INSERT OR REPLACE INTO root_coverage VALUES(?,?,?)', [source_id,identity,encoded(result).decode()])
            continue
        db.execute('INSERT OR REPLACE INTO root_coverage VALUES(?,?,?)', [source_id,identity,encoded(result).decode()])
      if root_key is None:
          db.execute("""UPDATE bodies SET state='pending' WHERE state='excluded: no eligible source'
            AND EXISTS (SELECT 1 FROM sources s WHERE s.body_key=bodies.body_key AND s.seen=? AND s.reason IS NULL)""",[identity])
      else:
          db.executemany("""UPDATE bodies SET state='pending' WHERE body_key=? AND state='excluded: no eligible source'
            AND EXISTS (SELECT 1 FROM sources s WHERE s.body_key=bodies.body_key AND s.seen=? AND s.reason IS NULL)""",
            [(body,identity) for body in affected_bodies])


def _prune_retired_text(db, identity):
    """The old immutable release owns rollback; work retains only this complete reference set."""
    while rows := db.execute('''SELECT p.id,p.text_z FROM passages p WHERE p.body_key NOT IN
      (SELECT body_key FROM sources WHERE seen=? AND body_key IS NOT NULL) LIMIT 128''', [identity]).fetchall():
        from .text_index import inflate
        with db:
            for row in rows:
                db.execute("INSERT INTO search(search,rowid,text) VALUES('delete',?,?)", [row['id'], inflate(row['text_z'])])
                db.execute('DELETE FROM passages WHERE id=?', [row['id']])
    with db:
        db.execute('DELETE FROM page_spans WHERE body_key NOT IN (SELECT body_key FROM sources WHERE seen=? AND body_key IS NOT NULL)',[identity])
        db.execute('DELETE FROM bodies WHERE body_key NOT IN (SELECT body_key FROM sources WHERE seen=? AND body_key IS NOT NULL)', [identity])
        db.execute('DELETE FROM body_metrics WHERE body_key NOT IN (SELECT body_key FROM bodies)')
        db.execute('DELETE FROM body_failures WHERE body_key NOT IN (SELECT body_key FROM bodies)')
        db.execute('DELETE FROM root_coverage WHERE source_data_id<>?',[identity])
        db.execute('DELETE FROM changes WHERE source_data_id<>?', [identity])
        db.execute('DELETE FROM sources WHERE seen<>?',[identity])
    db.execute('PRAGMA incremental_vacuum')


def _restore_historical(db,body_key,receipts,work):
    from .index_storage import verify_historical
    from .text_index import inflate
    for receipt in receipts:
        path=Path(receipt['path'])
        if path.is_symlink() or not path.exists():
            raise ExplorerError('Historical immutable reading is missing; preserve its receipt')
        with closing(connect(path,readonly=True)) as previous:
            body=previous.execute("SELECT * FROM bodies WHERE body_key=? AND state IN ('indexed','empty','manifest')",[body_key]).fetchone()
            if body is None:
                continue
            verify_historical(work,receipt)
            with db:
                rows=previous.execute('SELECT ordinal,location,text_z,speakers FROM passages WHERE body_key=? ORDER BY ordinal',[body_key])
                for row in rows:
                    cursor=db.execute('INSERT INTO passages(body_key,ordinal,location,text_z,speakers) VALUES(?,?,?,?,?)',
                        [body_key,row['ordinal'],row['location'],row['text_z'],row['speakers']])
                    db.execute('INSERT INTO search(rowid,text) VALUES(?,?)',[cursor.lastrowid,inflate(row['text_z'])])
                for row in previous.execute('SELECT page,chars FROM page_spans WHERE body_key=?',[body_key]):
                    db.execute('INSERT INTO page_spans VALUES(?,?,?)',[body_key,row['page'],row['chars']])
                db.execute('UPDATE bodies SET state=?,reason=NULL,chars=?,units=?,extra=? WHERE body_key=?',
                    [body['state'],body['chars'],body['units'],body['extra'],body_key])
            return True
    return False


def build(selection, work, output=None, *, expected_definition=None, limit=None, timeout=120, memory_mb=768,
          max_work_bytes=16 << 30, retry_errors=False, only_sources=None, min_free_bytes=15 << 30,snapshot_mode='copy',large_memory_mb=4096):
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ExplorerError('Index pilot limit must be a positive integer')
    if not 1 <= timeout <= 600 or not 128 <= memory_mb <= 16384 or max_work_bytes < (512 << 20):
        raise ExplorerError('Index resource policy requires timeout 1..600s, memory 128..16384 MiB and at least 512 MiB work')
    definition = extraction_definition()
    if expected_definition is not None and expected_definition not in (definition['sha256'],definition['policy_sha256']):
        raise ExplorerError('Text extraction definition differs from the pinned app, dependencies or tools; no payloads opened')
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    if work.is_symlink():
        raise ExplorerError('Index work directory is a symlink')
    with (work / 'writer.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ExplorerError('Another index writer owns this work directory') from None
        if (work / 'work.sqlite').is_symlink():
            raise ExplorerError('Index work database is a symlink')
        from . import index_storage
        if snapshot_mode not in ('copy','freeze'):
            raise ExplorerError('Unknown index snapshot mode')
        if snapshot_mode=='freeze':
            index_storage.preflight(work)
            index_storage.recover(work)
        if output is not None and Path(output).exists():
            if Path(output).is_symlink():
                raise ExplorerError('Immutable index output is a symlink')
            with closing(connect(output,readonly=True)) as accepted:
                saved=metadata(accepted,'artifact')
            if saved and saved.get('state')=='complete' and saved.get('source_data_id')==source_data_id(selection['manifest']) and saved.get('definition',{}).get('sha256')==definition['sha256']:
                return dict(saved,reused_snapshot=True,artifact=index_storage.output_identity(work,output))
            raise ExplorerError('Existing immutable index output identifies another preparation')
        index_storage.prepare_work(work,mode=snapshot_mode)
        shutil.rmtree(work/'active-pdf',ignore_errors=True)
        history=index_storage.historical(work)
        with closing(connect(work / 'work.sqlite', timeout=3600*24*365)) as db:
            metadata_bytes = sum(path.stat().st_size for path in (work / 'metadata').rglob('*') if path.is_file()) if (work / 'metadata').exists() else 0
            # Admit DB+journal or DB+snapshot, metadata cache, and one bounded text completion.
            db_budget = (max_work_bytes - metadata_bytes - (256 << 20)) // 2
            if db_budget < 1 << 20:
                raise ExplorerError('Index work budget cannot cover metadata, text completion and snapshot coexistence')
            page_size = db.execute('PRAGMA page_size').fetchone()[0]
            db.execute(f'PRAGMA max_page_count={db_budget // page_size}')
            initialize(db,definition['layout_definition'])
            identity = seed(db, selection, definition['body_definitions'],definition['association_definition'])
            with db:
                db.execute("UPDATE bodies SET state='pending' WHERE state IN ('retryable','refused')")
                policy=dict(timeout=timeout,memory_mb=memory_mb,large_memory_mb=large_memory_mb)
                if metadata(db,'resource_policy') not in (None,policy):
                    db.execute("UPDATE bodies SET state='pending' WHERE state='unreadable'")
                metadata(db,'resource_policy',policy)
            qualify_caption_sources(db, identity)
            if retry_errors:
                with db:
                    db.execute("UPDATE bodies SET state='pending' WHERE state='unreadable' AND body_key IN (SELECT body_key FROM sources WHERE seen=?)", [identity])
            processed = reused = restored = 0
            _exclude_ineligible_pending(db,identity)
            while limit is None or processed < limit:
                row=db.execute(*_next_body_query(identity,only_sources)).fetchone()
                if row is None:
                    break
                target = json.loads(row['target'])
                if _restore_historical(db,row['body_key'],history,work):
                    restored+=1;processed+=1
                    if target['unit_kind']=='playlist':
                        qualify_caption_sources(db,identity,row['body_key'])
                    continue
                body_started = time.monotonic()
                prior_bytes = (work / 'work.sqlite').stat().st_size
                reason = None
                size = target.get('saved_bytes')
                child_memory=large_memory_mb if target['format']=='pdf' and (type(size) is not int or size>64<<20) else memory_mb
                # Freeze links the closed inode; only copy mode needs another full
                # DB here. Both modes reserve one bounded source spool and text/SQL
                # mutation headroom. The outer watchdog enforces the live disk floor.
                mutation_reserve=(2<<30 if target['format']=='pdf' else 64<<20)+(1<<30)
                required_free=min_free_bytes+mutation_reserve+(prior_bytes if snapshot_mode=='copy' else 0)
                if (work / 'work.sqlite').stat().st_size > db_budget or shutil.disk_usage(work).free < required_free:
                    raise ExplorerError('Text index work disk budget reached; durable completed bodies remain reusable')
                completed = work / (row['body_key'] + '.pages.gz')
                if completed.is_symlink():
                    raise ExplorerError('Retained extraction completion is a symlink')
                request = work / 'active-body.json'
                if reason is None:
                    cached=False
                    try:
                        if target['format']!='pdf' and type(size) is int and size>64<<20:
                            raise IndexJobRefusal('Non-PDF body exceeds the configured complete-reader limit; publication remains pending')
                        cached = completed.exists()
                        if cached:
                            reused += 1
                        else:
                            atomic_json(request, dict(target, extraction_definition=definition['sha256'],min_free_bytes=min_free_bytes))
                            temporary = completed.with_suffix('.partial')
                            command = [sys.executable, '-m', 'congressional_explorer_mcp.index_cli', 'extract-one',
                                '--target', str(request), '--output', str(temporary), '--timeout', str(timeout), '--memory-mb', str(child_memory)]
                            for attempt in range(3):
                                result,child_peak = _run_child(command,timeout=timeout+5,memory_mb=child_memory)
                                if not result.returncode:
                                    break
                                try:
                                    outcome = json.loads(result.stderr)
                                except ValueError:
                                    outcome = dict(message=(result.stderr or 'Extraction child exited without a completion')[-1500:])
                                atomic_json(work/('failure-'+row['body_key']+'.json'),dict(outcome,body_key=row['body_key'],attempt=attempt+1))
                                if outcome.get('retryable'):
                                    if attempt < 2:
                                        time.sleep(.25 * 2**attempt)
                                        continue
                                    raise RetryableBodyRead(outcome['message'])
                                if outcome.get('refusal'):
                                    raise IndexJobRefusal(outcome['message'])
                                if 'MemoryError' in outcome['message'] or result.returncode<0:
                                    raise IndexJobRefusal(outcome['message'])
                                raise ExplorerError(outcome['message'])
                            with temporary.open('rb') as source:
                                os.fsync(source.fileno())
                            os.replace(temporary, completed)
                        completion_bytes = completed.stat().st_size
                        _consume(db, row['body_key'], completed)
                        if not cached:
                            with db:
                                extra=json.loads(db.execute('SELECT extra FROM bodies WHERE body_key=?',[row['body_key']]).fetchone()[0])
                                extra['process_peak_rss_bytes']=child_peak
                                db.execute('UPDATE bodies SET extra=? WHERE body_key=?',[encoded(extra).decode(),row['body_key']])
                        with db:
                            db.execute('INSERT OR REPLACE INTO body_metrics VALUES(?,?,?,?,?)',
                                [row['body_key'], time.monotonic()-body_started, size, completion_bytes,
                                 (work / 'work.sqlite').stat().st_size-prior_bytes])
                        completed.unlink()
                    except (ExplorerError, OSError, ValueError, subprocess.SubprocessError) as error:
                        if cached:
                            raise ExplorerError('Retained extraction completion is corrupt; preserve it for diagnosis') from error
                        if isinstance(error, (RetryableBodyRead, subprocess.TimeoutExpired,IndexJobRefusal)):
                            category='refused' if isinstance(error,IndexJobRefusal) else 'retryable'
                            with db:
                                db.execute("UPDATE bodies SET state=?,reason=? WHERE body_key=?", [category,str(error)[-1500:],row['body_key']])
                                db.execute('INSERT INTO body_failures(body_key,definition,category,reason) VALUES(?,?,?,?)',
                                    [row['body_key'],definition['sha256'],category,str(error)[-1500:]])
                                metadata(db,'artifact',dict(state='partial',source_data_id=identity,version=INDEX_VERSION))
                            atomic_json(work/'report.json',dict(state='partial',source_data_id=identity,last_failure=dict(body_key=row['body_key'],category=category,reason=str(error)[-1500:])))
                            raise ExplorerError(f'Archived body read is still {category}; completed work is retained and publication remains pending. Resume the same index command.') from error
                        reason = 'unreadable: ' + str(error)[-1500:]
                    finally:
                        shutil.rmtree(work/'active-pdf',ignore_errors=True)
                        request.unlink(missing_ok=True)
                        completed.with_suffix('.partial').unlink(missing_ok=True)
                if reason:
                    with db:
                        db.execute('UPDATE bodies SET state=?,reason=? WHERE body_key=?', ['unreadable' if reason.startswith('unreadable:') else reason, reason, row['body_key']])
                        db.execute('INSERT INTO body_failures(body_key,definition,category,reason) VALUES(?,?,?,?)',
                            [row['body_key'],definition['sha256'],'unreadable' if reason.startswith('unreadable:') else 'excluded',reason])
                    completed.unlink(missing_ok=True)
                processed += 1
                if target['unit_kind']=='playlist':
                    qualify_caption_sources(db,identity,row['body_key'])
            qualify_caption_sources(db, identity)
            pending = db.execute("SELECT count(*) FROM bodies WHERE state IN ('pending','retryable','refused') AND body_key IN (SELECT body_key FROM sources WHERE seen=? AND reason IS NULL)", [identity]).fetchone()[0]
            pending += db.execute("SELECT count(*) FROM sources WHERE seen=? AND reason LIKE 'pending:%'", [identity]).fetchone()[0]
            if not pending:
                with db:
                    db.execute("UPDATE bodies SET state='excluded: no eligible source' WHERE state='pending'")
                _prune_retired_text(db, identity)
            report = dict(version=INDEX_VERSION, source_data_id=identity, definition=definition,
                state='partial' if pending else 'complete', pending_bodies=pending, processed_bodies=processed,
                recovered_completions=reused, coverage=coverage(db, identity))
            report['restored_historical_bodies']=restored
            report['reference_changes'] = {row[0]: row[1] for row in db.execute('SELECT disposition,count(*) FROM changes WHERE source_data_id=? GROUP BY disposition', [identity])}
            with db:
                metadata(db, 'artifact', report)
            if output is not None:
                if pending:
                    raise ExplorerError('A partial indexing run cannot publish a search artifact; continue the retained work')
                output = Path(output)
                if output.exists():
                    raise ExplorerError('Text index output already exists; preserve immutable artifacts')
                # Freeze closes and pins the accepted DB, then links it without a bulk copy.
                if snapshot_mode=='freeze':
                    db.execute('PRAGMA journal_mode=DELETE')
                    db.close()
                    report['artifact']=index_storage.freeze(work,output,report)
                    atomic_json(work/'report.json',report)
                    return report
                # Copy mode requires separately admitted coexistence capacity.
                # No raw archived payloads are copied. Old/new artifact coexistence is admitted here.
                required = (work / 'work.sqlite').stat().st_size + (256 << 20)
                temporary = output.with_suffix('.partial')
                if temporary.is_symlink():
                    raise ExplorerError('Partial index snapshot is a symlink')
                temporary.unlink(missing_ok=True)
                if shutil.disk_usage(output.parent).free < required + min_free_bytes:
                    raise ExplorerError('Insufficient disk for immutable text-index snapshot beside retained work')
                # VACUUM INTO is SQLite's supported consistent compact snapshot.
                db.execute('VACUUM INTO ?', [str(temporary)])
                with temporary.open('rb') as source:
                    os.fsync(source.fileno())
                os.replace(temporary, output)
                output.chmod(0o444)
                identity_facts=index_storage.facts(output)
                index_storage.register_copy(work,output,report,identity_facts)
                report['artifact']=dict(identity_facts,path=str(output),stamp=index_storage.stamp(output))
            atomic_json(work / 'report.json', report)
            return report
