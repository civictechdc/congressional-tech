"""Verify the bounded continuation and generate its reviewable evidence report."""
from collections import Counter
import csv
import gzip
import html
import json
from pathlib import Path
import re

from continuation import save
from rule_review import DEFAULT_INPUT, HERE, ROOT, digest
from congress_api.retention.document_index import parser_fingerprint


def main():
    out = DEFAULT_INPUT / 'continuation-v1'
    prepared = json.loads((out / 'preparation.json').read_text())
    stats = json.loads((out / 'replay/stats.json').read_text())
    assert prepared['input_sha256'] == stats['input_sha256'] == digest(DEFAULT_INPUT / 'documents.parquet')
    assert prepared['baseline_sha256'] == digest(DEFAULT_INPUT / 'integration-v3/results.jsonl.gz')
    assert stats['filename_fingerprint'] == parser_fingerprint()
    for path, sha in stats['module_hashes'].items():
        assert digest(ROOT / path) == sha
    additions, regressions, changed, total, preserved = [], [], [], 0, 0
    with gzip.open(DEFAULT_INPUT / 'integration-v3/results.jsonl.gz', 'rt') as before, gzip.open(out / 'replay/results.jsonl.gz', 'rt') as after:
        for old_line, new_line in zip(before, after, strict=True):
            old, new = json.loads(old_line), json.loads(new_line)
            assert old['document_id'] == new['document_id']
            assert old['role_review'] == new['role_review']
            total += 1
            if old['status'] == 'classified':
                if new['status'] != 'classified':
                    regressions.append(new)
                elif old['document_kind'] != new['document_kind']:
                    changed.append(dict(before=old, after=new))
                else:
                    preserved += 1
            elif new['status'] == 'classified':
                assert old['status'] == 'unresolved'
                additions.append(new)
    assert total == stats['documents'] == 657103
    assert not changed and not regressions
    assert preserved == 9427
    assert len(additions) + preserved == stats['counts']['classified']
    with (out / 'new-classifications.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['document_id', 'filename', 'source_url', 'document_kind', 'document_kind_source'], extrasaction='ignore')
        writer.writeheader()
        for row in additions:
            writer.writerow({k: '|'.join(v) if isinstance(v, list) else v for k, v in row.items()})

    annotations = json.loads((HERE / 'native_adjudications.json').read_text())
    evidence = []
    for directory, reviews in annotations.items():
        selected = json.loads((out / directory / 'sample.json').read_text())['records']
        receipts = {r['document_id']: r for r in json.loads((out / directory / 'publisher-retrieval.json').read_text())}
        assert [r['document_id'] for r in selected] == [r['document_id'] for r in reviews]
        for record, review in zip(selected, reviews, strict=True):
            assert record['filename'] == review['filename']
            receipt = receipts[record['document_id']]['attempts'][-1]
            pdf = None
            if review['verdict'] != 'unavailable':
                assert receipt['matches_retained_digest']
                assert receipt['sha256'] == digest(Path(receipt['pdf']))
                assert receipt['sha256'] in {Path(k).name.removesuffix('.gz') for k in record['body_keys']}
                pdf = Path(receipt['pdf']).resolve().relative_to(out.resolve()).as_posix()
            else:
                assert receipt['status'] == 'read_error'
            evidence.append(dict(review, pdf=pdf, receipt=receipt, sample_directory=directory))
    assert len(evidence) == 37
    assert Counter(r['verdict'] for r in evidence) == {'supported': 32, 'supported_body_only': 4, 'unavailable': 1}
    save(out / 'native-evidence.json', evidence)

    pilot = json.loads((out / 'pilot.json').read_text())['records']
    assert len(pilot) == len({r['document_id'] for r in pilot}) == 400
    assert Counter(r['split'] for r in pilot) == {'development': 200, 'held-out': 200}
    seen = set()
    for row in pilot:
        keys = set(row['body_keys'] or [])
        assert not keys & seen
        seen.update(keys)
    assert not {r['document_id'] for r in pilot} & {r['document_id'] for r in additions}
    csv_rows = list(csv.DictReader((out / 'pilot-review.csv').open()))
    assert [r['document_id'] for r in csv_rows] == [r['document_id'] for r in pilot]
    assert all(not r['reviewed_kind'] for r in csv_rows)
    tests = {}
    for name in ['house-tests.log', 'catalog-tests.log', 'native-table-tests.log']:
        log = (out / name).read_text()
        count = re.search(r'(\d+) passed', log)
        assert count and 'failed' not in log.lower()
        tests[name] = int(count[1])
    summary = dict(classified=stats['counts']['classified'], unresolved=stats['counts']['unresolved'],
                   added=len(additions), added_kinds=dict(Counter(k for r in additions for k in r['document_kind'])),
                   conserved_ids=total, prior_classifications_preserved=preserved,
                   prior_kind_changes=len(changed), regressions=len(regressions),
                   content_checks=dict(Counter(r['verdict'] for r in evidence)),
                   retained_hash_matches=sum(bool(r['pdf']) for r in evidence),
                   association_probe=json.loads((out / 'association-probe/summary.json').read_text()),
                   association_candidates=prepared['association_records'], recovered_associations=0,
                   pilot_records=len(pilot), pilot_splits=dict(Counter(r['split'] for r in pilot)),
                   tests=tests, filename_fingerprint=stats['filename_fingerprint'],
                   artifact_hashes={p: digest(out / p) for p in ['pilot.json', 'pilot-review.csv', 'native-evidence.json', 'new-classifications.csv']},
                   scope='Local catalog 3.2.0, frozen experiment replay. No production publication of these changes; full current-catalog impact remains unmeasured.',
                   limitations=['First-page genre checks, not full-document factual review or a population precision estimate.',
                                'The 48 original-link probes are a bounded diagnostic sample, not proof that all 802 associations are unrecoverable.',
                                'Pilot text availability and reference labels are not yet checked. No held-out performance is claimed.'])
    save(out / 'verification.json', summary)
    esc = html.escape
    cards = []
    for row in evidence:
        links = f'<a href="{esc(row["pdf"])}">Hash-matched PDF</a>' if row['pdf'] else esc(row['receipt']['error'])
        cards.append(f'<details><summary>{esc(row["filename"])} — {esc(row["verdict"])}</summary><p>{esc(row["note"])}</p><p>Reviewed pages: {esc(str(row["reviewed_pages"]))}; method: {esc(row["method"])}. {links}</p></details>')
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Document-kind continuation</title>
<style>body{font:16px/1.5 system-ui;max-width:1050px;margin:3rem auto;padding:0 24px;color:#20312f;background:#fafbf9}a{color:#175c50}details{padding:12px 0;border-top:1px solid #becbc4}summary{cursor:pointer}td,th{text-align:left;padding:8px 20px 8px 0;border-bottom:1px solid #dde5df}code{overflow-wrap:anywhere}</style>
<h1>Document-kind continuation</h1>
<p><b>831 additional classifications</b> in the frozen experiment: 612 published hearings, 179 legislative texts and 40 public laws. Total classified: 10,258; eligible unresolved: 23,290.</p>
<p>All 657,103 IDs conserved. All 9,427 prior classifications unchanged. New rules are local and unpublished. <a href="https://github.com/civictechdc/congressional-tech/actions/runs/38823678887">Earlier publication status</a>.</p>
<h2>Review outputs</h2><ul>
<li><a href="new-classifications.csv">831 new classifications with provenance</a></li>
<li><a href="pilot-review.csv">400-document blank review sheet</a> · <a href="pilot.json">Frozen pilot and retained-body references</a></li>
<li><a href="association-candidates.json">802 source-association candidates</a> · <a href="association-probe/receipts.jsonl">48 original-link probe receipts</a></li>
<li><a href="verification.json">Verification and artifact hashes</a> · <a href="native-evidence.json">All native content adjudications</a></li></ul>
<h2>Source associations</h2><p>No association promoted. The frozen named population and the older local capture index supplied no exact original-URL evidence. The bounded original-link probe returned 14 HTTP 403, 14 HTTP 404, 10 HTTP 410 and 10 read failures. These failures do not establish that all candidates are unrecoverable.</p>
<h2>PDF pilot</h2><p>200 development and 200 held-out records, selected before availability checks. Publisher and filename strata are balanced; retained bodies do not repeat across the split. The sample is not population-weighted. Text availability and reference labels remain pending; no accuracy claim is made.</p>
<h2>Native-format evidence</h2><p>37 selected documents: 36 retrieved PDFs match retained SHA-256 values; one URL returned 404. All retrieved first pages were read; three also received image review. Four supported bodies remain outside the promoted conventions. Small targeted samples do not estimate population precision.</p>
<p><code>103-3.pdf</code> prints hearing serial <code>113–3</code> on its cover. The rule preserves the literal serial and does not infer Congress or a GPO publication number.</p>
'''+''.join(cards)+'</html>'
    (out / 'report.html').write_text(page)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
