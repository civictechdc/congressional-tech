"""Offline XML repair inspection over one pinned retained original.

Writes a separate original -> recovery candidate -> markup events -> text packet.
It never writes reading tables, selection manifests, body storage or publication.
Altered candidates remain partial even when their XML serialization is valid.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path


def inspect_xml_repair(input_path, *, expected_sha256, output_dir, max_bytes=64 << 20,
                      max_candidate_bytes=64 << 20, source_gap_note=None):
    """Retain an inspectable candidate and its evidence without accepting it as a reading."""
    from spicy_docs.extraction.body_text import rendition_text
    from spicy_docs.reading.markup import read_xml_events
    from spicy_docs.reading.xml_recovery import XmlRecoveryCandidate, recover_xml_candidate

    for name, value in (('max_bytes', max_bytes), ('max_candidate_bytes', max_candidate_bytes)):
        if type(value) is not int or value <= 0:
            raise ValueError(f'{name} must be a positive integer')
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    with input_path.open('rb') as stream:
        original = stream.read(max_bytes + 1)
    if len(original) > max_bytes:
        raise ValueError('Retained input exceeds max_bytes; no repair was attempted')
    if sha256(original).hexdigest() != expected_sha256:
        raise ValueError('Retained input does not match expected_sha256')
    # A fresh directory protects earlier evidence, including a previous refusal.
    output_dir.mkdir(parents=True, exist_ok=False)

    def write(name, data):
        path = output_dir / name
        with path.open('xb') as stream:
            stream.write(data)
        return dict(path=name, sha256=sha256(data).hexdigest(), bytes=len(data))

    files = {'original': write('original.raw', original)}
    try:
        repair = recover_xml_candidate(original, max_bytes=max_bytes, max_candidate_bytes=max_candidate_bytes)
    except (ValueError, UnicodeError) as error:
        repair = XmlRecoveryCandidate(source_sha256=expected_sha256, source_bytes=len(original), status='refused',
                                      reason='recovery_input_refused', source_error=str(error))
    metadata = asdict(repair)
    metadata.pop('candidate_body')
    # The candidate cap bounds what this operator writes or rereads, including
    # unchanged bytes. It is independent of the input cap: recovery may shrink
    # a larger malformed input into a smaller candidate.
    oversized = repair.candidate_body is not None and len(repair.candidate_body) > max_candidate_bytes
    if oversized:
        metadata['operator_refusal'] = dict(reason='candidate_exceeds_byte_bound',
                                            observed_candidate_bytes=len(repair.candidate_body),
                                            max_candidate_bytes=max_candidate_bytes)
    files['repair'] = write('repair.json', (json.dumps(metadata, indent=2) + '\n').encode())
    output = dict(schema='ct-markup-repair-inspection-v1', source_path=str(input_path.resolve()),
                  source_sha256=repair.source_sha256, status='refused' if oversized else repair.status,
                  reason='candidate_exceeds_byte_bound' if oversized else repair.reason,
                  content_completeness='unestablished' if repair.status == 'partial' else repair.status,
                  source_gap_note=source_gap_note, qualification='not_qualified_for_selection',
                  selected_for_publication=False, ocr_invoked=False, publisher_requests=0,
                  byte_positions_address=repair.byte_positions_address,
                  limits=dict(max_bytes=max_bytes, max_candidate_bytes=max_candidate_bytes), files=files)
    if oversized:
        output['content_completeness'] = 'unestablished'
        output['operator_refusal'] = metadata['operator_refusal']
    if repair.candidate_body is not None and not oversized:
        files['candidate'] = write('candidate.xml', repair.candidate_body)
        if repair.status in {'partial', 'unchanged'}:
            try:
                read = read_xml_events(repair.candidate_body, max_bytes=max_candidate_bytes,
                                       allow_external_doctype=True, allow_empty_internal_subset=True)
                events = ''.join(json.dumps(asdict(event), ensure_ascii=False) + '\n' for event in read.events)
                files['events'] = write('candidate.events.jsonl', events.encode())
                derived = rendition_text(repair.candidate_body, rendition='xml')
                files['text'] = write('candidate.txt', derived.text.encode())
                output['cleanup'] = asdict(derived.record)
            except (ValueError, UnicodeError) as error:
                output.update(status='refused', reason='candidate_consumer_refused', content_completeness='unestablished',
                              consumer_error=dict(error_type=type(error).__name__, message=str(error)))
    write('output.json', (json.dumps(output, indent=2) + '\n').encode())
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='Retained original XML bytes; no URL fetching')
    parser.add_argument('--sha256', required=True, help='Expected original SHA-256')
    parser.add_argument('--output-dir', type=Path, required=True, help='New directory for retained review artifacts')
    parser.add_argument('--max-bytes', type=int, default=64 << 20)
    parser.add_argument('--max-candidate-bytes', type=int, default=64 << 20)
    parser.add_argument('--source-gap-note', help='Direct reviewer observation, e.g. source ends mid-attribute')
    args = parser.parse_args(argv)
    output = inspect_xml_repair(args.input, expected_sha256=args.sha256, output_dir=args.output_dir,
                               max_bytes=args.max_bytes, max_candidate_bytes=args.max_candidate_bytes,
                               source_gap_note=args.source_gap_note)
    print(json.dumps(dict(output_dir=str(args.output_dir.resolve()), status=output['status'],
                          reason=output['reason'], qualification=output['qualification'])))
    return 2 if output['status'] == 'refused' else 0


if __name__ == '__main__':
    raise SystemExit(main())
