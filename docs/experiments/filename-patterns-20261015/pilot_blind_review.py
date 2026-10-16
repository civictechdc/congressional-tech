"""Build blind opening-page packets and validate separate reference decisions.

Development packets are practice. Held-out packets require verified publication
and eligibility evidence. This module never runs a classifier or edits frozen
development labels. Reviewer names are claims, not proof of independent review.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re

import pyarrow.parquet as pq

import pilot_review as review
from pilot_reconcile import body_hashes, file_digest, publication_gate
from rule_review import HERE, ROOT
from congress_api.retention.catalog_publication import local_catalog_paths


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def verify_candidate(freeze_path):
    freeze = json.loads(Path(freeze_path).read_text())
    for path, expected in freeze['source_hashes'].items():
        if file_digest(ROOT / path) != expected:
            raise ValueError('Frozen candidate source changed: ' + path)
    if file_digest(review.SAMPLE) != freeze['sample_sha256'] or file_digest(review.LABELS) != freeze['labels_sha256']:
        raise ValueError('Frozen selection or development labels changed')
    return freeze


def held_out_eligibility(directory):
    if directory is None:
        raise ValueError('Held-out review requires verified catalog reconciliation')
    directory = Path(directory)
    summary = json.loads((directory / 'summary.json').read_text())
    if not summary['held_out_review_unlocked'] or summary['sample_sha256'] != file_digest(review.SAMPLE):
        raise ValueError('Rehearsal or mismatched reconciliation cannot unlock held-out review')
    if file_digest(directory / 'eligibility.json') != summary['eligibility_sha256']:
        raise ValueError('Eligibility ledger changed')
    _, documents = local_catalog_paths(summary['catalog_root'])
    if file_digest(documents) != summary['documents_sha256']:
        raise ValueError('Reconciled catalog changed')
    metadata = {k.decode(): v.decode() for k, v in (pq.ParquetFile(documents).schema_arrow.metadata or {}).items()}
    gate = publication_gate(summary['publication_directory'], summary['catalog_root'], metadata)
    if not gate['verified'] or gate != summary['publication']:
        raise ValueError('Publication evidence changed or is not verified')
    ledger = json.loads((directory / 'eligibility.json').read_text())
    expected = {r['document_id'] for split in ['development', 'held-out'] for r in review.selected(split)}
    rows = {r['document_id']: r for r in ledger['records']}
    if set(rows) != expected or len(rows) != len(ledger['records']):
        raise ValueError('Eligibility ledger must preserve every selected document exactly once')
    return rows


def build(split, output, freeze_path, reconciliation=None):
    freeze = verify_candidate(freeze_path)
    eligibility = held_out_eligibility(reconciliation) if split == 'held-out' else None
    output = Path(output).resolve()
    rows, packets = review.records(), []
    for number, original in enumerate(review.selected(split), 1):
        identity = ('D' if split == 'development' else 'H') + f'{number:03}'
        receipt = rows.get(original['document_id'])
        eligible = eligibility is None or eligibility[original['document_id']]['catalog_eligible']
        item = dict(review_id=identity, document_id=original['document_id'], state='unavailable', body_sha256=None, pdf=None, pages=[])
        if not eligible:
            item['state'] = 'eligibility_changed'
        elif receipt and len(receipt['bodies']) == 1:
            body, = receipt['bodies']
            sha = body['sha256']
            if not re.fullmatch(r'[0-9a-f]{64}', sha) or sha not in body_hashes(original.get('body_keys')):
                raise ValueError('Review body is outside the frozen sample')
            pdf = (review.OUT / split / (sha + '.pdf')).resolve()
            if file_digest(pdf) != sha:
                raise ValueError('Review PDF changed')
            item.update(state='review', body_sha256=sha, pdf=os.path.relpath(pdf, output))
            for page in body.get('pages', []):
                text, info, _ = review.page_text(receipt, page['page'])
                item['pages'].append(dict(page=page['page'], text=text, text_sha256=info['text_sha256']))
            if body.get('status') == 'needs_visual_review' or not any(page['text'].strip() for page in item['pages']):
                item['state'] = 'needs_visual_review'
        elif receipt and len(receipt['bodies']) > 1:
            item['state'] = 'multiple_bodies'
        packets.append(item)
    data = dict(split=split, sample_sha256=freeze['sample_sha256'], candidate=freeze['candidate'],
                freeze_sha256=file_digest(freeze_path), reconciliation_sha256=file_digest(Path(reconciliation) / 'summary.json') if eligibility else None,
                purpose='practice' if split == 'development' else 'reference_review', records=packets)
    data['packet_id'] = fingerprint(data)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'packet.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    # Escape HTML delimiters in embedded JSON; document text is always displayed
    # through textContent, never interpreted as HTML or instructions.
    embedded = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    template = (HERE / 'blind_review.html').read_text()
    (output / 'report.html').write_text(template.replace('/*PACKET_DATA*/null', embedded))
    manifest = dict(packet_id=data['packet_id'], packet_sha256=file_digest(output / 'packet.json'),
                    html_sha256=file_digest(output / 'report.html'), records=len(packets), split=split,
                    purpose=data['purpose'], predictions_included=False)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))
    return manifest


def validate_packet(packet_directory, *, freeze_path, reconciliation=None):
    """Shared evidence checks for reference import, sealing and evaluation."""
    verify_candidate(freeze_path)
    directory = Path(packet_directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    if file_digest(directory / 'packet.json') != manifest['packet_sha256']:
        raise ValueError('Packet content changed')
    if file_digest(directory / 'report.html') != manifest['html_sha256']:
        raise ValueError('Review interface changed after packet creation')
    packet = json.loads((directory / 'packet.json').read_text())
    unsigned = {k: v for k, v in packet.items() if k != 'packet_id'}
    if fingerprint(unsigned) != packet['packet_id'] or packet['packet_id'] != manifest['packet_id']:
        raise ValueError('Packet identity mismatch')
    if packet['freeze_sha256'] != file_digest(freeze_path):
        raise ValueError('Candidate freeze changed')
    if packet['split'] == 'held-out':
        held_out_eligibility(reconciliation)
        if file_digest(Path(reconciliation) / 'summary.json') != packet['reconciliation_sha256']:
            raise ValueError('Packet reconciliation changed')
    return packet


def validate_decisions(packet, decisions, directory):
    """Normalize an export without changing the packet or decision journal."""
    if decisions['packet_id'] != packet['packet_id']:
        raise ValueError('Decision export belongs to another packet')
    records = {r['review_id']: r for r in packet['records']}
    seen, additions = set(), []
    for decision in decisions['decisions']:
        identity = decision['review_id']
        if identity in seen or identity not in records:
            raise ValueError('Unknown or duplicate review ID')
        seen.add(identity)
        source = records[identity]
        if not decision.get('reviewer', '').strip():
            raise ValueError('A reviewer name is required')
        verdict = decision['verdict']
        if verdict not in {'classified', 'uncertain', 'unavailable'}:
            raise ValueError('Unknown verdict')
        kind = decision.get('reference_kind', '').strip()
        quote = decision.get('evidence_quote', '').strip()
        page = next((p for p in source['pages'] if p['page'] == decision.get('evidence_page')), None)
        if verdict == 'classified':
            if source['state'] != 'review' or not kind or not quote or page is None:
                raise ValueError('Classification requires an eligible page, kind and quote')
        elif kind:
            raise ValueError('Uncertain and unavailable decisions cannot assign a kind')
        if quote and (page is None or ' '.join(quote.split()).casefold() not in ' '.join(page['text'].split()).casefold()):
            raise ValueError('Evidence quote is absent from the selected page')
        if source['body_sha256']:
            pdf = directory / source['pdf']
            if file_digest(pdf) != source['body_sha256']:
                raise ValueError('Review PDF changed after packet creation')
        entry = dict(packet_id=packet['packet_id'], purpose=packet['purpose'], split=packet['split'],
                     review_id=identity, document_id=source['document_id'], verdict=verdict,
                     reviewer_claim=decision['reviewer'].strip(), human_validated=False,
                     reference_kind=kind, evidence_page=decision.get('evidence_page'), evidence_quote=quote,
                     note=decision.get('note', ''), body_sha256=source['body_sha256'],
                     text_sha256=page['text_sha256'] if page else None)
        additions.append(entry)
    return additions


def import_decisions(packet_directory, decisions_path, *, freeze_path, reconciliation=None):
    directory = Path(packet_directory)
    packet = validate_packet(directory, freeze_path=freeze_path, reconciliation=reconciliation)
    additions = validate_decisions(packet, json.loads(Path(decisions_path).read_text()), directory)
    journal = directory / 'reference-decisions.jsonl'
    previous = [json.loads(line) for line in journal.read_text().splitlines()] if journal.exists() else []
    existing = {r['review_id']: r for r in previous}
    for entry in additions:
        if entry['review_id'] in existing and existing[entry['review_id']] != entry:
            raise ValueError('Existing decision differs; preserve it and record a separate adjudication')
    new = [entry for entry in additions if entry['review_id'] not in existing]
    if new and (directory / 'label-freeze.json').exists():
        raise ValueError('Reference decisions are sealed; preserve the frozen label set')
    if new:
        with journal.open('a') as stream:
            for entry in new:
                stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
    print('Imported', len(new), 'decisions; frozen development labels unchanged.')
    return new


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'import'])
    parser.add_argument('--split', choices=['development', 'held-out'], default='development')
    parser.add_argument('--output', type=Path, required=True, help='Packet directory')
    parser.add_argument('--freeze', type=Path, default=HERE / 'content_rule_freeze.json')
    parser.add_argument('--reconciliation', type=Path)
    parser.add_argument('--decisions', type=Path)
    args = parser.parse_args()
    if args.action == 'build':
        build(args.split, args.output, args.freeze, args.reconciliation)
    else:
        if args.decisions is None:
            parser.error('--decisions is required for import')
        import_decisions(args.output, args.decisions, freeze_path=args.freeze, reconciliation=args.reconciliation)
