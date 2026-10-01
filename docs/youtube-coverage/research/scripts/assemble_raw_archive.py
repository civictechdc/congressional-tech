"""Assemble a local R2-shaped archive from explicit retained-file manifests.

No fetching, uploads, snapshots, reader cutover or original-file deletion. Exact
body bytes are addressed by their uncompressed SHA-256. Original JSON values
remain restorable from receipts; JSON formatting is not an upstream observation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
import ctypes
import ctypes.util
from datetime import date
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
from urllib.parse import urlsplit

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.bundles import restore, separate
from congress_api.retention.raw_archive import CAPTURE_SCHEMA as SCHEMA
from congress_api.parsers.source_family import family

FAMILIES = ('congress/meetings', 'congress/committees', 'house/meeting-xml',
            'house/witness-xml', 'house/pages', 'senate/pages', 'senate/listings',
            'senate/players', 'senate/captions', 'govinfo/mods', 'govinfo/mets',
            'govinfo/premis', 'govinfo/transcript-html', 'youtube/api',
            'youtube/watch-pages', 'youtube/captions', 'documents',
            'external/legislators', 'external/wayback', 'external/provider-responses')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def capture_date(values):
    """Unknown or mixed observation dates are never replaced by migration dates."""
    dates = set()
    for value in values:
        if isinstance(value, str) and re.match(r'^\d{4}-\d\d-\d\d(?:T|$)', value):
            try: dates.add(date.fromisoformat(value[:10]).isoformat())
            except ValueError: pass
    return next(iter(dates)) if len(dates) == 1 else 'mixed-dates' if dates else 'undated'


def record_family(value):
    """Recognize native API JSON when its saved file has no request URL."""
    if not isinstance(value,dict):return None
    if 'eventId' in value and 'congress' in value:return 'congress/meetings'
    if 'committeeMeeting' in value or 'committeeMeetings' in value:return 'congress/meetings'
    if 'request' in value and ('committee' in value or 'committees' in value):return 'congress/committees'
    if 'packageId' in value and 'collectionCode' in value:return 'documents'
    return None


def file_hash(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def local_path(cache, value):
    if value.startswith('/'):return value
    return str(cache.parent/value) if value.startswith(cache.name+'/') else str(cache/value)


def independent_copy(source, destination, min_free):
    """Use APFS copy-on-write when available; never hardlink to the source."""
    if shutil.disk_usage(destination.parent).free < min_free:
        raise OSError('Minimum free disk space reached')
    if os.uname().sysname == 'Darwin':
        lib = ctypes.CDLL(ctypes.util.find_library('c'), use_errno=True)
        clone = lib.clonefile
        clone.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int)
        clone.restype = ctypes.c_int
        if clone(os.fsencode(source), os.fsencode(destination), 0) == 0:
            return 'copy-on-write'
        code = ctypes.get_errno()
        if code not in (18, 45):  # EXDEV, ENOTSUP: only these allow ordinary copy fallback.
            raise OSError(code, os.strerror(code))
    if shutil.disk_usage(destination.parent).free - source.stat().st_size < min_free:
        raise OSError('Copy would cross minimum free disk space')
    shutil.copyfile(source, destination)
    return 'copy'


class Bodies:
    def __init__(self, root, cache, minimum):
        self.root, self.cache, self.minimum = root, cache, int(minimum * 2**30)
        self.by_hash, self.by_file = {}, {}
        self.locks = [threading.Lock() for _ in range(256)]

    def key(self, digest): return f'bodies/sha256/{digest[:2]}/{digest}.gz'

    def adopt(self, item):
        source = Path(item['path'])
        before = source.stat()
        if (before.st_size, before.st_mtime_ns) != (item['size'], item['mtime_ns']):
            raise ValueError('Input changed since inventory')
        sha, size = hashlib.sha256(), 0
        opener = gzip.open if item['gzip'] else open
        with opener(source, 'rb') as f:
            for block in iter(lambda: f.read(1024*1024), b''): sha.update(block); size += len(block)
        digest = sha.hexdigest()
        if item.get('expected_sha256') and item['expected_sha256'] != digest:
            raise ValueError('Body digest differs from expected source digest')
        key = self.key(digest)
        with self.locks[int(digest[:2],16)]:
            if digest not in self.by_hash:
                target = self.root / key
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    temporary = target.with_name(f'.{digest}.{threading.get_ident()}.tmp')
                    try:
                        if item['gzip']:
                            independent_copy(source, temporary, self.minimum)
                            if file_hash(temporary) != file_hash(source): raise ValueError('Clone byte mismatch')
                        else:
                            if shutil.disk_usage(self.root).free < self.minimum: raise OSError('Minimum free disk space reached')
                            with source.open('rb') as incoming, temporary.open('wb') as compressed, gzip.GzipFile(filename='', mode='wb', fileobj=compressed, compresslevel=1, mtime=0) as out:
                                shutil.copyfileobj(incoming,out,1024*1024)
                        temporary.replace(target)
                    finally: temporary.unlink(missing_ok=True)
                # Independently validate the persisted bytes, including pre-existing targets.
                check, length = hashlib.sha256(), 0
                with gzip.open(target,'rb') as f:
                    for block in iter(lambda:f.read(1024*1024),b''):check.update(block);length+=len(block)
                if check.hexdigest()!=digest or length!=size:raise ValueError('Persisted body integrity failure')
                self.by_hash[digest] = dict(body_key=key,sha256=digest,bytes=size,
                    stored_sha256=file_hash(target),stored_bytes=target.stat().st_size)
        after = source.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('Source changed during archival')
        result = dict(self.by_hash[digest], source_file=str(source.relative_to(self.cache)),
                      family_hint=item.get('family_hint'), source_sha256=file_hash(source))
        self.by_file[str(source)] = result
        return result

    def put(self, data):
        digest = hashlib.sha256(data).hexdigest();key=self.key(digest)
        with self.locks[int(digest[:2],16)]:
            if digest in self.by_hash:return key
            target=self.root/key;target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():
                if shutil.disk_usage(self.root).free<len(data)+self.minimum:raise OSError('Minimum free disk space reached')
                temporary=target.with_name(f'.{digest}.{threading.get_ident()}.tmp')
                try:
                    temporary.write_bytes(gzip.compress(data,compresslevel=1,mtime=0));temporary.replace(target)
                finally:temporary.unlink(missing_ok=True)
            if gzip.decompress(target.read_bytes())!=data:raise ValueError('Persisted body integrity failure')
            self.by_hash[digest]=dict(body_key=key,sha256=digest,bytes=len(data),stored_sha256=file_hash(target),stored_bytes=target.stat().st_size)
        return key

    def get(self,key):return gzip.decompress((self.root/key).read_bytes())


class Receipts:
    def __init__(self, root, admin, run_id):
        self.root,self.admin,self.run_id=root,admin,run_id
        self.handles={};self.lock=threading.Lock();self.batch=[];self.rows=0;self.counts=Counter()
        self.writer=pq.ParquetWriter(admin/'captures.pending.parquet',SCHEMA,compression='zstd')

    def emit(self, owner, day, receipt, captures):
        if owner not in FAMILIES:raise ValueError(f'Unknown source family: {owner}')
        key=f'receipts/{owner}/{day}/{self.run_id}.jsonl.gz'
        with self.lock:
            if key not in self.handles:
                path=self.root/key;path.parent.mkdir(parents=True,exist_ok=True)
                if path.exists():raise ValueError('Receipt run already exists; use a new run id')
                self.handles[key]=[gzip.open(path,'wt',encoding='utf-8'),0]
            handle=self.handles[key];handle[0].write(encoded(receipt)+'\n');handle[1]+=1
            for cap in captures or [dict(family=owner,reference_kind='metadata',fidelity='saved-record')]:
                row={k:cap.get(k) for k in SCHEMA.names}
                row.update(family=cap.get('family') or owner,capture_date=cap.get('capture_date') or day,
                           source_file=receipt['source_file'],source_line=receipt.get('source_line'),
                           receipt_key=key,receipt_line=handle[1])
                self.batch.append(row);self.rows+=1;self.counts[row['family']]+=1
            if len(self.batch)>=8192:self.flush()

    def flush(self):
        if self.batch:self.writer.write_table(pa.Table.from_pylist(self.batch,schema=SCHEMA));self.batch.clear()

    def close(self):
        self.flush();self.writer.close()
        for handle,_ in self.handles.values():handle.close()


def bounded_map(pool, fn, values, window):
    """Keep the migration queue bounded even for hundreds of thousands of files."""
    values=iter(values);pending=deque()
    for _ in range(window):
        try:pending.append(pool.submit(fn,next(values)))
        except StopIteration:break
    while pending:
        yield pending.popleft().result()
        try:pending.append(pool.submit(fn,next(values)))
        except StopIteration:pass


def file_references(value, source, cache, aliases, bodies):
    found=[]
    def walk(node,pointer,context):
        if isinstance(node,list):
            for i,v in enumerate(node):walk(v,pointer+[i],context)
        if not isinstance(node,dict):return
        ctx=dict(context)
        for k in ('final_url','url','_url','requested_url'):
            if isinstance(node.get(k),str):ctx['context_url']=node[k]
        for k in ('retrieved_at','observed_at','completed_at','captured_at'):
            if isinstance(node.get(k),str):ctx['retrieved_at']=node[k];break
        for k in ('http_status','status_code','status'):
            if isinstance(node.get(k),int):ctx['http_status']=node[k];break
        for k in ('media_type','content_type'):
            if isinstance(node.get(k),str):ctx['media_type']=node[k];break
        # These journals retain exact response bytes by digest rather than path.
        # Do not interpret arbitrary hashes in analysis output as captures.
        digest_only = node.get('event') == 'capture' and isinstance(node.get('byte_size'),int)
        for k,v in node.items():
            is_digest = digest_only and k == 'sha256'
            if isinstance(v,str) and v and (is_digest or k in ('raw_path','raw_file','body_path') or k=='path' and isinstance(node.get('sha256'),str) and isinstance(node.get('bytes'),int)):
                p='' if is_digest else aliases.get(v,v)
                if p:p=local_path(cache,p)
                info=bodies.by_file.get(p)
                expected=node.get('raw_sha256' if k=='raw_file' else 'sha256')
                if isinstance(expected,str):expected=expected.removeprefix('sha256:')
                if expected and expected in bodies.by_hash:
                    info=bodies.by_hash[expected];resolution='digest_verified'
                elif info and expected and info.get('source_sha256')==expected:
                    resolution='stored_file_digest_verified'
                elif info and expected and info['sha256']!=expected:
                    info=None;resolution='historical_digest_unavailable'
                else:resolution='path_verified' if info else 'not_retained'
                cap=dict(reference_kind='file',original_path=None if is_digest else v,pointer_json=encoded(pointer+[k]),
                         fidelity='retained-file',resolution=resolution,**ctx)
                if ctx.get('context_url'):cap['family']=family(source,ctx['context_url'],pointer+[k])
                elif node.get('kind')=='original_html':cap['family']='govinfo/transcript-html' if str(node.get('package_id','')).startswith('CHRG-') else 'documents'
                else:cap['family']=family(p,pointer=pointer+[k]) or family(source,pointer=pointer+[k])
                if info:cap.update({k:info[k] for k in ('body_key','sha256','bytes','stored_sha256','stored_bytes')})
                found.append(cap)
            if k not in ('body','text','html','raw_html','raw_xml','browserHtml','httpResponseBody') and isinstance(v,(dict,list)):
                walk(v,pointer+[k],ctx)
    walk(value,[],{})
    return found

def run(body_manifest, record_manifest, aliases_path, cache, output, admin, run_id, workers=8, min_free_gib=20, prior_archive=None):
    cache=cache.resolve();output=output.resolve();admin=admin.resolve()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',run_id):raise ValueError('Invalid run id')
    output.mkdir(parents=True,exist_ok=True);admin.mkdir(parents=True,exist_ok=True)
    if (output/'snapshots').exists():raise ValueError('Unexpected snapshots directory')
    bodies=Bodies(output,cache,min_free_gib);started=time.monotonic();counts=Counter();errors=[]
    items=[json.loads(l) for l in body_manifest.open()]
    def adopt(item):
        try:return dict(status='verified',**bodies.adopt(item))
        except Exception as e:return dict(status='error',source_file=item['path'],error_type=type(e).__name__,error=str(e))
    with (admin/'body-results.jsonl').open('w') as journal,ThreadPoolExecutor(max_workers=workers) as pool:
        for r in bounded_map(pool,adopt,items,workers*8):
            journal.write(encoded(r)+'\n');counts['body_files']+=1
            if r['status']=='error':errors.append(r)
            if counts['body_files']%10000==0:
                journal.flush();print(encoded(dict(stage='bodies',**counts,total=len(items),distinct=len(bodies.by_hash),elapsed=round(time.monotonic()-started))),flush=True)
    if errors:
        (admin/'errors.json').write_text(json.dumps(errors,indent=2)+'\n')
        raise ValueError(f'{len(errors)} body imports failed; index not published')
    aliases=json.loads(aliases_path.read_text()) if aliases_path else {}
    receipts=Receipts(output,admin,run_id);used=set();body_families=defaultdict(set);file_families=defaultdict(set);unclassified=[];unresolved=[];lock=threading.Lock()
    def records(item):
        p=Path(item['path']);source=str(p.relative_to(cache));before=p.stat();local_counts=Counter()
        if (before.st_size,before.st_mtime_ns)!=(item['size'],item['mtime_ns']):raise ValueError(f'Input changed: {source}')
        opener=gzip.open if p.name.endswith('.gz') else open
        with opener(p,'rt',encoding='utf-8',newline='') as f:
            lines=f if p.name.endswith(('.jsonl','.jsonl.gz')) else [f.read()]
            for n,line in enumerate(lines,1):
                if not line.strip():continue
                try:original=json.loads(line)
                except ValueError as e:raise ValueError(f'Invalid JSON in {source}, record {n}: {e}') from e
                record,caps=separate(original,bodies.put)
                refs=file_references(original,source,cache,aliases,bodies)
                indexed=[]
                for c in caps:
                    fam=family(source,c.get('context_url',''),c['pointer'],c.get('media_type',''))
                    indexed.append(dict(c,**{k:bodies.by_hash[c['sha256']][k] for k in ('stored_sha256','stored_bytes')},
                        family=fam,reference_kind='embedded',pointer_json=encoded(c['pointer']),
                        http_status=c.get('http_status',c.get('status_code')),resolution='digest_verified'))
                indexed+=refs
                known=[c['family'] for c in indexed if c.get('family')]
                context_url=(original.get('_url') or original.get('url') or original.get('requested_url') or '') if isinstance(original,dict) else ''
                owner=Counter(known).most_common(1)[0][0] if known else item.get('family_hint') or family(source,context_url) or record_family(original)
                if not owner:
                    with lock:unclassified.append(dict(source_file=source,source_line=n if p.name.endswith(('.jsonl','.jsonl.gz')) else None,body_captures=len(caps),file_references=len(refs)))
                    local_counts['unclassified_records']+=1;continue
                dates=[c.get('retrieved_at') or c.get('captured_at') for c in indexed]
                if isinstance(original,dict):dates += [original.get(k) for k in ('retrieved_at','_retrieved_at','observed_at','completed_at')]
                day=capture_date(dates)
                for c in indexed:
                    c['family']=c.get('family') or owner;c['capture_date']=capture_date([c.get('retrieved_at') or c.get('captured_at')])
                result=dict(source_file=source,source_line=n if p.name.endswith(('.jsonl','.jsonl.gz')) else None,record=record,captures=caps,file_references=refs)
                # Validate serialization and actual canonical body readback.
                serialized=json.loads(encoded(result))
                if restore(serialized['record'],serialized['captures'],bodies.get)!=original:raise ValueError('Receipt cannot restore original JSON')
                receipts.emit(owner,day,result,indexed)
                with lock:
                    used.update(c['body_key'] for c in indexed if c.get('body_key'))
                    for c in indexed:
                        if c.get('body_key') and c.get('family'):body_families[c['body_key']].add(c['family'])
                        if c.get('original_path') and c.get('family'):
                            path=aliases.get(c['original_path'],c['original_path'])
                            path=local_path(cache,path)
                            file_families[path].add(c['family'])
                    unresolved.extend(dict(source_file=source,source_line=result['source_line'],**r) for r in refs if not r.get('body_key'))
                local_counts['records']+=1;local_counts['embedded_captures']+=len(caps);local_counts['file_references']+=len(refs)
        after=p.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError(f'Input changed: {source}')
        return local_counts
    record_items=[json.loads(l) for l in record_manifest.open()]
    try:
        with ThreadPoolExecutor(max_workers=min(workers,4)) as pool:
            for result in bounded_map(pool,records,record_items,32):
                counts.update(result);counts['record_files']+=1
                if counts['record_files']%10000==0:print(encoded(dict(stage='receipts',**counts,elapsed=round(time.monotonic()-started))),flush=True)
        # Retain older embedded observations that differ from today's input files.
        if prior_archive:
            for old_file in sorted((prior_archive/'receipts').glob('*.jsonl.gz')):
                with gzip.open(old_file,'rt') as old_stream:
                    for old_line,line in enumerate(old_stream,1):
                        r=json.loads(line)
                        if not any(c['body_key'] not in used for c in r['captures']):continue
                        source=str(Path(r['source_file']).relative_to(cache))
                        caps=[dict(c, family=family(source,c.get('context_url',''),c['pointer']),
                                  reference_kind='embedded',pointer_json=encoded(c['pointer']),
                                  resolution='digest_verified',**{k:bodies.by_hash[c['sha256']][k] for k in ('stored_sha256','stored_bytes')}) for c in r['captures']]
                        known=[c['family'] for c in caps if c['family']]
                        if not known:continue
                        owner=Counter(known).most_common(1)[0][0]
                        day=capture_date([c.get('retrieved_at') or c.get('captured_at') for c in caps])
                        r.update(source_file=source,prior_receipt_file=str(old_file.relative_to(cache)),prior_receipt_line=old_line)
                        restore(r['record'],r['captures'],bodies.get)
                        receipts.emit(owner,day,r,caps)
                        used.update(c['body_key'] for c in caps)
                        counts['historical_records']+=1
        # Preserve each retained loose file's original path even if another receipt references its body.
        for path,info in bodies.by_file.items():
            source=info['source_file']
            if source.startswith('raw-bundles-20260930/bodies/'):continue
            by_file=file_families[path];by_body=body_families[info['body_key']]
            owner=next(iter(by_file)) if len(by_file)==1 else next(iter(by_body)) if len(by_body)==1 else info.get('family_hint') or family(source)
            if not owner:
                unclassified.append(dict(source_file=source,body_captures=1,file_references=0));continue
            ref=dict(info,family=owner,reference_kind='retained-file',fidelity='retained-file',resolution='digest_verified',original_path=source)
            receipts.emit(owner,'undated',dict(source_file=source,source_line=None,record={'original_path':source},captures=[],file_references=[ref]),[ref]);used.add(info['body_key'])
    finally:receipts.close()
    (admin/'unclassified.json').write_text(json.dumps(unclassified,indent=2)+'\n')
    (admin/'unresolved-references.json').write_text(json.dumps(unresolved,indent=2)+'\n')
    # Failure/reference metadata remains queryable even where historical bytes were never retained.
    orphan=set(b['body_key'] for b in bodies.by_hash.values())-used
    (admin/'unindexed-body-keys.json').write_text(json.dumps(sorted(orphan),indent=2)+'\n')
    summary=dict(completed_at=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),**counts,
        distinct_bodies=len(bodies.by_hash),body_bytes=sum(b['bytes'] for b in bodies.by_hash.values()),stored_body_bytes=sum(b['stored_bytes'] for b in bodies.by_hash.values()),
        receipt_files=len(receipts.handles),index_rows=receipts.rows,by_family=dict(receipts.counts),
        unclassified_records=len(unclassified),unresolved_reference_occurrences=len(unresolved),unindexed_bodies=len(orphan),
        original_files_modified=False,snapshots_created=False,uploaded=False,elapsed_seconds=round(time.monotonic()-started))
    (admin/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(encoded(summary),flush=True)
    if orphan:raise ValueError(f'{len(orphan)} bodies have no source reference; index not published')
    (output/'indexes').mkdir(exist_ok=True)
    temporary=output/'indexes/captures.parquet.tmp'
    shutil.copyfile(admin/'captures.pending.parquet',temporary)
    temporary.replace(output/'indexes/captures.parquet')
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('body-manifest','record-manifest','cache','output','admin'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--prior-archive',type=Path);p.add_argument('--aliases',type=Path);p.add_argument('--run-id',required=True);p.add_argument('--workers',type=int,default=8);p.add_argument('--min-free-gib',type=float,default=20)
    a=p.parse_args()
    if a.workers<1 or a.min_free_gib<0:p.error('Positive workers and nonnegative free-space threshold required')
    run(a.body_manifest,a.record_manifest,a.aliases,a.cache,a.output,a.admin,a.run_id,a.workers,a.min_free_gib,a.prior_archive)
