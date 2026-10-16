"""Prepare blind review packets and retain explicitly adjudicated pilot labels."""
import argparse
import json
from pathlib import Path
import sys

from rule_review import DEFAULT_INPUT, HERE, digest

OUT = DEFAULT_INPUT / 'pilot-v1'
SAMPLE = DEFAULT_INPUT / 'continuation-v1/pilot.json'
LABELS = HERE / 'pilot_adjudications.json'


def records():
    rows = {}
    for name in ['receipts.jsonl', 'extraction-repairs.jsonl']:
        path = OUT / name
        if path.exists():
            for line in path.read_text().splitlines():
                row = json.loads(line)
                rows[row['document_id']] = row
    return rows


def selected(split):
    return [r for r in json.loads(SAMPLE.read_text())['records'] if r['split'] == split]


def page_text(receipt, page):
    body, = receipt['bodies']
    info = next(p for p in body['pages'] if p['page'] == page)
    path = OUT / receipt['split'] / info['text']
    assert digest(path) == info['text_sha256'], 'Review text changed after extraction'
    return path.read_text(), info, body['sha256']


def selected_method(receipt, info):
    """Older receipts marked any OCR attempt as OCR, even when native text won."""
    directory = OUT / receipt['split']
    return ('native_text' if (directory / info['text']).read_bytes() ==
            (directory / info['native_text']).read_bytes() else 'ocr')


def add(split, decisions):
    labels = json.loads(LABELS.read_text()) if LABELS.exists() else dict(
        sample_sha256=digest(SAMPLE), reviewer='assistant', human_validated=False,
        method='Reference labels adjudicated from displayed opening-page text excerpts and individually recorded additional pages/images. No filename-to-cluster label propagation. Not independent human ground truth.', records={})
    assert labels['sample_sha256'] == digest(SAMPLE)
    rows, frozen = records(), selected(split)
    for number, kind, page, quote, note in decisions:
        original = frozen[number - 1]
        row = rows[original['document_id']]
        assert row['status'] == 'review_ready'
        text, info, sha = page_text(row, page)
        assert sha in {Path(key).stem for key in original.get('body_keys') or []}
        assert digest(OUT / split / (sha + '.pdf')) == sha, 'Review body changed after extraction'
        normalized = ' '.join(text.split())
        assert ' '.join(quote.split()).casefold() in normalized.casefold(), (number, quote)
        identity = ('D' if split == 'development' else 'H') + f'{number:03}'
        entry = dict(review_id=identity, document_id=row['document_id'], split=split,
                     reference_kind=kind, evidence_page=page, evidence_quote=quote,
                     text_sha256=info['text_sha256'], body_sha256=sha,
                     extraction_method=selected_method(row, info), note=note)
        if row['document_id'] in labels['records']:
            assert labels['records'][row['document_id']] == entry, 'Do not silently replace adjudications'
        labels['records'][row['document_id']] = entry
    LABELS.write_text(json.dumps(labels, indent=2) + '\n')
    print('Saved', len(labels['records']), 'explicit reference labels.')


def packet(split, start, end, limit, page):
    rows = records()
    for number, original in enumerate(selected(split), 1):
        if not start <= number <= end:
            continue
        print('\n' + ('D' if split == 'development' else 'H') + f'{number:03}')
        row = rows.get(original['document_id'])
        if not row:
            print('PENDING'); continue
        if row['status'] != 'review_ready':
            print('UNAVAILABLE' if not row['bodies'] else 'NEEDS_REVIEW'); continue
        try:
            text, info, _ = page_text(row, page)
        except (StopIteration, ValueError):
            print('MISSING_PAGE_OR_MULTIPLE_BODIES'); continue
        text = '\n'.join(line.strip() for line in text.splitlines() if line.strip())
        print('PAGE', page, info['method'], 'CHARS', len(text))
        print(text[:limit])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['packet', 'add'])
    parser.add_argument('--split', choices=['development', 'held-out'], default='development')
    parser.add_argument('--start', type=int, default=1)
    parser.add_argument('--end', type=int, default=20)
    parser.add_argument('--limit', type=int, default=2000)
    parser.add_argument('--page', type=int, default=1)
    args = parser.parse_args()
    if args.action == 'add':
        add(args.split, json.load(sys.stdin))
    else:
        packet(args.split, args.start, args.end, args.limit, args.page)
