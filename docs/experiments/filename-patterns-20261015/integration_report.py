"""Verify and report the frozen-population replay and manual PDF checks."""
from collections import Counter
import csv
import gzip
import hashlib
import html
import json
from pathlib import Path
import re

import pyarrow.parquet as pq
from congress_api.parsers.document_types import document_label_kind
from congress_api.retention.document_index import parser_fingerprint
from rule_review import DEFAULT_INPUT, HERE, ROOT, digest, role_gate


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k:json.dumps(v) if isinstance(v, (list, dict)) else v for k,v in row.items()})


def content_results(directory, annotations):
    out = DEFAULT_INPUT / directory
    sample = json.loads((out / 'sample.json').read_text())['records']
    retrieval = {r['document_id']:r for r in json.loads((out / 'publisher-retrieval.json').read_text())}
    decisions = json.loads((HERE / annotations).read_text())
    assert [r['sample'] for r in decisions] == list(range(1, len(sample) + 1))
    rows = []
    for source, decision in zip(sample, decisions):
        fetched = retrieval[source['document_id']]['attempts'][-1]
        verdict = decision.get('verdict', 'supported')
        if verdict != 'unavailable':
            assert fetched['matches_retained_digest']
            assert digest(Path(fetched['pdf'])) == fetched['sha256']
            assert fetched['sha256'] in {Path(k).name.removesuffix('.gz') for k in source['body_keys']}
        rows.append({
            'sample':decision['sample'], 'document_id':source['document_id'],
            'filename':source['filename'], 'selection':source['selection'],
            'proposed_kinds':source.get('proposed_kinds') or source['document_kind'],
            'verdict':verdict, 'reviewed_pages':decision.get('pages', [1]),
            'method':decision.get('method', 'text') if verdict != 'unavailable' else 'not_read',
            'note':decision['note'], 'sha256':fetched.get('sha256'),
            'retained_digest_matches':fetched.get('matches_retained_digest', False),
            'pdf_pages':fetched.get('pages'), 'pdf':fetched.get('pdf'),
            'publisher_url':fetched['url'], 'retrieval_status':fetched['status'],
        })
    (out / 'adjudications.json').write_text(json.dumps(rows, indent=2) + '\n')
    write_csv(out / 'adjudications.csv', rows)
    return rows


def main():
    out = DEFAULT_INPUT / 'integration-v3'
    stats = json.loads((out / 'stats.json').read_text())
    assert digest(DEFAULT_INPUT / 'documents.parquet') == stats['input_sha256']
    assert parser_fingerprint() == stats['filename_fingerprint']
    for name, expected in stats['module_hashes'].items():
        assert digest(ROOT / name) == expected
    baseline = {r['document_id']:r for line in gzip.open(DEFAULT_INPUT / 'integration-baseline/results.jsonl.gz', 'rt')
                if (r := json.loads(line))}
    results = [json.loads(line) for line in gzip.open(out / 'results.jsonl.gz', 'rt')]
    current = {r['document_id']:r for r in results}
    assert len(results) == len(current) == len(baseline) == stats['documents']
    assert current.keys() == baseline.keys()
    assert Counter(r['status'] for r in results) == stats['counts']
    classified = [r for r in results if r['status'] == 'classified']
    assert all(baseline[r['document_id']]['status'] == 'unresolved' for r in classified)
    write_csv(out / 'classifications.csv', classified)
    formats = Counter()
    gates = Counter()
    broad_markers = Counter()
    label_hints = 0
    unproven_hints = 0
    # These are deliberately broad diagnostic searches, never classifiers.
    patterns = {'memo':r'memo', 'opening':r'opening', 'testimony':r'testimony',
                'vote':r'vote', 'amendment':r'amend|amndt|amdt',
                'malformed_statement_slot':r'hhrg.*[wm]state',
                'ssm':r'(?<![a-z])ssm(?![a-z])'}
    remaining_pdf = []
    for batch in pq.ParquetFile(DEFAULT_INPUT / 'documents.parquet').iter_batches():
        for row in batch.to_pylist():
            status = current[row['document_id']]['status']
            if status == 'role_review':
                gates[role_gate(row)] += 1
            elif status == 'unresolved':
                formats.update(row.get('format') or ['unknown'])
                for name, pattern in patterns.items():
                    if re.search(pattern, row['filename'], re.I):
                        broad_markers[name] += 1
                anchors = [o for o in row.get('source_occurrences') or []
                           if o.get('source_occurrence_scope') == ['anchor']]
                known = [o for o in anchors if any(document_label_kind(v) for v in o.get('source_link_label') or [])]
                label_hints += bool(known)
                unproven_hints += any('user_accepted_url_variant' in (o.get('source_association_basis') or []) for o in known)
                if row['filename'].lower().endswith('.pdf'):
                    remaining_pdf.append({
                        'document_id':row['document_id'], 'filename':row['filename'],
                        'source_url':row['source_url'], 'source_link_label':row['source_link_label'],
                        'anchor_count':len(anchors),
                        'association_bases':sorted({b for o in anchors for b in o.get('source_association_basis') or []}),
                    })
    remaining_pdf.sort(key=lambda r:hashlib.sha256(('remaining-review-20261015' + r['document_id']).encode()).hexdigest())
    write_csv(out / 'remaining-sample.csv', remaining_pdf[:100])
    fresh = content_results('integration-content-v1', 'integration_adjudications.json')
    residual = content_results('residual-content-v1', 'residual_adjudications.json')
    old_ids = {r['document_id'] for r in json.loads((DEFAULT_INPUT / 'content-validation-v1/adjudications.json').read_text())}
    assert not old_ids & {r['document_id'] for r in fresh}
    assert not old_ids & {r['document_id'] for r in residual}
    assert len({r['document_id'] for r in fresh + residual}) == 82
    assert Counter(r['verdict'] for r in fresh) == {'supported':58, 'supported_with_source_subtype':3}
    assert Counter(r['verdict'] for r in residual) == {'supported':18, 'unavailable':3}
    test_counts = {}
    for name in ['integration-house-tests-final.log', 'integration-catalog-tests-final.log']:
        text = (DEFAULT_INPUT / name).read_text()
        count = re.search(r'(\d+) passed in ', text)
        assert count and 'failed' not in text.lower()
        test_counts[name] = int(count[1])
    summary = {
        'classified_records':len(classified),
        'distinct_classified_filenames':len({r['filename'] for r in classified}),
        'eligible_records':len(classified) + stats['counts']['unresolved'],
        'classification_evidence':dict(Counter(','.join(r['document_kind_source']) for r in classified)),
        'unresolved_records':stats['counts']['unresolved'], 'remaining_formats':dict(formats),
        'role_review_reasons':dict(gates),
        'remaining_broad_filename_markers':dict(broad_markers),
        'remaining_records_with_known_label_hints':label_hints,
        'remaining_records_with_unproven_url_variant_label_hints':unproven_hints,
        'fresh_content_checks':dict(Counter(r['verdict'] for r in fresh)),
        'residual_content_checks':dict(Counter(r['verdict'] for r in residual)),
        'tests':test_counts,
        'scope':'Local maintained-reader integration and frozen named-population replay. No full catalog rebuild or publication.',
        'sample_limit':'Small stratified and purposeful samples do not estimate population precision. Content checks inspect identified pages, not full documents.',
        'stopping_reason':'The prior integrated replay assigned 9180 records; the final bounded extension adds 247 (2.7%). Remaining broad markers include topic mentions, unverified associations and ambiguous publisher slots. Further work includes body/association recovery and additional native publisher identifier formats.',
    }
    (out / 'verification.json').write_text(json.dumps(summary, indent=2) + '\n')
    esc = html.escape
    kind_rows = ''.join(f'<tr><td>{esc(kind)}</td><td>{count:,}</td></tr>' for kind,count in sorted(stats['kinds'].items(), key=lambda kv:-kv[1]))
    cards = []
    for directory, rows in [('integration-content-v1', fresh), ('residual-content-v1', residual)]:
        for r in rows:
            evidence = ''
            if r['pdf']:
                relative = Path(r['pdf']).resolve().relative_to(DEFAULT_INPUT).as_posix()
                evidence = f'<a href="../{esc(relative)}">Exact PDF</a>'
            cards.append(f'<details><summary>{esc(directory)} / {r["sample"]} · {esc(r["filename"])} · {esc(r["verdict"])}</summary><p>{esc(r["note"])}</p><p>Reviewed PDF pages {r["reviewed_pages"]}; method: {esc(r["method"])}. {evidence}</p></details>')
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Document-kind integration results</title>
<style>body{font:16px/1.5 system-ui;max-width:1100px;margin:3rem auto;padding:0 24px;color:#20312f;background:#fafbf9}a{color:#175c50}details{padding:13px 0;border-top:1px solid #becbc4}summary{cursor:pointer;overflow-wrap:anywhere}td,th{text-align:left;padding:7px 15px;border-bottom:1px solid #dde5df}table{font-size:14px}input{width:95%;padding:12px;margin:20px 0}</style>
<h1>Document-kind integration results</h1>
<p><strong>9,427 previously unclassified records now have a kind, across 9,410 distinct filenames.</strong> The maintained reader now recognizes 15 reviewed filename conventions and explicit publisher document labels. The source fallback requires attributable, agreeing anchors.</p>
<p>6,142 assignments come from filenames and publisher scope; 3,285 come from source context. This resolves 28.1% of the 33,548 records eligible for this named-document pass. The 623,555 records flagged for role review remain separate. This is an 80/20 pass over useful hints, not a claim that 80% of all unknown records are resolved.</p>
<p><strong>Verified locally:</strong> 4,561 filename tests and 517 catalog tests passed. The actual index-writer test checks both catalog tables and a cached source-context refresh. The frozen input hash and every record ID are conserved. No catalog was published or fully rebuilt.</p>
<h2>What changed</h2><ul><li>Publisher-specific memo, disclosure, charter, notice, witness-list, opening-statement, vote and amendment patterns; plus Transportation SSM and Resources testimony layouts.</li><li>Exact publisher labels fill gaps in opaque filenames, with conflicting or unknown anchor claims left unresolved. Guessed URL variants do not establish source association.</li><li>The new hearing-charter kind describes explicitly titled charters. A document's purpose determines its primary kind: a notice can use memorandum formatting, an opening statement can appear in a press release, and a witness list can include an agenda.</li><li>Original filename characters, dates, identifiers and source claims remain available. Filename evidence is not a claim that every matched document body was read.</li></ul>
<h2>Evidence and remaining work</h2><p>61 fresh stratified documents support the integrated kinds. Three opening-statement subtypes rely on explicit publisher labels while their PDFs confirm member statements. Another 18 body checks support six residual patterns. All 79 fetched PDFs match retained hashes. Three joint-committee MState samples returned 404; that proposed filename family remains unpromoted.</p>
<p>The earlier 38-document review found two conference OS examples whose opening subtype was unconfirmed, so that shorthand remains excluded. Across all three rounds, 117 PDFs were read on the recorded pages. These small samples are not a population accuracy estimate.</p>
<p>24,121 eligible records remain unresolved. The last extension added 247 classifications, only 2.7% beyond the prior 9,180. The next useful phase is document-content extraction and recovery of exact source associations, particularly for surname/date filenames, malformed statement slots, amendment identifiers and XML/API records. Generic labels, topic words and uncertain shorthand should remain unclassified.</p>
<p><a href="classifications.csv">All 9,427 assignments</a> · <a href="remaining-sample.csv">100 remaining PDF records</a> · <a href="verification.json">Verification and residual counts</a> · <a href="stats.json">Replay hashes and totals</a> · <a href="../integration-content-v1/adjudications.csv">61 fresh content checks</a> · <a href="../residual-content-v1/adjudications.csv">21 residual sample outcomes</a> · <a href="../content-validation-v1/report.html">Earlier 38-document review</a></p>
<h2>New assignments by kind</h2><table><thead><tr><th>Kind</th><th>Records</th></tr></thead><tbody>'''
    page += kind_rows + '</tbody></table><h2>Fresh document evidence</h2><input aria-label="Filter evidence" placeholder="Filter filenames or findings" oninput="document.querySelectorAll(\'details\').forEach(d=>d.hidden=!d.textContent.toLowerCase().includes(this.value.toLowerCase()))">' + ''.join(cards) + '</html>'
    (out / 'report.html').write_text(page)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
