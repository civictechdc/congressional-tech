"""Build a standalone, searchable evidence report and flat review exports."""
import csv
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[2] / 'output/filename-patterns-20261015'


def main():
    stats = json.loads((OUT / 'stats.json').read_text())
    reviews = json.loads((HERE / 'reviews.json').read_text())
    names = [json.loads(line) for line in (OUT / 'filename-records.jsonl').open()]
    nearest = np.load(OUT / 'neighbors.npz')
    positions = {s: i for i, s in enumerate(nearest['texts'])}
    neighbor_indices, neighbor_distances = nearest['neighbors'], nearest['distances']
    groups = []
    for filename in ['similarity-groups.json', 'templates.json', 'hdbscan-groups.json']:
        for g in json.loads((OUT / filename).read_text()):
            if g['method'] == 'template' and not g['descriptive']:
                continue
            formats = {}
            for i in g['filename_indices']:
                for k, v in names[i]['formats'].items():
                    formats[k] = formats.get(k, 0) + v
            g['formats'] = formats
            g['review'] = reviews['groups'].get(g['group_id'])
            g['title'] = (g['review'] or {}).get('candidate') or g.get('anchor') or g.get('template') or ', '.join(t for t, _ in g['top_terms'][:4])
            if g['method'] == 'similarity':
                a = positions[g['anchor']]
                scores = {int(j): float(1 - d) for j, d in zip(neighbor_indices[a], neighbor_distances[a])}
                worst = sorted(g['filename_indices'], key=lambda i: (scores.get(positions[names[i]['lexical']], 1), names[i]['filename']))[:2]
                g['boundary_examples'] = [{'filename': names[i]['filename'], 'cosine': scores.get(positions[names[i]['lexical']], 1), **names[i]['examples'][0]} for i in worst]
            g['examples'] = g['examples'][:3]
            groups.append(g)
    with (OUT / 'ranked-groups.csv').open('w', newline='') as f:
        fields = ['group_id','method','title','documents','distinct_filenames','saved_documents','verdict','note','examples']
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for g in groups:
            r = g['review'] or {}
            w.writerow({**{k: g[k] for k in fields[:6]}, 'verdict':r.get('verdict','unreviewed'), 'note':r.get('note',''), 'examples':' | '.join(x['filename'] for x in g['examples'])})
    with (OUT / 'filename-assignments.csv').open('w', newline='') as f:
        w = csv.writer(f); w.writerow(['filename','document_groups','saved_document_groups','template','lexical','disposition','similarity_group'])
        for i, line in enumerate((OUT / 'assignments.jsonl').open()):
            a = json.loads(line); n = names[i]; assert n['filename'] == a['filename']
            w.writerow([n['filename'],n['documents'],n['saved_documents'],n['template'],n['lexical'],a['primary_disposition'],a['similarity_group']])
    (OUT / 'reviewed-groups.json').write_text(json.dumps([g for g in groups if g['review']], indent=2, ensure_ascii=False)+'\n')
    grouped = {i for g in groups if g['method']=='similarity' for i in g['filename_indices']}
    tail = sorted([n for i,n in enumerate(names) if n['disposition']=='descriptive' and i not in grouped],key=lambda n:sha256(n['filename'].encode()).hexdigest())[:10]
    (OUT/'tail-review-sample.json').write_text(json.dumps(tail,indent=2,ensure_ascii=False)+'\n')
    payload = {'stats':stats, 'groups':groups, 'names':[[n['filename'],n['documents']] for n in names], 'tail':[{'filename':n['filename'],**n['examples'][0]} for n in tail]}
    html = TEMPLATE.replace('__DATA__', json.dumps(payload, ensure_ascii=False, separators=(',',':')).replace('<','\\u003c'))
    (OUT / 'report.html').write_text(html)
    print('Report:',OUT/'report.html','groups:',len(groups),'reviewed:',sum(bool(g['review']) for g in groups))


TEMPLATE = r'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Unclassified filename patterns · October 15, 2026</title>
<style>
:root{color-scheme:light;--ink:#162b3d;--muted:#536677;--line:#d8e0e6;--blue:#155a86;--paper:#faf9f5}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 system-ui,sans-serif}main{max-width:1180px;margin:auto;padding:48px 28px}h1{font-size:38px;line-height:1.15;letter-spacing:-1px;margin:12px 0 18px}h2{margin-top:36px;font-size:24px}h3{font-size:18px;margin:20px 0 8px}.eyebrow{font-size:12px;letter-spacing:2px;color:var(--blue);font-weight:700}.lead{max-width:840px;font-size:19px}.muted,small{color:var(--muted)}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:28px 0}.card{background:white;border:1px solid var(--line);border-top:3px solid var(--blue);padding:18px}.card strong{display:block;font-size:28px;font-variant-numeric:tabular-nums}.note{padding:18px 22px;background:#eef3f6;border-left:3px solid var(--blue);margin:24px 0}.caution{background:#fff5dd;border-color:#ae7427}a{color:var(--blue);text-underline-offset:3px}table{width:100%;border-collapse:collapse;background:#fff}th,td{text-align:left;padding:12px 14px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:13px;color:var(--muted);background:#eef3f6}.controls{display:flex;flex-wrap:wrap;gap:14px;align-items:end;padding:18px;background:#eef3f6;margin:20px 0}label{font-size:13px;font-weight:600;display:grid;gap:5px}input,select,button{font:inherit;border:1px solid #9eafbb;border-radius:4px;background:#fff;padding:9px;color:var(--ink)}#search{min-width:280px}button{cursor:pointer}button:hover{background:#e8eff3}details{background:#fff;border:1px solid var(--line);margin:10px 0}summary{cursor:pointer;padding:16px;display:flex;justify-content:space-between;gap:15px}summary:hover{background:#f0f5f8}.group-body{padding:0 20px 20px}.tag{font-size:12px;border:1px solid var(--line);padding:3px 7px;border-radius:20px;white-space:nowrap}.meta{font-size:13px;color:var(--muted)}.example{padding:12px 0;border-bottom:1px solid var(--line);overflow-wrap:anywhere}.filename{font:13px/1.6 ui-monospace,monospace;overflow-wrap:anywhere}.members{max-height:260px;overflow:auto;background:#f6f7f8;padding:14px}.end{margin-top:32px;padding-top:18px;border-top:1px solid var(--line);font-size:13px}.scroll{overflow:auto}@media(max-width:700px){main{padding:24px 16px}h1{font-size:30px}.cards{grid-template-columns:1fr 1fr}summary{display:block}#search{min-width:0;width:100%}.controls>label{width:100%}}
</style>
<main><div class="eyebrow">CONGRESSIONAL DOCUMENTS / EXPLORATORY ANALYSIS</div>
<h1>Recurring filenames, reviewable evidence.</h1>
<p class="lead">Conservative similarity grouping connects <strong>7,486 additional filenames</strong> beyond exact templates. Use these families to prioritize source review; a shared filename pattern does not establish a shared document kind.</p>
<p class="muted">October 15, 2026 · Frozen public catalog <code>0caede06d52f4c9caa8d5cbd24f83543</code></p>
<div class="cards"><div class="card"><strong>53,222</strong>distinct filenames analyzed</div><div class="card"><strong>37,874</strong>names with remaining alphabetic text</div><div class="card"><strong>22,696</strong>names in similarity groups</div><div class="card"><strong>25</strong>groups reviewed through samples</div></div>
<div class="note"><strong>Scope matters.</strong> The estimate of 7,500 could not be reproduced without an additional filter. This run covers all formats, Congresses, and saved states in the current release. There are 657,103 named unclassified catalog document groups, including many repeated metadata and caption filenames. Another 99,866 groups have no preferred filename. Document groups are catalog identities, not a verified count of distinct underlying content.</div>
<h2>What the comparison found</h2>
<div class="scroll"><table><thead><tr><th>Method</th><th>Groups</th><th>Distinct filenames grouped</th><th>Practical result</th></tr></thead><tbody>
<tr><td>Exact descriptive templates</td><td>2,271</td><td>15,212</td><td>Transparent baseline; finds repeated naming conventions.</td></tr>
<tr><td>TF-IDF similarity, common anchor</td><td>3,735</td><td>22,696</td><td>Preferred review queue. Adds 7,486 names; misses 2 covered by templates.</td></tr>
<tr><td>SVD + HDBSCAN</td><td>747</td><td>20,794</td><td>Some useful families, but clear incoherent groups. Do not use this configuration for kind inference.</td></tr>
</tbody></table></div>
<p class="muted">Coverage overlaps across methods. These counts measure grouping, not correct classifications. All names and original source evidence remain unchanged.</p>
<div class="note caution"><strong>A useful failure:</strong> HDBSCAN placed <code>dip.xml</code>, Diaz/DiMuccio filenames, DIRECTV-DISH material, and <code>DisplayNews.aspx</code> in one group. Its 34,203 document groups come from only eight distinct filenames. The 50-dimensional SVD retained 10.6% of feature variance; this comparison does not establish that other density-clustering configurations would fail.</div>
<h2>Review the families</h2>
<p>Start with hearing memos, charters, advisories, and publisher-scoped BGT opening statements. Markup versus hearing memo labels conflict in one group; WState filenames mix member and witness statements. Open a family to inspect source labels and low-similarity examples.</p>
<div class="controls"><label>Method<select id="method"><option value="similarity">Conservative similarity</option><option value="template">Exact templates</option><option value="hdbscan">HDBSCAN comparison</option></select></label><label>Format focus<select id="focus"><option value="pdf">At least half PDF records</option><option value="all">All formats</option><option value="xml">At least half XML records</option></select></label><label>Search families, filenames, or domains<input id="search" type="search" placeholder="memo, charter, BGT, disclosure…"></label><label>Review status<select id="review"><option value="all">All groups</option><option value="reviewed">Reviewed samples</option><option value="unreviewed">Unreviewed</option></select></label></div>
<p id="count" role="status" aria-live="polite"></p><div id="groups"></div><button id="more">Show 60 more groups</button>
<h2>What remains outside the groups</h2>
<p>15,178 names with alphabetic text remain ungrouped. Another 9,585 are opaque, numeric, or generic, and 5,763 are caption/media filenames. The alphabetic bucket still contains metadata names and unexplained acronyms; it is not a semantic quality label.</p>
<details><summary>Inspect ten deterministically sampled ungrouped names</summary><div class="group-body" id="tail"></div></details>
<p>Several tail examples already have useful publisher labels: written testimony, amendment, hearing notice, and Truth in Testimony form. Source-context extraction is a separate path to resolving them; more filename clustering alone will not address every case.</p>
<h2>Method and limits</h2>
<p>Original filenames are preserved. Analysis copies decode URL escapes, split case and separators, mask recorded date/opaque-ID tokens and remaining numbers, and preserve explicitly recognized bill references. Character 3–5-grams contribute 65% and word 1–2-grams 35% of TF-IDF similarity. Identical normalized lexical strings count once during modeling. Every similarity-group member has cosine similarity of at least 0.72 to a common anchor; each anchor considers up to 40 neighbors.</p>
<p>Reviews used filename and saved publisher-context samples, including low-similarity members. Labels and source pages are grouped observations; their positions do not establish individual pairings. Full scoped occurrences remain in the frozen Parquet input. Reviews did not inspect document contents or produce independently verified labels. No precision/recall result, automatic kind assignment, production rule, or publication resulted from this run. Numeric masking can hide meaningful distinctions in structured identifiers; original strings remain available for checking.</p>
<p><a href="ranked-groups.csv" download>Download ranked groups CSV</a> · <a href="filename-assignments.csv" download>Download every filename assignment</a> · <a href="reviewed-groups.json" download>Reviewed examples and reasoning</a> · <a href="stats.json">Machine-readable metrics</a></p>
<div class="end">Source hashes and catalog IDs were checked before extraction. Every selected document has one primary review disposition; alternative method memberships remain separate. Reproducible scripts and scope notes: <code>docs/experiments/filename-patterns-20261015/</code>.</div>
</main><script id="data" type="application/json">__DATA__</script><script>
const data=JSON.parse(document.getElementById('data').textContent), byId=id=>document.getElementById(id);let limit=60;
function el(tag,text,cls){const x=document.createElement(tag);if(text!==undefined)x.textContent=text;if(cls)x.className=cls;return x}
function link(url,label){try{const u=new URL(url);if(!['http:','https:'].includes(u.protocol))return el('span',label);const a=el('a',label);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a}catch{return el('span',label)}}
function example(x){const box=el('div',undefined,'example');box.append(el('div',x.filename,'filename'));box.append(el('div','Recorded publisher labels: '+((x.source_link_label||[]).join(' | ')||'Not recorded'),'meta'));if(x.cosine!==undefined)box.append(el('div','Anchor similarity: '+x.cosine.toFixed(3),'meta'));if(x.source_url)box.append(link(x.source_url,'Original source link'));if(x.source_original_page_url?.length){box.append(document.createTextNode(' · '));box.append(link(x.source_original_page_url[0],'Recorded source page (1 of '+x.source_original_page_url.length+')'))}return box}
function card(g){const d=el('details'),s=el('summary'),left=el('div');left.append(el('strong',g.title),el('div',g.group_id+' · '+Object.keys(g.formats).join(', '),'meta'));const right=el('div');right.append(el('span',g.distinct_filenames.toLocaleString()+' names / '+g.documents.toLocaleString()+' document groups','tag'));s.append(left,right);d.append(s);d.addEventListener('toggle',()=>{if(!d.open||d.dataset.loaded)return;d.dataset.loaded='1';const b=el('div',undefined,'group-body');b.append(el('p',g.review?g.review.verdict+' — '+g.review.note:'Unreviewed group. No candidate kind has been assessed.'));b.append(el('p','Frequent terms: '+g.top_terms.slice(0,7).map(x=>x[0]).join(', '),'meta'));b.append(el('p','Domains: '+g.top_domains.map(x=>x[0]+' ('+x[1]+')').join(', '),'meta'));b.append(el('h3','Representative examples'));g.examples.forEach(x=>b.append(example(x)));if(g.boundary_examples){b.append(el('h3','Low-similarity examples'));g.boundary_examples.forEach(x=>b.append(example(x)))}b.append(el('h3','All '+g.distinct_filenames+' member filenames'));const member=el('div',undefined,'members');g.filename_indices.forEach(i=>member.append(el('div',data.names[i][0],'filename')));b.append(member);d.append(b)});return d}
function render(){const method=byId('method').value,focus=byId('focus').value,review=byId('review').value,q=byId('search').value.toLowerCase().trim();const groups=data.groups.filter(g=>g.method===method&&(focus==='all'||(g.formats[focus]||0)>=g.documents*.5)&&(review==='all'||(review==='reviewed')===!!g.review)&&(!q||[g.title,g.group_id,JSON.stringify(g.top_domains),g.review?.note||''].join(' ').toLowerCase().includes(q)||g.filename_indices.some(i=>data.names[i][0].toLowerCase().includes(q))));byId('count').textContent=groups.length.toLocaleString()+' matching groups · showing '+Math.min(limit,groups.length).toLocaleString();byId('groups').replaceChildren(...groups.slice(0,limit).map(card));byId('more').hidden=limit>=groups.length}
['method','focus','search','review'].forEach(id=>byId(id).addEventListener('input',()=>{limit=60;render()}));byId('more').addEventListener('click',()=>{limit+=60;render()});data.tail.forEach(x=>byId('tail').append(example(x)));render();
</script></html>'''


if __name__ == '__main__':
    main()
