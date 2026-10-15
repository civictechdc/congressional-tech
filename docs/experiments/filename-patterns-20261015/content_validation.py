"""Freeze a fresh review sample and read exact retained bodies, without publication."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import pyarrow.parquet as pq

from rule_review import DEFAULT_INPUT, ROOT, digest

SEED = 'filename-rule-content-review-20261015-v1'


def prepare(out):
    if out.exists():
        raise FileExistsError('Choose a new output directory for a new sample.')
    review = DEFAULT_INPUT / 'rule-review-v2'
    rules = json.loads((review / 'rule-review.json').read_text())
    shown = {s['filename'] for r in rules for s in r['examples']}
    pools = defaultdict(list)
    selected = {}
    with gzip.open(review / 'document-review.jsonl.gz', 'rt') as f:
        for line in f:
            r = json.loads(line)
            if r['status'] == 'conflict':
                selected[r['document_id']] = dict(r, selection=['conflict'])
            if r['filename'] == '01-27-09_posey_amndt_on_recorded_votes.pdf':
                selected[r['document_id']] = dict(r, selection=['excluded_vote_topic_control'])
            if r['filename'] not in shown and r['status'].startswith('proposed_'):
                for rid in r['rule_ids']:
                    pools[rid].append(r)
    for rule in rules:
        rid = rule['rule_id']
        pool = pools[rid]
        publishers, markers, statuses, filenames = set(), set(), set(), set()
        for _ in range(min(3, len({r['filename'] for r in pool}))):
            def priority(r):
                marker = next(m['marker'] for m in r['matches'] if m['rule_id'] == rid)
                return (urlsplit(r['source_url']).hostname in publishers,
                        r['status'] in statuses, marker in markers,
                        hashlib.sha256((SEED + r['document_id']).encode()).hexdigest())
            r = min((r for r in pool if r['filename'] not in filenames), key=priority)
            filenames.add(r['filename'])
            publishers.add(urlsplit(r['source_url']).hostname)
            statuses.add(r['status'])
            markers.add(next(m['marker'] for m in r['matches'] if m['rule_id'] == rid))
            selected.setdefault(r['document_id'], dict(r, selection=[]))['selection'].append(rid)
    for batch in pq.ParquetFile(DEFAULT_INPUT / 'documents.parquet').iter_batches(columns=['document_id','body_keys','source_urls']):
        for r in batch.to_pylist():
            if r['document_id'] in selected:
                selected[r['document_id']].update(r)
    out.mkdir(parents=True)
    manifest = {'seed': SEED, 'method': 'Three distinct fresh filenames per rule, prioritize publisher/status/marker diversity, deterministic hash tie-break. Add all conflicts and one excluded topic control. Select before checking body availability. Not a random precision benchmark.',
                'input_sha256': {f: digest(review / f) for f in ['document-review.jsonl.gz','rule-review.json']},
                'records': list(selected.values())}
    (out / 'sample.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Frozen {len(selected)} distinct document IDs', flush=True)


def fetch(out, account):
    path = ROOT / 'docs/youtube-coverage/research/scripts/view_document_filenames.py'
    spec = importlib.util.spec_from_file_location('retained_viewer', path)
    viewer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(viewer)
    retained = viewer.RetainedFiles([ROOT / '.cache/congressional-tech-raw', ROOT / '.cache/filename-viewer-r2'], out / 'retained', account)
    # Use the existing local credential only for its intended Cloudflare API.
    if not os.environ.get('CLOUDFLARE_API_TOKEN'):
        for line in (ROOT / '.env').read_text().splitlines():
            if line.startswith('CLOUDFLARE_KEY='):
                os.environ['CLOUDFLARE_API_TOKEN'] = line.split('=',1)[1].strip().strip('\"\x27')
                break
    manifest = json.loads((out / 'sample.json').read_text())
    results = []
    def one(row):
        result = {'document_id': row['document_id'], 'filename': row['filename'], 'bodies': []}
        for key in row['body_keys'] or []:
            entry = {'body_key': key}
            try:
                compressed = retained.compressed(key)
                # Bound decompression independently of the compressed-object bound.
                import io
                with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as f:
                    body = f.read(64 * 1024**2 + 1)
                if len(body) > 64 * 1024**2:
                    raise ValueError('Decompressed body exceeds 64 MiB limit')
                sha = hashlib.sha256(body).hexdigest()
                if sha != Path(key).name.removesuffix('.gz'):
                    raise ValueError('Retained content digest mismatch')
                entry.update(sha256=sha, bytes=len(body))
                if not body.startswith(b'%PDF-'):
                    entry['status'] = 'not_pdf'
                else:
                    target = out / 'pdf' / (sha + '.pdf')
                    target.parent.mkdir(exist_ok=True)
                    target.write_bytes(body)
                    info = subprocess.run(['pdfinfo',str(target)],capture_output=True,text=True,timeout=30,check=True).stdout
                    pages = int(next(line.split(':',1)[1] for line in info.splitlines() if line.startswith('Pages:')))
                    textfile = target.with_suffix('.txt')
                    p = subprocess.run(['pdftotext','-layout',str(target),str(textfile)],capture_output=True,text=True,timeout=45)
                    if p.returncode:
                        raise ValueError('pdftotext failed: '+p.stderr[:300])
                    text = textfile.read_text(errors='replace')
                    entry.update(status='text_ready' if len(text.strip()) >= 100 else 'needs_visual_or_ocr',
                                 pages=pages, text_characters=len(text), pdf=str(target), text=str(textfile))
            except Exception as e:
                entry.update(status='read_error', error=str(e))
            result['bodies'].append(entry)
        result['status'] = 'retained_bodies_checked' if result['bodies'] else 'no_retained_body'
        return result
    with ThreadPoolExecutor(max_workers=3) as pool:
        with (out / 'retrieval.jsonl').open('w') as log:
            for r in pool.map(one, manifest['records']):
                results.append(r)
                log.write(json.dumps(r)+'\n'); log.flush()
                print(r['filename'], [b['status'] for b in r['bodies']] or [r['status']], flush=True)
    (out / 'retrieval.json').write_text(json.dumps(results,indent=2)+'\n')


def publishers(out):
    """Read recorded public URLs; keep these receipts distinct from retained reads."""
    destination = out / 'publisher-retrieval.jsonl'
    if destination.exists():
        raise FileExistsError('Publisher retrieval receipts already exist')
    manifest = json.loads((out / 'sample.json').read_text())
    def one(row):
        result = {'document_id':row['document_id'],'filename':row['filename'],'attempts':[]}
        urls = list(dict.fromkeys(row.get('source_urls') or [row['source_url']]))
        for url in urls[:2]:
            attempt = {'url':url}
            try:
                if urlsplit(url).scheme not in {'http','https'}:
                    raise ValueError('Not an absolute HTTP(S) URL')
                request = Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; CongressionalTech/1.0; document research)'})
                with urlopen(request,timeout=20) as response:
                    body = response.read(32 * 1024**2 + 1)
                    attempt.update(final_url=response.url,http_status=response.status,content_type=response.headers.get('Content-Type'))
                if len(body) > 32 * 1024**2:
                    raise ValueError('Publisher body exceeds 32 MiB limit')
                if not body.startswith(b'%PDF-'):
                    raise ValueError('Response is not PDF bytes')
                sha = hashlib.sha256(body).hexdigest()
                target = out / 'pdf' / (sha+'.pdf')
                target.parent.mkdir(exist_ok=True)
                target.write_bytes(body)
                info = subprocess.run(['pdfinfo',str(target)],capture_output=True,text=True,timeout=30,check=True).stdout
                pages = int(next(line.split(':',1)[1] for line in info.splitlines() if line.startswith('Pages:')))
                textfile = target.with_suffix('.txt')
                subprocess.run(['pdftotext','-layout',str(target),str(textfile)],capture_output=True,text=True,timeout=45,check=True)
                text = textfile.read_text(errors='replace')
                attempt.update(status='text_ready' if len(text.strip())>=100 else 'needs_visual_or_ocr',
                               sha256=sha,bytes=len(body),pages=pages,text_characters=len(text),pdf=str(target),text=str(textfile),
                               matches_retained_digest=sha in {Path(k).name.removesuffix('.gz') for k in row['body_keys'] or []})
            except Exception as e:
                attempt.update(status='read_error',error=str(e))
            result['attempts'].append(attempt)
            if attempt['status']!='read_error':break
        return result
    results=[]
    with ThreadPoolExecutor(max_workers=3) as pool, destination.open('w') as log:
        for r in pool.map(one,manifest['records']):
            results.append(r);log.write(json.dumps(r)+'\n');log.flush()
            print(r['filename'],r['attempts'][-1]['status'],flush=True)
    (out/'publisher-retrieval.json').write_text(json.dumps(results,indent=2)+'\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['prepare','fetch','publishers'])
    p.add_argument('--output', type=Path, default=DEFAULT_INPUT/'content-validation-v1')
    p.add_argument('--account-id')
    a = p.parse_args()
    if a.action == 'prepare': prepare(a.output)
    elif a.action == 'fetch': fetch(a.output,a.account_id)
    else: publishers(a.output)
