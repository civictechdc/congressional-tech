"""Verify frozen pilot evidence and report development-only reader diagnostics.

No network access, runtime changes, held-out text classification or catalog writes.
"""
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import html
import json
from pathlib import Path

import pilot_review as review
from rule_review import HERE, ROOT, digest
from congress_api.parsers import document_cover


def opening_fields(first, second):
    """Follow the maintained caller's page policy using saved extracted text."""
    fields = document_cover.document_page_fields(first)
    if not fields and not first.strip():
        fallback = document_cover.document_page_fields('', second)
        if fallback.get('content_document_kind') == ['transcript']:
            fields = fallback
    return fields


def audit():
    sample = json.loads(review.SAMPLE.read_text())['records']
    rows = review.records()
    labels_file = json.loads(review.LABELS.read_text())
    labels = labels_file['records']
    assert len(sample) == len(rows) == len({r['document_id'] for r in sample}) == 400
    assert set(rows) == {r['document_id'] for r in sample}
    assert labels_file['sample_sha256'] == digest(review.SAMPLE)
    assert set(labels) <= set(rows)
    assert all(label['split'] == 'development' for label in labels.values()), 'Held-out labels require a later evaluation phase'
    by_split = defaultdict(Counter)
    body_ids = defaultdict(set)
    expected_ids = defaultdict(set)
    attempts = Counter()
    baseline = {}
    audit_rows = []
    page_methods = Counter()
    repair_path = review.OUT / 'extraction-repairs.jsonl'
    for split in ['development', 'held-out']:
        selected = review.selected(split)
        assert len(selected) == 200
        for number, original in enumerate(selected, 1):
            identity = ('D' if split == 'development' else 'H') + f'{number:03}'
            row = rows[original['document_id']]
            assert row['split'] == split
            expected = {Path(key).stem for key in original.get('body_keys') or []}
            expected_ids[split].update(expected)
            for attempt in row['attempts']:
                attempts[attempt['transport'] + ':' + attempt['status']] += 1
            directory = review.OUT / split
            for body in row['bodies']:
                sha = body['sha256']
                assert sha in expected
                assert digest(directory / (sha + '.pdf')) == sha
                body_ids[split].add(sha)
                by_split[split]['matched_bodies'] += 1
                for page in body.get('pages', []):
                    assert digest(directory / page['text']) == page['text_sha256']
                    page_methods[review.selected_method(row, page)] += 1
            state = ('ready_for_reference_review' if row['status'] == 'review_ready'
                     else 'needs_visual_review' if row['bodies'] else 'unavailable_exact_body')
            label = labels.get(row['document_id'])
            record = dict(review_id=identity, document_id=row['document_id'], split=split,
                          availability=state, reference_kind='', evidence_page='', evidence_quote='',
                          selected_text_method='', native_reader_kind='', assisted_reader_kind='')
            if label:
                assert label['review_id'] == identity and label['split'] == split
                text, page, sha = review.page_text(row, label['evidence_page'])
                assert label['body_sha256'] == sha
                assert label['text_sha256'] == page['text_sha256']
                assert ' '.join(label['evidence_quote'].split()).casefold() in ' '.join(text.split()).casefold()
                assert label['extraction_method'] == review.selected_method(row, page)
                by_split[split]['reference_labels'] += 1
                record.update(reference_kind=label['reference_kind'], evidence_page=label['evidence_page'],
                              evidence_quote=label['evidence_quote'], selected_text_method=label['extraction_method'])
                body, = row['bodies']
                predictions = {}
                for mode, key in [('native', 'native_text'), ('assisted', 'text')]:
                    pages = {p['page']: (directory / p[key]).read_text() for p in body['pages']}
                    fields = opening_fields(pages.get(1, ''), pages.get(2, ''))
                    predictions[mode] = fields
                    record[mode + '_reader_kind'] = next(iter(fields.get('content_document_kind', [])), '')
                baseline[identity] = dict(document_id=row['document_id'], reference_kind=label['reference_kind'], **predictions)
            by_split[split][state] += 1
            audit_rows.append(record)
    assert not (body_ids['development'] & body_ids['held-out'])
    assert not (expected_ids['development'] & expected_ids['held-out'])
    metrics = {}
    for mode in ['native', 'assisted']:
        assigned = [r for r in audit_rows if r[mode + '_reader_kind']]
        disagreements = [r for r in assigned if r[mode + '_reader_kind'] != r['reference_kind']]
        metrics[mode] = dict(labeled_development=len(labels), assigned=len(assigned),
            exact_agreements=len(assigned) - len(disagreements), abstentions=len(labels) - len(assigned),
            disagreements=[dict(review_id=r['review_id'], reference_kind=r['reference_kind'],
                                reader_kind=r[mode + '_reader_kind']) for r in disagreements])
    per_kind = {}
    for kind in sorted({r['reference_kind'] for r in audit_rows if r['reference_kind']}):
        group = [r for r in audit_rows if r['reference_kind'] == kind]
        per_kind[kind] = dict(reference_count=len(group), **{
            mode + '_exact_agreements': sum(r[mode + '_reader_kind'] == kind for r in group)
            for mode in ['native', 'assisted']})
    sources = [HERE / name for name in ['pilot_extract.py', 'pilot_review.py', 'pilot_audit.py', 'pilot_adjudications.json']]
    sources += [Path(document_cover.__file__)]
    originals = [json.loads(line) for line in (review.OUT / 'receipts.jsonl').read_text().splitlines()]
    summary = dict(
        checked_at=datetime.now(timezone.utc).isoformat(), sample_sha256=digest(review.SAMPLE),
        records=400, splits=dict(by_split), distinct_matched_bodies=sum(map(len, body_ids.values())),
        original_extraction_errors=sum(b['status'] == 'extraction_error' for r in originals for b in r['bodies']),
        repair_receipts=len(repair_path.read_text().splitlines()),
        remaining_extraction_errors=sum(b['status'] == 'extraction_error' for r in rows.values() for b in r['bodies']),
        selected_page_methods=dict(page_methods), retrieval_attempts=dict(attempts),
        original_document_processing_seconds_sum=round(sum(r['elapsed_seconds'] for r in originals), 2),
        timing_limit='Sum of per-document original attempts, not wall time. OCR repairs and review time were not timed.',
        cost='Local tools and publisher HTTP requests; no paid model API used. CPU and network cost not metered.',
        reference_reviewer='assistant', human_validated=False,
        reference_scope='Opening-page excerpts plus recorded second-page checks; not full-document legal or factual review.',
        catalog_eligibility='Pending fresh 3.1.0 catalog. No sample substitutions or held-out evaluation.',
        source_hashes={str(p.relative_to(ROOT)): digest(p) for p in sources},
        receipt_hashes={p.name: digest(p) for p in [review.OUT / 'receipts.jsonl', repair_path]},
        baseline_limit='Existing document_page_fields rules on saved Poppler/native and OCR-assisted text, following caller page policy. Not end-to-end pypdf runtime performance or held-out accuracy.',
        development_diagnostics=metrics, per_kind=per_kind)
    (review.OUT / 'audit-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (review.OUT / 'development-baseline.json').write_text(json.dumps(baseline, indent=2) + '\n')
    with (review.OUT / 'review-ledger.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(audit_rows[0]))
        writer.writeheader(); writer.writerows(audit_rows)
    render(summary, audit_rows)
    print(json.dumps({key: summary[key] for key in ['records', 'splits', 'distinct_matched_bodies', 'development_diagnostics', 'per_kind']}, indent=2))


def render(summary, rows):
    esc = lambda value: html.escape(str(value))
    dev = summary['splits']['development']
    held = summary['splits']['held-out']
    cards = f'<p><b>400 selected · {summary["distinct_matched_bodies"]} exact bodies · {dev["reference_labels"]} development labels · 0 held-out evaluations</b></p>'
    counts = ''.join(f'<tr><td>{esc(kind)}</td><td>{values["reference_count"]}</td><td>{values["native_exact_agreements"]}</td><td>{values["assisted_exact_agreements"]}</td></tr>' for kind, values in summary['per_kind'].items())
    evidence = ''.join('<tr>' + ''.join(f'<td>{esc(row[key])}</td>' for key in ['review_id', 'reference_kind', 'evidence_page', 'evidence_quote', 'native_reader_kind', 'assisted_reader_kind']) + '</tr>' for row in rows if row['reference_kind'])
    content = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Frozen PDF pilot</title>
<style>body{{font:16px/1.5 system-ui;margin:40px auto;padding:0 24px;max-width:1200px;color:#24313b}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:9px;border-bottom:1px solid #ccd4da;text-align:left;vertical-align:top}}th{{background:#edf2f5}}code{{overflow-wrap:anywhere}}a{{color:#075b9c}}</style>
<h1>Frozen PDF pilot: development review</h1>{cards}
<p>Assistant-reviewed reference labels, not independently validated human ground truth. These labels describe document form; they do not endorse document claims. Review used opening-page excerpts and recorded additional pages. No new runtime rules or catalog kinds were added.</p>
<p>Development: {dev['ready_for_reference_review']} readable, {dev.get('needs_visual_review',0)} awaiting visual review, {dev.get('unavailable_exact_body',0)} unavailable exact bodies. Held-out: {held['ready_for_reference_review']} readable, {held.get('needs_visual_review',0)} awaiting visual review, {held.get('unavailable_exact_body',0)} unavailable exact bodies. Held-out text was extracted separately and has not been reviewed for reference labels or classified.</p>
<p>The 3.1.0 publication and fresh-catalog eligibility reconciliation remain prerequisites for held-out evaluation. The frozen sample is balanced across strata and does not estimate population-wide accuracy or coverage.</p>
<p><a href="review-ledger.csv">All 400 review states (CSV)</a> · <a href="audit-summary.json">Verified counts and code hashes</a> · <a href="development-baseline.json">Development reader outputs</a></p>
<h2>Existing reader diagnostic</h2><p>These counts apply the maintained text rules to saved opening pages, with the existing restricted second-page policy. Native and OCR-assisted text are separate inputs. This is a development diagnostic, not an end-to-end production benchmark.</p>
<pre>{esc(json.dumps(summary['development_diagnostics'], indent=2))}</pre>
<h2>Reference types and exact agreements</h2><table><thead><tr><th>Reference kind</th><th>Reviewed</th><th>Native reader</th><th>OCR-assisted reader</th></tr></thead><tbody>{counts}</tbody></table>
<h2>Recommended next work</h2><ol><li>Verify the active publication, reconcile every pilot ID and replay filename version 3.2.0 against the full catalog.</li><li>Use the development examples to qualify bounded content rules for explicit amendments, House published hearings and committee vote sheets. Require headings and document structure; preserve ambiguous cases as abstentions.</li><li>Settle mixed packets and external-document types separately. Keep filename grammar in house_naming and PDF recognition in congress_api.</li><li>Freeze candidate code and thresholds before held-out review. Report coverage, errors and abstentions by kind, including acquisition failures. Seek human review before treating assistant labels as release qualification.</li></ol>
<details><summary>All development reference evidence ({dev['reference_labels']} records)</summary><table><thead><tr><th>ID</th><th>Reference kind</th><th>Page</th><th>Evidence quote</th><th>Native output</th><th>Assisted output</th></tr></thead><tbody>{evidence}</tbody></table></details>
<p>Original failure receipts are retained. {summary['repair_receipts']} extraction receipts were retried from the same verified bytes after correcting an OCR image-path bug; {summary['remaining_extraction_errors']} reader errors remain. OCR attempt metadata is distinguished from the text actually selected. Timing excludes repairs and review; no paid model API was used.</p></html>'''
    (review.OUT / 'report.html').write_text(content)


if __name__ == '__main__':
    audit()
