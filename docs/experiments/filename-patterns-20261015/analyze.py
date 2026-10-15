"""Reproducible filename discovery; proposals never alter document kinds."""
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import unquote, urlsplit

import numpy as np
import pyarrow.parquet as pq
from scipy.sparse import hstack
from sklearn.cluster import HDBSCAN
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import normalize

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / 'output/filename-patterns-20261015'
GENERIC = set('index playlist segment chunk main media caption captions subtitle subtitles download getdoc document file attachment view default downloadfile docs pdf html xml mods mets premis vtt m3u8 aspx cgi php final revised updated copy v'.split())
PLACEHOLDERS = {'date', 'id', 'number'}
MASK_FIELDS = ['date_token', 'short_date_token', 'date_range_token', 'opaque_uuid', 'opaque_hex']
UUID = re.compile(r'(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
HEX = re.compile(r'(?i)(?<![a-z0-9])[0-9a-f]{16,}(?![a-z0-9])')
BILL = re.compile(r'(?i)\b(h\.?[ _.-]*r\.?|s|h[ _.-]*res|s[ _.-]*res|h[ _.-]*j[ _.-]*res|s[ _.-]*j[ _.-]*res)[ _.-]*(\d{1,5})(?!\d)')


def write_json(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def normalize_name(name, fields=None):
    """Analysis-only normalization; never change literal values or infer surnames."""
    s = unicodedata.normalize('NFKC', unquote(name)).strip()
    s = re.sub(r'(?i)\.(pdf|docx?|xlsx?|pptx?|txt|html?|xml|vtt|m3u8|zip|jpg|jpeg|png|json|aspx|cgi|php|wmv|wvx)$', '', s)
    for field in MASK_FIELDS:
        for token in sorted((fields or {}).get(field, []), key=len, reverse=True):
            if token:
                s = s.replace(unquote(token), ' <id> ' if field.startswith('opaque') else ' <date> ')
    s = UUID.sub(' <id> ', s)
    s = HEX.sub(' <id> ', s)
    # Preserve bill numbers while masking unrelated numbers. Capture before case splitting.
    bills = []
    def protect(match):
        bills.append(re.sub(r'[^a-z]', '', match[1].lower()) + match[2])
        return ' billplaceholder' + chr(97 + len(bills) - 1) + ' '
    s = BILL.sub(protect, s)
    s = re.sub(r'(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])', ' ', s)
    s = re.sub(r'\d+', ' <number> ', s).casefold()
    s = re.sub(r'[^\w<>]+', ' ', s).replace('_', ' ')
    for i, bill in enumerate(bills):
        s = s.replace('billplaceholder' + chr(97 + i), bill)
    template = ' '.join(s.split())
    lexical = ' '.join(w for w in template.split() if w.strip('<>') not in PLACEHOLDERS and w not in GENERIC)
    return template, lexical


def main():
    start = time.monotonic()
    columns = ['document_id', 'source_id', 'filename', 'format', 'source_url', 'source_committee_name',
               'source_link_label', 'source_link_heading', 'source_original_page_url', *MASK_FIELDS]
    names = {}
    statuses = json.loads((OUT / 'source-status.json').read_text())
    document_rows = 0
    for batch in pq.ParquetFile(OUT / 'documents.parquet').iter_batches(columns=columns):
        for r in batch.to_pylist():
            document_rows += 1
            n = names.setdefault(r['filename'], {'filename': r['filename'], 'document_ids': [], 'saved_documents': 0,
                'formats': Counter(), 'domains': Counter(), 'fields': defaultdict(set), 'examples': []})
            n['document_ids'].append(r['document_id'])
            n['saved_documents'] += statuses[r['document_id']]['saved']
            n['formats'].update(r['format'] or [])
            host = urlsplit(r['source_url'] or '').hostname or '(no source URL)'
            n['domains'][host] += 1
            for field in MASK_FIELDS:
                n['fields'][field].update(r[field] or [])
            if len(n['examples']) < 3:
                n['examples'].append({k: r[k] for k in ['document_id','source_id','source_url','source_link_label','source_link_heading','source_original_page_url']})
    names = [names[key] for key in sorted(names)]
    templates = defaultdict(list)
    lexical_groups = defaultdict(list)
    for i, n in enumerate(names):
        n['template'], n['lexical'] = normalize_name(n['filename'], n.pop('fields'))
        n['documents'] = len(n['document_ids'])
        # Captions/playlists are accounted for as format families, not document-kind proposals.
        if set(n['formats']) <= {'text/vtt','m3u8','application/x-mpegurl','video/x-ms-wvx','video/x-ms-wmv','mp4','video/x-ms-asf'}:
            n['disposition'] = 'caption_or_media_filename'
        elif not re.search(r'[a-z]{2}', n['lexical']):
            n['disposition'] = 'opaque_numeric_or_generic'
        else:
            n['disposition'] = 'descriptive'
            lexical_groups[n['lexical']].append(i)
        templates[n['template']].append(i)
    print('Population',document_rows,'names',len(names),'lexical strings',len(lexical_groups),flush=True)
    write_json('normalization-examples.json', [{'filename': n['filename'],'template': n['template'],'lexical': n['lexical'],'disposition':n['disposition']} for n in names])
    with (OUT / 'filename-records.jsonl').open('w') as f:
        for n in names:
            f.write(json.dumps(n,ensure_ascii=False)+'\n')
    def summary(key, ids, arm, extra=None):
        docs = sum(names[i]['documents'] for i in ids)
        domains = Counter()
        words = Counter()
        for i in ids:
            domains.update(names[i]['domains'])
            words.update(set(names[i]['lexical'].split()))
        selected = sorted(ids,key=lambda i:(-names[i]['documents'],names[i]['filename']))
        examples = list(dict.fromkeys(selected[:4]+selected[-2:]))
        return {'group_id': key, 'method': arm, 'documents': docs,'distinct_filenames':len(ids),
            'saved_documents':sum(names[i]['saved_documents'] for i in ids),
            'top_terms': words.most_common(10),'top_domains': domains.most_common(6),
            'filename_indices': ids, 'examples':[{'filename':names[i]['filename'],**names[i]['examples'][0]} for i in examples],
            **(extra or {})}
    template_groups=[]
    for t, ids in templates.items():
        if len(ids)>=2:
            template_groups.append(summary('T-'+sha256(t.encode()).hexdigest()[:12],ids,'template',{'template':t,'descriptive':any(names[i]['disposition']=='descriptive' for i in ids)}))
    template_groups.sort(key=lambda g:(not g['descriptive'],-g['documents'],g['group_id']))
    write_json('templates.json',template_groups)
    texts=sorted(lexical_groups)
    char=TfidfVectorizer(analyzer='char_wb',ngram_range=(3,5),min_df=2,dtype=np.float32,sublinear_tf=True)
    word=TfidfVectorizer(ngram_range=(1,2),token_pattern=r'(?u)\b\w+\b',min_df=1,dtype=np.float32,sublinear_tf=True)
    X=normalize(hstack([char.fit_transform(texts)*np.sqrt(.65),word.fit_transform(texts)*np.sqrt(.35)],format='csr'))
    print('Features',X.shape,flush=True)
    nn=NearestNeighbors(n_neighbors=min(40,len(texts)),metric='cosine',algorithm='brute',n_jobs=2).fit(X)
    distances=[];neighbors=[]
    for a in range(0,len(texts),256):
        d,j=nn.kneighbors(X[a:a+256]);distances.extend(d);neighbors.extend(j)
        if a%4096==0:print('Neighbors',a,'/',len(texts),flush=True)
    distances=np.asarray(distances);neighbors=np.asarray(neighbors)
    np.savez_compressed(OUT/'neighbors.npz',distances=distances,neighbors=neighbors,texts=np.array(texts))
    # Conservative star groups: every member is close to one anchor; no transitive chaining.
    candidates={i:[int(j) for j,d in zip(neighbors[i],distances[i]) if d<=.28 and j!=i] for i in range(len(texts))}
    order=sorted(range(len(texts)),key=lambda i:(-len(candidates[i]),-sum(names[k]['documents'] for k in lexical_groups[texts[i]]),texts[i]))
    used=set();similar=[]
    for anchor in order:
        if anchor in used:continue
        members=[anchor]+[j for j in candidates[anchor] if j not in used]
        ids=sorted(k for j in members for k in lexical_groups[texts[j]])
        if len(ids)<2:continue
        used.update(members)
        scores=dict(zip(neighbors[anchor].tolist(),(1-distances[anchor]).tolist()))
        sims=[scores.get(j,1.) for j in members]
        similar.append(summary('S-'+sha256(texts[anchor].encode()).hexdigest()[:12],ids,'similarity',{'anchor':texts[anchor], 'lexical_strings':len(members),'min_anchor_cosine':min(sims),'mean_anchor_cosine':float(np.mean(sims))}))
    similar.sort(key=lambda g:(-g['documents'],g['group_id']))
    write_json('similarity-groups.json',similar)
    # The comparison uses the same feature matrix reduced to 50 dimensions.
    svd=TruncatedSVD(n_components=min(50,X.shape[0]-1,X.shape[1]-1),random_state=42)
    reduced=normalize(svd.fit_transform(X))
    print('HDBSCAN starting',flush=True)
    model=HDBSCAN(min_cluster_size=5,min_samples=3,metric='euclidean',n_jobs=2).fit(reduced)
    density=[]
    for label in sorted(set(model.labels_)-{-1}):
        members=np.flatnonzero(model.labels_==label).tolist()
        ids=sorted(k for j in members for k in lexical_groups[texts[j]])
        density.append(summary(f'H-{int(label):04}',ids,'hdbscan',{'lexical_strings':len(members),'mean_membership_strength':float(model.probabilities_[members].mean())}))
    density.sort(key=lambda g:(-g['documents'],g['group_id']))
    write_json('hdbscan-groups.json',density)
    write_json('hdbscan-labels.json',{'texts':texts,'labels':model.labels_.tolist(),'strengths':model.probabilities_.tolist()})
    term_names=Counter();term_docs=Counter()
    for n in names:
        if n['disposition']!='descriptive':continue
        tokens=n['lexical'].split()
        terms=set(tokens)|{' '.join(tokens[i:i+2]) for i in range(len(tokens)-1)}
        for term in terms:term_names[term]+=1;term_docs[term]+=n['documents']
    write_json('terms.json',[{'term':term,'filenames':count,'documents':term_docs[term]} for term,count in term_names.most_common(500)])
    # All selected documents get exactly one primary disposition. Group memberships are alternatives.
    by_name={k:g['group_id'] for g in similar for k in g['filename_indices']}
    assignment_counts=Counter();assignment_documents=Counter()
    with (OUT/'assignments.jsonl').open('w') as f:
        for i,n in enumerate(names):
            disposition=n['disposition'] if n['disposition']!='descriptive' else ('similarity_group' if i in by_name else 'descriptive_ungrouped')
            assignment_counts[disposition]+=1;assignment_documents[disposition]+=n['documents']
            f.write(json.dumps({'filename':n['filename'],'filename_index':i,'primary_disposition':disposition,'similarity_group':by_name.get(i),'document_ids':n['document_ids']})+'\n')
    template_set={i for g in template_groups if g['descriptive'] for i in g['filename_indices']}
    sim_set=set(by_name);hdb_set={i for g in density for i in g['filename_indices']}
    def coverage(indices):return {'filenames':len(indices),'documents':sum(names[i]['documents'] for i in indices)}
    manifest=json.loads((HERE/'input-manifest.json').read_text())
    stats={'catalog_id':manifest['catalog_id'],'input_counts':manifest['counts'],'distinct_filenames':len(names),
        'primary_filename_counts':dict(assignment_counts),'primary_document_counts':dict(assignment_documents),
        'descriptive_lexical_strings':len(texts),'features':X.shape[1],
        'template_groups':len(template_groups),'descriptive_template_groups':sum(g['descriptive'] for g in template_groups),
        'similarity_groups':len(similar),'hdbscan_groups':len(density),
        'template_coverage':coverage(template_set),'similarity_coverage':coverage(sim_set),'hdbscan_coverage':coverage(hdb_set),
        'similarity_beyond_templates':coverage(sim_set-template_set),'template_beyond_similarity':coverage(template_set-sim_set),
        'hdbscan_noise_lexical_strings':int(sum(model.labels_==-1)),
        'svd_explained_variance':float(svd.explained_variance_ratio_.sum()),
        'parameters':{'character_ngrams':[3,5],'word_ngrams':[1,2],'character_weight':.65,'word_weight':.35,'anchor_cosine_minimum':.72,'neighbor_cap':40,'hdbscan_min_cluster_size':5,'hdbscan_min_samples':3,'svd_dimensions':50,'seed':42},
        'elapsed_seconds':round(time.monotonic()-start,2)}
    assert sum(assignment_documents.values())==document_rows==manifest['counts']['named_unclassified_documents']
    assert sum(assignment_counts.values())==len(names)
    write_json('stats.json',stats)
    print(json.dumps(stats,indent=2),flush=True)


if __name__=='__main__':main()
