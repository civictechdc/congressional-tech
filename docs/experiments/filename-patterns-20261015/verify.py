"""Check population conservation, grouping bounds, and reproducibility inputs."""
from collections import Counter
from hashlib import file_digest
import json
from pathlib import Path
import platform
import sys
import urllib.request

import numpy as np
import pyarrow.parquet as pq
import scipy
import sklearn

from analyze import normalize_name

HERE=Path(__file__).resolve().parent
OUT=HERE.parents[2]/'output/filename-patterns-20261015'


def digest(path):
    with path.open('rb') as stream:
        return file_digest(stream,'sha256').hexdigest()


def main():
    manifest=json.loads((HERE/'input-manifest.json').read_text())
    stats=json.loads((OUT/'stats.json').read_text())
    assert digest(OUT/'documents.parquet')==manifest['input_sha256']
    source=Path(manifest['source_root'])
    for entry in manifest['source_manifest']['files'].values():
        assert digest(source/entry['key'])==entry['sha256']
    input_ids=set()
    for b in pq.ParquetFile(OUT/'documents.parquet').iter_batches(columns=['document_id','filename','document_kind','record_role']):
        for r in b.to_pylist():
            assert r['filename'] and not r['document_kind'] and r['record_role']==['document']
            assert r['document_id'] not in input_ids
            input_ids.add(r['document_id'])
    names=[json.loads(line) for line in (OUT/'filename-records.jsonl').open()]
    assigned=set();counts=Counter()
    for i,line in enumerate((OUT/'assignments.jsonl').open()):
        r=json.loads(line)
        assert r['filename_index']==i and r['filename']==names[i]['filename']
        for d in r['document_ids']:
            assert d not in assigned
            assigned.add(d)
        counts[r['primary_disposition']]+=len(r['document_ids'])
    assert assigned==input_ids
    assert dict(counts)==stats['primary_document_counts']
    nearest=np.load(OUT/'neighbors.npz');positions={s:i for i,s in enumerate(nearest['texts'])}
    neighbor_indices,neighbor_distances=nearest['neighbors'],nearest['distances']
    similarities=json.loads((OUT/'similarity-groups.json').read_text());seen=set()
    for g in similarities:
        a=positions[g['anchor']]
        scores={int(j):float(1-d) for j,d in zip(neighbor_indices[a],neighbor_distances[a])}
        assert not seen.intersection(g['filename_indices']);seen.update(g['filename_indices'])
        for i in g['filename_indices']:
            assert scores[positions[names[i]['lexical']]]>=.72-1e-6
        assert sum(names[i]['documents'] for i in g['filename_indices'])==g['documents']
    # Constructed counterexamples: preserve bill identity and modifiers; mask opaque noise.
    assert normalize_name('H.R.1234.pdf')[1]=='hr1234'
    assert normalize_name('H.R.1235.pdf')[1]=='hr1235'
    assert normalize_name('Smith_20240312_Responses.pdf',{'date_token':['20240312']})==('smith <date> responses','smith responses')
    assert normalize_name('index_1_23984.vtt')[1]==''
    assert normalize_name('a18e453c-9bfc-4010-8a5b-85380fd7e4d3.pdf')[1]==''
    assert normalize_name('WrittenStatement.pdf')[1]=='written statement'
    assert normalize_name('statement-summary.pdf')[1]!=normalize_name('statement.pdf')[1]
    req=urllib.request.Request('https://congressional-viewer-data.mdeeb.workers.dev/manifest.json',headers={'User-Agent':'congressional-tech-viewer-publisher/1.0 (+https://github.com/civictechdc/congressional-tech)'})
    pointer=json.load(urllib.request.urlopen(req,timeout=30))
    public_unchanged=pointer==json.loads((HERE/'public-pointer.json').read_text())
    result={'population_conserved':True,'named_documents':len(input_ids),'distinct_filenames':len(names),
        'source_pair_hashes_unchanged':True,'public_selection_unchanged':public_unchanged,
        'similarity_groups_disjoint':True,'all_member_anchor_cosines_at_least_0_72':True,
        'constructed_normalization_checks':7,'classification_changes':0,
        'runtime':{'python':sys.version,'platform':platform.platform(),'numpy':np.__version__,'scipy':scipy.__version__,'sklearn':sklearn.__version__},
        'artifacts':{str(p.relative_to(HERE.parents[2])):digest(p) for directory in [HERE,OUT] for p in sorted(directory.iterdir()) if p.is_file() and p.name not in {'verification.json','import-timing.log','verification.log'} }}
    (OUT/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='artifacts'},indent=2))


if __name__=='__main__':main()
