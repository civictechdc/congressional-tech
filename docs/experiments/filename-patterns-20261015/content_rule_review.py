"""Compare current and checkpoint PDF readers on development records only."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
import html
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

import pilot_review as review
from pilot_audit import opening_fields
from rule_review import DEFAULT_INPUT, HERE, ROOT, digest

OUTPUT = DEFAULT_INPUT / 'content-rules-v1'
COVER = Path('packages/congress_api/src/congress_api/parsers/document_cover.py')


def worker(pdf, baseline):
    from congress_api.retention import capture_metadata
    if baseline:
        spec = importlib.util.spec_from_file_location('baseline_cover', baseline)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        capture_metadata.document_cover = module.document_cover
        capture_metadata.document_page_fields = module.document_page_fields
    # This invokes the maintained small-body and large-file dispatch. No store
    # is supplied and no metadata parts or capture records are written.
    result = capture_metadata.read_document_file(pdf, pdf.stem, 'development-experiment')
    print(json.dumps(result))


def run():
    labels = json.loads(review.LABELS.read_text())['records']
    assert len(labels) == 140 and all(l['split'] == 'development' for l in labels.values())
    baseline = json.loads((HERE / 'pilot_baseline.json').read_text())
    assert digest(review.SAMPLE) == baseline['summary']['sample_sha256']
    assert digest(review.LABELS) == baseline['summary']['source_hashes'][str(review.LABELS.relative_to(ROOT))]
    OUTPUT.mkdir(exist_ok=True)
    old = subprocess.run(['git', 'show', '38f7557:' + str(COVER)], cwd=ROOT,
                         check=True, capture_output=True).stdout
    old_path = OUTPUT / 'baseline_document_cover.py'
    old_path.write_bytes(old)
    assert digest(old_path) == baseline['summary']['source_hashes'][str(COVER)]
    fingerprint = dict(sample_sha256=digest(review.SAMPLE), labels_sha256=digest(review.LABELS),
                       baseline_parser_sha256=digest(old_path), candidate_parser_sha256=digest(ROOT / COVER),
                       evaluator_sha256=digest(Path(__file__)), scope='development-only',
                       production_ocr=False, fresh_catalog_reconciled=False)
    manifest = OUTPUT / 'manifest.json'
    if manifest.exists():
        assert json.loads(manifest.read_text()) == fingerprint, 'Use a new output directory after code or evidence changes'
    else:
        manifest.write_text(json.dumps(fingerprint, indent=2) + '\n')
    receipts = review.records()
    tasks = []
    for label in labels.values():
        pdf = review.OUT / 'development' / (label['body_sha256'] + '.pdf')
        assert digest(pdf) == label['body_sha256']
        tasks.append((label, pdf))

    def one(task):
        label, pdf = task
        row = dict(review_id=label['review_id'], reference_kind=label['reference_kind'], document_id=label['document_id'])
        for mode in ['baseline', 'candidate']:
            command = [sys.executable, str(Path(__file__)), '--worker', str(pdf)]
            if mode == 'baseline':
                command += ['--baseline', str(old_path)]
            start = time.monotonic()
            try:
                result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
                reading = json.loads(result.stdout) if result.returncode == 0 else dict(status='worker_failed', error_type='exit_' + str(result.returncode))
                reading['diagnostic'] = result.stderr[-4000:]
            except subprocess.TimeoutExpired:
                reading = dict(status='timeout', error_type='30_second_limit')
            row[mode] = dict(reading, elapsed_seconds=round(time.monotonic() - start, 3))
        receipt = receipts[label['document_id']]
        body, = receipt['bodies']
        for mode, key in [('native_text', 'native_text'), ('ocr_assisted', 'text')]:
            pages = {}
            for page in body['pages']:
                review.page_text(receipt, page['page'])  # Verify recorded text before comparison.
                pages[page['page']] = (review.OUT / 'development' / page[key]).read_text()
            row[mode] = opening_fields(pages.get(1, ''), pages.get(2, ''))
        return row

    log = OUTPUT / 'readings.jsonl'
    previous = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    completed = {r['document_id'] for r in previous}
    assert len(completed) == len(previous) and completed <= set(labels)
    with ThreadPoolExecutor(max_workers=3) as pool, log.open('a') as stream:
        for row in pool.map(one, [t for t in tasks if t[0]['document_id'] not in completed]):
            previous.append(row)
            stream.write(json.dumps(row) + '\n'); stream.flush()
            print(len(previous), row['review_id'], flush=True)
    assert len(previous) == 140
    summarize(previous, fingerprint)


def kind(fields):
    return next(iter(fields.get('content_document_kind', [])), '')


def summarize(rows, fingerprint):
    metrics = {}
    for mode in ['baseline', 'candidate', 'native_text', 'ocr_assisted']:
        assigned = [r for r in rows if kind(r[mode])]
        disagreements = [dict(review_id=r['review_id'], expected=r['reference_kind'], observed=kind(r[mode]))
                         for r in assigned if kind(r[mode]) != r['reference_kind']]
        metrics[mode] = dict(assigned=len(assigned), exact_agreements=len(assigned) - len(disagreements),
                            abstentions=len(rows) - len(assigned), disagreements=disagreements,
                            errors=[r['review_id'] for r in rows if r[mode].get('status') in {'failed', 'worker_failed', 'timeout'}],
                            per_kind=dict(Counter(kind(r[mode]) for r in assigned)))
    changed_prior = [r['review_id'] for r in rows if kind(r['baseline']) and kind(r['baseline']) != kind(r['candidate'])]
    newly_assigned = [r['review_id'] for r in rows if not kind(r['baseline']) and kind(r['candidate'])]
    summary = dict(**fingerprint, records=len(rows), metrics=metrics, changed_prior_kinds=changed_prior,
                   newly_assigned=newly_assigned, reference_reviewer='assistant', human_validated=False,
                   readings_sha256=digest(OUTPUT / 'readings.jsonl'),
                   limitations='Development-only balanced sample. No held-out or full-catalog qualification. Existing retained body readings require explicit reprocessing; a rebuild alone does not refresh them.')
    (OUTPUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    with (OUTPUT / 'comparison.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['review_id', 'document_id', 'reference_kind', 'baseline_pdf', 'candidate_pdf', 'native_text', 'ocr_assisted'])
        for row in sorted(rows, key=lambda row: row['review_id']):
            writer.writerow([row['review_id'], row['document_id'], row['reference_kind'], *[kind(row[m]) for m in metrics]])
    content = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>Content rule development review</title>
<style>body{font:16px/1.5 system-ui;max-width:1000px;margin:40px auto;padding:0 20px}pre{white-space:pre-wrap}a{color:#075b9c}</style>
<h1>Content rule development review</h1><p>Three content recognizers in congress_api: operative amendments, published House hearings and committee vote sheets. No production OCR. Reference labels are assistant-reviewed.</p>
<p><a href="comparison.csv">All 140 development comparisons</a> · <a href="summary.json">Counts and parser hashes</a> · <a href="../pilot-v1/baseline/report.html">Frozen pilot baseline</a></p>'''
    content += '<pre>' + html.escape(json.dumps(summary, indent=2)) + '</pre></html>'
    (OUTPUT / 'report.html').write_text(content)
    print(json.dumps(metrics, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    OUTPUT = args.output
    worker(args.worker, args.baseline) if args.worker else run()
