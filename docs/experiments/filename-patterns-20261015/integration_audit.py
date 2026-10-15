"""Replay maintained filename and source-kind readers on the frozen population."""
import argparse
from collections import Counter
from functools import lru_cache
import gzip
import json
from pathlib import Path
import time

import pyarrow.parquet as pq

from rule_review import DEFAULT_INPUT, ROOT, digest, role_gate
from congress_api.retention.document_index import extract, fill_document_kind, parser_fingerprint


def run(output):
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True)
    source=DEFAULT_INPUT/'documents.parquet'
    before=digest(source)
    counts=Counter();kinds=Counter();seen=set();start=time.monotonic()
    cached=lru_cache(maxsize=100000)(extract)
    with gzip.open(output/'results.jsonl.gz','wt') as f:
        for batch in pq.ParquetFile(source).iter_batches(batch_size=2048):
            for row in batch.to_pylist():
                assert row['document_id'] not in seen
                seen.add(row['document_id'])
                gate=role_gate(row)
                filename_kinds=set()
                if not gate:
                    for url in sorted(set(row.get('source_urls') or [row.get('source_url') or ''])):
                        filename_kinds.update(cached((row['filename'],url)).get('document_kind') or [])
                    row['document_kind']=sorted(filename_kinds) or None
                    fill_document_kind(row)
                r={k:row.get(k) for k in ['document_id','filename','source_url','document_kind','document_kind_source']}
                r['role_review']=gate;r['filename_kinds']=sorted(filename_kinds)
                r['status']='role_review' if gate else 'classified' if row.get('document_kind') else 'unresolved'
                counts[r['status']]+=1;kinds.update(r['document_kind'] or [])
                f.write(json.dumps(r,separators=(',',':'))+'\n')
    assert len(seen)==pq.ParquetFile(source).metadata.num_rows
    assert digest(source)==before
    modules=['packages/house-naming/src/house_naming/data/guide.json',
             'packages/congress_api/src/congress_api/retention/document_index.py',
             'packages/congress_api/src/congress_api/parsers/document_types.py']
    (output/'code').mkdir()
    for p in modules:(output/'code'/Path(p).name).write_bytes((ROOT/p).read_bytes())
    stats={'documents':len(seen),'counts':dict(counts),'kinds':dict(kinds),'input_sha256':before,
           'filename_fingerprint':parser_fingerprint(),'module_hashes':{p:digest(ROOT/p) for p in modules},
           'elapsed_seconds':round(time.monotonic()-start,1),
           'scope':'All frozen IDs accounted for; maintained readers replayed on records not flagged by the experiment role gate. Not a full retained-body catalog rebuild.'}
    (output/'stats.json').write_text(json.dumps(stats,indent=2)+'\n')
    print(json.dumps(stats,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path)
    run(p.parse_args().output)
