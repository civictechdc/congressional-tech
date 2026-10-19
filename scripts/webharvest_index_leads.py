#!/usr/bin/env python3
"""Summarize a completed index audit and find additional PDF filename leads.

All work is local. Filename equality is a search lead, never document identity.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from webharvest_cdx import digest, key, load, parse_cdx, save


def basename(url):
    return unquote(urlsplit(url).path.rsplit('/', 1)[-1]).casefold()


def write_rows(path, rows):
    with path.open('w') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')


def summarize(run):
    results = [json.loads(line) for line in (run / 'url-results.jsonl').read_text().splitlines()]
    assert len(results) == len({row['original_url'] for row in results}) == load(run / 'input-manifest.json')['remaining_urls']
    wanted = defaultdict(list)
    for row in results:
        name = basename(row['original_url'])
        if name.endswith('.pdf'):
            wanted[name].append(row)
    indexed_by_name = defaultdict(dict)
    checked, rows_scanned = set(), 0
    for coverage in load(run / 'coverage.json'):
        for proof in coverage['requests']:
            identity = (coverage['collection'], proof['sha256'])
            if identity in checked:
                continue
            raw = Path(proof['body_path']).read_bytes()
            if digest(raw) != proof['sha256']:
                raise ValueError('retained_index_hash_mismatch')
            rows, _ = parse_cdx(raw)
            checked.add(identity)
            rows_scanned += len(rows)
            for capture in rows:
                name = basename(capture['url'])
                if capture['status'] != '200' or name not in wanted or capture['mime'].lower() not in {'application/pdf', 'application/x-pdf'}:
                    continue
                ident = (coverage['collection'], capture['urlkey'])
                prior = indexed_by_name[name].get(ident)
                if prior and prior['timestamp'] >= capture['timestamp']:
                    continue
                indexed_by_name[name][ident] = {**capture, 'collection': coverage['collection'], 'evidence': proof,
                    'replay_url': f"https://webharvest.gov/{coverage['collection']}/{capture['timestamp']}id_/{capture['url']}",
                    'availability': 'index_match_not_download_verified'}
    filename_leads = []
    for row in results:
        candidates = []
        for capture in indexed_by_name.get(basename(row['original_url']), {}).values():
            if capture['urlkey'] == row['urlkey']:
                continue
            same_host = urlsplit(row['original_url']).hostname == urlsplit(capture['url']).hostname
            old, archived = urlsplit(row['original_url']), urlsplit(capture['url'])
            same_path = (unquote(old.path).casefold(), old.query) == (unquote(archived.path).casefold(), archived.query)
            basis = 'same_path_different_host' if same_path else 'same_filename_same_host' if same_host else 'same_filename_different_host'
            candidates.append({**capture, 'match_basis': basis,
                'document_identity_verified': False})
        if candidates:
            filename_leads.append({'original_url': row['original_url'], 'filename': basename(row['original_url']),
                'candidates': sorted(candidates, key=lambda c: (c['match_basis'] != 'same_filename_same_host', c['collection'], c['timestamp']))})
    exact = [r for r in results if r['captures']]
    pdf = [r for r in exact if any(c['mime'].lower() in {'application/pdf', 'application/x-pdf'} for c in r['captures'])]
    write_rows(run / 'exact-index-matches.jsonl', exact)
    write_rows(run / 'exact-pdf-index-matches.jsonl', pdf)
    write_rows(run / 'filename-pdf-leads.jsonl', filename_leads)
    exact_pdf_urls = {r['original_url'] for r in pdf}
    extra = {r['original_url'] for r in filename_leads} - exact_pdf_urls
    by_url = defaultdict(list)
    for row in pdf:
        by_url[row['original_url']].extend({**c, 'match_basis': 'exact_canonical_url', 'document_identity_verified': False}
            for c in row['captures'] if c['mime'].lower() in {'application/pdf', 'application/x-pdf'})
    for row in filename_leads:
        by_url[row['original_url']].extend(row['candidates'])
    rank = {'exact_canonical_url': 0, 'same_path_different_host': 1, 'same_filename_same_host': 2, 'same_filename_different_host': 3}
    queue = [{'original_url': url, 'candidates': sorted(captures, key=lambda c: (rank[c['match_basis']], -int(c['timestamp'])))}
             for url, captures in by_url.items()]
    queue.sort(key=lambda row: (rank[row['candidates'][0]['match_basis']], row['original_url']))
    write_rows(run / 'pdf-download-candidates.jsonl', queue)
    summary = {**load(run / 'summary.json'), 'filename_search': {'evidence_responses_scanned': len(checked),
        'index_rows_scanned': rows_scanned, 'urls_with_pdf_filename_candidates': len(filename_leads),
        'additional_urls_beyond_exact_pdf_matches': len(extra),
        'urls_with_same_path_on_other_host': sum(any(c['match_basis'] == 'same_path_different_host' for c in r['candidates']) for r in filename_leads),
        'urls_with_same_filename_on_original_host': sum(any(c['match_basis'] == 'same_filename_same_host' for c in r['candidates']) for r in filename_leads),
        'scope': 'Exact decoded case-insensitive PDF basename across retained successful captures. Different paths or hosts are candidates, not verified document matches.'},
        'urls_in_pdf_candidate_queue': len(queue),
        'exact_match_mime_counts': dict(Counter(c['mime'] for r in exact for c in r['captures']))}
    save(run / 'results-summary.json', summary)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    summarize(parser.parse_args().run)
