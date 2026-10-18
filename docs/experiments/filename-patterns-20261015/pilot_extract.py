"""Extract the frozen PDF pilot without assigning kinds or changing captures.

Local retained bytes take precedence. Recorded publisher URLs are a fallback;
only exact retained SHA-256 matches enter the reference-label review queue.
Development and held-out outputs remain separate. Failures are never replaced.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from rule_review import DEFAULT_INPUT, digest
from congress_api.retention import pdf_tools

LIMIT = 32 * 1024**2


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def read_local(key, roots):
    if not key.startswith('bodies/sha256/') or '..' in key.split('/'):
        raise ValueError('Invalid retained body location')
    for root in roots:
        path = root / key
        if path.is_file():
            with gzip.open(path, 'rb') as stream:
                data = stream.read(LIMIT + 1)
            if len(data) > LIMIT:
                raise ValueError('Retained PDF exceeds 32 MiB limit')
            if hashlib.sha256(data).hexdigest() != Path(key).stem:
                raise ValueError('Retained object digest mismatch')
            return data, str(path)
    return None, None


def extract_pages(data, sha, directory):
    pdf = directory / (sha + '.pdf')
    pdf.write_bytes(data)
    pages = pdf_tools.page_count_file(pdf)
    result = dict(sha256=sha, bytes=len(data), pdf=pdf.name, page_count=pages, pages=[])
    for page in range(1, min(pages, 2) + 1):
        text = pdf_tools.opening_page_text_file(pdf, page)
        native = directory / f'{sha}.page-{page}.native.txt'
        native.write_text(text)
        item = dict(page=page, native_text=native.name, method='native_text')
        if sum(char.isalpha() for char in text) < 80:
            stem = directory / f'{sha}.page-{page}'
            subprocess.run(['pdftoppm', '-f', str(page), '-l', str(page), '-singlefile',
                            '-scale-to', '1800', '-png', str(pdf), str(stem)],
                           check=True, capture_output=True, timeout=30)
            image = directory / f'{sha}.page-{page}.png'
            ocr = subprocess.run(['tesseract', str(image), 'stdout', '-l', 'eng'],
                                 check=True, capture_output=True, text=True, timeout=30).stdout
            (directory / f'{sha}.page-{page}.ocr.txt').write_text(ocr)
            item.update(ocr_attempted=True, image=image.name)
            if len(ocr.strip()) > len(text.strip()):
                text = ocr
                item['method'] = 'ocr'
        ready = directory / f'{sha}.page-{page}.txt'
        ready.write_text(text)
        item.update(text=ready.name, characters=len(text), text_sha256=digest(ready))
        result['pages'].append(item)
    return result


def run(source, output, roots):
    source_sha = digest(source)
    sample = json.loads(source.read_text())
    if output.exists():
        manifest = json.loads((output / 'manifest.json').read_text())
        assert manifest['sample_sha256'] == source_sha, 'Resume requires the same frozen selection'
    else:
        output.mkdir(parents=True)
        save(output / 'manifest.json', dict(sample=str(source.resolve()), sample_sha256=source_sha,
             reader_versions=pdf_tools.reader_versions(), max_body_bytes=LIMIT,
             started_at=datetime.now(timezone.utc).isoformat(),
             policy='No replacements. Exact retained hash required for reference review. No classification or held-out tuning.'))
    for split in ['development', 'held-out']:
        (output / split).mkdir(exist_ok=True)
    log = output / 'receipts.jsonl'
    existing = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    completed = {r['document_id'] for r in existing}

    def one(row):
        started = time.monotonic()
        result = dict(document_id=row['document_id'], filename=row['filename'], split=row['split'],
                      checked_at=datetime.now(timezone.utc).isoformat(), attempts=[], bodies=[])
        directory = output / row['split']
        expected = {Path(key).stem for key in row.get('body_keys') or []}
        bodies = {}
        for key in row.get('body_keys') or []:
            attempt = dict(transport='local_retained', body_key=key)
            try:
                data, path = read_local(key, roots)
                attempt['status'] = 'found' if data is not None else 'not_local'
                if data is not None:
                    attempt['path'] = path
                    bodies[hashlib.sha256(data).hexdigest()] = data
            except Exception as error:
                attempt.update(status='read_error', error=str(error))
            result['attempts'].append(attempt)
        urls = list(dict.fromkeys([row.get('source_url'), *(row.get('source_urls') or [])]))
        for url in urls[:3]:
            if expected and expected <= bodies.keys():
                break
            if not url:
                continue
            attempt = dict(transport='publisher', url=url)
            try:
                if urlsplit(url).scheme not in {'http', 'https'}:
                    raise ValueError('Not an HTTP(S) URL')
                request = Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; CongressionalTech/1.0; document research)'})
                with urlopen(request, timeout=15) as response:
                    attempt.update(http_status=response.status, final_url=response.url,
                                   content_type=response.headers.get('Content-Type'))
                    data = response.read(LIMIT + 1)
                if len(data) > LIMIT:
                    raise ValueError('Publisher body exceeds 32 MiB limit')
                sha = hashlib.sha256(data).hexdigest()
                attempt.update(sha256=sha, bytes=len(data))
                if not data.lstrip().startswith(b'%PDF-'):
                    attempt['status'] = 'not_pdf'
                elif sha in expected:
                    attempt['status'] = 'matches_retained_digest'
                    bodies[sha] = data
                else:
                    attempt['status'] = 'different_pdf' if expected else 'no_retained_digest'
                    # Keep new or changed bytes separate from the frozen reference set.
                    quarantine = output / 'unmatched'
                    quarantine.mkdir(exist_ok=True)
                    (quarantine / (sha + '.pdf')).write_bytes(data)
            except HTTPError as error:
                attempt.update(status='http_error', http_status=error.code, error=str(error))
            except Exception as error:
                attempt.update(status='read_error', error=str(error))
            result['attempts'].append(attempt)
            if not expected and attempt.get('status') == 'no_retained_digest':
                break
        for sha, data in sorted(bodies.items()):
            try:
                body = extract_pages(data, sha, directory)
                body['status'] = 'text_ready' if any(p['characters'] >= 80 for p in body['pages']) else 'needs_visual_review'
            except Exception as error:
                body = dict(sha256=sha, status='extraction_error', error=str(error))
            result['bodies'].append(body)
        result.update(status='review_ready' if any(b['status'] == 'text_ready' for b in result['bodies']) else 'unresolved',
                      expected_bodies=len(expected), matched_bodies=len(bodies),
                      elapsed_seconds=round(time.monotonic() - started, 2))
        return result

    pending = [r for r in sample['records'] if r['document_id'] not in completed]
    with ThreadPoolExecutor(max_workers=3) as pool, log.open('a') as stream:
        for result in pool.map(one, pending):
            stream.write(json.dumps(result) + '\n'); stream.flush()
            existing.append(result)
            print(len(existing), result['split'], result['filename'], result['status'], flush=True)
    assert len(existing) == len(sample['records']) == len({r['document_id'] for r in existing})
    save(output / 'extraction-summary.json', dict(records=len(existing),
         splits={split: dict(Counter(r['status'] for r in existing if r['split'] == split)) for split in ['development', 'held-out']},
         matched_bodies=sum(r['matched_bodies'] for r in existing),
         ocr_pages=sum(p['method'] == 'ocr' for r in existing for b in r['bodies'] for p in b.get('pages', [])),
         reader_errors=sum(b['status'] == 'extraction_error' for r in existing for b in r['bodies']),
         elapsed_seconds_sum=round(sum(r['elapsed_seconds'] for r in existing), 2),
         sample_sha256=source_sha, receipts_sha256=digest(log)))


def repair_extraction(output):
    """Retry saved bytes after an extractor fix; retain the original failure log."""
    receipts = [json.loads(line) for line in (output / 'receipts.jsonl').read_text().splitlines()]
    path = output / 'extraction-repairs.jsonl'
    repairs = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    done = {r['document_id'] for r in repairs}
    with path.open('a') as stream:
        for original in receipts:
            if original['document_id'] in done or not any(b['status'] == 'extraction_error' for b in original['bodies']):
                continue
            result = dict(original, bodies=[], repair_reason='Correct OCR page-image path; retry exact previously downloaded bytes.')
            directory = output / result['split']
            for body in original['bodies']:
                if body['status'] != 'extraction_error':
                    result['bodies'].append(body)
                    continue
                sha = body['sha256']
                pdf = directory / (sha + '.pdf')
                assert digest(pdf) == sha
                try:
                    fixed = extract_pages(pdf.read_bytes(), sha, directory)
                    fixed['status'] = 'text_ready' if any(p['characters'] >= 80 for p in fixed['pages']) else 'needs_visual_review'
                except Exception as error:
                    fixed = dict(body, error=str(error))
                result['bodies'].append(fixed)
            result['status'] = 'review_ready' if any(b['status'] == 'text_ready' for b in result['bodies']) else 'unresolved'
            stream.write(json.dumps(result) + '\n'); stream.flush()
            print(result['document_id'], result['status'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_INPUT / 'continuation-v1/pilot.json')
    parser.add_argument('--output', type=Path, default=DEFAULT_INPUT / 'pilot-v1')
    parser.add_argument('--body-root', type=Path, action='append', default=[])
    parser.add_argument('--repair-extraction', action='store_true')
    args = parser.parse_args()
    if args.repair_extraction:
        repair_extraction(args.output)
    else:
        run(args.source, args.output, args.body_root)
