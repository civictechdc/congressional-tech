"""Join manually reviewed content findings to exact, hashed source PDFs."""
from collections import Counter
import csv
import html
import json
from pathlib import Path

from rule_review import DEFAULT_INPUT, HERE, digest


def main():
    out = DEFAULT_INPUT / 'content-validation-v1'
    manifest = json.loads((out/'sample.json').read_text())
    retrieval = {r['document_id']:r for r in json.loads((out/'publisher-retrieval.json').read_text())}
    annotations = json.loads((HERE/'content_adjudications.json').read_text())
    assert [a['sample'] for a in annotations] == list(range(1,len(manifest['records'])+1))
    old_rules = json.loads((DEFAULT_INPUT/'rule-review-v2/rule-review.json').read_text())
    shown = {s['filename'] for r in old_rules for s in r['examples']}
    rows=[]
    for a,r in zip(annotations,manifest['records']):
        fetched = retrieval[r['document_id']]['attempts'][-1]
        assert fetched['matches_retained_digest']
        assert digest(Path(fetched['pdf'])) == fetched['sha256']
        assert fetched['sha256'] in {Path(k).name.removesuffix('.gz') for k in r['body_keys']}
        if a['verdict'] in {'supported','subtype_unconfirmed'}:
            assert r['filename'] not in shown
        row = {'sample':a['sample'],'document_id':r['document_id'],'filename':r['filename'],
               'selection':r['selection'],'proposed_kinds':r['proposed_kinds'],
               'content_kind':a['kind'],'verdict':a['verdict'],'evidence_note':a['note'],
               'reviewed_pages':[1,2] if a['sample']==7 else [1],
               'review_method':'page_image_and_text' if (out/f'page-{a["sample"]:02}.png').exists() else 'extracted_page_text',
               'page_count':fetched['pages'],'sha256':fetched['sha256'],
               'matches_retained_digest':True,'publisher_url':fetched['url'],
               'final_url':fetched['final_url'],'pdf':fetched['pdf'],'text':fetched['text'],
               'original_status':r['status'],'source_evidence':r['source_evidence'],
               'decision_scope':'reviewed_sample_only','production_change':False}
        rows.append(row)
    assert len({r['document_id'] for r in rows})==38
    rule_rows=[]
    for rule in old_rules:
        selected=[r for r in rows if rule['rule_id'] in r['selection']]
        assert len(selected)==3
        assert len({r['filename'] for r in selected})==3
        rule_rows.append({'rule_id':rule['rule_id'],'population_matches':rule['unique_document_count'],
                          'reviewed_samples':3,'verdicts':dict(Counter(r['verdict'] for r in selected)),
                          'next_step':'resolve_opening_subtype' if rule['rule_id']=='opening.science' else
                                      'taxonomy_decision_and_broader_validation' if rule['rule_id']=='charter.science' else
                                      'broader_validation','production_ready':False})
    for filename,data in [('adjudications.json',rows),('rule-validation.json',rule_rows)]:
        (out/filename).write_text(json.dumps(data,indent=2)+'\n')
    with (out/'adjudications.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader()
        for r in rows:
            writer.writerow({k:json.dumps(v) if isinstance(v,(list,dict)) else v for k,v in r.items()})
    with (out/'rule-validation.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rule_rows[0]));writer.writeheader()
        for r in rule_rows:
            writer.writerow({k:json.dumps(v) if isinstance(v,dict) else v for k,v in r.items()})
    stats={'sample_documents':len(rows),'rule_sample_slots':36,'distinct_rule_sample_documents':35,
           'exact_retained_digest_matches':38,'extraction_counts':dict(Counter(retrieval[r['document_id']]['attempts'][-1]['status'] for r in rows)),
           'verdict_counts':dict(Counter(r['verdict'] for r in rows)),
           'rules':len(rule_rows),'rules_with_three_fresh_samples':12,
           'production_changes':0,'review_scope':'First-page document-kind review, plus the attached resume start for sample 7. This is not full-document factual verification.',
           'sample_sha256':digest(out/'sample.json'),'adjudications_source_sha256':digest(HERE/'content_adjudications.json'),
           'retrieval_sha256':digest(out/'publisher-retrieval.json'),
           'limitations':['Purposeful small sample, not an unbiased accuracy estimate. No rule is production-qualified.',
                          'Both files in the two conflicts support memorandum; do not generalize that filename always outranks source labels.',
                          'Two OS conference-remarks files support member statements but do not explicitly prove the opening subtype.',
                          'Notice/memorandum and opening-remarks/press-release overlap requires a documented primary-kind convention.',
                          'All retained-object reads were denied; all publisher PDF bytes independently match the recorded retained SHA-256 digests.',
                          '33 PDFs yielded text; five scans required page-image inspection. Some text layers are imperfect.']}
    for name,expected in manifest['input_sha256'].items():
        assert digest(DEFAULT_INPUT/'rule-review-v2'/name)==expected
    (out/'verification.json').write_text(json.dumps(stats,indent=2)+'\n')
    esc=html.escape
    cards=[]
    for r in rows:
        pdf=Path(r['pdf']).relative_to(out).as_posix()
        preview=f'<a href="page-{r["sample"]:02}.png">Reviewed page image</a> · ' if (out/f'page-{r["sample"]:02}.png').exists() else ''
        cards.append(f'<details><summary>{r["sample"]:02} · {esc(r["filename"])} <span>{esc(r["verdict"])}</span></summary><p>{esc(r["evidence_note"])}</p><p>Content kind: <b>{esc(r["content_kind"])}</b> · {r["page_count"]} PDF pages · inspected pages {esc(str(r["reviewed_pages"]))}</p><p>{preview}<a href="{esc(pdf)}">Exact PDF</a> · <a href="{esc(pdf.removesuffix(".pdf")+".txt")}">Extracted text</a></p><p>SHA-256 matches retained body: <code>{r["sha256"]}</code></p></details>')
    table=''.join(f'<tr><td>{esc(r["rule_id"])}</td><td>{r["population_matches"]:,}</td><td>{esc(json.dumps(r["verdicts"]))}</td><td>{esc(r["next_step"])}</td></tr>' for r in rule_rows)
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Content validation of filename rules</title><style>body{font:16px/1.5 system-ui;max-width:1150px;margin:3rem auto;padding:0 24px;color:#20312f;background:#fafbf9}a{color:#175c50}details{padding:15px 0;border-top:1px solid #becbc4}summary{cursor:pointer;overflow-wrap:anywhere}summary span{font-size:13px;color:#52685e}code{overflow-wrap:anywhere}td,th{text-align:left;padding:8px;border-bottom:1px solid #dde5df}table{font-size:14px;width:100%}input{width:95%;padding:12px;margin:20px 0}</style>
<h1>Content validation of filename rules</h1>
<p>38 documents inspected · all 38 match retained content hashes · no production classifications changed.</p>
<p>Three fresh filenames per rule gave 36 review slots across 35 distinct documents: 33 supported the proposed kind; two conference remarks did not explicitly establish the opening-statement subtype. Two additional conflicts resolve to memoranda, and one excluded vote-topic control is an amendment.</p>
<p>Review scope: the complete first page of each document, plus the start of the attached resume in one disclosure file. Five scans required images. This small, deliberately varied sample is not a precision estimate.</p>
<h2>What the content changes</h2><ul>
<li>Keep source disagreements visible. Both conflict PDFs are memoranda despite incorrect notice/disclosure link labels.</li>
<li>Classify purpose separately from presentation. Notices can use memorandum formatting; opening remarks can be published as press releases; witness lists can include agendas.</li>
<li>Keep Science OS inference provisional. Two conference remarks support member statements, but the exact opening subtype remains unconfirmed.</li>
<li>Keep hearing-charter as a proposed taxonomy addition; the three sampled documents explicitly use that title.</li></ul>
<h2>Path forward</h2><ol><li>Record the primary-kind convention and retain secondary form/role evidence.</li><li>Expand validation by rule, publisher and filename layout, including hard negatives and a random held-out sample. Measure accuracy and missing-content rates separately.</li><li>Promote only supported scopes to the maintained reader with regression fixtures; rerun the frozen population and review changes before any catalog publication.</li></ol>
<p><a href="adjudications.csv">All 38 content decisions</a> · <a href="rule-validation.csv">Rule validation CSV</a> · <a href="verification.json">Verification</a> · <a href="sample.json">Frozen sample</a> · <a href="../rule-review-v2/report.html">Original rule review</a></p>'''
    page+='<table><thead><tr><th>Rule</th><th>Population matches</th><th>Three-sample result</th><th>Next step</th></tr></thead><tbody>'+table+'</tbody></table>'
    page+='<h2>Document evidence</h2><input aria-label="Filter evidence" placeholder="Filter filenames, verdicts or evidence" oninput="document.querySelectorAll(\'details\').forEach(d=>d.hidden=!d.textContent.toLowerCase().includes(this.value.toLowerCase()))">'+''.join(cards)+'</html>'
    (out/'report.html').write_text(page)
    print(json.dumps(stats,indent=2))


if __name__=='__main__':main()
