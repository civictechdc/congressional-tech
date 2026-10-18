"""Seal reference decisions, then compare frozen native PDF readers.

All selected records remain in the denominator. No OCR, network acquisition,
catalog mutation, automatic release approval or held-out rule tuning occurs.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import time

import pilot_blind_review as blind
from pilot_reconcile import file_digest
from rule_review import HERE, ROOT
from congress_api.retention import pdf_tools
from congress_api.retention import capture_metadata
from congress_api.retention.document_evidence import evidence_fingerprint

COVER = 'packages/congress_api/src/congress_api/parsers/document_cover.py'
SUCCESS = {'completed', 'unclassified'}


def write_new(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def environment():
    pdf_tools.reader_versions.cache_clear()
    return dict(python=platform.python_version(), reader_versions=pdf_tools.reader_versions(),
                reader_fingerprint=evidence_fingerprint(),
                capture_metadata_sha256=file_digest(capture_metadata.__file__),
                evaluator_sha256=file_digest(__file__),
                validation_sha256=file_digest(blind.__file__))


def checked_references(directory, packet):
    """Revalidate imported decisions and conserve records without reference text."""
    journal = directory / 'reference-decisions.jsonl'
    imported = [json.loads(line) for line in journal.read_text().splitlines()] if journal.exists() else []
    exported = dict(packet_id=packet['packet_id'], decisions=[dict(
        review_id=r['review_id'], reviewer=r['reviewer_claim'], verdict=r['verdict'],
        reference_kind=r['reference_kind'], evidence_page=r['evidence_page'],
        evidence_quote=r['evidence_quote'], note=r['note']) for r in imported])
    validated = blind.validate_decisions(packet, exported, directory)
    if validated != imported:
        raise ValueError('Imported reference evidence changed')
    by_id = {r['review_id']: r for r in validated}
    references = []
    for record in packet['records']:
        decision = by_id.get(record['review_id'])
        if decision is None and record['state'] == 'review':
            raise ValueError('Every available record needs a reference decision before sealing: ' + record['review_id'])
        if decision is None:
            decision = dict(review_id=record['review_id'], document_id=record['document_id'],
                            verdict='not_reviewable', reference_kind='', note=record['state'],
                            reviewer_claim=None, human_validated=False, body_sha256=record['body_sha256'])
        references.append(dict(decision, evidence_state=record['state']))
    return references, file_digest(journal) if journal.exists() else None


def seal(directory, *, freeze_path, reconciliation=None):
    directory = Path(directory).resolve()
    packet = blind.validate_packet(directory, freeze_path=freeze_path, reconciliation=reconciliation)
    references, journal_hash = checked_references(directory, packet)
    runtime = environment()
    candidate = json.loads(Path(freeze_path).read_text())
    if runtime['reader_versions'] != candidate['reader_versions']:
        raise ValueError('PDF reader versions differ from the frozen candidate')
    result = dict(packet_id=packet['packet_id'], packet_sha256=file_digest(directory / 'packet.json'),
                  candidate_freeze_sha256=file_digest(freeze_path), journal_sha256=journal_hash,
                  sealed_at=datetime.now(timezone.utc).isoformat(), split=packet['split'],
                  purpose=packet['purpose'], environment=runtime, records=references,
                  independent_reference_validation=False)
    write_new(directory / 'label-freeze.json', result)
    return result


def verify_seal(directory, *, freeze_path, reconciliation=None):
    directory = Path(directory)
    packet = blind.validate_packet(directory, freeze_path=freeze_path, reconciliation=reconciliation)
    frozen = json.loads((directory / 'label-freeze.json').read_text())
    refs, journal_hash = checked_references(directory, packet)
    if (frozen['packet_id'] != packet['packet_id'] or frozen['packet_sha256'] != file_digest(directory / 'packet.json')
            or frozen['candidate_freeze_sha256'] != file_digest(freeze_path)
            or frozen['records'] != refs or frozen['journal_sha256'] != journal_hash
            or frozen['environment'] != environment()):
        raise ValueError('Sealed labels, evidence or reader environment changed')
    for record in packet['records']:
        if record['body_sha256'] and file_digest(directory / record['pdf']) != record['body_sha256']:
            raise ValueError('Sealed PDF changed')
    return packet, frozen


def worker(pdf, expected_sha, fingerprint, baseline=None):
    if file_digest(pdf) != expected_sha:
        raise ValueError('PDF changed before reader invocation')
    if baseline:
        # Each reading runs in its own process. Keep the hashed historical
        # source intact while supplying its reader at the original import path.
        # The reader moved byte-for-byte from parsers to retention.
        sys.modules['congress_api.parsers.pdf_tools'] = pdf_tools
        spec = importlib.util.spec_from_file_location('frozen_baseline_cover', baseline)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        def baseline_cover(data, read_page, *, strict=False):
            return module.document_cover(data, strict=strict)
        capture_metadata.document_cover = baseline_cover
        capture_metadata.document_page_fields = module.document_page_fields
    return capture_metadata.read_document_file(pdf, expected_sha, fingerprint)


def read_pdf(pdf, expected_sha, fingerprint, baseline=None):
    command = [sys.executable, str(Path(__file__).resolve()), 'worker', '--pdf', str(pdf),
               '--expected-sha', expected_sha, '--fingerprint', fingerprint]
    if baseline:
        command += ['--baseline', str(baseline)]
    start = time.monotonic()
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
        value = json.loads(result.stdout) if result.returncode == 0 else dict(status='worker_failed', error_type='exit_' + str(result.returncode))
        value['diagnostic'] = result.stderr[-4000:]
        kinds = value.get('content_document_kind') or []
        if not isinstance(kinds, list) or len(kinds) > 1 or any(not isinstance(k, str) or not k for k in kinds):
            raise ValueError('Invalid reader kind')
        if value.get('status') not in SUCCESS | {'failed', 'worker_failed', 'size_limit'}:
            raise ValueError('Invalid reader status')
    except subprocess.TimeoutExpired:
        value = dict(status='timeout', error_type='30_second_limit')
    except (ValueError, TypeError, AttributeError):
        value = dict(status='worker_failed', error_type='invalid_worker_result')
    return dict(value, elapsed_seconds=round(time.monotonic() - start, 3))


def kind(reading):
    return next(iter(reading.get('content_document_kind') or []), '') if reading.get('status') in SUCCESS else ''


def interval(successes, total):
    """95% Wilson interval for a descriptive within-sample agreement proportion."""
    if total == 0:
        return None
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    half = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total)) / denominator
    return [max(0, center - half), min(1, center + half)]


def summarize(rows):
    metrics = {}
    for mode in ['baseline', 'candidate']:
        attempted = [r for r in rows if r[mode]['status'] != 'not_run']
        errors = [r for r in attempted if r[mode]['status'] not in SUCCESS]
        assigned = [r for r in attempted if kind(r[mode])]
        scored = [r for r in assigned if r['reference_verdict'] == 'classified']
        disagreements = [r for r in scored if kind(r[mode]) != r['reference_kind']]
        agreements = len(scored) - len(disagreements)
        per_kind = {}
        kinds = sorted({kind(r[mode]) for r in assigned} | {r['reference_kind'] for r in rows if r['reference_kind']})
        for name in kinds:
            predicted = [r for r in assigned if kind(r[mode]) == name]
            compared = [r for r in scored if kind(r[mode]) == name]
            exact = sum(r['reference_kind'] == name for r in compared)
            per_kind[name] = dict(reference_count=sum(r['reference_kind'] == name for r in rows),
                                  assigned=len(predicted), scored_assignments=len(compared), exact_agreements=exact,
                                  disagreements=len(compared) - exact, unscored_assignments=len(predicted) - len(compared),
                                  agreement_interval_95=interval(exact, len(compared)))
        metrics[mode] = dict(attempted=len(attempted), not_run=len(rows) - len(attempted), assigned=len(assigned),
            abstentions=sum(r[mode]['status'] in SUCCESS and not kind(r[mode]) for r in attempted),
            reader_errors=[r['review_id'] for r in errors], scored_assignments=len(scored),
            exact_agreements=agreements, unscored_assignments=len(assigned) - len(scored),
            disagreements=[dict(review_id=r['review_id'], expected=r['reference_kind'], observed=kind(r[mode])) for r in disagreements],
            agreement_interval_95=interval(agreements, len(scored)), per_kind=per_kind)
    changed = [r for r in rows if kind(r['baseline']) and kind(r['baseline']) != kind(r['candidate'])]
    new = [r['review_id'] for r in rows if r['baseline']['status'] in SUCCESS and not kind(r['baseline']) and kind(r['candidate'])]
    rule_status = {}
    rule_names = set(metrics['candidate']['per_kind']) | {kind(r['baseline']) for r in changed}
    for name in sorted(rule_names):
        values = metrics['candidate']['per_kind'].get(name, dict(disagreements=0))
        regressions = [r['review_id'] for r in changed if name in {kind(r['baseline']), kind(r['candidate'])}]
        rule_status[name] = dict(status='blocked_observed_error' if values['disagreements'] or regressions else 'requires_independent_review',
                                 changed_prior_kinds=regressions, automatic_release=False)
    return dict(records=len(rows), reference_verdicts=dict(Counter(r['reference_verdict'] for r in rows)),
                evidence_states=dict(Counter(r['evidence_state'] for r in rows)), metrics=metrics,
                changed_prior_kinds=[r['review_id'] for r in changed], newly_assigned=new, rule_status=rule_status,
                human_validated=False, production_ocr=False,
                interval_note='95% Wilson intervals describe scored assignments in this balanced sample, not population precision. Unscored assignments and missing bodies are reported separately. No interval alone approves a rule.')


def evaluate(directory, output, *, freeze_path, reconciliation=None):
    directory, output = Path(directory).resolve(), Path(output).resolve()
    packet, frozen = verify_seal(directory, freeze_path=freeze_path, reconciliation=reconciliation)
    candidate = json.loads(Path(freeze_path).read_text())
    baseline = subprocess.run(['git', 'show', candidate['baseline_commit'] + ':' + COVER],
                              cwd=ROOT, capture_output=True, check=True).stdout
    if sha256(baseline).hexdigest() != candidate['development_summary']['baseline_parser_sha256']:
        raise ValueError('Baseline parser differs from frozen comparison')
    output.mkdir(parents=True, exist_ok=False)
    manifest = dict(packet_id=packet['packet_id'], label_freeze_sha256=file_digest(directory / 'label-freeze.json'),
                    candidate_freeze_sha256=file_digest(freeze_path), split=packet['split'], purpose=packet['purpose'],
                    environment=frozen['environment'], packet_directory=str(directory),
                    baseline_parser_sha256=sha256(baseline).hexdigest(), output_directory=str(output))
    # An interrupted held-out run leaves its marker and partial readings. Inspect
    # that evidence explicitly; do not silently rerun it in a fresh directory.
    if packet['split'] == 'held-out':
        write_new(directory / 'evaluation-started.json', manifest)
    write_new(output / 'manifest.json', manifest)
    baseline_path = output / 'baseline_document_cover.py'
    baseline_path.write_bytes(baseline)
    references = {r['review_id']: r for r in frozen['records']}

    def one(record):
        ref = references[record['review_id']]
        result = dict(review_id=record['review_id'], document_id=record['document_id'],
                      body_sha256=record['body_sha256'], evidence_state=record['state'],
                      reference_verdict=ref['verdict'], reference_kind=ref['reference_kind'])
        for mode in ['baseline', 'candidate']:
            if not record['pdf'] or record['state'] == 'eligibility_changed':
                result[mode] = dict(status='not_run', reason=record['state'])
            else:
                fingerprint = manifest['baseline_parser_sha256'] if mode == 'baseline' else frozen['environment']['reader_fingerprint']
                result[mode] = read_pdf(directory / record['pdf'], record['body_sha256'], fingerprint,
                                        baseline_path if mode == 'baseline' else None)
        return result

    rows = []
    with ThreadPoolExecutor(max_workers=3) as pool, (output / 'readings.jsonl').open('x') as stream:
        for row in pool.map(one, packet['records']):
            rows.append(row)
            stream.write(json.dumps(row) + '\n'); stream.flush()
    verify_seal(directory, freeze_path=freeze_path, reconciliation=reconciliation)
    if file_digest(directory / 'label-freeze.json') != manifest['label_freeze_sha256']:
        raise ValueError('Label freeze changed during evaluation')
    with (output / 'comparison.csv').open('x', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['review_id', 'document_id', 'evidence_state', 'reference_verdict', 'reference_kind',
                         'baseline_status', 'baseline_kind', 'baseline_error', 'candidate_status', 'candidate_kind', 'candidate_error'])
        for row in rows:
            writer.writerow([row[key] for key in ['review_id', 'document_id', 'evidence_state', 'reference_verdict', 'reference_kind']]
                            + [value for mode in ['baseline', 'candidate'] for value in
                               [row[mode]['status'], kind(row[mode]), row[mode].get('error_type', '')]])
    result = dict(summarize(rows), **manifest, readings_sha256=file_digest(output / 'readings.jsonl'),
                  comparison_sha256=file_digest(output / 'comparison.csv'), completed=True)
    write_new(output / 'summary.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['seal', 'evaluate', 'worker'])
    parser.add_argument('--packet', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--freeze', type=Path, default=HERE / 'content_rule_freeze.json')
    parser.add_argument('--reconciliation', type=Path)
    parser.add_argument('--pdf', type=Path)
    parser.add_argument('--expected-sha')
    parser.add_argument('--fingerprint')
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args()
    if args.action == 'worker':
        if not all([args.pdf, args.expected_sha, args.fingerprint]):
            parser.error('worker requires --pdf, --expected-sha and --fingerprint')
        print(json.dumps(worker(args.pdf, args.expected_sha, args.fingerprint, args.baseline)))
    else:
        if args.packet is None or args.action == 'evaluate' and args.output is None:
            parser.error('--packet is required; evaluate also requires --output')
        result = (seal(args.packet, freeze_path=args.freeze, reconciliation=args.reconciliation) if args.action == 'seal'
                  else evaluate(args.packet, args.output, freeze_path=args.freeze, reconciliation=args.reconciliation))
        print(json.dumps({k: v for k, v in result.items() if k not in {'records', 'environment'}}, indent=2))
