"""Offline, reproducible proposal review. Never writes catalog classifications.

The frozen document ID is the counting unit. Filenames are never identity keys
for decisions; cached reader results include the complete source URL.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from functools import lru_cache
import gzip
import hashlib
import html
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for package in ('house-naming', 'congress_api'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))

from house_naming import Engine
from house_naming.errors import NamingError
from congress_api.parsers.document_types import document_type
from congress_api.parsers.senate_page import explicit_document_kind, section_document_kind

DEFAULT_INPUT = ROOT / 'output/filename-patterns-20261015'
SCIENCE = ['science.house.gov', 'democrats-science.house.gov', 'republicans-science.house.gov']
RESOURCES = ['naturalresources.house.gov']
ENERGY = ['energycommerce.house.gov', 'democrats-energycommerce.house.gov']
EDUCATION = ['edworkforce.house.gov', 'democrats-edworkforce.house.gov']
COMMITTEES = sorted(set(SCIENCE + RESOURCES + ENERGY + EDUCATION + [
    'judiciary.house.gov', 'democrats-judiciary.house.gov', 'agriculture.house.gov',
    'waysandmeans.house.gov', 'financialservices.house.gov', 'smallbusiness.house.gov',
    'oversight.house.gov', 'oversightdemocrats.house.gov', 'appropriations.house.gov',
    'transportation.house.gov', 'veterans.house.gov']))
VOTE = r'(?<![a-z])(?:rcv?\s*\d+|record(?:ed)?\s*vote|roll\s*call|vote\s*(?:record|sheet)|voting\s*record)'
MEDIA_EXT = {'.wmv','.wvx','.mp4','.m3u8','.vtt','.jpg','.jpeg','.png','.gif','.mp3'}
MEDIA_FORMAT = {'mp4','m3u8','text/vtt','application/x-mpegurl','video/x-ms-wvx','video/x-ms-wmv','video/x-ms-asf'}


def norm(value):
    return re.sub(r'[^a-z0-9]+', ' ', value.casefold()).strip()


def host(url):
    try:
        p = urlsplit(url or '')
        if p.scheme not in {'http','https'} or p.username or p.password:
            return ''
        return (p.hostname or '').removeprefix('www.')
    except ValueError:
        return ''


def load_rules():
    """Proposal-only patterns. Each rule exposes its scope and exclusions."""
    definitions = [
        ('memo.explicit','committee-memorandum',COMMITTEES,
         r'(?<![a-z])(?:hearing\s*memo|markup\s*memo|briefing\s*memo|background\s*memo|dem\s*memo|memo\s+(?:he|ep|ee|cat|cmt|oi|fc)\b)', [],
         'Explicit memorandum wording; event subtype remains separate.'),
        ('memo.local','committee-memorandum',RESOURCES + ['financialservices.house.gov','smallbusiness.house.gov'],
         r'(?<![a-z])(?:(?:fl|emr|iana|iiana|wpo|fc|cm|mpt|fi|oi|hi)\s*(?:hearing|hrg)?\s*memo|hrg\s*memo|hearingmemo)', [],
         'Publisher-local memo abbreviations; confirm hearing versus markup from source.'),
        ('charter.science','hearing-charter',SCIENCE,r'\bcharter\b',[],
         'Science committee charter family; proposed new kind requires taxonomy review.'),
        ('notice.explicit','meeting-notice',COMMITTEES,r'(?:hearing|hrg|hrng|markup)\s*(?:notice|ntc)|\bhearing\s+advisory\b',[],
         'Notice wording; the event itself is not a transcript.'),
        ('advisory.waysmeans','meeting-notice',['waysandmeans.house.gov'],r'\badvisory\b',[],
         'Broad meeting notice proposal; advisory alone does not establish hearing subtype.'),
        ('witness-list.local','witness-list',COMMITTEES,r'witness\s*list|wtns\s*l(?:is)?(?:s)?t',[],
         'Witness-list wording, including observed local abbreviations.'),
        ('disclosure.local','testimony-disclosure',RESOURCES + SCIENCE + EDUCATION + ['smallbusiness.house.gov','waysandmeans.house.gov','appropriations.house.gov'],
         r'disclosure|(?<![a-z])ttf(?![a-z])|truth\s+in\s+(?:testimony|testifying)',
         [r'whistle\s*blower|protected\s+disclosure|6103'],
         'Disclosure candidate only within reviewed publishers; exclude whistleblower and tax disclosures.'),
        ('opening.explicit','opening-statement',COMMITTEES,
         r'opening\s*(?:statement|stat|stmt)|(?:^|\d|\s)(?:br|fp|dd|gg|eec)\s+opening\b|\bopening\s+(?:ep|he|oi|cat|cmt|dccp)\b',[],
         'Explicit statement layout; no speaker-role inference.'),
        ('opening.science','opening-statement',SCIENCE,r'(?<![a-z])os(?![a-z])',[],
         'Science publisher OS convention; does not imply witness or member identity.'),
        ('opening.resources','opening-statement',RESOURCES,
         r'(?:lamborn|fleming|hastings|bishop|young|mcclintock|chairmanhastings|chairman)opening(?:stat)?',[],
         'Joined opening marker in a reviewed publisher layout.'),
        ('vote.explicit','committee-vote',COMMITTEES,VOTE,
         [r'\b(?:amendment|amndt|amend|amdt)\b.*\b(?:on|to|regarding|about)\s+(?:recorded\s+votes?|roll\s+calls?)\b'],
         'Vote records remain separate from the amendments they reference.'),
        ('amendment.explicit','amendment',COMMITTEES,
         r'\bamendment\b|(?<![a-z])amend\s*\d+|\bamdt\b.*\btext\b',
         [VOTE,r'\b(?:vote|votes|voting|roster|list|memo|notice|summary|description|report)\b|\bopening\b|\btestimony\b'],
         'Amendment text proposal; reject votes, lists, descriptions and contextual mentions.'),
    ]
    return [dict(rule_id=i,proposed_kind=k,publishers=h,pattern=p,exclusions=e,note=n,
                 taxonomy_status='proposed_new_kind' if k=='hearing-charter' else 'existing_kind',
                 status='unvalidated_candidate') for i,k,h,p,e,n in definitions]


def role_gate(row):
    name = row['filename'].casefold()
    ext = Path(name).suffix
    formats = {x.casefold() for x in row.get('format') or []}
    if row.get('record_role') != ['document']:
        return 'non_document_role'
    if ext in MEDIA_EXT or formats & MEDIA_FORMAT or any(x.startswith(('video/','audio/','image/')) for x in formats):
        return 'media_or_image'
    if ext == '.zip' or any('zip' in x for x in formats):
        return 'archive'
    if ext == '.xml' and (re.match(r'^(?:hhrg|hmtg|hmkp)-',name) or name in {'dip.xml','mods.xml','mets.xml','premis.xml'}):
        return 'xml_record_role_review'
    urls = row.get('source_urls') or [row.get('source_url') or '']
    paths = [urlsplit(u).path.casefold() for u in urls if host(u)]
    if ext in {'.html','.htm','.aspx','.php'} or formats & {'html','text/html'}:
        return 'html_record_role_review'
    if not ext and paths and all(re.search(r'/(?:hearings?|events?|press-releases|committee-activity)(?:/|$)',p) for p in paths):
        return 'event_or_index_role_review'
    if name in {'home','hearings','hearings-calendar','watch-live','text','fulltext'}:
        return 'generic_endpoint_role_review'
    return None


LABEL_KINDS = {
    'hearing memo':'committee-memorandum','hearing memorandum':'committee-memorandum',
    'markup memo':'committee-memorandum','markup memorandum':'committee-memorandum',
    'committee memo':'committee-memorandum','briefing memo':'committee-memorandum',
    'hearing charter':'hearing-charter','opening statement':'opening-statement',
    'opening statements':'opening-statement','witness list':'witness-list',
    'subcommittee hearing witness list':'witness-list','hearing notice':'meeting-notice',
    'hearing advisory':'meeting-notice','meeting notice':'meeting-notice',
    'truth in testimony':'testimony-disclosure','truth in testifying':'testimony-disclosure',
    'witness disclosure':'testimony-disclosure','witness disclosure form':'testimony-disclosure',
}


def trusted_anchors(row):
    for index,o in enumerate(row.get('source_occurrences') or []):
        basis=set(o.get('source_association_basis') or [])
        if (o.get('source_occurrence_scope')==['anchor'] and o.get('source_link_url')
                and o.get('source_original_page_url') and basis
                and basis <= {'retained_html_link','publisher_redirect'}):
            yield index,o


def label_kind(value):
    return LABEL_KINDS.get(norm(value)) or document_type(explicit_document_kind(value))


def context_evidence(row):
    evidence=[]
    for index,o in trusted_anchors(row):
        # The document's explicit label/type outranks the containing section.
        claims=[]
        if any(b.startswith('publisher') for b in o.get('source_document_type_basis') or []):
            claims += [('source_document_type',v,document_type(v)) for v in o.get('source_document_type') or []]
        claims += [('source_link_label',v,label_kind(v)) for v in o.get('source_link_label') or []]
        known=[c for c in claims if c[2]]
        if not known:
            headings=o.get('source_link_heading') or []
            k=document_type(section_document_kind({'headings':headings}))
            if not k and len(headings)==1:
                k=LABEL_KINDS.get(norm(headings[0]))
            if k: known=[('source_link_heading',headings[0],k)]
        for field,value,kind in known:
            evidence.append({'occurrence_index':index,'field':field,'value':value,'kind':kind,
                             'pages':o['source_original_page_url'],'links':o['source_link_url']})
    return evidence


def compatible(kinds):
    # A shared broad family does not establish agreement on the document kind.
    return len(set(kinds))<=1


def classify(row,rules,baseline=(),errors=()):
    gate=role_gate(row)
    result={'document_id':row['document_id'],'filename':row['filename'],'source_url':row.get('source_url'),
            'formats':row.get('format') or [],'role_review':gate,'baseline_kinds':sorted(set(baseline)),
            'proposed_kinds':[],'rule_ids':[],'matches':[],'rejected_rules':[],
            'source_evidence':[],'reader_errors':list(errors),'status':'unresolved'}
    if gate:
        result['status']='role_review';return result
    publishers={host(u) for u in row.get('source_urls') or [row.get('source_url')]}
    for _,o in trusted_anchors(row):publishers.update(host(p) for p in o['source_original_page_url'])
    value=norm(row['filename'])
    for rule in rules:
        found=re.search(rule['pattern'],value,re.I)
        if not found:continue
        rejected=[p for p in rule['exclusions'] if re.search(p,value,re.I)]
        scoped=sorted(publishers & set(rule['publishers']))
        if rejected or not scoped:
            result['rejected_rules'].append({'rule_id':rule['rule_id'],'reason':'excluded_wording' if rejected else 'outside_publisher_scope'})
            continue
        result['rule_ids'].append(rule['rule_id'])
        result['matches'].append({'rule_id':rule['rule_id'],'marker':found.group(),'publishers':scoped})
        result['proposed_kinds'].append(rule['proposed_kind'])
    result['proposed_kinds']=sorted(set(result['proposed_kinds']))
    evidence=context_evidence(row); result['source_evidence']=evidence
    source_kinds={e['kind'] for e in evidence}
    all_kinds=set(baseline)|source_kinds|set(result['proposed_kinds'])
    if errors:result['status']='reader_error'
    elif not compatible(all_kinds):result['status']='conflict'
    elif baseline:result['status']='existing_reader_candidate'
    elif result['proposed_kinds']:
        result['status']='proposed_corroborated' if source_kinds else 'proposed_filename_only'
    elif source_kinds:result['status']='source_context_candidate'
    # Evidence is never promoted to a verified kind in this workflow.
    return result


def grams(value):
    s=' '+value+' '
    return {s[i:i+3] for i in range(max(1,len(s)-2))}


def select_samples(ids,names):
    """Central lexical profile, furthest member, then source/format diversity."""
    if len(ids)<=3:return list(ids)
    features={i:grams(names[i]['lexical']) for i in ids}
    freq=Counter(g for fs in features.values() for g in fs)
    center=max(ids,key=lambda i:(sum(freq[g] for g in features[i])/len(features[i]),-i))
    def distance(i,j):
        a,b=features[i],features[j]
        return 1-len(a&b)/len(a|b)
    boundary=max((i for i in ids if i!=center),key=lambda i:(distance(i,center),-i))
    picked=[center,boundary]
    domains=set().union(*(set(names[i]['domains']) for i in picked))
    extensions={Path(names[i]['filename']).suffix.lower() for i in picked}
    third=max((i for i in ids if i not in picked),key=lambda i:(
        bool(set(names[i]['domains'])-domains),Path(names[i]['filename']).suffix.lower() not in extensions,
        min(distance(i,j) for j in picked),-i))
    return picked+[third]


def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def csv_file(path,fields,rows):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for row in rows:
            # JSON preserves exact strings; CSV quotes protect structural separators.
            w.writerow({k:json.dumps(row.get(k),ensure_ascii=False) if isinstance(row.get(k),(list,dict)) else row.get(k) for k in fields})


def run(input_dir,output_dir):
    import pyarrow.parquet as pq
    from congress_api.retention.document_index import parser_fingerprint
    start=time.monotonic()
    if output_dir.exists():raise FileExistsError('Choose a new output directory; review runs are immutable.')
    required=['documents.parquet','filename-records.jsonl','ranked-groups.csv','similarity-groups.json','templates.json','hdbscan-groups.json']
    before={f:digest(input_dir/f) for f in required}
    output_dir.mkdir(parents=True)
    rules=load_rules()
    (output_dir/'rules.json').write_text(json.dumps(rules,indent=2)+'\n')
    engine=Engine()
    @lru_cache(maxsize=100000)
    def baseline(name,url):
        try:
            r=engine.extract(name,source_url=url or None)
            return tuple(r['metadata'].get('document_kind') or []),None
        except NamingError as e:return (),str(e)
    names=[]
    with (input_dir/'filename-records.jsonl').open() as f:
        for line in f:
            n=json.loads(line)
            names.append({k:n[k] for k in ('filename','lexical','domains','examples')})
    representative={}; counts=Counter();baseline_counts=Counter();proposal_counts=Counter()
    rule_docs=defaultdict(set);rule_states=defaultdict(Counter);rule_publishers=defaultdict(Counter)
    rule_examples=defaultdict(list);rejections=defaultdict(list);rule_rejected=Counter()
    seen=set();conflicts=[];unresolved_sample=[]
    fields=['document_id','filename','source_url','status','role_review','baseline_kinds','proposed_kinds','rule_ids','source_evidence','reader_errors']
    columns=['document_id','filename','source_url','source_urls','format','record_role','source_occurrences','source_link_label','source_link_heading']
    parquet=pq.ParquetFile(input_dir/'documents.parquet')
    with gzip.open(output_dir/'document-review.jsonl.gz','wt') as detail, (output_dir/'candidate-documents.csv').open('w',newline='') as c:
        writer=csv.DictWriter(c,fieldnames=fields);writer.writeheader()
        for batch in parquet.iter_batches(batch_size=2048,columns=columns):
            for row in batch.to_pylist():
                doc=row['document_id']
                if doc in seen:raise ValueError(f'Duplicate frozen document ID: {doc}')
                seen.add(doc);kinds=set();errors=[]
                if role_gate(row) is None:
                    urls=sorted(set(row.get('source_urls') or [row.get('source_url') or '']))
                    for url in urls:
                        k,e=baseline(row['filename'],url);kinds.update(k)
                        if e:errors.append({'source_url':url,'error':e})
                result=classify(row,rules,kinds,errors)
                counts[result['status']]+=1
                if result['role_review']:counts['role:'+result['role_review']]+=1
                baseline_counts.update(kinds);proposal_counts.update(result['proposed_kinds'])
                result['input_row']=len(seen)
                if result['status'] not in {'role_review','unresolved'}:
                    # Preserve each original occurrence, rather than combining flat labels.
                    result['source_occurrences']=row.get('source_occurrences') or []
                    writer.writerow({k:json.dumps(result.get(k),ensure_ascii=False) if isinstance(result.get(k),(list,dict)) else result.get(k) for k in fields})
                detail.write(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n')
                sample={k:result[k] for k in ('document_id','filename','source_url','status','baseline_kinds','proposed_kinds','source_evidence')}
                sample['flat_source_labels']=row.get('source_link_label') or []
                if row['filename'] not in representative or result['status']=='conflict':representative[row['filename']]=sample
                if result['status']=='conflict':conflicts.append(sample)
                if result['status']=='unresolved' and len(unresolved_sample)<100:unresolved_sample.append(sample)
                for rid in result['rule_ids']:
                    rule_docs[rid].add(doc);rule_states[rid][result['status']]+=1
                    rule_publishers[rid][host(row.get('source_url'))]+=1
                    rule_examples[rid].append(sample)
                for rejected in result['rejected_rules']:
                    rid=rejected['rule_id'];rule_rejected[rid]+=1
                    if len(rejections[rid])<12:rejections[rid].append({**sample,'reason':rejected['reason']})
            if len(seen)%20480==0:print(f'Reviewed {len(seen):,} document groups; {time.monotonic()-start:.1f}s',flush=True)
    summaries=[]
    for rule in rules:
        rid=rule['rule_id'];candidates=rule_examples[rid]
        # Prioritize conflicts and corroboration; group samples below provide diversity.
        samples=[]
        for s in sorted(candidates,key=lambda x:(x['status']!='conflict',x['status']!='proposed_corroborated',x['filename'])):
            if len(samples)<3 and s['filename'] not in {x['filename'] for x in samples}:samples.append(s)
        summaries.append({**rule,'unique_document_count':len(rule_docs[rid]),'status_counts':dict(rule_states[rid]),
                          'publisher_counts':dict(rule_publishers[rid]),'rejected_document_count':rule_rejected[rid],
                          'examples':samples,'counterexamples':rejections[rid]})
    summaries.sort(key=lambda r:(-r['status_counts'].get('proposed_corroborated',0),-r['unique_document_count'],r['rule_id']))
    (output_dir/'rule-review.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2)+'\n')
    csv_file(output_dir/'rule-review.csv',['rule_id','proposed_kind','taxonomy_status','status','publishers','pattern','exclusions','note','unique_document_count','status_counts','publisher_counts','rejected_document_count','examples','counterexamples'],summaries)
    csv_file(output_dir/'conflicts.csv',['document_id','filename','source_url','baseline_kinds','proposed_kinds','source_evidence'],conflicts)
    csv_file(output_dir/'unresolved-sample.csv',['document_id','filename','source_url','flat_source_labels'],unresolved_sample)
    groups=[]
    for filename in ['similarity-groups.json','templates.json','hdbscan-groups.json']:
        for g in json.loads((input_dir/filename).read_text()):
            if g['method']=='template' and not g['descriptive']:continue
            ids=select_samples(g['filename_indices'],names)
            samples=[{'selection':reason,'filename':names[i]['filename'],'publisher_counts':names[i]['domains'],
                      'document_example':representative[names[i]['filename']]} for i,reason in zip(ids,['central','boundary','diverse'])]
            groups.append({'group_id':g['group_id'],'method':g['method'],'documents':g['documents'],'distinct_filenames':g['distinct_filenames'],'samples':samples})
    csv_file(output_dir/'group-review-samples.csv',['group_id','method','documents','distinct_filenames','samples'],groups)
    (output_dir/'group-review-samples.json').write_text(json.dumps(groups,ensure_ascii=False)+'\n')
    after={f:digest(input_dir/f) for f in required}
    if before!=after:raise RuntimeError('Frozen inputs changed during review')
    if len(seen)!=parquet.metadata.num_rows:raise RuntimeError('Population conservation failed')
    if len(groups)!=6753:raise RuntimeError('Expected the complete frozen group inventory')
    statuses={k:v for k,v in counts.items() if not k.startswith('role:')}
    assert sum(statuses.values())==len(seen)
    current=parser_fingerprint()
    helper_paths=[ROOT/'packages/congress_api/src/congress_api/parsers'/f
                  for f in ('document_types.py','senate_page.py')]
    snapshot=(parquet.schema_arrow.metadata or {}).get(b'house_naming_fingerprint',b'').decode()
    stats={'documents':len(seen),'distinct_filenames':len(names),'group_rows':len(groups),'status_counts':statuses,
           'role_counts':{k[5:]:v for k,v in counts.items() if k.startswith('role:')},
           'baseline_kind_counts':dict(baseline_counts),'proposal_kind_counts':dict(proposal_counts),
           'unique_rule_matched_documents':len(set().union(*rule_docs.values())),
           'snapshot_parser_fingerprint':snapshot,'current_parser_fingerprint':current,'parser_fingerprint_matches_snapshot':snapshot==current,
           'inputs_unchanged':True,'classification_changes':0,'input_sha256':before,
           'implementation_sha256':digest(Path(__file__)),'elapsed_seconds':round(time.monotonic()-start,1),
           'source_reader_sha256':{str(p.relative_to(ROOT)):digest(p) for p in helper_paths},
           'limitations':['All outputs are unvalidated proposals; corroboration is not measured precision.',
                         'Baseline replays the maintained filename Engine with each source URL; this is not a full catalog rebuild.',
                         'Publisher evidence uses trusted retained anchors only; flat label unions are not decision evidence.',
                         'Role findings are filename/format/URL flags, not XML root or document body inspection.',
                         'No document contents or OCR were read; source-context candidates need content validation where ambiguous.',
                         'Group samples use lexical centrality and distance, then source/extension diversity; they do not prove purity.',
                         'Rule counts overlap; unique document totals are calculated from IDs. Unresolved sample is lexical-first, not a quality benchmark.']}
    (output_dir/'verification.json').write_text(json.dumps(stats,indent=2)+'\n')
    render_report(output_dir,stats,summaries)
    print(json.dumps(stats,indent=2),flush=True)


def render_report(out,stats,rules):
    esc=html.escape
    cards=[]
    for r in rules:
        samples=''.join('<li><code>'+esc(s['filename'])+'</code> — '+esc(s['status'])+'</li>' for s in r['examples'])
        counters=''.join('<li><code>'+esc(s['filename'])+'</code> — '+esc(s['reason'])+'</li>' for s in r['counterexamples'])
        cards.append(f'<details><summary>{esc(r["rule_id"])} → {esc(r["proposed_kind"])} · {r["unique_document_count"]:,} documents</summary><p>{esc(r["note"])}</p><p>Taxonomy: {esc(r["taxonomy_status"])}. All rules require validation.</p><p>Publishers: {esc(", ".join(r["publishers"]))}</p><pre>{esc(json.dumps(r["status_counts"],indent=2))}</pre><p>Examples</p><ul>{samples}</ul><p>Counterexamples / excluded candidates</p><ul>{counters}</ul></details>')
    status=''.join(f'<tr><td>{esc(k)}</td><td>{v:,}</td></tr>' for k,v in stats['status_counts'].items())
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Document kind rule review</title><style>body{font:16px/1.5 system-ui;margin:3rem auto;max-width:1100px;padding:0 24px;color:#20312f;background:#fafbf9}h1{font-size:32px}details{border-top:1px solid #becbc4;padding:15px 0}summary{cursor:pointer;font-weight:600}code{overflow-wrap:anywhere}pre{white-space:pre-wrap}td{padding:4px 20px 4px 0}input{padding:10px;width:95%;margin:20px 0}a{color:#175c50}</style><h1>Document kind rule review</h1><p>Offline dry run · no catalog classifications changed.</p><p>Corroborated means a retained publisher label agrees. It does not mean the rule has passed accuracy validation.</p>'''
    page+=f'<p>{stats["documents"]:,} document groups accounted for; {stats["unique_rule_matched_documents"]:,} unique documents match candidate rules. Counts across individual rules overlap.</p><table>{status}</table>'
    page+='<p><a href="rule-review.csv">Rule review CSV</a> · <a href="candidate-documents.csv">Per-document candidates</a> · <a href="conflicts.csv">Conflicts</a> · <a href="group-review-samples.csv">All groups: central, boundary, diverse samples</a> · <a href="verification.json">Verification and limitations</a></p><input aria-label="Filter rules" placeholder="Filter rules, kinds, or publishers" oninput="document.querySelectorAll(\'details\').forEach(d=>d.hidden=!d.textContent.toLowerCase().includes(this.value.toLowerCase()))">'
    page+=''.join(cards)+'<p>'+esc(' '.join(stats['limitations']))+'</p></html>'
    (out/'report.html').write_text(page)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,default=DEFAULT_INPUT)
    p.add_argument('--output',type=Path,default=DEFAULT_INPUT/'rule-review')
    a=p.parse_args();run(a.input,a.output)
